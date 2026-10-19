"""The CI gate must follow recorded evidence, not a runner's process exit status."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_package_tests.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("yuezheng_ci_runner", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLEAN_SESSION = {"exitstatus": 0, "testsfailed": 0, "testscollected": 229}
CLEAN_REPORT = {"tests": 229, "failures": 0, "errors": 0, "skipped": 4}


def test_clean_session_and_report_pass():
    passed, detail = load_runner().verdict(CLEAN_REPORT, CLEAN_SESSION)
    assert passed is True
    assert detail == "225 passed, 4 skipped"


def test_any_recorded_failure_or_error_fails_the_run():
    runner = load_runner()
    assert runner.verdict({"tests": 10, "failures": 1, "errors": 0, "skipped": 0},
                          CLEAN_SESSION)[0] is False
    assert runner.verdict({"tests": 10, "failures": 0, "errors": 2, "skipped": 0},
                          CLEAN_SESSION)[0] is False
    assert runner.verdict(CLEAN_REPORT,
                          {"exitstatus": 0, "testsfailed": 1, "testscollected": 229})[0] is False


def test_interrupted_session_never_passes_even_with_a_clean_partial_report():
    # The Windows runner interrupted a run after 16 passing tests; the truncated
    # report alone must not be read as success.
    passed, detail = load_runner().verdict(
        {"tests": 16, "failures": 0, "errors": 0, "skipped": 0},
        {"exitstatus": 2, "testsfailed": 0, "testscollected": 229})
    assert passed is False
    assert "interrupted" in detail


def test_missing_session_or_report_never_passes():
    runner = load_runner()
    assert runner.verdict(CLEAN_REPORT, None)[0] is False
    assert runner.verdict(None, CLEAN_SESSION)[0] is False
    assert runner.verdict({"tests": 0, "failures": 0, "errors": 0, "skipped": 0},
                          CLEAN_SESSION)[0] is False


def test_report_totals_are_summed_across_suites(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(
        '<?xml version="1.0"?><testsuites>'
        '<testsuite tests="2" failures="0" errors="0" skipped="1"/>'
        '<testsuite tests="3" failures="0" errors="0" skipped="0"/>'
        '</testsuites>', encoding="utf-8")
    assert load_runner().evaluate_report(report) == {
        "tests": 5, "failures": 0, "errors": 0, "skipped": 1}


def test_unreadable_records_are_not_a_pass(tmp_path):
    runner = load_runner()
    report = tmp_path / "junit.xml"
    report.write_text("<testsuite", encoding="utf-8")
    session = tmp_path / "session.json"
    session.write_text("{not json", encoding="utf-8")
    assert runner.evaluate_report(report) is None
    assert runner.evaluate_session(session) is None


def _fake_child(totals, session, status):
    def run(command, env=None):
        for argument in command:
            if argument.startswith("--junitxml="):
                if totals is not None:
                    Path(argument.split("=", 1)[1]).write_text(
                        f'<testsuite tests="{totals["tests"]}" failures="{totals["failures"]}" '
                        f'errors="{totals["errors"]}" skipped="{totals["skipped"]}"/>',
                        encoding="utf-8")
        if session is not None:
            Path(env["YUEZHENG_SESSION_RESULT"]).write_text(json.dumps(session), encoding="utf-8")
        return SimpleNamespace(returncode=status)
    return run


def test_clean_records_win_over_a_nonzero_child_status(tmp_path, monkeypatch, capsys):
    runner = load_runner()
    monkeypatch.setenv("YUEZHENG_JUNIT_REPORT", str(tmp_path / "junit.xml"))
    monkeypatch.setattr(runner.subprocess, "run", _fake_child(CLEAN_REPORT, CLEAN_SESSION, 1))
    assert runner.main(["-q"]) == 0
    assert "teardown artifact" in capsys.readouterr().err


def test_failing_report_keeps_the_run_failed(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setenv("YUEZHENG_JUNIT_REPORT", str(tmp_path / "junit.xml"))
    broken = {"tests": 229, "failures": 1, "errors": 0, "skipped": 4}
    monkeypatch.setattr(runner.subprocess, "run", _fake_child(broken, CLEAN_SESSION, 1))
    assert runner.main(["-q"]) == 1


def test_child_without_records_fails(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setenv("YUEZHENG_JUNIT_REPORT", str(tmp_path / "junit.xml"))
    monkeypatch.setattr(runner.subprocess, "run", _fake_child(None, None, 0))
    assert runner.main(["-q"]) == 1
