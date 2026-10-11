"""Environment diagnostics for reproducible ScoreBridge installs."""
from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path


def _check(name: str, ok: bool, detail: str, required: bool = True) -> dict:
    return {"name": name, "status": "pass" if ok else ("missing" if required else "optional"), "detail": detail}


def diagnose() -> dict:
    """Return machine-readable checks without changing the user's system."""
    checks = [
        _check("python", True, f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}"),
        _check("Pillow", importlib.util.find_spec("PIL") is not None, "required for raster preparation"),
        _check("PyMuPDF", importlib.util.find_spec("fitz") is not None, "required for PDF rendering"),
    ]
    audiveris = os.environ.get("AUDIVERIS_BIN") or shutil.which("audiveris") or "/Applications/Audiveris.app/Contents/MacOS/Audiveris"
    musescore = os.environ.get("MUSESCORE_BIN") or shutil.which("mscore") or shutil.which("MuseScore") or "/Applications/MuseScore 4.app/Contents/MacOS/mscore"
    checks.append(_check("audiveris", Path(audiveris).exists(), str(audiveris), required=False))
    checks.append(_check("websockets", importlib.util.find_spec("websockets") is not None,
                         "optional live editing; unattended extension backend does not require WebSocket", required=False))
    checks.append(_check("musescore", Path(musescore).exists(), str(musescore)))
    checks.append(_check("mcp", importlib.util.find_spec("mcp") is not None, "install with pip install -e '.[mcp]'", required=False))
    required = [c for c in checks if c["status"] == "missing"]
    return {"status": "pass" if not required else "needs_setup", "checks": checks, "missing": [c["name"] for c in required]}
