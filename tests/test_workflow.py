import io
import json
import zipfile

import pytest

from pcb_assistant.agents import CircuitBOMAgent, ReviewAgent, enforce_circuit_evidence, validate_fact
from pcb_assistant.exports import artifact_files, csv_text, export_zip
from pcb_assistant.importers import inspect_file
from pcb_assistant.orchestrator import MANUAL_CHECKS, Orchestrator, approved, evidence_hash, gate_blockers, invalidate
from pcb_assistant.schemas import *
from pcb_assistant.storage import Conflict, Store


def approve(p, gate):
    Orchestrator().approve(p,gate,"Automated test","Synthetic fixture, no hardware approval",evidence_hash(p,gate))


def test_missing_requirements_cannot_select_parts():
    p=Project(name="Test",brief="4-layer board")
    o=Orchestrator(); o.requirements(p,Requirement())
    assert p.requirements.values.layers==4
    assert len(p.requirements.questions)==11
    with pytest.raises(ValueError): approve(p,Gate.REQUIREMENTS)
    with pytest.raises(ValueError): o.plan(p)
    with pytest.raises(ValueError): CircuitBOMAgent().run(Requirement(),ResearchResult())


def test_offline_mvp_outputs_and_gate_blocks(requirement):
    p=Project(name="MCU 4-layer",brief="MCU sensor board 4-layer")
    o=Orchestrator();o.requirements(p,requirement);approve(p,Gate.REQUIREMENTS);o.plan(p)
    assert p.circuit.bom and p.circuit.connections
    assert all(not c.from_pin and not c.to_pin for c in p.circuit.connections)
    assert all(c.status=="Unresolved" for c in p.circuit.connections)
    with pytest.raises(ValueError):approve(p,Gate.COMPONENTS)
    artifacts=artifact_files(p)
    assert {"bom.csv","pin_connections.csv","requirements.md","project.json","approvals.json"}<=artifacts.keys()
    assert "DRAFT" in artifacts["requirements.md"]
    assert "UNRESOLVED" in artifacts["bom.csv"]


def test_sequential_gates_and_requirement_invalidation(valid_project):
    p=valid_project
    with pytest.raises(ValueError):approve(p,Gate.CONNECTIONS)
    approve(p,Gate.COMPONENTS);approve(p,Gate.CONNECTIONS)
    assert approved(p,Gate.CONNECTIONS)
    values=p.requirements.values.model_copy(update={"max_current_ma":200})
    Orchestrator().requirements(p,values)
    assert not p.approvals and p.circuit is None and p.research is None


def test_stale_evidence_hash_and_critical_cannot_be_waived(valid_project):
    p=valid_project
    with pytest.raises(ValueError):Orchestrator().approve(p,Gate.COMPONENTS,"Human","note","stale")
    p.design_review.findings.append(ReviewFinding(severity="critical",category="connections",message="short"))
    with pytest.raises(ValueError):approve(p,Gate.COMPONENTS)


def test_unverified_and_wrong_endpoint_rejected(valid_project):
    p=valid_project
    c=p.circuit.model_copy(deep=True)
    c.connections[0].from_pin="99"
    with pytest.raises(ValueError):enforce_circuit_evidence(c,p.research)
    c=p.circuit.model_copy(deep=True)
    c.connections[0].from_signal="WRONG"
    with pytest.raises(ValueError):enforce_circuit_evidence(c,p.research)
    research=p.research.model_copy(deep=True)
    for fact in research.facts:fact.status="Inferred"
    with pytest.raises(ValueError):enforce_circuit_evidence(p.circuit,research)


def test_citation_must_exist_and_match(valid_project):
    p=valid_project
    fact=p.research.facts[0].model_copy(deep=True)
    validate_fact(fact,p.sources)
    fact.page=200
    with pytest.raises(ValueError):validate_fact(fact,p.sources)
    fact.page=1;fact.quote="Imagined datasheet statement"
    with pytest.raises(ValueError):validate_fact(fact,p.sources)


