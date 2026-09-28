from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False, str_strip_whitespace=True)


class Gate(StrEnum):
    REQUIREMENTS = "requirements"
    COMPONENTS = "components"
    CONNECTIONS = "connections"
    SCHEMATIC = "schematic"
    PCB = "pcb"
    RELEASE = "release"


GATES = list(Gate)


class Requirement(Schema):
    mcu: str = ""
    layers: int | None = Field(default=None, ge=1, le=32)
    usb: Literal["", "power_only", "data", "none"] = ""
    input_voltage: float | None = Field(default=None, gt=0, le=1000)
    rail_voltage: float | None = Field(default=None, gt=0, le=1000)
    max_current_ma: float | None = Field(default=None, gt=0, le=100000)
    assembly: Literal["", "hand", "smt", "mixed"] = ""
    manufacturer: str = ""
    design_rules: str = ""
    board_size: str = ""
    sensor: str = ""
    display: str = ""
    extras: str = ""
    clarifications: dict[str, str] = Field(default_factory=dict)


QUESTIONS = {
    "mcu": "ใช้ MCU / โมดูลรุ่นใด (ระบุ part number)?",
    "layers": "PCB กี่ชั้น?",
    "usb": "USB ใช้รับไฟอย่างเดียว ส่งข้อมูล หรือไม่ใช้?",
    "input_voltage": "แรงดันไฟเข้ากี่โวลต์?",
    "rail_voltage": "แรงดันรางหลักกี่โวลต์?",
    "max_current_ma": "กระแสโหลดรวมสูงสุดกี่ mA?",
    "assembly": "ประกอบมือ SMT หรือผสม?",
    "manufacturer": "โรงงานที่จะผลิตชื่ออะไร?",
    "design_rules": "Design rule / stackup ที่ตกลงกับโรงงาน (ระบุเวอร์ชันหรือข้อกำหนด)?",
    "board_size": "ขนาดบอร์ดสูงสุด / ข้อจำกัดทางกล?",
    "sensor": "ต้องการ sensor รุ่นใด หรือระบุว่าไม่ใช้?",
    "display": "ต้องการจอรุ่นใด / interface หรือระบุว่าไม่ใช้?",
}


class RequirementProposal(Schema):
    key: str
    value: str | int | float
    reason: str = Field(min_length=1)
    basis: Literal["brief", "recommendation"] = "recommendation"
    quote: str = ""
    status: Literal["pending", "accepted", "rejected"] = "pending"

    @model_validator(mode="after")
    def valid_requirement(self):
        if self.key not in QUESTIONS:
            raise ValueError("Unknown requirement field")
        validated = Requirement.model_validate({self.key: self.value})
        if self.key in [k for k in QUESTIONS if getattr(validated, k) in (None, "")]:
            raise ValueError("Proposal must contain a value")
        return self


class RequirementsAdvice(Schema):
    proposals: list[RequirementProposal] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class RequirementsResult(Schema):
    values: Requirement = Field(default_factory=Requirement)
    questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    block_diagram: str = ""
    power_tree: str = ""
    proposals: list[RequirementProposal] = Field(default_factory=list)


class DatasheetSource(Schema):
    id: str = Field(default_factory=uid)
    file_id: str
    title: str = Field(min_length=1, max_length=300)
    revision: str = Field(min_length=1, max_length=100)
    url: str = ""
    pages: dict[int, str] = Field(default_factory=dict)
    sha256: str
    component_refs: list[str] = Field(default_factory=list)
    part_number: str = ""


class PartCandidate(Schema):
    ref: str = Field(pattern=r"^[A-Z][A-Z0-9]*[0-9]+$")
    part_number: str = Field(min_length=1)
    manufacturer: str
    role: str
    package: str
    product_url: str
    datasheet_url: str
    rationale: str
    status: Literal["pending", "selected", "rejected"] = "pending"


class PartsDiscovery(Schema):
    parts: list[PartCandidate] = Field(default_factory=list, max_length=40)
    unresolved: list[str] = Field(default_factory=list)


class Fact(Schema):
    id: str = Field(default_factory=uid)
    component_ref: str = Field(min_length=1)
    kind: Literal["pin", "voltage", "footprint", "decoupling", "interface", "other"]
    claim: str = Field(min_length=1)
    source_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=8, max_length=2000)
    status: Literal["Confirmed", "Inferred", "Unresolved"] = "Inferred"
    confidence: float = Field(default=0.5, ge=0, le=1)
    verified_by: str = ""
    pin_number: str = ""
    pin_name: str = ""


