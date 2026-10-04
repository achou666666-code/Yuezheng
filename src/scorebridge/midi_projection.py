"""Project authored MIDI into the shared performance plan for DAW adapters."""
from collections import defaultdict, deque
import hashlib
from pathlib import Path


def project_midi(path, title=""):
    import mido
    midi = mido.MidiFile(str(path))
    if midi.type == 2 or midi.ticks_per_beat <= 0:
        raise ValueError("Use a synchronous PPQ MIDI file")
    tempo_ticks, meter_ticks = {0: 500000}, {0: (4, 4)}
    for stream in midi.tracks:
        pos = 0
        for message in stream:
            pos += message.time
            if message.type == "set_tempo":
                tempo_ticks[pos] = message.tempo
            elif message.type == "time_signature":
                meter_ticks[pos] = message.numerator, message.denominator
    points, previous, seconds, tempo = [], 0, 0, 500000
    for tick, value in sorted(tempo_ticks.items()):
        seconds += mido.tick2second(tick - previous, midi.ticks_per_beat, tempo)
        points.append((tick, seconds, value))
        previous, tempo = tick, value
    def clock(tick):
        p = next(p for p in reversed(points) if p[0] <= tick)
        return p[1] + mido.tick2second(tick - p[0], midi.ticks_per_beat, p[2])
    tracks, events = [], []
    for index, stream in enumerate(midi.tracks):
        programs, groups, pending = defaultdict(int), {}, defaultdict(deque)
        pos, name = 0, ""
        controls, bends = defaultdict(list), defaultdict(list)
        def group(channel, program):
            key = channel, program
            if key not in groups:
                identifier = f"midi-{index}-{channel}-{program}"
                groups[key] = {"id": identifier, "name": name or identifier, "gm_program": None if channel == 9 else program,
                               "is_drum": channel == 9, "instrument_source": "authored_midi"}
            return groups[key]
        for message in stream:
            pos += message.time
            if message.type == "track_name":
                name = message.name
            elif message.type == "program_change":
                programs[message.channel] = message.program
            elif message.type == "control_change":
                controls[message.channel].append({"number": message.control, "value": message.value, "seconds": clock(pos)})
            elif message.type == "pitchwheel":
                bends[message.channel].append({"value": message.pitch, "seconds": clock(pos)})
            elif message.type == "note_on" and message.velocity > 0:
                pending[message.channel, message.note].append((pos, message.velocity, programs[message.channel]))
            elif message.type in {"note_off", "note_on"}:
                stack = pending[message.channel, message.note]
                if stack:
                    begin, velocity, program = stack.popleft()
                    track = group(message.channel, program)
                    if pos > begin:
                        events.append({"kind": "drum" if message.channel == 9 else "note", "track": track["id"],
                                       "midi_pitch": message.note, "velocity": velocity,
                                       "start_seconds": clock(begin), "end_seconds": clock(pos)})
        if any(pending.values()):
            raise ValueError("MIDI contains unterminated notes")
        for (channel, program), track in groups.items():
            track.update(controls=controls[channel], pitch_bends=bends[channel])
            tracks.append(track)
    return {"schema_version": 1, "kind": "scorebridge_music_plan", "title": title or Path(path).stem,
            "source": {"record_path": str(Path(path).resolve()), "record_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "recognizer": "authored_midi_projection"},
            "performance": {"tracks": tracks, "events": events},
            "tempo_map": [{"seconds": s, "bpm": mido.tempo2bpm(t), "source": "authored_midi"} for _, s, t in points],
            "meter_map": [{"quarter": tick / midi.ticks_per_beat, "numerator": n, "denominator": d, "source": "authored_midi"} for tick, (n, d) in sorted(meter_ticks.items())],
            "notation": {"grid_quarters": .25, "pitch_mode": "concert"}, "bindings": {}, "warnings": []}
