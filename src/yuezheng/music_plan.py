"""Shared Agent construction plan: source, performance, notation and target bindings.

Performance times are seconds from the original audio. Notation is a separate
representation; changing the notation grid never changes the performance.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

from .audio.transcribe import validate_events


def finite(value, label, low=0, high=float("inf")):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Invalid {label}")
    return value


def validate_music_plan(plan):
    if not isinstance(plan, dict) or plan.get("schema_version") != 1 or plan.get("kind") != "scorebridge_music_plan":
        raise ValueError("Expected schema_version 1 and kind scorebridge_music_plan")
    if not isinstance(plan.get("title"), str) or not plan["title"].strip():
        raise ValueError("Plan title must be nonempty")
    performance = plan.get("performance")
    native = plan.get("notation", {}).get("native")
    if not performance and not native:
        raise ValueError("Plan needs performance events or a native notation plan")
    if native and (not isinstance(native, dict) or not native.get("score") or not native.get("steps")):
        raise ValueError("Native notation needs score and steps")
    if performance:
        validate_events(performance)
        if not performance.get("tracks") and performance["events"]:
            raise ValueError("Performance events need explicit track identities")
        for track in performance["tracks"]:
            program = track.get("gm_program")
            if program is not None and (isinstance(program, bool) or not isinstance(program, int) or not 0 <= program <= 127):
                raise ValueError("GM programs use zero-based integers 0..127")
            for c in track.get("controls", []):
                finite(c["seconds"], "controller time")
                for key in ("number", "value"):
                    if isinstance(c[key], bool) or not isinstance(c[key], int) or not 0 <= c[key] <= 127:
                        raise ValueError("Invalid MIDI controller")
            for b in track.get("pitch_bends", []):
                finite(b["seconds"], "bend time")
                if isinstance(b["value"], bool) or not isinstance(b["value"], int) or not -8192 <= b["value"] <= 8191:
                    raise ValueError("Invalid pitch bend")
        tempos = plan.get("tempo_map", [])
        if not tempos or tempos[0].get("seconds") != 0:
            raise ValueError("Tempo map must start at zero")
        previous = -1
        for point in tempos:
            pos = finite(point["seconds"], "tempo time")
            finite(point["bpm"], "quarter-note tempo", 1, 1000)
            if pos <= previous:
                raise ValueError("Tempo times must be strictly increasing")
            previous = pos
        meters = plan.get("meter_map", [])
        if not meters or meters[0].get("quarter") != 0:
            raise ValueError("Meter map must start at quarter zero")
        previous = None
        for point in meters:
            q = finite(point["quarter"], "meter position")
            n, d = point["numerator"], point["denominator"]
            if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 64 or isinstance(d, bool) or d not in (1, 2, 4, 8, 16, 32, 64):
                raise ValueError("Invalid meter")
            if previous:
                bars = (q - previous["quarter"]) / (previous["numerator"] * 4 / previous["denominator"])
                if bars <= 0 or abs(bars - round(bars)) > 1e-6:
                    raise ValueError("Meter changes must start on a measure boundary")
            previous = point
        grid = plan.get("notation", {}).get("grid_quarters", .25)
        if grid not in (.0625, .125, .25, .5, 1):
            raise ValueError("Automatic notation grid must be 1/64..1/4 note; use native notation for tuplets")
        key = plan.get("notation", {}).get("key_fifths")
        if key is not None and (isinstance(key, bool) or not isinstance(key, int) or not -7 <= key <= 7):
            raise ValueError("Invalid notated key signature")
    # Also reject nonfinite annotations before any editor receives the plan.
    json.dumps(plan, allow_nan=False)
    return plan


def seconds_to_quarters(seconds, tempos):
    quarters = 0.0
    for i, point in enumerate(tempos):
        end = tempos[i + 1]["seconds"] if i + 1 < len(tempos) else seconds
        if seconds <= point["seconds"]:
            break
        quarters += (min(seconds, end) - point["seconds"]) * point["bpm"] / 60
        if seconds <= end:
            break
    return quarters


def load_music_plan(path):
    return validate_music_plan(json.loads(Path(path).read_text(encoding="utf-8")))


def make_music_plan(input_path, output_path, title="", bpm=None, numerator=4, denominator=4):
    """Wrap Agent/engine events or an existing native plan without changing notes."""
    source = Path(input_path).resolve()
    record = json.loads(source.read_text(encoding="utf-8"))
    if record.get("kind") == "scorebridge_music_plan":
        plan = copy.deepcopy(record)
    else:
        plan = {"schema_version": 1, "kind": "scorebridge_music_plan", "title": title or source.stem,
                "source": {"record_path": str(source), "record_sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
                "warnings": [], "bindings": {}, "notation": {}}
        if "score" in record and "steps" in record:
            plan["notation"]["native"] = record
            plan["title"] = title or record["score"].get("title", source.stem)
        else:
            if "events_path" in record:
                record = json.loads(Path(record["events_path"]).read_text(encoding="utf-8"))
            plan["source"].update({k: record[k] for k in ("source_path", "source_sha256", "recognizer") if k in record})
            plan["performance"] = copy.deepcopy(record)
            tempo = bpm if bpm is not None else record.get("timing", {}).get("bpm", 120)
            tempo_source = "agent" if bpm is not None else record.get("timing", {}).get("source", "serialization_default")
            plan["tempo_map"] = [{"seconds": 0, "bpm": tempo, "source": tempo_source}]
            plan["meter_map"] = [{"quarter": 0, "numerator": numerator, "denominator": denominator,
                                  "source": "agent" if bpm is not None else "provisional"}]
            plan["notation"] = {"grid_quarters": .25, "pitch_mode": "concert", "key_fifths": None}
            plan["warnings"] = list(record.get("warnings", []))
            if tempo_source == "serialization_default":
                plan["warnings"].append("120 BPM is an internal serialization clock, not an identified tempo. Agent should supply musical timing before notation delivery.")
            elif tempo_source == "beat_tracker_estimate":
                plan["warnings"].append("Beat-tracker tempo is provisional; Agent resolves meter, half/double pulse and tempo changes.")
            plan["warnings"].append("Automatic notation uses a provisional grid and pitch spelling. Original performance times are preserved.")
    if title:
        plan["title"] = title
    validate_music_plan(plan)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(destination)
    return {"status": "planned", "plan_path": str(destination), "warnings": plan.get("warnings", [])}
