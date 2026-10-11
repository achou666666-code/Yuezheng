"""Shared playback-instrument audit for CLI and MCP entry points."""
from .instruments import INSTRUMENTS, instrument_spec
from .instrument_names import resolve_instrument_name


def audit_instruments(score) -> dict:
    parts = []
    unresolved = []
    for part in score.parts:
        spec = instrument_spec(part.instrument_id)
        item = {
            "id": part.id,
            "name": part.name,
            "instrument_id": part.instrument_id,
            "mapped": bool(spec),
            "instrument_sound": spec.get("instrument_sound"),
            "midi_program": spec.get("midi_program"),
        }
        parts.append(item)
        if not spec and part.instrument_id not in unresolved:
            unresolved.append(part.instrument_id)
    return {
        "status": "pass" if not unresolved else "needs_review",
        "parts": parts,
        "unresolved_instrument_ids": unresolved,
        "piano_fallback_detected": any(
            resolve_instrument_name(item["instrument_id"], INSTRUMENTS) != "keyboard.piano"
            and item["instrument_sound"] == "keyboard.piano"
            for item in parts
        ),
    }
