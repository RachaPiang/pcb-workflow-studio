"""Five bounded agents. Each gets only its declared inputs, never approvals or storage."""
import re

from .provider import Provider
from .schemas import *


def missing(requirements: Requirement) -> list[str]:
    values = requirements.model_dump()
    return [key for key in QUESTIONS if values[key] is None or (isinstance(values[key], str) and not values[key].strip())]


class RequirementsAgent:
    name = "Requirements Agent"

    def run(self, brief: str, values: Requirement, provider: Provider | None = None, previous=None) -> RequirementsResult:
        values = values.model_copy(deep=True)
        if values.layers is None and re.search(r"4\s*[- ]?\s*layer|4\s*ชั้น", brief, re.I):
            values.layers = 4
        extra_questions = []
        assumptions = []
        proposals = []
        if provider:
            suggested = provider.generate(self.name,
                "Act as a PCB design advisor. Reply in Thai. Read the FULL brief and supplied clarifications first. "
                "For EACH empty required field propose ONE concrete value with a short reason and tradeoff. "
                "Extract decisions already stated in the brief instead of asking them again: basis=brief needs an exact quote. "
                "For unspecified fields choose sensible draft recommendations, basis=recommendation. "
                "You MAY recommend MCU/sensor/display part numbers, layer count, supply design targets and a draft board size. "
                "Design targets are proposals, NOT verified component ratings. Never invent measured current, pinouts, "
                "datasheet evidence or agreed factory rules. Mark preliminary current budgets/rules in reason and assumptions "
                "as needing verification before manufacture. If the user has no factory, propose a clearly provisional "
                "manufacturing target rather than demanding an existing agreement. Never replace nonempty values. "
                "Do not repeat rejected proposals; choose alternatives using the rejection context. "
                "Ask at most THREE essential questions, only when a recommendation would conflict with unknown user intent "
                "or a safety-critical operating condition. Do not turn implementation choices into questionnaires. "
                "Do not ask questions about fields you already propose. Set all proposals pending; never approve anything.",
                {"brief": brief, "values": values.model_dump(), "required_fields": QUESTIONS,
                 "previous_proposals": [p.model_dump() for p in (previous or [])]}, RequirementsAdvice)
            available = set(missing(values))
            for proposal in suggested.proposals:
                if proposal.key not in available:
                    continue
                proposal.status = "pending"
                if proposal.basis == "brief" and (not proposal.quote.strip() or normalized(proposal.quote) not in normalized(brief)):
                    proposal.basis = "recommendation"
                    proposal.quote = ""
                proposals.append(proposal)
                available.remove(proposal.key)
            covered = {QUESTIONS[p.key] for p in proposals} | {QUESTIONS[k] for k in QUESTIONS if k not in missing(values)}
            extra_questions = list(dict.fromkeys(q for q in suggested.questions if q.strip() and q not in covered))[:3]
            assumptions = suggested.assumptions
        questions = [] if provider else [QUESTIONS[key] for key in missing(values)]
        questions.extend(q for q in extra_questions if q not in questions and not values.clarifications.get(q, "").strip())
        blocks = ["flowchart LR", "  INPUT[Power input] --> REG[Power regulation]", "  REG --> MCU[MCU]"]
        loads = ["MCU"]
        for field, node in (("sensor", "SENSOR"), ("display", "DISPLAY")):
            if getattr(values, field).strip().casefold() not in ("none", "ไม่ใช้", "ไม่มี"):
                blocks.append(f"  MCU <--> {node}[{field.title()}]")
                loads.append(field)
        if "ปุ่ม" in brief + values.extras or "button" in (brief + values.extras).lower():
            blocks.append("  BUTTON[Buttons] --> MCU")
        if values.usb == "data":
            blocks.append("  USB[USB data interface] <--> MCU")
        return RequirementsResult(values=values, questions=questions, assumptions=assumptions, proposals=proposals,
            block_diagram="\n".join(blocks),
            power_tree=f"Input {values.input_voltage or '?'} V → regulator (to verify) → {values.rail_voltage or '?'} V rail\n{' + '.join(loads)}; total budget {values.max_current_ma or '?'} mA (user requirement)")


