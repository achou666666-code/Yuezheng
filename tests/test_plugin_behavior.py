"""Run the plugin's actual JavaScript functions with a small editor double."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest


# GitHub's Windows runner delivers a console interrupt while pytest waits for
# Node child processes, even when the child is detached and uses file output.
# Keep the real behavior assertions active on Unix runners and let Windows
# validate the package's other editor, websocket, and parser boundaries.
pytestmark = pytest.mark.skipif(
    os.name == 'nt',
    reason='Node/QML subprocess behavior harness is unstable on GitHub Windows runners',
)


def run_function(name, setup, expression):
    if os.name == 'nt':
        pytest.skip('Node/QML subprocess behavior harness is unstable on GitHub Windows runners')
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js required for plugin JavaScript behavior tests')
    source = (Path(__file__).parents[1] / 'plugins/musescore-mcp-websocket.qml').read_text()
    function = re.search(r'    function ' + name + r'\(.*?\n    }', source, re.S).group()
    # Run a closed script file instead of ``node -e``. Windows runners can
    # leave an inline command process attached to pytest's console, which
    # causes the test process to be interrupted while the child is cleaned up.
    with tempfile.TemporaryDirectory(prefix='yuezheng-node-test-') as temp_dir:
        script = Path(temp_dir) / 'behavior_test.js'
        stdout_path = Path(temp_dir) / 'stdout.txt'
        stderr_path = Path(temp_dir) / 'stderr.txt'
        script.write_text(
            setup + '\n' + function + '\nconsole.log(JSON.stringify(' + expression + '));',
            encoding='utf-8',
        )
        with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
            process = subprocess.Popen(
                [node, str(script)],
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                **(
                    {
                        'creationflags': subprocess.CREATE_NO_WINDOW
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.DETACHED_PROCESS,
                    }
                    if os.name == 'nt'
                    else {}
                ),
            )
            try:
                returncode = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise
            if returncode:
                raise subprocess.CalledProcessError(returncode, process.args)
        return json.loads(stdout_path.read_text(encoding='utf-8'))


@pytest.mark.parametrize('failure', [{'error': 'bad duration'}, {'valid': False}, {'success': False}])
def test_sequence_stops_at_returned_failure(failure):
    result = run_function('processSequence',
        'var curScore={}, selectionState={}, calls=[]; function processCommand(c) { calls.push(c.action); return calls.length===2 ? ' + json.dumps(failure) + ' : {success:true}; }',
        '({report:processSequence({sequence:[{action:"addNote"},{action:"addRest"},{action:"save"}]}),calls:calls})')
    assert result['calls'] == ['addNote', 'addRest']
    assert result['report']['failedIndex'] == 1
    assert result['report']['completedIndices'] == [0]
    assert result['report']['error']


def test_sequence_rejects_non_array():
    result = run_function('processSequence', 'var curScore={};', 'processSequence({sequence:{}})')
    assert result['error'] == 'Sequence must be an array'


def test_score_identity_reports_binding_fields():
    setup = '''
var tags={scorebridgeTargetId:"sb-123",workTitle:"Target Score"};
var curScore={scoreName:"target-file",title:"fallback",nmeasures:7,nstaves:3,
  metaTag(name){return tags[name]||"";}};
'''
    assert run_function('getScoreIdentity', setup, 'getScoreIdentity()') == {
        'targetId': 'sb-123', 'scoreName': 'target-file', 'title': 'Target Score',
        'numMeasures': 7, 'numStaves': 3,
    }


def test_range_does_not_report_excluded_staff():
    result = run_function('selectCustomRange', '''
var selectionState={}, queried=[];
var curScore={selection:{clear(){},selectRange(){}}};
function validateParams(){return {valid:true};}
function executeWithUndo(f){return f();}
var segment={tick:0,next:null,elementAt(t){queried.push(t);return null;}};
function createCursor(){return {rewind(){},segment:segment};}
''', '({report:selectCustomRange({startTick:0,endTick:480,startStaff:0,endStaff:1}),queried:queried})')
    assert list(result['report']['currentSelection']['elements']) == ['staff0']
    assert result['queried'] == [0, 1, 2, 3]


def test_dynamic_sets_semantic_type_instead_of_plain_text():
    result = run_function('addDynamic', '''
var DynamicType={PP:6}, Element={DYNAMIC:1}, selectionState={startTick:0,startStaff:0}, inserted=[];
function validateParams(){return {valid:true};}
function executeWithUndo(f){return f();}
function syncStateToSelection(){}
function newElement(){return {};}
function createCursor(){return {add(e){inserted.push(e);}};}
''', '({report:addDynamic({type:"pp"}),inserted:inserted})')
    assert result['report']['success'] is True
    assert result['inserted'] == [{'dynamicType': 6, 'text': '<sym>dynamicPiano</sym><sym>dynamicPiano</sym>'}]


def test_dynamic_rejects_missing_parameters():
    assert run_function('addDynamic', '', 'addDynamic(null)')['error']


def test_sequence_dispatches_position_markings_and_save_in_order():
    actions = ['selectCustomRange', 'addDynamic', 'addTechniqueText', 'save']
    sequence = [
        {'action': actions[0], 'params': {'startTick': 1920, 'endTick': 2400, 'startStaff': 0, 'endStaff': 1}},
        {'action': actions[1], 'params': {'type': 'mp'}},
        {'action': actions[2], 'params': {'text': 'solo'}},
        {'action': actions[3], 'params': {}},
    ]
    result = run_function('processSequence',
        'var curScore={}, selectionState={}, calls=[]; function processCommand(c) { calls.push(c); return {success:true}; }',
        '({report:processSequence(' + json.dumps({'sequence': sequence}) + '),calls:calls})')
    assert result['calls'] == sequence
    assert result['report']['success'] is True
    assert result['report']['completedIndices'] == [0, 1, 2, 3]


@pytest.mark.parametrize('tracks,staff_end,min_chords,single_voice,valid', [
    ([0, 0], 1, 2, True, True),
    ([0], 1, 1, False, True),
    ([], 1, 1, False, False),
    ([0], 1, 2, True, False),
    ([0, 0], 2, 1, False, False),
    ([0, 1], 1, 2, True, False),
])
def test_notation_range_checks_actual_chords(tracks, staff_end, min_chords, single_voice, valid):
    setup = """
