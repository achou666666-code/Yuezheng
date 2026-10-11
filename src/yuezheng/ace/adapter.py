"""Create a separate ACE project and verify note data and actual sound sources."""
from collections import Counter, defaultdict, deque
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from yuezheng.music_plan import validate_music_plan, seconds_to_quarters


class ACEError(RuntimeError):
    pass


class ACEStudioAdapter:
    def __init__(self, executable=""):
        self.executable = executable or os.environ.get("SCOREBRIDGE_ACE_CLI") or shutil.which("acestudio-cli") or "/Applications/ACE Studio.app/Contents/Helpers/acestudio-cli"

    def call(self, *args, timeout=120):
        try:
            result = subprocess.run([self.executable, "--json", *map(str, args)], capture_output=True, text=True, timeout=timeout)
            if result.returncode:
                raise ACEError((result.stderr or result.stdout)[-3000:])
            data = json.loads(result.stdout)
            if "error" in data:
                raise ACEError(str(data["error"]))
            return data
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise ACEError(str(exc)) from exc

    def status(self):
        try:
            return {"status": "connected", "project": self.call("project", "info"), "executable": self.executable}
        except ACEError as exc:
            return {"status": "unavailable", "error": str(exc), "executable": self.executable}


_AI_TERMS = {40: "Violin", 41: "Viola", 42: "Cello", 43: "Basses (", 56: "Trumpet",
             57: "Trombone", 60: "French Horn", 65: "Saxophone Alto", 66: "Saxophone Tenor",
             67: "Saxophone Baritone", 71: "Clarinet"}


def select_source(track, catalog, binding):
    """Resolve exact configured sounds or a supported acoustic class; never rename piano."""
    requested = binding.get("source_ref")
    if requested:
        matches = [s for s in catalog if s["ref"] == requested]
    else:
        term = _AI_TERMS.get(track.get("gm_program")) if not track.get("is_drum") else None
        matches = [s for s in catalog if term and s.get("kind") == "instrument" and s.get("name", "").startswith(term)
                   and "Vintage" not in s["name"]]
        matches.sort(key=lambda s: (s.get("category") == "String Sections", s["name"]))
        if not matches and (track.get("gm_program") == 0 or track.get("is_drum")):
            # The built-in GM device's factory bank is piano on channel 1,
            # standard kit on channel 10. Other programs need explicit presets.
            matches = [s for s in catalog if s.get("name") == "DLSMusicDevice" and s.get("kind") == "external-instrument"]
    if not matches:
        raise ACEError(f"No resolved sound source for {track.get('name', track['id'])}. Agent must set bindings.ace.{track['id']}.source_ref from the installed catalog, with a preset/state for a multi-instrument plugin.")
    return matches[0]


def _read_notes(adapter, imported):
    notes = []
    for clip in imported:
        info = adapter.call("clip", "get", "--track-index", clip["trackIndex"], "--clip-index", clip.get("clipIndex", 0))
        content = adapter.call("clip", "note-content", "--track-index", clip["trackIndex"], "--clip-index", clip.get("clipIndex", 0))
        offset = info.get("geometry", {}).get("pos", info.get("pos", 0))
        for n in content.get("notes", []):
            notes.append((clip["trackIndex"], n["pitch"], offset + n["pos"], n["dur"]))
    return notes


def _refresh_clips(adapter, clips):
    for clip in clips:
        listed = adapter.call("clip", "list", "--track-uuid", clip["trackUuid"])["clips"]
        if len(listed) != 1:
            raise ACEError("Expected exactly one imported clip on this owned track")
        # Loading an AI instrument converts the MIDI clip and replaces its UUID.
        clip["clipUuid"] = listed[0]["clipUuid"]
        clip["clipIndex"] = 0
        clip["clipType"] = listed[0]["clipType"]


