import json
import socket
import threading
import time

import pytest

from pcb_assistant.agents import CircuitBOMAgent, DatasheetResearchAgent, PartsDiscoveryAgent, ReviewAgent, enforce_circuit_evidence, ground_draft
from pcb_assistant.orchestrator import Orchestrator, evidence_hash, gate_blockers
from pcb_assistant.provider import Usage
from pcb_assistant.schemas import *
from pcb_assistant.exports import usage_summary
from pcb_assistant.web_research import public_target, acquire_sources


def candidate(**changes):
    return PartCandidate(**dict(dict(ref="U1", part_number="TEST-MCU", manufacturer="TEST", role="MCU",
        package="TEST-PACKAGE", product_url="https://example.com/part", datasheet_url="https://example.com/doc.pdf",
        rationale="software fixture"), **changes))


def test_research_prefers_pin_table_and_diverse_sections_over_repeated_mentions(requirement):
    source = DatasheetSource(file_id="fixture", title="TEST", revision="TEST", sha256="a"*64,
        pages={1: "Contents\nPin definitions\nRecommended operating conditions\nFootprint",
               2: "Boot configuration\n" + "strapping pin " * 700,
               3: "Pin definitions\nName No. Type Function\nVDD 1 Power\nGND 2 Ground",
               4: "Recommended operating conditions\n3.0 to 3.6 V",
               5: "Package dimensions\nTEST footprint",
               6: "Typical application\nTEST decoupling"})
    captured = {}
    class CaptureProvider:
        def generate(self, agent, instruction, context, schema):
            captured.update(context)
            return ResearchResult()
    DatasheetResearchAgent().run(requirement, [source], CaptureProvider())
    pages = captured["pages"]
    assert [p["page"] for p in pages[:4]] == [3, 4, 5, 6]
    assert 1 not in [p["page"] for p in pages]
    assert all(len(p["text"]) <= 3500 for p in pages)
    assert sum(len(p["text"]) for p in pages) <= 14000


def test_missing_url_does_not_bind_unrelated_uploaded_document():
    source = DatasheetSource(file_id="unrelated", title="OTHER", revision="TEST", sha256="a"*64,
                            pages={1: "OTHER component datasheet"})
    p = Project(name="test", brief="test", sources=[source],
                discovery=PartsDiscovery(parts=[candidate(datasheet_url="", status="selected")]))
    issues = acquire_sources(p, None)
    assert len(issues) == 1
    assert p.sources[0].component_refs == []


class FakeProvider:
    supports_web_search = True
    label, model, effort = "test", "test", "low"

    def __init__(self, project=None):
        self.last_usage = Usage(calls=0)
        self.calls = []
        self.project = project

    def generate(self, agent, instruction, context, schema):
        self.calls.append(agent)
        self.last_usage = Usage(calls=1, input_tokens=10*len(self.calls), output_tokens=2,
                                duration_ms=100, search_count=1 if agent == "Parts Discovery Agent" else 0)
        if schema is PartsDiscovery:
            return PartsDiscovery(parts=[candidate()])
        if schema is ResearchResult:
            return self.project.research.model_copy(deep=True)
        if schema is CircuitResult:
            return self.project.circuit.model_copy(deep=True)
        return ReviewResult()


def test_no_false_research_call_when_there_are_no_sources(requirement):
    p=Project(name="test", brief="test")
    Orchestrator().requirements(p,requirement)
    Orchestrator().approve(p,Gate.REQUIREMENTS,"test","fixture",evidence_hash(p,Gate.REQUIREMENTS))
    provider=FakeProvider()
    def gen(agent, instruction, context, schema):
        provider.calls.append(agent)
        provider.last_usage=Usage(input_tokens=11,output_tokens=3)
        return CircuitBOMAgent().run(requirement,ResearchResult())
    provider.generate=gen
    Orchestrator(provider).plan(p)
    assert provider.calls == ["Circuit/BOM Agent"]
    assert p.runs[-2].calls == 0
    assert p.runs[-1].input_tokens == 11
    assert p.runs[-1].telemetry_version == 2


