"""pytest plugin used by ``scripts/run_package_tests.py``.

The hosted Windows runner has delivered a console interrupt to the pytest
process in the middle of a run (``16 passed`` followed by ``KeyboardInterrupt``
from ``importlib._bootstrap_external``), even though nothing in the tests asks
for one. The wrapper enables the signal guard for that platform and records the
session result, so the run is judged by data instead of by a process exit status
the runner does not preserve.
"""
import json
import os
import signal


def pytest_configure(config):
    if os.name == "nt" and os.environ.get("YUEZHENG_IGNORE_CONSOLE_INTERRUPT") == "1":
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, signal.SIG_IGN)


def pytest_sessionfinish(session, exitstatus):
    destination = os.environ.get("YUEZHENG_SESSION_RESULT")
    if not destination:
        return
    record = {
        "exitstatus": int(exitstatus),
        "testsfailed": int(session.testsfailed),
        "testscollected": int(session.testscollected),
    }
    with open(destination, "w", encoding="utf-8") as stream:
        json.dump(record, stream)
