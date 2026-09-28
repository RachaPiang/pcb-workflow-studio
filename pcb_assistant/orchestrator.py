from .agents import (CircuitBOMAgent, DatasheetResearchAgent, ManufacturingTestAgent,
                     RequirementsAgent, ReviewAgent, PartsDiscoveryAgent, enforce_circuit_evidence, missing, validate_fact)
from .importers import review_imports
from .schemas import *
from .storage import digest
from .provider import Usage


MANUAL_CHECKS = {
    Gate.SCHEMATIC: {"erc": "ตรวจ ERC และ schematic ของไฟล์รุ่นนี้แล้ว", "pinout": "เทียบขาและ package กับ datasheet ต้นฉบับแล้ว", "power": "ตรวจ power tree, decoupling, boot/reset และระดับ logic แล้ว"},
    Gate.PCB: {"layout": "ตรวจ routing, return path, clearance และตำแหน่งชิ้นส่วนใน EasyEDA แล้ว", "stackup": "ยืนยัน stackup และ design rules กับโรงงานแล้ว", "drc_revision": "DRC ที่นำเข้าเป็นผลจาก PCB รุ่นเดียวกับภาพและไฟล์ผลิต"},
    Gate.RELEASE: {"gerber_viewer": "เปิด Gerber/drill ใน viewer และตรวจ geometry/alignment แล้ว", "package": "ตรวจไฟล์ผลิต BOM และ CPL/placement (ถ้าประกอบ SMT) ครบแล้ว", "bringup": "ตรวจ test points, tolerances และ current limit สำหรับ bring-up แล้ว"},
}


def invalidate(project: Project, start: Gate):
    affected = set(GATES[GATES.index(start):])
    project.approvals = [a for a in project.approvals if a.gate not in affected]
    project.manual_checks = [c for c in project.manual_checks if c.gate not in affected]
    if start in (Gate.REQUIREMENTS, Gate.COMPONENTS, Gate.CONNECTIONS):
        project.import_review = None
        project.manufacturing = None


def evidence_hash(p: Project, gate: Gate):
    req = p.requirements.model_dump()
    research = p.research.model_dump() if p.research else None
    circuit = p.circuit.model_dump() if p.circuit else None
    design = p.design_review.model_dump() if p.design_review else None
    if gate == Gate.REQUIREMENTS:
        return digest({"brief": p.brief, "requirements": req})
    values = {"requirements": req, "research": research}
    if gate == Gate.COMPONENTS:
        values.update(circuit={k: circuit[k] for k in ("components", "bom")} if circuit else None,
                      review=[f for f in (design or {}).get("findings", []) if f["category"] in ("components", "voltage") or f["severity"] == "critical"])
        return digest(values)
    values.update(circuit=circuit, design_review=design)
    if gate == Gate.CONNECTIONS:
        return digest(values)
    kinds = {"easyeda", "bom", "netlist", "schematic_image"}
    if gate in (Gate.PCB, Gate.RELEASE):
        kinds |= {"pcb_image", "drc"}
    if gate == Gate.RELEASE:
        kinds |= {"gerber", "other"}
    values["files"] = [f.model_dump() for f in p.files if f.active and f.kind in kinds]
    values["import_review"] = p.import_review.model_dump() if p.import_review else None
    values["checks"] = [c.model_dump() for c in p.manual_checks if c.gate in GATES[:GATES.index(gate)+1]]
    if gate == Gate.RELEASE:
        values["manufacturing"] = p.manufacturing.model_dump() if p.manufacturing else None
    return digest(values)


def approved(p: Project, gate: Gate):
    for required in GATES[:GATES.index(gate)+1]:
        if not any(a.gate == required and a.evidence_hash == evidence_hash(p, required) for a in p.approvals):
            return False
    return True


