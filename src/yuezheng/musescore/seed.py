"""Create a playable MSCZ scaffold before live MCP notation entry."""
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4
from xml.etree.ElementTree import Element, ElementTree, SubElement

from yuezheng.instruments import instrument_spec

from .adapter import MuseScoreAdapter, MuseScoreError
from .catalog import scaffold_instrument


DIVISIONS = 24
_CLEFS = {
    "treble": ("G", "2"),
    "bass": ("F", "4"),
    "alto": ("C", "3"),
    "tenor": ("C", "4"),
    "percussion": ("percussion", "2"),
}
_MUSESCORE_ID_ALIASES = {
    "wind.flutes.flute": "flute", "flute": "flute",
    "wind.reed.oboe": "oboe", "oboe": "oboe",
    "wind.reed.bassoon": "bassoon", "bassoon": "bassoon",
    "wind.reed.clarinet.bflat": "bb-clarinet", "clarinet in bb": "bb-clarinet",
    "clarinet in b-flat": "bb-clarinet", "bb-clarinet": "bb-clarinet",
    "wind.reed.clarinet.bass": "bass-clarinet", "bass clarinet in bb": "bass-clarinet",
    "brass.trumpet.bflat": "bb-trumpet", "trumpet in bb": "bb-trumpet",
    "brass.french-horn": "horn", "horn in f": "horn", "horn": "horn",
    "brass.trombone": "trombone", "trombone": "trombone",
    "brass.tuba": "tuba", "tuba": "tuba", "drum.timpani": "timpani", "timpani": "timpani",
    "strings.violin": "violin", "violin": "violin", "strings.viola": "viola", "viola": "viola",
    "strings.cello": "violoncello", "violoncello": "violoncello", "cello": "violoncello",
    "strings.contrabass": "contrabass", "contrabass": "contrabass",
    "keyboard.piano": "piano", "piano": "piano",
}
_PITCHED_MIDI_CHANNELS = tuple(range(1, 10)) + tuple(range(11, 17))


def _positive_int(value, label, maximum):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > maximum:
        raise ValueError(f"{label} must be an integer from 1 to {maximum}")
    return value


def _normalise_spec(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("score specification must be an object")
    title = spec.get("title", "Untitled Score")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a nonempty string")
    measures = _positive_int(spec.get("measures", 1), "measures", 10000)
    time = spec.get("time", {"beats": 4, "beat_type": 4})
    if not isinstance(time, dict):
        raise ValueError("time must be an object")
    beats = _positive_int(time.get("beats"), "time.beats", 64)
    beat_type = time.get("beat_type")
    if beat_type not in {1, 2, 4, 8, 16, 32, 64}:
        raise ValueError("time.beat_type must be 1, 2, 4, 8, 16, 32, or 64")
    duration = beats * 4 * DIVISIONS
    if duration % beat_type:
        raise ValueError("time signature cannot be represented exactly")
    key_fifths = spec.get("key_fifths", 0)
    if not isinstance(key_fifths, int) or isinstance(key_fifths, bool) or not -7 <= key_fifths <= 7:
        raise ValueError("key_fifths must be an integer from -7 to 7")
    tempo = spec.get("tempo_bpm")
    if tempo is not None and (not isinstance(tempo, (int, float)) or isinstance(tempo, bool) or tempo <= 0 or tempo > 1000):
        raise ValueError("tempo_bpm must be greater than 0 and at most 1000")
    parts = spec.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("parts must be a nonempty array")
    if len(parts) > 128:
        raise ValueError("parts may contain at most 128 entries")
    normalised_parts = []
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            raise ValueError(f"parts[{index}] must be an object")
        name = part.get("name")
        instrument_id = part.get("instrument_id")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"parts[{index}].name must be a nonempty string")
        if not isinstance(instrument_id, str) or not instrument_id.strip():
            raise ValueError(f"parts[{index}].instrument_id must be a nonempty string")
        known = instrument_spec(instrument_id)
        musescore_id = part.get("musescore_id", _MUSESCORE_ID_ALIASES.get(instrument_id.casefold(), instrument_id))
        if not isinstance(musescore_id, str) or not musescore_id.strip():
            raise ValueError(f"parts[{index}].musescore_id must be a nonempty string")
        known = {**known, **scaffold_instrument(musescore_id)}
        sound = part.get("instrument_sound", known.get("instrument_sound"))
        program = part.get("midi_program", known.get("midi_program"))
        if not isinstance(sound, str) or not sound.strip() or not isinstance(program, int) or not 1 <= program <= 128:
            raise ValueError(
                f"parts[{index}] instrument is unresolved; provide a known instrument_id "
                "or explicit instrument_sound and midi_program"
            )
        clefs = part.get("clefs", [part.get("clef", known.get("clef", "treble"))])
        if not isinstance(clefs, list) or not clefs or len(clefs) > 4:
            raise ValueError(f"parts[{index}].clefs must contain one to four clefs")
        if any(clef not in _CLEFS for clef in clefs):
            raise ValueError(f"parts[{index}].clefs contains an unsupported clef")
        normalised_parts.append({
            "id": f"P{index + 1}", "name": name.strip(), "instrument_id": musescore_id.strip(),
            "instrument_sound": sound.strip(), "midi_program": program, "clefs": clefs,
            "unpitched": known.get("unpitched", False), "midi_unpitched": known.get("midi_unpitched"),
            "transpose_diatonic": part.get("transpose_diatonic", known.get("transpose_diatonic")),
            "transpose_chromatic": part.get("transpose_chromatic", known.get("transpose_chromatic")),
        })
    return {"title": title.strip(), "measures": measures, "beats": beats,
            "beat_type": beat_type, "measure_duration": duration // beat_type,
            "key_fifths": key_fifths, "tempo_bpm": tempo, "parts": normalised_parts}


