from collections import defaultdict
from yuezheng.musicxml.compiler import DIVISIONS, DURATIONS
from yuezheng.score_ir import Score

def validate_score(score: Score):
    issues = []
    if score.pitch_mode not in {"written", "concert"}:
        issues.append({"severity": "error", "type": "pitch_mode", "message": "pitch_mode must be written or concert"})
    if not score.parts:
        issues.append({"severity": "error", "type": "parts", "message": "score has no parts"})
    for part in score.parts:
        if not part.staves:
            issues.append({"severity": "error", "part": part.id, "type": "staves", "message": "part has no staves"}); continue
        sets = [set(m.number for m in staff.measures) for staff in part.staves]
        if any(s != sets[0] for s in sets[1:]):
            issues.append({"severity": "error", "part": part.id, "type": "measure_alignment", "message": "staves do not contain the same measures"})
        active_time = (4, 4)
        for staff in part.staves:
            for measure in staff.measures:
                if measure.time_beats is not None: active_time = (measure.time_beats, measure.time_beat_type)
                expected = active_time[0] * DIVISIONS * 4 // active_time[1]
                totals = defaultdict(int)
                for event in measure.events:
                    if event.duration not in DURATIONS:
                        issues.append({"severity": "error", "part": part.id, "staff": staff.id, "measure": measure.number, "type": "duration", "message": "unsupported duration %s" % event.duration}); continue
                    totals[event.voice] += DURATIONS[event.duration][0]
                for voice, total in totals.items():
                    if total != expected:
                        issues.append({"severity": "error", "part": part.id, "staff": staff.id, "measure": measure.number, "voice": voice, "type": "measure_duration", "expected": expected, "actual": total})
    return {"status": "pass" if not issues else "error", "issues": issues}
