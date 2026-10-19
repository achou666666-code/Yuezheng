"""Yuezheng MCP entry point. Install with `pip install -e '.[mcp]'`."""
import json
from pathlib import Path
from typing import Optional
from yuezheng.score_ir import load_score
from yuezheng.musicxml import compile_musicxml
from yuezheng.validation import validate_score
from yuezheng.musescore import (MuseScoreAdapter, MuseScoreError, MuseScoreWebSocketBackend,
                                  MuseScoreWebSocketError, bind_editor_score, create_seed_score)
from yuezheng.patches import apply_patch
from yuezheng.score_ir import save_score
from yuezheng.input import classify_page, inspect_input, prepare_image, prepare_input
from yuezheng.omr import OMRAdapter, run_omr
from yuezheng.musicxml import parse_musicxml
from yuezheng.review import create_review_packet, apply_review
from yuezheng.finalize import finalize_score
from yuezheng.workflow import transcribe_score
from yuezheng.doctor import diagnose
from yuezheng.instrument_audit import audit_instruments
from yuezheng.agent_workflow import prepare_agent_job, execute_plan_file

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise SystemExit("Install Yuezheng with the mcp extra: pip install -e '.[mcp]'") from exc

mcp = FastMCP("Yuezheng")

@mcp.tool()
def music_plan(input_path: str, output_path: str, title: str = "", bpm: Optional[float] = None,
               numerator: int = 4, denominator: int = 4) -> dict:
    """Wrap Agent recognition or engine events in a shared source/performance/notation plan. Agent supplies timing internally."""
    from yuezheng.music_plan import make_music_plan
    try:
        return make_music_plan(input_path, output_path, title, bpm, numerator, denominator)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def music_deliver(input_path: str, output_dir: str, formats: list[str], executable: str = "", ace_cli: str = "", sibelius_url: str = "") -> dict:
    """Deliver selected MSCZ/SIB/MusicXML/PDF/multitrack MIDI/ACE/audio outputs. Does not recognize music; use Agent or audio_transcribe first."""
    from yuezheng.music_delivery import deliver_music_plan
    return deliver_music_plan(input_path, output_dir, formats, executable, ace_cli, sibelius_url)

@mcp.tool()
def ace_status(executable: str = "") -> dict:
    """Read-only official ACE Studio CLI connection check."""
    from yuezheng.ace.adapter import ACEStudioAdapter
    return ACEStudioAdapter(executable).status()

@mcp.tool()
def sibelius_status(url: str = "") -> dict:
    """Inspect the official local Sibelius Connect endpoint and installed Yuezheng bridge."""
    from yuezheng.sibelius import sibelius_status as inspect
    return inspect(url)

@mcp.tool()
def sibelius_install_plugin(destination: str = "") -> dict:
    """Install Yuezheng's bundled ManuScript bridge in Sibelius' user plug-in directory."""
    from yuezheng.sibelius import install_sibelius_plugin
    return install_sibelius_plugin(destination)

