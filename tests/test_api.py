import io
import json
import zipfile

from pcb_assistant.schemas import Gate


def create(client):
    response=client.post("/api/projects",json={"name":"MCU Sensor Board 4-layer","brief":"4-layer MCU with IMU, OLED, USB-C and buttons"})
    assert response.status_code==201
    return response.json()


def test_create_resume_approve_export_and_revision_conflict(client,requirement):
    d=create(client);p=d["project"];url="/api/projects/"+p["id"]
    assert client.post(url+"/run/plan",json={"version":p["version"],"reason":"test"}).status_code==400
    d=client.put(url+"/requirements",json={"version":p["version"],"reason":"test answers","values":requirement.model_dump()}).json();p=d["project"]
    response=client.post(url+"/approve",json={"version":p["version"],"reason":"test","gate":"requirements","reviewer":"Automated test","note":"Software fixture only","evidence_hash":d["gates"][0]["evidence_hash"]})
    assert response.status_code==200
    old=p["version"];p=response.json()["project"]
    response=client.post(url+"/run/plan",json={"version":p["version"],"reason":"offline smoke"})
    assert response.status_code==200 and response.json()["project"]["circuit"]["bom"]
    assert client.post(url+"/run/plan",json={"version":old,"reason":"stale"}).status_code==409
    resumed=client.get(url).json()["project"]
    assert resumed["circuit"]["connections"]
    result=client.get(url+"/export")
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert "pin_connections.csv" in archive.namelist()
        saved=json.loads(archive.read("project.json"))
        assert saved["version"]==resumed["version"]
    restored=client.post(url+"/restore",json={"version":resumed["version"],"target_version":1,"reason":"restore test"}).json()["project"]
    assert not restored["approvals"] and restored["version"]>resumed["version"]
    assert client.get(url+"?version=1").json()["project"]["version"]==1


def test_csrf_host_and_origin_guards(client):
    token=client.headers.pop("X-PCB-Token")
    assert client.post("/api/demo").status_code==403
    client.headers["X-PCB-Token"]=token
    assert client.post("/api/demo",headers={"Origin":"https://evil.example"}).status_code==403
    assert client.get("/api/bootstrap",headers={"Host":"evil.example"}).status_code==400
    assert client.get("/").status_code==200


def test_invalid_json_and_upload_versions(client):
    d=create(client);p=d["project"];url="/api/projects/"+p["id"]
    response=client.post(url+"/files",data={"version":p["version"],"kind":"easyeda","reason":"source"},files={"file":("board.json",b'{"shape":[]}',"application/json")})
    assert response.status_code==200
    updated=response.json()["project"];file=updated["files"][0]
    original=client.get(url+"/files/"+file["id"])
    assert original.content==b'{"shape":[]}'
    assert original.headers["content-type"]=="application/octet-stream"
    assert client.post(url+"/files",data={"version":p["version"],"kind":"bom","reason":"stale"},files={"file":("bom.csv",b"x", "text/csv")}).status_code==409
    invalid=client.post(url+"/files",data={"version":updated["version"],"kind":"easyeda","reason":"invalid"},files={"file":("bad.json",b"bad", "application/json")})
    assert invalid.status_code==400
    assert client.get(url).json()["project"]["version"]==updated["version"]


def test_demo_never_auto_approves(client):
    response=client.post("/api/demo")
    p=response.json()["project"]
    assert not p["approvals"] and p["circuit"] is None and p["requirements"]["values"]["layers"]==4


def test_settings_never_return_or_persist_keys(client):
    response=client.put("/api/settings",json={"mode":"ai","base_url":"http://localhost:11434/v1","model":"test","api_key":"secret-synthetic-token"})
    assert response.status_code==200
    assert "secret-synthetic-token" not in response.text
    d=create(client)
    assert "secret-synthetic-token" not in client.get("/api/projects/"+d["project"]["id"]+"/export").text
    assert client.put("/api/settings",json={"mode":"ai","base_url":"http://external.example/v1","model":"test"}).status_code==400


def test_codex_setting_does_not_request_or_store_an_api_key(client):
    response=client.put("/api/settings",json={"mode":"codex","model":""})
    assert response.status_code==200
    data=response.json()
    assert data["mode"]=="codex" and data["has_key"] is False


def test_research_cannot_self_confirm(client,valid_project):
    p=client.app.state.store.save(valid_project,0,"synthetic")
    url="/api/projects/"+p.id
    research=p.research.model_dump()
    research["facts"][0]["claim"]="Changed claim"
    research["facts"][0]["verified_by"]="FORGED"
    response=client.put(url+"/research",json={"version":p.version,"reason":"edit","research":research})
    assert response.status_code==200
    changed=response.json()["project"]["research"]["facts"][0]
    assert changed["status"]=="Inferred" and not changed["verified_by"]


def test_revoke_preserves_draft_but_clears_approvals(client,valid_project):
    p=client.app.state.store.save(valid_project,0,"synthetic")
    response=client.post(f"/api/projects/{p.id}/revoke",json={"version":p.version,"gate":"requirements","reason":"End software test"})
    assert response.status_code==200
    result=response.json()
    assert not result["project"]["approvals"]
    assert result["project"]["circuit"]
    assert all(not g["approved"] for g in result["gates"])
    assert client.get(f"/api/projects/{p.id}?version=1").json()["project"]["approvals"]
