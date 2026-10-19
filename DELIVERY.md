# Yuezheng first-release acceptance

`Release checklist completion: 100%` means that the defined checks for the
release passed. It does not mean universal transcription accuracy, universal
score support, or cross-platform software acceptance.

## Fixed design

Skill instructs the calling Agent → Agent reads original PDF/images → internal
notation plan → the selected native software adapter executes the plan → the
target software handles engraving, instruments, playback and saving → the
requested native project is the main user deliverable.

Recognition is performed by the calling multimodal Agent. Yuezheng executes
its notation plan through the selected native software adapter. Audiveris remains
an optional auxiliary route.

## Fixed acceptance checkpoints

The checkpoints for this release are fixed and are not estimates of recognition
accuracy. Future features do not change this release's denominator.

| Checkpoint | Acceptance | State |
| --- | --- | --- |
| 64% | Source preparation, base notation and standard instruments | Completed in prior commits |
| 73% | Exact document identity before live edits | Completed, CI passed |
| 82% | Special notation and real unpitched percussion | Passed native-file and audio checks |
| 91% | MCP creation, editing and saving | Passed official extension host and MCP stdio call |
| Release checklist completion: 100% | Native orchestral regression, installed-package checks and release | Acceptance passed for the defined v0.1 checklist |

## What the delivered route does

`musescore_build_score` creates the scaffold and executes a complete Agent plan
without a running GUI/plugin. `musescore_apply_plan` edits an explicitly bound
file. Both use MuseScore's official extension host and a matching per-run receipt.
Failed batches never publish a partial copy or replace an existing output.
The optional live WebSocket backend remains available for already-open documents.

Tests cover notes/chords, voices, rests, tuplets, ties/slurs, grace notes and order,
dynamics, lyrics/text, tempo units, keys, layout, standard templates and percussion.
The local orchestral source is retained only on the owner's computer; it is not
included in the repository or release. The public executable plan uses original
demo music. Runtime evidence is recorded in `tests/LIVE_EDITOR_RESULTS.md`.

The verified platform is macOS / MuseScore Studio 4.7.4. Windows/Linux extension
locations are provided but have not had a real application acceptance run.

## Capabilities still outside this release

Arbitrary MuseSound/VST selection, playback changes triggered solely by technique
text, cross-staff slurs, two-chord tremolos, and additional software backends
remain extension points. Native MuseScore and Sibelius delivery are available
through their respective adapters. The workflow preserves the Agent's supplied
content; it does not claim a measured recognition percentage or identical layout
for arbitrary scores. Missing commands return errors instead of silently
discarding notation.

## First-release verification

Local tests: 178 passed. A clean checkout installed in a new virtual environment
passed 177 tests; one private-source test was skipped because that source is not
distributed. GitHub CI passed for commit `6644076`; release documentation and
connection cleanup are checked again by the release commit's CI.

Actual MCP execution and the native-file orchestral checks above establish the
agreed first-release acceptance. The release tag records its delivered version;
The checklist completion refers only to this defined release checklist, not to
universal recognition accuracy or support for every input.

## v0.2.0 — sheet music and audio to editable music

This upgrade keeps the five agreed work packages fixed:

1. Engine routing/provisioning: Basic Pitch ONNX, Transkun, YourMT3 and optional
   Demucs, isolated runtimes, cached weights, actual inference, timeout cleanup
   and automatic fallback. The Agent chooses tools internally.
2. Shared music plan: source provenance, original performance seconds,
   sounding MIDI pitches, track identities, tempo/meter maps, controls and bends,
   plus a separate detailed native notation representation.
3. Selected outputs: MSCZ, MusicXML, PDF and multitrack MIDI. Audio notation has
   explicit rests, overlapping voices and cross-bar ties. Quantization is a
   provisional notation projection; original MIDI timing stays intact.
