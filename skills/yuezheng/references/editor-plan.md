# Agent plans: default file backend

Use `musescore_build_score(specification, steps, output_path)` or
`yuezheng build-score PLAN.json --output SCORE.mscz` for unattended creation.
PLAN contains `score` plus ordered `steps`. See the executable
[example](../../../examples/native-plan.json). This route does not use computer
use, Accessibility, a running GUI or WebSocket. It creates a private scaffold,
executes the commands below in MuseScore's official extension host, validates
per-run acknowledgements stored in MSCZ, then publishes the native score.

For editing, `musescore_apply_plan(plan_path, input_path, output_path)` accepts
`{"target": THE_RETURNED_TARGET, "steps": [...]}`. `output_path` defaults to the
input. Each private batch is published only after every step succeeds. An error
or `incomplete` leaves input and existing output unchanged, so a corrected batch
can be replayed safely from that unchanged file. This differs from the live
WebSocket partial-write behavior described below. `save` requests are fulfilled
by the converter; no Save dialog is opened.

## Positioned special notation (2.11)

All commands use zero-based `staff`, optional `voice` (0–3, default 0), and
`startTick`. A quarter note is 480 ticks. Write the main chord first.

| Action | Additional parameters | Verified scope |
| --- | --- | --- |
| `addGraceNotes` | `type`, `notes:[{pitch,tpc},...]` | Group in input musical order; handles MuseScore's prepend behavior |
| `addGraceSlur` | optional zero-based `graceIndex` | Connects a grace note to its main chord |
| `addTremolo` | `type: r8/r16/r32/r64/buzz` | Single-chord tremolos; uses the running version's enum |
| `addArpeggio` | `type: normal/up/down/bracket/upStraight/downStraight` | One staff; `span:1` |
| `addFermata` | `type: normal/short/long/veryShort/veryLong`, optional `below`, `timeStretch` | Semantic fermata and playback duration factor |
| `addOrnament` | `type: trill/shortTrill/mordent/turn/invertedTurn` | Chord-attached ornament |
| `getDrumset` | optional tick | Reads valid drum pitches, names, lines, noteheads and voices |
| `addPercussionNote` | `pitches`, `duration` | Same position/duration as addChord; rejects pitches absent from the actual drumset |
| `setAccidental` | `pitch`, `type: natural/sharp/flat/doubleSharp/doubleFlat`, `bracket: none/parentheses/square` | Forced/courtesy accidental on a main note |
| `setNoteHead` | `pitch`, `type: normal/cross/diamond/triangle` | Notehead appearance; for percussion updates the part's drum-pitch mapping |
| `setTempo` | `bpm`, `beatUnit: quarter/dottedQuarter/half/eighth`, optional `text` | For dotted quarter = 124, playback uses quarter = 186 |

`addArticulation` also accepts `accent`. Select an explicit single-staff range
before dynamics, articulations, slurs, lyrics or technique text. Slurs retain
both endpoint chords even at the end of the last measure. `addLyrics` requires
an array of strings, optional zero-based `verse`.

Pitched templates include flute, oboe, Bb/bass clarinet, bassoon, horn, Bb trumpet,
trombone, tuba, timpani, violin, viola, violoncello, contrabass, piano, glockenspiel
and marimba. Use `cello` in a specification if desired; it resolves to the real
MuseScore template `violoncello`. Multi-staff instruments supply `clefs`.
Unpitched templates include percussion, snare-drum, bass-drum, cymbal,
crash-cymbal, tambourine and triangle. Their scaffold uses channel 10, an
unpitched instrument, percussion clef and no key signature. A name alone is
never treated as a playback assignment.

## Optional live WebSocket backend


A plan is execution data, not a new mandatory music representation. Use small,
ordered batches with stable IDs:

```json
{"steps": [
  {"id": "flute-m1-position", "action": "goToMeasure", "params": {"measure": 1}},
  {"id": "flute-m1-dynamic", "action": "addDynamic", "params": {"type": "p"}}
]}
```

Check the connected backend's capabilities and parameters before execution.
The bundled action-protocol plugin 2.1 supports standard `addDynamic`,
`addTechniqueText`, and `save` on an already-open score. `save` uses its existing
MuseScore path. Set an explicit staff/tick range when positioning a batch:
`selectCustomRange({startTick: 0, endTick: 480, startStaff: 0, endStaff: 1})`.
Staff indices are zero-based and endStaff is exclusive. Do not assume duration
conventions or command names are interchangeable across plugins.

## Backend evidence