def test_cross_net_short_and_voltage_conflict(valid_project):
    p=valid_project
    c=p.circuit.model_copy(deep=True)
    c.connections[1].to_pin="1"
    c.nets[0].voltage=5
    report=ReviewAgent().run(p.requirements.values,p.research,c)
    assert sum(f.severity=="critical" for f in report.findings)>=2


def test_immutable_versions_and_optimistic_concurrency(tmp_path,valid_project):
    store=Store(tmp_path)
    first=store.save(valid_project,0,"initial")
    second=first.model_copy(deep=True);second.name="Edited"
    second=store.save(second,1,"rename")
    assert store.get(first.id,1).name!=second.name
    with pytest.raises(Conflict):store.save(first,1,"stale write")
    assert len(store.history(first.id))==2
    sha=store.put_original(first.id,b"original")
    assert store.original_path(first.id,sha).read_bytes()==b"original"
    with pytest.raises(ValueError):store.original_path("../bad",sha)


def test_csv_formula_injection():
    text=csv_text(["value"],[["=1+1"],["  @SUM(1,2)"],["plain"]])
    assert "'=1+1" in text and "'  @SUM" in text and "plain" in text


def test_export_detects_modified_original(tmp_path,valid_project):
    store=Store(tmp_path)
    p=store.save(valid_project,0,"fixture")
    sha=store.put_original(p.id,b"original")
    p.files.append(FileVersion(name="original.txt",kind="other",sha256=sha,size=8))
    store.original_path(p.id,sha).write_bytes(b"changed")
    with pytest.raises(ValueError,match="modified"):
        export_zip(p,store)


def test_missing_pin_assignment_and_sensor_are_errors(valid_project):
    p=valid_project
    p.circuit.pins=[]
    p.requirements.values.sensor="SENSOR-TEST"
    result=ReviewAgent().run(p.requirements.values,p.research,p.circuit)
    assert any(f.category=="components" and f.severity=="error" for f in result.findings)
    assert any(f.category=="connections" and f.severity=="error" for f in result.findings)


def test_full_synthetic_release_requires_manual_checks(valid_project):
    p=valid_project;approve(p,Gate.COMPONENTS);approve(p,Gate.CONNECTIONS)
    netlist={"nets":[{"name":"VMAIN","nodes":[{"ref":"J1","pin":"1"},{"ref":"U1","pin":"1"}]},{"name":"GND","nodes":[{"ref":"J1","pin":"2"},{"ref":"U1","pin":"2"}]}]}
    drc={"completed":True,"tool":"Synthetic TEST","revision":"1","issues":[]}
    bom=b"Designator,Quantity,Manufacturer Part,Footprint\nU1,1,TEST-MCU,TEST-PACKAGE\nJ1,1,TEST-INPUT,TEST-CONNECTOR\n"
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,"w") as z:
        for ext in ["gtl","gbl","g1","g2","gts","gbs","gko"]:z.writestr("test."+ext,"%FSLAX24Y24*%\nM02*")
        z.writestr("test.drl","M48\nM30")
    for name,kind,data in [("bom.csv","bom",bom),("net.json","netlist",json.dumps(netlist).encode()),("drc.json","drc",json.dumps(drc).encode()),("pcb.png","pcb_image",b"\x89PNG\r\n\x1a\nTEST"),("sch.json","easyeda",b'{"shape":[]}'),("board.zip","gerber",archive.getvalue())]:
        p.files.append(inspect_file(name,kind,data))
    Orchestrator().imports(p)
    for gate in (Gate.SCHEMATIC,Gate.PCB,Gate.RELEASE):
        assert gate_blockers(p,gate)
        for key in MANUAL_CHECKS[gate]:p.manual_checks.append(ManualCheck(gate=gate,key=key,checked=True,reviewer="Automated test",note="Synthetic fixture only"))
        assert not gate_blockers(p,gate),gate_blockers(p,gate)
        approve(p,gate)
    assert approved(p,Gate.RELEASE)
    assert "HUMAN-APPROVED RELEASE" in artifact_files(p)["requirements.md"]
    invalidate(p,Gate.SCHEMATIC)
    assert not approved(p,Gate.RELEASE)
    assert approved(p,Gate.CONNECTIONS)