def test_cached_pipeline_does_not_repeat_ai(valid_project):
    provider=FakeProvider(valid_project.model_copy(deep=True))
    p=valid_project.model_copy(deep=True)
    p.pipeline_cache={}
    orchestrator=Orchestrator(provider)
    orchestrator.plan(p)
    assert provider.calls == ["Datasheet Research Agent", "Circuit/BOM Agent"]
    assert [r.input_tokens for r in p.runs[-2:]] == [10,20]
    calls=len(p.runs)
    orchestrator.plan(p)
    assert len(p.runs)==calls
    assert len(provider.calls)==2


def test_draft_pins_visible_but_gate_still_blocked(valid_project):
    p=valid_project
    for fact in p.research.facts:
        fact.status="Inferred"
        fact.verified_by=""
    enforce_circuit_evidence(p.circuit,p.research,allow_draft=True)
    assert any(pin.number for pin in p.circuit.pins)
    with pytest.raises(ValueError):
        enforce_circuit_evidence(p.circuit,p.research)
    p.design_review=ReviewAgent().run(p.requirements.values,p.research,p.circuit)
    assert gate_blockers(p,Gate.COMPONENTS)
    assert any(f.category=="connections" and f.severity=="error" for f in p.design_review.findings)


def test_search_requires_actual_search_events(requirement):
    provider=FakeProvider()
    assert PartsDiscoveryAgent().run(requirement,"test",provider).parts
    def no_search(*args):
        provider.last_usage=Usage(search_count=0)
        return PartsDiscovery(parts=[candidate()])
    provider.generate=no_search
    with pytest.raises(ValueError,match="ค้นเว็บจริง"):
        PartsDiscoveryAgent().run(requirement,"test",provider)


@pytest.mark.parametrize("url", ["file:///secret", "http://example.com/doc", "https://user:password@example.com/doc", "https://example.com:8443/doc"])
def test_download_rejects_unsafe_schemes_and_auth(url):
    with pytest.raises(ValueError): public_target(url)


@pytest.mark.parametrize("ip", ["127.0.0.1","10.1.1.2","169.254.169.254","::1"])
def test_download_blocks_private_dns(monkeypatch,ip):
    monkeypatch.setattr(socket,"getaddrinfo",lambda *a,**kw:[(None,None,None,None,(ip,443))])
    with pytest.raises(ValueError): public_target("https://example.com/doc")


def test_cached_pdf_not_downloaded_again(monkeypatch):
    p=Project(name="test",brief="test",discovery=PartsDiscovery(parts=[candidate(status="selected")]))
    p.sources=[DatasheetSource(file_id="fixture",title="test",revision="test",url="https://example.com/doc.pdf",sha256="a"*64)]
    def fail(*args): raise AssertionError("downloaded again")
    monkeypatch.setattr("pcb_assistant.web_research.fetch_pdf",fail)
    assert acquire_sources(p,None)==[]
    assert p.sources[0].component_refs==["U1"]


def test_selection_does_not_auto_approve(client,valid_project):
    valid_project.discovery=PartsDiscovery(parts=[candidate()])
    p=client.app.state.store.save(valid_project,0,"fixture")
    result=client.post(f"/api/projects/{p.id}/parts/decide",json={"version":p.version,"reason":"choose","refs":["U1"],"accept":True})
    assert result.status_code==200
    data=result.json()
    assert data["project"]["discovery"]["parts"][0]["status"]=="selected"
    assert not data["gates"][1]["approved"]


