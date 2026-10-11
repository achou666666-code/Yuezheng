from collections import defaultdict
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from yuezheng.score_ir import Event, Score
from yuezheng.instruments import instrument_spec

DIVISIONS = 8
DURATIONS = {"whole": (32, "whole"), "half": (16, "half"), "quarter": (8, "quarter"), "eighth": (4, "eighth"), "16th": (2, "16th"), "32nd": (1, "32nd"),
             "dotted-whole": (48, "whole"),
             "dotted-half": (24, "half"), "dotted-quarter": (12, "quarter"), "dotted-eighth": (6, "eighth"), "dotted-16th": (3, "16th")}

def _pitch(value):
    if not value or len(value) < 2:
        raise ValueError("pitch must look like C4, Bb3 or F#5")
    step = value[0].upper(); rest = value[1:]; alter = 0
    if rest.startswith("#"): alter, rest = 1, rest[1:]
    elif rest.startswith("b"): alter, rest = -1, rest[1:]
    elif rest.startswith("n"): rest = rest[1:]
    if step not in "CDEFGAB" or not rest.lstrip("-").isdigit(): raise ValueError("invalid pitch: %s" % value)
    return step, alter, int(rest)

def _note(parent, event, pitch_value, staff_number, chord=False):
    n = SubElement(parent, "note")
    if chord: SubElement(n, "chord")
    if event.kind == "rest":
        SubElement(n, "rest")
    else:
        step, alter, octave = _pitch(pitch_value)
        p = SubElement(n, "pitch"); SubElement(p, "step").text = step
        if alter: SubElement(p, "alter").text = str(alter)
        SubElement(p, "octave").text = str(octave)
        if event.accidental: SubElement(n, "accidental").text = event.accidental
        if event.tie_start: SubElement(n, "tie", type="start")
        if event.tie_stop: SubElement(n, "tie", type="stop")
    dur, typ = DURATIONS[event.duration]; SubElement(n, "duration").text = str(dur)
    SubElement(n, "voice").text = str(event.voice); SubElement(n, "type").text = typ
    if event.duration.startswith("dotted-"):
        SubElement(n, "dot")
    SubElement(n, "staff").text = str(staff_number)
    if event.tie_start or event.tie_stop:
        notations = SubElement(SubElement(n, "notations"), "tied")
        notations.set("type", "start" if event.tie_start else "stop")
    if event.articulations:
        arts = SubElement(SubElement(n, "notations"), "articulations")
        for name in event.articulations: SubElement(arts, name)
def _event(parent, event, staff_number):
    if event.duration not in DURATIONS: raise ValueError("unsupported duration: %s" % event.duration)
    if event.kind == "chord":
        if not event.pitches:
            event.kind = "rest"
            _note(parent, event, None, staff_number)
            return
        for index, value in enumerate(event.pitches): _note(parent, event, value, staff_number, index > 0)
    else:
        # Some OMR engines emit a note shell without pitch when a glyph is
        # unreadable. Keep the duration in the exported score as a rest so the
        # document remains valid and the unresolved event stays reviewable.
        if event.kind == "note" and not event.pitch:
            event.kind = "rest"
        _note(parent, event, event.pitch, staff_number)

def _direction(measure_el, measure):
    for text in measure.directions + measure.dynamics:
        d = SubElement(measure_el, "direction", placement="below")
        dt = SubElement(d, "direction-type")
        if text in {"pp", "p", "mp", "mf", "f", "ff", "sfz"}:
            SubElement(SubElement(dt, "dynamics"), text)
        else: SubElement(dt, "words").text = text
    if measure.tempo_bpm:
        d = SubElement(measure_el, "direction", placement="above"); dt = SubElement(d, "direction-type")
        met = SubElement(dt, "metronome"); SubElement(met, "beat-unit").text = measure.tempo_beat; SubElement(met, "per-minute").text = str(measure.tempo_bpm).rstrip("0").rstrip(".")
        SubElement(d, "sound", tempo=str(measure.tempo_bpm))

