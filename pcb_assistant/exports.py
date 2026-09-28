import csv
import hashlib
import io
import json
import zipfile

from .orchestrator import approved, gate_status
from .schemas import Gate


def json_text(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False)


def csv_text(columns, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(columns)
    for row in rows:
        cells = []
        for value in row:
            text = str(value if value is not None else "")
            # Spreadsheet formula injection: protect also whitespace-prefixed formula cells.
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")):
                text = "'" + text
            cells.append(text)
        writer.writerow(cells)
    return "\ufeff" + out.getvalue()


def usage_summary(p):
    runs = [r for r in p.runs if r.calls and r.telemetry_version >= 2]
    cost_values = [r.estimated_cost_usd for r in runs if r.estimated_cost_usd is not None]
    return {
        "calls": sum(r.calls for r in runs),
        "excluded_legacy_runs": sum(r.calls > 0 and r.telemetry_version < 2 for r in p.runs),
        "search_count": sum(r.search_count for r in runs),
        "failed_attempts": sum(not r.success for r in runs),
        "missing_usage_runs": sum(r.input_tokens is None or r.output_tokens is None for r in runs),
        "input_tokens": sum(r.input_tokens or 0 for r in runs),
        "output_tokens": sum(r.output_tokens or 0 for r in runs),
        "total_tokens": sum(r.total_tokens or 0 for r in runs),
        "duration_ms": sum(r.duration_ms or 0 for r in runs),
        "estimated_cost_usd": round(sum(cost_values), 8) if cost_values else None,
        "models": sorted({r.model for r in runs if r.model}),
        "efforts": sorted({r.effort for r in runs if r.effort}),
        "cost_basis": "published API rates" if cost_values else "Codex quota or provider usage unavailable",
    }


def artifact_files(p):
    circuit = p.circuit
    status = "HUMAN-APPROVED RELEASE" if approved(p, Gate.RELEASE) else "DRAFT — NOT RELEASED FOR MANUFACTURING"
    banner = f"# {p.name}\n\n{status}\n\nProject {p.id}, version {p.version}\n\n"
    req = p.requirements.values.model_dump()
    findings = [f for report in (p.design_review, p.import_review) if report for f in report.findings]
    files = {
        "project.json": p.model_dump_json(indent=2),
        "requirements.json": json_text(p.requirements),
        "requirements.md": banner + "## Requirements\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in req.items()) + "\n\n## Block diagram\n\n```mermaid\n" + p.requirements.block_diagram + "\n```\n\n## Power tree\n\n" + p.requirements.power_tree,
        "datasheet_sources.json": json_text([s.model_dump() for s in p.sources]),
        "research.json": json_text(p.research),
        "parts_candidates.json": json_text(p.discovery),
        "circuit.json": json_text(circuit),
        "design_constraints.json": json_text([c.model_dump() for c in circuit.constraints] if circuit else []),
        "approvals.json": json_text([a.model_dump(mode="json") for a in p.approvals]),
        "gates.json": json_text(gate_status(p)),
        "file_versions.json": json_text([f.model_dump() for f in p.files]),
        "agent_runs.json": json_text([r.model_dump() for r in p.runs]),
        "usage_report.json": json_text(usage_summary(p)),
        "review_report.md": banner + "## Findings\n\n" + ("\n".join(f"- **{f.severity.upper()} / {f.category}**: {f.message} ({', '.join(f.affected)})" for f in findings) or "No review has run / no findings. This does not imply approval.") + "\n\n## Limitations\n\n" + "\n".join("- " + line for report in (p.design_review, p.import_review) if report for line in report.limitations),
        "manufacturing_checklist.md": banner + "\n".join("- [ ] " + s for s in (p.manufacturing.checklist if p.manufacturing else ["Run export review first"])),
        "bringup_test_plan.md": banner + "\n\n".join(f"## {s.order}. {s.action}\n\nPoint: {s.test_point}\n\nExpected: {s.expected}\n\nSTOP: {s.stop_condition}" for s in (p.manufacturing.test_steps if p.manufacturing else [])),
    }
    files["bom.csv"] = csv_text(["references", "quantity", "part_number", "value", "footprint", "supplier", "notes"],
        [(" ".join(b.references), b.quantity, b.part_number, b.value, b.footprint, b.supplier, b.notes) for b in circuit.bom] if circuit else [])
    files["pin_connections.csv"] = csv_text(["net", "from_ref", "from_pin", "from_signal", "to_ref", "to_pin", "to_signal", "status", "evidence_ids", "notes"],
        [(c.net, c.from_ref, c.from_pin, c.from_signal, c.to_ref, c.to_pin, c.to_signal, c.status, " ".join(c.evidence_ids), c.notes) for c in circuit.connections] if circuit else [])
    files["pins.csv"] = csv_text(["component_ref", "number", "name", "direction", "evidence_ids"],
        [(p.component_ref, p.number, p.name, p.direction, " ".join(p.evidence_ids)) for p in circuit.pins] if circuit else [])
    files["circuit_notes.md"] = banner + "## Decoupling\n\n" + "\n".join("- " + s for s in (circuit.decoupling if circuit else [])) + "\n\n## Pull-up / Pull-down\n\n" + "\n".join("- " + s for s in (circuit.pull_resistors if circuit else [])) + "\n\n## Unresolved\n\n" + "\n".join("- " + s for s in (circuit.unresolved if circuit else []))
    return files


def export_zip(p, store):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in artifact_files(p).items():
            archive.writestr(name, content)
        for f in p.files:
            path = store.original_path(p.id, f.sha256)
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != f.sha256:
                raise ValueError(f"Original file missing or modified: {f.name}; restore the exact original before export")
            archive.write(path, "originals/" + f.id + "_" + f.name)
    return stream.getvalue()
