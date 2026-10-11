# Yuezheng

[English](README.md) | [简体中文](README.zh-CN.md)

**An Agent-led music production assistant for turning musical ideas and source material into editable projects.**
Yuezheng combines a Skill, reusable programs, and CLI/MCP interfaces. The Agent
interprets a natural-language request, understands sheet music, images, PDFs or
audio, organizes the musical material, and uses the requested output/software
workflow. Image/audio transcription is the first core workflow; notation and
DAW adapters are built so the assistant can grow into broader music production
tasks. MuseScore and Sibelius are current notation adapters, and ACE Studio is
the first native DAW adapter; the product is not tied to one editor.

## Workflow

```text
Request + PDF / images / audio
→ Agent assesses input, available capabilities and task
→ direct recognition or selected optional transcription/separation tools
→ internal music / notation plan
→ file generation or music-software adapter
→ editable user deliverable
```

## Available on main

| Capability | Current implementation |
| --- | --- |
| PDF and image input | Source preparation, page mapping, original/enhanced evidence; Agent reads the score |
| Editable notation | Agent plans create/edit/save native MSCZ through MuseScore, or native SIB through Sibelius Connect |
| Audio transcription | Optional Basic Pitch, Transkun and YourMT3 engines; isolated environments, fallback and cached jobs |
| Audio assistance | Optional Demucs stems, waveform/spectral evidence and candidate combination |
| Shared plan/output | Original performance plus notation; selected MSCZ, MusicXML, PDF and multitrack MIDI |
| Native DAW project | Official ACE CLI: note import, actual AI/plugin sound bindings, save/reopen/readback |
| Evaluation | Separate pitch/onset, release timing, drum and instrument-identity measurements |

Recognition remains Agent-led. Optional engines provide source-linked candidates;
Agent judgments and detailed notation use the shared plan. File generation and
software adapters carry out that plan. See [music plan and output scope](skills/yuezheng/references/music-plan.md)
and [measured development results](demos/audio-to-score/README.md).

## Install and connect an Agent

```bash
git clone https://github.com/achou666666-code/Yuezheng.git
cd Yuezheng
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[mcp,image,audio,websocket]'
.venv/bin/yuezheng doctor
```

On Windows use `.venv\Scripts\python.exe` and `.venv\Scripts\yuezheng.exe`.
Install `skills/yuezheng` in the Agent's skill directory. Agents with a terminal
can use CLI commands; for MCP, configure the environment's Python executable with
the absolute path to `mcp_server/server.py`:

```bash
.venv/bin/python mcp_server/server.py
```

Native MSCZ needs MuseScore Studio with `--extension` support, verified on macOS
Studio 4.7.4. Windows/Linux extension paths are provided but not application-tested.
Audio engines need a separate Python 3.10/3.11; if none exists and uv is available,
Yuezheng provisions one privately. Compressed audio needs ffmpeg.
Optional dependencies and model weights are installed/cached only when selected,
not bundled into the core. Pre-existing external model environments can be reused.

## PDF/images to notation

The Agent prepares the source, reads it and supplies notation steps:

```bash
yuezheng prepare score.pdf --output work/source
yuezheng build-score work/plan.json --output score.mscz
```

MCP equivalents: `score_transcribe` and `musescore_build_score`.
[examples/native-plan.json](examples/native-plan.json) shows original demo music.
For edits use `musescore_apply_plan` or `yuezheng apply-plan`, preserving the
returned exact target. The file backend executes in a private copy and checks a
matching receipt before publishing. See [notation commands and supported scope](skills/yuezheng/references/editor-plan.md).
Audiveris remains opt-in assistance. Original images and page mappings are retained.

## Audio to musical events

```bash
yuezheng audio-backends
yuezheng transcribe-audio recording.wav --output work/audio --hint mixed
# When useful:
yuezheng separate-audio recording.wav --output work/stems
```

MCP equivalents: `audio_backends`, `audio_transcribe`, `audio_separate`.
The Agent chooses hints and tools internally; the user need not select models.
`--hint piano` prefers Transkun; `solo` prefers Basic Pitch; `mixed`/`auto` prefers
YourMT3. Failed inference switches engines. `--combine` retains two candidates for
Agent resolution rather than doubling notes. Identical jobs reuse verified files;
failed jobs preserve source and attempts for recovery.

For explicit provisioning use `yuezheng audio-install ENGINE`. Set
`SCOREBRIDGE_AUDIO_HOME` or `--cache-dir` for model storage. Import checks and
successful inference are distinguished; neither is an accuracy percentage.
Basic Pitch does not identify instruments: its default piano program must not be
mistaken for recognized piano. Drum stems need a drum-capable transcriber.

## Selected files and native projects

```bash
yuezheng music-plan work/events.json --output work/music-plan.json --bpm 96
yuezheng deliver-music work/music-plan.json --output final --formats mscz
# When requested:
yuezheng deliver-music work/music-plan.json --output final --formats musicxml pdf midi ace sib
```

MCP: `music_plan`, `music_deliver`, `ace_status`, `sibelius_status`, and
`sibelius_create_score`. The Agent supplies musical
context internally; users need not fill a plan. Existing image notation plans
can be wrapped in the same format. Performance MIDI retains original event
times; automatic audio notation uses a provisional grid, separate from that
performance. Detailed notation remains Agent-authored editor commands.

ACE Studio must be running with External Agent Access. The official CLI adapter
creates a separate project, resolves installed sound sources, saves and reads it
back, then restores the previous project. Native project paths come from ACE's
save response. AI instruments use native synthesis parameters; MIDI CC/velocity
are retained/verified on GenericMidi plugin tracks, with unmapped AI expression
reported explicitly. Multi-instrument plugins require an actual preset/state.
See [music plan / ACE reference](skills/yuezheng/references/music-plan.md).

Sibelius delivery uses its official local Sibelius Connect WebSocket and a bundled
ManuScript bridge. Install the bridge with `yuezheng sibelius-install-plugin`,
enable Sibelius Connect on port 1898, and request `sib` in `deliver-music`. The
adapter opens the generated MusicXML and saves the native `.sib` file only after
Sibelius returns a successful save result and the file exists.

## Editor details and development

Optional live MuseScore editing uses the bundled QML/WebSocket plugin:
`bash scripts/install_musescore_plugin.sh`, enable it in MuseScore, then run
`yuezheng editor-status`. The default file route needs no live plugin.
See [editor reference](skills/yuezheng/references/editor-plan.md),
[live validation](tests/LIVE_EDITOR_RESULTS.md), and [delivery record](DELIVERY.md).

The current upgrade implements the five agreed work packages: engine routing,
shared music plan, selected file output, first native DAW adapter and unified
Skill/CLI/MCP acceptance. Further adapters reuse the same music plan. Complex
recording accuracy is measured by input class, not represented as one universal
percentage. English and Chinese project documentation are maintained together.

The public brand and primary commands are now **Yuezheng**. The `scorebridge`
Python import path, CLI alias, internal plan schema and legacy environment names
remain available for existing projects.

```bash
python -m pip install -e '.[test,image,audio,mcp,websocket]'
pytest -q
```
