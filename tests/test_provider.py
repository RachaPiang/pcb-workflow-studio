import json
import os

import httpx
import pytest

from pcb_assistant.provider import CompatibleProvider, CodexCLIProvider, ProviderError
from pcb_assistant.schemas import ResearchResult
from pcb_assistant.provider import output_schema, parse_output
from pcb_assistant.schemas import RequirementsAdvice


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop installation")
def test_codex_finds_desktop_binary_without_path(monkeypatch, tmp_path):
    binary = tmp_path / "OpenAI" / "Codex" / "bin" / "version" / "codex.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"fixture")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("pcb_assistant.provider.shutil.which", lambda name: None)
    assert CodexCLIProvider()._resolve_executable() == str(binary)


def test_codex_preserves_explicit_executable():
    assert CodexCLIProvider(executable="custom-codex")._resolve_executable() == "custom-codex"


def test_codex_stage_timeouts_are_long_but_bounded(monkeypatch):
    monkeypatch.delenv("PCB_CODEX_TIMEOUT_SEARCH", raising=False)
    monkeypatch.delenv("PCB_CODEX_TIMEOUT_STAGE", raising=False)
    provider = CodexCLIProvider()
    assert provider._timeout_seconds(True) == 420
    assert provider._timeout_seconds(False) == 300
    monkeypatch.setenv("PCB_CODEX_TIMEOUT_STAGE", "9999")
    assert provider._timeout_seconds(False) == 900
    monkeypatch.setenv("PCB_CODEX_TIMEOUT_SEARCH", "bad")
    assert provider._timeout_seconds(True) == 420


def test_compatible_provider_contract_and_schema(monkeypatch):
    real=httpx.Client
    captured={}
    def respond(request):
        captured.update(json.loads(request.content))
        assert request.headers["authorization"]=="Bearer test-key"
        return httpx.Response(200,json={"choices":[{"message":{"content":'{"facts":[],"unresolved":["missing source"]}'}}]})
    monkeypatch.setattr(httpx,"Client",lambda **kw:real(transport=httpx.MockTransport(respond),**kw))
    p=CompatibleProvider("http://localhost:11434/v1","test-model","test-key")
    result=p.generate("Research","Extract evidence",{"pages":[]},ResearchResult)
    assert result.unresolved==["missing source"]
    assert len(captured["messages"])==2 and "Never approve a gate" in captured["messages"][0]["content"]


@pytest.mark.parametrize("payload",[{}, {"choices":[{"message":{"content":None}}]}, {"choices":[{"message":{"content":"not json"}}]}, {"choices":[{"message":{"content":'{"approved":true}'}}]}])
def test_malformed_provider_response_fails_closed(monkeypatch,payload):
    real=httpx.Client
    monkeypatch.setattr(httpx,"Client",lambda **kw:real(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=payload)),**kw))
    with pytest.raises(ProviderError):CompatibleProvider("http://localhost/v1","test").generate("test","test",{},ResearchResult)


def test_provider_http_error_does_not_expose_response_or_key(monkeypatch):
    real=httpx.Client
    monkeypatch.setattr(httpx,"Client",lambda **kw:real(transport=httpx.MockTransport(lambda req:httpx.Response(401,text="secret key echoed")),**kw))
    with pytest.raises(ProviderError) as error:CompatibleProvider("http://localhost/v1","test","secret").generate("test","test",{},ResearchResult)
    assert "secret" not in str(error.value)


def test_codex_provider_uses_read_only_ephemeral_cli(monkeypatch, tmp_path):
    calls = {}
    def fake_run(args, **kwargs):
        calls["args"], calls["kwargs"] = args, kwargs
        with open(args[args.index("--output-schema") + 1], encoding="utf-8") as stream:
            spec = json.load(stream)
        assert spec["required"] == list(spec["properties"])
        assert spec["additionalProperties"] is False
        assert kwargs["encoding"] == "utf-8"
        output = args[args.index("-o") + 1]
        with open(output, "w", encoding="utf-8") as stream:
            stream.write('{"facts":[],"unresolved":["synthetic"]}')
        return type("Completed", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr("pcb_assistant.provider.subprocess.run", fake_run)
    result = CodexCLIProvider(cwd=tmp_path).generate("Research", "Extract", {"pages": []}, ResearchResult)
    assert result.unresolved == ["synthetic"]
    assert "--ephemeral" in calls["args"] and "-s" in calls["args"] and calls["args"][calls["args"].index("-s") + 1] == "read-only"
    assert "--skip-git-repo-check" in calls["args"] and calls["kwargs"]["cwd"] == tmp_path
    assert calls["kwargs"]["env"]["CODEX_HOME"].endswith(".codex")
    assert "auth.json" not in calls["kwargs"]["input"]


def test_codex_provider_resolves_only_configured_model(monkeypatch, tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('model = "test-codex-model"\napi_key = "must-not-be-read"\n', encoding="utf-8")
    monkeypatch.setattr("pcb_assistant.provider.Path.home", lambda: tmp_path)
    provider = CodexCLIProvider()
    assert provider.model == "test-codex-model"
    assert "api_key" not in provider.label


@pytest.mark.parametrize("wrapped", [
    '{"facts":[],"unresolved":["ต้องตรวจ"]}',
    '\ufeff{"facts":[],"unresolved":["ต้องตรวจ"]}',
    '```json\n{"facts":[],"unresolved":["ต้องตรวจ"]}\n```',
    'คำตอบ: {"facts":[],"unresolved":["ต้องตรวจ"]} จบ',
])
def test_codex_output_wrappers(wrapped):
    assert parse_output(wrapped, ResearchResult).unresolved == ["ต้องตรวจ"]


@pytest.mark.parametrize("bad", ['not json', '{"facts":', '{} {}', '{"approved":true}', '{"facts":"private-sensitive-text"}'])
def test_codex_bad_output_is_rejected_without_leaking_data(bad):
    with pytest.raises(ProviderError) as exc:
        parse_output(bad, ResearchResult)
    assert "private-sensitive-text" not in str(exc.value)


def test_advice_wire_schema_describes_valid_values_for_each_key():
    spec = output_schema(RequirementsAdvice)
    variants = spec["$defs"]["RequirementProposal"]["anyOf"]
    props = {v["properties"]["key"]["enum"][0]: v["properties"] for v in variants}
    assert props["layers"]["value"]["type"] == "integer"
    assert props["layers"]["value"]["maximum"] == 32
    assert props["usb"]["value"]["enum"] == ["power_only", "data", "none"]
    assert props["assembly"]["value"]["enum"] == ["hand", "smt", "mixed"]
    assert props["mcu"]["status"]["enum"] == ["pending"]
    assert all(v["required"] == list(v["properties"]) for v in variants)
    assert '"default"' not in json.dumps(spec)


def test_advice_still_rejects_incorrect_engineering_values():
    with pytest.raises(ProviderError, match="proposals.0"):
        parse_output(json.dumps({"proposals":[{"key":"layers","value":100,"reason":"test"}]}), RequirementsAdvice)
