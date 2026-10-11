"""One-call OMR orchestration for Agent clients."""
from pathlib import Path
from typing import Optional
from zipfile import BadZipFile, ZipFile
from .engine import OMRAdapter
from yuezheng.input import inspect_input, prepare_image
from yuezheng.musicxml import parse_musicxml
from yuezheng.score_ir import save_score
from yuezheng.validation import validate_score


def _find_musicxml(directory: Path) -> Optional[Path]:
    files = sorted(directory.rglob("*.musicxml")) + sorted(directory.rglob("*.xml"))
    if files:
        return files[0]
    # Audiveris commonly exports compressed MusicXML containers (.mxl).
    # Extract the score XML beside the container so the normal parser can consume it.
    for container in sorted(directory.rglob("*.mxl")):
        try:
            with ZipFile(container) as archive:
                members = [name for name in archive.namelist()
                           if name.lower().endswith((".musicxml", ".xml"))
                           and not name.lower().endswith("container.xml")]
                if not members:
                    continue
                target = directory / f"{container.stem}.musicxml"
                target.write_bytes(archive.read(members[0]))
                return target
        except (BadZipFile, OSError, KeyError):
            continue
    return None


def run_omr(input_path: str, output_dir: str, executable: str = "", scale: int = 2) -> dict:
    """Inspect, preprocess, run Audiveris, import and validate its MusicXML output."""
    source = Path(input_path)
    destination = Path(output_dir)
    inspection = inspect_input(str(source))
    if inspection["status"] != "pass":
        return {"status": "error", "stage": "inspect", **inspection}
    destination.mkdir(parents=True, exist_ok=True)
    prepared = source
    if source.suffix.lower() != ".pdf":
        prepared = destination / f"{source.stem}.prepared.png"
        try:
            prep = prepare_image(str(source), str(prepared), scale)
        except (ImportError, ValueError, OSError) as exc:
            return {"status": "error", "stage": "prepare", "error": str(exc)}
    engine = OMRAdapter(executable or None)
    # Enhanced raster images can occasionally hurt OMR (especially old 1-bit scans).
    # Retry the original image in a clean directory before reporting failure.
    attempts = [(prepared, "prepared")]
    if source.suffix.lower() != ".pdf":
        attempts.append((source, "original"))
    result = None
    xml = None
    used_variant = None
    for candidate, variant in attempts:
        candidate_dir = destination / ("omr" if variant == "prepared" else "omr-original")
        candidate_result = engine.run(str(candidate), str(candidate_dir))
        output_dir = candidate_result.get("output_dir")
        candidate_xml = _find_musicxml(Path(output_dir)) if output_dir else None
        if candidate_xml is not None:
            # Audiveris can export a valid MXL while returning non-zero because
            # a late warning or one sheet did not complete cleanly.
            if candidate_result.get("status") != "pass":
                candidate_result["status"] = "pass"
                candidate_result["warning"] = "Audiveris returned a non-zero code after writing MusicXML"
            result, xml, used_variant = candidate_result, candidate_xml, variant
            break
        if candidate_result["status"] != "pass":
            result = candidate_result
            continue
        result = candidate_result
    if result is None:
        return {"status": "error", "stage": "omr", "error": "OMR did not run"}
    if result["status"] != "pass":
        return {"stage": "omr", **result}
    if xml is None:
        return {"status": "error", "stage": "omr_output", "error": "OMR completed but no MusicXML was found", **result}
    try:
        score = parse_musicxml(str(xml))
        score_path = destination / f"{source.stem}.score.json"
        save_score(score, score_path)
        report = validate_score(score)
        result_status = "pass" if report["status"] == "pass" else "needs_review"
        return {"status": result_status, "input": inspection, "prepared_path": str(prepared.resolve()),
                "input_variant": used_variant,
                "musicxml_path": str(xml.resolve()), "score_path": str(score_path.resolve()),
                "parts": len(score.parts), "validation": report, "omr": result}
    except (OSError, ValueError) as exc:
        return {"status": "error", "stage": "import", "musicxml_path": str(xml.resolve()), "error": str(exc)}
