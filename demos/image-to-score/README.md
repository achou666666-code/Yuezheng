# Image to score demo

The default route uses the calling multimodal Agent to read the source image,
then MuseScore MCP to execute its notation plan and save editable MSCZ.
The Agent supplies the musical content; Yuezheng handles software execution.

Run from the repository root:

```bash
.venv/bin/yuezheng prepare public-image.png --output /tmp/yuezheng-image
```

The Agent reads the original and prepared pages, establishes page order, and
records instrument templates, printed pitches/keys, rhythm, text and notation in
a plan containing `score` and `steps`. It then calls
`musescore_build_score(specification, steps, output_path)`, or:

```bash
.venv/bin/yuezheng build-score PLAN.json --output /tmp/image-score.mscz
```

The bundled `public-samples/twinkle-twinkle-cc0.png` can be used as an image input.
`examples/native-plan.json` is a separate original-music tool smoke test; it is
not a transcription of that image. To test software execution alone:

```bash
.venv/bin/yuezheng build-score examples/native-plan.json --output /tmp/native-demo.mscz
```

Video walkthroughs will be added here after recording. Keep source permissions
and image attribution with any public demonstration.

## Optional historical OMR smoke tests

`output/twinkle-run/` records an earlier Audiveris experiment, including source
evidence, MusicXML and Score IR. It is not the default Agent-led workflow.
The optional `score_transcribe(..., mode="omr")` route remains available for
experimentation; see the repository README.
