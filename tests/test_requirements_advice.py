import pytest

from pcb_assistant.agents import RequirementsAgent
from pcb_assistant.provider import Usage
from pcb_assistant.schemas import Requirement, RequirementProposal, RequirementsAdvice


class Advisor:
    label = "test:advisor"
    last_usage = Usage(model="test", input_tokens=10, output_tokens=20)

    def __init__(self, advice):
        self.advice = advice
        self.context = None

    def generate(self, agent, instruction, context, schema):
        assert schema is RequirementsAdvice
        self.context = context
        return self.advice.model_copy(deep=True)


def test_advice_preserves_choices_and_requires_user_acceptance():
    provider = Advisor(RequirementsAdvice(proposals=[
        RequirementProposal(key="mcu", value="REPLACEMENT", reason="test"),
        RequirementProposal(key="usb", value="power_only", reason="from brief", basis="brief", quote="USB power only", status="accepted"),
        RequirementProposal(key="input_voltage", value=5, reason="guess", basis="brief", quote="absent quote"),
    ], questions=[f"Question {i}" for i in range(25)]))
    result = RequirementsAgent().run("USB power only", Requirement(mcu="USER-MCU"), provider)
    assert result.values.mcu == "USER-MCU" and result.values.usb == ""
    assert len(result.questions) == 3
    assert [p.key for p in result.proposals] == ["usb", "input_voltage"]
    assert all(p.status == "pending" for p in result.proposals)
    assert result.proposals[0].basis == "brief"
    assert result.proposals[1].basis == "recommendation"


@pytest.mark.parametrize("key,value", [("layers", 100), ("usb", "invalid"), ("approvals", "yes"), ("mcu", "")])
def test_invalid_recommendations_are_rejected(key, value):
    with pytest.raises(ValueError):
        RequirementProposal(key=key, value=value, reason="test")


def test_accept_reject_and_persistence(client, requirement):
    provider = Advisor(RequirementsAdvice(proposals=[
        RequirementProposal(key=k, value=getattr(requirement, k), reason="Draft software fixture")
        for k in Requirement.model_fields if k not in ("extras", "clarifications")
    ]))
    client.app.state.settings.provider = provider
    project = client.post("/api/projects", json={"name": "Advisor test", "brief": "Help me choose"}).json()["project"]
    url = "/api/projects/" + project["id"]
    project = client.put(url+"/requirements", json={"version": project["version"], "reason": "recommend", "values": project["requirements"]["values"], "analyze_ai": True}).json()["project"]
    assert len(project["requirements"]["proposals"]) == 12
    assert not project["approvals"]
    version = project["version"]
    project = client.post(url+"/requirements/decide", json={"version": version, "reason": "no", "keys": ["mcu"], "accept": False}).json()["project"]
    assert project["requirements"]["values"]["mcu"] == ""
    assert project["requirements"]["proposals"][0]["status"] == "rejected"
    assert client.post(url+"/requirements/decide", json={"version": version, "reason": "stale", "keys": ["layers"], "accept": True}).status_code == 409
    assert client.post(url+"/requirements/decide", json={"version": project["version"], "reason": "no", "keys": ["mcu"], "accept": True}).status_code == 400
    keys = [p["key"] for p in project["requirements"]["proposals"] if p["status"] == "pending"]
    project = client.post(url+"/requirements/decide", json={"version": project["version"], "reason": "accept rest", "keys": keys, "accept": True}).json()["project"]
    assert project["requirements"]["values"]["layers"] == 4
    assert not project["approvals"]
    loaded = client.get(url).json()
    assert loaded["project"]["requirements"] == project["requirements"]
    assert loaded["gates"][0]["blockers"]  # MCU still needs a decision.
    project = client.put(url+"/requirements", json={"version": project["version"], "reason": "alternative", "values": project["requirements"]["values"], "analyze_ai": True}).json()["project"]
    assert provider.context["previous_proposals"][0]["status"] == "rejected"
    project = client.post(url+"/requirements/decide", json={"version": project["version"], "reason": "accept", "keys": ["mcu"], "accept": True}).json()["project"]
    assert not client.get(url).json()["gates"][0]["blockers"]
    assert not project["approvals"]


def test_editing_brief_discards_stale_proposals(client):
    from pcb_assistant.schemas import Project, RequirementsResult
    p = Project(name="stale", brief="first", requirements=RequirementsResult(proposals=[RequirementProposal(key="layers", value=4, reason="test")]))
    p = client.app.state.store.save(p, 0, "fixture")
    url = "/api/projects/"+p.id
    result = client.put(url+"/requirements", json={"version": p.version, "reason": "new brief", "brief": "different project", "values": p.requirements.values.model_dump()})
    assert result.status_code == 200
    assert not result.json()["project"]["requirements"]["proposals"]
