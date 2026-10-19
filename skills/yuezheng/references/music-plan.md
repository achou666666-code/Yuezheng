# Shared music plan and delivery

The Agent translates the user's request into a plan and requested formats.
This is internal working data, not a required user form or extra deliverable.

```bash
# Authored image/PDF notation: reuse the native score + steps plan.
yuezheng music-plan work/native-plan.json --output work/music-plan.json
# Audio: wrap frozen Agent/engine events. The Agent supplies musical timing.
yuezheng music-plan work/events.json --output work/music-plan.json --bpm 96
yuezheng deliver-music work/music-plan.json --output final --formats mscz
# Select only what the user asked for:
yuezheng deliver-music work/music-plan.json --output final --formats musicxml pdf midi ace sib
# Listening preview:
yuezheng deliver-music work/music-plan.json --output final --formats wav mp3
```

`wav` and `mp3` render a listening preview from the same notated score through
MuseScore. They are an aid for checking the result, not a new performance, not a
replacement for the original recording, and not a sound-quality guarantee.

MCP: `music_plan`, `music_deliver`, `ace_status`, `sibelius_status`, and
`sibelius_create_score`. These call the same functions
as the CLI. `audio_transcribe` recognizes audio; `music_deliver` does not.

## Plan fields

- `schema_version: 1`, `kind: scorebridge_music_plan`, `title`, `source`.
- `performance`: `tracks` with stable IDs, zero-based `gm_program` or `null`,
  `is_drum`, controls/bends; `events` with track, sounding MIDI pitch, absolute
  source start/end seconds and velocity. Source uncertainties remain explicit.
- `tempo_map`: strictly increasing `{seconds, bpm, source}` starting at zero;
  BPM always means quarter notes per minute.
- `meter_map`: `{quarter, numerator, denominator, source}` at measure boundaries.
- `notation.native`: existing `{"score":..., "steps":[...]}` for detailed
  notation. Preserve original written pitches/keys/lyrics/marks with the native
  commands described in editor-plan.md.
- Without a native plan, the audio notation projection uses `grid_quarters`
  (default .25), concert pitch and provisional enharmonic spelling. It preserves
  overlaps as separate voices, full rests and cross-bar ties. More than four
  voices get additional parts rather than lost notes. The Agent refines this
  representation when a detailed score is requested.
- `bindings.ace`: mapping from performance track ID to sound configuration.

Performance MIDI uses original event times, all supplied tempo/meter changes,
velocity, CC, bends and channel-10 drums. More than 15 pitched tracks get MIDI
ports instead of conflicting program changes. Notation quantization does not
change that performance. A 120 BPM serialization default is explicitly labelled
when no pulse was identified; do not present it as a recognized tempo. Beat
tracker estimates are evidence, with possible half/double pulse ambiguity.

Detailed image/PDF engraving remains native Agent notation; an audio projection
cannot reconstruct the engraving of an unknown original printed score.

## ACE Studio

Install and run ACE Studio with External Agent Access. Prefer its official CLI,
`SCOREBRIDGE_ACE_CLI` or `--ace-cli` override. `ace-status` is read-only.
The adapter creates a separate project, checks imported note identities/timing,
loads actual sources, saves, reopens and reads back. It uses the returned
`savedPath`, since ACE wraps files in a project directory. A dirty previous
project is saved to a private snapshot before switching; it is restored afterwards.
It never uses a discard-changes flag. A host timeout is inspected/recovered,
not treated as a completed write.

Acoustic sources are selected from the live catalog for supported GM classes:
violin/viola/cello/bass, trumpet/trombone/horn, supported saxophones and clarinet.
On macOS, the built-in DLSMusicDevice can supply its factory piano and standard
channel-10 kit. Other sounds use an explicit binding, selected internally by the
Agent from the live catalog. For example:

```json
{"bindings":{"ace":{"strings":{
  "source_ref":"instrument:21"
},"winds":{
  "source_ref":"plugin:vst3:EXACT_REF_FROM_CATALOG",
  "format":"vst3","preset":"EXACT_PRESET_FROM_LIBRARY","midi_channel":1
}}}}}
```

External plugins need a preset, state file, or an explicitly resolved
`single_program` configuration; a multi-instrument plugin's name is insufficient.
An unresolved binding retains private MIDI and returns a concrete repair reason.
The Agent resolves it without sending the user a per-note approval questionnaire.

ACE's AI Instrument clips use native synthesis parameters, **not MIDI CC or
velocity**. Their editable pitches/times and sound bindings are checked;
MIDI expression remains in the private performance MIDI, with an explicit
receipt warning about the unmapped expression. GenericMidi/plugin tracks retain
and verify MIDI velocities/controllers/bends. Explicit supported AI note
articulations are applied by display name. Native synthesis-parameter mappings
can be added per instrument; do not pretend MIDI controllers were applied to AI.
Mounted sound sources and nonempty audio do not prove subjective sound quality.

## Sibelius

Sibelius output uses the official localhost Sibelius Connect WebSocket (default
`ws://127.0.0.1:1898`) and the bundled `Yuezheng.plg` ManuScript bridge.
`yuezheng sibelius-install-plugin` installs it in the user plug-in directory;
the MCP equivalent is `sibelius_install_plugin`. `sibelius_create_score` opens
MusicXML through the plugin and calls `Score.SaveAs(path, "SIBL")`. The adapter
publishes `.sib` only after the response reports success and the file is present.
Use `sibelius_status` to inspect the endpoint and plugin. The plan remains the
same across MuseScore, Sibelius, ACE and file outputs.

## Recovery and publication

Intermediates and receipts live in `final/.scorebridge/`; public files contain
only selected formats. A failed score backend does not block independent MIDI
or MusicXML outputs. Reports list actual outputs and per-format failures.
Resolve a failure and re-run from the same saved plan. Existing user scores are
not used as development scratch space.