def gate_blockers(p: Project, gate: Gate) -> list[str]:
    reasons = []
    previous = GATES[GATES.index(gate)-1] if gate != Gate.REQUIREMENTS else None
    if previous and not approved(p, previous):
        reasons.append(f"ต้องอนุมัติ {previous.value} ก่อน")
    if gate == Gate.REQUIREMENTS:
        reasons += [QUESTIONS[k] for k in missing(p.requirements.values)]
        reasons += [q for q in p.requirements.questions if q not in reasons]
        return reasons
    if not p.circuit or not p.research or not p.design_review:
        reasons.append("ต้องรัน Research → Circuit/BOM → Review ก่อน")
        return reasons
    findings = list(p.design_review.findings)
    if gate in (Gate.SCHEMATIC, Gate.PCB, Gate.RELEASE) and p.import_review:
        findings += p.import_review.findings
    if gate == Gate.RELEASE and p.manufacturing:
        findings += p.manufacturing.findings
    categories = {"components", "voltage"} if gate == Gate.COMPONENTS else None
    for f in findings:
        # A critical anywhere in the applicable review cannot be waived.
        relevant = categories is None or f.category in categories
        if gate == Gate.SCHEMATIC and f.category in ("pcb", "release"):
            relevant = False
        if gate == Gate.PCB and f.category == "release":
            relevant = False
        if f.severity == "critical" or (f.severity == "error" and relevant):
            reasons.append(f"{f.severity.upper()}: {f.message}" + (" [" + ", ".join(f.affected) + "]" if f.affected else ""))
    if gate != Gate.COMPONENTS and (p.circuit.unresolved or p.research.unresolved):
        reasons.append("ยังมี Unresolved questions ใน research/circuit; แก้ไขพร้อมหลักฐานก่อนอนุมัติ connections")
    if gate in MANUAL_CHECKS:
        if p.import_review is None:
            reasons.append("ต้องรันตรวจไฟล์นำเข้าในเวอร์ชันปัจจุบัน")
        active = [f for f in p.files if f.active]
        required = {Gate.SCHEMATIC: {"bom", "netlist"}, Gate.PCB: {"drc", "pcb_image"}, Gate.RELEASE: {"gerber"}}[gate]
        for kind in required:
            if not any(f.kind == kind and (f.summary.get("supported") or kind == "pcb_image") for f in active):
                reasons.append(f"ขาดไฟล์ {kind} ที่อ่านได้")
        if gate == Gate.SCHEMATIC and not any(f.kind in ("easyeda", "schematic_image") for f in active):
            reasons.append("ต้องมี EasyEDA source หรือภาพ schematic สำหรับ manual review")
        for key, label in MANUAL_CHECKS[gate].items():
            if not any(c.gate == gate and c.key == key and c.checked for c in p.manual_checks):
                reasons.append(label)
    if gate == Gate.RELEASE and not p.manufacturing:
        reasons.append("ยังไม่มี Manufacturing checklist / bring-up plan")
    return list(dict.fromkeys(reasons))


def gate_status(p):
    return [{"gate": g.value, "approved": approved(p, g), "blockers": gate_blockers(p, g),
             "evidence_hash": evidence_hash(p, g), "manual_checks": MANUAL_CHECKS.get(g, {})} for g in GATES]


