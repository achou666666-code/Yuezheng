# Changelog

Yuezheng releases from v0.1.0 onward. The v0.4 patch tags were cut per commit,
so this file records delivered capability and the platform state behind it
rather than repeating thirty near-identical patch entries. Detailed acceptance
evidence lives in [DELIVERY.md](DELIVERY.md) and the `demos/` records.

## Unreleased

### Added

- Audio preview delivery: `deliver-music --formats wav mp3` renders a listening
  copy from the same notated MSCZ through MuseScore. It is an aid for checking a
  result, not a new performance and not a sound-quality guarantee.
- Jianpu (numbered notation) delivery: `deliver-music --formats jianpu` writes a
  jianpu-ly input (`.jly`) and a compact reading copy (`.txt`) from the shared
  notation grid, with an explicit warning when a key signature is missing, a
  percussion track is omitted or a meter does not use a quarter-note beat.

### Changed

- Package tests are decided by a recorded pytest session result plus a JUnit
  report, not by the pytest process exit status. The hosted Windows runner has
  returned exit 1 after a clean summary; failures, errors, empty reports,
  missing records and interrupted sessions still fail.
- A console-interrupt guard keeps the same Windows runner from terminating the
  run mid-suite, and an interrupted run can no longer pass on a truncated
  report.
- The Windows package job is a required gate again: the `continue-on-error`
  flag, the two `--ignore` arguments and the diagnostic job whose tests were all
  skipped on Windows are gone. All three platforms run the full suite and upload
  their report as an artifact.

## v0.4.28 — 2026-10-12

Final patch of the Windows CI investigation. The Windows package job was made
non-blocking and documented as diagnostic evidence, with two test modules
excluded and a separate diagnostic job added.

## v0.4.1 – v0.4.27 — 2026-10-11

Packaging, MusicXML compatibility and cross-platform CI. Made Yuezheng the
canonical Python package while keeping the `scorebridge` import path and CLI
alias, hardened MusicXML parsing for third-party shapes, checked wheel metadata
and release-tag versions in CI, and stabilised Windows test processes for the
MCP, WebSocket, editor and plugin harnesses.

## v0.4.0 — 2026-10-11

Public brand migration. Yuezheng became the product and package name, with
`scorebridge` retained as a compatibility alias for imports, the CLI, the plan
schema and existing environment variables.

## v0.3.0 — 2026-10-10

Native Sibelius delivery. A bundled ManuScript bridge is driven through the
official local Sibelius Connect WebSocket; the adapter opens the MusicXML
projection and publishes `.sib` only after Sibelius reports a successful save
and the file exists.

## v0.2.0 — 2026-10-04

Agent-led audio transcription and editable delivery:

- Optional Basic Pitch, Transkun and YourMT3 engines in isolated runtimes, with
  automatic fallback, cached jobs and optional Demucs stems.
- The shared music plan: source provenance, original performance timing,
  tempo/meter maps, track identities, controls and bends, plus a separate native
  notation representation.
- Selected outputs only: MSCZ, MusicXML, PDF, multitrack MIDI and ACE projects.
- ACE Studio adapter through the official CLI: separate project, actual sound
  sources, save, reopen and readback, previous project preserved.
- Audio evidence preparation and held-out event benchmarking.

## v0.1.0 — 2026-10-02

First release. Agent-authored notation executed through MuseScore's official
extension host without computer use: a private scaffold, ordered notation
commands, a per-run execution receipt in the saved MSCZ, and publication only
when the whole batch succeeds. Live WebSocket editing, optional Audiveris OMR,
source preparation and instrument auditing remain available.
