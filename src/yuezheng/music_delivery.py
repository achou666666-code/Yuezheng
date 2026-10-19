"""Selected editable deliverables from one music plan. Intermediates stay private."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import tempfile
from xml.etree.ElementTree import Element, ElementTree, SubElement

from .music_plan import load_music_plan, seconds_to_quarters, validate_music_plan
from .musescore.adapter import MuseScoreAdapter, MuseScoreError


def write_performance_midi(plan, output):
    import mido
    validate_music_plan(plan)
    performance = plan["performance"]
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    timeline = []
    tick = lambda s: round(seconds_to_quarters(s, plan["tempo_map"]) * 480)
    for p in plan["tempo_map"]:
        timeline.append((tick(p["seconds"]), mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(p["bpm"]))))
    for p in plan["meter_map"]:
        timeline.append((round(p["quarter"] * 480), mido.MetaMessage("time_signature", numerator=p["numerator"], denominator=p["denominator"])))
    _delta_track(conductor, timeline)
    channels = list(range(9)) + list(range(10, 16))
    pitched = drum = 0
    for track in performance["tracks"]:
        if track.get("is_drum"):
            port, channel = drum, 9
            drum += 1
        else:
            port, channel = pitched // 15, channels[pitched % 15]
            pitched += 1
        if port > 127:
            raise ValueError("MIDI port capacity exceeded")
        stream = mido.MidiTrack()
        midi.tracks.append(stream)
        stream.append(mido.MetaMessage("track_name", name=track.get("name", track["id"])))
        stream.append(mido.MetaMessage("midi_port", port=port))
        if track.get("gm_program") is not None and not track.get("is_drum"):
            stream.append(mido.Message("program_change", channel=channel, program=track["gm_program"]))
        events = []
        for event in performance["events"]:
            if event["track"] == track["id"]:
                start, end = tick(event["start_seconds"]), tick(event["end_seconds"])
                events.extend([(start, mido.Message("note_on", channel=channel, note=event["midi_pitch"], velocity=event.get("velocity", 80))),
                               (max(start + 1, end), mido.Message("note_off", channel=channel, note=event["midi_pitch"], velocity=0))])
        for c in track.get("controls", []):
            events.append((tick(c["seconds"]), mido.Message("control_change", channel=channel, control=c["number"], value=c["value"])))
        for b in track.get("pitch_bends", []):
            events.append((tick(b["seconds"]), mido.Message("pitchwheel", channel=channel, pitch=b["value"])))
        _delta_track(stream, events)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    midi.save(str(destination))
    return destination


def _delta_track(track, messages):
    # Off before on at one tick for a repeated pitch; otherwise stable input order.
    previous = 0
    for tick, message in sorted(messages, key=lambda e: (e[0], 0 if e[1].type == "note_off" else 1)):
        track.append(message.copy(time=tick - previous))
        previous = tick
    import mido
    track.append(mido.MetaMessage("end_of_track"))


_TYPES = [(1920, "whole"), (960, "half"), (480, "quarter"), (240, "eighth"),
          (120, "16th"), (60, "32nd"), (30, "64th")]


def _pieces(duration):
    for base, kind in _TYPES:
        dotted = base * 3 // 2
        while duration >= dotted:
            yield dotted, kind, True
            duration -= dotted
        while duration >= base:
            yield base, kind, False
            duration -= base
    if duration:
        raise ValueError("Duration is not representable on this notation grid")


def _bars(plan, last):
    meters = plan["meter_map"]
    result, pos, index = [], 0, 0
    while pos < max(480, last):
        if index + 1 < len(meters) and round(meters[index + 1]["quarter"] * 480) == pos:
            index += 1
        m = meters[index]
        end = pos + round(m["numerator"] * 4 / m["denominator"] * 480)
        result.append((pos, end, m))
        pos = end
    return result


def _lanes(plan, track):
    grid = round(plan.get("notation", {}).get("grid_quarters", .25) * 480)
    grouped = defaultdict(list)
    for event in plan["performance"]["events"]:
        if event["track"] == track["id"]:
            begin = round(seconds_to_quarters(event["start_seconds"], plan["tempo_map"]) * 480 / grid) * grid
            end = max(begin + grid, round(seconds_to_quarters(event["end_seconds"], plan["tempo_map"]) * 480 / grid) * grid)
            grouped[begin, end].append(event)
    lanes = []
    for (begin, end), notes in sorted(grouped.items()):
        lane = next((l for l in lanes if l[-1][1] <= begin), None)
        if lane is None:
            lane = []
            lanes.append(lane)
        lane.append((begin, end, notes))
    return lanes or [[]]


def write_plan_musicxml(plan, output):
    """Baseline audio notation, with explicit rests, overlapping voices and bar ties.

    Detailed Agent-authored symbols use notation.native and the editor adapter.
    This projection never claims to recover an original engraving from audio.
    """
    validate_music_plan(plan)
    root = Element("score-partwise", version="4.0")
    SubElement(SubElement(root, "work"), "work-title").text = plan["title"]
    parts = SubElement(root, "part-list")
    tracks = []
    for track in plan["performance"]["tracks"]:
        lanes = _lanes(plan, track)
        for i in range(0, len(lanes), 4):
            tracks.append((track, lanes[i:i + 4], i // 4))
    last = max((end for _, lanes, _ in tracks for lane in lanes for _, end, _ in lane), default=480)
    bars = _bars(plan, last)
    for index, (track, lanes, split) in enumerate(tracks, 1):
        pid = f"P{index}"
        score_part = SubElement(parts, "score-part", id=pid)
        name = track.get("name", track["id"]) + (f" (voices {split * 4 + 1}+)" if split else "")
        SubElement(score_part, "part-name").text = "Drumset" if track.get("is_drum") else name
        notes = [e for lane in lanes for _, _, chord in lane for e in chord]
        pitches = sorted({e["midi_pitch"] for e in notes}) if track.get("is_drum") else [None]
        for pitch in pitches:
            iid = pid + (f"-D{pitch}" if pitch is not None else "-I")
            instrument = SubElement(score_part, "score-instrument", id=iid)
            SubElement(instrument, "instrument-name").text = name if pitch is None else f"GM Drum {pitch}"
            midi = SubElement(score_part, "midi-instrument", id=iid)
            channels = list(range(1, 10)) + list(range(11, 17))
            SubElement(midi, "midi-channel").text = str(10 if pitch is not None else channels[(index - 1) % 15])
            if pitch is not None:
                SubElement(midi, "midi-unpitched").text = str(pitch + 1)
            elif track.get("gm_program") is not None:
                SubElement(midi, "midi-program").text = str(track["gm_program"] + 1)
        body = SubElement(root, "part", id=pid)
        for number, (begin, end, meter) in enumerate(bars, 1):
            measure = SubElement(body, "measure", number=str(number))
            if number == 1 or meter is not bars[number - 2][2]:
                attributes = SubElement(measure, "attributes")
                if number == 1:
                    SubElement(attributes, "divisions").text = "480"
                    key = plan.get("notation", {}).get("key_fifths")
                    if key is not None and not track.get("is_drum"):
                        SubElement(SubElement(attributes, "key"), "fifths").text = str(key)
                    clef = SubElement(attributes, "clef")
                    bass = notes and sum(e["midi_pitch"] for e in notes) / len(notes) < 55
                    SubElement(clef, "sign").text = "percussion" if track.get("is_drum") else "F" if bass else "G"
                    SubElement(clef, "line").text = "2" if track.get("is_drum") or not bass else "4"
                time = SubElement(attributes, "time")
                SubElement(time, "beats").text = str(meter["numerator"])
                SubElement(time, "beat-type").text = str(meter["denominator"])
            if index == 1:
                for tempo in plan["tempo_map"]:
                    pos = round(seconds_to_quarters(tempo["seconds"], plan["tempo_map"]) * 480)
                    if begin <= pos < end:
                        direction = SubElement(measure, "direction", placement="above")
                        metronome = SubElement(SubElement(direction, "direction-type"), "metronome")
                        SubElement(metronome, "beat-unit").text = "quarter"
                        SubElement(metronome, "per-minute").text = str(tempo["bpm"])
                        SubElement(direction, "offset").text = str(pos - begin)
                        SubElement(direction, "sound", tempo=str(tempo["bpm"]))
            for voice, lane in enumerate(lanes, 1):
                if voice > 1:
                    SubElement(SubElement(measure, "backup"), "duration").text = str(end - begin)
                cursor = begin
                for start, stop, chord in lane:
                    if stop <= begin or start >= end:
                        continue
                    clipped_start, clipped_end = max(begin, start), min(end, stop)
                    _rests(measure, clipped_start - cursor, voice)
                    duration = clipped_end - clipped_start
                    pieces = list(_pieces(duration))
                    for k, (length, kind, dotted) in enumerate(pieces):
                        for n, event in enumerate(chord):
                            note = SubElement(measure, "note", dynamics=str(round(event.get("velocity", 80) / 127 * 100)))
                            if n:
                                SubElement(note, "chord")
                            pitch = event["midi_pitch"]
                            if track.get("is_drum"):
                                unpitched = SubElement(note, "unpitched")
                                step, octave = {36: ("F", 4), 38: ("C", 5), 42: ("G", 5)}.get(pitch, ("E", 5))
                                SubElement(unpitched, "display-step").text = step
                                SubElement(unpitched, "display-octave").text = str(octave)
                            else:
                                spelling = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[pitch % 12]
                                p = SubElement(note, "pitch")
                                SubElement(p, "step").text = spelling[0]
                                if len(spelling) > 1:
                                    SubElement(p, "alter").text = "1"
                                SubElement(p, "octave").text = str(pitch // 12 - 1)
                            SubElement(note, "duration").text = str(length)
                            tied_stop, tied_start = start < begin or k > 0, stop > end or k < len(pieces) - 1
                            for flag, kind_tie in ((tied_stop, "stop"), (tied_start, "start")):
                                if flag:
                                    SubElement(note, "tie", type=kind_tie)
                            SubElement(note, "instrument", id=pid + (f"-D{pitch}" if track.get("is_drum") else "-I"))
                            SubElement(note, "voice").text = str(voice)
                            SubElement(note, "type").text = kind
                            if dotted:
                                SubElement(note, "dot")
                            if tied_start or tied_stop:
                                notation = SubElement(note, "notations")
                                for flag, kind_tie in ((tied_stop, "stop"), (tied_start, "start")):
                                    if flag:
                                        SubElement(notation, "tied", type=kind_tie)
                    cursor = clipped_end
                _rests(measure, end - cursor, voice)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)
    return destination


def _rests(measure, duration, voice):
    for length, kind, dotted in _pieces(duration):
        note = SubElement(measure, "note")
        SubElement(note, "rest")
        SubElement(note, "duration").text = str(length)
        SubElement(note, "voice").text = str(voice)
        SubElement(note, "type").text = kind
        if dotted:
            SubElement(note, "dot")


def deliver_music_plan(input_path, output_dir, formats=("mscz",), executable="", ace_cli="", sibelius_url=""):
    """Generate only requested public files and preserve a private delivery receipt."""
    try:
        plan = load_music_plan(input_path)
        allowed = {"mscz", "musicxml", "pdf", "midi", "ace", "sib", "wav", "mp3"}
        if not formats or len(formats) != len(set(formats)) or any(f not in allowed for f in formats):
            raise ValueError("Choose unique formats: mscz, sib, musicxml, pdf, midi, ace, wav, mp3")
        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        internal = output / ".scorebridge" / ("delivery-" + digest[:20])
        internal.mkdir(parents=True, exist_ok=True)
        report = {"status": "delivered", "plan_sha256": digest, "outputs": {}, "warnings": list(plan.get("warnings", []))}
        adapter = MuseScoreAdapter(executable=executable or None,
                                   timeout=300 if set(formats) & {"wav", "mp3"} else 90)
        score_path = internal / "score.mscz"
        xml_path = internal / "score.musicxml"
        native = plan.get("notation", {}).get("native")
        need_score = bool(set(formats) & {"mscz", "pdf", "wav", "mp3"}) or bool(native and set(formats) & {"musicxml", "midi", "ace", "sib"})
        score_error = None
        if need_score:
            try:
                if native:
                    from .musescore.build import build_agent_score
                    built = build_agent_score(native["score"], native["steps"], str(score_path), executable)
                    if built.get("status") != "pass":
                        raise ValueError("Native editor execution failed: " + json.dumps(built, ensure_ascii=False))
                    report["editor_receipt"] = built
                else:
                    write_plan_musicxml(plan, xml_path)
                    adapter.convert(str(xml_path), str(score_path))
            except (ValueError, OSError, MuseScoreError) as exc:
                score_error = str(exc)
        import shutil
        for fmt in formats:
            try:
                if score_error and (fmt in {"mscz", "pdf", "wav", "mp3"} or native and fmt in {"musicxml", "midi", "ace", "sib"}):
                    raise ValueError(score_error)
                if fmt == "sib":
                    from .sibelius.adapter import create_sibelius_score
                    sib_xml = internal / "sibelius.musicxml"
                    if native:
                        adapter.convert(str(score_path), str(sib_xml))
                    else:
                        write_plan_musicxml(plan, sib_xml)
                    result = create_sibelius_score(str(sib_xml), str(output / "music.sib"), sibelius_url)
                    report["outputs"][fmt] = result["output_path"]
                    report["sibelius_receipt"] = result
                    continue
                if fmt == "ace":
                    from .ace.adapter import create_ace_project
                    ace_plan = plan
                    if not plan.get("performance"):
                        adapter.convert(str(score_path), str(internal / "native.mid"))
                        from .midi_projection import project_midi
                        ace_plan = project_midi(internal / "native.mid", plan["title"])
                        ace_plan["bindings"] = plan.get("bindings", {})
                    result = create_ace_project(ace_plan, str(internal / "ace.mid"), str(output / "music.acep"), ace_cli)
                    if result.get("status") != "delivered":
                        raise ValueError(json.dumps(result, ensure_ascii=False))
                    report["outputs"][fmt] = result["saved_path"]
                    report["ace_receipt"] = result
                    report["warnings"].extend(result.get("warnings", []))
                    continue
                suffix = "mid" if fmt == "midi" else fmt
                destination = output / ("music." + suffix)
                if fmt == "midi" and plan.get("performance"):
                    write_performance_midi(plan, destination)
                elif fmt == "musicxml" and not native:
                    write_plan_musicxml(plan, destination)
                elif fmt == "mscz":
                    shutil.copyfile(score_path, destination)
                else:
                    # MuseScore renders audio for an audio extension and
                    # engraves for a document extension from the same MSCZ.
                    adapter.convert(str(score_path), str(destination))
                report["outputs"][fmt] = str(destination)
            except (ValueError, OSError, RuntimeError, MuseScoreError, ImportError) as exc:
                report["status"] = "partial"
                report.setdefault("errors", {})[fmt] = str(exc)
        receipt = internal / "receipt.json"
        receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**report, "receipt_path": str(receipt)}
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, MuseScoreError, ImportError) as exc:
        return {"status": "error", "error": str(exc)}
