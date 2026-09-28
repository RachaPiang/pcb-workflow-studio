"""Read-only, bounded importers. Unknown formats are explicitly unsupported."""
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import PurePosixPath

from pypdf import PdfReader

from .schemas import DatasheetSource, FileVersion, ReviewFinding, ReviewResult

MAX_UPLOAD = 20 * 1024 * 1024


def extract_pdf(data: bytes, research=False):
    """Runs in a separate process so malformed PDFs cannot hang the application."""
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("PDF ต้องไม่ต้องใช้รหัสผ่านในการเปิด")
    if len(reader.pages) > (1000 if research else 200):
        raise ValueError("PDF ต้องไม่เข้ารหัสและไม่เกิน 200 หน้า; แบ่งเอกสารก่อนนำเข้า")
    pages, total, truncated = {}, 0, []
    selected = list(range(len(reader.pages)))
    if research and len(selected) > 80:
        selected = selected[:60] + selected[-15:]
    for index in selected:
        number, page = index + 1, reader.pages[index]
        raw = page.extract_text() or ""
        content = raw[:30000]
        if len(raw) > len(content):
            truncated.append(number)
        total += len(content)
        if total > 1000000:
            raise ValueError("PDF text เกิน 1 ล้านตัวอักษร; แบ่งเอกสารก่อนนำเข้า")
        pages[number] = content
    summary = {"supported": True, "pages": pages, "page_count": len(reader.pages), "truncated_pages": truncated,
               "selected_pages": list(pages), "partial": len(pages) < len(reader.pages),
               "limitation": "PDF text extraction อาจอ่านตารางผิด; ตรวจรูปต้นฉบับก่อนยืนยันข้อเท็จจริง ไม่มี OCR"}
    if truncated:
        summary["limitation"] += "; บางหน้าถูกตัดข้อความที่ 30,000 ตัวอักษร ดู truncated_pages"
    if summary["partial"]:
        summary["limitation"] += "; อ่านเฉพาะ 60 หน้าแรกและ 15 หน้าสุดท้ายของเอกสารใหญ่ ต้นฉบับเก็บครบทุกหน้า"
    if not any(t.strip() for t in pages.values()):
        summary["supported"] = False
        summary["limitation"] = "ไม่พบข้อความใน PDF; อาจเป็นภาพสแกน ต้องใช้ OCR ภายนอกแล้วตรวจเทียบต้นฉบับ"
    return summary


def decode(data: bytes):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("ไฟล์ข้อความต้องเข้ารหัส UTF-8") from None


def parse_bom(data):
    content = decode(data)
    rows = list(csv.DictReader(io.StringIO(content)))
    if not rows or len(rows) > 10000:
        raise ValueError("BOM ต้องมีข้อมูล 1–10,000 แถว")
    aliases = {"references": ("references", "reference", "designator", "designators", "ref"),
               "quantity": ("quantity", "qty"), "part_number": ("part_number", "mpn", "manufacturer part", "manufacturer part number"),
               "value": ("value", "name", "comment"), "footprint": ("footprint", "package")}
    parsed = []
    for row in rows:
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k is not None}
        mapped = {field: next((row[k] for k in keys if k in row), "") for field, keys in aliases.items()}
        refs = [r for r in re.split(r"[,;\s]+", mapped["references"]) if r]
        if not refs:
            raise ValueError("BOM ต้องมีคอลัมน์ Designator / references")
        try:
            quantity = int(mapped["quantity"]) if mapped["quantity"] else len(refs)
        except ValueError:
            raise ValueError("BOM quantity ต้องเป็นจำนวนเต็ม") from None
        if quantity < 1:
            raise ValueError("BOM quantity ต้องมากกว่า 0")
        parsed.append({**mapped, "references": refs, "quantity": quantity})
    return {"supported": True, "rows": parsed, "row_count": len(parsed)}


def parse_netlist(data):
    try:
        doc = json.loads(decode(data))
    except ValueError:
        return {"supported": False, "limitation": "Netlist รุ่นนี้รองรับ normalized JSON เท่านั้น; ดูตัวอย่างใน examples/"}
    if not isinstance(doc, dict) or not isinstance(doc.get("nets"), list) or not doc["nets"]:
        return {"supported": False, "limitation": "รูปแบบ netlist ไม่ตรง schema {nets:[{name,nodes:[{ref,pin}]}]}"}
    nets, names, seen = [], set(), {}
    for net in doc["nets"]:
        if not isinstance(net, dict) or not isinstance(net.get("name"), str) or not net["name"].strip() or not isinstance(net.get("nodes"), list) or not net["nodes"]:
            raise ValueError("Netlist มี net ที่ไม่ถูกต้อง")
        if net["name"] in names:
            raise ValueError("Netlist มีชื่อ net ซ้ำ")
        names.add(net["name"])
        nodes = []
        for node in net["nodes"]:
            if not isinstance(node, dict) or not all(isinstance(node.get(k), str) and node[k].strip() for k in ("ref", "pin")):
                raise ValueError("Netlist node ต้องมี ref และ pin เป็น string")
            key = (node["ref"], node["pin"])
            if key in seen:
                raise ValueError("Netlist มี endpoint ซ้ำ / อยู่หลาย net")
            seen[key] = net["name"]
            nodes.append({"ref": node["ref"], "pin": node["pin"]})
        nets.append({"name": net["name"], "nodes": nodes})
    return {"supported": True, "nets": nets}


