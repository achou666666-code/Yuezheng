from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

@dataclass
class SourceRef:
    page: Optional[int] = None
    bbox: Optional[List[float]] = None
    confidence: Optional[float] = None

@dataclass
class Event:
    kind: str  # note, rest, chord
    duration: str
    pitch: Optional[str] = None
    pitches: List[str] = field(default_factory=list)
    voice: int = 1
    accidental: Optional[str] = None
    tie_start: bool = False
    tie_stop: bool = False
    articulations: List[str] = field(default_factory=list)
    techniques: List[str] = field(default_factory=list)
    source: Optional[SourceRef] = None

@dataclass
class Measure:
    number: int
    events: List[Event] = field(default_factory=list)
    key_fifths: Optional[int] = None
    time_beats: Optional[int] = None
    time_beat_type: Optional[int] = None
    tempo_bpm: Optional[float] = None
    tempo_beat: str = "quarter"
    dynamics: List[str] = field(default_factory=list)
    directions: List[str] = field(default_factory=list)
    source: Optional[SourceRef] = None

@dataclass
class Staff:
    id: str
    measures: List[Measure] = field(default_factory=list)
    clef: str = "treble"

@dataclass
class Part:
    id: str
    name: str
    instrument_id: str
    transposition: Optional[str] = None
    staves: List[Staff] = field(default_factory=list)

@dataclass
class Score:
    title: str
    parts: List[Part] = field(default_factory=list)
    pitch_mode: str = "written"
    metadata: Dict[str, Any] = field(default_factory=dict)
