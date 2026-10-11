"""Canonical instrument metadata for MusicXML and MIDI export."""

INSTRUMENTS = {
    "wind.flutes.flute": {"name": "Flute", "midi_program": 74, "instrument_sound": "wind.flutes.flute"},
    "wind.reed.clarinet.bflat": {"name": "Clarinet in B-flat", "midi_program": 72, "instrument_sound": "wind.reed.clarinet.clarinet", "transpose_diatonic": -1, "transpose_chromatic": -2},
    "brass.french-horn": {"name": "Horn in F", "midi_program": 61, "instrument_sound": "brass.horns.french-horn", "transpose_diatonic": -4, "transpose_chromatic": -7},
    "strings.violin": {"name": "Violin", "midi_program": 41, "instrument_sound": "strings.violin"},
    "keyboard.piano": {"name": "Piano", "midi_program": 1, "instrument_sound": "keyboard.piano"},
}

_ALIASES = {
    "flute": "wind.flutes.flute", "oboe": "wind.reed.oboe", "bassoon": "wind.reed.bassoon",
    "clarinet in bb": "wind.reed.clarinet.bflat", "clarinet in b-flat": "wind.reed.clarinet.bflat",
    "bass clarinet in bb": "wind.reed.clarinet.bass", "trumpet in bb": "brass.trumpet.bflat",
    "horn in f": "brass.french-horn", "trombone": "brass.trombone", "tuba": "brass.tuba",
    "timpani": "drum.timpani", "piano": "keyboard.piano", "violin": "strings.violin",
    "viola": "strings.viola", "violoncello": "strings.cello", "contrabass": "strings.contrabass",
}
INSTRUMENTS.update({
    "wind.reed.oboe": {"name": "Oboe", "midi_program": 69, "instrument_sound": "wind.reed.oboe"},
    "wind.reed.bassoon": {"name": "Bassoon", "midi_program": 71, "instrument_sound": "wind.reed.bassoon"},
    "wind.reed.clarinet.bass": {"name": "Bass Clarinet in Bb", "midi_program": 72, "instrument_sound": "wind.reed.clarinet.bass", "transpose_diatonic": -1, "transpose_chromatic": -2},
    "brass.trumpet.bflat": {"name": "Trumpet in Bb", "midi_program": 57, "instrument_sound": "brass.trumpet.bflat", "transpose_diatonic": -1, "transpose_chromatic": -2},
    "brass.trombone": {"name": "Trombone", "midi_program": 58, "instrument_sound": "brass.trombone"},
    "brass.tuba": {"name": "Tuba", "midi_program": 59, "instrument_sound": "brass.tuba"},
    "drum.timpani": {"name": "Timpani", "midi_program": 48, "instrument_sound": "drum.timpani"},
    "strings.violin": {"name": "Violin", "midi_program": 41, "instrument_sound": "strings.violin"},
    "strings.viola": {"name": "Viola", "midi_program": 42, "instrument_sound": "strings.viola"},
    "strings.cello": {"name": "Violoncello", "midi_program": 43, "instrument_sound": "strings.cello"},
    "strings.contrabass": {"name": "Contrabass", "midi_program": 44, "instrument_sound": "strings.contrabass"},
})

def instrument_spec(instrument_id: str) -> dict:
    from .instrument_names import resolve_instrument_name
    instrument_id = resolve_instrument_name(instrument_id, INSTRUMENTS)
    direct = INSTRUMENTS.get(instrument_id)
    if direct:
        return direct
    label = instrument_id.lower().replace("♭", "b").strip()
    alias = _ALIASES.get(label)
    if alias:
        return INSTRUMENTS.get(alias, {})
    # OMR labels commonly append desk numbers or combine like instruments.
    # Resolve the stable instrument family while retaining the printed part name.
    for prefix, alias in (
        ("flute", "flute"), ("oboe", "oboe"), ("clarinet", "clarinet in bb"),
        ("bass clarinet", "bass clarinet in bb"), ("bassoon", "bassoon"),
        ("trumpet", "trumpet in bb"), ("horn", "horn in f"),
        ("trombone", "trombone"), ("tuba", "tuba"), ("timpani", "timpani"),
        ("violin", "violin"), ("viola", "viola"), ("violoncello", "violoncello"),
        ("cello", "violoncello"), ("contrabass", "contrabass"), ("double bass", "contrabass"),
        ("piano", "piano"),
    ):
        if label.startswith(prefix):
            return INSTRUMENTS.get(_ALIASES[alias], {})
    return {}
