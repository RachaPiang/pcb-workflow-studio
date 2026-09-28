"""Manual UI fixture: localhost:8766, synthetic data, no AI/network provider."""
import tempfile
import time
from pathlib import Path

import uvicorn

from pcb_assistant.api import create_app
from pcb_assistant.cancellation import check_cancelled
from pcb_assistant.orchestrator import Orchestrator, evidence_hash
from pcb_assistant.schemas import Project, Requirement, Gate


def main():
    with tempfile.TemporaryDirectory(prefix='pcb-ui-fixture-') as root:
        app = create_app(Path(root))
        app.state.settings.provider = None
        p = Project(name='UI TEST · Synthetic only', brief='Software fixture only, no real circuit')
        engine = Orchestrator()
        engine.requirements(p, Requirement(mcu='TEST-MCU', layers=4, usb='none', input_voltage=3.3,
            rail_voltage=3.3, max_current_ma=100, assembly='hand', manufacturer='TEST', design_rules='TEST',
            board_size='50 x 40 mm', sensor='none', display='none'))
        engine.approve(p, Gate.REQUIREMENTS, 'Fixture', 'Software fixture only', evidence_hash(p, Gate.REQUIREMENTS))
        app.state.store.save(p, 0, 'Synthetic UI fixture')
        original = Orchestrator.plan
        attempts = 0
        def delayed(self, project):
            nonlocal attempts
            attempts += 1
            self.progress('ทดสอบปุ่มหยุด · ไม่ได้เรียก AI')
            until = time.monotonic() + (30 if attempts == 1 else 2)
            while time.monotonic() < until:
                check_cancelled()
                time.sleep(.05)
            original(self, project)
        Orchestrator.plan = delayed
        uvicorn.run(app, host='127.0.0.1', port=8766, log_level='warning')


if __name__ == '__main__':
    main()
