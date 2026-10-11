"""Transactional, software-neutral score edits."""
from copy import deepcopy
from dataclasses import asdict

from yuezheng.score_ir import Event, Measure, Score, SourceRef
from yuezheng.score_ir.io import score_from_dict
from yuezheng.validation import validate_score


def _event(data):
    value = dict(data)
    source = value.get("source")
    value["source"] = SourceRef(**source) if isinstance(source, dict) else source
    return Event(**value)


def apply_patch(score: Score, patch: dict) -> tuple[Score, dict]:
    """Apply a high-level patch atomically and validate the result.

    The original object is never mutated. Supported operation: ``replace_measure``.
    """
    candidate = deepcopy(score)
    operation = patch.get("operation")
    if operation != "replace_measure":
        return score, {"status": "error", "issues": [{"type": "operation", "message": "only replace_measure is supported"}]}
    part_id, staff_id, number = patch.get("part_id"), patch.get("staff_id"), patch.get("measure")
    part = next((p for p in candidate.parts if p.id == part_id), None)
    staff = next((s for s in part.staves if s.id == staff_id), None) if part else None
    measure = next((m for m in staff.measures if m.number == number), None) if staff else None
    if not (part and staff and measure):
        return score, {"status": "error", "issues": [{"type": "target", "message": "part_id, staff_id, or measure was not found"}]}
    for field in ("key_fifths", "time_beats", "time_beat_type", "tempo_bpm", "tempo_beat", "dynamics", "directions"):
        if field in patch:
            setattr(measure, field, patch[field])
    measure.events = [_event(value) for value in patch.get("events", [])]
    report = validate_score(candidate)
    if report["status"] != "pass":
        return score, report
    return candidate, {"status": "pass", "operation": operation, "part_id": part_id, "staff_id": staff_id, "measure": number}
