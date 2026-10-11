"""Standalone child-process entry point. Imports no ScoreBridge dependencies."""
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys

DRUM_NAMES = {35: "kick", 36: "kick", 37: "side_stick", 38: "snare", 40: "snare",
              42: "closed_hi_hat", 44: "pedal_hi_hat", 46: "open_hi_hat",
              49: "crash_cymbal_1", 57: "crash_cymbal_2", 51: "ride_cymbal_1",
              59: "ride_cymbal_2", 41: "low_floor_tom", 43: "high_floor_tom",
              45: "low_tom", 47: "low_mid_tom", 48: "high_mid_tom", 50: "high_tom"}


def yourmt3_checkpoint():
    """Fetch one hash-checked weight file; do not clone all Space/LFS assets."""
    import hashlib
    import os
    import shutil
    from huggingface_hub import hf_hub_download
    from mt3_infer import get_model_info
    spec = get_model_info("yourmt3")["checkpoint"]["download"]
    repository = spec["source_url"].split("/spaces/", 1)[1].strip("/")
    checkpoint = Path(os.environ["MT3_CHECKPOINT_DIR"]) / "last.ckpt"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    if not checkpoint.is_file():
        cached = hf_hub_download(repository, filename=spec["target_path"], repo_type="space")
        partial = checkpoint.with_suffix(f".partial-{os.getpid()}")
        try:
            os.link(cached, partial)
        except OSError:
            shutil.copyfile(cached, partial)
        partial.replace(checkpoint)
    digest = hashlib.sha256()
    with checkpoint.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != spec["sha256"]:
        raise ValueError("YourMT3 checkpoint checksum mismatch; remove the damaged cache file before retrying")
    return checkpoint


MODULES = {"basic_pitch": ("basic_pitch", "basic-pitch"), "transkun": ("transkun", "transkun"),
           "yourmt3": ("mt3_infer", "mt3-infer"), "demucs": ("demucs", "demucs")}


def probe(engine):
    module, package = MODULES[engine]
    importlib.import_module(module)
    if engine == "basic_pitch":
        importlib.import_module("onnxruntime")
        importlib.import_module("basic_pitch.inference")
    elif engine == "transkun":
        importlib.import_module("transkun.transcribe")
    elif engine == "yourmt3":
        importlib.import_module("mt3_infer.api")
    else:
        importlib.import_module("demucs.separate")
    return {"installed": True, "version_installed": importlib.metadata.version(package),
            "runtime_verified": False, "python_version": sys.version.split()[0]}


def midi_events(path, engine):
    import pretty_midi
    midi = pretty_midi.PrettyMIDI(str(path))
    events, tracks = [], []
    for index, instrument in enumerate(midi.instruments):
        track = f"track-{index + 1}"
        identified = engine == "yourmt3" or engine == "transkun"
        tracks.append({"id": track, "name": instrument.name or track,
                       "is_drum": bool(instrument.is_drum),
                       "gm_program": int(instrument.program) if identified and not instrument.is_drum else None,
                       "instrument_source": "model" if engine == "yourmt3" else "backend_domain" if engine == "transkun" else "unresolved",
                       "velocity_source": "default" if engine == "yourmt3" else "model_estimate",
                       "controls": [{"number": int(c.number), "value": int(c.value), "seconds": float(c.time)}
                                    for c in instrument.control_changes],
                       "pitch_bends": [{"value": int(b.pitch), "seconds": float(b.time)} for b in instrument.pitch_bends]})
        for note in instrument.notes:
            events.append({"kind": "drum" if instrument.is_drum else "note", "track": track,
                           "midi_pitch": int(note.pitch), "velocity": int(note.velocity),
                           "start_seconds": float(note.start), "end_seconds": float(note.end),
                           **({"drum": DRUM_NAMES.get(note.pitch, f"gm-{note.pitch}")} if instrument.is_drum else {})})
    return {"schema_version": 1, "recognizer": engine, "evidence_mode": "audio_model",
            "tracks": tracks, "events": sorted(events, key=lambda e: (e["start_seconds"], e["track"], e["midi_pitch"])),
            "engine_midi": str(path.resolve())}


def run(engine, source, destination, device):
    midi = destination.with_suffix(".mid")
    if engine == "basic_pitch":
        from basic_pitch import build_icassp_2022_model_path, FilenameSuffix
        from basic_pitch.inference import predict
        _, performance, _ = predict(str(source), build_icassp_2022_model_path(FilenameSuffix.onnx))
        performance.write(str(midi))
    elif engine == "transkun":
        import subprocess
        subprocess.run([sys.executable, "-m", "transkun.transcribe", str(source), str(midi),
                        "--device", device], check=True)
    elif engine == "yourmt3":
        import librosa
        import numpy as np
        import torch
        from mt3_infer import load_model
        torch.set_num_threads(2)
        samples, rate = librosa.load(str(source), sr=16000, mono=False)
        if samples.ndim > 1:
            mono = samples.mean(axis=0)
            energies = (samples ** 2).mean(axis=1)
            samples = samples[np.argmax(energies)] if (mono ** 2).mean() < .01 * energies.max() else mono
        model = load_model("yourmt3", checkpoint_path=str(yourmt3_checkpoint()), device=device, auto_download=False)
        model.transcribe(samples, sr=rate).save(str(midi))
    else:
        import subprocess
        folder = destination.parent / "stems"
        subprocess.run([sys.executable, "-m", "demucs.separate", "-n", "htdemucs",
                        "-d", device, "--float32", "-o", str(folder), str(source)], check=True)
        candidates = sorted(folder.glob("htdemucs/*/*.wav"))
        if not candidates:
            raise ValueError("Separation returned no stems")
        return {"schema_version": 1, "recognizer": "demucs", "kind": "separation",
                "stems": [{"name": p.stem, "audio": str(p.resolve())} for p in candidates]}
    if not midi.is_file() or midi.stat().st_size < 14:
        raise ValueError("Transcription produced no valid MIDI")
    result = midi_events(midi, engine)
    # Supply timing evidence to the Agent; this estimate is not an asserted
    # meter or a tempo-change transcription. It never changes note timestamps.
    try:
        import librosa
        samples, rate = librosa.load(str(source), sr=22050, mono=True)
        tempo, beats = librosa.beat.beat_track(y=samples, sr=rate)
        bpm = float(tempo.item() if hasattr(tempo, "item") else tempo)
        if bpm > 0 and len(beats):
            result["timing"] = {"bpm": bpm, "source": "beat_tracker_estimate",
                                "beats_seconds": [float(t) for t in librosa.frames_to_time(beats, sr=rate)],
                                "scope": "Provisional pulse; Agent resolves half/double tempo, meter and changes"}
    except (ImportError, ValueError, RuntimeError):
        pass
    return result


if __name__ == "__main__":
    # Some ML packages log to stdout. Probe stdout is a JSON-only protocol.
    import contextlib
    try:
        action, engine = sys.argv[1:3]
        with contextlib.redirect_stdout(sys.stderr):
            if action == "probe":
                result = probe(engine)
            elif action == "run":
                source, destination = map(Path, sys.argv[3:5])
                result = run(engine, source, destination, sys.argv[5])
                destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
            else:
                raise ValueError("Unknown action")
        if action == "probe":
            print(json.dumps(result))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
