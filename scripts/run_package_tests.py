#!/usr/bin/env python3
"""Run the package test suite and decide the result from recorded evidence.

Two GitHub-hosted Windows runner defects make the pytest process exit status
unusable as a gate signal: the runner has returned exit 1 after a clean summary,
and it has delivered a spurious console interrupt in the middle of a run. This
wrapper runs pytest in a child process with the interrupt guard enabled, then
decides from two records the child produces:

* the pytest session record written by ``scripts/pytest_ci_guard.py``, which
  only reports success when the session actually finished (``exitstatus == 0``);
* the JUnit report, which must contain tests and no failure or error.

A missing record, an interrupted session, an empty report or any failure/error
still fails the run. Only the incidental process exit status is ignored.

``YUEZHENG_JUNIT_REPORT`` chooses the report path (CI uploads it).
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree


def evaluate_report(path):
    """Return JUnit suite totals, or None when the report is absent/unreadable."""
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return None
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in totals:
            try:
                totals[key] += int(suite.get(key, 0) or 0)
            except ValueError:
                return None
    return totals


def evaluate_session(path):
    """Return the session record, or None when pytest never finished."""
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    return record


def verdict(totals, session):
    """Decide from the session record and report; never from the exit status."""
    if session is None:
        return False, "pytest did not record a completed session"
    if session.get("exitstatus") != 0:
        return False, (f"pytest session ended with exit status {session.get('exitstatus')}"
                       " (interrupted or internal error)")
    if session.get("testsfailed"):
        return False, f"{session['testsfailed']} test(s) failed in the pytest session"
    if totals is None:
        return False, "no readable JUnit report"
    if totals["tests"] == 0:
        return False, "the report contains no tests"
    if totals["failures"] or totals["errors"]:
        return False, f"{totals['failures']} failure(s), {totals['errors']} error(s)"
    return True, f"{totals['tests']} passed, {totals['skipped']} skipped"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    report = Path(os.environ.get("YUEZHENG_JUNIT_REPORT")
                  or Path(tempfile.gettempdir()) / f"yuezheng-package-tests-{os.getpid()}.xml")
    session_path = report.with_suffix(".session.json")
    report.unlink(missing_ok=True)
    session_path.unlink(missing_ok=True)
    if not any(argument == "--junitxml" or argument.startswith("--junitxml=") for argument in argv):
        argv.append("--junitxml=" + str(report))
    print(f"Yuezheng package tests: JUnit report at {report}", flush=True)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [
        str(Path(__file__).resolve().parent), environment.get("PYTHONPATH")]))
    environment["YUEZHENG_SESSION_RESULT"] = str(session_path)
    if os.name == "nt":
        environment["YUEZHENG_IGNORE_CONSOLE_INTERRUPT"] = "1"
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "pytest_ci_guard", *argv],
            env=environment)
        status = completed.returncode
    except KeyboardInterrupt:
        return 130
    passed, detail = verdict(evaluate_report(report), evaluate_session(session_path))
    if passed:
        if status:
            print(f"pytest exited {status} but the session and report are clean ({detail}). "
                  "The exit status is a runner teardown artifact; the records decide.",
                  file=sys.stderr, flush=True)
        else:
            print(f"Package tests passed: {detail}.", flush=True)
        return 0
    print(f"Package tests failed: {detail} (pytest exited {status}).",
          file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
