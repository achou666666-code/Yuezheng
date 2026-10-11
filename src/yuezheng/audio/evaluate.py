"""One-to-one event scoring against held-out answers, never a recognizer."""
import json
import math
from pathlib import Path


def _read_events(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("Audio event document requires schema_version: 1")
    events = document.get("events")
    if not isinstance(events, list):
        raise ValueError("events must be an array")
    for event in events:
        if not isinstance(event, dict) or event.get("kind") not in {"note", "drum"}:
            raise ValueError("Each event needs kind note or drum")
        start, end = event.get("start_seconds"), event.get("end_seconds")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)) or start < 0 or end <= start:
            raise ValueError("Event times must be finite, nonnegative and increasing")
        if event["kind"] == "note":
            pitch = event.get("midi_pitch")
            if isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 127:
                raise ValueError("Notes need an integer midi_pitch from 0 to 127")
        elif not isinstance(event.get("drum"), str) or not event["drum"]:
            raise ValueError("Drums need a nonempty drum category")
    return document, events


def _identity(event):
    return event["kind"], event.get("midi_pitch") if event["kind"] == "note" else event["drum"]


def _matching(reference, predicted, onset_tolerance, offset_tolerance=None):
    # Maximum cardinality bipartite matching; duplicates cannot inflate recall.
    edges = []
    for expected in reference:
        candidates = [i for i, actual in enumerate(predicted)
                      if _identity(expected) == _identity(actual)
                      and abs(expected["start_seconds"] - actual["start_seconds"]) <= onset_tolerance
                      and (offset_tolerance is None or expected["kind"] == "drum"
                           or abs(expected["end_seconds"] - actual["end_seconds"]) <= offset_tolerance)]
        edges.append(sorted(candidates, key=lambda i: abs(expected["start_seconds"] - predicted[i]["start_seconds"])))
    owners = {}

    def assign(r, seen):
        for p in edges[r]:
            if p in seen:
                continue
            seen.add(p)
            if p not in owners or assign(owners[p], seen):
                owners[p] = r
                return True
        return False

    for r in range(len(reference)):
        assign(r, set())
    return sorted((r, p) for p, r in owners.items())


def _metrics(reference, predicted, pairs):
    matched = len(pairs)
    precision = matched / len(predicted) if predicted else None
    recall = matched / len(reference) if reference else None
    f1 = 2 * matched / (len(reference) + len(predicted)) if reference or predicted else None
    return {"reference_events": len(reference), "predicted_events": len(predicted), "matched": matched,
            "missed": len(reference) - matched, "extra": len(predicted) - matched,
            "precision": precision, "recall": recall, "f1": f1}


def evaluate_audio_events(reference_path, prediction_path, onset_tolerance=.05, offset_tolerance=.1):
    """Separate onset/pitch accuracy, note duration, drums and optional routing."""
    for v in (onset_tolerance, offset_tolerance):
        if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0:
            raise ValueError("Time tolerances must be finite and nonnegative")
    _, reference = _read_events(reference_path)
    document, predicted = _read_events(prediction_path)
    report = {"status": "measured", "onset_tolerance_seconds": onset_tolerance,
              "offset_tolerance_seconds": offset_tolerance,
              "recognizer": document.get("recognizer", "unspecified"),
              "evidence_mode": document.get("evidence_mode", "unspecified")}
    if document.get("evaluation_design"):
        report["evaluation_design"] = document["evaluation_design"]
    for kind in ("note", "drum"):
        expected = [e for e in reference if e["kind"] == kind]
        actual = [e for e in predicted if e["kind"] == kind]
        pairs = _matching(expected, actual, onset_tolerance)
        scores = _metrics(expected, actual, pairs)
        scores["onset_mae_seconds"] = (sum(abs(expected[r]["start_seconds"] - actual[p]["start_seconds"]) for r, p in pairs) / len(pairs) if pairs else None)
        if kind == "note":
            scores["with_offset"] = _metrics(expected, actual, _matching(expected, actual, onset_tolerance, offset_tolerance))
            scores["offset_mae_seconds"] = (sum(abs(expected[r]["end_seconds"] - actual[p]["end_seconds"]) for r, p in pairs) / len(pairs) if pairs else None)
        instrument_pairs = [(r, p) for r, p in pairs if expected[r].get("instrument_id")]
        scores["instrument_matches"] = sum(expected[r]["instrument_id"] == actual[p].get("instrument_id") for r, p in instrument_pairs)
        scores["instrument_comparisons"] = len(instrument_pairs)
        scores["unmatched_reference"] = [e for i, e in enumerate(expected) if i not in {r for r, _ in pairs}]
        scores["unmatched_prediction"] = [e for i, e in enumerate(actual) if i not in {p for _, p in pairs}]
        report[kind] = scores
    report["scope"] = "Event timing/pitch and supplied instrument identity only; not notation, playback quality or general audio accuracy."
    return report