def parse_drc(data):
    try:
        doc = json.loads(decode(data))
    except ValueError:
        return {"supported": False, "limitation": "DRC ต้องเป็น normalized JSON พร้อม completed=true, tool, revision และ issues; ไม่ตีความข้อความว่า pass"}
    if not isinstance(doc, dict) or doc.get("completed") is not True or not isinstance(doc.get("issues"), list) or not doc.get("tool") or not doc.get("revision"):
        return {"supported": False, "limitation": "DRC ขาดหลักฐานว่ารันครบ / tool / revision / issues"}
    for issue in doc["issues"]:
        if not isinstance(issue, dict) or issue.get("severity") not in ("critical", "error", "warning", "info") or not isinstance(issue.get("message"), str) or not issue["message"].strip():
            raise ValueError("DRC issue ไม่ตรง schema")
    return {"supported": True, "tool": str(doc["tool"]), "revision": str(doc["revision"]), "issues": doc["issues"], "completed": True}


def parse_gerber(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 300 or sum(e.file_size for e in entries) > 80 * 1024 * 1024:
                raise ValueError("ZIP เกินขีดจำกัด 300 entries / 80 MB uncompressed")
            files, roles = [], set()
            for entry in entries:
                path = PurePosixPath(entry.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts or ":" in entry.filename or entry.flag_bits & 1:
                    raise ValueError("ZIP มี path ไม่ปลอดภัยหรือไฟล์เข้ารหัส")
                if entry.file_size > 20 * 1024 * 1024 or (entry.file_size > 1000000 and entry.file_size / max(entry.compress_size, 1) > 200):
                    raise ValueError("ZIP มีรายการขนาดหรือ compression ratio สูงผิดปกติ")
                if entry.is_dir():
                    continue
                body = archive.read(entry).decode("ascii", errors="replace")
                name = path.name.lower()
                role = "other"
                is_gerber = "%FS" in body and ("M02*" in body or "M00*" in body)
                if is_gerber:
                    for suffix, candidate in {".gtl": "top_copper", ".gbl": "bottom_copper", ".gts": "top_mask", ".gbs": "bottom_mask", ".gko": "outline", ".gm1": "outline", ".g1": "inner1", ".g2": "inner2", ".g1l": "inner1", ".g2l": "inner2"}.items():
                        if name.endswith(suffix):
                            role = candidate
                    if role == "other":
                        lower = name.replace("_", "").replace("-", "")
                        for term, candidate in {"toplayer": "top_copper", "bottomlayer": "bottom_copper", "topsoldermask": "top_mask", "bottomsoldermask": "bottom_mask", "boardoutline": "outline", "inner1": "inner1", "inner2": "inner2"}.items():
                            if term in lower:
                                role = candidate
                if name.endswith((".drl", ".xln", ".txt")) and "M48" in body and ("M30" in body or "%" in body):
                    role = "drill"
                roles.add(role)
                files.append({"name": entry.filename, "size": entry.file_size, "role": role})
            return {"supported": True, "entries": files, "roles": sorted(roles), "limitation": "ตรวจชื่อและ signature เท่านั้น; ยังไม่ได้ตรวจ geometry, registration หรือ manufacturability"}
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ValueError("อ่าน Gerber ZIP ไม่สำเร็จ") from None


def inspect_file(name: str, kind: str, data: bytes, research_pdf=False) -> FileVersion:
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("ไฟล์ต้องมีข้อมูลและขนาดไม่เกิน 20 MB")
    name = name.replace("\\", "/").split("/")[-1][:200]
    if not name or any(ord(c) < 32 for c in name):
        raise ValueError("ชื่อไฟล์ไม่ถูกต้อง")
    summary = {"supported": False, "limitation": "เก็บไฟล์ต้นฉบับไว้สำหรับตรวจด้วยตนเอง"}
    if kind == "bom":
        summary = parse_bom(data)
    elif kind == "netlist":
        summary = parse_netlist(data)
    elif kind == "drc":
        summary = parse_drc(data)
    elif kind == "gerber":
        summary = parse_gerber(data)
    elif kind == "easyeda":
        doc = json.loads(decode(data))
        if not isinstance(doc, dict):
            raise ValueError("EasyEDA source ต้องเป็น JSON object")
        summary = {"supported": False, "keys": list(doc)[:40], "shape_count": len(doc.get("shape", [])) if isinstance(doc.get("shape"), list) else None,
                   "limitation": "ตรวจ JSON structure ได้ แต่ยังไม่ได้แปล proprietary EasyEDA shapes เป็น netlist; ต้องนำเข้า normalized netlist แยก"}
    elif kind in ("schematic_image", "pcb_image"):
        if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
            raise ValueError("ภาพต้องเป็น PNG หรือ JPEG")
        summary = {"supported": False, "limitation": "ภาพสำหรับมนุษย์ตรวจ; MVP ยังไม่มี vision/geometry review"}
    elif kind == "datasheet":
        if not data.startswith(b"%PDF-"):
            raise ValueError("Datasheet ต้องเป็น PDF")
        try:
            from pathlib import Path
            result = subprocess.run([sys.executable, "-m", "pcb_assistant.pdf_worker"] + (["--research"] if research_pdf else []), input=data, capture_output=True,
                                    timeout=30, cwd=Path(__file__).resolve().parent.parent,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            parsed = json.loads(result.stdout)
            if result.returncode or "error" in parsed:
                raise ValueError(parsed.get("error", "อ่าน PDF ไม่สำเร็จ"))
            summary = parsed
        except subprocess.TimeoutExpired:
            raise ValueError("อ่าน PDF เกินเวลา 30 วินาที; ลองแบ่งเอกสารเป็นไฟล์เล็กลง") from None
        except ValueError:
            raise
        except Exception:
            raise ValueError("อ่าน PDF ไม่สำเร็จ; ตรวจไฟล์ต้นฉบับ") from None
    return FileVersion(name=name, kind=kind, sha256=hashlib.sha256(data).hexdigest(), size=len(data), summary=summary)


def review_imports(files, circuit, layers):
    result = ReviewResult(limitations=["EasyEDA source และภาพเก็บเป็นหลักฐานสำหรับ manual review; ไม่แก้ไฟล์ต้นฉบับ", "Netlist/DRC รองรับ normalized JSON เท่านั้น; unknown format ไม่ถูกถือว่าผ่าน"])
    active = [f for f in files if f.active and f.kind != "datasheet"]
    def add(severity, category, msg, file=None):
        result.findings.append(ReviewFinding(severity=severity, category=category, message=msg, affected=[file.name] if file else []))
    for kind, category in (("bom", "schematic"), ("netlist", "schematic"), ("drc", "pcb"), ("gerber", "release")):
        if not any(f.kind == kind and f.summary.get("supported") for f in active):
            add("error", category, f"ขาดไฟล์ {kind} ที่อ่านได้สำหรับตรวจขั้น {category}")
    if not any(f.kind in ("easyeda", "schematic_image") for f in active):
        add("error", "schematic", "ขาด EasyEDA source / ภาพ schematic สำหรับ manual review")
    if not any(f.kind == "pcb_image" for f in active):
        add("error", "pcb", "ขาดภาพ PCB สำหรับ manual layout review")
    for file in active:
        summary = file.summary
        if not summary.get("supported"):
            add("warning", "coverage", summary.get("limitation", "Unsupported format"), file)
            continue
        if file.kind == "drc":
            for issue in summary["issues"]:
                add(issue["severity"], "pcb", issue["message"], file)
        elif file.kind == "bom" and circuit:
            expected = {ref: item for item in circuit.bom for ref in item.references}
            actual, duplicates = {}, set()
            for row in summary["rows"]:
                if row["quantity"] != len(row["references"]):
                    add("error", "schematic", "BOM quantity ไม่ตรงกับจำนวน references", file)
                for ref in row["references"]:
                    if ref in actual:
                        duplicates.add(ref)
                    actual[ref] = row
            if duplicates:
                add("error", "schematic", "BOM reference ซ้ำ: " + ", ".join(sorted(duplicates)), file)
            for ref in sorted(set(expected) | set(actual)):
                if ref not in expected or ref not in actual:
                    add("error", "schematic", f"BOM component ไม่ตรงกับแผน: {ref}", file)
                elif expected[ref].part_number != actual[ref]["part_number"] or expected[ref].footprint != actual[ref]["footprint"]:
                    add("error", "schematic", f"BOM part/footprint ไม่ตรงกับแผน: {ref}", file)
        elif file.kind == "netlist" and circuit:
            actual = {n["name"]: {(p["ref"], p["pin"]) for p in n["nodes"]} for n in summary["nets"]}
            expected = {}
            for con in circuit.connections:
                expected.setdefault(con.net, set()).update([(con.from_ref, con.from_pin), (con.to_ref, con.to_pin)])
            for net in sorted(set(expected) | set(actual)):
                if expected.get(net, set()) != actual.get(net, set()):
                    add("error", "schematic", f"Netlist endpoints ไม่ตรงกับแผน: {net}", file)
        elif file.kind == "gerber":
            required = {"top_copper", "bottom_copper", "top_mask", "bottom_mask", "outline", "drill"}
            if layers == 4:
                required |= {"inner1", "inner2"}
            elif layers not in (1, 2):
                add("error", "release", "Gerber inventory อัตโนมัติรองรับ 1/2/4 layers เท่านั้น", file)
            if layers == 1:
                required.remove("bottom_copper")
            absent = required - set(summary["roles"])
            if absent:
                add("error", "release", "Gerber package ขาด/ไม่รู้จัก: " + ", ".join(sorted(absent)), file)
    return result
