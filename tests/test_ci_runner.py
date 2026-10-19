"""The CI gate must follow the test report, not a runner's process exit status."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_package_tests.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("yuezheng_ci_runner", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_report_passes_without_consulting_the_exit_status():
    passed, detail = load_runner().verdict(
        {"tests": 229, "failures": 0, "errors": 0, "skipped": 4})
    assert passed is True
    assert detail == "229 passed, 4 skipped"


def test_any_recorded_failure_or_error_fails_the_run():
    runner = load_runner()
    assert runner.verdict(
        {"tests": 10, "failures": 1, "errors": 0, "skipped": 0})[0] is False
    assert runner.verdict(
        {"tests": 10, "failures": 0, "errors": 2, "skipped": 0})[0] is False


def test_missing_or_empty_report_never_passes():
    runner = load_runner()
    assert runner.verdict(None)[0] is False
    assert runner.verdict(
        {"tests": 0, "failures": 0, "errors": 0, "skipped": 0})[0] is False


def test_report_totals_are_summed_across_suites(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(
        '<?xml version="1.0"?><testsuites>'
        '<testsuite tests="2" failures="0" errors="0" skipped="1"/>'
        '<testsuite tests="3" failures="0" errors="0" skipped="0"/>'
        '</testsuites>', encoding="utf-8")
    assert load_runner().evaluate_report(report) == {
        "tests": 5, "failures": 0, "errors": 0, "skipped": 1}


def test_unreadable_report_is_not_a_pass(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text("<testsuite", encoding="utf-8")
    runner = load_runner()
    assert runner.evaluate_report(report) is None
    assert runner.verdict(None)[0] is False


def _fake_child(write_report, status):
    def run(*arguments, **keywords):
        write_report()
        return SimpleNamespace(returncode=status)
    return run


def test_clean_report_wins_over_a_nonzero_child_status(tmp_path, monkeypatch, capsys):
    runner = load_runner()
    report = tmp_path / "junit.xml"
    monkeypatch.setenv("YUEZHENG_JUNIT_REPORT", str(report))
    monkeypatch.setattr(runner.subprocess, "run", _fake_child(
        lambda: report.write_text(
            '<testsuite tests="120" failures="0" errors="0" skipped="4"/>', encoding="utf-8"),
        1))
    assert runner.main(["-q"]) == 0
    assert "teardown artifact" in capsys.readouterr().err


def test_failing_report_keeps_the_run_failed(tmp_path, monkeypatch):
    runner = load_runner()
    report = tmp_path / "junit.xml"
    monkeypatch.setenv("YUEZHENG_JUNIT_REPORT", str(report))
    monkeypatch.setattr(runner.subprocess, "run", _fake_child(
        lambda: report.write_text(
            '<testsuite tests="120" failures="1" errors="0" skipped="4"/>', encoding="utf-8"),
        1))
    assert runner.main(["-q"]) == 1


def test_child_that_writes_no_report_fails(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setenv("YUEZHENG_JUNIT_REPORT", str(tmp_path / "missing.xml"))
    monkeypatch.setattr(runner.subprocess, "run",
                        _fake_child(lambda: None, 0))
    assert runner.main(["-q"]) == 1

