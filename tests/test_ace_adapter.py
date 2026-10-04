from pathlib import Path
import json
import os
import pytest
from scorebridge.ace.adapter import ACEStudioAdapter, ACEError, select_source, create_ace_project


def test_structured_host_error_never_becomes_success(monkeypatch):
    class Response:
        returncode = 0
        stdout = '{"error":{"code":"STALE_WRITE","message":"changed target"}}'
        stderr = ''
    monkeypatch.setattr('scorebridge.ace.adapter.subprocess.run', lambda *a, **k: Response())
    with pytest.raises(ACEError, match='changed target'):
        ACEStudioAdapter('cli').call('project', 'save')


def test_program_identity_selects_real_source_not_a_label():
    catalog = [{'ref':'instrument:1','kind':'instrument','name':'Violin - Test'},
               {'ref':'instrument:2','kind':'instrument','name':'Clarinet - Test'},
               {'ref':'plugin:kit','kind':'external-instrument','name':'DLSMusicDevice','formats':['au']}]
    assert select_source({'id':'c','gm_program':71},catalog,{})['ref'] == 'instrument:2'
    assert select_source({'id':'d','is_drum':True},catalog,{})['ref'] == 'plugin:kit'
    with pytest.raises(ACEError):
        select_source({'id':'f','gm_program':73},catalog,{})


def test_parallel_session_refuses_before_touching_project(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr('scorebridge.ace.adapter.tempfile.gettempdir', lambda: str(tmp_path))
    name = hashlib.sha256(b'cli').hexdigest()[:16]
    owner = os.getuid() if hasattr(os, 'getuid') else 0
    lock = tmp_path / f'scorebridge-ace-{owner}-{name}.lock'
    lock.write_text(str(os.getpid()))
    monkeypatch.setattr(ACEStudioAdapter, 'call', lambda *a, **k: pytest.fail('Unexpected host mutation'))
    assert create_ace_project({},'test.mid','test.acep','cli')['status'] == 'busy'
    assert lock.exists()
