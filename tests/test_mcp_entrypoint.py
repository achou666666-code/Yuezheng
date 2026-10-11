import asyncio
import importlib.util
from pathlib import Path
import pytest


def test_server_exposes_agent_default():
    pytest.importorskip('mcp')
    spec = importlib.util.spec_from_file_location('scorebridge_mcp_test', Path(__file__).parents[1] / 'mcp_server/server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tools = {t.name: t for t in asyncio.run(module.mcp.list_tools())}
    assert tools['score_transcribe'].inputSchema['properties']['mode']['default'] == 'agent'
    assert 'musescore_execute_plan' in tools
    assert 'musescore_create_score' in tools
    assert {'music_plan', 'music_deliver', 'ace_status', 'sibelius_status',
            'sibelius_install_plugin', 'sibelius_create_score'} <= tools.keys()
    assert 'musescore_bind_score' in tools
    assert tools['musescore_create_score'].inputSchema['properties']['open_editor']['default'] is False

    assert "musescore_build_score" in tools
    assert "musescore_apply_plan" in tools
    assert "audio_prepare" in tools
    assert "audio_evaluate" in tools
    assert "audio_backends" in tools
    assert "audio_install" in tools
    assert "audio_transcribe" in tools
    assert "audio_separate" in tools
    assert tools['audio_transcribe'].inputSchema['properties']['hint']['default'] == 'auto'
    assert {'yuezheng_doctor', 'scorebridge_doctor'} <= tools.keys()
