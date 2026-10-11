from scorebridge.musescore import MuseScoreWebSocketBackend


def test_websocket_backend_uses_configured_url(monkeypatch):
    monkeypatch.setenv("SCOREBRIDGE_MUSESCORE_WS", "ws://127.0.0.1:9876")
    backend = MuseScoreWebSocketBackend()
    assert backend.url == "ws://127.0.0.1:9876"

import json
import sys
import threading
import pytest
from websockets.sync.server import serve
from scorebridge.musescore import MuseScoreWebSocketError


@pytest.mark.parametrize('wire_key', ['action', 'command'])
def test_real_socket_negotiates_protocol_and_propagates_error(wire_key):
    writes = []
    def handler(socket):
        for raw in socket:
            message = json.loads(raw)
            if wire_key not in message:
                socket.send(json.dumps({'error': 'missing field'}))
            elif message[wire_key] == 'ping':
                socket.send(json.dumps({'result': 'pong'}))
            else:
                writes.append(message[wire_key])
                socket.send(json.dumps({'status': 'success', 'result': {'error': 'No score open'}}))
    server = serve(handler, '127.0.0.1', 0)
    try:
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        bridge = MuseScoreWebSocketBackend(url=f'ws://127.0.0.1:{server.socket.getsockname()[1]}', timeout=2)
        assert bridge.status()['protocol'] == wire_key
        writes.clear()
        with pytest.raises(MuseScoreWebSocketError, match='No score open'):
            bridge.command('addNote', {'pitch': 60})
        assert writes == ['addNote']
    finally:
        if sys.platform == 'win32':
            # websockets' sync Server.shutdown waits for a selector that
            # closing a listening socket doesn't wake on Windows.
            server.socket.close()
            thread.join(0.1)
        else:
            server.shutdown()
            thread.join(3)


@pytest.mark.parametrize('reply', [{'error': 'bad'}, {'status': 'error', 'message': 'bad'}, {'result': {'valid': False}}, {'result': {'success': False}}])
def test_plugin_failures_are_not_success(reply):
    with pytest.raises(MuseScoreWebSocketError):
        MuseScoreWebSocketBackend._check_response(reply)


def test_status_reports_missing_command_without_marking_connection_down(monkeypatch):
    backend = MuseScoreWebSocketBackend()
    calls = []
    def command(action, params=None):
        calls.append(action)
        if action == "ping":
            backend.negotiated_protocol = "action"
            return {"result": "pong"}
        raise MuseScoreWebSocketError("Plugin rejected command: Unknown command: getCapabilities")
    monkeypatch.setattr(backend, "command", command)
    report = backend.status()
    assert report["available"] is True
    assert report["capabilities"]["ping"] is True
    assert report["capabilities"]["getCapabilities"] is False
    assert report["capabilities"]["save"] is None
    assert calls == ["ping", "getCapabilities"]


def test_status_reads_capabilities_without_executing_save(monkeypatch):
    backend = MuseScoreWebSocketBackend()
    calls = []
    def command(action, params=None):
        calls.append(action)
        backend.negotiated_protocol = "action"
        if action == "ping":
            return {"result": "pong"}
        return {"result": {"pluginVersion": "2.0", "commands": ["getScore", "save"], "reserved_commands": ["createScore"]}}
    monkeypatch.setattr(backend, "command", command)
    report = backend.status()
    assert report["capabilities"]["getScore"] is True
    assert report["capabilities"]["save"] is True
    assert report["capabilities"]["reserved_commands"] == ["createScore"]
    assert calls == ["ping", "getCapabilities"]


def test_status_preserves_reserved_dynamic_command(monkeypatch):
    backend = MuseScoreWebSocketBackend()
    def command(action, params=None):
        backend.negotiated_protocol = "action"
        if action == "ping":
            return {"result": "pong"}
        return {"result": {"pluginVersion": "2.0", "commands": ["getScore"],
                               "reserved_commands": ["addDynamic"]}}
    monkeypatch.setattr(backend, "command", command)
    report = backend.status()
    assert report["capabilities"]["reserved_commands"] == ["addDynamic"]
