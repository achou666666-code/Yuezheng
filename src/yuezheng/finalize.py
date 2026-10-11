"""MSCZ delivery with internal compilation and structural audit artifacts."""
import json
from pathlib import Path

from .musicxml import compile_musicxml, parse_musicxml
from .musescore import MuseScoreAdapter, MuseScoreError
from .score_ir import load_score
from .validation import validate_score


def finalize_score(score_path: str, output_dir: str, executable: str = "", allow_issues: bool = True) -> dict:
    score = load_score(score_path)
    validation = validate_score(score)
    if validation["status"] != "pass" and not allow_issues:
        return {"status": "error", "stage": "validate", "validation": validation}
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    stem = Path(score_path).stem.replace(".reviewed", "")
    internal = out / ".scorebridge"; internal.mkdir(exist_ok=True)
    xml = compile_musicxml(score, internal / f"{stem}.musicxml")
    result = {"status": "needs_review" if validation["status"] != "pass" else "pass",
              "score_path": str(Path(score_path).resolve()), "musicxml_path": str(xml.resolve()),
              "validation": validation, "exports": []}
    adapter = MuseScoreAdapter(executable=executable or None)
    for suffix in ("mscz",):
        target = out / f"{stem}.{suffix}"
        try:
            converted = adapter.convert(str(xml), str(target))
            result["exports"].append(converted)
        except (MuseScoreError, TimeoutError) as exc:
            result.setdefault("warnings", []).append({"format": suffix, "error": str(exc)})
    roundtrip = internal / f"{stem}.roundtrip.musicxml"
    if any(Path(item["output_path"]).suffix == ".mscz" for item in result["exports"]):
        mscz = next(Path(item["output_path"]) for item in result["exports"] if Path(item["output_path"]).suffix == ".mscz")
        try:
            result["roundtrip"] = adapter.convert(str(mscz), str(roundtrip))
            returned = parse_musicxml(str(roundtrip))
            result["roundtrip_audit"] = {"parts": len(returned.parts),
                "instruments": [{"id": p.id, "name": p.name, "instrument_id": p.instrument_id} for p in returned.parts]}
        except (MuseScoreError, OSError, ValueError, TimeoutError) as exc:
            result.setdefault("warnings", []).append({"format": "roundtrip", "error": str(exc)})
    if not result["exports"]:
        result["status"] = "error"
        result["stage"] = "mscz_export"
    elif "roundtrip" not in result:
        result["status"] = "incomplete"
    result["verification_scope"] = "file structure and part metadata; not source accuracy or listening verification"
    report_path = internal / f"{stem}.audit.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["audit_path"] = str(report_path.resolve())
    return result