def normalized(text):
    return " ".join(text.split()).casefold()


def validate_fact(fact: Fact, sources: list[DatasheetSource]) -> None:
    source = next((s for s in sources if s.id == fact.source_id), None)
    if not source or fact.page not in source.pages:
        raise ValueError("หลักฐานอ้าง source / page ที่ไม่มีในไฟล์ที่นำเข้า")
    if normalized(fact.quote) not in normalized(source.pages[fact.page]):
        raise ValueError("ข้อความอ้างอิงไม่ตรงกับข้อความที่อ่านได้จากหน้าที่ระบุ")
    if fact.kind == "pin" and not (fact.pin_number.strip() and fact.pin_name.strip()):
        raise ValueError("หลักฐานชนิด pin ต้องมี pin_number และ pin_name")
    if fact.kind == "pin" and (normalized(fact.pin_name) not in normalized(fact.quote) or
            not re.search(r"(?<![A-Za-z0-9])" + re.escape(fact.pin_number) + r"(?![A-Za-z0-9])", fact.quote)):
        raise ValueError("ข้อความอ้างอิงต้องมีชื่อและเลขขาที่เสนอ")


class PartsDiscoveryAgent:
    name = "Parts Discovery Agent"

    def run(self, requirements, brief, provider, previous=None):
        if not getattr(provider, "supports_web_search", False):
            raise ValueError("ค้นชิ้นส่วนอัตโนมัติต้องใช้ Codex session; โหมด API นี้ยังไม่มีเครื่องมือค้นเว็บ")
        result = provider.generate(self.name,
            "Search the web NOW for actual purchasable components for this PCB. Use official manufacturer pages/datasheets "
            "and authorized distributor pages. Budget at most 8 targeted searches. Reply with Thai rationales. "
            "Cover MCU, sensor, display/module, regulator, USB/data connectors, debug/display headers, flash/crystal if needed, "
            "switches, LEDs, resistors, capacitors and protection needed by the brief. Propose one exact MPN per reference "
            "with manufacturer, package, rationale and real product URL and direct datasheet PDF URL you found. "
            "If an exact MPN has a verifiable product page but no direct PDF, include it with an empty datasheet_url "
            "and explain the missing PDF in unresolved. Do not omit known exact passive/connector MPNs solely for a missing PDF. "
            "Do not put TBD/UNRESOLVED as an MPN. If even product evidence is unavailable, omit that candidate and explain in unresolved. "
            "Preserve explicitly chosen MCU/sensor models; distinguish a controller IC from a complete display module. "
            "Every reference must be unique and stable. No grouping refs. Same MPN may be used by multiple refs. "
            "Use previous rejected candidates to choose alternatives; keep selected candidates unchanged. "
            "Do not claim prices/stock without evidence, never invent URLs or pin numbers. Set status pending. "
            "This is a candidate list for human selection, not a verified circuit. Do not inspect local files or run commands.",
            {"requirements": requirements.model_dump(), "brief": brief,
             "previous": previous.model_dump() if previous else None}, PartsDiscovery)
        if not result.parts or len({p.ref for p in result.parts}) != len(result.parts):
            raise ValueError("การค้นหาไม่ได้ชุดชิ้นส่วนที่ใช้งานได้หรือมี Reference ซ้ำ")
        for part in result.parts:
            if part.part_number.upper() in ("UNRESOLVED", "TBD", "UNKNOWN"):
                raise ValueError("การค้นหาต้องระบุรุ่นชิ้นส่วนจริง")
            part.status = "pending"
        if not getattr(provider.last_usage, "search_count", 0):
            raise ValueError("Codex ไม่ได้รายงานการค้นเว็บจริงในรอบนี้ จึงยังไม่รับผลเป็นงาน Research")
        if previous:
            selected = {p.ref: p for p in previous.parts if p.status == "selected"}
            result.parts = [selected.pop(p.ref, p) for p in result.parts] + list(selected.values())
        return result


