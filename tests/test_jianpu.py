"""Jianpu projection: scale degrees, octaves, durations, parts and validation."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scorebridge.jianpu import write_jianpu
from scorebridge.music_delivery import deliver_music_plan


def make_plan(events, tracks=None, key=0, tempos=None, meters=None, title="Test"):
    """Quarters are seconds here because every test tempo is 60 BPM."""
    tracks = tracks or [{"id": "lead", "name": "Lead", "gm_program": 73}]
    return {
        "schema_version": 1, "kind": "scorebridge_music_plan", "title": title,
        "source": {}, "notation": {"grid_quarters": .25, "key_fifths": key},
        "tempo_map": tempos or [{"seconds": 0, "bpm": 60}],
        "meter_map": meters or [{"quarter": 0, "numerator": 4, "denominator": 4}],
        "performance": {
            "tracks": tracks,
            "events": [
                {"kind": "note", "track": track, "midi_pitch": pitch,
                 "start_seconds": start, "end_seconds": end}
                for track, pitch, start, end in events
            ],
        },
    }


def lines_of(plan, tmp_path, text=False):
    result = write_jianpu(plan, tmp_path / "out.jly", tmp_path / "out.txt")
    return Path(result["text_path" if text else "jly_path"]).read_text().splitlines(), result


def test_simple_melody_uses_scale_degrees(tmp_path):
    lines, result = lines_of(make_plan([("lead", 60, 0, 1), ("lead", 62, 1, 2),
                                        ("lead", 64, 2, 3), ("lead", 65, 3, 4)]), tmp_path)
    assert result["warnings"] == []
    assert "1=C 4/4" in lines
    assert "4=60" in lines
    assert "instrument=Lead" in lines
    assert "1 2 3 4 |" in lines


def test_rests_fill_the_gap(tmp_path):
    lines, _ = lines_of(make_plan([("lead", 60, 0, 1), ("lead", 62, 2, 3),
                                   ("lead", 64, 3, 4)]), tmp_path)
    assert "1 0 2 3 |" in lines


def test_octaves_are_marked_around_the_tonic(tmp_path):
    lines, _ = lines_of(make_plan([("lead", 48, 0, 1), ("lead", 60, 1, 2),
                                   ("lead", 72, 2, 3), ("lead", 84, 3, 4)]), tmp_path)
    assert "1, 1 1' 1'' |" in lines


def test_chord_members_keep_their_own_octave_marks(tmp_path):
    lines, _ = lines_of(make_plan([("lead", 60, 0, 1), ("lead", 64, 0, 1),
                                   ("lead", 67, 0, 1), ("lead", 72, 1, 2),
                                   ("lead", 74, 2, 3), ("lead", 76, 3, 4)]), tmp_path)
    assert "135 1' 2' 3' |" in lines


def test_key_signature_and_accidentals(tmp_path):
    # F major: C-E-G is 5-7-2, B natural is #4, C sharp is b6.
    lines, _ = lines_of(make_plan(
        [("lead", 60, 0, 1), ("lead", 64, 0, 1), ("lead", 67, 0, 1),
         ("lead", 65, 1, 2), ("lead", 71, 2, 3), ("lead", 72, 3, 4)],
        key=-1), tmp_path)
    assert "1=F 4/4" in lines
    assert "5,7,2 1 #4 5 |" in lines


def test_note_crossing_a_barline_is_tied(tmp_path):
    lines, _ = lines_of(make_plan([("lead", 60, 0, 1), ("lead", 62, 1, 2),
                                   ("lead", 64, 2, 3), ("lead", 65, 3, 5)]), tmp_path)
    assert "1 2 3 4 ~ |" in lines
    assert "4 0 - - |" in lines


def test_meter_change_at_a_barline(tmp_path):
    plan = make_plan([("lead", 60, 0, 1), ("lead", 62, 1, 2), ("lead", 64, 2, 3),
                      ("lead", 65, 3, 4), ("lead", 67, 4, 5), ("lead", 69, 5, 6),
                      ("lead", 71, 6, 7)],
                     meters=[{"quarter": 0, "numerator": 4, "denominator": 4},
                             {"quarter": 4, "numerator": 3, "denominator": 4}])
    lines, result = lines_of(plan, tmp_path)
    assert "1 2 3 4 |" in lines
    assert "3/4 5 6 7 |" in lines
    assert result["warnings"] == []


def test_tempo_change_at_a_barline(tmp_path):
    plan = make_plan([("lead", 60, 0, 1), ("lead", 62, 1, 2), ("lead", 64, 2, 3),
                      ("lead", 65, 3, 4),
                      # 120 BPM from second 4: these four notes are one quarter each.
                      ("lead", 67, 4, 4.5), ("lead", 69, 4.5, 5),
                      ("lead", 71, 5, 5.5), ("lead", 72, 5.5, 6)],
                     tempos=[{"seconds": 0, "bpm": 60}, {"seconds": 4, "bpm": 120}])
    lines, _ = lines_of(plan, tmp_path)
    assert "1 2 3 4 |" in lines
    assert "4=120 5 6 7 1' |" in lines


def test_tempo_change_inside_a_bar_is_reported(tmp_path):
    plan = make_plan([("lead", 60, 0, 1), ("lead", 62, 1, 2),
                      ("lead", 64, 2, 3), ("lead", 65, 3, 4)],
                     tempos=[{"seconds": 0, "bpm": 60}, {"seconds": 1.5, "bpm": 120}])
    _, result = lines_of(plan, tmp_path)
    assert any("inside a bar" in warning for warning in result["warnings"])


def test_non_quarter_meter_is_reported(tmp_path):
    plan = make_plan([("lead", 60, 0, 1), ("lead", 62, 1, 2), ("lead", 64, 2, 3)],
                     meters=[{"quarter": 0, "numerator": 6, "denominator": 8}])
    _, result = lines_of(plan, tmp_path)
    assert any("quarter-note beat" in warning for warning in result["warnings"])


def test_percussion_is_reported_not_silently_dropped(tmp_path):
    tracks = [{"id": "lead", "name": "Lead", "gm_program": 73},
              {"id": "kit", "name": "Drumset", "is_drum": True}]
    lines, result = lines_of(make_plan(
        [("lead", 60, 0, 1), ("lead", 62, 1, 2), ("lead", 64, 2, 3), ("lead", 65, 3, 4),
         ("kit", 38, 0, 1)], tracks=tracks), tmp_path)
    assert any("Percussion track Drumset" in warning for warning in result["warnings"])
    assert not any("instrument=Drumset" in line for line in lines)


def test_missing_key_signature_is_reported(tmp_path):
    plan = make_plan([("lead", 60, 0, 1), ("lead", 62, 1, 2),
                      ("lead", 64, 2, 3), ("lead", 65, 3, 4)])
    plan["notation"].pop("key_fifths")
    lines, result = lines_of(plan, tmp_path)
    assert any("assumes C major" in warning for warning in result["warnings"])
    assert "1=C 4/4" in lines


def test_polyphonic_track_becomes_separate_parts(tmp_path):
    lines, result = lines_of(make_plan(
        [("lead", 60, 0, 2), ("lead", 67, 1, 3),
         ("lead", 62, 2, 4), ("lead", 64, 3, 4)]), tmp_path)
    assert result["parts"] == 2
    assert "instrument=Lead" in lines
    assert "instrument=Lead (voice 2)" in lines


def test_text_copy_matches_the_jianpu_content(tmp_path):
    plan = make_plan([("lead", 60, 0, 1), ("lead", 62, 1, 2),
                      ("lead", 64, 2, 3), ("lead", 65, 3, 4)])
    text, _ = lines_of(plan, tmp_path, text=True)
    assert text[0].startswith("1=C 4/4")
    assert "[Lead]" in text
    assert "1 2 3 4 |" in text


@pytest.mark.skipif(importlib.util.find_spec("jianpu_ly") is None,
                    reason="jianpu-ly is not installed")
def test_generated_file_parses_with_jianpu_ly(tmp_path):
    plan = make_plan([("lead", 60, 0, 1), ("lead", 64, 1, 2), ("lead", 67, 2, 3),
                      ("lead", 72, 3, 4), ("lead", 71, 4, 5), ("lead", 69, 5, 6),
                      ("lead", 67, 6, 8)],
                     meters=[{"quarter": 0, "numerator": 4, "denominator": 4},
                             {"quarter": 4, "numerator": 3, "denominator": 4},
                             {"quarter": 7, "numerator": 4, "denominator": 4}],
                     key=-1)
    path = tmp_path / "validate.jly"
    write_jianpu(plan, path)
    completed = subprocess.run([sys.executable, "-m", "jianpu_ly", str(path)],
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "\\version" in completed.stdout


def test_native_plan_is_projected_through_its_engraved_score(tmp_path, monkeypatch):
    import mido

    native = {"score": {"title": "Native", "parts": [{"instrument_id": "flute"}],
                        "key_fifths": -1},
              "steps": [{"id": "note", "action": "addChord", "params": {}}]}
    plan = {"schema_version": 1, "kind": "scorebridge_music_plan", "title": "Native",
            "source": {}, "bindings": {}, "warnings": [],
            "notation": {"native": native, "grid_quarters": .25}}
    source = tmp_path / "native.json"
    source.write_text(json.dumps(plan))

    def fake_build(score, steps, output, executable=""):
        Path(output).write_bytes(b"PK\x03\x04")
        return {"status": "pass", "target": {}, "parts": []}

    def fake_convert(self, src, destination):
        midi = mido.MidiFile(type=1, ticks_per_beat=480)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60)))
        track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
        track.append(mido.Message("note_on", note=60, velocity=80, time=0))
        track.append(mido.Message("note_off", note=60, velocity=0, time=480))
        midi.save(str(destination))
        return {"output_path": str(destination)}

    monkeypatch.setattr("scorebridge.musescore.build.build_agent_score", fake_build)
    monkeypatch.setattr("scorebridge.musescore.adapter.MuseScoreAdapter.convert", fake_convert)
    report = deliver_music_plan(source, tmp_path / "output", ["jianpu"])
    assert report["status"] == "delivered"
    jly = Path(report["outputs"]["jianpu"]).read_text()
    # The key signature comes from the Agent's engraved specification.
    assert "1=F 4/4" in jly
    assert "1" in jly


def test_delivery_writes_both_jianpu_files(tmp_path):
    plan = make_plan([("lead", 60, 0, 1), ("lead", 62, 1, 2),
                      ("lead", 64, 2, 3), ("lead", 65, 3, 4)])
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan))
    report = deliver_music_plan(source, tmp_path / "output", ["jianpu"])
    assert report["status"] == "delivered"
    assert set(report["outputs"]) == {"jianpu", "jianpu_text"}
    assert Path(report["outputs"]["jianpu"]).read_text().startswith("title=Test")
    assert "1 2 3 4 |" in Path(report["outputs"]["jianpu_text"]).read_text()
    # No notation software is needed for an event plan.
    assert "editor_receipt" not in report
