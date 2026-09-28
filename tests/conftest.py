import pytest
from fastapi.testclient import TestClient

from pcb_assistant.api import create_app
from pcb_assistant.orchestrator import Orchestrator, evidence_hash
from pcb_assistant.schemas import *


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        client.headers["X-PCB-Token"] = client.get("/api/bootstrap").json()["token"]
        yield client


@pytest.fixture
def requirement():
    return Requirement(mcu="TEST-MCU", layers=4, usb="none", input_voltage=3.3,
                       rail_voltage=3.3, max_current_ma=100, assembly="hand", manufacturer="TEST FAB",
                       design_rules="TEST RULES", board_size="50 x 40 mm", sensor="none", display="none")


@pytest.fixture
def valid_project(requirement):
    """Entirely synthetic circuit, used solely to exercise software gate mechanics."""
    p = Project(name="SYNTHETIC TEST ONLY", brief="4-layer MCU sensor workflow SOFTWARE TEST")
    o = Orchestrator()
    o.requirements(p, requirement)
    o.approve(p, Gate.REQUIREMENTS, "Automated test", "Fixture only", evidence_hash(p, Gate.REQUIREMENTS))
    source = DatasheetSource(file_id="synthetic-file", title="Synthetic fixture, not a datasheet", revision="TEST-1", sha256="a"*64,
        pages={1:"TEST-MCU pin 1 VDD and pin 2 GND. TEST-INPUT pin 1 OUT and pin 2 GND. TEST-PACKAGE footprint and TEST-CONNECTOR footprint. Supply range 3.0 to 3.6 V; connector range 0 to 6 V."})
    p.sources=[source]
    facts=[]
    for ref, footprint, low, high, pin_name in (("U1","TEST-PACKAGE",3,3.6,"VDD"),("J1","TEST-CONNECTOR",0,6,"OUT")):
        for kind, claim, quote, number, name in [
            ("footprint",footprint,footprint+" footprint","",""),
            ("voltage",f"{low} to {high} V","Supply range 3.0 to 3.6 V" if ref=="U1" else "connector range 0 to 6 V","",""),
            ("pin",pin_name,"pin 1 "+pin_name,"1",pin_name),
            ("pin","Ground","pin 2 GND","2","GND")]:
            facts.append(Fact(component_ref=ref,kind=kind,claim=claim,source_id=source.id,page=1,quote=quote,
                              status="Confirmed",verified_by="Automated test fixture",pin_number=number,pin_name=name))
    p.research=ResearchResult(facts=facts)
    components=[]
    for ref, pn, package, role, low, high in (("U1","TEST-MCU","TEST-PACKAGE","MCU",3,3.6),("J1","TEST-INPUT","TEST-CONNECTOR","Power input",0,6)):
        components.append(Component(ref=ref,part_number=pn,role=role,rationale="Synthetic software test",footprint=package,
                                    evidence_ids=[f.id for f in facts if f.component_ref==ref],voltage_min=low,voltage_max=high))
    circuit=CircuitResult(components=components,bom=[BOMItem(references=[c.ref],quantity=1,part_number=c.part_number,footprint=c.footprint) for c in components],
        pins=[Pin(component_ref=f.component_ref,number=f.pin_number,name=f.pin_name,evidence_ids=[f.id]) for f in facts if f.kind=="pin"],
        nets=[Net(name="VMAIN",voltage=3.3),Net(name="GND",voltage=0)],
        connections=[Connection(net="VMAIN",from_ref="J1",from_pin="1",from_signal="OUT",to_ref="U1",to_pin="1",to_signal="VDD",evidence_ids=[f.id for f in facts if f.kind=="pin"]),
                     Connection(net="GND",from_ref="J1",from_pin="2",from_signal="GND",to_ref="U1",to_pin="2",to_signal="GND",evidence_ids=[f.id for f in facts if f.kind=="pin"])])
    o.circuit(p,circuit)
    return p
