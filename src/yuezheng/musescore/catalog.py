"""MuseScore scaffold defaults; MIDI programs use MusicXML's one-based numbers."""
# Canonical template IDs, sound taxonomy, program, clef, diatonic/chromatic offset.
_PITCHED = {
    'flute': ('wind.flutes.flute', 74, 'treble', 0, 0),
    'oboe': ('wind.reed.oboe', 69, 'treble', 0, 0),
    'bb-clarinet': ('wind.reed.clarinet.clarinet', 72, 'treble', -1, -2),
    'bass-clarinet': ('wind.reed.clarinet.bass', 72, 'treble', -8, -14),
    'bassoon': ('wind.reed.bassoon', 71, 'bass', 0, 0),
    'horn': ('brass.horns.french-horn', 61, 'treble', -4, -7),
    'bb-trumpet': ('brass.trumpet', 57, 'treble', -1, -2),
    'trombone': ('brass.trombone', 58, 'bass', 0, 0),
    'tuba': ('brass.tuba', 59, 'bass', 0, 0),
    'timpani': ('drum.timpani', 48, 'bass', 0, 0),
    'violin': ('strings.violin', 41, 'treble', 0, 0),
    'viola': ('strings.viola', 42, 'alto', 0, 0),
    'violoncello': ('strings.cello', 43, 'bass', 0, 0),
    'contrabass': ('strings.contrabass', 44, 'bass', -7, -12),
    'piano': ('keyboard.piano', 1, 'treble', 0, 0),
    'choir-synth': ('voice.choir', 53, 'treble', 0, 0),
    'glockenspiel': ('pitched-percussion.glockenspiel',10,'treble',14,24),
    'marimba': ('pitched-percussion.marimba',13,'treble',0,0),
}
_DRUMS = {
    'percussion': ('drum.group', 38),
    'snare-drum': ('drum.snare-drum', 38),
    'bass-drum': ('drum.bass-drum', 36),
    'cymbal': ('metal.cymbal', 49),
    'crash-cymbal': ('metal.cymbal.crash', 49),
    'tambourine': ('metal.tambourine', 54),
    'triangle': ('metal.triangle', 81),
}


def scaffold_instrument(template_id):
    if template_id in _DRUMS:
        sound, pitch = _DRUMS[template_id]
        return {'instrument_sound': sound, 'midi_program': 1, 'clef': 'percussion',
                'unpitched': True, 'midi_unpitched': pitch + 1}
    if template_id in _PITCHED:
        sound, program, clef, diatonic, chromatic = _PITCHED[template_id]
        return {'instrument_sound': sound, 'midi_program': program, 'clef': clef,
                'transpose_diatonic': diatonic or None,
                'transpose_chromatic': chromatic or None}
    return {}