def _backup(parent, duration):
    backup = SubElement(parent, "backup")
    SubElement(backup, "duration").text = str(duration)

def compile_musicxml(score: Score, output: str) -> Path:
    root = Element("score-partwise", version="4.0"); work = SubElement(root, "work"); SubElement(work, "work-title").text = score.title
    part_list = SubElement(root, "part-list")
    for part in score.parts:
        sp = SubElement(part_list, "score-part", id=part.id); SubElement(sp, "part-name").text = part.name
        inst = SubElement(sp, "score-instrument", id=part.id + "-I1"); SubElement(inst, "instrument-name").text = part.name
        spec = instrument_spec(part.instrument_id)
        if spec.get("instrument_sound"):
            SubElement(inst, "instrument-sound").text = spec["instrument_sound"]
        midi = SubElement(sp, "midi-instrument", id=part.id + "-I1")
        if spec.get("midi_program"):
            SubElement(midi, "midi-program").text = str(spec["midi_program"])
        SubElement(midi, "midi-channel").text = str((len(part_list.findall("score-part")) % 15) + 1)
    for part in score.parts:
        pe = SubElement(root, "part", id=part.id)
        maps = [{m.number: m for m in staff.measures} for staff in part.staves]
        numbers = sorted(set().union(*(set(x) for x in maps)))
        active_time = (4, 4); active_keys = defaultdict(int)
        for number in numbers:
            measures = [x.get(number) for x in maps]; primary = next(m for m in measures if m)
            me = SubElement(pe, "measure", number=str(number))
            if number == 1 or any(m and (m.key_fifths is not None or m.time_beats is not None) for m in measures):
                attrs = SubElement(me, "attributes"); SubElement(attrs, "divisions").text = str(DIVISIONS)
                if len(part.staves) > 1: SubElement(attrs, "staves").text = str(len(part.staves))
                changed_time = next((m for m in measures if m and m.time_beats is not None), None)
                if changed_time: active_time = (changed_time.time_beats, changed_time.time_beat_type)
                for staff_number, measure in enumerate(measures, 1):
                    if measure and measure.key_fifths is not None: active_keys[staff_number] = measure.key_fifths
                    key = SubElement(attrs, "key")
                    if len(part.staves) > 1: key.set("number", str(staff_number))
                    SubElement(key, "fifths").text = str(active_keys[staff_number])
                tm = SubElement(attrs, "time"); SubElement(tm, "beats").text = str(active_time[0]); SubElement(tm, "beat-type").text = str(active_time[1])
                spec = instrument_spec(part.instrument_id)
                if number == 1 and spec.get("transpose_chromatic") is not None:
                    transpose = SubElement(attrs, "transpose")
                    SubElement(transpose, "diatonic").text = str(spec["transpose_diatonic"])
                    SubElement(transpose, "chromatic").text = str(spec["transpose_chromatic"])
                for staff_number, staff in enumerate(part.staves, 1):
                    cl = SubElement(attrs, "clef")
                    if len(part.staves) > 1: cl.set("number", str(staff_number))
                    SubElement(cl, "sign").text = "F" if staff.clef == "bass" else "G"; SubElement(cl, "line").text = "4" if staff.clef == "bass" else "2"
            _direction(me, primary)
            expected = active_time[0] * DIVISIONS * 4 // active_time[1]
            for staff_index, measure in enumerate(measures, 1):
                if staff_index > 1: _backup(me, expected)
                if not measure: continue
                voices = defaultdict(list)
                for ev in measure.events: voices[ev.voice].append(ev)
                for voice_index, (_, events) in enumerate(sorted(voices.items()), 1):
                    if voice_index > 1: _backup(me, expected)
                    for ev in events: _event(me, ev, staff_index)
    out = Path(output); ElementTree(root).write(out, encoding="utf-8", xml_declaration=True); return out
