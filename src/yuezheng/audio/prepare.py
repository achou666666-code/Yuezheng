"""Prepare time-linked audio and spectral images, without choosing notes."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import wave


_PLOT_LOCK = threading.RLock()


def _libraries():
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ValueError("Install ScoreBridge's audio extra: pip install -e '.[audio]'") from exc
    return np, plt


def _pcm(path):
    np, _ = _libraries()
    with wave.open(str(path), "rb") as stream:
        channels, width, rate = stream.getnchannels(), stream.getsampwidth(), stream.getframerate()
        if width != 2 or stream.getcomptype() != "NONE":
            raise ValueError("Evidence WAV must contain uncompressed 16-bit PCM")
        data = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
    if not len(data):
        raise ValueError("Audio contains no samples")
    return data.reshape(-1, channels).astype(np.float32) / 32768.0, rate


def _spectrum(samples, rate, window_seconds):
    """Combine channel energy rather than summing signals that can cancel."""
    np, _ = _libraries()
    size = max(256, 2 ** round(math.log2(rate * window_seconds)))
    hop = max(1, round(rate * .02))
    padded = np.pad(samples, ((size // 2, size // 2), (0, 0)))
    frames = np.lib.stride_tricks.sliding_window_view(padded, size, axis=0)[::hop]
    window = np.hanning(size)
    powers = np.abs(np.fft.rfft(frames * window, axis=-1)) ** 2
    energy = np.sqrt(powers.mean(axis=1)).T
    return np.fft.rfftfreq(size, 1 / rate), np.arange(energy.shape[1]) * hop / rate, energy


def _draw_evidence(samples, rate, start, destination, midi_low=24, midi_high=108):
    np, plt = _libraries()
    duration = len(samples) / rate
    figure, axes = plt.subplots(3, 1, figsize=(15, 10), constrained_layout=True)
    # A waveform and two resolutions expose the timing/frequency tradeoff.
    stride = max(1, len(samples) // 10000)
    times = np.arange(0, len(samples), stride) / rate + start
    for channel in range(samples.shape[1]):
        axes[0].plot(times, samples[::stride, channel], linewidth=.5, alpha=.7)
    axes[0].set(ylabel="PCM amplitude", title="Source waveform (all channels)")
    semitones = np.arange(midi_low, midi_high + .125, .125)
    frequencies = 440 * 2 ** ((semitones - 69) / 12)
    for ax, window_seconds in zip(axes[1:], [.37, .09]):
        bins, t, energy = _spectrum(samples, rate, window_seconds)
        display = np.stack([np.interp(frequencies, bins, energy[:, i], left=0, right=0) for i in range(energy.shape[1])], axis=1)
        peak = max(float(display.max()), 1e-12)
        db = 20 * np.log10(np.maximum(display / peak, 1e-6))
        ax.pcolormesh(t + start, semitones, db, shading="auto", cmap="magma", vmin=-70, vmax=0)
        ticks = np.arange(midi_low, midi_high + 1, 1 if midi_high - midi_low <= 36 else 6)
        names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        ax.set_yticks(ticks, [f"{m} {names[m % 12]}{m // 12 - 1}" for m in ticks])
        ax.set(ylabel="Frequency in MIDI-semitone units",
               title=f"Raw STFT, window about {window_seconds:g}s; harmonics are NOT extra notes")
        ax.grid(axis="y", alpha=.15)
    for ax in axes:
        ax.set_xlim(start, start + duration)
        ax.grid(axis="x", alpha=.2)
        ax.set_xlabel("Original source time (seconds)")
    figure.savefig(destination, dpi=120)
    plt.close(figure)


def prepare_audio(input_path, output_dir, segment_seconds=8.0, overlap_seconds=1.0, midi_low=24, midi_high=108):
    """Return evidence awaiting the Agent. Does not call a model or DAW."""
    source = Path(input_path).expanduser().resolve()
    try:
        segment_seconds, overlap_seconds = float(segment_seconds), float(overlap_seconds)
        if (not math.isfinite(segment_seconds) or not math.isfinite(overlap_seconds)
                or not 1 <= segment_seconds <= 30 or not 0 <= overlap_seconds < segment_seconds):
            raise ValueError("segment_seconds must be 1..30; overlap_seconds must be nonnegative and smaller")
        if not source.is_file():
            raise ValueError("Audio input does not exist")
        if (any(isinstance(v, bool) or not isinstance(v, int) for v in (midi_low, midi_high))
                or not 0 <= midi_low < midi_high <= 127):
            raise ValueError("Frequency display requires integer 0 <= midi_low < midi_high <= 127")
        _libraries()
        folder = Path(output_dir).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        job = Path(tempfile.mkdtemp(prefix="audio-", dir=folder))
        original = job / ("source" + source.suffix.lower())
        shutil.copyfile(source, original)
        normalized = job / "decoded.wav"
        ffmpeg = os.environ.get("SCOREBRIDGE_FFMPEG") or shutil.which("ffmpeg")
        if ffmpeg:
            result = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(original),
                                     "-vn", "-map_metadata", "-1", "-ar", "22050", "-c:a", "pcm_s16le",
                                     str(normalized)], capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise ValueError("Audio decode failed: " + result.stderr[-2000:])
        else:
            # Standard WAV works without an external decoder; compressed formats need ffmpeg.
            _pcm(original)
            shutil.copyfile(original, normalized)
        samples, rate = _pcm(normalized)
        duration = len(samples) / rate
        segments = []
        step = segment_seconds - overlap_seconds
        start = 0.0
        while start < duration:
            first, last = round(start * rate), min(len(samples), round((start + segment_seconds) * rate))
            clip = samples[first:last]
            audio_path = job / f"segment-{len(segments) + 1:04d}.wav"
            image_path = audio_path.with_suffix(".png")
            np, _ = _libraries()
            with wave.open(str(audio_path), "wb") as stream:
                stream.setparams((samples.shape[1], 2, rate, 0, "NONE", "not compressed"))
                stream.writeframes((np.clip(clip, -1, .999969) * 32768).round().astype("<i2").tobytes())
            with _PLOT_LOCK:
                _draw_evidence(clip, rate, first / rate, image_path, midi_low, midi_high)
            segments.append({"id": len(segments) + 1, "start_seconds": first / rate,
                             "end_seconds": last / rate, "audio": str(audio_path), "spectrum": str(image_path)})
            if last == len(samples):
                break
            start += step
        manifest = {"schema_version": 1, "status": "awaiting_agent", "recognizer": "calling_agent",
                    "input_type": "audio", "source_path": str(source), "original_audio": str(original),
                    "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                    "decoded_audio": str(normalized), "duration_seconds": duration,
                    "sample_rate": rate, "channels": samples.shape[1], "segments": segments,
                    "display_midi_range": [midi_low, midi_high],
                    "evidence_kind": "waveform_and_raw_spectrum",
                    "next": "The calling Agent reads audio or spectral evidence and supplies music events in source seconds. Raw spectral harmonics are not notes. Deduplicate overlap. No music was recognized by this tool."}
        manifest_path = job / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {**manifest, "manifest_path": str(manifest_path)}
    except (ValueError, OSError, wave.Error, subprocess.SubprocessError) as exc:
        return {"status": "error", "stage": "prepare_audio", "error": str(exc)}
