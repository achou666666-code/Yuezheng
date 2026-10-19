import argparse, json, sys
from pathlib import Path
from yuezheng.doctor import diagnose
from yuezheng.score_ir import load_score
from yuezheng.musicxml import compile_musicxml
from yuezheng.validation import validate_score

def main():
    parser=argparse.ArgumentParser(prog=Path(sys.argv[0]).name, description="Yuezheng: Agent-led music production assistant for editable music projects")
    sub=parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("music-plan", help="Wrap Agent notation or audio events in one music construction plan")
    plan.add_argument("input"); plan.add_argument("--output", required=True)
    plan.add_argument("--title", default="")
    plan.add_argument("--bpm", type=float, default=None)
    plan.add_argument("--numerator", type=int, default=4)
    plan.add_argument("--denominator", type=int, default=4)
    deliver = sub.add_parser("deliver-music", help="Deliver only requested notation, MIDI or native DAW files")
    deliver.add_argument("input"); deliver.add_argument("--output", required=True)
    deliver.add_argument("--formats", nargs="+", choices=["mscz", "sib", "musicxml", "pdf", "midi", "ace", "wav", "mp3", "jianpu"], default=["mscz"])
    deliver.add_argument("--executable", default="")
    deliver.add_argument("--ace-cli", default="")
    deliver.add_argument("--sibelius-url", default="")
    ace = sub.add_parser("ace-status", help="Read-only official ACE Studio CLI connection check")
    ace.add_argument("--ace-cli", default="")
    sibelius = sub.add_parser("sibelius-status", help="Inspect the local Sibelius Connect endpoint and bridge plugin")
    sibelius.add_argument("--url", default="")
    install_sibelius = sub.add_parser("sibelius-install-plugin", help="Install the bundled Sibelius Connect bridge")
    install_sibelius.add_argument("--destination", default="")
    sub.add_parser("doctor")
    backends = sub.add_parser("audio-backends", help="Inspect optional isolated audio engines")
    backends.add_argument("--cache-dir", default="")
    install = sub.add_parser("audio-install", help="Install one optional audio engine in isolation")
    install.add_argument("engine", choices=["basic_pitch", "transkun", "yourmt3", "demucs"])
    install.add_argument("--cache-dir", default="")
    transcribe = sub.add_parser("transcribe-audio", help="Run audio transcription with automatic engine fallback")
    transcribe.add_argument("input"); transcribe.add_argument("--output", required=True)
    transcribe.add_argument("--hint", choices=["auto", "solo", "piano", "mixed"], default="auto")
    transcribe.add_argument("--engine", choices=["auto", "basic_pitch", "transkun", "yourmt3"], default="auto")
    transcribe.add_argument("--cache-dir", default="")
    transcribe.add_argument("--no-install", action="store_true")
    transcribe.add_argument("--no-fallback", action="store_true")
    transcribe.add_argument("--combine", action="store_true", help="Keep two engine candidates for Agent resolution")
    transcribe.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    transcribe.add_argument("--timeout", type=int, default=1800)
    separate = sub.add_parser("separate-audio", help="Create aligned audio stems for optional transcription assistance")
    separate.add_argument("input"); separate.add_argument("--output", required=True)
    separate.add_argument("--cache-dir", default="")
    separate.add_argument("--no-install", action="store_true")
    separate.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    separate.add_argument("--timeout", type=int, default=1800)
    prepare=sub.add_parser("prepare"); prepare.add_argument("input"); prepare.add_argument("--output", required=True)
    prepare.add_argument("--dpi", type=int, default=450)
    audio = sub.add_parser("prepare-audio", help="Prepare audio evidence for the calling Agent")
    audio.add_argument("input"); audio.add_argument("--output", required=True)
    audio.add_argument("--segment-seconds", type=float, default=8)
    audio.add_argument("--overlap-seconds", type=float, default=1)
    audio.add_argument("--midi-low", type=int, default=24)
    audio.add_argument("--midi-high", type=int, default=108)
    evaluate = sub.add_parser("evaluate-audio", help="Measure Agent events against independent reference events")
    evaluate.add_argument("reference"); evaluate.add_argument("prediction")
    evaluate.add_argument("--output", default="")
    evaluate.add_argument("--onset-tolerance", type=float, default=.05)
    evaluate.add_argument("--offset-tolerance", type=float, default=.1)
    sub.add_parser("editor-status")
    sub.add_parser("editor-connect")
    audit = sub.add_parser("instrument-audit")
    audit.add_argument("input")
    open_score = sub.add_parser("open-score")
    open_score.add_argument("input")
    open_score.add_argument("--executable", default="")
    bind_score = sub.add_parser("bind-score")
    bind_score.add_argument("input")
    bind_score.add_argument("--target", required=True)
    bind_score.add_argument("--executable", default="")
    bind_score.add_argument("--url", default="")
    create_score = sub.add_parser("create-score")
    create_score.add_argument("spec")
    create_score.add_argument("--output", required=True)
    create_score.add_argument("--executable", default="")
    create_score.add_argument("--open", action="store_true", dest="open_editor")
    execute=sub.add_parser("execute-plan"); execute.add_argument("input"); execute.add_argument("--url", default="")
    apply=sub.add_parser("apply-plan"); apply.add_argument("plan"); apply.add_argument("--input", required=True); apply.add_argument("--output", default=""); apply.add_argument("--executable", default="")
    build=sub.add_parser("build-score"); build.add_argument("plan"); build.add_argument("--output", required=True); build.add_argument("--executable", default="")
    validate=sub.add_parser("validate"); validate.add_argument("input")
    compile_cmd=sub.add_parser("compile"); compile_cmd.add_argument("input"); compile_cmd.add_argument("--output", required=True)
    args=parser.parse_args()
    if args.command in {"music-plan", "deliver-music", "ace-status", "sibelius-status", "sibelius-install-plugin"}:
        try:
            if args.command == "music-plan":
                from yuezheng.music_plan import make_music_plan
                result = make_music_plan(args.input, args.output, args.title, args.bpm, args.numerator, args.denominator)
            elif args.command == "deliver-music":
                from yuezheng.music_delivery import deliver_music_plan
                result = deliver_music_plan(args.input, args.output, args.formats, args.executable, args.ace_cli, args.sibelius_url)
            elif args.command == "ace-status":
                from yuezheng.ace.adapter import ACEStudioAdapter
                result = ACEStudioAdapter(args.ace_cli).status()
            elif args.command == "sibelius-status":
                from yuezheng.sibelius import sibelius_status
                result = sibelius_status(args.url)
            else:
                from yuezheng.sibelius import install_sibelius_plugin
                result = install_sibelius_plugin(args.destination)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            result = {"status": "error", "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.get("status") in {"planned", "delivered", "connected", "available", "installed"} else 1)
    if args.command in {"audio-backends", "audio-install", "transcribe-audio", "separate-audio"}:
        from .audio.backends import audio_backends, install_backend
        from .audio.transcribe import transcribe_audio, separate_audio
        if args.command == "audio-backends":
            report = audio_backends(args.cache_dir)
        elif args.command == "audio-install":
            report = install_backend(args.engine, args.cache_dir)
        elif args.command == "transcribe-audio":
            report = transcribe_audio(args.input, args.output, args.hint, args.engine, args.cache_dir,
                                      not args.no_install, not args.no_fallback, args.combine, args.device, args.timeout)
        else:
            report = separate_audio(args.input, args.output, args.cache_dir,
                                    not args.no_install, args.device, args.timeout)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(1 if report.get("status") in {"error", "busy"} else 0)
    if args.command in {"prepare-audio", "evaluate-audio"}:
        from .audio import prepare_audio, evaluate_audio_events
        try:
            if args.command == "prepare-audio":
                report = prepare_audio(args.input, args.output, args.segment_seconds, args.overlap_seconds, args.midi_low, args.midi_high)
            else:
                report = evaluate_audio_events(args.reference, args.prediction, args.onset_tolerance, args.offset_tolerance)
                if args.output:
                    destination = Path(args.output)
                    if destination.resolve() in {Path(args.reference).resolve(), Path(args.prediction).resolve()}:
                        raise ValueError("Report must not overwrite reference or prediction")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except (ValueError, OSError) as exc:
            report = {"status": "error", "error": str(exc)}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(1 if report.get("status") == "error" else 0)
    if args.command in {"apply-plan", "build-score"}:
        from .musescore.extension import execute_extension_plan_file
        from .musescore.build import build_agent_score
        try:
            if args.command == "apply-plan":
                report = execute_extension_plan_file(args.plan, args.input, args.output, args.executable)
            else:
                plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
                report = build_agent_score(plan.get("score"), plan.get("steps"), args.output, args.executable)
        except (ValueError, OSError) as exc:
            report = {"status":"error", "error":str(exc)}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report.get("status") in {"executed","pass"} else 1)
    if args.command == "editor-connect":
        from .musescore.connect import connect_editor
        report = connect_editor()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report['status'] == 'connected' else 1)
    if args.command == "doctor":
        report = diagnose(); print(json.dumps(report, ensure_ascii=False, indent=2)); raise SystemExit(0 if report["status"] == "pass" else 1)
    if args.command == "prepare":
        from .agent_workflow import prepare_agent_job
        print(json.dumps(prepare_agent_job(args.input, args.output, args.dpi), ensure_ascii=False, indent=2)); return
    if args.command == "editor-status":
        from .musescore import MuseScoreWebSocketBackend
        report = MuseScoreWebSocketBackend().status()
        print(json.dumps(report, ensure_ascii=False, indent=2)); raise SystemExit(0 if report["available"] else 1)
    if args.command == "instrument-audit":
        from .instrument_audit import audit_instruments
        report = audit_instruments(load_score(args.input))
        print(json.dumps(report, ensure_ascii=False, indent=2)); raise SystemExit(0 if report["status"] == "pass" else 1)
    if args.command == "open-score":
        from .musescore import MuseScoreAdapter, MuseScoreError
        try:
            report = MuseScoreAdapter(executable=args.executable or None).open_score(args.input)
        except MuseScoreError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
            raise SystemExit(1)
        print(json.dumps(report, ensure_ascii=False, indent=2)); return
    if args.command == "bind-score":
        from .musescore import (MuseScoreAdapter, MuseScoreWebSocketBackend,
                                bind_editor_score)
        try:
            target_payload = json.loads(Path(args.target).read_text(encoding="utf-8"))
            target = target_payload.get("target", target_payload)
            report = bind_editor_score(
                args.input, target,
                adapter=MuseScoreAdapter(executable=args.executable or None),
                bridge=MuseScoreWebSocketBackend(url=args.url or None),
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            report = {"status": "error", "error": str(exc)}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report.get("status") == "bound" else 1)
    if args.command == "create-score":
        from .musescore import create_seed_score
        try:
            specification = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "error", "stage": "specification", "error": str(exc)}, ensure_ascii=False, indent=2))
            raise SystemExit(1)
        report = create_seed_score(specification, args.output, args.executable, args.open_editor)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["status"] == "pass" else 1)
    if args.command == "execute-plan":
        from .agent_workflow import execute_plan_file
        report = execute_plan_file(args.input, args.url)
        print(json.dumps(report, ensure_ascii=False, indent=2)); raise SystemExit(0 if report["status"] == "executed" else 1)
    score=load_score(args.input); report=validate_score(score)
    if args.command=="validate": print(json.dumps(report, ensure_ascii=False, indent=2)); raise SystemExit(0 if report["status"]=="pass" else 1)
    if report["status"]!="pass": print(json.dumps(report, ensure_ascii=False, indent=2)); raise SystemExit(1)
    output=compile_musicxml(score,args.output); print(json.dumps({"status":"pass","output":str(output.resolve())},ensure_ascii=False))