def _write_expression(adapter, plan, active, clips):
    lanes, warnings = [], []
    for track, clip in zip(active, clips):
        content = adapter.call("clip", "note-content", "--track-index", clip["trackIndex"], "--clip-index", clip["clipIndex"])
        pool = defaultdict(deque)
        for note in content["notes"]:
            pool[note["pitch"], note["pos"], note["dur"]].append(note)
        velocities = defaultdict(list)
        for event in plan["performance"]["events"]:
            if event["track"] != track["id"]:
                continue
            start = round(seconds_to_quarters(event["start_seconds"], plan["tempo_map"]) * 480)
            end = round(seconds_to_quarters(event["end_seconds"], plan["tempo_map"]) * 480)
            notes = pool[event["midi_pitch"], start, max(1, end - start)]
            if not notes:
                raise ACEError("Cannot bind expression to the imported note")
            note = notes.popleft()
            velocities[event.get("velocity", 80)].append(note["noteUuid"])
            if event.get("articulation"):
                adapter.call("note", "set-articulation", "--note-uuid", note["noteUuid"], "--articulation", event["articulation"])
        if clip["clipType"].lower() != "genericmidi":
            warnings.append(f"{track['id']}: AI instrument clips use native synthesis parameters. MIDI velocities/CC/bends remain in the private performance MIDI; they are not claimed as native AI expression.")
            continue
        for value, ids in velocities.items():
            adapter.call("midiparam", "set-velocity", "--note-uuid", *ids, "--velocity", value)
        grouped = defaultdict(dict)
        for c in track.get("controls", []):
            grouped[f"cc{c['number']}"][round(seconds_to_quarters(c["seconds"], plan["tempo_map"]) * 480)] = c["value"]
        for b in track.get("pitch_bends", []):
            grouped["pitchbend"][round(seconds_to_quarters(b["seconds"], plan["tempo_map"]) * 480)] = b["value"] + 8192
        for name, points in grouped.items():
            # MIDI holds the previous value until the event. ACE linearly
            # interpolates anchors: put a preceding hold anchor at tick-1.
            default = 8192 if name == "pitchbend" else {"cc7": 100, "cc8": 64, "cc10": 64, "cc11": 127}.get(name, 0)
            anchors, last = {}, default
            for pos, value in sorted(points.items()):
                if pos:
                    anchors.setdefault(0, default)
                    anchors.setdefault(pos - 1, last)
                anchors[pos] = value
                last = value
            expected = [{"pos": p, "value": v} for p, v in sorted(anchors.items())]
            adapter.call("midiparam", "write", "--clip-uuid", clip["clipUuid"], "--lane", name,
                         "--points", json.dumps(expected), "--replace", "lane")
            lanes.append({"track_uuid": clip["trackUuid"], "lane": name, "points": expected})
    return lanes, warnings


def _verify_expression(adapter, plan, active, clips, lanes):
    for track, clip in zip(active, clips):
        if clip["clipType"].lower() != "genericmidi":
            continue
        read = adapter.call("midiparam", "velocity", "--clip-uuid", clip["clipUuid"])
        expected = Counter(e.get("velocity", 80) for e in plan["performance"]["events"] if e["track"] == track["id"])
        if Counter(n["velocity"] for n in read["notes"]) != expected:
            raise ACEError("Saved ACE velocities differ from the performance plan")
    by_track = {c["trackUuid"]: c for c in clips}
    for lane in lanes:
        read = adapter.call("midiparam", "read", "--clip-uuid", by_track[lane["track_uuid"]]["clipUuid"], "--lane", lane["lane"])
        points = [{"pos": p["pos"], "value": p["value"]} for p in read["points"]]
        if points != lane["points"]:
            raise ACEError("Saved ACE controller/pitch-bend lane differs")


def create_ace_project(plan, midi_path, output_path, executable=""):
    """Serialize sessions addressing the same local ACE application."""
    name = hashlib.sha256(ACEStudioAdapter(executable).executable.encode()).hexdigest()[:16]
    owner = os.getuid() if hasattr(os, "getuid") else 0
    lock = Path(tempfile.gettempdir()) / f"scorebridge-ace-{owner}-{name}.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text())
            os.kill(pid, 0)
            return {"status": "busy", "error": "Another ScoreBridge ACE project session is running"}
        except ProcessLookupError:
            lock.unlink(missing_ok=True)
        except (OSError, ValueError):
            return {"status": "busy", "error": "Cannot establish ACE session lock ownership"}
    try:
        with lock.open("x") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        return {"status": "busy", "error": "Another ScoreBridge ACE project session is running"}
    try:
        return _create_ace_project(plan, midi_path, output_path, executable)
    finally:
        lock.unlink(missing_ok=True)