class ResearchResult(Schema):
    facts: list[Fact] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class Component(Schema):
    ref: str
    part_number: str
    role: str
    rationale: str
    footprint: str = "UNRESOLVED"
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["Confirmed", "Inferred", "Unresolved"] = "Unresolved"
    voltage_min: float | None = None
    voltage_max: float | None = None


class Pin(Schema):
    component_ref: str
    number: str = ""
    name: str
    direction: Literal["input", "output", "bidirectional", "power", "passive", "unknown"] = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)


class Net(Schema):
    name: str
    voltage: float | None = None
    interface: str = ""


class Connection(Schema):
    net: str
    from_ref: str
    from_pin: str = ""
    from_signal: str
    to_ref: str
    to_pin: str = ""
    to_signal: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["Confirmed", "Inferred", "Unresolved"] = "Unresolved"
    notes: str = ""


class BOMItem(Schema):
    references: list[str]
    quantity: int = Field(ge=1)
    part_number: str
    value: str = ""
    footprint: str = "UNRESOLVED"
    supplier: str = ""
    notes: str = ""


class DesignConstraint(Schema):
    category: str
    rule: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["Confirmed", "Inferred", "Unresolved"] = "Unresolved"


class CircuitResult(Schema):
    components: list[Component] = Field(default_factory=list)
    bom: list[BOMItem] = Field(default_factory=list)
    pins: list[Pin] = Field(default_factory=list)
    nets: list[Net] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    constraints: list[DesignConstraint] = Field(default_factory=list)
    decoupling: list[str] = Field(default_factory=list)
    pull_resistors: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class ReviewFinding(Schema):
    id: str = Field(default_factory=uid)
    severity: Literal["critical", "error", "warning", "question", "info"]
    category: str
    message: str
    affected: list[str] = Field(default_factory=list)
    evidence: str = ""
    agent: str = "Review Agent"


class ReviewResult(Schema):
    findings: list[ReviewFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FileVersion(Schema):
    id: str = Field(default_factory=uid)
    name: str
    kind: Literal["datasheet", "easyeda", "bom", "netlist", "schematic_image", "pcb_image", "drc", "gerber", "other"]
    sha256: str
    size: int = Field(ge=0)
    uploaded_at: str = Field(default_factory=now)
    summary: dict = Field(default_factory=dict)
    active: bool = True


class Approval(Schema):
    gate: Gate
    evidence_hash: str
    approved_by: str = Field(min_length=1)
    note: str = Field(min_length=1)
    approved_at: str = Field(default_factory=now)


class ManualCheck(Schema):
    gate: Gate
    key: str
    checked: bool
    reviewer: str = Field(min_length=1)
    note: str = Field(min_length=1)
    at: str = Field(default_factory=now)


class TestStep(Schema):
    order: int = Field(ge=1)
    action: str
    test_point: str
    expected: str
    stop_condition: str
    evidence_ids: list[str] = Field(default_factory=list)


class ManufacturingResult(Schema):
    checklist: list[str] = Field(default_factory=list)
    test_steps: list[TestStep] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)


class AgentRun(Schema):
    agent: str
    provider: str
    input_hash: str
    output_hash: str
    calls: int = Field(default=0, ge=0)
    model: str = ""
    effort: str = ""
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    usage_source: Literal["provider", "codex_quota", "unavailable", "offline"] = "unavailable"
    telemetry_version: int = 1
    success: bool = True
    search_count: int = 0
    at: str = Field(default_factory=now)


class Project(Schema):
    schema_version: int = 1
    id: str = Field(default_factory=uid)
    name: str = Field(min_length=1, max_length=200)
    brief: str = Field(min_length=1, max_length=20000)
    version: int = 0
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    requirements: RequirementsResult = Field(default_factory=RequirementsResult)
    sources: list[DatasheetSource] = Field(default_factory=list)
    research: ResearchResult | None = None
    circuit: CircuitResult | None = None
    design_review: ReviewResult | None = None
    import_review: ReviewResult | None = None
    manufacturing: ManufacturingResult | None = None
    files: list[FileVersion] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    manual_checks: list[ManualCheck] = Field(default_factory=list)
    runs: list[AgentRun] = Field(default_factory=list)
    change_reason: str = "Project created"
    discovery: PartsDiscovery | None = None
    pipeline_cache: dict[str, str] = Field(default_factory=dict)
    pipeline_status: str = ""