Yuezheng includes `plugins/musescore-mcp-websocket.qml`. Its `getCapabilities`
response separates available `commands` from `reserved_commands`; editor-status
exposes that response. Upstream mcp-score uses a different `command` protocol;
the bundled plugin uses `action`. Prefer the connected instance's capabilities
over an upstream command list. Opening an existing file is handled by
`musescore_open`. Initial-score creation is handled by `musescore_create_score`,
which builds and converts a private MusicXML scaffold before the WebSocket edit
session. Create/Open/Save-As remain reserved in the QML plugin itself. Standard
MuseScore instrument replacement, including its playback sound, is available
through `setPartInstrument`.

Create the scaffold before executing editor steps:

```json
{"title":"Agent Orchestra","measures":5,"time":{"beats":12,"beat_type":8},
 "key_fifths":-2,"tempo_bpm":124,
 "parts":[{"name":"Flute","instrument_id":"flute"},
          {"name":"Piano","instrument_id":"piano","clefs":["treble","bass"]}]}
```

The tool rejects unresolved instruments instead of allowing a silent piano
fallback. Its returned `instrument_steps` use MuseScore catalog IDs for an
idempotent live check. The MSCZ is the edit target and final deliverable; the
seed MusicXML is internal scaffolding.

The range → dynamic → technique text → save batch was verified on MuseScore
4.7.4 by inspecting the saved MSCZ: `mp` with velocity 64 and the exact staff text
occurred on the target staff only. This verifies these edits, not all notation
or audible technique switching.

Plugin 2.2 adds batched `addArticulation({type:"staccato"})` (also marcato,
tenuto) and `addSlur({})`. Use selectCustomRange before each operation. A slur
connects the selected notes in a single staff and voice; select at least two
chord positions. Live tests verified exact saved symbols and paired slur endpoints
in an initially unmarked second staff. Rest-only and multi-staff ranges are
rejected, as is a one-note slur. Articulations toggle existing marks; these writes
are not idempotent. Cross-staff and mixed-voice slurs need another editing route.

`SCOREBRIDGE_MUSESCORE_WS` overrides `ws://localhost:8765`.
`SCOREBRIDGE_MUSESCORE_PROTOCOL` may be `auto`, `action`, or `command`.
Auto mode probes only `ping`; write operations are never retried automatically.

Plans execute sequentially, not atomically. On `incomplete`, preserve completed
IDs and read actual editor state before continuing. A timeout can occur after an
edit applied. Do not replay the full plan and duplicate notes. `executed` means
commands acknowledged, not that a score has been saved or verified musically.

A notation-only marking and its playback effect are separate checks. An opened
instrument dialog, a renamed part, or a nonempty audio file does not demonstrate
a correct instrument assignment.

## Instrument identity and playback (bundled plugin 2.5)

Use `getMidiChannels` to inspect part indices, instrument IDs and channel data.
To correct a standard instrument, execute for example:

```json
{"steps":[
  {"id":"flute-sound","action":"setPartInstrument","params":{"part":0,"instrumentId":"flute"}},
  {"id":"save-sound","action":"save"}
]}
```

`part` is zero-based. `instrumentId` must be an ID from MuseScore's instrument
catalog, not the visible staff label or a General MIDI number. The command calls
MuseScore 4.7's instrument-template replacement API, reads the new ID back, and
fails unknown IDs instead of claiming success. Replacement can change the part's
name, clef, transposition and playback sound; use it intentionally before writing
or after auditing imported parts. Raw `setMidiPatch` is reserved: live testing
showed that its saved MIDI program changed while rendered audio stayed identical.
Arbitrary MuseSound, VST and SoundFont resource selection remains outside this
command.

## Precise note, chord and tie entry (bundled plugin 2.6)

Use `addChord` for both single notes and chords. Position every event explicitly:

```json
{"action":"addChord","params":{
  "staff":0,"voice":1,"startTick":1920,
  "duration":{"numerator":3,"denominator":8},
  "pitches":[72,76,79],"tpcs":[14,18,15]
}}
```

Duration is a fraction of a whole note, so `1/4` is a quarter and `3/8` is a
dotted quarter. Staff and voice are zero-based; voices range from 0 through 3.
The command locates the tick before switching voices so an empty secondary voice
can be expanded correctly. It rejects absent ticks, invalid pitches, duplicate
pitches, zero durations and mismatched TPC arrays, then reads the saved chord
back before reporting success.

TPC preserves the printed spelling when written-pitch display is active. Natural
bases are F=13, C=14, G=15, D=16, A=17, E=18, B=19; add 7 per sharp and subtract
7 per flat. For example, F-sharp=20, B-flat=12 and E-flat=11. The accepted range
is -1 through 35. Omit `tpcs` only when MuseScore's automatic spelling is suitable.

Add one tie per pitch after both source and destination chords exist:

```json
{"action":"addTie","params":{"staff":0,"voice":1,"startTick":1920,"pitch":72}}
```

