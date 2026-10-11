import pytest
from pathlib import Path, PurePosixPath
import os
from scorebridge.musescore import MuseScoreAdapter, MuseScoreError

def test_convert_checks_input_before_launch(tmp_path):
    executable = tmp_path / ("fake-mscore.exe" if os.name == "nt" else "fake-mscore")
    executable.write_bytes(b"fake")
    adapter = MuseScoreAdapter(executable=str(executable))
    with pytest.raises(MuseScoreError, match="Input does not exist"):
        adapter.convert(str(tmp_path / "missing.musicxml"), str(tmp_path / "out.mscz"))


def test_invalid_explicit_executable_does_not_fall_back(tmp_path):
    assert MuseScoreAdapter(executable=str(tmp_path / 'missing')).resolve() is None


def test_open_score_checks_input_before_launch(tmp_path):
    executable = tmp_path / ("fake-mscore.exe" if os.name == "nt" else "fake-mscore")
    executable.write_bytes(b"fake")
    adapter = MuseScoreAdapter(executable=str(executable))
    with pytest.raises(MuseScoreError, match="Input does not exist"):
        adapter.open_score(str(tmp_path / "missing.mscz"))


def test_open_score_reports_process(monkeypatch, tmp_path):
    import subprocess
    source = tmp_path / "source.mscz"
    source.write_bytes(b"score")
    class Process:
        pid = 4242
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Process())
    adapter = MuseScoreAdapter(executable="/bin/true")
    monkeypatch.setattr(adapter, "resolve", lambda: source)
    result = adapter.open_score(str(source))
    assert result["status"] == "pass"
    assert result["pid"] == 4242
    assert result["command"][-1] == str(source.resolve())


def test_open_score_uses_macos_document_event_for_app_bundle(monkeypatch, tmp_path):
    import scorebridge.musescore.adapter as adapter_module
    source = tmp_path / "source.mscz"
    source.write_bytes(b"score")
    calls = []
    class Process:
        pid = 99
    monkeypatch.setattr(adapter_module.sys, "platform", "darwin")
    monkeypatch.setattr(adapter_module.subprocess, "Popen",
                        lambda command, **kwargs: calls.append(command) or Process())
    adapter = MuseScoreAdapter()
    monkeypatch.setattr(adapter, "resolve",
                        lambda: PurePosixPath("/Applications/MuseScore 4.app/Contents/MacOS/mscore"))
    result = adapter.open_score(str(source))
    assert calls == [["/usr/bin/open", "-a", "/Applications/MuseScore 4.app", str(source.resolve())]]
    assert result["command"] == calls[0]


def test_launch_score_process_returns_real_musescore_pid(monkeypatch, tmp_path):
    import scorebridge.musescore.adapter as adapter_module
    source = tmp_path / "source.mscz"
    source.write_bytes(b"score")
    calls = []
    class Process:
        pid = 777
    monkeypatch.setattr(adapter_module.subprocess, "Popen",
                        lambda command, **kwargs: calls.append(command) or Process())
    executable = tmp_path / ("fake-mscore.exe" if os.name == "nt" else "fake-mscore")
    executable.write_bytes(b"fake")
    adapter = MuseScoreAdapter(executable=str(executable))
    result = adapter.launch_score_process(str(source))
    assert calls == [[str(executable), str(source.resolve())]]
    assert result["pid"] == 777
    assert result["launch_mode"] == "dedicated_process"


def test_macos_dedicated_launch_uses_open_new_and_discovers_pid(monkeypatch, tmp_path):
    import subprocess
    import scorebridge.musescore.adapter as adapter_module
    source = tmp_path / "source.mscz"
    source.write_bytes(b"score")
    calls = []
    monkeypatch.setattr(adapter_module.sys, "platform", "darwin")
    monkeypatch.setattr(adapter_module.subprocess, "run",
                        lambda command, **kwargs: calls.append(command) or subprocess.CompletedProcess(command, 0))
    adapter = MuseScoreAdapter()
    executable = PurePosixPath("/Applications/MuseScore 4.app/Contents/MacOS/mscore")
    monkeypatch.setattr(adapter, "resolve", lambda: executable)
    states = iter(({11}, {11, 22}))
    monkeypatch.setattr(adapter, "_running_musescore_pids", lambda exe: next(states))
    result = adapter.launch_score_process(str(source))
    assert calls == [["/usr/bin/open", "-n", "-a", "/Applications/MuseScore 4.app", str(source.resolve())]]
    assert result["pid"] == 22


def test_failed_conversion_cannot_reuse_old_output(tmp_path, monkeypatch):
    import subprocess
    from zipfile import ZipFile
    source = tmp_path / 'source.musicxml'; source.write_text('<score-partwise/>')
    target = tmp_path / 'old.mscz'
    with ZipFile(target, 'w') as archive:
        archive.writestr('old.mscx', '<museScore/>')
    original = target.read_bytes()
    monkeypatch.setattr(MuseScoreAdapter, 'resolve', lambda self: source)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess([], 1, '', 'failed'))
    with pytest.raises(MuseScoreError, match='failed'):
        MuseScoreAdapter().convert(str(source), str(target))
    assert target.read_bytes() == original
