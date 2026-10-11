"""Execute Agent plans in MuseScore's official extension host, without GUI automation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

from .adapter import MuseScoreAdapter, MuseScoreError
from .connect import identity_mismatches


RECEIPT_TAG = 'scorebridgeExecutionReceipt'
# No dialogs, lifecycle actions, undo, nested unguarded batches, or writes outside
# the explicitly named score. Save is handled by the converter itself.
PLAN_ACTIONS = frozenset({
    'getScore', 'getScoreIdentity', 'getCapabilities', 'getDrumset',
    'selectCustomRange', 'selectCurrentMeasure', 'getCursorInfo', 'goToMeasure',
    'addChord', 'addRest', 'addTie', 'addTuplet', 'addGraceNote',
    'addGraceNotes', 'addGraceSlur', 'addTremolo', 'addArpeggio', 'addFermata', 'addOrnament', 'addPercussionNote',
    'setNoteHead', 'setAccidental', 'addLyrics', 'addDynamic', 'addArticulation', 'addSlur', 'addTechniqueText',
    'setKeySignature', 'setTimeSignature', 'setTempo', 'setPartInstrument',
    'setPageLayout', 'setLayoutBreak', 'setStaffVisible', 'getMidiChannels',
    'getPageLayout', 'save',
})


def extension_directory():
    explicit = os.environ.get('SCOREBRIDGE_EXTENSION_DIR')
    if explicit:
        return Path(explicit)
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/MuseScore/MuseScore4/extensions'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'MuseScore/MuseScore4/extensions'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'MuseScore/MuseScore4/extensions'


def score_xml(path):
    with ZipFile(path) as archive:
        member = next(n for n in archive.namelist() if n.endswith('.mscx'))
        return ET.fromstring(archive.read(member))


def file_identity(path):
    root = score_xml(path)
    score = root.find('Score')
    tags = {n.get('name'): n.text or '' for n in score.findall('metaTag')}
    staves = score.findall('Staff')
    return {'targetId': tags.get('scorebridgeTargetId', ''),
            'scoreName': Path(path).stem, 'title': tags.get('workTitle', ''),
            'numMeasures': len(staves[0].findall('Measure')) if staves else 0,
            'numStaves': len(staves)}


def validate_plan(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get('target'), dict):
        raise ValueError('plan.target must contain the exact creation target')
    errors = identity_mismatches(plan['target'], {})
    if 'target' in errors:
        raise ValueError(errors['target'])
    steps = plan.get('steps')
    if not isinstance(steps, list) or not steps:
        raise ValueError('plan.steps must be a nonempty list')
    seen = set()
    for step in steps:
        if (not isinstance(step, dict) or not isinstance(step.get('id'), str) or not step['id']
                or step['id'] in seen or step.get('action') not in PLAN_ACTIONS
                or not isinstance(step.get('params', {}), dict)):
            raise ValueError('Each step needs a unique id, supported action and object params')
        seen.add(step['id'])
    # Also rejects NaN/Infinity before embedding data into JavaScript.
    json.dumps(plan, allow_nan=False)


def command_library():
    return Path(__file__).with_name('commands.js').read_text(encoding='utf-8')


def extension_script(plan, run_id, digest):
    payload = json.dumps(plan, ensure_ascii=True, allow_nan=False)
    # Only JSON data is embedded; user strings are never interpolated as code.
    return command_library() + '\nfunction main() {\n' + '''
    var plan = PAYLOAD;
    var report = {runId: RUN_ID, planHash: DIGEST, target: plan.target,
                  status: "executed", completed: []};
    var actual = getScoreIdentity();
    var fields = ["targetId","scoreName","title","numMeasures","numStaves"];
    for (var k = 0; k < fields.length; k++) {
        if (actual[fields[k]] !== plan.target[fields[k]]) throw new Error("Wrong score target: " + fields[k]);
    }
    initCursorState();
    for (var i = 0; i < plan.steps.length; i++) {
        var step = plan.steps[i];
        try {
            var result = step.action === "save" ? {success:true, savedBy:"MuseScore converter"} : processCommand(step);
            if (!result || result.error || result.success === false || result.valid === false)
                throw new Error(JSON.stringify(result));
            report.completed.push({id:step.id, response:result});
        } catch (e) {
            report.status = "incomplete";
            report.failed_step = step.id;
            report.error = String(e);
            break;
        }
    }
    curScore.setMetaTag("scorebridgeExecutionReceipt", JSON.stringify(report));
}
'''.replace('RUN_ID', json.dumps(run_id)).replace('DIGEST', json.dumps(digest)).replace('PAYLOAD', payload)


def execute_extension_plan(plan, input_path, output_path='', adapter=None):
    """Apply a complete batch to a private copy; publish MSCZ only on full success.

    A failed batch leaves both the source and any old destination unchanged. The
    caller can correct and replay the plan because no partial output was published.
    """
    source = Path(input_path).resolve()
    destination = Path(output_path or input_path).resolve()
    try:
        validate_plan(plan)
        if not source.is_file() or source.suffix.lower() != '.mscz':
            raise ValueError('input_path must be an existing MSCZ')
        if destination.suffix.lower() != '.mscz':
            raise ValueError('output_path must end in .mscz')
        actual = file_identity(source)
        mismatches = identity_mismatches(plan['target'], actual)
        if mismatches:
            return {'status':'wrong_target', 'completed':[], 'mismatches':mismatches,
                    'error':'Input MSCZ does not match plan.target; no MuseScore command was run'}
        engine = adapter or MuseScoreAdapter()
        executable = engine.resolve()
        if not executable:
            raise MuseScoreError('Install MuseScore Studio 4.6+ with --extension support or set MUSESCORE_BIN')
        digest = hashlib.sha256(json.dumps(plan, sort_keys=True, allow_nan=False).encode()).hexdigest()
        run_id = uuid4().hex
        destination.parent.mkdir(parents=True, exist_ok=True)
        extensions = extension_directory()
        extensions.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='scorebridge-run-', dir=extensions) as installed:
            folder = Path(installed)
            uri = 'musescore://extensions/' + folder.name
            manifest = {'uri':uri, 'type':'macros', 'title':'ScoreBridge plan executor',
                        'apiversion':1, 'actions':[{'path':'main.js'}]}
            (folder/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (folder/'main.js').write_text(extension_script(plan, run_id, digest), encoding='utf-8')
            with tempfile.TemporaryDirectory(prefix='scorebridge-output-', dir=destination.parent) as temp:
                generated = Path(temp)/destination.name
                command = [str(executable), '--extension', uri, '-o', str(generated), str(source)]
                process = subprocess.run(command, capture_output=True, text=True,
                                         timeout=engine.timeout, env=os.environ.copy())
                if not engine._valid_output(generated):
                    raise MuseScoreError('MuseScore extension did not produce an MSCZ; ' + process.stderr[-1500:])
                root = score_xml(generated)
                receipt_text = next((n.text for n in root.iter('metaTag') if n.get('name') == RECEIPT_TAG), None)
                receipt = json.loads(receipt_text or '{}')
                if receipt.get('runId') != run_id or receipt.get('planHash') != digest or receipt.get('target') != plan['target']:
                    raise MuseScoreError('MuseScore output has no matching execution receipt; refusing to publish')
                report = {**receipt, 'backend':'musescore-extension', 'computer_use':False,
                          'source_unchanged_on_failure':True, 'returncode':process.returncode}
                if receipt.get('status') != 'executed':
                    return {**report, 'published':False, 'completed_in_private_copy':report['completed'], 'completed':[]}
                if [s['id'] for s in plan['steps']] != [s['id'] for s in receipt.get('completed', [])]:
                    raise MuseScoreError('MuseScore did not acknowledge every planned step')
                generated.replace(destination)
                return {**report, 'published':True, 'mscz_path':str(destination),
                        'verification':'MuseScore execution receipt and native file integrity; not a source-recognition accuracy score'}
    except (ValueError, OSError, MuseScoreError, subprocess.SubprocessError, KeyError, StopIteration, BadZipFile, ET.ParseError) as exc:
        return {'status':'error', 'error':str(exc), 'published':False, 'completed':[], 'computer_use':False}


def execute_extension_plan_file(plan_path, input_path, output_path='', executable=''):
    try:
        plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return {'status':'error', 'error':str(exc), 'published':False}
    return execute_extension_plan(plan, input_path, output_path,
                                  MuseScoreAdapter(executable=executable or None))
