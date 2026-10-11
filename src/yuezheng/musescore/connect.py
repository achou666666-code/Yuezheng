"""Exact live-score binding. No computer use or UI automation."""
from pathlib import Path

from .adapter import MuseScoreError
from .websocket import MuseScoreWebSocketBackend


def connect_editor(pid=None, timeout=12) -> dict:
    """Check a live connection without screen control or Accessibility automation.

    Use the official extension backend for unattended file-based notation. Live
    WebSocket use requires the user to enable the plugin once in MuseScore.
    """
    state = MuseScoreWebSocketBackend(timeout=2).status()
    if state.get('available'):
        return {'status':'connected', 'activation':'already_running', **state}
    return {'status':'needs_live_plugin', 'editor':state, 'computer_use':False,
            'error':'No live MuseScore plugin is listening',
            'next':'Use musescore_build_score / scorebridge build-score for unattended creation, or enable the plugin once for live editing.'}


def _identity_result(response):
    value = response.get("result", response) if isinstance(response, dict) else {}
    return value if isinstance(value, dict) else {}


def identity_mismatches(expected, actual):
    if not isinstance(expected, dict):
        return {"target":"expected target must be an object"}
    if not isinstance(actual, dict):
        actual = {}
    required = ("targetId", "scoreName", "title", "numMeasures", "numStaves")
    missing = [key for key in required if key not in expected]
    if missing:
        return {"target": "missing expected fields: " + ", ".join(missing)}
    invalid = []
    for key in ("targetId", "scoreName", "title"):
        if not isinstance(expected[key], str) or not expected[key]:
            invalid.append(key)
    for key in ("numMeasures", "numStaves"):
        if not isinstance(expected[key], int) or isinstance(expected[key], bool) or expected[key] < 1:
            invalid.append(key)
    if invalid:
        return {"target": "invalid expected fields: " + ", ".join(invalid)}
    return {key: {"expected": expected[key], "actual": actual.get(key)}
            for key in required if actual.get(key) != expected[key]}


def bind_editor_score(input_path, target, adapter=None, bridge=None, timeout=20) -> dict:
    """Bind an existing live listener only when its exact score identity matches."""
    source = Path(input_path)
    if not source.is_file():
        raise MuseScoreError(f"Input does not exist: {source}")
    socket = bridge or MuseScoreWebSocketBackend(timeout=2)
    state = socket.status()
    if state.get("available"):
        try:
            current = _identity_result(socket.command("getScoreIdentity"))
        except Exception:
            current = {}
        if not identity_mismatches(target, current):
            return {"status": "bound", "input_path": str(source.resolve()),
                    "target": target, "actual": current, "activation": "already_target"}
        return {"status": "wrong_target",
                "error": "The active MuseScore MCP listener belongs to another score; no file was opened and no edit was sent",
                "target": target, "actual": current,
                "mismatches": identity_mismatches(target, current),
                "next": "Stop the current MuseScore MCP listener, then bind this score again."}
    else:
        return {"status":"needs_live_plugin", "computer_use":False,
                "error":"Live plugin is unavailable; use the official extension backend for unattended file edits",
                "target":target}