class Orchestrator:
    def __init__(self, provider=None, store=None, progress=None):
        self.provider = provider
        self.store = store
        self.progress = progress or (lambda text: None)

    def step(self, p, agent, inputs, callback, ai=True):
        from .cancellation import check_cancelled
        check_cancelled()
        use_ai = bool(self.provider and ai)
        if use_ai:
            self.provider.last_usage = Usage(calls=1, model=getattr(self.provider, "model", ""),
                                             effort=getattr(self.provider, "effort", ""))
        self.progress(agent.name)
        try:
            result = callback()
            check_cancelled()
        except Exception:
            self.record(p, agent, inputs, {"failed": True}, ai=use_ai, success=False)
            raise
        self.record(p, agent, inputs, result, ai=use_ai)
        return result

    def signature(self, inputs):
        return digest({"pipeline": 3, "inputs": inputs, "provider": getattr(self.provider, "label", "offline"),
                       "effort": getattr(self.provider, "effort", "")})

    def record(self, p, agent, inputs, result, ai=True, success=True):
        usage = self.provider.last_usage if self.provider and ai else Usage(calls=0, source="offline")
        p.runs.append(AgentRun(agent=agent.name, provider=self.provider.label if self.provider and ai else "offline:deterministic",
                               input_hash=digest(inputs), output_hash=digest(result), calls=usage.calls,
                               model=usage.model, effort=usage.effort, input_tokens=usage.input_tokens,
                               output_tokens=usage.output_tokens, total_tokens=usage.total_tokens,
                               duration_ms=usage.duration_ms, estimated_cost_usd=usage.estimated_cost_usd,
                               usage_source=usage.source, telemetry_version=2, success=success, search_count=usage.search_count))

    def requirements(self, p: Project, values: Requirement, analyze_ai=False):
        agent = RequirementsAgent()
        result = self.step(p, agent, {"brief": p.brief, "values": values.model_dump()},
                           lambda: agent.run(p.brief, values, self.provider if analyze_ai else None, p.requirements.proposals), ai=analyze_ai)
        # Retain unanswered additional questions when saving a clarification form.
        if not analyze_ai:
            result.proposals = [proposal.model_copy(deep=True) for proposal in p.requirements.proposals
                                if getattr(result.values, proposal.key) in (None, "") or
                                getattr(result.values, proposal.key) == getattr(Requirement.model_validate({proposal.key: proposal.value}), proposal.key)]
            result.assumptions = list(p.requirements.assumptions)
            result.questions += [q for q in p.requirements.questions if q not in QUESTIONS.values() and q not in result.questions and not values.clarifications.get(q, "").strip()]
        p.pipeline_cache = {}
        p.discovery = None
        p.requirements = result
        p.research = None
        p.circuit = None
        p.design_review = None
        invalidate(p, Gate.REQUIREMENTS)

    def discover(self, p):
        if not approved(p, Gate.REQUIREMENTS):
            raise ValueError("ต้องอนุมัติ Requirements ก่อนค้นหาชิ้นส่วน")
        agent = PartsDiscoveryAgent()
        previous = p.discovery
        p.discovery = self.step(p, agent, {"requirements": p.requirements.values.model_dump()},
                                lambda: agent.run(p.requirements.values, p.brief, self.provider, previous))
        p.pipeline_cache = {}
        p.circuit, p.design_review = None, None
        invalidate(p, Gate.COMPONENTS)
        p.pipeline_status = "ค้นหาชิ้นส่วนแล้ว เลือกชุดที่แนะนำในหน้า Datasheet และหลักฐานก่อนสร้างวงจร"

    def plan(self, p: Project):
        if not approved(p, Gate.REQUIREMENTS):
            raise ValueError("ต้องอนุมัติ Requirements ก่อนรัน Agent เลือกอุปกรณ์")
        selected = []
        download_problems = []
        if self.provider and self.store and getattr(self.provider, "supports_web_search", False):
            if not p.discovery:
                self.discover(p)
                return
            if any(part.status != "selected" for part in p.discovery.parts):
                raise ValueError("เลือกชิ้นส่วนให้ครบก่อน หากปฏิเสธบางรุ่นให้กดค้นหาทางเลือกใหม่")
            selected = p.discovery.parts
            self.progress("ดาวน์โหลด datasheet และเก็บต้นฉบับ (ใช้ไฟล์เดิมเมื่อมีแล้ว)")
            from .web_research import acquire_sources
            download_problems = acquire_sources(p, self.store, self.progress)
            p.pipeline_status = "\n".join(download_problems)
            if not p.sources:
                raise ValueError("ยังอ่าน datasheet ไม่ได้: " + " | ".join(download_problems[:3]))
        research_agent, circuit_agent, reviewer = DatasheetResearchAgent(), CircuitBOMAgent(), ReviewAgent()
        active_sources = [s for s in p.sources if not selected or not s.part_number or any(
            part.part_number == s.part_number and part.ref in s.component_refs for part in selected)]
        inputs = {"requirements": p.requirements.values.model_dump(), "sources": [s.model_dump() for s in active_sources]}
        signature = self.signature(inputs)
        if p.research is None or p.pipeline_cache.get("research") != signature:
            research = self.step(p, research_agent, inputs,
                lambda: research_agent.run(p.requirements.values, active_sources, self.provider), ai=bool(active_sources))
            if p.research:
                verified = [f for f in p.research.facts if f.status == "Confirmed" and f.verified_by and f.source_id in {s.id for s in active_sources}]
                research.facts = verified + [f for f in research.facts if not any((f.source_id, f.page, f.claim) == (v.source_id, v.page, v.claim) for v in verified)]
            p.research = research
            p.circuit, p.design_review = None, None
            p.pipeline_cache["research"] = signature
            invalidate(p, Gate.COMPONENTS)
        inputs = {"requirements": p.requirements.values.model_dump(), "research": p.research.model_dump(),
                  "selected": [part.model_dump() for part in selected]}
        signature = self.signature(inputs)
        if p.circuit is None or p.pipeline_cache.get("circuit") != signature:
            p.circuit = self.step(p, circuit_agent, inputs,
                lambda: circuit_agent.run(p.requirements.values, p.research, self.provider, selected))
            p.pipeline_cache["circuit"] = signature
            invalidate(p, Gate.COMPONENTS)
        # Run programmatic checks every time; an independent AI review is optional.
        self.progress("ตรวจวงจรตามกฎและจัดทำผลร่าง")
        p.design_review = reviewer.run(p.requirements.values, p.research, p.circuit)
        p.pipeline_status = ("สร้างร่างแล้ว เลขขาที่มีหลักฐานแสดงให้ตรวจได้ ยังไม่อนุมัติวงจร" +
                             ("\nเอกสารที่ยังขาด: " + " | ".join(download_problems) if download_problems else ""))

    def ai_review(self, p):
        if not p.circuit or not p.research:
            raise ValueError("สร้างร่างวงจรก่อนตรวจด้วย AI")
        agent = ReviewAgent()
        p.design_review = self.step(p, agent, {"circuit": p.circuit.model_dump()},
            lambda: agent.run(p.requirements.values, p.research, p.circuit, self.provider))
        invalidate(p, Gate.COMPONENTS)
        p.pipeline_status = "ตรวจด้วย AI แล้ว ดูประเด็นในหน้า Review"

    def circuit(self, p: Project, circuit: CircuitResult):
        if not approved(p, Gate.REQUIREMENTS) or p.research is None:
            raise ValueError("ต้องอนุมัติ Requirements และรัน research ก่อน")
        enforce_circuit_evidence(circuit, p.research, allow_draft=True)
        old_hash = evidence_hash(p, Gate.COMPONENTS)
        p.circuit = circuit
        p.design_review = ReviewAgent().run(p.requirements.values, p.research, circuit)
        invalidate(p, Gate.COMPONENTS if evidence_hash(p, Gate.COMPONENTS) != old_hash else Gate.CONNECTIONS)

    def regenerate_circuit(self, p: Project):
        if not approved(p, Gate.REQUIREMENTS) or p.research is None:
            raise ValueError("ต้องอนุมัติ Requirements และรัน research ก่อน")
        agent = CircuitBOMAgent()
        selected = [part for part in p.discovery.parts if part.status == "selected"] if p.discovery else []
        inputs = {"requirements": p.requirements.values.model_dump(), "research": p.research.model_dump(),
                  "selected": [part.model_dump() for part in selected]}
        p.circuit = self.step(p, agent, inputs, lambda: agent.run(p.requirements.values, p.research, self.provider, selected))
        p.pipeline_cache["circuit"] = self.signature(inputs)
        p.design_review = ReviewAgent().run(p.requirements.values, p.research, p.circuit)
        invalidate(p, Gate.COMPONENTS)
        p.pipeline_status = "สร้างวงจรจากหลักฐานที่เก็บไว้แล้ว ไม่ได้ค้นเว็บหรืออ่าน PDF ใหม่"

    def imports(self, p: Project):
        if not p.circuit:
            raise ValueError("ต้องมีแผนวงจรก่อนตรวจไฟล์")
        result = review_imports(p.files, p.circuit, p.requirements.values.layers)
        invalidate(p, Gate.SCHEMATIC)
        p.import_review = result
        agent = ManufacturingTestAgent()
        p.manufacturing = self.step(p, agent, {"requirements": p.requirements.values.model_dump(), "files": [f.model_dump() for f in p.files if f.active]}, lambda: agent.run(p.requirements.values, p.files, self.provider))

    def approve(self, p: Project, gate: Gate, reviewer: str, note: str, expected_hash: str):
        if not reviewer.strip() or not note.strip():
            raise ValueError("ระบุชื่อผู้อนุมัติและเหตุผล")
        if expected_hash != evidence_hash(p, gate):
            raise ValueError("ข้อมูลที่กำลังอนุมัติเปลี่ยนไปแล้ว กรุณาตรวจเวอร์ชันใหม่")
        blockers = gate_blockers(p, gate)
        if blockers:
            raise ValueError("Gate ถูกบล็อก: " + " | ".join(blockers[:12]))
        p.approvals = [a for a in p.approvals if a.gate != gate]
        p.approvals.append(Approval(gate=gate, evidence_hash=expected_hash, approved_by=reviewer.strip(), note=note.strip()))
