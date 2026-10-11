"""High-level Agent transcription workflow."""
import json
from pathlib import Path

from .input import classify_page, prepare_input
from .omr import run_omr
from .review import apply_review, create_review_packet
from .finalize import finalize_score
from .score_ir import load_score, save_score
from copy import deepcopy


def _merge_page_scores(score_paths, output_path):
    """Concatenate page-local Score IR while retaining page order."""
    merged = None
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    for score_path in score_paths:
        page_score = load_score(score_path)
        if merged is None:
            merged = page_score
            continue
        for target_part in merged.parts:
            source_part = next((p for p in page_score.parts if p.id == target_part.id), None)
            if not source_part:
                continue
            for target_staff in target_part.staves:
                source_staff = next((s for s in source_part.staves if s.id == target_staff.id), None)
                if not source_staff:
                    continue
                offset = target_staff.measures[-1].number if target_staff.measures else 0
                for measure in source_staff.measures:
                    copied = deepcopy(measure)
                    copied.number += offset
                    target_staff.measures.append(copied)
    if merged is None:
        return None
    save_score(merged, output_path)
    return output_path


def transcribe_score(input_path: str, output_dir: str, decisions_path: str = "",
                     audiveris: str = "", musescore: str = "", dpi: int = 450) -> dict:
    """Run normalize -> OMR -> review packet -> optional decisions -> exports."""
    out = Path(output_dir).expanduser()
    evidence = prepare_input(input_path, str(out / "evidence"), dpi=dpi)
    if evidence.get("status") != "pass":
        return evidence
    # Audiveris is more reliable on the original high-resolution raster for a
    # single image; retain the generated PDF as the canonical bridge artifact.
    source_for_omr = evidence["internal_pdf"]
    if evidence.get("input_type") == "images" and evidence.get("page_count") == 1:
        source_for_omr = evidence["pages"][0].get("enhanced") or evidence["pages"][0]["rendered"]
    if evidence.get("input_type") == "pdf" and evidence.get("page_count", 0) > 1:
        page_results, score_paths, failed_pages, skipped_pages = [], [], [], []
        for page in evidence.get("pages", []):
            classification = classify_page(page["rendered"])
            page["classification"] = classification
            if classification["page_type"] == "non_score" and classification["confidence"] >= 0.95:
                skipped_pages.append(page["page"])
                page_results.append({"page": page["page"], "status": "skipped",
                                     "page_type": "non_score", "classification": classification})
                continue
            # Give run_omr the clean 450-DPI render. It creates one enhanced
            # candidate and then retries this original image automatically.
            page_source = page["rendered"]
            page_result = run_omr(page_source, str(out / "omr-pages" / f"page-{page['page']:04d}"), executable=audiveris)
            page_results.append({"page": page["page"], "status": page_result.get("status"),
                                "page_type": classification["page_type"], "classification": classification,
                                "input_variant": page_result.get("input_variant"),
                                "score_path": page_result.get("score_path"), "musicxml_path": page_result.get("musicxml_path"),
                                "error": page_result.get("error"), "stage": page_result.get("stage")})
            if page_result.get("score_path"):
                score_paths.append(page_result["score_path"])
            else:
                failed_pages.append(page["page"])
        merged_path = out / "omr" / f"{Path(input_path).stem}.score.json"
        merged_score = _merge_page_scores(score_paths, merged_path) if score_paths else None
        omr = {"status": "pass" if merged_score and not failed_pages else ("needs_review" if merged_score else "error"),
               "stage": "omr_pages", "score_path": str(Path(merged_score).resolve()) if merged_score else None,
               "page_results": page_results, "failed_pages": failed_pages, "pages_succeeded": len(score_paths),
               "skipped_pages": skipped_pages, "pages_total": len(evidence.get("pages", []))}
        summary_path = out / "run-summary.json"
        omr["summary_path"] = str(summary_path.resolve())
        summary_path.write_text(json.dumps(omr, ensure_ascii=False, indent=2), encoding="utf-8")
        Path(evidence["manifest_path"]).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        omr = run_omr(source_for_omr, str(out / "omr"), executable=audiveris)
    if omr.get("status") == "error" and evidence.get("input_type") == "images":
        # A clean rendered page is the second candidate when enhancement harms
        # staff or notehead detection.
        rendered = evidence["pages"][0]["rendered"] if evidence.get("page_count") == 1 else evidence["internal_pdf"]
        if rendered != source_for_omr:
            omr = run_omr(rendered, str(out / "omr-rendered"), executable=audiveris)
    result = {"status": omr.get("status", "error"), "stage": "omr" if omr.get("status") == "error" else "review",
              "input": evidence, "omr": omr}
    if omr.get("status") == "error":
        return result
    packet = create_review_packet(omr["score_path"], evidence["manifest_path"], str(out / "review.json"))
    result["review"] = {"path": packet["review_path"], "task_count": packet["task_count"]}
    score_path = omr["score_path"]
    if decisions_path:
        applied = apply_review(score_path, decisions_path, str(out / "reviewed.score.json"))
        result["decisions"] = applied
        if applied.get("output_path"):
            score_path = applied["output_path"]
    if decisions_path:
        result["final"] = finalize_score(score_path, str(out / "finalized"), executable=musescore)
        result["status"] = result["final"].get("status", result["status"])
        result["stage"] = "finalized"
    return result