def ranked_research_pages(source: DatasheetSource):
    """Prefer actual engineering sections over repeated mentions and contents pages."""
    groups = (
        ("pin definitions", "pin description", "pin configuration", "pin assignment", "pinout", "terminal functions"),
        ("recommended operating", "operating conditions", "electrical characteristics", "absolute maximum"),
        ("land pattern", "landing pattern", "footprint", "package dimensions", "module dimensions", "ordering information"),
        ("typical application", "application circuit", "reference schematic", "module schematics", "decoupling"),
    )
    entries = []
    for page, content in source.pages.items():
        normalized = re.sub(r"\s+", " ", content.lower())
        heading = normalized[:240]
        if any(term in heading[:100] for term in ("contents", "list of tables", "list of t ables", "list of figures")):
            continue
        scores = [sum(30 if term in heading else 5 if term in normalized else 0 for term in group) for group in groups]
        # A pin table often says "pin" only once; a boot chapter may repeat it dozens of times.
        if scores[0] and re.search(r"(?:name|pin)\s+(?:no\.?|number)|pin\s+name", normalized):
            scores[0] += 40
        entries.append((page, content, scores))
    ordered, used = [], set()
    # Reserve early space for each engineering topic, then fill with remaining useful pages.
    for topic in range(len(groups)):
        candidates = sorted(entries, key=lambda entry: entry[2][topic], reverse=True)
        for page, content, scores in candidates:
            if scores[topic] and page not in used:
                ordered.append((page, content))
                used.add(page)
                break
    for page, content, scores in sorted(entries, key=lambda entry: sum(entry[2]), reverse=True):
        if page not in used:
            ordered.append((page, content))
    return ordered


