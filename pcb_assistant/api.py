import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .agents import validate_fact
from .cancellation import cancel_event, check_cancelled, JobCancelled
from .exports import artifact_files, export_zip
from .importers import MAX_UPLOAD, inspect_file
from .orchestrator import MANUAL_CHECKS, Orchestrator, gate_status, invalidate
from .provider import CompatibleProvider, ProviderSettings
from .schemas import *
from .storage import Conflict, Store, digest

BASE = Path(__file__).resolve().parent


class CreateProject(Schema):
    name: str = Field(min_length=1, max_length=200)
    brief: str = Field(min_length=1, max_length=20000)


class Mutation(Schema):
    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class RequirementsEdit(Mutation):
    values: Requirement
    brief: str | None = Field(default=None, min_length=1, max_length=20000)
    analyze_ai: bool = False


class ProposalDecision(Mutation):
    keys: list[str] = Field(min_length=1, max_length=12)
    accept: bool


class PartDecision(Mutation):
    refs: list[str] = Field(min_length=1, max_length=40)
    accept: bool


class JobRequest(Mutation):
    stage: Literal["plan", "circuit", "imports", "discover", "review", "requirements"]
    requirements: RequirementsEdit | None = None
    retry_downloads: bool = False


class GateApproval(Mutation):
    gate: Gate
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=3000)
    evidence_hash: str


class GateRevoke(Mutation):
    gate: Gate


class CircuitEdit(Mutation):
    circuit: CircuitResult


class ResearchEdit(Mutation):
    research: ResearchResult


class FactVerify(Mutation):
    reviewer: str = Field(min_length=1, max_length=200)


class CheckEdit(Mutation):
    gate: Gate
    key: str
    checked: bool
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=3000)


class Restore(Mutation):
    target_version: int = Field(ge=1)


class FileEdit(Mutation):
    active: bool


class SettingsEdit(Schema):
    mode: Literal["offline", "ai", "codex"]
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    effort: str = ""


