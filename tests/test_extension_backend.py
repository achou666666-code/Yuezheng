import json
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from scorebridge.musescore import extension

TARGET = {'targetId':'sb-test', 'scoreName':'score', 'title':'Fixture',
          'numMeasures':1, 'numStaves':1}
PLAN = {'target':TARGET, 'steps':[{'id':'note', 'action':'addChord',
                                 'params':{'staff':0,'voice':0,'startTick':0,
                                           'duration':{'numerator':1,'denominator':4},'pitches':[60]}}]}


def write_score(path, receipt=None):
    root = ET.Element('museScore')
    score = ET.SubElement(root,'Score')
    for key,value in [('scorebridgeTargetId','sb-test'),('workTitle','Fixture')]:
        ET.SubElement(score,'metaTag',name=key).text=value
    if receipt is not None:
        ET.SubElement(score,'metaTag',name=extension.RECEIPT_TAG).text=json.dumps(receipt)
    ET.SubElement(ET.SubElement(score,'Staff',id='1'),'Measure')
    with ZipFile(path,'w') as z:
        z.writestr('score.mscx',ET.tostring(root))


class Adapter:
    timeout=1
    def resolve(self):return Path('/fake/mscore')
    _valid_output=staticmethod(extension.MuseScoreAdapter._valid_output)


def mock_converter(monkeypatch,tmp_path,status='executed',receipt_valid=True):
    monkeypatch.setenv('SCOREBRIDGE_EXTENSION_DIR',str(tmp_path/'extensions'))
    calls=[]
    def convert(args,**kw):
        calls.append(args)
        script=next((tmp_path/'extensions').glob('*/main.js')).read_text()
        run_id=re.search(r'runId: "([^"]+)"',script).group(1)
        digest=re.search(r'planHash: "([^"]+)"',script).group(1)
        receipt={'runId':run_id if receipt_valid else 'stale', 'planHash':digest,
                 'target':TARGET, 'status':status, 'completed':[{'id':'note','response':{'success':True}}]}
        if status!='executed':receipt.update(failed_step='next',error='rejected')
        write_score(args[args.index('-o')+1],receipt)
        return subprocess.CompletedProcess(args,0,'','')
    monkeypatch.setattr(extension.subprocess,'run',convert)
    return calls


def test_success_has_matching_native_receipt_and_uses_no_ui(monkeypatch,tmp_path):
    source=tmp_path/'score.mscz';write_score(source)
    output=tmp_path/'out.mscz'
    calls=mock_converter(monkeypatch,tmp_path)
    report=extension.execute_extension_plan(PLAN,str(source),str(output),Adapter())
    assert report['status']=='executed' and report['published']
    assert report['computer_use'] is False
    assert Path(calls[0][0]).name == 'mscore'
    assert calls[0][1] == '--extension'
    assert output.exists()
    assert list((tmp_path/'extensions').iterdir())==[]


def test_failed_private_batch_preserves_source_and_existing_destination(monkeypatch,tmp_path):
    source=tmp_path/'score.mscz';write_score(source)
    previous=source.read_bytes()
    output=tmp_path/'out.mscz';output.write_bytes(b'old output')
    mock_converter(monkeypatch,tmp_path,status='incomplete')
    result=extension.execute_extension_plan(PLAN,str(source),str(output),Adapter())
    assert result['status']=='incomplete' and not result['published']
    assert result['completed']==[]
    assert result['completed_in_private_copy'][0]['id']=='note'
    assert source.read_bytes()==previous and output.read_bytes()==b'old output'


def test_stale_receipt_is_never_published(monkeypatch,tmp_path):
    source=tmp_path/'score.mscz';write_score(source)
    output=tmp_path/'out.mscz'
    mock_converter(monkeypatch,tmp_path,receipt_valid=False)
    result=extension.execute_extension_plan(PLAN,str(source),str(output),Adapter())
    assert result['status']=='error' and not output.exists()


def test_wrong_target_runs_no_process(monkeypatch,tmp_path):
    source=tmp_path/'different.mscz';write_score(source)
    monkeypatch.setattr(extension.subprocess,'run',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('process started')))
    assert extension.execute_extension_plan(PLAN,str(source),adapter=Adapter())['status']=='wrong_target'


def test_plan_rejects_dialog_commands_duplicates_and_nonfinite_values():
    import pytest
    for steps in [[{'id':'open','action':'openScore'}],
                  [{'id':'n','action':'save'},{'id':'n','action':'save'}],
                  [{'id':'n','action':'setTempo','params':{'bpm':float('nan')}}]]:
        with pytest.raises(ValueError):extension.validate_plan({'target':TARGET,'steps':steps})


def test_command_assets_are_synchronized_and_javascript_parses():
    import shutil
    import pytest
    qml=(Path(__file__).parents[1]/'plugins/musescore-mcp-websocket.qml').read_text()
    functions='\n'.join(re.findall(r'    function \w+\(.*?\n    }',qml,re.S))
    assert functions in extension.command_library()
    node=shutil.which('node')
    if not node:pytest.skip('Node unavailable')
    subprocess.run([node,'--check',str(Path(extension.__file__).with_name('commands.js'))],check=True,capture_output=True)


def test_embedding_never_interprets_plan_strings():
    plan={'target':TARGET,'steps':[{'id':'text','action':'addTechniqueText','params':{'text':'DIGEST RUN_ID PAYLOAD ` ${process.exit()} </script>'}}]}
    script=extension.extension_script(plan,'run','digest')
    assert '"text": "DIGEST RUN_ID PAYLOAD ` ${process.exit()} </script>"' in script
