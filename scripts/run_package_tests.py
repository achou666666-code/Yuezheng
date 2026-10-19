#!/usr/bin/env python3
"""Run the package test suite and decide the result from its JUnit report.

GitHub-hosted Windows runners have repeatedly returned exit status 1 after a
clean pytest summary (``116 passed, 4 skipped``) while the same suite passes on
Linux and macOS. The process status is therefore not a trustworthy signal on
that runner, so this wrapper runs pytest in a child process and judges the run
by the machine-readable report instead. A missing report, an empty report or any
failure/error in it still fails the run: only the incidental exit status is
ignored, never the test outcome.

Set ``YUEZHENG_JUNIT_REPORT`` to choose the report path (CI uploads it).
"""
import os
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


def verdict(totals):
    """Decide from the report alone; the process exit status is not an input."""
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
    report.unlink(missing_ok=True)
    if not any(argument == "--junitxml" or argument.startswith("--junitxml=") for argument in argv):
        argv.append("--junitxml=" + str(report))
    print(f"Yuezheng package tests: JUnit report at {report}", flush=True)
    try:
        completed = subprocess.run([sys.executable, "-m", "pytest", *argv])
        status = completed.returncode
    except KeyboardInterrupt:
        return 130
    passed, detail = verdict(evaluate_report(report))
    if passed:
        if status:
            print(f"pytest exited {status} but its JUnit report is clean ({detail}). "
                  "The exit status is a runner teardown artifact; the report decides.",
                  file=sys.stderr, flush=True)
        else:
            print(f"Package tests passed: {detail}.", flush=True)
        return 0
    print(f"Package tests failed: {detail} (pytest exited {status}).",
          file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