def build_seed_musicxml(spec: dict, output_path: str, target_id: str = "") -> Path:
    """Write a rest-filled MusicXML scaffold used only as MuseScore input."""
    data = _normalise_spec(spec)
    root = Element("score-partwise", version="4.0")
    work = SubElement(root, "work")
    SubElement(work, "work-title").text = data["title"]
    if target_id:
        identification = SubElement(root, "identification")
        miscellaneous = SubElement(identification, "miscellaneous")
        SubElement(miscellaneous, "miscellaneous-field",
                   name="scorebridgeTargetId").text = target_id
    part_list = SubElement(root, "part-list")
    for index, part in enumerate(data["parts"]):
        score_part = SubElement(part_list, "score-part", id=part["id"])
        SubElement(score_part, "part-name").text = part["name"]
        score_instrument = SubElement(score_part, "score-instrument", id=part["id"] + "-I1")
        SubElement(score_instrument, "instrument-name").text = part["name"]
        SubElement(score_instrument, "instrument-sound").text = part["instrument_sound"]
        midi = SubElement(score_part, "midi-instrument", id=part["id"] + "-I1")
        SubElement(midi, "midi-channel").text = str(10 if part["unpitched"] else _PITCHED_MIDI_CHANNELS[index % len(_PITCHED_MIDI_CHANNELS)])
        SubElement(midi, "midi-program").text = str(part["midi_program"])
        if part["unpitched"]:
            SubElement(midi, "midi-unpitched").text = str(part["midi_unpitched"])
    for part in data["parts"]:
        part_element = SubElement(root, "part", id=part["id"])
        for measure_number in range(1, data["measures"] + 1):
            measure = SubElement(part_element, "measure", number=str(measure_number))
            if measure_number == 1:
                attributes = SubElement(measure, "attributes")
                SubElement(attributes, "divisions").text = str(DIVISIONS)
                if not part["unpitched"]:
                    key = SubElement(attributes, "key")
                    SubElement(key, "fifths").text = str(data["key_fifths"])
                time = SubElement(attributes, "time")
                SubElement(time, "beats").text = str(data["beats"])
                SubElement(time, "beat-type").text = str(data["beat_type"])
                if len(part["clefs"]) > 1:
                    SubElement(attributes, "staves").text = str(len(part["clefs"]))
                if part["transpose_chromatic"] is not None:
                    transpose = SubElement(attributes, "transpose")
                    SubElement(transpose, "diatonic").text = str(part["transpose_diatonic"])
                    SubElement(transpose, "chromatic").text = str(part["transpose_chromatic"])
                for staff_number, clef_name in enumerate(part["clefs"], 1):
                    clef = SubElement(attributes, "clef")
                    if len(part["clefs"]) > 1:
                        clef.set("number", str(staff_number))
                    sign, line = _CLEFS[clef_name]
                    SubElement(clef, "sign").text = sign
                    SubElement(clef, "line").text = line
                if data["tempo_bpm"] is not None and part["id"] == "P1":
                    direction = SubElement(measure, "direction", placement="above")
                    direction_type = SubElement(direction, "direction-type")
                    metronome = SubElement(direction_type, "metronome")
                    SubElement(metronome, "beat-unit").text = "quarter"
                    SubElement(metronome, "per-minute").text = str(data["tempo_bpm"])
                    SubElement(direction, "sound", tempo=str(data["tempo_bpm"]))
            for staff_number in range(1, len(part["clefs"]) + 1):
                if staff_number > 1:
                    backup = SubElement(measure, "backup")
                    SubElement(backup, "duration").text = str(data["measure_duration"])
                note = SubElement(measure, "note")
                SubElement(note, "rest", measure="yes")
                SubElement(note, "duration").text = str(data["measure_duration"])
                SubElement(note, "voice").text = "1"
                if len(part["clefs"]) > 1:
                    SubElement(note, "staff").text = str(staff_number)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return output


