"""Source-linked review packets for an Agent supervising OMR output."""
import json
from dataclasses import asdict
from pathlib import Path

from .score_ir import load_score, save_score
from .patches import apply_patch


def _manifest_pages(manifest_path):
    if not manifest_path:
        return {}
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return {int(page["page"]): page for page in data.get("pages", [])}


def create_review_packet(score_path: str, manifest_path: str = "", output_path: str = "") -> dict:
    """Create one review task per measure, retaining source evidence and candidates."""
    score = load_score(score_path)
    pages = _manifest_pages(manifest_path)
    tasks = []
    for part in score.parts:
        for staff in part.staves:
            measures = staff.measures
            for index, measure in enumerate(measures):
                source = measure.source
                page_no = source.page if source and source.page else (next(iter(pages)) if len(pages) == 1 else None)
                evidence = pages.get(page_no, {}) if page_no else {}
                before = measures[index - 1].number if index else None
                after = measures[index + 1].number if index + 1 < len(measures) else None
                tasks.append({
                    "id": f"{part.id}:{staff.id}:{measure.number}",
                    "target": {"part_id": part.id, "staff_id": staff.id, "measure": measure.number},
                    "part": {"id": part.id, "name": part.name, "instrument_id": part.instrument_id,
                             "transposition": part.transposition, "clef": staff.clef},
                    "context": {"previous_measure": before, "next_measure": after},
                    "source": asdict(source) if source else None,
                    "evidence": evidence,
                    "candidate": {"key_fifths": measure.key_fifths, "time_beats": measure.time_beats,
                                  "time_beat_type": measure.time_beat_type, "tempo_bpm": measure.tempo_bpm,
                                  "tempo_beat": measure.tempo_beat, "dynamics": measure.dynamics,
                                  "directions": measure.directions,
                                  "events": [asdict(event) for event in measure.events]},
                    "decision": None,
                })
    packet = {"schema": "scorebridge.review.v1", "status": "needs_review", "score_path": str(Path(score_path).resolve()),
              "manifest_path": str(Path(manifest_path).resolve()) if manifest_path else None,
              "task_count": len(tasks), "tasks": tasks}
    destination = Path(output_path) if output_path else Path(score_path).with_suffix(".review.json")
    destination.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    packet["review_path"] = str(destination.resolve())
    return packet


def apply_review(score_path: str, decisions, output_path: str = "") -> dict:
    """Apply accepted review decisions while preserving the full score on local failures."""
    score = load_score(score_path)
    packet_meta = {}
    if isinstance(decisions, (str, Path)):
        payload = json.loads(Path(decisions).read_text(encoding="utf-8"))
        if "schema" in payload and payload["schema"] != "scorebridge.review.v1":
            return {"status": "error", "error": "Unsupported review packet schema", "schema": payload.get("schema")}
        packet_meta = {key: payload.get(key) for key in ("schema", "score_path", "manifest_path") if key in payload}
        decisions = payload.get("tasks", [])
    applied, rejected, skipped, decision_log = [], [], [], []
    for task in decisions:
        decision = task.get("decision") if isinstance(task, dict) else None
        if not decision or decision.get("action", "accept") in {"skip", "keep"}:
            skipped.append(task.get("id") if isinstance(task, dict) else None)
            decision_log.append({"id": task.get("id") if isinstance(task, dict) else None,
                                 "action": (decision or {}).get("action", "keep"),
                                 "confidence": (decision or {}).get("confidence"),
                                 "rationale": (decision or {}).get("rationale")})
            continue
        patch = dict(decision.get("patch", {}))
        patch.setdefault("operation", "replace_measure")
        target = task.get("target", {})
        for key in ("part_id", "staff_id", "measure"):
            patch.setdefault(key, target.get(key))
        updated, report = apply_patch(score, patch)
        if report.get("status") == "pass":
            score = updated
            applied.append(task.get("id", f"{patch.get('part_id')}:{patch.get('measure')}"))
            decision_log.append({"id": task.get("id"), "action": decision.get("action", "accept"),
                                 "confidence": decision.get("confidence"), "rationale": decision.get("rationale"),
                                 "result": "applied"})
        else:
            rejected.append({"id": task.get("id"), "report": report})
            decision_log.append({"id": task.get("id"), "action": decision.get("action", "accept"),
                                 "confidence": decision.get("confidence"), "rationale": decision.get("rationale"),
                                 "result": "rejected", "report": report})
    destination = Path(output_path) if output_path else Path(score_path).with_name(Path(score_path).stem + ".reviewed.json")
    save_score(score, destination)
    return {"status": "pass" if not rejected else "needs_review", "output_path": str(destination.resolve()),
            "applied": applied, "rejected": rejected, "skipped": skipped,
            "decision_log": decision_log, **packet_meta}
