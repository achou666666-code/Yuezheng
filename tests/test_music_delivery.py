import copy
import json
from pathlib import Path
from xml.etree import ElementTree as E
import mido
import pytest

from scorebridge.music_plan import make_music_plan, validate_music_plan, seconds_to_quarters
from scorebridge.music_delivery import deliver_music_plan, write_performance_midi, write_plan_musicxml
from scorebridge.midi_projection import project_midi
from scorebridge.ace.adapter import select_source, ACEError


@pytest.fixture
def plan():
    return {"schema_version": 1, "kind": "scorebridge_music_plan", "title": "Original test",
            "source": {}, "tempo_map": [{"seconds": 0, "bpm": 120}, {"seconds": 2, "bpm": 60}],
            "meter_map": [{"quarter": 0, "numerator": 4, "denominator": 4}, {"quarter": 4, "numerator": 3, "denominator": 4}],
            "notation": {"grid_quarters": .25}, "performance": {
                "tracks": [{"id": "flute", "name": "Flute", "gm_program": 73,
                            "controls": [{"number": 1, "value": 88, "seconds": .3}],
                            "pitch_bends": [{"value": 120, "seconds": .5}]},
                           {"id": "drums", "name": "Drumset", "is_drum": True}],
                "events": [{"kind": "note", "track": "flute", "midi_pitch": 72, "start_seconds": 1.8, "end_seconds": 3.5, "velocity": 90},
                           {"kind": "note", "track": "flute", "midi_pitch": 76, "start_seconds": 2, "end_seconds": 2.5, "velocity": 80},
                           {"kind": "drum", "track": "drums", "midi_pitch": 38, "start_seconds": .3, "end_seconds": .4, "velocity": 70}]}}


def test_tempo_units_and_midi_roundtrip(plan, tmp_path):
    assert seconds_to_quarters(3.5, plan["tempo_map"]) == 5.5
    projected = project_midi(write_performance_midi(plan, tmp_path / "music.mid"))
    assert [p["bpm"] for p in projected["tempo_map"]] == [120, 60]
    assert [(m["quarter"], m["numerator"]) for m in projected["meter_map"]] == [(0, 4), (4, 3)]
    original = sorted((e["midi_pitch"], e["start_seconds"], e["end_seconds"]) for e in plan["performance"]["events"])
    restored = sorted((e["midi_pitch"], e["start_seconds"], e["end_seconds"]) for e in projected["performance"]["events"])
    assert restored == original
    assert projected["performance"]["tracks"][0]["controls"][0]["value"] == 88
    assert projected["performance"]["tracks"][0]["pitch_bends"][0]["value"] == 120
    assert projected["performance"]["tracks"][1]["is_drum"]


def test_notation_ties_voices_and_meter(plan, tmp_path):
    before = copy.deepcopy(plan)
    root = E.parse(write_plan_musicxml(plan, tmp_path / "score.musicxml")).getroot()
    assert plan == before
    part = root.find("part")
    assert part.find("measure/note/rest") is not None
    assert root.find(".//tie[@type='start']") is not None
    assert root.find(".//tie[@type='stop']") is not None
    assert root.find(".//backup") is not None
    assert part.findall("measure")[1].findtext("attributes/time/beats") == "3"
    for measure in part.findall("measure"):
        counts = {}
        for note in measure.findall("note"):
            if note.find("chord") is None:
                v = note.findtext("voice")
                counts[v] = counts.get(v, 0) + int(note.findtext("duration"))
        expected = 1920 if measure.get("number") == "1" else 1440
        assert set(counts.values()) == {expected}
    assert root.findtext("part-list/score-part/midi-instrument/midi-program") == "74"
    assert root.findall("part-list/score-part")[1].findtext("midi-instrument/midi-unpitched") == "39"


def test_large_midi_ensemble_uses_ports_not_program_collisions(plan, tmp_path):
    plan["performance"]["tracks"] = [{"id": str(i), "name": str(i), "gm_program": i} for i in range(22)]
    plan["performance"]["events"] = [{"kind": "note", "track": str(i), "midi_pitch": 60, "start_seconds": 0, "end_seconds": .5} for i in range(22)]
    midi = mido.MidiFile(write_performance_midi(plan, tmp_path / "many.mid"))
    pairs = [(next(m.port for m in t if m.type == "midi_port"), next(m.channel for m in t if m.type == "program_change")) for t in midi.tracks[1:]]
    assert len(set(pairs)) == 22
    assert all(channel != 9 for _, channel in pairs)


