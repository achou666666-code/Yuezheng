# Agent-led audio transcription

The calling Agent owns the task and musical interpretation. Assess host audio
input and tool availability internally; the user does not need to ask whether
this Agent can hear, choose a model, or approve individual notes. Use native audio
recognition when genuinely available and suitable, otherwise invoke an optional
transcription engine. Editor software receives the resulting music plan.

## Engine tools

```bash
yuezheng audio-backends
yuezheng transcribe-audio recording.wav --output work/audio --hint mixed
# Only when separation helps:
yuezheng separate-audio recording.wav --output work/stems
```

MCP equivalents: `audio_backends`, `audio_transcribe`, `audio_separate`.
The hint comes from the Agent's interpretation of the task/source: `piano` prefers
Transkun, `solo` prefers Basic Pitch, and `mixed`/`auto` prefers YourMT3. Failure
switches to the next engine. A pitched-only fallback on a mixture is a draft;
it cannot establish drum or instrument identities. Repair the failed runtime or
use stems and appropriate engines rather than treating the fallback as complete.

`--combine` keeps two candidates for source-based Agent resolution. It does not
append both note lists or accept agreement as proof. Apply combination only when
useful; retain primary events and the disagreements while resolving uncertain
segments. No full second transcription pass or human note-review gate is required.

Python 3.10/3.11 runtimes are installed in separate optional environments, not in
the Agent/core Python. Models are loaded in short-lived workers and released on
exit. Packages are pinned; YourMT3 downloads one checksum-verified checkpoint
rather than cloning the Space's entire Git LFS repository. Models are not bundled
with Yuezheng. Set `SCOREBRIDGE_AUDIO_HOME` or `--cache-dir` to choose cache
storage. To provision only one engine, use `yuezheng audio-install ENGINE`.
A pre-existing runtime can be supplied with
`SCOREBRIDGE_AUDIO_BASIC_PITCH_PYTHON`, `SCOREBRIDGE_AUDIO_TRANSKUN_PYTHON`,
`SCOREBRIDGE_AUDIO_YOURMT3_PYTHON`, or `SCOREBRIDGE_AUDIO_DEMUCS_PYTHON`.
These external runtimes are inspected but never installed over.

`audio-backends` distinguishes imports from actual inference verification.
Neither proves accuracy on a new recording. A genuine dependency/permission
failure should be repaired or reported specifically, not replaced by invented
notes or a generic claim that the Agent cannot do the task.

## Source and event evidence

`audio_transcribe` retains original audio, decoded WAV, attempts, model MIDI and
source-linked event candidates in a private job. Identical inputs/options reuse
verified artifacts; failed jobs can resume. Events use sounding MIDI pitches and
absolute source seconds. They retain velocity, control changes and pitch bends
when supplied by the engine. Printed instrument transposition belongs in the
notation plan, not in these sounding pitches.

Basic Pitch does not identify instruments. Its default MIDI program 0 is not
recognized piano. Resolve track sound identity using the source/task or an
instrument-capable engine before native score/project delivery. YourMT3 provides
model-estimated GM families; same-family players are not automatically separate
orchestral parts. Do not claim arbitrary dynamics/techniques were recognized
merely because the model emitted a fixed default velocity.

Separation produces aligned **audio stems**, not notes. Demucs's drum/bass/vocal/
other groups do not isolate every orchestral instrument. Keep the original mix,
transcribe melodic stems with a suitable engine, and use a drum-capable engine
for percussion. Never run Basic Pitch on a drum stem as a drum recognizer.

For difficult local judgments, `audio_prepare` / `yuezheng prepare-audio`
provides source-linked waveform/STFT images. These are diagnostic evidence;
without native audio input, do not claim to have heard the file. Preserve rests,
ornaments and genuine polyphony; harmonics and reverb tails are not extra notes.

## Evaluation and delivery

`audio_evaluate` / `yuezheng evaluate-audio` compares frozen predictions with
held-out reference events. Score pitch/onset, release timing, drum categories and
supplied instrument identity separately. References are development answers,
never recognition input. Samples rendered with an instrument must have their
actual instrument/routing checked, not just a matching part name.

Use the existing MuseScore plan tools for Agent-authored notation. Engine MIDI is
candidate performance data, not a finished engraved score or verified DAW project.
Use `music_plan` then `music_deliver` for selected notation, multitrack MIDI or
native ACE delivery. Read [music-plan.md](music-plan.md) for timing, instrument
bindings, automatic notation and software-specific expression. Preserve the best
complete draft and source uncertainties for editing;
do not turn uncertainty into a mandatory human checkpoint.
