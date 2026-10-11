"""MusicXML 4.0 subset parser used as the OMR engine boundary."""
from pathlib import Path
from xml.etree import ElementTree as ET
from yuezheng.score_ir import Event, Measure, Part, Score, Staff
from yuezheng.instruments import INSTRUMENTS

_DURATION_NAMES = {"whole": "whole", "half": "half", "quarter": "quarter", "eighth": "eighth", "16th": "16th", "32nd": "32nd"}

def _duration_name(duration, divisions, note, measure_rest=False):
    if measure_rest:
        return "dotted-whole" if duration == divisions * 6 else "whole"
    dotted = _tag(note, "dot") is not None
    values = {"whole": divisions * 4, "half": divisions * 2,
              "quarter": divisions, "eighth": divisions // 2,
              "16th": divisions // 4, "32nd": max(1, divisions // 8)}
    for name, value in values.items():
        if duration == value:
            return ("dotted-" + name) if dotted else name
        if duration * 2 == value * 3:
            return "dotted-" + name
    return min(values, key=lambda name: abs(duration - values[name]))

def _tag(element, name):
    value = element.find(name)
    return value if value is not None else element.find("{*}" + name)

def _local_name(tag):
    return tag.rsplit("}", 1)[-1]

def _children(element, name):
    return [child for child in list(element) if _local_name(child.tag) == name]

def _descendants(element, name):
    return [node for node in element.iter() if _local_name(node.tag) == name]

def _descendant_text(element, name, default=None):
    nodes = _descendants(element, name)
    return nodes[0].text if nodes and nodes[0].text is not None else default

def _text(element, name, default=None):
    value = _tag(element, name)
    return value.text if value is not None else default

def _parse_note(note, divisions):
    duration = int(_text(note, "duration", "0"))
    rest_node = _tag(note, "rest")
    kind = "rest" if rest_node is not None else "note"
    pitch = None
    pitch_node = _tag(note, "pitch")
    if pitch_node is not None:
        step = _text(pitch_node, "step")
        octave = _text(pitch_node, "octave")
        alter = int(_text(pitch_node, "alter", "0"))
        pitch = step + ("#" if alter == 1 else "b" if alter == -1 else "") + octave
    # OMR output commonly uses these exact type names; quantize unknown values conservatively.
    duration_name = _duration_name(duration, divisions, note, bool(rest_node is not None and rest_node.attrib.get("measure") == "yes"))
    return Event(kind, duration_name, pitch=pitch, voice=int(_text(note, "voice", "1")), accidental=_text(note, "accidental"))

def parse_musicxml(path: str) -> Score:
    root = ET.parse(path).getroot()
    title = _descendant_text(root, "work-title", Path(path).stem)
    parts = []
    score_parts = _descendants(root, "score-part")
    names = {node.attrib.get("id"): _text(node, "part-name", node.attrib.get("id", "Part")) for node in score_parts}
    ids = {node.attrib.get("id"): next((key for key, spec in INSTRUMENTS.items() if spec["name"].lower() == _text(node, "part-name", "").lower()), _text(node, "part-name", node.attrib.get("id", "Part"))) for node in score_parts}
    for part_node in _descendants(root, "part"):
        pid = part_node.attrib["id"]
        staff_map = {}
        active = {"divisions": 1, "key": None, "beats": None, "beat_type": None, "clef": "treble"}
        measure_seq = 0
        for measure_node in list(part_node):
            if not measure_node.tag.endswith("measure"): continue
            raw_number = measure_node.attrib.get("number", "")
            # Audiveris may label continuation measures with composite values
            # such as ``4+1`` when a page begins mid-system.  Score IR needs a
            # stable integer for ordering and page merging, so use document
            # order for any non-integer label (the source XML remains evidence).
            try:
                number = int(raw_number)
            except (TypeError, ValueError):
                number = measure_seq + 1
            measure_seq = max(measure_seq + 1, number)
            attrs = _tag(measure_node, "attributes")
            if attrs is not None:
                active["divisions"] = int(_text(attrs, "divisions", active["divisions"]))
                key = _tag(attrs, "key")
                if key is not None: active["key"] = int(_text(key, "fifths", "0"))
                time = _tag(attrs, "time")
                if time is not None:
                    active["beats"], active["beat_type"] = int(_text(time, "beats", "4")), int(_text(time, "beat-type", "4"))
                clef = _tag(attrs, "clef")
                if clef is not None: active["clef"] = "bass" if _text(clef, "sign") == "F" else "treble"
            for note in _children(measure_node, "note"):
                staff_no = int(_text(note, "staff", "1"))
                event = _parse_note(note, active["divisions"])
                entries = staff_map.setdefault(staff_no, [])
                # MusicXML encodes a chord as one normal note followed by
                # additional notes carrying <chord/>. Their duration counts once.
                if _tag(note, "chord") is not None and entries and entries[-1][0] == number:
                    previous = entries[-1][1]
                    if previous.kind == "note":
                        previous.kind = "chord"
                        previous.pitches = [previous.pitch] if previous.pitch else []
                        previous.pitch = None
                    if previous.kind == "chord" and event.pitch:
                        previous.pitches.append(event.pitch)
                else:
                    entries.append((number, event, active.copy()))
        staves = []
        for staff_no, entries in sorted(staff_map.items()):
            measures = []
            by_number = {}
            for number, event, state in entries:
                measure = by_number.setdefault(number, Measure(number))
                measure.events.append(event)
                measure.key_fifths, measure.time_beats, measure.time_beat_type = state["key"], state["beats"], state["beat_type"]
            measures = [by_number[n] for n in sorted(by_number)]
            staves.append(Staff(f"{pid}-S{staff_no}", measures, entries[0][2]["clef"] if entries else "treble"))
        parts.append(Part(pid, names.get(pid, pid), ids.get(pid, names.get(pid, pid)), None, staves or [Staff(f"{pid}-S1")]))
    return Score(title, parts, "written", {"source_format": "musicxml"})
