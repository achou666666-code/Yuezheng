"""Agent-facing engine routing, actual inference, and source-linked job recovery."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import wave

from .backends import ENGINES, backend_status, install_backend, run_backend, record_inference, engine_python


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def select_engines(hint="auto", engine="auto"):
    """Hints come from the Agent's task assessment, not a required user questionnaire."""
    choices = {"auto": ["yourmt3", "basic_pitch"], "mixed": ["yourmt3", "basic_pitch"],
               "piano": ["transkun", "yourmt3", "basic_pitch"],
               "solo": ["basic_pitch", "yourmt3"]}
    if hint not in choices:
        raise ValueError("hint must be auto, solo, piano or mixed")
    if engine != "auto" and (engine not in ENGINES or ENGINES[engine]["kind"] != "transcription"):
        raise ValueError("engine must be auto, basic_pitch, transkun or yourmt3")
    order = choices[hint]
    return order if engine == "auto" else [engine] + [item for item in order if item != engine]


def validate_events(record, duration=None):
    """Check the result's integrity. This is not an accuracy estimate."""
    if not isinstance(record, dict) or not isinstance(record.get("events"), list):
        raise ValueError("Engine result must contain an events list")
    tracks = record.get("tracks", [])
    if not isinstance(tracks, list):
        raise ValueError("tracks must be a list")
    identifiers = [track.get("id") for track in tracks]
    if any(not isinstance(i, str) or not i for i in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Track identities must be unique nonempty strings")
    for event in record["events"]:
        if not isinstance(event, dict) or event.get("kind") not in {"note", "drum"}:
            raise ValueError("Invalid note/drum event")
        pitch, velocity = event.get("midi_pitch"), event.get("velocity", 80)
        if isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 127:
            raise ValueError("Invalid MIDI pitch")
        if isinstance(velocity, bool) or not isinstance(velocity, int) or not 1 <= velocity <= 127:
            raise ValueError("Invalid MIDI velocity")
        start, end = event.get("start_seconds"), event.get("end_seconds")
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end))
                or not 0 <= start < end or duration is not None and end > duration + .5):
            raise ValueError("Invalid event time or event outside source duration")
        if tracks and event.get("track") not in identifiers:
            raise ValueError("Event refers to an absent track")
    return record


def _decode(source, output):
    ffmpeg = os.environ.get("SCOREBRIDGE_FFMPEG") or shutil.which("ffmpeg")
    if ffmpeg:
        result = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(source),
                                 "-vn", "-map_metadata", "-1", "-c:a", "pcm_s16le", str(output)],
                                capture_output=True, text=True, timeout=300)
        if result.returncode:
            raise ValueError("Audio decode failed: " + result.stderr[-2000:])
    else:
        shutil.copyfile(source, output)
    with wave.open(str(output), "rb") as stream:
        if stream.getsampwidth() != 2 or not stream.getnframes():
            raise ValueError("Decoder requires nonempty PCM16 WAV; install ffmpeg for other audio formats")
        return {"duration_seconds": stream.getnframes() / stream.getframerate(),
                "channels": stream.getnchannels(), "sample_rate": stream.getframerate()}


