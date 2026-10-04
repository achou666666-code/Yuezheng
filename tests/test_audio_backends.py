import json
from pathlib import Path
import subprocess
import wave

import pytest

from scorebridge.audio.backends import engine_python, install_backend, _run
from scorebridge.audio.transcribe import select_engines, transcribe_audio, validate_events


def record(pitch=60):
    return {"schema_version": 1, "recognizer": "basic_pitch",
            "tracks": [{"id": "lead", "gm_program": None, "instrument_source": "unresolved"}],
            "events": [{"kind": "note", "track": "lead", "midi_pitch": pitch, "velocity": 80,
                        "start_seconds": .1, "end_seconds": .8}]}


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "recording.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 8000)
    monkeypatch.delenv("SCOREBRIDGE_FFMPEG", raising=False)
    monkeypatch.setattr("scorebridge.audio.transcribe.shutil.which", lambda name: None)
    monkeypatch.setattr("scorebridge.audio.transcribe.backend_status",
                        lambda *args: {"installed": True, "version_installed": "test"})
    monkeypatch.setattr("scorebridge.audio.transcribe.record_inference", lambda *args: None)
    return path


def fake_inference(data, calls):
    def run(engine, source, destination, *args):
        calls.append(engine)
        Path(destination).write_text(json.dumps(data))
        return data
    return run


def test_piano_and_mixed_routes_do_not_choose_piano_for_unknown_audio():
    assert select_engines("piano")[0] == "transkun"
    assert select_engines("mixed")[0] == "yourmt3"
    assert select_engines()[0] == "yourmt3"
    assert select_engines("solo")[0] == "basic_pitch"
    with pytest.raises(ValueError):
        select_engines(engine="demucs")


def test_backend_override_is_external_not_modified(tmp_path, monkeypatch):
    python = tmp_path / "external" / "python"
    monkeypatch.setenv("SCOREBRIDGE_AUDIO_BASIC_PITCH_PYTHON", str(python))
    assert engine_python("basic_pitch") == python
    result = install_backend("basic_pitch", str(tmp_path / "cache"))
    assert result["status"] == "error"
    assert not python.parent.exists()


def test_timeout_automatically_switches_engine_without_losing_source(source, tmp_path, monkeypatch):
    calls = []
    successful = fake_inference(record(), calls)
    def run(engine, *args):
        if engine == "yourmt3":
            calls.append(engine)
            raise subprocess.TimeoutExpired("model", 1)
        return successful(engine, *args)
    monkeypatch.setattr("scorebridge.audio.transcribe.run_backend", run)
    original = source.read_bytes()
    report = transcribe_audio(str(source), str(tmp_path / "out"), hint="mixed", auto_install=False)
    assert report["status"] == "transcribed"
    assert calls == ["yourmt3", "basic_pitch"]
    assert source.read_bytes() == original
    assert Path(report["original_audio"]).read_bytes() == original
    assert report["attempts"][0]["status"] == "error"
    assert report["accuracy"] == "not_measured"
    assert report["warnings"]
    result = json.loads(Path(report["events_path"]).read_text())
    assert result["tracks"][0]["gm_program"] is None


def test_unchanged_job_reuses_verified_event_artifact(source, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("scorebridge.audio.transcribe.run_backend", fake_inference(record(), calls))
    first = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    second = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    assert first["status"] == second["status"] == "transcribed"
    assert second["reused"] is True
    assert calls == ["basic_pitch"]


def test_changed_source_is_not_reused(source, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("scorebridge.audio.transcribe.run_backend", fake_inference(record(), calls))
    first = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    payload = bytearray(source.read_bytes()); payload[-1] = 1; source.write_bytes(payload)
    second = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    assert first["source_sha256"] != second["source_sha256"]
    assert first["job_dir"] != second["job_dir"]
    assert calls == ["basic_pitch", "basic_pitch"]


def test_tampered_final_artifact_is_reconstructed_from_candidate(source, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("scorebridge.audio.transcribe.run_backend", fake_inference(record(), calls))
    first = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    Path(first["events_path"]).write_text("{}");
    second = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    assert second["status"] == "transcribed" and not second["reused"]
    assert json.loads(Path(second["events_path"]).read_text())["events"][0]["midi_pitch"] == 60


def test_combination_keeps_candidates_without_doubling_notes(source, tmp_path, monkeypatch):
    calls = []
    def run(engine, *args):
        return fake_inference(record(60 if engine == "basic_pitch" else 61), calls)(engine, *args)
    monkeypatch.setattr("scorebridge.audio.transcribe.run_backend", run)
    report = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False, combine=True)
    assert len(report["candidates"]) == 2
    assert report["event_count"] == 1
    assert report["requires_agent_resolution"]


def test_failed_job_can_resume_without_overwriting_existing_music(source, tmp_path, monkeypatch):
    def fail(*args):
        raise ValueError("corrupt model")
    monkeypatch.setattr("scorebridge.audio.transcribe.run_backend", fail)
    failed = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    assert failed["status"] == "error"
    assert len(failed["attempts"]) == 2
    assert Path(failed["original_audio"]).is_file()
    assert not (Path(failed["job_dir"]) / ".lock").exists()
    monkeypatch.setattr("scorebridge.audio.transcribe.run_backend", fake_inference(record(), []))
    recovered = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    assert recovered["status"] == "transcribed"
    assert recovered["job_dir"] == failed["job_dir"]


def test_modified_candidate_is_not_trusted_when_recovering(source, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("scorebridge.audio.transcribe.run_backend", fake_inference(record(), calls))
    first = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    Path(first["events_path"]).write_text("{}")
    Path(first["candidates"][0]["events_path"]).write_text(json.dumps(record(61)))
    second = transcribe_audio(str(source), str(tmp_path / "out"), hint="solo", auto_install=False)
    assert calls == ["basic_pitch", "basic_pitch"]
    assert json.loads(Path(second["events_path"]).read_text())["events"][0]["midi_pitch"] == 60


@pytest.mark.parametrize("change", [
    {"midi_pitch": True}, {"midi_pitch": 128}, {"start_seconds": float("nan")},
    {"end_seconds": .01}, {"velocity": 0}, {"track": "missing"}, {"end_seconds": 3},
])
def test_malformed_model_events_are_not_published(change):
    data = record(); data["events"][0].update(change)
    with pytest.raises(ValueError):
        validate_events(data, duration=1)


def test_no_install_option_does_not_start_downloads(source, tmp_path, monkeypatch):
    monkeypatch.setattr("scorebridge.audio.transcribe.backend_status", lambda *args: {"installed": False})
    monkeypatch.setattr("scorebridge.audio.transcribe.install_backend", lambda *args: pytest.fail("unexpected download"))
    report = transcribe_audio(str(source), str(tmp_path / "out"), auto_install=False)
    assert report["status"] == "error"
    assert all("disabled" in entry["error"] for entry in report["attempts"])


def test_real_process_timeout_releases_model_child(tmp_path):
    import os
    import sys
    import time
    if os.name == "nt":
        pytest.skip("POSIX process-group fixture")
    artifact = tmp_path / "orphan.txt"
    child = "import time; from pathlib import Path; time.sleep(.7); Path(" + repr(str(artifact)) + ").write_text('orphan')"
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(10)"
    with pytest.raises(subprocess.TimeoutExpired):
        _run([sys.executable, "-c", parent], timeout=.2)
    time.sleep(.8)
    assert not artifact.exists()
