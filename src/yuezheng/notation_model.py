"""Notated content shared by projections that do not use performance timing.

The jianpu projection can be built from a performance plan (audio events) or
from an engraved MusicXML score. Both produce this model, so rendering only has
to deal with absolute ticks and never with playback timing.
"""
from dataclasses import dataclass, field


@dataclass
class NotatedPart:
    name: str
    key_fifths: int = 0
    # (start_tick, end_tick, written midi pitches, tie_after)
    groups: list = field(default_factory=list)
    # (start_tick, fifths) for every key change, opening key included
    keys: list = field(default_factory=list)


@dataclass
class NotatedScore:
    title: str
    # (start_tick, numerator, denominator) at each meter change
    meters: list = field(default_factory=list)
    # (tick, bpm) at each tempo change
    tempos: list = field(default_factory=list)
    parts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    # end of the engraved score, so trailing rest bars are not lost
    end_tick: int = 0