def transcribe_audio(input_path, output_dir, hint="auto", engine="auto", cache_dir="",
                     auto_install=True, fallback=True, combine=False, device="cpu", timeout=1800):
    """Run chosen engines, keep candidate evidence and automatically recover failures.

    A secondary model is evidence for the Agent, not blindly appended to the
    primary notes. Unknown instruments remain explicitly unresolved.
    """
    locked = None
    try:
        choices = select_engines(hint, engine)
        if not fallback:
            choices = choices[:1]
        if device not in {"cpu", "cuda", "auto"}:
            raise ValueError("Supported devices: cpu, cuda, auto")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 7200:
            raise ValueError("timeout must be an integer from 1 to 7200 seconds")
        source = Path(input_path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("Audio source does not exist")
        source_hash = _hash(source)
        options = {"hint": hint, "engine": engine, "fallback": fallback, "combine": combine,
                   "device": device, "versions": {e: ENGINES[e]["version"] for e in choices},
                   "runtimes": {e: str(engine_python(e, cache_dir)) for e in choices},
                   "worker_sha256": _hash(Path(__file__).with_name("worker.py"))}
        key = hashlib.sha256((source_hash + json.dumps(options, sort_keys=True)).encode()).hexdigest()[:20]
        job = Path(output_dir).expanduser().resolve() / ("transcription-" + key)
        job.mkdir(parents=True, exist_ok=True)
        manifest = job / "manifest.json"
        candidate_hashes = {}
        if manifest.is_file():
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            candidate_hashes = {c["engine"]: c["sha256"] for c in previous.get("candidates", [])}
            if previous.get("status") == "transcribed":
                result_path = Path(previous["events_path"])
                if result_path.is_file() and _hash(result_path) == previous.get("events_sha256"):
                    validate_events(json.loads(result_path.read_text(encoding="utf-8")), previous["duration_seconds"])
                    return {**previous, "reused": True}
        # Only this private job is locked; stale locks from a dead process recover.
        lock = job / ".lock"
        if lock.exists():
            try:
                pid = int(lock.read_text())
                os.kill(pid, 0)
                return {"status": "busy", "job_dir": str(job), "error": "This audio job is already running"}
            except ProcessLookupError:
                lock.unlink()
        with lock.open("x") as stream:
            stream.write(str(os.getpid()))
        locked = lock
        original = job / ("source" + source.suffix.lower())
        if not original.exists() or _hash(original) != source_hash:
            shutil.copyfile(source, original)
        decoded = job / "decoded.wav"
        info = _decode(original, decoded)
        report = {"schema_version": 1, "status": "running", "source_path": str(source),
                  "source_sha256": source_hash, "original_audio": str(original),
                  "decoded_audio": str(decoded), "job_dir": str(job), **info,
                  "options": options, "attempts": [], "candidates": [], "warnings": []}
        _write(manifest, report)
        primary = None
        for selected in choices:
            artifact = job / (selected + ".json")
            try:
                status = backend_status(selected, cache_dir)
                if not status["installed"]:
                    if not auto_install:
                        raise ValueError("Engine is not installed (automatic installation disabled)")
                    installed = install_backend(selected, cache_dir)
                    if installed["status"] != "installed":
                        raise ValueError(installed["error"])
                    status = installed
                if artifact.is_file() and _hash(artifact) == candidate_hashes.get(selected):
                    data = validate_events(json.loads(artifact.read_text(encoding="utf-8")), info["duration_seconds"])
                else:
                    artifact.unlink(missing_ok=True)
                    data = validate_events(run_backend(selected, decoded, artifact, cache_dir, timeout, device), info["duration_seconds"])
                if not data["events"]:
                    raise ValueError("No notes detected; try another engine or inspect a silent source")
                record_inference(selected, status.get("version_installed"), source_hash, cache_dir)
                report["attempts"].append({"engine": selected, "status": "transcribed", "version": status.get("version_installed"),
                                            "event_count": len(data["events"])})
                report["candidates"].append({"engine": selected, "events_path": str(artifact), "sha256": _hash(artifact)})
                if primary is None:
                    primary = selected, data
                if not combine or len(report["candidates"]) >= 2:
                    break
            except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
                report["attempts"].append({"engine": selected, "status": "error", "error": str(exc)[-4000:]})
                # A malformed/partial artifact must not poison the next recovery.
                artifact.unlink(missing_ok=True)
            _write(manifest, report)
        if primary is None:
            report["status"] = "error"
            report["error"] = "All chosen engines failed; inspect attempts. Source and job are preserved for recovery."
        else:
            selected, data = primary
            if hint in {"auto", "mixed"} and not ENGINES[selected]["instruments"]:
                report["warnings"].append("Fallback cannot identify mixed instruments or drums. Pitched notes are a draft; resolve instrument/part assignment from source or separated stems.")
            if any(t.get("instrument_source") == "unresolved" for t in data.get("tracks", [])):
                report["warnings"].append("Unresolved instrument identities are retained; a MIDI program 0 from the engine is not identified piano.")
            events_path = job / "events.json"
            _write(events_path, {**data, "source_sha256": source_hash, "source_path": str(source),
                                 "duration_seconds": info["duration_seconds"], "warnings": report["warnings"]})
            report.update(status="transcribed", recognizer=selected, events_path=str(events_path),
                          events_sha256=_hash(events_path), event_count=len(data["events"]),
                          requires_agent_resolution=bool(report["warnings"] or combine), accuracy="not_measured")
        _write(manifest, report)
        return {**report, "manifest_path": str(manifest), "reused": False}
    except (ValueError, OSError, subprocess.SubprocessError, wave.Error) as exc:
        return {"status": "error", "stage": "audio_transcribe", "error": str(exc)}
    finally:
        if locked:
            locked.unlink(missing_ok=True)


def separate_audio(input_path, output_dir, cache_dir="", auto_install=True, device="cpu", timeout=1800):
    """Optional source separation. Stems stay aligned to the original timeline."""
    try:
        source = Path(input_path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("Audio source does not exist")
        job = Path(output_dir).expanduser().resolve() / ("separation-" + _hash(source)[:20])
        job.mkdir(parents=True, exist_ok=True)
        destination = job / "stems.json"
        if destination.is_file():
            previous = json.loads(destination.read_text())
            if all(Path(s["audio"]).is_file() for s in previous["stems"]):
                return {**previous, "status": "separated", "reused": True}
        if not backend_status("demucs", cache_dir)["installed"]:
            if not auto_install:
                raise ValueError("Demucs not installed")
            installation = install_backend("demucs", cache_dir)
            if installation["status"] != "installed":
                raise ValueError(installation["error"])
        decoded = job / "decoded.wav"
        info = _decode(source, decoded)
        data = run_backend("demucs", decoded, destination, cache_dir, timeout, device)
        if not data.get("stems") or not all(Path(s["audio"]).is_file() for s in data["stems"]):
            raise ValueError("Separation did not produce readable audio stems")
        data.update(status="separated", source_path=str(source), source_sha256=_hash(source),
                    **info, reused=False, note="Audio stems are not transcribed notes or individual orchestral parts. Retain the original mix as evidence.")
        _write(destination, data)
        record_inference("demucs", backend_status("demucs", cache_dir).get("version_installed"), _hash(source), cache_dir)
        return data
    except (ValueError, OSError, subprocess.SubprocessError, wave.Error) as exc:
        return {"status": "error", "stage": "audio_separate", "error": str(exc)}