4. ACE adapter: official CLI, stable clip/track resolution, actual AI or plugin
   sources, native project save/reopen, note and sound readback, generic MIDI
   expression verification, previous-project preservation and session locking.
5. Shared Skill/CLI/MCP functions, clean installed-package acceptance and
   synchronized English/Chinese documentation.

Actual acceptance is recorded in
[delivery-validation.json](demos/audio-to-score/delivery-validation.json).
The recognized mixed-audio candidate's 54 events reached all five requested
formats; ACE's saved project read back 54 pitches/times and velocities. A
separate generic MIDI test verified CC and pitch bend after reopening. Detailed
native Agent notation also reached all five formats, including actual AI violin
and trombone. A seven-note AI violin/clarinet fixture retained tempo and meter
changes. Existing user music projects were not used as test scratch files.

Measured transcription results are separate in
[engine-validation.json](demos/audio-to-score/engine-validation.json).
These are short controlled/rendered inputs. They do not establish a universal
accuracy percentage for dense orchestral recordings. AI Instrument expression
uses its native parameter model; MIDI velocities/CC are not silently claimed
as AI parameter edits. Unmapped expression is retained in private performance
MIDI and reported in the receipt. Other DAW adapters remain later extensions.

One live ACE request hung inside a third-party BBC plugin's unload path. Saved
work was preserved and ACE recovered for acceptance. Application restart is not
an adapter dependency. CLI import rows omitted track coordinates, and AI loading
changed clip UUIDs; the adapter resolves actual state instead of assuming the
help examples' shape. Local verification passed 221 tests. The staged release
installed into a clean virtual environment passed 220 tests, with one private-source
test skipped because its source is not distributed. The Skill validator and diff
checks passed. GitHub CI records the published commit's verification.

## v0.3.0 and v0.4.x — native Sibelius, brand migration, packaging

v0.3.0 added native Sibelius delivery through the official Sibelius Connect
WebSocket and the bundled ManuScript bridge; the adapter opens the MusicXML
projection and publishes `.sib` only after Sibelius reports a successful save and
the file exists. v0.4.0 renamed the product and canonical Python package to
Yuezheng while keeping the `scorebridge` import path, CLI alias, plan schema and
legacy environment variables. v0.4.1–v0.4.27 covered MusicXML compatibility,
release metadata checks and cross-platform test stability. Capability history is
recorded in [CHANGELOG.md](CHANGELOG.md).

## Current verification — 2026-10-20

Environment: macOS arm64, MuseScore Studio 4.7.4, Python 3.11.16, ffmpeg present.

| Check | Result |
| --- | --- |
| `python scripts/run_package_tests.py -q` | 257 passed |
| `yuezheng doctor` | pass (Pillow, PyMuPDF, MuseScore, Audiveris, MCP, WebSocket) |
| `build-score examples/native-plan.json` | published MSCZ, 15/15 receipted steps, 7.2 s |
| `deliver-music examples/music-plan.json --formats mscz musicxml pdf midi` | four files, 5.9 s |
| `deliver-music examples/music-plan.json --formats wav mp3` | 9.5 s stereo 44.1 kHz WAV + MP3, rendered in 9.0 s |
| `deliver-music ... --formats jianpu` | `.jly` accepted by jianpu-ly and a text copy, 14.9 s from a native plan |

These are software-execution checks against bundled example plans. They add no
recognition-accuracy score and are not a new acceptance denominator.

Not re-verified in this environment: ACE Studio (installed, External Agent Access
disabled), Sibelius (not installed) and the optional audio engines (not
provisioned). Those adapters remain covered by unit tests only.

## Platform gate

The Windows package job is a required gate again. Package tests are decided by
a recorded pytest session result plus a JUnit report rather than the pytest
process exit status, because the hosted Windows runner has returned exit 1 after
a clean summary and has delivered a spurious console interrupt mid-suite.
Failures, errors, empty reports, missing records and interrupted sessions still
fail the run.