The immediate next event in that voice must be a chord containing the same MIDI
pitch. An existing forward tie returns `changed:false`; a rest or nonmatching
chord fails without inventing a destination note. For large passages, batch
positioned chords first, then ties, markings and `save`.

## Precise rests and tuplets (bundled plugin 2.7)

Rests use the same whole-note duration convention as chords:

```json
{"action":"addRest","params":{"staff":0,"voice":2,"startTick":0,"duration":{"numerator":1,"denominator":4}}}
```

Staff and voice are zero-based. The command locates the tick before switching
voice, so it can expand an empty secondary voice, and reads the created rest back
before reporting success.

Create a quarter-duration 3:2 eighth-note triplet with:

```json
{"action":"addTuplet","params":{"staff":0,"voice":3,"startTick":960,"ratio":{"numerator":3,"denominator":2},"duration":{"numerator":1,"denominator":4}}}
```

`ratio.numerator` is the actual note count and `ratio.denominator` is the normal
count occupying the same span. `duration` is the total tuplet span. MuseScore
initially fills the container with rests; write the member notes/rests afterward
at their score ticks. The command rejects invalid positions and ratios, then
verifies MuseScore's actual/normal note counts and total duration. Cross-measure
and nested tuplets remain outside the verified scope.

## Grace notes (bundled plugin 2.8)

Create the main chord first, then attach one semantic grace note to it:

```json
{"action":"addGraceNote","params":{"staff":0,"voice":0,"startTick":1920,"pitch":71,"tpc":19,"type":"acciaccatura"}}
```

The main chord is addressed by zero-based staff and voice plus absolute tick.
`pitch` is the grace note's MIDI pitch and optional `tpc` is its printed spelling
under written-pitch display. Supported types are `acciaccatura`, `appoggiatura`,
`grace4`, `grace16`, `grace32`, `grace8after`, `grace16after`, and
`grace32after`. If the main event is a chord, optional `anchorPitch` selects the
main note used to invoke MuseScore's grace-note command; the grace chord still
belongs to the whole main chord. The command reads back the created pitch, TPC,
semantic `NoteType`, placement and total grace-note count. Preserve completed
plan IDs when resuming so a grace note is not inserted twice.

## Exact score binding (bundled plugin 2.9)

Score creation returns an opaque target object. Preserve it verbatim:

```json
{"target":{"targetId":"scorebridge-...","scoreName":"score","title":"Agent Score","numMeasures":5,"numStaves":22}}
```

Before editing, use `musescore_bind_score` (CLI `yuezheng bind-score`) with
the MSCZ path and that target. A listener is reused only when it already owns the
requested score. A different live score returns `wrong_target` without opening
or editing anything; stop that listener and bind again. When no listener exists,
Yuezheng starts a dedicated MuseScore process. Binding succeeds only when the
plugin's read-only `getScoreIdentity` result exactly matches all five fields.

Every `musescore_execute_plan` payload must contain the same top-level `target`.
The executor checks identity before sending the first mutation. A mismatch
returns `wrong_target`, an empty `completed` list and field-by-field differences.
Do not weaken this check to filenames, active-window guesses or process IDs.

## Written key signatures (bundled plugin 2.3)

Use `setKeySignature` in a plan with explicit `staff`, `measure`, and `fifths`.
For a B-flat clarinet at staff 1 whose second measure prints one flat:
`{"action":"setKeySignature","params":{"staff":1,"measure":2,"fifths":-1}}`.
Read the printed key directly; do not pre-transpose this input. The command derives
the concert key from MuseScore's staff transposition at that measure. An identical
setting returns changed:false. A new setting replaces the signature at that
position without transposing existing notes. It affects the selected staff only.
Use written-pitch display and conventional keys (-7 through +7); percussion and
custom key signatures need another route. The target must be a measure start.

## Page layout (bundled plugin 2.4)

The Agent decides page dimensions and break positions from the source or desired
layout; these commands execute those decisions. For A4 with custom margins:

```json
{"steps":[
  {"id":"page-size","action":"setPageLayout","params":{"widthMm":210,"heightMm":297,"leftMm":18,"rightMm":12,"topMm":20,"bottomMm":16}},
  {"id":"break-m4","action":"setLayoutBreak","params":{"measure":4,"type":"page"}},
  {"id":"save-layout","action":"save"}
]}
```

All six page values are required, in millimeters. Margins must leave a positive
printable area. The same margins apply to odd and even pages (not mirrored).
`setLayoutBreak` applies score-wide after the one-based measure; types are line,
page, none. It replaces an existing layout break and skips an identical one;
section breaks are not removed because they can carry musical settings.
Call `getPageLayout` after the edits finish to read the new page count. The saved
style may round dimensions slightly. These commands do not handle staff sizing,
collision correction, or automatic page-for-page replication of a source.