@mcp.tool()
def sibelius_create_score(musicxml_path: str, output_path: str, url: str = "") -> dict:
    """Open MusicXML through official Sibelius Connect and save an editable native SIB score."""
    from yuezheng.sibelius import SibeliusError, create_sibelius_score
    try:
        return create_sibelius_score(musicxml_path, output_path, url)
    except (SibeliusError, OSError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def audio_backends(cache_dir: str = "") -> dict:
    """Inspect real optional engine runtimes without downloading models. Installed is not measured transcription accuracy."""
    from yuezheng.audio.backends import audio_backends as inspect
    return inspect(cache_dir)

@mcp.tool()
def audio_install(engine: str, cache_dir: str = "") -> dict:
    """Install only one optional audio engine in a separate Python runtime; preserve the Agent/core environment."""
    from yuezheng.audio.backends import install_backend
    return install_backend(engine, cache_dir)

@mcp.tool()
def audio_transcribe(input_path: str, output_dir: str, hint: str = "auto", engine: str = "auto",
                     cache_dir: str = "", auto_install: bool = True, fallback: bool = True,
                     combine: bool = False, device: str = "cpu", timeout: int = 1800) -> dict:
    """Recognize audio with optional engines, automatic fallback and cached recovery. Agent supplies hints internally and resolves candidate evidence."""
    from yuezheng.audio.transcribe import transcribe_audio
    return transcribe_audio(input_path, output_dir, hint, engine, cache_dir, auto_install, fallback, combine, device, timeout)

@mcp.tool()
def audio_separate(input_path: str, output_dir: str, cache_dir: str = "", auto_install: bool = True,
                   device: str = "cpu", timeout: int = 1800) -> dict:
    """Optional time-aligned audio stems; not MIDI transcription and not individual orchestral parts. Keep original mix as evidence."""
    from yuezheng.audio.transcribe import separate_audio
    return separate_audio(input_path, output_dir, cache_dir, auto_install, device, timeout)

@mcp.tool()
def audio_prepare(input_path: str, output_dir: str, segment_seconds: float = 8.0, overlap_seconds: float = 1.0, midi_low: int = 24, midi_high: int = 108) -> dict:
    """Prepare time-linked audio/spectral evidence for the calling Agent. Does not recognize music or call DAW transcription."""
    from yuezheng.audio import prepare_audio
    return prepare_audio(input_path, output_dir, segment_seconds, overlap_seconds, midi_low, midi_high)

@mcp.tool()
def audio_evaluate(reference_path: str, prediction_path: str, onset_tolerance: float = .05, offset_tolerance: float = .1) -> dict:
    """Benchmark Agent event predictions against held-out reference notes; never use reference as recognition input."""
    from yuezheng.audio import evaluate_audio_events
    try:
        return evaluate_audio_events(reference_path, prediction_path, onset_tolerance, offset_tolerance)
    except (ValueError, OSError) as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def musescore_connect() -> dict:
    """Check a live plugin connection. For unattended work use musescore_build_score/apply_plan."""
    from yuezheng.musescore.connect import connect_editor
    return connect_editor()

@mcp.tool()
def yuezheng_doctor() -> dict:
    """Check Python, image, OMR, MuseScore and MCP dependencies."""
    return diagnose()

@mcp.tool(name="scorebridge_doctor")
def scorebridge_doctor_compatibility() -> dict:
    """Compatibility alias for the legacy ScoreBridge doctor tool."""
    return yuezheng_doctor()

@mcp.tool()
def score_validate(input_path: str) -> dict:
    """Validate a Score IR JSON file before it is sent to notation software."""
    return validate_score(load_score(input_path))

@mcp.tool()
def score_compile(input_path: str, output_path: str, allow_issues: bool = False) -> dict:
    """Compile a validated Score IR JSON document to editable MusicXML."""
    score=load_score(input_path); report=validate_score(score)
    if report["status"] != "pass" and not allow_issues: return report
    output=compile_musicxml(score, output_path)
    return {"status":"pass" if report["status"] == "pass" else "needs_review", "output_path":str(output.resolve()), "validation": report}

@mcp.tool()
def score_inspect(input_path: str) -> dict:
    """Return the score title, pitch mode, parts, staves and measure counts."""
    score=load_score(input_path)
    return {"title":score.title,"pitch_mode":score.pitch_mode,"parts":[{"id":p.id,"name":p.name,"instrument_id":p.instrument_id,"staves":len(p.staves),"measures":[len(s.measures) for s in p.staves]} for p in score.parts]}

@mcp.tool()
def score_instrument_audit(input_path: str) -> dict:
    """Audit every part's instrument mapping before MuseScore export."""
    return audit_instruments(load_score(input_path))

@mcp.tool()
def score_apply_patch(input_path: str, patch: dict, output_path: str = "") -> dict:
    """Apply one validated, high-level edit without mutating the input file."""
    score = load_score(input_path)
    updated, report = apply_patch(score, patch)
    if report["status"] != "pass":
        return report
    destination = output_path or input_path
    save_score(updated, destination)
    return {**report, "output_path": str(Path(destination).resolve())}

@mcp.tool()
def musescore_status() -> dict:
    """Detect a local MuseScore executable and report the available backend."""
    return MuseScoreAdapter().status()

@mcp.tool()
def musescore_open(input_path: str, executable: str = "") -> dict:
    """Open an existing MSCZ or MusicXML file in MuseScore."""
    try:
        return MuseScoreAdapter(executable=executable or None).open_score(input_path)
    except (MuseScoreError, OSError) as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def musescore_bind_score(input_path: str, target: dict, executable: str = "", url: str = "") -> dict:
    """Open an MSCZ in the MCP-owning MuseScore process and verify its exact identity."""
    try:
        return bind_editor_score(input_path, target,
                                 adapter=MuseScoreAdapter(executable=executable or None),
                                 bridge=MuseScoreWebSocketBackend(url=url or None))
    except (MuseScoreError, OSError) as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def musescore_create_score(specification: dict, output_path: str, executable: str = "", open_editor: bool = False) -> dict:
    """Create a playable MSCZ scaffold from parts, meter and measure count, then optionally open it."""
    return create_seed_score(specification, output_path, executable, open_editor)

@mcp.tool()
def musescore_convert(input_path: str, output_path: str, executable: str = "") -> dict:
    """Convert MusicXML or MSCZ through MuseScore's command line exporter."""
    try:
        return {"status": "pass", **MuseScoreAdapter(executable=executable or None).convert(input_path, output_path)}
    except (MuseScoreError, TimeoutError) as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def musescore_websocket_status(url: str = "") -> dict:
    """Check a running MuseScore QML/WebSocket plugin."""
    return MuseScoreWebSocketBackend(url=url or None).status()

@mcp.tool()
def musescore_websocket_command(action: str, params: Optional[dict] = None, url: str = "") -> dict:
    """Send one command to a compatible MuseScore plugin, such as getScore or addNote."""
    try:
        return {"status": "pass", "response": MuseScoreWebSocketBackend(url=url or None).command(action, params or {})}
    except MuseScoreWebSocketError as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def score_build_mscz(input_path: str, musicxml_path: str, mscz_path: str, executable: str = "", allow_issues: bool = False) -> dict:
    """Validate Score IR, compile MusicXML, then ask MuseScore for an MSCZ."""
    score = load_score(input_path)
    report = validate_score(score)
    if report["status"] != "pass" and not allow_issues:
        return report
    xml = compile_musicxml(score, musicxml_path)
    try:
        converted = MuseScoreAdapter(executable=executable or None).convert(str(xml), mscz_path)
    except (MuseScoreError, TimeoutError) as exc:
        return {"status": "error", "stage": "musescore", "error": str(exc), "musicxml_path": str(xml.resolve())}
    return {"status": "pass" if report["status"] == "pass" else "needs_review", "musicxml_path": str(xml.resolve()), "mscz_path": converted["output_path"], "validation": report}

@mcp.tool()
def input_inspect(input_path: str) -> dict:
    """Inspect a PDF or raster score before OMR processing."""
    return inspect_input(input_path)

@mcp.tool()
def image_prepare(input_path: str, output_path: str, scale: int = 2) -> dict:
    """Upscale and clean a raster score image for a later OMR pass."""
    try:
        return prepare_image(input_path, output_path, scale)
    except (ImportError, ValueError, OSError) as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def input_prepare(input_path: str, output_dir: str, dpi: int = 450, enhance: bool = True) -> dict:
    """Normalize a PDF, image, or image directory into a source-linked evidence package."""
    return prepare_input(input_path, output_dir, dpi=dpi, enhance=enhance)

@mcp.tool()
def page_classify(input_path: str) -> dict:
    """Conservatively classify a raster page as score, non-score, or uncertain."""
    try:
        return classify_page(input_path)
    except (ImportError, OSError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def omr_status() -> dict:
    """Report whether a local Audiveris OMR engine is available."""
    return OMRAdapter().status()

@mcp.tool()
def omr_run(input_path: str, output_dir: str, executable: str = "", scale: int = 2) -> dict:
    """Run the complete inspect -> prepare -> OMR -> Score IR pipeline."""
    return run_omr(input_path, output_dir, executable, scale)

@mcp.tool()
def musicxml_import(input_path: str, output_score_path: str = "") -> dict:
    """Import OMR-produced MusicXML into Yuezheng's canonical Score IR."""
    try:
        score = parse_musicxml(input_path)
        destination = output_score_path or str(Path(input_path).with_suffix(".score.json"))
        save_score(score, destination)
        report = validate_score(score)
        return {"status": "pass" if report["status"] == "pass" else "needs_review", "output_path": str(Path(destination).resolve()), "parts": len(score.parts), "validation": report}
    except (OSError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}

@mcp.tool()
def review_create(score_path: str, manifest_path: str = "", output_path: str = "") -> dict:
    """Create source-linked measure review tasks for an Agent."""
    return create_review_packet(score_path, manifest_path, output_path)

@mcp.tool()
def review_apply(score_path: str, decisions_path: str, output_path: str = "") -> dict:
    """Apply Agent review decisions and keep rejected tasks in the report."""
    return apply_review(score_path, decisions_path, output_path)

@mcp.tool()
def score_finalize(score_path: str, output_dir: str, executable: str = "", allow_issues: bool = True) -> dict:
    """Deliver MSCZ only; keep compilation and structural audit files internal."""
    return finalize_score(score_path, output_dir, executable, allow_issues)

@mcp.tool()
def score_transcribe(input_path: str, output_dir: str, decisions_path: str = "", audiveris: str = "", musescore: str = "", dpi: int = 450, mode: str = "agent") -> dict:
    """Prepare source images for the calling Agent. OMR requires explicit mode='omr'."""
    if mode == "agent":
        return prepare_agent_job(input_path, output_dir, dpi)
    if mode == "omr":
        return transcribe_score(input_path, output_dir, decisions_path, audiveris, musescore, dpi)
    return {"status": "error", "error": "mode must be agent or omr"}

@mcp.tool()
def musescore_build_score(specification: dict, steps: list, output_path: str, executable: str = "") -> dict:
    """Create and precisely edit MSCZ using MuseScore's official extension host. No computer use or running GUI/plugin required. Agent must supply recognized music; this tool does not recognize it."""
    from yuezheng.musescore.build import build_agent_score
    return build_agent_score(specification, steps, output_path, executable)

@mcp.tool()
def musescore_apply_plan(plan_path: str, input_path: str, output_path: str = "", executable: str = "") -> dict:
    """Apply an exact-target notation plan without computer use. Publish MSCZ only when every MuseScore command succeeds; failed batches preserve input and existing output."""
    from yuezheng.musescore.extension import execute_extension_plan_file
    return execute_extension_plan_file(plan_path, input_path, output_path, executable)

@mcp.tool()
def musescore_execute_plan(input_path: str, url: str = "") -> dict:
    """Execute ordered Agent editor commands; return completed IDs on partial failure."""
    return execute_plan_file(input_path, url)

if __name__ == "__main__": mcp.run()
