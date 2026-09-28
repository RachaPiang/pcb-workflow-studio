"""Double-click friendly Windows launcher; server runs without a console window."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"


def health():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=1) as response:
            return json.load(response).get("app") == "pcb-workflow-studio"
    except Exception:
        return False


def main():
    if "--stop" in sys.argv:
        if not health():
            print("PCB Studio is not running.")
            return
        with urllib.request.urlopen(URL + "/api/bootstrap", timeout=3) as response:
            token = json.load(response)["token"]
        request = urllib.request.Request(URL + "/api/shutdown", method="POST", data=b"{}", headers={"X-PCB-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3):
            print("PCB Studio stopped.")
        return
    if not health():
        (ROOT / "data").mkdir(exist_ok=True)
        with (ROOT / "data" / "server.log").open("ab") as log:
            subprocess.Popen([sys.executable, str(ROOT / "serve.py")], cwd=ROOT, stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        for _ in range(50):
            if health():
                break
            time.sleep(0.2)
        else:
            raise SystemExit("Unable to start. See data/server.log (port 8765 may be in use).")
    if "--no-browser" not in sys.argv:
        webbrowser.open(URL)
    print(f"PCB Workflow Studio is running at {URL}")


if __name__ == "__main__":
    main()
