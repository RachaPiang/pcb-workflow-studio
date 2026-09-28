"""Cancellation scoped to the worker, never to unrelated Codex sessions."""
from contextvars import ContextVar
import os
import subprocess
import time

cancel_event = ContextVar("pcb_cancel_event", default=None)


class JobCancelled(ValueError):
    pass


def check_cancelled():
    event = cancel_event.get()
    if event is not None and event.is_set():
        raise JobCancelled("หยุดงานแล้ว ผลขั้นตอนที่สำเร็จยังอยู่ กดทำต่อเมื่อต้องการ")


def run_process(args, *, input, timeout, **kwargs):
    if cancel_event.get() is None:
        return subprocess.run(args, input=input, timeout=timeout, capture_output=True, **kwargs)
    check_cancelled()
    started = time.monotonic()
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    try:
        first = True
        while True:
            check_cancelled()
            if time.monotonic() - started >= timeout:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                stdout, stderr = process.communicate(input=input if first else None, timeout=0.25)
                check_cancelled()
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                first = False
    finally:
        if process.poll() is None:
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if process.poll() is None:
                process.kill()
        process.communicate()
