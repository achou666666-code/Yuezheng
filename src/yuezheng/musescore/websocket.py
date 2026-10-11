"""Optional bridge to MuseScore QML/WebSocket MCP plugins."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional


class MuseScoreWebSocketError(RuntimeError):
    pass


class MuseScoreWebSocketBackend:
    name = "websocket"

    def __init__(self, url: Optional[str] = None, timeout: float = 8.0, protocol: str = "auto"):
        self.url = url or os.environ.get("SCOREBRIDGE_MUSESCORE_WS", "ws://localhost:8765")
        self.timeout = timeout
        self.protocol = os.environ.get("SCOREBRIDGE_MUSESCORE_PROTOCOL", protocol)
        if self.protocol not in {"auto", "action", "command"}:
            raise ValueError("protocol must be auto, action, or command")

    @staticmethod
    def _check_response(result):
        if not isinstance(result, dict):
            raise MuseScoreWebSocketError("Plugin returned a non-object response")
        node = result
        while isinstance(node, dict):
            if node.get("error") or node.get("status") == "error" or node.get("success") is False or node.get("valid") is False:
                raise MuseScoreWebSocketError(f"Plugin rejected command: {node}")
            node = node.get("result")
        return result

    async def _exchange(self, socket, key, action, params):
        await socket.send(json.dumps({key: action, "params": params}))
        raw = await asyncio.wait_for(socket.recv(), timeout=self.timeout)
        return self._check_response(json.loads(raw))

    async def _send_async(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import websockets
        except ImportError as exc:
            raise MuseScoreWebSocketError("Install with: pip install -e '.[websocket]'") from exc
        try:
            async with websockets.connect(self.url, open_timeout=self.timeout, close_timeout=self.timeout) as socket:
                key = self.protocol
                if key == "auto":
                    # Negotiate only with read-only ping. Never retry a write:
                    # a lost acknowledgement doesn't mean the edit wasn't applied.
                    errors = []
                    for candidate in ("action", "command"):
                        try:
                            pong = await self._exchange(socket, candidate, "ping", {})
                            if pong.get("result") != "pong":
                                raise MuseScoreWebSocketError(f"Unexpected ping response: {pong}")
                            key = candidate
                            break
                        except MuseScoreWebSocketError as exc:
                            errors.append(str(exc))
                    else:
                        raise MuseScoreWebSocketError("No compatible protocol: " + "; ".join(errors))
                result = await self._exchange(socket, key, action, params)
                self.negotiated_protocol = key
                return result
        except MuseScoreWebSocketError:
            raise
        except Exception as exc:
            raise MuseScoreWebSocketError(f"MuseScore WebSocket unavailable at {self.url}: {exc}") from exc

    def command(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return asyncio.run(self._send_async(action, params or {}))

    def status(self) -> dict:
        try:
            result = self.command("ping")
            if result.get("result") != "pong":
                raise MuseScoreWebSocketError(f"Unexpected ping response: {result}")
            capabilities = {"ping": True}
            try:
                capability_response = self.command("getCapabilities")
                capability_result = capability_response.get("result", {})
                commands = capability_result.get("commands", [])
                reserved_commands = capability_result.get("reserved_commands", [])
                capabilities.update({
                    "getCapabilities": True,
                    "pluginVersion": capability_result.get("pluginVersion"),
                    "commands": commands,
                    "reserved_commands": reserved_commands,
                    "getScore": "getScore" in commands,
                    "save": "save" in commands,
                })
            except MuseScoreWebSocketError as exc:
                capabilities.update({
                    "getCapabilities": False,
                    "getScore": None,
                    "save": None,
                    "error": str(exc),
                    "hint": "Restart MuseScore and enable the bundled ScoreBridge plugin.",
                })
            return {"available": True, "backend": self.name, "url": self.url,
                    "protocol": self.negotiated_protocol, "capabilities": capabilities,
                    "response": result}
        except MuseScoreWebSocketError as exc:
            return {"available": False, "backend": self.name, "url": self.url, "error": str(exc),
                    "hint": "Enable a compatible MuseScore QML/WebSocket plugin and keep MuseScore open."}