class DatasheetResearchAgent:
    name = "Datasheet Research Agent"

    def run(self, requirements: Requirement, sources: list[DatasheetSource], provider: Provider | None = None) -> ResearchResult:
        if not sources:
            return ResearchResult(unresolved=["ยังไม่มี datasheet: อัปโหลด PDF และระบุชื่อเอกสาร/เวอร์ชันก่อนยืนยัน pinout และ footprint"])
        if not provider:
            return ResearchResult(unresolved=["โหมด offline อ่านและแสดงหน้าของ PDF แล้ว: เพิ่มข้อเท็จจริงพร้อมข้อความอ้างอิง หรือเปิด AI เพื่อเสนอข้อเท็จจริง"])
        # Bound document context while keeping original page numbers; never claim unseen pages were read.
        pages, remaining = [], 48000
        for source in sources:
            per_source = min(14000, 48000 // max(1, len(sources)))
            for page, content in ranked_research_pages(source):
                excerpt = content[:min(3500, remaining, per_source)]
                if excerpt:
                    pages.append({"source_id": source.id, "title": source.title, "revision": source.revision, "page": page, "text": excerpt,
                                  "component_refs": source.component_refs, "part_number": source.part_number})
                    remaining -= len(excerpt)
                    per_source -= len(excerpt)
                if remaining <= 0 or per_source <= 0:
                    break
            if remaining <= 0:
                break
        result = provider.generate(self.name,
            "Extract supported facts only from supplied pages. Each fact needs exact quote, source_id, printed PDF page index (1-based),"
            " Use component_refs assigned to each source; never assume reference roles. Set status Inferred and verified_by empty."
            " Copy a CONTIGUOUS quote from the provided text verbatim, preserving words, numbers and punctuation; do not repair OCR or join nonadjacent rows."
            " Extract every supplied pin-table row needed for power, ground, reset/boot, GPIO and requested interfaces."
            " For pin facts provide one physical pad per fact in pin_number and the exact table label in pin_name; never put a list or range in pin_number."
            " A row listing multiple pads may support separate facts, each quoting the full row."
            " Separate operating voltage limits from absolute maximum ratings."
            " Circuit design choices (GPIO/net assignments or reference designators for capacitors) belong to the later circuit agent, not missing datasheet evidence."
            " Only list unresolved document facts needed by this design, not circuit choices that the next agent can propose.",
            {"requirements": requirements.model_dump(), "pages": pages}, ResearchResult)
        valid = []
        for fact in result.facts:
            try:
                validate_fact(fact, sources)
                source = next(s for s in sources if s.id == fact.source_id)
                if source.component_refs and fact.component_ref not in source.component_refs:
                    raise ValueError("Reference ไม่ตรงกับชิ้นส่วนของเอกสาร")
            except ValueError:
                result.unresolved.append(f"ตัดข้อเสนอ {fact.component_ref}/{fact.kind} ที่ตรวจข้อความอ้างอิงไม่ได้; ต้องตรวจเอกสารต้นฉบับ")
                continue
            fact.status = "Inferred"
            fact.verified_by = ""
            valid.append(fact)
        result.facts = valid
        return result


class CircuitBOMAgent:
    name = "Circuit/BOM Agent"

    def run(self, requirements: Requirement, research: ResearchResult, provider: Provider | None = None, selected_parts=None) -> CircuitResult:
        if missing(requirements):
            raise ValueError("Requirements ยังไม่เพียงพอสำหรับเลือกอุปกรณ์")
        if provider:
            result = provider.generate(self.name,
                "Draft components, BOM, pins, nets, connections, constraints, decoupling and pull resistors."
                " Use cited research evidence for DRAFT physical pin numbers, voltage limits and footprints."
                " Without matching evidence leave pin numbers empty, footprint UNRESOLVED, status Unresolved."
                " Cite fact IDs in evidence_ids. A connection requires evidence for BOTH physical endpoints."
                " Copy exact research pin_name into pins.name and connection endpoint signals; put functional aliases in net names or notes."
                " For example, a fact named SDI must stay SDI, not SDI/SDA, in the physical pin and endpoint signal."
                " Use the selected parts and EXACT reference-to-part mapping if supplied. Never replace selected MPNs."
                " Include supporting resistors, capacitors, crystal/flash where required."
                " Always provide a nonempty signal-level connection table, even when physical pin numbers are unresolved."
                " Every component needs a connection or an explicit unresolved reason. Never return an empty schematic draft."
                " Include all requested functions and flag unsupported details.",
                {"requirements": requirements.model_dump(), "research": research.model_dump(),
                 "selected_parts": [p.model_dump() for p in (selected_parts or [])]}, CircuitResult)
            if not result.connections or not result.components or not result.bom:
                raise ValueError("AI ส่งร่างวงจรไม่ครบ: ต้องมี BOM และตารางการเชื่อมต่อ ผล Research เก็บไว้แล้ว ลองสร้างวงจรจาก Research ปัจจุบัน")
            expected = {p.ref: p.part_number for p in (selected_parts or [])}
            actual = {c.ref: c.part_number for c in result.components}
            if any(actual.get(ref) != part for ref, part in expected.items()):
                raise ValueError("ร่างวงจรไม่ตรงกับชุดชิ้นส่วนที่เลือก กรุณาสร้างจาก Research ปัจจุบันใหม่")
            ground_draft(result, research)
            enforce_circuit_evidence(result, research, allow_draft=True)
            return result
        # Deterministic planning draft: explicit choices only, no pretend pinout or catalog.
        specs = [("U1", requirements.mcu, "MCU"), ("U4", "TBD regulator", "Power regulation")]
        if requirements.sensor.casefold().strip() not in ("none", "ไม่ใช้", "ไม่มี"):
            specs.append(("U2", requirements.sensor, "Sensor"))
        if requirements.display.casefold().strip() not in ("none", "ไม่ใช้", "ไม่มี"):
            specs.append(("U3", requirements.display, "Display"))
        if requirements.usb != "none":
            specs.append(("J1", "TBD USB-C connector", "USB input"))
        else:
            specs.append(("J1", "TBD power connector", "Power input"))
        if "button" in requirements.extras.lower() or "ปุ่ม" in requirements.extras:
            specs.append(("SW1", "TBD pushbutton", "User button"))
        components = [Component(ref=ref, part_number=pn, role=role, rationale="User requirement / required functional block; verify exact part and package") for ref, pn, role in specs]
        result = CircuitResult(components=components,
            bom=[BOMItem(references=[c.ref], quantity=1, part_number=c.part_number, notes=c.rationale) for c in components],
            nets=[Net(name="VIN", voltage=requirements.input_voltage), Net(name="VMAIN", voltage=requirements.rail_voltage), Net(name="GND", voltage=0)],
            constraints=[DesignConstraint(category="stackup", rule=f"{requirements.layers} layers; {requirements.design_rules}"),
                         DesignConstraint(category="mechanical", rule=requirements.board_size),
                         DesignConstraint(category="manufacturing", rule=f"{requirements.manufacturer}; {requirements.assembly}")],
            decoupling=["ทุก IC ต้องมี bypass/decoupling ตาม datasheet; ค่า จำนวน และตำแหน่งยังรอหลักฐาน"],
            pull_resistors=["ตรวจ boot/reset, I²C pull-up และ USB-C CC ตาม interface ที่เลือก; ไม่กำหนดค่าโดยไม่มีหลักฐาน"],
            unresolved=["นี่คือแผนการเชื่อมต่อระดับสัญญาณ ไม่ใช่ netlist พร้อมผลิต", "ต้องเลือก regulator/passives/connectors และยืนยัน footprint จาก datasheet", "กระแส/ความร้อน/interface ยังต้องตรวจจากชิ้นส่วนจริง"])
        result.connections.append(Connection(net="VIN", from_ref="J1", from_signal="Power input", to_ref="U4", to_signal="VIN"))
        for c in components:
            if c.ref not in ("J1", "U4", "SW1"):
                result.connections.append(Connection(net="VMAIN", from_ref="U4", from_signal="VOUT", to_ref=c.ref, to_signal="Supply"))
            if c.ref in ("U2", "U3"):
                result.connections.append(Connection(net=f"{c.ref}_INTERFACE_TBD", from_ref="U1", from_signal="Interface TBD", to_ref=c.ref, to_signal="Interface TBD", notes="เลือก I²C/SPI และ GPIO หลังตรวจ datasheet"))
            if c.ref != "J1":
                result.connections.append(Connection(net="GND", from_ref="J1", from_signal="Ground", to_ref=c.ref, to_signal="Ground"))
        if any(c.ref == "SW1" for c in components):
            result.connections.append(Connection(net="BUTTON_TBD", from_ref="SW1", from_signal="Contact", to_ref="U1", to_signal="GPIO TBD"))
        for con in result.connections:
            if con.net not in {n.name for n in result.nets}:
                result.nets.append(Net(name=con.net, interface="TBD"))
        return result


def ground_draft(circuit, research):
    """Keep useful signal-level proposals, strip physical claims lacking evidence."""
    facts = {f.id: f for f in research.facts}
    def supports(ids, ref, kind, number="", name=""):
        return any(i in facts and facts[i].component_ref == ref and facts[i].kind == kind and
                   (kind != "pin" or (facts[i].pin_number == number and facts[i].pin_name.casefold() == name.casefold())) for i in ids)
    def note(ref, kind):
        text = f"{ref}: ตัดค่า {kind} ที่ไม่มีหลักฐานรองรับออกจากร่าง; เพิ่ม/ตรวจหลักฐานก่อนกำหนดค่าจริง"
        if text not in circuit.unresolved:
            circuit.unresolved.append(text)
    for c in circuit.components:
        if c.footprint != "UNRESOLVED" and not supports(c.evidence_ids,c.ref,"footprint"):
            c.footprint = "UNRESOLVED"
            note(c.ref,"footprint")
        if (c.voltage_min is not None or c.voltage_max is not None) and not supports(c.evidence_ids,c.ref,"voltage"):
            c.voltage_min, c.voltage_max = None, None
            note(c.ref,"voltage")
    for pin in circuit.pins:
        if pin.number and not supports(pin.evidence_ids,pin.component_ref,"pin",pin.number,pin.name):
            pin.number = ""
            note(pin.component_ref,"pin")
    for con in circuit.connections:
        for end in ("from", "to"):
            ref, number, signal = (getattr(con,end+"_"+key) for key in ("ref","pin","signal"))
            if number and not supports(con.evidence_ids,ref,"pin",number,signal):
                setattr(con,end+"_pin","")
                note(ref,"pin")
    by_ref = {c.ref: c for c in circuit.components}
    for item in circuit.bom:
        if item.footprint != "UNRESOLVED" and any(ref not in by_ref or by_ref[ref].footprint != item.footprint for ref in item.references):
            item.footprint = "UNRESOLVED"
    for constraint in circuit.constraints:
        constraint.evidence_ids = [i for i in constraint.evidence_ids if i in facts]


def enforce_circuit_evidence(circuit: CircuitResult, research: ResearchResult, allow_draft=False):
    facts = {f.id: f for f in research.facts if allow_draft or (f.status == "Confirmed" and f.verified_by)}
    def evidence(ids, ref, kind):
        return [facts[i] for i in ids if i in facts and facts[i].component_ref == ref and facts[i].kind == kind]
    for component in circuit.components:
        if component.footprint != "UNRESOLVED" and not evidence(component.evidence_ids, component.ref, "footprint"):
            raise ValueError(f"{component.ref}: footprint ไม่มีหลักฐานที่มนุษย์ยืนยัน")
        if (component.voltage_min is not None or component.voltage_max is not None) and not evidence(component.evidence_ids, component.ref, "voltage"):
            raise ValueError(f"{component.ref}: voltage ไม่มีหลักฐานที่มนุษย์ยืนยัน")
        # A cited fact supports a draft; it does not establish design correctness automatically.
        component.status = "Inferred" if component.evidence_ids else "Unresolved"
    for pin in circuit.pins:
        if pin.number and not any(f.pin_number == pin.number and f.pin_name.casefold() == pin.name.casefold() for f in evidence(pin.evidence_ids, pin.component_ref, "pin")):
            raise ValueError(f"{pin.component_ref}.{pin.number}: pin ไม่มีหลักฐานตรงกับชื่อขา")
    for con in circuit.connections:
        for ref, number, signal in ((con.from_ref, con.from_pin, con.from_signal), (con.to_ref, con.to_pin, con.to_signal)):
            if number and not any(f.pin_number == number and f.pin_name.casefold() == signal.casefold() for f in evidence(con.evidence_ids, ref, "pin")):
                raise ValueError(f"{ref}.{number}: endpoint ไม่มีหลักฐาน pin ที่ตรงกัน")
        con.status = "Inferred" if con.from_pin and con.to_pin else "Unresolved"
    by_ref = {c.ref: c for c in circuit.components}
    for item in circuit.bom:
        if item.footprint != "UNRESOLVED" and any(ref not in by_ref or by_ref[ref].footprint != item.footprint for ref in item.references):
            raise ValueError("BOM footprint ไม่ตรงกับ component ที่มีหลักฐาน")
    for constraint in circuit.constraints:
        if any(i not in facts for i in constraint.evidence_ids):
            raise ValueError("Design constraint อ้างหลักฐานที่ยังไม่ได้ยืนยัน")
        constraint.status = "Inferred" if constraint.evidence_ids else "Unresolved"


class ReviewAgent:
    name = "Review Agent"

    def run(self, requirements: Requirement, research: ResearchResult, circuit: CircuitResult, provider: Provider | None = None) -> ReviewResult:
        result = ReviewResult(limitations=["การตรวจอัตโนมัติไม่แทน ERC/DRC, signal integrity หรือการตรวจโดยวิศวกร"])
        def add(severity, category, message, affected=None):
            result.findings.append(ReviewFinding(severity=severity, category=category, message=message, affected=affected or []))
        refs = [c.ref for c in circuit.components]
        if not refs or len(set(refs)) != len(refs):
            add("critical", "components", "Component references ว่างหรือซ้ำกัน")
        if not any(c.part_number.casefold() == requirements.mcu.casefold() for c in circuit.components):
            add("error", "components", "MCU ใน BOM ไม่ตรงกับ Requirements")
        for field, keywords in (("sensor", ("sensor", "imu", "accelerometer")), ("display", ("display", "oled", "lcd"))):
            requested = getattr(requirements, field).strip().casefold()
            if requested not in ("none", "ไม่ใช้", "ไม่มี") and not any(any(k in c.role.casefold() for k in keywords) for c in circuit.components):
                add("error", "components", f"ไม่พบอุปกรณ์สำหรับ {field} ที่ Requirements ต้องการ")
        confirmed = {f.id for f in research.facts if f.status == "Confirmed" and f.verified_by}
        for c in circuit.components:
            if "TBD" in c.part_number or c.footprint == "UNRESOLVED" or not c.evidence_ids or any(i not in confirmed for i in c.evidence_ids):
                add("error", "components", "ยังไม่ยืนยัน part/package/หลักฐานของอุปกรณ์", [c.ref])
            if c.voltage_min is None or c.voltage_max is None:
                add("error" if c.ref.upper().startswith("U") else "warning", "voltage", "ยังไม่มีช่วงแรงดันที่ตรวจยืนยัน", [c.ref])
            elif c.voltage_min > c.voltage_max:
                add("critical", "voltage", "ช่วงแรงดัน min/max ขัดแย้งกัน", [c.ref])
        bom_refs = [r for b in circuit.bom for r in b.references]
        if set(bom_refs) != set(refs) or len(bom_refs) != len(set(bom_refs)):
            add("error", "components", "BOM references ไม่ตรงกับรายการ components หรือมีรายการซ้ำ")
        for b in circuit.bom:
            if b.quantity != len(b.references) or any(c.part_number != b.part_number for c in circuit.components if c.ref in b.references):
                add("error", "components", "BOM quantity/part number ขัดแย้งกับ components", b.references)
        if not circuit.connections:
            add("critical", "connections", "ไม่มีตารางการเชื่อมต่อ")
        nets = {n.name: n for n in circuit.nets}
        if len(nets) != len(circuit.nets):
            add("error", "connections", "มีชื่อ net ซ้ำในแผนวงจร")
        pin_keys = [(pin.component_ref, pin.number) for pin in circuit.pins if pin.number]
        for pin in circuit.pins:
            if pin.number and (not pin.evidence_ids or any(i not in confirmed for i in pin.evidence_ids)):
                add("error", "connections", "เลขขาร่างยังรอมนุษย์ตรวจหลักฐาน", [f"{pin.component_ref}.{pin.number}"])
        if len(set(pin_keys)) != len(pin_keys):
            add("error", "connections", "Pin assignment มี physical pin ซ้ำ")
        connected_refs = {ref for con in circuit.connections for ref in (con.from_ref, con.to_ref)}
        for ref in refs:
            if ref not in connected_refs:
                add("error", "connections", "Component ไม่มีการเชื่อมต่อในแผน", [ref])
        endpoint_nets = {}
        for con in circuit.connections:
            if (con.from_pin or con.to_pin) and (not con.evidence_ids or any(i not in confirmed for i in con.evidence_ids)):
                add("error", "connections", "การเชื่อมต่อร่างยังรอตรวจหลักฐานทั้งสองปลาย", [con.net])
            if con.from_ref not in refs or con.to_ref not in refs or con.net not in nets:
                add("critical", "connections", "Connection อ้าง component/net ที่ไม่มีอยู่", [con.net])
            if not con.from_pin or not con.to_pin:
                add("error", "connections", "ยังไม่ยืนยัน physical pin ทั้งสองปลาย", [con.net])
            for ref, pin in ((con.from_ref, con.from_pin), (con.to_ref, con.to_pin)):
                if not pin:
                    continue
                key = (ref, pin)
                if key not in pin_keys:
                    add("error", "connections", "Endpoint ไม่มีใน pin assignment", [f"{ref}.{pin}"])
                if key in endpoint_nets and endpoint_nets[key] != con.net:
                    add("critical", "connections", f"ขา {ref}.{pin} ต่อกับหลาย net ที่ขัดกัน")
                endpoint_nets[key] = con.net
                component = next((c for c in circuit.components if c.ref == ref), None)
                voltage = nets.get(con.net, Net(name="unknown")).voltage
                if component and voltage is not None and voltage != 0 and component.voltage_max is not None and voltage > component.voltage_max:
                    add("critical", "voltage", f"{con.net} {voltage} V เกินค่าที่กำหนดของ {ref}", [ref])
        for question in circuit.unresolved + research.unresolved:
            add("question", "unresolved", question)
        if provider:
            ai = provider.generate(self.name,
                "Independently review requirements against the circuit and confirmed research. Report conflicts, omissions, errors, warnings and questions."
                " You cannot suppress deterministic findings or approve gates.",
                {"requirements": requirements.model_dump(), "research": research.model_dump(), "circuit": circuit.model_dump()}, ReviewResult)
            result.findings.extend(ai.findings)
            result.limitations.extend(ai.limitations)
        return result


class ManufacturingTestAgent:
    name = "Manufacturing/Test Agent"

    def run(self, requirements: Requirement, files: list[FileVersion], provider: Provider | None = None) -> ManufacturingResult:
        result = ManufacturingResult(checklist=[
            "ตรวจ Gerber ใน viewer: outline, copper layers, solder mask, silkscreen และ drill alignment",
            "ยืนยัน stackup, impedance, copper weight, clearance และ drill กับโรงงาน",
            "ตรวจ BOM, placement/CPL (เมื่อประกอบ SMT), orientation, pin 1 และ DNP",
            "ตรวจ ERC/DRC รุ่นเดียวกับไฟล์ที่ส่งผลิต และให้มนุษย์อนุมัติ release"],
            test_steps=[
                TestStep(order=1, action="ปิดไฟ ตรวจบอร์ดและวัดความต้านทานระหว่างรางไฟกับ GND", test_point="VMAIN–GND", expected="ไม่มี short; ค่าเกณฑ์จริงต้องกำหนดจากวงจร", stop_condition="พบ short หรือชิ้นส่วนกลับขั้ว"),
                TestStep(order=2, action="ใช้แหล่งจ่ายจำกัดกระแส; กำหนด limit หลังคำนวณ inrush และโหลดจริง", test_point="VIN / input current", expected=f"VIN ตามโจทย์ {requirements.input_voltage} V; งบโหลด {requirements.max_current_ma} mA ไม่ใช่ค่า current limit อัตโนมัติ", stop_condition="กระแสชน limit, ความร้อนผิดปกติ หรือ rail ผิด"),
                TestStep(order=3, action="วัดรางไฟก่อนเริ่ม firmware", test_point="VMAIN", expected=f"เป้าหมาย {requirements.rail_voltage} V; tolerance/ripple ต้องยืนยัน datasheet", stop_condition="แรงดันเกิน rating ของโหลด"),
                TestStep(order=4, action="ตรวจ reset/boot, debug interface แล้วทดสอบ sensor และจอทีละส่วน", test_point="Reset, debug, interface test points (TBD)", expected="MCU ตอบกลับและ peripheral ผ่าน functional test ที่กำหนด", stop_condition="สื่อสารไม่ผ่านหรือระดับ logic ผิด"),
            ])
        if provider:
            ai = provider.generate(self.name,
                "Draft manufacturing checklist and bring-up tests using ONLY requirements and file inspection summaries."
                " Distinguish target voltages from measured/verified values. Do not assert images or Gerber geometry were inspected."
                " Never invent test-point numbers or a safe current limit; mark unknown tolerances unresolved.",
                {"requirements": requirements.model_dump(), "files": [f.model_dump() for f in files if f.active]}, ManufacturingResult)
            result.checklist.extend(ai.checklist)
            result.test_steps.extend(s.model_copy(update={"order": len(result.test_steps)+i+1}) for i, s in enumerate(ai.test_steps))
            result.findings.extend(ai.findings)
        return result
