"""Read engraved MusicXML into the notated model used by the jianpu projection.

This path keeps the engraved positions and durations, so playback-only timing
such as an arpeggio spread or humanisation cannot move a note or split a chord
into an extra voice. The performance projection remains the route for audio.
"""
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from ..notation_model import NotatedPart, NotatedScore

_TICKS = 480
_STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(element, name):
    for node in element:
        if _local(node.tag) == name:
            return node
    return None


def _children(element, name):
    return [node for node in element if _local(node.tag) == name]


def _text(element, name, default=None):
    node = _child(element, name)
    return node.text if node is not None and node.text is not None else default


def _descendants(element, name):
    return [node for node in element.iter() if _local(node.tag) == name]


def _ticks(duration_text, divisions):
    return round(int(duration_text) * _TICKS / divisions)


def _midi(note):
    pitch = _child(note, "pitch")
    if pitch is None:
        return None
    step = _text(pitch, "step", "C")
    alter = int(_text(pitch, "alter", "0"))
    octave = int(_text(pitch, "octave", "4"))
    return (octave + 1) * 12 + _STEPS.get(step, 0) + alter


def _tied(note):
    for tie in _children(note, "tie"):
        if tie.attrib.get("type") == "start":
            return True
    notations = _child(note, "notations")
    if notations is not None:
        for tied in _children(notations, "tied"):
            if tied.attrib.get("type") == "start":
                return True
    return False


def read_musicxml_notation(path, title=None):
    """Return a NotatedScore built from the engraved positions in a MusicXML file."""
    root = ET.parse(path).getroot()
    warnings = []
    score_title = title or next(
        (node.text for node in _descendants(root, "work-title") if node.text), None) or Path(path).stem
    names = {}
    for part in _descendants(root, "score-part"):
        identifier = part.attrib.get("id")
        names[identifier] = _text(part, "part-name", identifier)
    meters, tempos, parts = {}, {}, []
    score_end = 0
    for part_node in _descendants(root, "part"):
        pid = part_node.attrib.get("id")
        base_name = names.get(pid, pid)
        divisions, position = 1, 0
        meter = (4, 4)
        key = 0
        voice_notes = defaultdict(list)
        last_starts = {}
        staff_seen = set()
        keys = []
        grace_notes = 0
        for measure in _children(part_node, "measure"):
            attributes = _child(measure, "attributes")
            if attributes is not None:
                value = _text(attributes, "divisions")
                if value:
                    divisions = int(value)
                time = _child(attributes, "time")
                if time is not None:
                    meter = (int(_text(time, "beats", "4")), int(_text(time, "beat-type", "4")))
                key_node = _child(attributes, "key")
                if key_node is not None:
                    key = int(_text(key_node, "fifths", "0"))
            if not keys or keys[-1][1] != key:
                keys.append((position, key))
            meters.setdefault(position, meter)
            cursor = position
            length = round(meter[0] * 4 / meter[1] * _TICKS)
            for node in measure:
                tag = _local(node.tag)
                if tag == "backup":
                    cursor -= _ticks(_text(node, "duration", "0"), divisions)
                elif tag == "forward":
                    cursor += _ticks(_text(node, "duration", "0"), divisions)
                elif tag == "direction":
                    sound = _child(node, "sound")
                    if sound is not None and sound.attrib.get("tempo"):
                        tempos.setdefault(cursor, round(float(sound.attrib["tempo"])))
                elif tag != "note":
                    continue
                else:
                    if _child(node, "grace") is not None:
                        grace_notes += 1
                        continue
                    staff = int(_text(node, "staff", "1"))
                    voice = int(_text(node, "voice", "1"))
                    staff_seen.add(staff)
                    duration = _ticks(_text(node, "duration", "0"), divisions)
                    if _child(node, "chord") is not None and (staff, voice) in last_starts:
                        start = last_starts[staff, voice]
                    else:
                        start = cursor
                        last_starts[staff, voice] = start
                        cursor += duration
                    pitch = _midi(node)
                    if pitch is None:
                        continue
                    groups = voice_notes[staff, voice]
                    if groups and groups[-1][0] == start:
                        begin, end, pitches, tie = groups[-1]
                        groups[-1] = (begin, max(end, start + duration), pitches + [pitch], tie or _tied(node))
                    else:
                        groups.append((start, start + duration, [pitch], _tied(node)))
            position += length
        score_end = max(score_end, position)
        if grace_notes:
            warnings.append(f"{base_name}: {grace_notes} grace note(s) are not written in jianpu.")
        unpitched = any(_child(node, "unpitched") is not None for node in _descendants(part_node, "note"))
        if unpitched and not voice_notes:
            warnings.append(
                f"Percussion part {base_name} has no numbered-notation staff and was not written "
                "to the jianpu output.")
            continue
        multiple_staves = len(staff_seen) > 1
        first_voice = {}
        for staff, voice in voice_notes:
            first_voice[staff] = min(voice, first_voice.get(staff, voice))
        for (staff, voice), groups in sorted(voice_notes.items()):
            name = base_name
            suffixes = []
            if multiple_staves and staff != 1:
                suffixes.append(f"staff {staff}")
            if voice != first_voice[staff]:
                suffixes.append(f"voice {voice}")
            if suffixes:
                name = f"{name} ({', '.join(suffixes)})"
            parts.append(NotatedPart(name, keys[0][1] if keys else 0, groups, keys))
    return NotatedScore(score_title,
                        sorted(((tick, n, d) for tick, (n, d) in meters.items())),
                        sorted(tempos.items()), parts, warnings, score_end)