def test_unresolved_identity_not_fabricated_piano(plan, tmp_path):
    plan["performance"]["tracks"][0]["gm_program"] = None
    midi = mido.MidiFile(write_performance_midi(plan, tmp_path / "unknown.mid"))
    assert not any(m.type == "program_change" for m in midi.tracks[1])
    with pytest.raises(ACEError, match="No resolved sound"):
        select_source(plan["performance"]["tracks"][0], [{"ref": "instrument:1", "kind": "instrument", "name": "Violin"}], {})


def test_invalid_timing_caught_before_delivery(plan, tmp_path):
    plan["tempo_map"][1]["seconds"] = -1
    p = tmp_path / "plan.json"; p.write_text(json.dumps(plan))
    assert deliver_music_plan(p, tmp_path / "output", ["midi"])["status"] == "error"
    assert not (tmp_path / "output").exists()


def test_native_plan_wrapper_and_selected_outputs(plan, tmp_path):
    native = {"score": {"title": "Native", "parts": [{"instrument_id": "flute"}]}, "steps": [{"id": "note", "action": "addChord", "params": {}}]}
    p = tmp_path / "native.json"; p.write_text(json.dumps(native))
    result = make_music_plan(p, tmp_path / "wrapped.json")
    assert result["status"] == "planned"
    assert json.loads((tmp_path / "wrapped.json").read_text())["notation"]["native"] == native
    p.write_text(json.dumps(plan))
    result = deliver_music_plan(p, tmp_path / "output", ["midi"])
    assert set(result["outputs"]) == {"midi"}
    assert [f.name for f in (tmp_path / "output").iterdir() if f.is_file()] == ["music.mid"]


def test_no_hardcoded_musical_tempo(tmp_path):
    p = tmp_path / "events.json"
    p.write_text(json.dumps({"tracks": [{"id": "t"}], "events": [{"kind": "note", "track": "t", "midi_pitch": 60, "start_seconds": 0, "end_seconds": 1}]}))
    result = make_music_plan(p, tmp_path / "plan.json")
    assert "not an identified tempo" in result["warnings"][0]


def test_missing_notation_software_does_not_block_midi(plan, tmp_path):
    p = tmp_path / "plan.json"; p.write_text(json.dumps(plan))
    report = deliver_music_plan(p, tmp_path / "output", ["mscz", "midi", "musicxml"], executable=str(tmp_path / "missing"))
    assert report["status"] == "partial"
    assert set(report["outputs"]) == {"midi", "musicxml"}
    assert "mscz" in report["errors"]


def test_audio_preview_renders_from_the_delivered_score(plan, tmp_path, monkeypatch):
    p = tmp_path / "plan.json"; p.write_text(json.dumps(plan))
    conversions = []

    def fake_convert(self, input_path, output_path):
        Path(output_path).write_bytes(b"RIFF....WAVE")
        conversions.append((Path(input_path).suffix, Path(output_path).name))
        return {"output_path": str(output_path)}

    monkeypatch.setattr("scorebridge.musescore.adapter.MuseScoreAdapter.convert", fake_convert)
    report = deliver_music_plan(p, tmp_path / "output", ["wav", "mp3"])
    assert report["status"] == "delivered"
    assert set(report["outputs"]) == {"wav", "mp3"}
    assert Path(report["outputs"]["wav"]).read_bytes().startswith(b"RIFF")
    assert Path(report["outputs"]["mp3"]).name == "music.mp3"
    # The audio is rendered from the notated MSCZ, never from the private plan.
    assert (".mscz", "music.wav") in conversions
    assert (".mscz", "music.mp3") in conversions


def test_unknown_delivery_format_is_rejected(plan, tmp_path):
    p = tmp_path / "plan.json"; p.write_text(json.dumps(plan))
    assert deliver_music_plan(p, tmp_path / "output", ["ogg"])["status"] == "error"


def test_sibelius_delivery_uses_independent_musicxml_projection(plan, tmp_path, monkeypatch):
    p = tmp_path / "plan.json"; p.write_text(json.dumps(plan))

    def fake_create(xml_path, output_path, url):
        assert Path(xml_path).read_text().startswith("<?xml")
        Path(output_path).write_bytes(b"SIB")
        return {"status": "delivered", "output_path": output_path, "staff_count": 2}

    monkeypatch.setattr("scorebridge.sibelius.adapter.create_sibelius_score", fake_create)
    report = deliver_music_plan(p, tmp_path / "output", ["sib"], executable=str(tmp_path / "missing"))
    assert report["status"] == "delivered"
    assert Path(report["outputs"]["sib"]).read_bytes() == b"SIB"
    assert report["sibelius_receipt"]["staff_count"] == 2
