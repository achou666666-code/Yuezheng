"""Native Sibelius delivery through the official Sibelius Connect protocol."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from importlib.resources import files


DEFAULT_URL = "ws://127.0.0.1:1898"
PLUGIN_NAME = "ScoreBridge"


class SibeliusError(RuntimeError):
    pass


def _plugin_root() -> Path:
    override = os.environ.get("SCOREBRIDGE_SIBELIUS_PLUGIN_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Avid/Sibelius/Plugins/ScoreBridge"
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        return base / "Avid/Sibelius/Plugins/ScoreBridge"
    return Path.home() / ".local/share/Avid/Sibelius/Plugins/ScoreBridge"


def install_sibelius_plugin(destination: str = "") -> dict:
    """Install the bundled source as Sibelius' UTF-16LE .plg format."""
    root = Path(destination).expanduser().resolve() if destination else _plugin_root()
    target = root / f"{PLUGIN_NAME}.plg"
    source = files("scorebridge.sibelius").joinpath("ScoreBridge.plg.in").read_text(encoding="utf-8")
    payload = b"\xff\xfe" + source.replace("\n", "\r\n").encode("utf-16-le")
    root.mkdir(parents=True, exist_ok=True)
    changed = not target.exists() or target.read_bytes() != payload
    if changed:
        temporary = target.with_suffix(".plg.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    return {
        "status": "installed",
        "plugin": PLUGIN_NAME,
        "path": str(target),
        "changed": changed,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _host_port(url: str) -> tuple[str, int]:
    prefix = "ws://"
    if not url.startswith(prefix):
        raise ValueError("Sibelius Connect URL must use ws:// on localhost")
    authority = url[len(prefix):].split("/", 1)[0]
    host, separator, port = authority.rpartition(":")
    if not separator:
        host, port = authority, "80"
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Sibelius Connect only accepts a localhost URL")
    return host, int(port)


def sibelius_status(url: str = "") -> dict:
    endpoint = url or os.environ.get("SCOREBRIDGE_SIBELIUS_URL", DEFAULT_URL)
    plugin = _plugin_root() / f"{PLUGIN_NAME}.plg"
    try:
        host, port = _host_port(endpoint)
        with socket.create_connection((host, port), timeout=.4):
            listening = True
    except (OSError, ValueError):
        listening = False
    return {
        "status": "available" if listening else "unavailable",
        "url": endpoint,
        "listening": listening,
        "plugin_installed": plugin.is_file(),
        "plugin_path": str(plugin),
    }


class SibeliusConnect:
    """One official localhost WebSocket session."""

    def __init__(self, url: str = "", timeout: float = 30, connector=None):
        self.url = url or os.environ.get("SCOREBRIDGE_SIBELIUS_URL", DEFAULT_URL)
        _host_port(self.url)
        self.timeout = timeout
        self._connector = connector

    def _connect(self):
        if self._connector:
            return self._connector(self.url)
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise SibeliusError("Install ScoreBridge with the websocket extra") from exc
        try:
            return connect(self.url, open_timeout=self.timeout, close_timeout=2)
        except (OSError, TimeoutError) as exc:
            raise SibeliusError(f"Cannot connect to Sibelius Connect at {self.url}: {exc}") from exc

    def invoke_plugin(self, method: str, args: list | None = None) -> dict:
        handshake = {
            "message": "connect",
            "clientName": "ScoreBridge",
            "handshakeVersion": "1.0",
            "plugins": [PLUGIN_NAME],
        }
        request = {"message": "invokePlugin", "name": PLUGIN_NAME, "method": method}
        if args is not None:
            request["args"] = args
        try:
            with self._connect() as ws:
                ws.send(json.dumps(handshake))
                hello = json.loads(ws.recv(timeout=self.timeout))
                if not hello.get("sessionToken"):
                    raise SibeliusError(f"Sibelius rejected the handshake: {hello}")
                ws.send(json.dumps(request))
                while True:
                    response = json.loads(ws.recv(timeout=self.timeout))
                    if response.get("message") == "invokePluginResponse":
                        break
        except SibeliusError:
            raise
        except (OSError, TimeoutError, ValueError, TypeError) as exc:
            raise SibeliusError(f"Sibelius Connect request failed: {exc}") from exc
        if response.get("result") is not True:
            raise SibeliusError(f"Sibelius could not invoke {PLUGIN_NAME}.{method}: {response}")
        value = response.get("return_value", response.get("returnValue"))
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            try:
                decoded = json.loads(value)
                return decoded if isinstance(decoded, dict) else {"return_value": decoded}
            except json.JSONDecodeError:
                return {"return_value": value}
        return {"status": "ok"}


def create_sibelius_score(input_path: str, output_path: str, url: str = "", client=None) -> dict:
    """Open MusicXML in Sibelius, save an atomic native .sib, and verify it exists."""
    source = Path(input_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {".musicxml", ".xml", ".mxl"}:
        raise SibeliusError("Sibelius input must be an existing MusicXML or MXL file")
    if destination.suffix.lower() != ".sib":
        raise SibeliusError("Sibelius output must end in .sib")
    destination.parent.mkdir(parents=True, exist_ok=True)
    install = install_sibelius_plugin()
    bridge = client or SibeliusConnect(url)
    temporary = destination.with_name(destination.stem + ".scorebridge-partial.sib")
    if temporary.exists():
        temporary.unlink()
    result = bridge.invoke_plugin("ImportAndSave", [str(source), str(temporary)])
    if result.get("status") != "saved":
        raise SibeliusError(result.get("error", f"Sibelius did not confirm a saved score: {result}"))
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise SibeliusError("Sibelius reported success but did not create a native score")
    os.replace(temporary, destination)
    return {
        "status": "delivered",
        "output_path": str(destination),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "size": destination.stat().st_size,
        "staff_count": result.get("staff_count"),
        "bar_count": result.get("bar_count"),
        "plugin": install,
        "transport": "Sibelius Connect",
    }