def create_seed_score(spec: dict, output_path: str, executable: str = "", open_editor: bool = False,
                      adapter: Optional[MuseScoreAdapter] = None,
                      binder: Optional[Callable] = None) -> dict:
    """Create an MSCZ scaffold, optionally open it, and return follow-up instrument steps."""
    destination = Path(output_path)
    if destination.suffix.lower() != ".mscz":
        return {"status": "error", "error": "output_path must end in .mscz"}
    try:
        data = _normalise_spec(spec)
    except ValueError as exc:
        return {"status": "error", "stage": "specification", "error": str(exc)}
    target_id = "scorebridge-" + uuid4().hex
    internal = destination.parent / ".scorebridge" / (destination.stem + ".seed.musicxml")
    build_seed_musicxml(spec, str(internal), target_id=target_id)
    backend = adapter or MuseScoreAdapter(executable=executable or None)
    try:
        converted = backend.convert(str(internal), str(destination))
    except (MuseScoreError, OSError, TimeoutError) as exc:
        return {"status": "error", "stage": "musescore", "error": str(exc),
                "internal_musicxml": str(internal.resolve())}
    result = {
        "status": "pass", "mscz_path": converted["output_path"],
        "title": data["title"], "measures": data["measures"],
        "time": {"beats": data["beats"], "beat_type": data["beat_type"]},
        "parts": [{"part": index, "name": part["name"],
                   "instrument_id": part["instrument_id"], "staves": len(part["clefs"])}
                  for index, part in enumerate(data["parts"])],
        "instrument_steps": [
            {"id": f"instrument-{index + 1}", "action": "setPartInstrument",
             "params": {"part": index, "instrumentId": part["instrument_id"], "name":part["name"]}}
            for index, part in enumerate(data["parts"])
        ],
        "internal_musicxml": str(internal.resolve()),
        "target": {
            "targetId": target_id,
            "scoreName": destination.stem,
            "title": data["title"],
            "numMeasures": data["measures"],
            "numStaves": sum(len(part["clefs"]) for part in data["parts"]),
        },
    }
    if open_editor:
        try:
            if binder is None:
                from .connect import bind_editor_score
                binder = bind_editor_score
            result["editor"] = binder(str(destination), result["target"], adapter=backend)
            if result["editor"].get("status") != "bound":
                result["status"] = "incomplete"
                result["stage"] = "bind_editor"
                result["error"] = result["editor"].get("error", "MuseScore target binding failed")
        except (MuseScoreError, OSError) as exc:
            result["status"] = "incomplete"
            result["stage"] = "bind_editor"
            result["error"] = str(exc)
    return result
