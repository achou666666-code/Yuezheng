"""Jianpu (numbered notation) projection of a music plan.

One internal note model feeds two public files:

* ``.jly`` - input for jianpu-ly, which renders LilyPond and from that PDF;
* ``.txt`` - a compact reading copy for people who do not have LilyPond.

The projection uses the same provisional grid as the MusicXML projection, so
both notations agree on where a note starts and how long it lasts. Nothing is
invented or silently dropped: a missing key signature, a tempo change inside a
bar and unpitched percussion are reported instead of guessed.
"""
from .music_plan import seconds_to_quarters
from .notation_grid import bars as _bars, lanes as _lanes

KEY_NAMES = {0: "C", 1: "G", 2: "D", 3: "A", 4: "E", 5: "B", 6: "F#", 7: "C#",
             -1: "F", -2: "Bb", -3: "Eb", -4: "Ab", -5: "Db", -6: "Gb", -7: "Cb"}

# (pitch class above the tonic) -> (scale degree, accidental)
_DEGREES = {0: (1, ""), 2: (2, ""), 4: (3, ""), 5: (4, ""), 7: (5, ""),
            9: (6, ""), 11: (7, ""), 1: (1, "#"), 3: (3, "b"),
            6: (4, "#"), 8: (6, "b"), 10: (7, "b")}

# ticks: (prefix, suffix, extension dashes) for each serialization
_JLY = {1920: ("", "", 3), 1440: ("", "", 2), 960: ("", "", 1), 720: ("", ".", 0),
        480: ("", "", 0), 360: ("q", ".", 0), 240: ("q", "", 0),
        180: ("s", ".", 0), 120: ("s", "", 0), 60: ("d", "", 0), 30: ("h", "", 0)}
_TEXT = {1920: ("", "", 3), 1440: ("", "", 2), 960: ("", "", 1), 720: ("", ".", 0),
         480: ("", "", 0), 360: ("_", ".", 0), 240: ("_", "", 0),
         180: ("__", ".", 0), 120: ("__", "", 0), 60: ("___", "", 0), 30: ("____", "", 0)}

_CHUNK_ORDER = (1920, 1440, 960, 720, 480, 360, 240, 180, 120, 60, 30)


def _chunks(length):
    result = []
    for size in _CHUNK_ORDER:
        while length >= size:
            result.append(size)
            length -= size
    if length:
        raise ValueError("Duration is not representable in jianpu")
    return result


def _pitch_token(pitch, tonic):
    degree, accidental = _DEGREES[(pitch - tonic) % 12]
    octave = (pitch - (60 + tonic)) // 12
    mark = "'" * octave if octave > 0 else "," * (-octave)
    return f"{accidental}{degree}{mark}"


def _items(groups, start, end):
    """Turn the groups overlapping one bar into rests and notes filling the bar."""
    items, cursor = [], start
    for begin, stop, events in groups:
        if stop <= start or begin >= end:
            continue
        left, right = max(begin, start), min(stop, end)
        if left > cursor:
            items.append(("rest", [], left - cursor, False))
        pitches = sorted({event["midi_pitch"] for event in events})
        items.append(("note", pitches, right - left, right < stop))
        cursor = right
    if cursor < end:
        items.append(("rest", [], end - cursor, False))
    if sum(item[2] for item in items) != end - start:
        raise ValueError("Bar is not filled by the notation grid")
    return items


def _split(items):
    result = []
    for kind, pitches, length, tie_after in items:
        chunks = _chunks(length)
        for index, chunk in enumerate(chunks):
            # Only notes tie; a rest split on the grid stays two plain rests.
            tie = kind == "note" and (tie_after or index < len(chunks) - 1)
            result.append((kind, pitches, chunk, tie))
    return result


def _write_item(kind, pitches, length, tie_after, tonic, table):
    prefix, suffix, dashes = table[length]
    body = "0" if kind == "rest" else "".join(_pitch_token(p, tonic) for p in pitches)
    return prefix + body + suffix + " -" * dashes + (" ~" if tie_after else "")


def _text_item(kind, pitches, length, tie_after, tonic, table):
    if kind == "rest":
        body = "0"
    elif len(pitches) > 1:
        body = "(" + " ".join(_pitch_token(p, tonic) for p in pitches) + ")"
    else:
        body = _pitch_token(pitches[0], tonic)
    prefix, suffix, dashes = table[length]
    return prefix + body + suffix + " -" * dashes + (" ~" if tie_after else "")