def test_failed_calls_retained_and_legacy_excluded(client,valid_project):
    provider=FakeProvider(valid_project)
    def fail(*args):
        provider.last_usage=Usage(input_tokens=100,output_tokens=5)
        raise ValueError("fixture error")
    provider.generate=fail
    client.app.state.settings.provider=provider
    p=client.app.state.store.save(valid_project,0,"fixture")
    response=client.post(f"/api/projects/{p.id}/run/circuit",json={"version":p.version,"reason":"test failure"})
    assert response.status_code==400
    saved=client.app.state.store.get(p.id)
    assert not saved.runs[-1].success
    assert saved.runs[-1].input_tokens==100
    saved.runs.append(AgentRun(agent="old",provider="old",input_hash="",output_hash="",calls=1,input_tokens=99999))
    summary=usage_summary(saved)
    assert summary["input_tokens"]==100
    assert summary["excluded_legacy_runs"]==1


def test_background_job_progress_and_duplicate_protection(client,valid_project):
    started, release = threading.Event(), threading.Event()
    provider=FakeProvider()
    original=provider.generate
    def delayed(*args):
        started.set()
        assert release.wait(3)
        return original(*args)
    provider.generate=delayed
    client.app.state.settings.provider=provider
    p=client.app.state.store.save(valid_project,0,"fixture")
    body={"version":p.version,"reason":"test","stage":"discover"}
    job=client.post(f"/api/projects/{p.id}/jobs",json=body)
    assert job.status_code==202
    try:
        assert started.wait(1)
        assert client.post(f"/api/projects/{p.id}/jobs",json=body).status_code==400
        status=client.get('/api/jobs/'+job.json()['id']).json()
        assert status["progress"]=="Parts Discovery Agent"
    finally:
        release.set()
    for _ in range(100):
        status=client.get('/api/jobs/'+job.json()['id']).json()
        if status["status"] not in ("queued","running"):
            break
        time.sleep(.01)
    assert status["status"]=="done"
    assert status["result"]["project"]["discovery"]["parts"]


def test_pdf_partial_failure_does_not_discard_sources(monkeypatch):
    p=Project(name="test",brief="test",discovery=PartsDiscovery(parts=[candidate(status="selected"),candidate(ref="U2",part_number="SECOND",datasheet_url="https://example.com/second.pdf",status="selected")]))
    def fetch(url):
        if url.endswith('second.pdf'): raise ValueError('HTTP 403')
        return b'%PDF-test',url
    monkeypatch.setattr('pcb_assistant.web_research.fetch_pdf',fetch)
    monkeypatch.setattr('pcb_assistant.web_research.inspect_file',lambda *a,**kw:FileVersion(name='test.pdf',kind='datasheet',sha256='a'*64,size=9,summary={'supported':True,'pages':{1:'text from page'}}))
    class FakeStore:
        def put_original(self,*args):pass
    issues=acquire_sources(p,FakeStore())
    assert len(p.sources)==1 and len(p.files)==1
    assert 'U2 SECOND' in issues[0]


def test_missing_physical_evidence_keeps_signal_table(valid_project):
    p=valid_project
    ground_draft(p.circuit,ResearchResult())
    enforce_circuit_evidence(p.circuit,ResearchResult(),allow_draft=True)
    assert p.circuit.connections
    assert all(not c.from_pin and not c.to_pin for c in p.circuit.connections)
    assert all(c.footprint=='UNRESOLVED' for c in p.circuit.components)
    assert all(c.voltage_min is None for c in p.circuit.components)
    assert p.circuit.unresolved


def test_pdf_empty_password_encryption_supported():
    import io
    from pypdf import PdfWriter
    from pcb_assistant.importers import extract_pdf
    writer=PdfWriter()
    writer.add_blank_page(width=100,height=100)
    writer.encrypt('',owner_password='fixture-owner',algorithm='AES-256')
    stream=io.BytesIO();writer.write(stream)
    result=extract_pdf(stream.getvalue(),research=True)
    assert result['page_count']==1
    assert not result['supported']  # Blank pages still aren't usable evidence.
