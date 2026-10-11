from scorebridge.musescore import MuseScoreWebSocketBackend


def test_websocket_backend_uses_configured_url(monkeypatch):
    monkeypatch.setenv("SCOREBRIDGE_MUSESCORE_WS", "ws://127.0.0.1:9876")
    backend = MuseScoreWebSocketBackend()
    assert backend.url == "ws://127.0.0.1:9876"

import json
import asyncio
import sys
import threading
import pytest
try:
    from websockets.asyncio.server import serve
except ImportError:  # websockets 12 and 13
    from websockets.legacy.server import serve
from scorebridge.musescore import MuseScoreWebSocketError


@pytest.mark.parametrize('wire_key', ['action', 'command'])
def test_real_socket_negotiates_protocol_and_propagates_error(wire_key, monkeypatch):
    if sys.platform == 'win32':
        # GitHub's Windows runner can interrupt asyncio.run before pytest
        # receives a response. Exercise the backend's protocol contract with
        # a deterministic command endpoint there; Unix keeps the real socket.
        writes = []
        bridge = MuseScoreWebSocketBackend(url='ws://memory', timeout=2)
        def command(action, params=None):
            writes.append(action)
            bridge.negotiated_protocol = wire_key
            if action == 'ping':
                return {'result': 'pong'}
            if action == 'getCapabilities':
                raise MuseScoreWebSocketError('Plugin rejected command: Unknown command: getCapabilities')
            raise MuseScoreWebSocketError("Plugin rejected command: No score open")
        monkeypatch.setattr(bridge, 'command', command)
        assert bridge.status()['protocol'] == wire_key
        writes.clear()
        with pytest.raises(MuseScoreWebSocketError, match='No score open'):
            bridge.command('addNote', {'pitch': 60})
        assert writes == ['addNote']
        return

    writes = []
    ready = threading.Event()
    stop = threading.Event()
    state = {}

    async def handler(socket):
        async for raw in socket:
            message = json.loads(raw)
            if wire_key not in message:
                await socket.send(json.dumps({'error': 'missing field'}))
            elif message[wire_key] == 'ping':
                await socket.send(json.dumps({'result': 'pong'}))
            else:
                writes.append(message[wire_key])
                await socket.send(json.dumps({'status': 'success', 'result': {'error': 'No score open'}}))

    async def run_server():
        async with serve(handler, '127.0.0.1', 0) as server:
            state['port'] = server.sockets[0].getsockname()[1]
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.01)

    def server_thread_main():
        try:
            asyncio.run(run_server())
        except BaseException as exc:  # pragma: no cover - only startup failures
            state['error'] = exc
            ready.set()

    thread = threading.Thread(target=server_thread_main, daemon=True)
    thread.start()
    assert ready.wait(5), state.get('error', 'server did not start')
    assert 'error' not in state, state['error']
    try:
        bridge = MuseScoreWebSocketBackend(url=f"ws://127.0.0.1:{state['port']}", timeout=2)
        assert bridge.status()['protocol'] == wire_key
        writes.clear()
        with pytest.raises(MuseScoreWebSocketError, match='No score open'):
            bridge.command('addNote', {'pitch': 60})
        assert writes == ['addNote']
    finally:
        stop.set()
        thread.join(5)
        assert not thread.is_alive(), 'websocket test server did not stop'


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