def _parts(plan, warnings):
    result, seen = [], {}
    for track in plan["performance"]["tracks"]:
        if track.get("is_drum"):
            if any(event["track"] == track["id"] for event in plan["performance"]["events"]):
                warnings.append(
                    f"Percussion track {track.get('name', track['id'])} has no numbered-notation "
                    "staff and was not written to the jianpu output.")
            continue
        active = [lane for lane in _lanes(plan, track) if lane]
        if len(active) > 1:
            warnings.append(
                f"Track {track.get('name', track['id'])} produces {len(active)} voices; playback "
                "timing such as an arpeggio can separate chord notes into extra voices.")
        for index, lane in enumerate(active):
            name = track.get("name") or track["id"]
            if index:
                name = f"{name} (voice {index + 1})"
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                name = f"{name} ({seen[name]})"
            result.append((name, lane))
    return result


def write_jianpu(plan, jly_path, text_path=None):
    """Write a jianpu-ly input and, optionally, a compact reading copy."""
    warnings = []
    key = plan.get("notation", {}).get("key_fifths")
    if key is None:
        warnings.append("No key signature was supplied; the jianpu projection assumes C major (1=C).")
        key = 0
    key = int(key)
    if key not in KEY_NAMES:
        raise ValueError("Jianpu needs a key signature from -7 to 7")
    tonic = (7 * key) % 12
    parts = _parts(plan, warnings)
    if not parts:
        raise ValueError("Nothing to notate: the plan has no pitched events")
    last = max(stop for _, lane in parts for _, stop, _ in lane)
    bars = _bars(plan, last)
    if any(meter["denominator"] != 4 for meter in plan["meter_map"]):
        warnings.append(
            "A meter in this plan does not use a quarter-note beat; jianpu dashes and beams "
            "follow quarter beats, so they may not match the printed beat of that meter.")
    bar_starts = {start for start, _, _ in bars}
    tempo = {}
    for point in plan["tempo_map"]:
        tick = round(seconds_to_quarters(point["seconds"], plan["tempo_map"]) * 480)
        tempo[tick] = round(point["bpm"])
        if tick not in bar_starts:
            warnings.append(
                f"Tempo change at tick {tick} falls inside a bar; jianpu shows it at the "
                "next bar line, the performance keeps the original timing.")
    # A change inside a bar is displayed at the next bar line rather than dropped.
    shown = {}
    ordered = sorted(bar_starts)
    for tick, bpm in sorted(tempo.items()):
        if tick in bar_starts:
            shown[tick] = bpm
        else:
            later = next((start for start in ordered if start > tick), None)
            if later is not None:
                shown[later] = bpm
    first = bars[0][2]
    opening_bpm = tempo.get(0)
    jly = [f"title={plan['title']}",
           # Marks follow the digit, including inside chords; without this the
           # parser rejects a chord that mixes marked and unmarked members.
           "OctavesAfter",
           f"1={KEY_NAMES[key]} {first['numerator']}/{first['denominator']}"]
    if opening_bpm:
        jly.append(f"4={opening_bpm}")
    text = [f"1={KEY_NAMES[key]} {first['numerator']}/{first['denominator']}"
            + (f" \u2669={opening_bpm}" if opening_bpm else ""),
            f"title: {plan['title']}"]
    previous_meter = (first["numerator"], first["denominator"])
    previous_tempo = opening_bpm
    for index, (name, lane) in enumerate(parts):
        if index:
            jly.append("NextPart")
        jly.extend(["", f"instrument={name}"])
        text.extend(["", f"[{name}]"])
        for start, end, meter in bars:
            current = (meter["numerator"], meter["denominator"])
            meter_prefix = ""
            if current != previous_meter:
                meter_prefix = f"{current[0]}/{current[1]} "
                previous_meter = current
            tempo_prefix = ""
            bpm = shown.get(start)
            if bpm and bpm != previous_tempo:
                tempo_prefix = f"4={bpm} "
                text_tempo_prefix = f"\u2669={bpm} "
                previous_tempo = bpm
            else:
                text_tempo_prefix = ""
            items = _split(_items(lane, start, end))
            jly.append(meter_prefix + tempo_prefix + " ".join(
                _write_item(*item, tonic, _JLY) for item in items) + " |")
            text.append(meter_prefix + text_tempo_prefix + " ".join(
                _text_item(*item, tonic, _TEXT) for item in items) + " |")
    jly_path.parent.mkdir(parents=True, exist_ok=True)
    jly_path.write_text("\n".join(jly) + "\n", encoding="utf-8")
    result = {"jly_path": str(jly_path), "parts": len(parts), "warnings": warnings}
    if text_path:
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text("\n".join(text) + "\n", encoding="utf-8")
        result["text_path"] = str(text_path)
    return result
