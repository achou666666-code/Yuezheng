# Audio transcription and editable delivery

[English](README.md) | [简体中文](README.zh-CN.md)

The Agent chooses native audio understanding or optional transcription engines,
interprets the candidates and writes the shared music plan. Software adapters
write editable music. ACE's own audio-to-MIDI recognizer is not used.

Implemented: decoding/evidence, isolated engines, automatic fallback, optional
Demucs stems, source-linked plans, selected MSCZ/MusicXML/PDF/multitrack MIDI,
and an official-CLI ACE project adapter with actual sound bindings and readback.

## Actual model measurements

[engine-validation.json](engine-validation.json) freezes predictions, held-out
reference events, hashes, seeds, runtime versions and measured results. Onset
matching tolerance is 50 ms; pitch identity must match. Offset matching uses
100 ms. The test inputs are short original harmonic controls and MuseScore
sample renders, not microphone recordings or commercial music.

| Input | Engine | Pitch/onset matched | Pitch/onset F1 | With-offset F1 | Drum matched |
| --- | --- | --- | --- | --- | --- |
| Harmonic melody | Basic Pitch | 12/12 | 1.000 | 1.000 | — |
| Harmonic polyphony | Transkun | 13/24 | 0.703 | 0.432 | — |
| Harmonic mix | YourMT3 | 25/32 | 0.877 | 0.807 | 17/24 |
| Sampled melody | Basic Pitch | 10/12 | 0.800 | 0.160 | — |
| Sampled piano | Transkun | 24/24 | 1.000 | 0.375 | — |
| Sampled piano/low piano/standard drum kit | YourMT3 | 31/32 | 0.969 | 0.875 | 22/24 |
| Random rests and note lengths | Basic Pitch | 9/9 | 1.000 | 0.889 | — |

These are measured samples, not a universal product accuracy percentage. Piano
onset/pitch quality does not imply exact release timing. Instrument-family and
orchestral-player separation have not been independently accepted. An earlier
mixed render used a generic Percussion patch (program 48); the corrected fixture
was audited as Drumset/program 0 before scoring its percussion.

All four optional engines ran on macOS arm64 / Python 3.11 / CPU. This machine's
runtime footprints were approximately Basic Pitch 515 MiB, Transkun 949 MiB,
YourMT3 1077 MiB and Demucs 818 MiB, with about 620 MiB of downloaded weights.
These are development-machine measurements. Users install only selected engines;
model environments and weights are not bundled into the core.

## Reproduce

```bash
python -m pip install -e '.[audio]'
python scripts/make_audio_benchmark.py --output work/controls --seed 2026100407
# A sampled fixture needs MuseScore and ffmpeg:
python scripts/make_audio_benchmark.py --output work/sampled --seed 2026100407 --musescore /path/to/mscore
yuezheng transcribe-audio work/sampled/inputs/mixed.wav --output work/inference --hint mixed
# Freeze events before opening the answer:
yuezheng evaluate-audio work/sampled/answers/mixed.json work/inference/transcription-JOB/events.json
yuezheng music-plan work/inference/transcription-JOB/events.json --output work/plan.json --bpm 120
yuezheng deliver-music work/plan.json --output final --formats mscz musicxml pdf midi ace
```

Here 120 BPM is the authored fixture tempo, not a tempo-recognition score. Agent
requests on arbitrary sources must determine musical timing internally. A direct
engine result is a candidate; using its data without musical interpretation is
not equivalent to a finished high-precision transcription.

## Acceptance scope

The actual mixed-audio candidate produced 54 events. The same plan generated
MSCZ, MusicXML, PDF, multitrack MIDI and a saved/reopened two-track ACE project.
ACE read back all 54 pitches/times and MIDI velocities, with mounted piano and
channel-10 kit. A separate seven-note test mounted AI violin and clarinet,
retained tempo/meter changes and reopened correctly. AI Instrument clips do not
use MIDI CC/velocity; unmapped expression is explicit, while plugin/MIDI tracks
retain those controls. See [music plan reference](../../skills/yuezheng/references/music-plan.md).

[validation.json](validation.json) preserves the earlier Agent spectral-image
self-evaluation as a historical record; it is separate from model results.
The fixed upgrade comprises five packages: engine routing/provisioning, shared
plan, selected outputs, first DAW adapter, and unified Skill/CLI/MCP acceptance.
Future adapters and larger real-recording benchmarks extend subsequent releases.