def create_app(data_root: Path | None = None):
    app = FastAPI(title="PCB Workflow Studio", version="0.1.0")
    store = Store(data_root or Path(os.getenv("PCB_DATA_DIR", str(BASE.parent / "data"))))
    settings = ProviderSettings()
    token = secrets.token_urlsafe(32)
    ai_lock = threading.RLock()
    jobs = {}
    cancellations = {}
    jobs_lock = threading.Lock()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pcb-workflow")
    app.state.store, app.state.settings = store, settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not secrets.compare_digest(request.headers.get("x-pcb-token", ""), token):
                return JSONResponse({"detail": "Local session token missing; reload the app"}, status_code=403)
            if request.headers.get("origin") and request.headers["origin"] != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
        content_length = request.headers.get("content-length", "0")
        try:
            if int(content_length) > MAX_UPLOAD + 1024 * 1024:
                return JSONResponse({"detail": "Request exceeds 20 MB file limit"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid content length"}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def value_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing_handler(request, exc):
        return JSONResponse({"detail": "Project / file / version not found"}, status_code=404)

    def load_edit(project_id, version):
        if cancel_event.get() is None:
            with jobs_lock:
                if any(j["project_id"] == project_id and j["status"] in ("queued", "running") for j in jobs.values()):
                    raise ValueError("โปรเจกต์นี้กำลังทำงาน หยุดงานหรือรอให้เสร็จก่อนแก้ข้อมูล")
        p = store.get(project_id)
        if p.version != version:
            raise Conflict("โปรเจกต์มีการเปลี่ยนแปลง กรุณาโหลดใหม่")
        return p

    def output(p):
        return {"project": p.model_dump(mode="json"), "gates": gate_status(p)}

    @app.get("/api/bootstrap")
    def bootstrap():
        return {"token": token, "settings": settings.public(), "questions": QUESTIONS, "version": "0.1.0"}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "pcb-workflow-studio", "version": "0.1.0"}

    @app.put("/api/settings")
    def configure(body: SettingsEdit):
        with jobs_lock:
            if any(j["status"] in ("queued", "running") for j in jobs.values()):
                raise ValueError("มีงานกำลังทำงาน รอให้เสร็จก่อนเปลี่ยน model")
        if body.mode == "codex":
            from .provider import CodexCLIProvider
            settings.provider = CodexCLIProvider(body.model, body.effort, cwd=BASE.parent)
        else:
            settings.provider = CompatibleProvider(body.base_url, body.model, body.api_key, body.effort) if body.mode == "ai" else None
        return settings.public()

    @app.get("/api/projects")
    def list_projects():
        return store.list()

    @app.post("/api/projects", status_code=201)
    def create_project(body: CreateProject):
        if not body.name.strip() or not body.brief.strip():
            raise ValueError("กรุณาระบุชื่อโปรเจกต์และโจทย์")
        p = Project(name=body.name.strip(), brief=body.brief.strip())
        Orchestrator().requirements(p, Requirement())
        return output(store.save(p, 0, "สร้างโปรเจกต์"))

    @app.post("/api/demo", status_code=201)
    def create_demo():
        p = Project(name="MCU Sensor Board · 4-layer (ตัวอย่าง)", brief="บอร์ด MCU 4-layer มี USB-C, IMU, OLED, ปุ่มกด และไฟ 3.3V — โปรเจกต์ทดสอบซอฟต์แวร์ ไม่ใช่วงจรพร้อมผลิต")
        Orchestrator().requirements(p, Requirement(layers=4, extras="ปุ่มกด 1 ปุ่ม"))
        return output(store.save(p, 0, "สร้างตัวอย่าง; ยังไม่มีการอนุมัติใด ๆ"))

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str, version: int | None = None):
        return output(store.get(project_id, version))

    @app.put("/api/projects/{project_id}/requirements")
    def edit_requirements(project_id: str, body: RequirementsEdit):
        p = load_edit(project_id, body.version)
        if not body.analyze_ai and ((body.brief is not None and body.brief != p.brief) or body.values != p.requirements.values):
            # Recommendations were made for the previous brief/constraints.
            p.requirements.proposals = []
        if body.brief is not None:
            p.brief = body.brief
        with ai_lock:
            Orchestrator(settings.provider).requirements(p, body.values, body.analyze_ai)
        return output(store.save(p, body.version, body.reason))

    @app.post("/api/projects/{project_id}/requirements/decide")
    def decide_requirements(project_id: str, body: ProposalDecision):
        p = load_edit(project_id, body.version)
        proposals = {item.key: item for item in p.requirements.proposals if item.status == "pending"}
        if len(set(body.keys)) != len(body.keys) or any(key not in proposals for key in body.keys):
            raise ValueError("ข้อเสนอเปลี่ยนไปแล้ว กรุณาโหลดข้อมูลใหม่")
        values = p.requirements.values.model_dump()
        for key in body.keys:
            item = proposals[key]
            if body.accept:
                if values[key] not in (None, ""):
                    raise ValueError("มีค่าที่บันทึกไว้แล้ว กรุณาแก้ในรายละเอียดแทน")
                values[key] = item.value
            item.status = "accepted" if body.accept else "rejected"
        Orchestrator().requirements(p, Requirement.model_validate(values))
        return output(store.save(p, body.version, body.reason))

    def execute_stage(project_id, stage, body, progress=None):
        with ai_lock:
            p = load_edit(project_id, body.version)
            before = digest(p)
            orchestrator = Orchestrator(settings.provider, store, progress)
            try:
                check_cancelled()
                if getattr(body, "retry_downloads", False):
                    p.pipeline_cache = {k: v for k, v in p.pipeline_cache.items() if not k.startswith("download:")}
                if stage == "requirements":
                    if body.requirements is None:
                        raise ValueError("ต้องมีข้อมูล Requirements")
                    edit = body.requirements
                    # Commit the brief/values only when the analysis succeeds.
                    proposed = p.model_copy(deep=True)
                    if edit.brief is not None:
                        proposed.brief = edit.brief
                    try:
                        orchestrator.requirements(proposed, edit.values, True)
                    finally:
                        p.runs = proposed.runs
                    p = proposed
                else:
                    {"plan": orchestrator.plan, "circuit": orchestrator.regenerate_circuit,
                 "imports": orchestrator.imports, "discover": orchestrator.discover,
                     "review": orchestrator.ai_review}[stage](p)
            except ValueError as exc:
                if digest(p) != before:
                    p.pipeline_status = str(exc)
                    store.save(p, body.version, "เก็บผลขั้นตอนที่ทำสำเร็จและข้อมูลการเรียก: " + str(exc)[:200])
                raise
            return output(store.save(p, body.version, body.reason))

    @app.post("/api/projects/{project_id}/run/{stage}")
    def run(project_id: str, stage: Literal["plan", "circuit", "imports", "discover", "review"], body: Mutation):
        return execute_stage(project_id, stage, body)

    @app.post("/api/projects/{project_id}/parts/decide")
    def decide_parts(project_id: str, body: PartDecision):
        p = load_edit(project_id, body.version)
        if not p.discovery:
            raise ValueError("ค้นหาชิ้นส่วนก่อน")
        parts = {part.ref: part for part in p.discovery.parts}
        if any(ref not in parts for ref in body.refs):
            raise ValueError("Reference ไม่ตรงกับชุดชิ้นส่วน")
        target_status = "selected" if body.accept else "rejected"
        if all(parts[ref].status == target_status for ref in body.refs):
            return output(p)
        for ref in body.refs:
            parts[ref].status = "selected" if body.accept else "rejected"
        p.pipeline_cache = {}
        p.research, p.circuit, p.design_review = None, None, None
        invalidate(p, Gate.COMPONENTS)
        p.pipeline_status = "เลือกชิ้นส่วนแล้ว กดดาวน์โหลดเอกสารและสร้างร่าง" if all(part.status == "selected" for part in parts.values()) else "เลือกชุดให้ครบ หรือค้นหาทางเลือกสำหรับรุ่นที่ไม่เลือก"
        return output(store.save(p, body.version, body.reason))

    @app.post("/api/projects/{project_id}/jobs", status_code=202)
    def start_job(project_id: str, body: JobRequest):
        load_edit(project_id, body.version)
        with jobs_lock:
            if any(j["status"] in ("queued", "running") for j in jobs.values()):
                raise ValueError("มีงานกำลังทำอยู่ รอให้เสร็จก่อนเพื่อไม่เรียก AI ซ้ำ")
            job_id = uid()
            cancellations[job_id] = threading.Event()
            jobs[job_id] = {"id": job_id, "project_id": project_id, "stage": body.stage,
                            "status": "queued", "progress": "รอเริ่มงาน", "started_at": now()}
        def progress(text):
            check_cancelled()
            with jobs_lock:
                jobs[job_id]["progress"] = text
        def work():
            scope = cancel_event.set(cancellations[job_id])
            with jobs_lock:
                jobs[job_id]["status"] = "running"
            try:
                result = execute_stage(project_id, body.stage, body, progress)
                with jobs_lock:
                    jobs[job_id].update(status="done", result=result)
            except Exception as exc:
                with jobs_lock:
                    jobs[job_id].update(status="cancelled" if isinstance(exc, JobCancelled) else "error", error=str(exc) if isinstance(exc, ValueError) else "ขั้นตอนทำงานไม่สำเร็จ โปรดลองโหลดโปรเจกต์ใหม่")
            finally:
                cancel_event.reset(scope)
                with jobs_lock:
                    cancellations.pop(job_id, None)
        executor.submit(work)
        return {"id": job_id}

    @app.get("/api/jobs")
    def active_jobs():
        with jobs_lock:
            return [dict(j) for j in jobs.values() if j["status"] in ("queued", "running")]

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        with jobs_lock:
            if job_id not in jobs:
                raise KeyError(job_id)
            if job_id in cancellations:
                cancellations[job_id].set()
                jobs[job_id]["progress"] = "กำลังหยุด · รอการเชื่อมต่อปัจจุบันคืนการควบคุม"
            return dict(jobs[job_id])

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        with jobs_lock:
            if job_id not in jobs:
                raise KeyError(job_id)
            return dict(jobs[job_id])

    @app.post("/api/projects/{project_id}/approve")
    def approve(project_id: str, body: GateApproval):
        p = load_edit(project_id, body.version)
        Orchestrator().approve(p, body.gate, body.reviewer, body.note, body.evidence_hash)
        return output(store.save(p, body.version, f"อนุมัติ {body.gate.value}: {body.note}"))

    @app.put("/api/projects/{project_id}/circuit")
    def edit_circuit(project_id: str, body: CircuitEdit):
        p = load_edit(project_id, body.version)
        Orchestrator().circuit(p, body.circuit)
        return output(store.save(p, body.version, body.reason))

    @app.post("/api/projects/{project_id}/revoke")
    def revoke_gate(project_id: str, body: GateRevoke):
        p = load_edit(project_id, body.version)
        affected = set(GATES[GATES.index(body.gate):])
        p.approvals = [a for a in p.approvals if a.gate not in affected]
        p.manual_checks = [c for c in p.manual_checks if c.gate not in affected]
        return output(store.save(p, body.version, f"ถอนอนุมัติ {body.gate.value}: {body.reason}"))

    @app.put("/api/projects/{project_id}/research")
    def edit_research(project_id: str, body: ResearchEdit):
        p = load_edit(project_id, body.version)
        if not p.research:
            raise ValueError("รัน Research ก่อนเพิ่มข้อเท็จจริง")
        previous = {f.id: f for f in p.research.facts}
        if len({f.id for f in body.research.facts}) != len(body.research.facts):
            raise ValueError("Fact IDs ต้องไม่ซ้ำ")
        for fact in body.research.facts:
            validate_fact(fact, p.sources)
            old = previous.get(fact.id)
            if old and old.model_dump() == fact.model_dump():
                continue
            fact.status = "Inferred"
            fact.verified_by = ""
        p.research = body.research
        p.circuit = None
        p.design_review = None
        invalidate(p, Gate.COMPONENTS)
        return output(store.save(p, body.version, body.reason))

    @app.post("/api/projects/{project_id}/facts/{fact_id}/verify")
    def verify_fact(project_id: str, fact_id: str, body: FactVerify):
        p = load_edit(project_id, body.version)
        if not p.research or not body.reviewer.strip():
            raise ValueError("ต้องมี research และชื่อผู้ตรวจ")
        fact = next((f for f in p.research.facts if f.id == fact_id), None)
        if not fact:
            raise KeyError(fact_id)
        validate_fact(fact, p.sources)
        fact.status, fact.verified_by = "Confirmed", body.reviewer.strip()
        p.circuit, p.design_review = None, None
        invalidate(p, Gate.COMPONENTS)
        return output(store.save(p, body.version, body.reason))

    @app.post("/api/projects/{project_id}/files")
    def upload(project_id: str, version: int = Form(...), kind: str = Form(...), reason: str = Form(...),
               title: str = Form(""), revision: str = Form(""), url: str = Form(""), component_ref: str = Form(""), file: UploadFile = File(...)):
        p = load_edit(project_id, version)
        if not reason.strip():
            raise ValueError("ระบุเหตุผลการนำเข้า")
        content = file.file.read(MAX_UPLOAD + 1)
        item = inspect_file(file.filename or "upload", kind, content)
        if kind == "datasheet":
            if not title.strip() or not revision.strip():
                raise ValueError("Datasheet ต้องระบุชื่อเอกสารและเวอร์ชัน (unknown ได้ แต่ต้องตรวจต้นฉบับ)")
            part = next((part for part in p.discovery.parts if part.ref == component_ref), None) if p.discovery else None
            if component_ref and not part:
                raise ValueError("เลือกชิ้นส่วนที่ตรงกับเอกสารจากรายการปัจจุบัน")
            source = DatasheetSource(file_id=item.id, title=title, revision=revision, url=url,
                                    pages=item.summary.pop("pages"), sha256=item.sha256,
                                    component_refs=[component_ref] if part else [], part_number=part.part_number if part else "")
            p.sources.append(source)
            p.research, p.circuit, p.design_review = None, None, None
            invalidate(p, Gate.COMPONENTS)
        else:
            # One active version per kind/name; originals and old snapshots remain available.
            for old in p.files:
                if old.kind == kind and old.name == item.name:
                    old.active = False
            invalidate(p, Gate.SCHEMATIC)
            p.import_review, p.manufacturing = None, None
        store.put_original(p.id, content)
        p.files.append(item)
        return output(store.save(p, version, reason))

    @app.put("/api/projects/{project_id}/files/{file_id}")
    def activate_file(project_id: str, file_id: str, body: FileEdit):
        p = load_edit(project_id, body.version)
        item = next((f for f in p.files if f.id == file_id), None)
        if not item:
            raise KeyError(file_id)
        if item.kind == "datasheet":
            raise ValueError("Datasheet เป็นหลักฐานถาวร; ใช้แก้ research หรือย้อนเวอร์ชันเพื่อเปลี่ยนชุดหลักฐาน")
        item.active = body.active
        invalidate(p, Gate.SCHEMATIC)
        p.import_review, p.manufacturing = None, None
        return output(store.save(p, body.version, body.reason))

    @app.get("/api/projects/{project_id}/files/{file_id}")
    def download_original(project_id: str, file_id: str, preview: bool = False):
        p = store.get(project_id)
        item = next((f for f in p.files if f.id == file_id), None)
        if not item:
            raise KeyError(file_id)
        path = store.original_path(p.id, item.sha256)
        if preview and item.kind in ("pcb_image", "schematic_image"):
            media = "image/png" if path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
            return FileResponse(path, media_type=media)
        return FileResponse(path, media_type="application/octet-stream", filename=item.name)

    @app.put("/api/projects/{project_id}/checks")
    def set_check(project_id: str, body: CheckEdit):
        p = load_edit(project_id, body.version)
        if body.key not in MANUAL_CHECKS.get(body.gate, {}) or not body.reviewer.strip() or not body.note.strip():
            raise ValueError("Checklist key / ผู้ตรวจ / บันทึกไม่ถูกต้อง")
        # Save check, invalidate this gate and later approvals, retain other check entries.
        p.approvals = [a for a in p.approvals if GATES.index(a.gate) < GATES.index(body.gate)]
        p.manual_checks = [c for c in p.manual_checks if not (c.gate == body.gate and c.key == body.key)]
        p.manual_checks.append(ManualCheck(gate=body.gate, key=body.key, checked=body.checked, reviewer=body.reviewer, note=body.note))
        return output(store.save(p, body.version, body.reason))

    @app.get("/api/projects/{project_id}/history")
    def history(project_id: str):
        store.get(project_id)
        return store.history(project_id)

    @app.post("/api/projects/{project_id}/restore")
    def restore(project_id: str, body: Restore):
        load_edit(project_id, body.version)
        p = store.get(project_id, body.target_version)
        p.approvals, p.manual_checks = [], []
        return output(store.save(p, body.version, f"ย้อนกลับ v{body.target_version}; ต้องอนุมัติใหม่: {body.reason}"))

    @app.get("/api/projects/{project_id}/artifacts/{name}")
    def artifact(project_id: str, name: str, version: int | None = None):
        p = store.get(project_id, version)
        files = artifact_files(p)
        if name not in files:
            raise KeyError(name)
        media = "application/json" if name.endswith(".json") else "text/csv" if name.endswith(".csv") else "text/markdown"
        return Response(files[name], media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/projects/{project_id}/export")
    def export(project_id: str, version: int | None = None):
        p = store.get(project_id, version)
        return Response(export_zip(p, store), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="pcb-{p.id[:8]}-v{p.version}.zip"'})

    @app.get("/")
    def index():
        return FileResponse(BASE / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    return app
