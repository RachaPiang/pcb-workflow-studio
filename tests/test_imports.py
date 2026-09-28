import io
import json
import zipfile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pcb_assistant.importers import inspect_file, parse_bom, parse_drc, parse_gerber, parse_netlist, review_imports


def test_bom_aliases_and_grouped_references():
    result=parse_bom(b'Designator,Qty,Manufacturer Part,Footprint\n"R1,R2",2,RES-10K,0603\n')
    assert result["rows"][0]["references"]==["R1","R2"]
    with pytest.raises(ValueError):parse_bom(b"Name,Qty\nX,1")
    with pytest.raises(ValueError):parse_bom(b"Designator,Qty\nX,-1")


@pytest.mark.parametrize("data",[b"DRC passed, no errors",b'{}',b'{"completed":false,"issues":[]}',b'{"completed":true,"issues":[]}'])
def test_unknown_drc_never_passes(data):
    assert parse_drc(data)["supported"] is False


def test_invalid_drc_severity_rejected():
    with pytest.raises(ValueError):parse_drc(json.dumps({"completed":True,"tool":"test","revision":"v1","issues":[{"severity":"ok","message":"x"}]}).encode())


def test_netlist_unsupported_and_duplicate_endpoints():
    assert not parse_netlist(b"(export (nets))")["supported"]
    doc={"nets":[{"name":"VCC","nodes":[{"ref":"U1","pin":"1"}]},{"name":"GND","nodes":[{"ref":"U1","pin":"1"}]}]}
    with pytest.raises(ValueError):parse_netlist(json.dumps(doc).encode())


def test_gerber_zip_slip_and_fake_layers():
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as z:z.writestr("../../escape.txt","test")
    with pytest.raises(ValueError):parse_gerber(buffer.getvalue())
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as z:z.writestr("board.gtl","this is not gerber")
    assert parse_gerber(buffer.getvalue())["roles"]==["other"]


def test_empty_scan_pdf_is_not_supported():
    stream=io.BytesIO();writer=PdfWriter();writer.add_blank_page(100,100);writer.write(stream)
    result=inspect_file("scan.pdf","datasheet",stream.getvalue())
    assert not result.summary["supported"] and "OCR" in result.summary["limitation"]


def test_pdf_text_extraction_preserves_page_numbers():
    stream=io.BytesIO();writer=PdfWriter();page=writer.add_blank_page(300,300)
    font=DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")]=DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):writer._add_object(font)})})
    content=DecodedStreamObject();content.set_data(b"BT /F1 12 Tf 20 260 Td (SYNTHETIC TEST pin 1 VDD) Tj ET")
    page[NameObject("/Contents")]=writer._add_object(content)
    writer.write(stream)
    result=inspect_file("fixture.pdf","datasheet",stream.getvalue())
    assert result.summary["supported"]
    assert "pin 1 VDD" in result.summary["pages"]["1"]


def test_import_diff_detects_bom_and_net_errors(valid_project):
    bom=inspect_file("bad.csv","bom",b"references,quantity,part_number,footprint\nU1,1,WRONG,TEST-PACKAGE\n")
    net=inspect_file("bad.json","netlist",b'{"nets":[{"name":"VMAIN","nodes":[{"ref":"U1","pin":"9"}]}]}')
    report=review_imports([bom,net],valid_project.circuit,4)
    assert sum(f.severity=="error" for f in report.findings)>=3


def test_original_filename_sanitized_and_images_checked():
    result=inspect_file("../../schematic.json","easyeda",b'{"shape":[]}')
    assert result.name=="schematic.json" and not result.summary["supported"]
    with pytest.raises(ValueError):inspect_file("attack.svg","pcb_image",b"<svg onload='x'/>")
    with pytest.raises(ValueError):inspect_file("empty.csv","bom",b"")
