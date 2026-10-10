import json
from pathlib import Path

import pytest

from scorebridge.sibelius.adapter import (
    SibeliusConnect,
    SibeliusError,
    create_sibelius_score,
    install_sibelius_plugin,
)


class FakeSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def send(self, value):
        self.sent.append(json.loads(value))

    def recv(self, timeout=None):
        return json.dumps(self.responses.pop(0))


def test_official_handshake_and_plugin_invocation():
    socket = FakeSocket([
        {"sessionToken": "token"},
        {"message": "invokePluginResponse", "result": True,
         "return_value": {"status": "saved", "staff_count": 3}},
    ])
    client = SibeliusConnect(connector=lambda url: socket)
    result = client.invoke_plugin("ImportAndSave", ["in.musicxml", "out.sib"])
    assert result["staff_count"] == 3
    assert socket.sent[0] == {
        "message": "connect", "clientName": "ScoreBridge",
        "handshakeVersion": "1.0", "plugins": ["ScoreBridge"],
    }
    assert socket.sent[1]["message"] == "invokePlugin"
    assert socket.sent[1]["method"] == "ImportAndSave"


def test_rejected_handshake_is_not_reported_as_success():
    socket = FakeSocket([{"message": "error", "error": "denied"}])
    with pytest.raises(SibeliusError, match="rejected"):
        SibeliusConnect(connector=lambda url: socket).invoke_plugin("InspectActive")


def test_plugin_install_uses_sibelius_encoding(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOREBRIDGE_SIBELIUS_PLUGIN_DIR", str(tmp_path))
    first = install_sibelius_plugin()
    second = install_sibelius_plugin()
    data = Path(first["path"]).read_bytes()
    assert data.startswith(b"\xff\xfe")
    text = data[2:].decode("utf-16-le")
    assert "ImportAndSave" in text and "Sibelius.Open" in text
    assert first["changed"] is True
    assert second["changed"] is False


def test_native_score_is_published_only_after_file_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOREBRIDGE_SIBELIUS_PLUGIN_DIR", str(tmp_path / "plugins"))
    source = tmp_path / "source.musicxml"
    source.write_text("<score-partwise/>", encoding="utf-8")

    class FakeClient:
        def invoke_plugin(self, method, args):
            assert method == "ImportAndSave"
            Path(args[1]).write_bytes(b"SIBELIUS-NATIVE")
            return {"status": "saved", "staff_count": 2, "bar_count": 5}

    output = tmp_path / "final.sib"
    result = create_sibelius_score(source, output, client=FakeClient())
    assert result["status"] == "delivered"
    assert output.read_bytes() == b"SIBELIUS-NATIVE"
    assert result["staff_count"] == 2 and result["bar_count"] == 5
    assert not (tmp_path / "final.scorebridge-partial.sib").exists()


def test_missing_native_output_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOREBRIDGE_SIBELIUS_PLUGIN_DIR", str(tmp_path / "plugins"))
    source = tmp_path / "source.musicxml"
    source.write_text("<score-partwise/>", encoding="utf-8")

    class FalseSuccess:
        def invoke_plugin(self, method, args):
            return {"status": "saved"}

    with pytest.raises(SibeliusError, match="did not create"):
        create_sibelius_score(source, tmp_path / "final.sib", client=FalseSuccess())
