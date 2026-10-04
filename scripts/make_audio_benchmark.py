#!/usr/bin/env python3
"""Create original short blind-test audio. Answers stay outside Agent evidence.

The default renderer is a deterministic synthetic control (not sampled piano).
Optional MuseScore rendering adds real GM flute/piano/percussion sample tests.
No third-party composition or sample library is distributed by this script.
"""
import argparse
import json
from pathlib import Path
import random
import secrets
import shutil
import subprocess
import wave
from xml.etree.ElementTree import Element, SubElement, ElementTree


def _write_xml(events, path):
    root = Element("score-partwise", version="4.0")
    part_list = SubElement(root, "part-list")
    tracks = list(dict.fromkeys(event["track"] for event in events))
    for i, track in enumerate(tracks):
        group = [e for e in events if e["track"] == track]
        percussion = group[0]["kind"] == "drum"
        name = "Drumset" if percussion else group[0]["instrument_id"]
        entry = SubElement(part_list, "score-part", id=f"P{i}")
        SubElement(entry, "part-name").text = name
        drum_values = {"kick": 36, "snare": 38, "closed_hi_hat": 42}
        identities = list(dict.fromkeys(e.get("drum", "pitched") for e in group))
        for identity in identities:
            iid = f"P{i}-{identity}"
            instrument = SubElement(entry, "score-instrument", id=iid)
            drum_names = {"kick": "Acoustic Bass Drum", "snare": "Acoustic Snare", "closed_hi_hat": "Closed Hi-Hat"}
            SubElement(instrument, "instrument-name").text = drum_names[identity] if percussion else name
            midi = SubElement(entry, "midi-instrument", id=iid)
            SubElement(midi, "midi-channel").text = "10" if percussion else str(i + 1)
            SubElement(midi, "midi-program").text = "1" if percussion or name == "piano" else "74"
            if percussion:
                SubElement(midi, "midi-unpitched").text = str(drum_values[identity] + 1)
        part = SubElement(root, "part", id=f"P{i}")
        for m in range(4):
            measure = SubElement(part, "measure", number=str(m + 1))
            if not m:
                attributes = SubElement(measure, "attributes")
                SubElement(attributes, "divisions").text = "1000"
                time = SubElement(attributes, "time")
                SubElement(time, "beats").text = "4"
                SubElement(time, "beat-type").text = "4"
                clef = SubElement(attributes, "clef")
                SubElement(clef, "sign").text = "percussion" if percussion else "G"
                if not percussion:
                    SubElement(clef, "line").text = "2"
                direction = SubElement(measure, "direction")
                SubElement(direction, "direction-type")
                SubElement(direction, "sound", tempo="120")
            current = 0
            starts = sorted(set(e["start_seconds"] for e in group if m * 2 <= e["start_seconds"] < m * 2 + 2))
            for onset in starts:
                tick = round((onset - m * 2) * 2000)
                if tick > current:
                    forward = SubElement(measure, "forward")
                    SubElement(forward, "duration").text = str(tick - current)
                simultaneous = [e for e in group if e["start_seconds"] == onset]
                durations = []
                for j, event in enumerate(simultaneous):
                    note = SubElement(measure, "note")
                    if j:
                        SubElement(note, "chord")
                    if percussion:
                        unpitched = SubElement(note, "unpitched")
                        SubElement(unpitched, "display-step").text = "C"
                        SubElement(unpitched, "display-octave").text = "5"
                    else:
                        p = event["midi_pitch"]
                        pitch = SubElement(note, "pitch")
                        spelling = [("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0), ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0)][p % 12]
                        SubElement(pitch, "step").text = spelling[0]
                        if spelling[1]:
                            SubElement(pitch, "alter").text = "1"
                        SubElement(pitch, "octave").text = str(p // 12 - 1)
                    ticks = round((event["end_seconds"] - onset) * 2000)
                    durations.append(ticks)
                    SubElement(note, "duration").text = str(ticks)
                    SubElement(note, "instrument", id=f"P{i}-{event.get('drum', 'pitched')}")
                current = tick + max(durations)
            if current < 4000:
                rest = SubElement(measure, "note")
                SubElement(rest, "rest")
                SubElement(rest, "duration").text = str(4000 - current)
    ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _synthetic(events, path, seed):
    import numpy as np
    rate = 22050
    samples = np.zeros((round(9 * rate), 2))
    rng = np.random.default_rng(seed)
    for event in events:
        start = round(event["start_seconds"] * rate)
        size = round((event["end_seconds"] - event["start_seconds"]) * rate)
        t = np.arange(size) / rate
        if event["kind"] == "note":
            frequency = 440 * 2 ** ((event["midi_pitch"] - 69) / 12)
            tone = sum(np.sin(2 * np.pi * frequency * h * t) / h ** 2 for h in range(1, 6))
            envelope = np.minimum(t / .012, 1) * np.minimum((size / rate - t) / .025, 1)
        else:
            noise = rng.normal(size=size)
            if event["drum"] == "kick":
                tone = np.sin(2 * np.pi * (60 * t + 35 * .03 * (1 - np.exp(-t / .03))))
                envelope = np.exp(-t / .08)
            elif event["drum"] == "snare":
                tone = .55 * noise + .5 * np.sin(2 * np.pi * 185 * t)
                envelope = np.exp(-t / .055)
            else:
                tone = noise - np.roll(noise, 1)
                envelope = np.exp(-t / .02)
        pan = .3 if event["track"] == "bass" else .7
        samples[start:start + size] += (tone * envelope * .16)[:, None] * np.array([pan, 1 - pan])
    samples /= max(1, float(np.abs(samples).max()) / .85)
    with wave.open(str(path), "wb") as stream:
        stream.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes((samples * 32767).round().astype("<i2").tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--musescore", default="", help="Optional executable to render sampled instruments")
    parser.add_argument("--irregular-melody", action="store_true", help="One control with random note lengths and rests, without a supplied rhythm template")
    args = parser.parse_args()
    seed = args.seed if args.seed is not None else secrets.randbits(32)
    rng = random.Random(seed)
    if args.irregular_melody and args.musescore:
        raise SystemExit("The irregular timing control currently uses the synthetic renderer")
    root = Path(args.output).resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit("Use a new output directory so an earlier blind test cannot be overwritten")
    for folder in (root / "inputs", root / "answers"):
        folder.mkdir(parents=True, exist_ok=True)
    cases = []
    for case in (("irregular",) if args.irregular_melody else ("melody", "polyphonic", "mixed")):
        events = []
        if case == "irregular":
            onset = .25
            while onset < 7:
                length = rng.choice([.25, .375, .5, .75])
                events.append({"kind": "note", "track": "lead", "midi_pitch": rng.choice([64, 65, 67, 69, 71, 72, 74, 76]),
                               "start_seconds": onset, "end_seconds": onset + length})
                onset += length + rng.choice([.125, .25, .375])
        starts = [0, .5, 1, 2, 3, 3.5, 4, 5, 6, 6.5, 7, 7.5] if case == "melody" else [0, 1, 2, 3, 4, 5, 6, 7]
        for i, onset in enumerate(starts if case != "irregular" else []):
            end = starts[i + 1] if i + 1 < len(starts) else 8
            if case == "melody":
                pitches = [rng.choice([67, 69, 71, 72, 74, 76, 78])]
            else:
                base = rng.choice([60, 62, 65, 67])
                pitches = [base, base + rng.choice([3, 4]), base + 7]
            for pitch in pitches:
                events.append({"kind": "note", "track": "lead", "instrument_id": "flute" if case == "melody" else "piano",
                               "midi_pitch": pitch, "start_seconds": onset, "end_seconds": end})
        if case == "mixed":
            for onset in range(8):
                events.append({"kind": "note", "track": "bass", "instrument_id": "piano", "midi_pitch": rng.choice([36, 38, 41, 43]),
                               "start_seconds": onset, "end_seconds": onset + 1})
                events.append({"kind": "drum", "track": "drums", "drum": "kick" if onset % 2 == 0 else "snare",
                               "start_seconds": onset, "end_seconds": onset + .25})
            for i in range(16):
                events.append({"kind": "drum", "track": "drums", "drum": "closed_hi_hat",
                               "start_seconds": i * .5, "end_seconds": i * .5 + .125})
        reference = root / "answers" / f"{case}.json"
        audio = root / "inputs" / f"{case}.wav"
        if args.musescore:
            xml = root / "answers" / f"{case}.musicxml"
            _write_xml(events, xml)
            command = [args.musescore, "-o", str(audio), str(xml)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if not audio.is_file() or audio.stat().st_size < 1000:
                raise SystemExit("Rendering failed: " + result.stderr[-2000:])
            # MuseScore exports float WAV; normalize to broadly readable PCM.
            decoder = shutil.which("ffmpeg")
            if not decoder:
                raise SystemExit("ffmpeg is required to normalize the sampled WAV")
            pcm = audio.with_name(audio.stem + ".pcm.wav")
            subprocess.run([decoder, "-v", "error", "-nostdin", "-y", "-i", str(audio),
                            "-c:a", "pcm_s16le", str(pcm)], check=True)
            pcm.replace(audio)
            with wave.open(str(audio), "rb") as stream:
                if stream.getnframes() == 0:
                    raise SystemExit("Renderer produced empty WAV")
            renderer = "musescore_samples"
        else:
            _synthetic(events, audio, seed)
            # Synthetic harmonic tones do not establish real instrument identity.
            for event in events:
                event.pop("instrument_id", None)
            renderer = "synthetic_harmonic_control"
        reference.write_text(json.dumps({"schema_version": 1, "events": events}, indent=2), encoding="utf-8")
        cases.append({"case": case, "audio": str(audio), "reference": str(reference), "renderer": renderer})
    (root / "answers" / "recipe.json").write_text(json.dumps({"seed": seed, "cases": cases}, indent=2), encoding="utf-8")
    print(json.dumps({"status": "created", "inputs": str(root / "inputs"), "answers": str(root / "answers"), "cases": len(cases)}, indent=2))


if __name__ == "__main__":
    main()