def _create_ace_project(plan, midi_path, output_path, executable=""):
    """Own a new project only. Snapshot dirty work, save/reopen/read back, then restore.

    Missing instruments are resolved before replacing the active project. Host
    errors retain the private MIDI and receipts instead of manufacturing success.
    """
    adapter = ACEStudioAdapter(executable)
    previous = None
    changed = False
    report = {"status": "error", "stage": "ace_project"}
    try:
        validate_music_plan(plan)
        if not plan.get("performance"):
            raise ACEError("ACE adapter needs a performance projection; deliver native notation as MIDI first")
        status = adapter.call("project", "info")
        catalog = adapter.call("sound-source", "list", "--kind", "instrument", "--kind", "external-instrument")["soundSources"]
        key = hashlib.sha256((json.dumps(plan, sort_keys=True) + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                              + str(Path(output_path).resolve())).encode()).hexdigest()
        cache = Path(midi_path).parent / "ace-result.json"
        if cache.is_file():
            stored = json.loads(cache.read_text(encoding="utf-8"))
            saved_path = Path(stored.get("saved_path", ""))
            refs = {s["ref"] for s in catalog}
            if (stored.get("cache_key") == key and saved_path.is_file()
                    and hashlib.sha256(saved_path.read_bytes()).hexdigest() == stored.get("saved_sha256")
                    and all(s["source"]["soundSource"]["ref"] in refs for s in stored.get("sounds", []))):
                return {**stored, "reused": True}
        active = [t for t in plan["performance"]["tracks"] if any(e["track"] == t["id"] for e in plan["performance"]["events"])]
        if not active:
            raise ACEError("Cannot create an empty ACE transcription project")
        bindings = plan.get("bindings", {}).get("ace", {})
        resolved = [(t, select_source(t, catalog, bindings.get(t["id"], {}))) for t in active]
        for track, source in resolved:
            config = bindings.get(track["id"], {})
            factory_gm = source["name"] == "DLSMusicDevice" and (track.get("gm_program") == 0 or track.get("is_drum"))
            if source["kind"] == "external-instrument" and not factory_gm and not any(config.get(k) for k in ("preset", "state_file", "single_program")):
                raise ACEError("A multi-instrument plugin needs a resolved preset/state or explicit single_program binding; loading its name alone does not select this part's sound")
        from yuezheng.music_delivery import write_performance_midi
        write_performance_midi(plan, midi_path)
        previous = adapter.call("project", "dirty")
        if previous.get("dirty") or not previous.get("projectPath"):
            snapshot = Path(midi_path).parent / "previous-project.acep"
            saved = adapter.call("project", "save-as", str(snapshot))
            previous["projectPath"] = saved["savedPath"]
            report["previous_snapshot"] = saved["savedPath"]
        # Never pass --discard-changes. Host refuses a racing unsaved edit.
        changed = True
        adapter.call("project", "new")
        imported = adapter.call("import", "file", "--path", str(Path(midi_path).resolve()), "--pos", "0t",
                                "--split-polyphonic", "false", "--with-tempo", "true", "--with-time-signatures", "true")
        clips = imported.get("clips", [])
        report["import_receipt"] = imported
        if len(clips) != len(active):
            raise ACEError(f"Imported {len(clips)} clips for {len(active)} nonempty tracks")
        locations = {}
        for track in adapter.call("track", "list")["tracks"]:
            if track.get("region") != "arrangement":
                continue
            listed = adapter.call("clip", "list", "--track-index", track["trackIndex"])
            for index, clip in enumerate(listed.get("clips", [])):
                locations[clip["clipUuid"]] = {"trackUuid": track["trackUuid"], "trackIndex": track["trackIndex"],
                                               "clipIndex": clip.get("clipIndex", index)}
        for clip in clips:
            # Locate by the stable imported clip UUID. Import currently returns
            # geometry but no track coordinates; neither names nor order bind it.
            if clip["clipUuid"] not in locations:
                raise ACEError("Imported clip UUID could not be resolved")
            clip.update(locations[clip["clipUuid"]])
        sounds = []
        for (track, source), clip in zip(resolved, clips):
            uuid = clip["trackUuid"]
            config = bindings.get(track["id"], {})
            args = ["sound-source", "load", "--track-uuid", uuid, "--source", source["ref"]]
            if source["kind"] == "external-instrument":
                args += ["--format", config.get("format", "vst3" if "vst3" in source.get("formats", []) else "au")]
            adapter.call(*args)
            if source["kind"] == "external-instrument":
                adapter.call("instrument", "set", "--track-uuid", uuid, "--midi-channel", str(config.get("midi_channel", 10 if track.get("is_drum") else 1)))
                if config.get("preset"):
                    adapter.call("audio-plugin", "apply-preset", "--track-uuid", uuid, "--slot", "instrument", "--preset", config["preset"])
                if config.get("state_file"):
                    adapter.call("audio-plugin", "set-state", "--track-uuid", uuid, "--slot", "instrument", str(Path(config["state_file"]).resolve()))
            mounted = adapter.call("sound-source", "get", "--track-uuid", uuid)
            if not mounted.get("hasSource") or mounted.get("state") not in {"ready", "mounted"} or mounted["soundSource"]["ref"] != source["ref"]:
                raise ACEError("Sound source did not mount as requested")
            sounds.append({"plan_track": track["id"], "track_uuid": uuid, "source": mounted})
        _refresh_clips(adapter, clips)
        lanes, expression_warnings = _write_expression(adapter, plan, active, clips)
        expected = []
        for track, clip in zip(active, clips):
            for e in plan["performance"]["events"]:
                if e["track"] == track["id"]:
                    start = round(seconds_to_quarters(e["start_seconds"], plan["tempo_map"]) * 480)
                    end = round(seconds_to_quarters(e["end_seconds"], plan["tempo_map"]) * 480)
                    expected.append((clip["trackIndex"], e["midi_pitch"], start, max(1, end - start)))
        actual = _read_notes(adapter, clips)
        if Counter(actual) != Counter(expected):
            raise ACEError(f"ACE note readback differs: expected {len(expected)}, read {len(actual)}")
        saved = adapter.call("project", "save-as", str(Path(output_path).resolve()))
        saved_path = saved["savedPath"]
        if not Path(saved_path).is_file():
            raise ACEError("ACE reported save but no native project exists")
        adapter.call("project", "open", saved_path)
        _refresh_clips(adapter, clips)
        reopened = _read_notes(adapter, clips)
        if Counter(reopened) != Counter(expected):
            raise ACEError("Saved ACE project failed note readback")
        for mounted in sounds:
            reread = adapter.call("sound-source", "get", "--track-uuid", mounted["track_uuid"])
            if reread.get("soundSource", {}).get("ref") != mounted["source"]["soundSource"]["ref"] or reread.get("state") not in {"ready", "mounted"}:
                raise ACEError("Saved ACE sound-source binding failed readback")
        _verify_expression(adapter, plan, active, clips, lanes)
        report.update(status="delivered", saved_path=saved_path, note_count=len(actual), sounds=sounds,
                      reopened=True, timing_import={k: imported.get(k) for k in ("tempoImported", "timeSignaturesImported")},
                      expression_lanes_verified=len(lanes), velocities_verified=not expression_warnings,
                      warnings=expression_warnings,
                      playback_scope="Verified mounted sources and editable note data; cloud render or listening quality is not certified")
    except (ACEError, OSError, ValueError, KeyError, TypeError) as exc:
        report["error"] = str(exc)
    finally:
        if changed and previous and previous.get("projectPath"):
            try:
                if adapter.call("project", "dirty").get("dirty"):
                    recovery = adapter.call("project", "save-as", str(Path(midi_path).parent / "ace-recovery.acep"))
                    report["recovery_path"] = recovery["savedPath"]
                adapter.call("project", "open", previous["projectPath"])
                report["previous_project_restored"] = True
            except ACEError as exc:
                report["restore_error"] = str(exc)
                report["status"] = "partial"
    if report.get("status") == "delivered":
        report.update(cache_key=key, saved_sha256=hashlib.sha256(Path(report["saved_path"]).read_bytes()).hexdigest(), reused=False)
        cache.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