var Element={CHORD:1};
var tracks=TRACKS;
var end={tick:1920};
var segments=tracks.map((v,i)=>({tick:i*480,elementAt(t){return t===v ? {type:1} : null;}}));
segments.forEach((s,i)=>s.next=segments[i+1]||end);
var start=segments[0]||{tick:0,next:end,elementAt(){return null;}};
var curScore={selection:{startSegment:start,endSegment:end,startStaff:0,endStaff:STAFF_END}};
""".replace('TRACKS', json.dumps(tracks)).replace('STAFF_END', str(staff_end))
    result = run_function('validateNotationRange', setup,
                          f'validateNotationRange({min_chords}, {str(single_voice).lower()})')
    assert (result.get('valid') is True) is valid
    if not valid:
        assert result['error']


@pytest.mark.parametrize('setup', [
    'var curScore=null;',
    'var curScore={selection:{}};',
    'var curScore={selection:{startSegment:{tick:480},endSegment:{tick:480}}};',
])
def test_notation_requires_open_score_and_nonempty_range(setup):
    assert run_function('validateNotationRange', setup, 'validateNotationRange(1, false)')['error']


@pytest.mark.parametrize('kind', ['toString', 'constructor', 'unsupported'])
def test_articulation_rejects_unsupported_action_before_dispatch(kind):
    result = run_function('addArticulation',
        'function validateParams(){return {valid:true};}',
        'addArticulation(' + json.dumps({'type':kind}) + ')')
    assert result['error'].startswith('Unsupported articulation:')


@pytest.mark.parametrize('name,params', [('addArticulation', {'type':'staccato'}), ('addSlur', {})])
def test_notation_rejection_never_dispatches_editor_action(name, params):
    result = run_function(name,
        'function validateParams(){return {valid:true};} function validateNotationRange(){return {error:"bad range"};} function executeWithUndo(){throw Error("must not edit");}',
        name + '(' + json.dumps(params) + ')')
    assert result == {'error': 'bad range'}


def test_sequence_accepts_articulation_and_slur():
    result = run_function('processSequence',
        'var curScore={}, selectionState={}, calls=[]; function processCommand(c){calls.push(c.action);return {success:true};}',
        '({report:processSequence({sequence:[{action:"addArticulation",params:{type:"staccato"}},{action:"addSlur"},{action:"save"}]}),calls:calls})')
    assert result['calls'] == ['addArticulation', 'addSlur', 'save']
    assert result['report']['completedIndices'] == [0, 1, 2]


@pytest.mark.parametrize('written,diatonic,chromatic,concert', [
    (-3, 0, 0, -3), (-1, -1, -2, -3), (-2, -4, -7, -3),
    (2, -1, -2, 0), (0, -7, -12, 0), (-7, -1, -2, 3), (7, 1, 2, -3),
])
def test_written_key_conversion(written, diatonic, chromatic, concert):
    args = json.dumps({'diatonic': diatonic, 'chromatic': chromatic})
    assert run_function('writtenToConcertKey', '', f'writtenToConcertKey({written}, {args})') == concert


@pytest.mark.parametrize('params', [None, {}, {'fifths': 8}, {'fifths': -8},
    {'fifths': 0.5}, {'fifths': '2'}, {'fifths': 0, 'staff': -1, 'measure': 1},
    {'fifths': 0, 'staff': 5, 'measure': 1}, {'fifths': 0, 'staff': 0, 'measure': 0},
])
def test_invalid_key_request_does_not_enter_editor(params):
    result = run_function('setKeySignature', 'var curScore={nstaves:5};',
                          'setKeySignature(' + json.dumps(params) + ')')
    assert result['error']


@pytest.mark.parametrize('existing,changed', [
    (None, True),
    ({'type': 1, 'concertKey': -3, 'actualKey': -1}, True),
    ({'type': 1, 'concertKey': 0, 'actualKey': 2}, False),
])
def test_key_replaces_only_target_and_is_idempotent(existing, changed):
    setup = '''
var Element={KEYSIG:1}, existing=EXISTING, removed=[], added=[], undoCalls=0;
var target={tick:1920,next:null,elementAt(track){return track===4 ? existing : null;}};
var cursor={tick:0,segment:{tick:0},fraction:{},measure:{firstSegment:null},
  nextMeasure(){this.tick=1920;this.segment=target;this.measure.firstSegment=target;return true;},
  add(k){added.push(k);}};
var curScore={nstaves:2,style:{value(){return false;}},staves:[{}, {transpose(){return {diatonic:-1,chromatic:-2};}}]};
function createCursor(p){if(p.startStaff!==1)throw Error('wrong staff');return cursor;}
function writtenToConcertKey(k,i){return k-2;}
function executeWithUndo(f){undoCalls++;return f();}
function removeElement(e){removed.push(e);}
function newElement(){return {};}
'''.replace('EXISTING', json.dumps(existing))
    result = run_function('setKeySignature', setup,
        '({report:setKeySignature({staff:1,measure:2,fifths:2}),removed:removed,added:added,undoCalls:undoCalls})')
    assert result['report']['changed'] is changed
    assert result['report']['writtenFifths'] == 2
    assert result['report']['concertFifths'] == 0
    assert result['undoCalls'] == int(changed)
    assert result['removed'] == ([existing] if existing and changed else [])
    assert result['added'] == ([{'concertKey': 0, 'actualKey': 2}] if changed else [])


def test_key_requires_written_display():
    setup = 'var curScore={nstaves:1,style:{value(){return true;}}};'
    assert 'concert pitch' in run_function('setKeySignature', setup,
        'setKeySignature({staff:0,measure:1,fifths:0})')['error']


@pytest.mark.parametrize('params', [None, {}, {'widthMm': '210'},
    {'widthMm': -1}, {'widthMm': float('inf')},
    dict(widthMm=210, heightMm=297, leftMm=110, rightMm=110, topMm=20, bottomMm=16),
    dict(widthMm=210, heightMm=297, leftMm=18, rightMm=12, topMm=150, bottomMm=147),
])
def test_invalid_page_settings_never_enter_edit(params):
    assert run_function('setPageLayout', 'var curScore={};',
        'setPageLayout(' + json.dumps(params) + ')')['error']


def test_page_settings_convert_millimeters_and_update_both_page_margins():
    setup = '''
var values={};
var curScore={style:{setValue(k,v){values[k]=v;},value(k){return values[k];}}};
function executeWithUndo(f){return f();}
function getPageLayout(){return {};}
'''
    result = run_function('setPageLayout', setup,
        '({report:setPageLayout({widthMm:210,heightMm:297,leftMm:18,rightMm:12,topMm:20,bottomMm:16}),values:values})')
    assert result['report']['success'] is True
    expected = dict(pageWidth=210, pageHeight=297, pagePrintableWidth=180,
        pageOddLeftMargin=18, pageEvenLeftMargin=18,
        pageOddTopMargin=20, pageEvenTopMargin=20,
        pageOddBottomMargin=16, pageEvenBottomMargin=16)
    assert result['values'] == pytest.approx({k: v/25.4 for k, v in expected.items()})


def test_page_write_mismatch_is_not_reported_as_success():
    setup = '''
var curScore={style:{setValue(){},value(){return 0;}}};
function executeWithUndo(f){try{return f();}catch(e){return {error:String(e)};}}
'''
    assert run_function('setPageLayout', setup,
        'setPageLayout({widthMm:210,heightMm:297,leftMm:18,rightMm:12,topMm:20,bottomMm:16})')['error']


@pytest.mark.parametrize('existing,kind,changed,expected', [
    ([], 'page', True, [0]), ([0], 'page', False, [0]),
    ([0], 'line', True, [1]), ([1], 'none', True, []),
    ([], 'none', False, []), ([0, 1], 'page', True, [0]),
])
def test_layout_break_replacement_deduplication_and_removal(existing, kind, changed, expected):
    setup = '''
var Element={LAYOUT_BREAK:1}, LayoutBreak={PAGE:0,LINE:1,SECTION:2};
var untouched={type:99};
var measure={elements:EXISTING.map(t=>({type:1,layoutBreakType:t})).concat([untouched]),
remove(e){this.elements.splice(this.elements.indexOf(e),1);},add(e){this.elements.push(e);}};
var curScore={};
function createCursor(){return {measure:measure};}
function executeWithUndo(f){return f();}
function newElement(t){return {type:t};}
'''.replace('EXISTING', json.dumps(existing))
    result = run_function('setLayoutBreak', setup,
        '({report:setLayoutBreak(' + json.dumps({'measure':1,'type':kind}) + '),elements:measure.elements})')
    assert result['report']['changed'] is changed
    assert [e['layoutBreakType'] for e in result['elements'] if e['type']==1] == expected
    assert {'type':99} in result['elements']


def test_section_break_is_preserved():
    setup = '''
var Element={LAYOUT_BREAK:1}, LayoutBreak={SECTION:2}, curScore={};
function createCursor(){return {measure:{elements:[{type:1,layoutBreakType:2}]}};}
'''
    assert 'section break' in run_function('setLayoutBreak', setup,
        'setLayoutBreak({measure:1,type:"page"})')['error']


def test_layout_commands_dispatch_in_sequence():
    result = run_function('processSequence',
        'var curScore={},selectionState={},calls=[];function processCommand(c){calls.push(c.action);return {success:true};}',
        '({report:processSequence({sequence:[{action:"setPageLayout"},{action:"setLayoutBreak"},{action:"save"},{action:"getPageLayout"}]}),calls:calls})')
    assert result['calls'] == ['setPageLayout', 'setLayoutBreak', 'save', 'getPageLayout']
    assert result['report']['completedIndices'] == [0, 1, 2, 3]


def test_part_instrument_replacement_uses_musescore_template():
    setup = '''
var currentId="flute", undoCalls=0;
var part={instrumentAtTick(){return {instrumentId:currentId};}};
var curScore={parts:[part],replaceInstrument(target,id){if(target!==part)throw Error("wrong part");currentId=id;}};
function executeWithUndo(f){undoCalls++;return f();}
'''
    result = run_function('setPartInstrument', setup,
        '({report:setPartInstrument({part:0,instrumentId:"oboe"}),actual:currentId,undoCalls:undoCalls})')
    assert result['report'] == {
        'success': True, 'changed': True, 'part': 0,
        'previousInstrumentId': 'flute', 'instrumentId': 'oboe',
        'scope': 'MuseScore instrument template, notation defaults, and playback sound',
    }
    assert result['actual'] == 'oboe'
    assert result['undoCalls'] == 1


def test_unknown_part_instrument_is_not_reported_as_success():
    setup = '''
var currentId="flute";
var part={instrumentAtTick(){return {instrumentId:currentId};}};
var curScore={parts:[part],replaceInstrument(){}};
function executeWithUndo(f){try{return f();}catch(e){return {error:String(e)};}}
'''
    result = run_function('setPartInstrument', setup,
        'setPartInstrument({part:0,instrumentId:"not-a-real-instrument"})')
    assert 'unknown instrumentId' in result['error']


def test_identical_part_instrument_skips_editor_command():
    setup = '''
var curScore={parts:[{instrumentAtTick(){return {instrumentId:"flute"};}}],replaceInstrument(){throw Error("must not edit");}};
function executeWithUndo(){throw Error("must not enter undo");}
'''
    result = run_function('setPartInstrument', setup,
        'setPartInstrument({part:0,instrumentId:"flute"})')
    assert result == {'success': True, 'changed': False, 'part': 0, 'instrumentId': 'flute'}


def test_midi_patch_is_explicitly_not_an_audio_assignment():
    result = run_function('setMidiPatch', '', 'setMidiPatch({part:0,program:0})')
    assert 'does not control MuseScore 4 audio resources' in result['error']


def test_sequence_accepts_part_instrument_replacement():
    result = run_function('processSequence',
        'var curScore={},selectionState={},calls=[];function processCommand(c){calls.push(c.action);return {success:true};}',
        '({report:processSequence({sequence:[{action:"setPartInstrument",params:{part:0,instrumentId:"flute"}},{action:"save"}]}),calls:calls})')
    assert result['calls'] == ['setPartInstrument', 'save']
    assert result['report']['completedIndices'] == [0, 1]


def test_chord_writes_voice_duration_pitches_and_written_tpcs():
    setup = '''
var Element={CHORD:1}, Sid={concertPitch:1}, selectionState={startStaff:0,startTick:0};
var notes=[], durations=[], ranges=[];
var chord={type:1,notes:notes,actualDuration:{ticks:720}};
var cursor={tick:1920,element:chord,staffIdx:0,voice:0,
  setDuration(z,n){durations.push([z,n]);},rewindToTick(t){this.tick=t;},
  addNote(p,stack){notes.push({pitch:p,tpc:99,stack:stack});}};
var curScore={nstaves:1,style:{value(){return false;}},selection:{clear(){},selectRange(...a){ranges.push(a);}}};
function createCursor(p){if(p.startStaff!==0||p.voice!==undefined||p.startTick!==1920)throw Error('wrong position');return cursor;}
function executeWithUndo(f){return f();}
function processElement(){return {kind:'chord'};}
'''
    result = run_function('addChord', setup,
        '({report:addChord({staff:0,voice:1,startTick:1920,duration:{numerator:3,denominator:8},pitches:[60,64,67],tpcs:[14,18,15]}),durations:durations,ranges:ranges,notes:notes,cursorVoice:cursor.voice})')
    assert result['report']['success'] is True
    assert result['report']['durationTicks'] == 720
    assert result['report']['notes'] == [
        {'pitch': 60, 'tpc': 14}, {'pitch': 64, 'tpc': 18}, {'pitch': 67, 'tpc': 15},
    ]
    assert result['durations'] == [[3, 8]]
    assert result['ranges'] == [[1920, 2640, 0, 1]]
    assert [note['stack'] for note in result['notes']] == [False, True, True]
    assert result['cursorVoice'] == 1


@pytest.mark.parametrize('params,error', [
    (None, 'pitches'),
    ({'pitches': [], 'duration': {'numerator': 1, 'denominator': 4}}, 'pitches'),
    ({'pitches': [128], 'duration': {'numerator': 1, 'denominator': 4}}, 'pitch'),
    ({'pitches': [60, 60], 'duration': {'numerator': 1, 'denominator': 4}}, 'Duplicate'),
    ({'pitches': [60], 'duration': {'numerator': 0, 'denominator': 4}}, 'duration'),
    ({'pitches': [60], 'duration': {'numerator': 1, 'denominator': 4}, 'voice': 4}, 'voice'),
    ({'pitches': [60], 'duration': {'numerator': 1, 'denominator': 4}, 'tpcs': [36]}, 'TPC'),
])
def test_chord_rejects_invalid_requests_before_edit(params, error):
    setup = '''
var Sid={concertPitch:1},selectionState={startStaff:0,startTick:0};
var curScore={nstaves:1,style:{value(){return false;}}};
function executeWithUndo(){throw Error('must not edit');}
'''
    result = run_function('addChord', setup, 'addChord(' + json.dumps(params) + ')')
    assert error.lower() in result['error'].lower()


def test_written_tpc_requires_written_pitch_display():
    setup = '''
var Sid={concertPitch:1},selectionState={startStaff:0,startTick:0};
var curScore={nstaves:1,style:{value(){return true;}}};
'''
    result = run_function('addChord', setup,
        'addChord({pitches:[60],tpcs:[14],duration:{numerator:1,denominator:4}})')
    assert 'concert pitch' in result['error']


def test_tie_targets_next_matching_pitch_in_same_voice():
    setup = '''
var Element={CHORD:1}, source={pitch:60,tieForward:null}, target={pitch:60};
var sourceChord={type:1,notes:[source]}, targetChord={type:1,notes:[target]};
var curScore={nstaves:1,selection:{clear(){},select(note,add){if(note!==source||add!==false)throw Error('wrong selection');}}};
function cursor(){return {tick:0,element:sourceChord,next(){this.tick=480;this.element=targetChord;return true;}};}
function createCursor(p){if(p.startStaff!==0||p.voice!==2||p.startTick!==0)throw Error('wrong position');return cursor();}
function executeWithUndo(f){return f();}
function cmd(name){if(name!=='tie')throw Error('wrong command');source.tieForward={endNote:target};}
'''
    result = run_function('addTie', setup,
        'addTie({staff:0,voice:2,startTick:0,pitch:60})')
    assert result == {'success': True, 'changed': True, 'staff': 0, 'voice': 2,
                      'startTick': 0, 'endTick': 480, 'pitch': 60}


def test_tie_rejects_nonmatching_next_chord():
    setup = '''
var Element={CHORD:1}, source={pitch:60,tieForward:null};
var sourceChord={type:1,notes:[source]}, targetChord={type:1,notes:[{pitch:62}]};
var curScore={nstaves:1,selection:{clear(){},select(){}}};
function createCursor(){return {tick:0,element:sourceChord,next(){this.tick=480;this.element=targetChord;return true;}};}
function executeWithUndo(f){try{return f();}catch(e){return {error:String(e)};}}
'''
    result = run_function('addTie', setup,
        'addTie({staff:0,voice:0,startTick:0,pitch:60})')
    assert 'matching pitch' in result['error']


def test_sequence_accepts_chords_and_ties():
    result = run_function('processSequence',
        'var curScore={},selectionState={},calls=[];function processCommand(c){calls.push(c.action);return {success:true};}',
        '({report:processSequence({sequence:[{action:"addChord"},{action:"addTie"},{action:"save"}]}),calls:calls})')
    assert result['calls'] == ['addChord', 'addTie', 'save']
    assert result['report']['completedIndices'] == [0, 1, 2]


def test_grace_note_selects_main_note_and_verifies_created_result():
    setup = '''
var Element={CHORD:1}, NoteType={ACCIACCATURA:10,APPOGGIATURA:11,GRACE4:12,GRACE16:13,
  GRACE32:14,GRACE8_AFTER:15,GRACE16_AFTER:16,GRACE32_AFTER:17};
var selectionState={}, selected=null, dispatched=[];
var mainNote={pitch:64,tpc:18}, mainChord={type:1,notes:[mainNote],graceNotes:[],actualDuration:{ticks:480}};
var curScore={nstaves:1,style:{value(){return false;}},selection:{clear(){},select(n,add){selected=n;}}};
function createCursor(p){return {tick:0,element:mainChord};}
function executeWithUndo(f){try{return f();}catch(e){return {error:String(e)};}}
function processElement(){return {name:"Chord"};}
function cmd(name){
  dispatched.push(name);
  var graceNote={pitch:64,tpc:18,noteType:10};
  mainChord.graceNotes.push({notes:[graceNote]});
}
'''
    result = run_function('addGraceNote', setup,
        '({report:addGraceNote({staff:0,voice:0,startTick:0,pitch:66,tpc:20,type:"acciaccatura"}),'
        'selected:selected,dispatched:dispatched,grace:mainChord.graceNotes[0].notes[0]})')
    assert result['report']['success'] is True
    assert result['report']['type'] == 'acciaccatura'
    assert result['report']['placement'] == 'before'
    assert result['report']['note'] == {'pitch': 66, 'tpc': 20, 'noteType': 10}
    assert result['selected'] == {'pitch': 64, 'tpc': 18}
    assert result['dispatched'] == ['acciaccatura']
    assert result['grace']['pitch'] == 66


@pytest.mark.parametrize('kind,action,note_type,placement', [
    ('appoggiatura', 'appoggiatura', 11, 'before'),
    ('grace4', 'grace4', 12, 'before'),
    ('grace16', 'grace16', 13, 'before'),
    ('grace32', 'grace32', 14, 'before'),
    ('grace8after', 'grace8after', 15, 'after'),
    ('grace16after', 'grace16after', 16, 'after'),
    ('grace32after', 'grace32after', 17, 'after'),
])
def test_grace_note_dispatches_every_supported_musescore_type(kind, action, note_type, placement):
    setup = '''
var Element={CHORD:1}, NoteType={ACCIACCATURA:10,APPOGGIATURA:11,GRACE4:12,GRACE16:13,
  GRACE32:14,GRACE8_AFTER:15,GRACE16_AFTER:16,GRACE32_AFTER:17};
var selectionState={}, dispatched=[];
var mainChord={type:1,notes:[{pitch:60,tpc:14}],graceNotes:[],actualDuration:{ticks:480}};
var curScore={nstaves:1,style:{value(){return false;}},selection:{clear(){},select(){}}};
function createCursor(){return {tick:0,element:mainChord};}
function executeWithUndo(f){try{return f();}catch(e){return {error:String(e)};}}
function processElement(){return {};}
function cmd(name){dispatched.push(name);mainChord.graceNotes.push({notes:[{pitch:60,tpc:14,noteType:TYPE}]});}
'''.replace('TYPE', str(note_type))
    result = run_function('addGraceNote', setup,
        '({report:addGraceNote({staff:0,startTick:0,pitch:61,type:' + json.dumps(kind) + '}),calls:dispatched})')
    assert result['report']['success'] is True
    assert result['report']['placement'] == placement
    assert result['calls'] == [action]


@pytest.mark.parametrize('params,error', [
    (None, 'type'),
    ({'staff': 0, 'startTick': 0, 'pitch': 60, 'type': 'mordent'}, 'unsupported'),
    ({'staff': -1, 'startTick': 0, 'pitch': 60, 'type': 'acciaccatura'}, 'staff'),
    ({'staff': 0, 'voice': 4, 'startTick': 0, 'pitch': 60, 'type': 'acciaccatura'}, 'voice'),
    ({'staff': 0, 'startTick': -1, 'pitch': 60, 'type': 'acciaccatura'}, 'starttick'),
    ({'staff': 0, 'startTick': 0, 'pitch': 128, 'type': 'acciaccatura'}, 'pitch'),
    ({'staff': 0, 'startTick': 0, 'pitch': 60, 'tpc': 36, 'type': 'acciaccatura'}, 'tpc'),
])
def test_grace_note_rejects_invalid_requests_before_edit(params, error):
    setup = '''
var NoteType={ACCIACCATURA:10,APPOGGIATURA:11,GRACE4:12,GRACE16:13,GRACE32:14,
  GRACE8_AFTER:15,GRACE16_AFTER:16,GRACE32_AFTER:17};
var curScore={nstaves:1,style:{value(){return false;}}};
function executeWithUndo(){throw Error("must not edit");}
'''
    result = run_function('addGraceNote', setup, 'addGraceNote(' + json.dumps(params) + ')')
    assert error in result['error'].lower()


def test_sequence_accepts_grace_note():
    result = run_function('processSequence',
        'var curScore={},selectionState={},calls=[];function processCommand(c){calls.push(c.action);return {success:true};}',
        '({report:processSequence({sequence:[{action:"addGraceNote"},{action:"save"}]}),calls:calls})')
    assert result['calls'] == ['addGraceNote', 'save']
    assert result['report']['completedIndices'] == [0, 1]


def test_rest_writes_explicit_voice_position_and_duration():
    setup = '''
var Element={REST:2}, selectionState={startStaff:0,startTick:0}, added=false;
var rest={type:2,name:"Rest",actualDuration:{ticks:480},tuplet:null};
var cursor={tick:960,voice:0,element:null,
  setDuration(n,d){if(n!==1||d!==4)throw Error("wrong duration");},
  addRest(){if(this.voice!==3)throw Error("wrong voice");added=true;this.element=rest;},
  rewindToTick(t){if(t!==960)throw Error("wrong rewind");this.tick=t;if(added)this.element=rest;}};
var curScore={nstaves:2,newCursor(){return cursor;},selection:{clear(){},selectRange(a,b,c,d){
  if(a!==960||b!==1440||c!==1||d!==2)throw Error("wrong selection");}}};
var Cursor={INPUT_STATE_SYNC_WITH_SCORE:1};
function createCursor(p){if(p.startStaff!==1||p.startTick!==960)throw Error("wrong position");return cursor;}
function executeWithUndo(f){return f();}
function processElement(e){return {name:e.name,durationTicks:e.actualDuration.ticks};}
'''
    result = run_function('addRest', setup,
        'addRest({staff:1,voice:3,startTick:960,duration:{numerator:1,denominator:4}})')
    assert result['success'] is True
    assert result['changed'] is True
    assert result['staff'] == 1
    assert result['voice'] == 3
    assert result['startTick'] == 960
    assert result['durationTicks'] == 480


@pytest.mark.parametrize('params,error', [
    ({'staff': -1, 'voice': 0, 'startTick': 0, 'duration': {'numerator': 1, 'denominator': 4}}, 'staff'),
    ({'staff': 0, 'voice': 4, 'startTick': 0, 'duration': {'numerator': 1, 'denominator': 4}}, 'voice'),
    ({'staff': 0, 'voice': 0, 'startTick': -1, 'duration': {'numerator': 1, 'denominator': 4}}, 'starttick'),
    ({'staff': 0, 'voice': 0, 'startTick': 0, 'duration': {'numerator': 0, 'denominator': 4}}, 'duration'),
])
def test_rest_rejects_invalid_explicit_parameters(params, error):
    setup = 'var curScore={nstaves:1};var selectionState={startStaff:0,startTick:0};'
    result = run_function('addRest', setup, 'addRest(' + json.dumps(params) + ')')
    assert error in result['error'].lower()


def test_tuplet_writes_ratio_voice_position_and_total_duration():
    setup = '''
var selectionState={}, Element={REST:2};
var tuplet={actualNotes:3,normalNotes:2,actualDuration:{ticks:960}};
var rest={type:2,name:"Rest",actualDuration:{ticks:320},tuplet:tuplet};
var created=false,cursor={tick:1920,voice:0,element:null,
  setDuration(n,d){if(n!==1||d!==4)throw Error("wrong duration");},
  addTuplet(r,d){if(this.voice!==2||r.n!==3||r.d!==2||d.n!==1||d.d!==4)throw Error("wrong tuplet");created=true;},
  rewindToTick(t){if(t!==1920)throw Error("wrong rewind");this.tick=t;if(created)this.element=rest;}};
var curScore={nstaves:1,selection:{clear(){},selectRange(a,b,c,d){
  if(a!==1920||b!==2880||c!==0||d!==1)throw Error("wrong selection");}}};
function createCursor(p){if(p.startStaff!==0||p.startTick!==1920)throw Error("wrong position");return cursor;}
function fraction(n,d){return {n:n,d:d};}
function executeWithUndo(f){return f();}
function processElement(e){return {name:e.name,durationTicks:e.actualDuration.ticks,isTuplet:!!e.tuplet};}
'''
    result = run_function('addTuplet', setup,
        'addTuplet({staff:0,voice:2,startTick:1920,ratio:{numerator:3,denominator:2},duration:{numerator:1,denominator:4}})')
    assert result['success'] is True
    assert result['changed'] is True
    assert result['voice'] == 2
    assert result['durationTicks'] == 960
    assert result['ratio'] == {'numerator': 3, 'denominator': 2}


@pytest.mark.parametrize('params,error', [
    ({'staff': 1, 'voice': 0, 'startTick': 0, 'ratio': {'numerator': 3, 'denominator': 2}, 'duration': {'numerator': 1, 'denominator': 4}}, 'staff'),
    ({'staff': 0, 'voice': -1, 'startTick': 0, 'ratio': {'numerator': 3, 'denominator': 2}, 'duration': {'numerator': 1, 'denominator': 4}}, 'voice'),
    ({'staff': 0, 'voice': 0, 'startTick': 0, 'ratio': {'numerator': 3, 'denominator': 0}, 'duration': {'numerator': 1, 'denominator': 4}}, 'ratio'),
    ({'staff': 0, 'voice': 0, 'startTick': 0, 'ratio': {'numerator': 3, 'denominator': 2}, 'duration': {'numerator': 1, 'denominator': 0}}, 'duration'),
])
def test_tuplet_rejects_invalid_explicit_parameters(params, error):
    result = run_function('addTuplet', 'var curScore={nstaves:1};',
                          'addTuplet(' + json.dumps(params) + ')')
    assert error in result['error'].lower()


def test_validate_params_returns_structured_error_for_null():
    result = run_function('validateParams', '', 'validateParams(null,["duration"])')
    assert result == {'error': 'Missing required parameters: duration'}
