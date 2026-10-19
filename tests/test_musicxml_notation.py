"""Reading engraved MusicXML into the notated model, without playback timing."""
from yuezheng.musicxml.notation import read_musicxml_notation

HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>{name}</part-name></score-part></part-list>
  <part id="P1">{body}</part>
</score-partwise>
"""

MEASURE = """<measure number="1">
  <attributes><divisions>1</divisions>{key}
    <time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>
  </attributes>{content}
</measure>"""


def build(tmp_path, content, name="Piano", key="<key><fifths>0</fifths></key>",
          beats=4, beat_type=4):
    body = MEASURE.format(content=content, key=key, beats=beats, beat_type=beat_type)
    path = tmp_path / "score.musicxml"
    path.write_text(HEAD.format(name=name, body=body), encoding="utf-8")
    return path


def note(step, octave, duration=1, voice=1, staff=None, chord=False, tie=False):
    parts = ["<note>"]
    if chord:
        parts.append("<chord/>")
    parts.append(f"<pitch><step>{step}</step><octave>{octave}</octave></pitch>")
    parts.append(f"<duration>{duration}</duration>")
    if tie:
        parts.append('<tie type="start"/>')
    if staff:
        parts.append(f"<staff>{staff}</staff>")
    parts.append(f"<voice>{voice}</voice></note>")
    return "".join(parts)


def rest(duration=1, voice=1, staff=None):
    return (f"<note><rest/><duration>{duration}</duration>"
            + (f"<staff>{staff}</staff>" if staff else "")
            + f"<voice>{voice}</voice></note>")


def test_chord_members_share_one_group(tmp_path):
    score = read_musicxml_notation(build(
        tmp_path, note("C", 4) + note("E", 4, chord=True) + note("G", 4, chord=True)
        + rest(3)))
    assert len(score.parts) == 1
    start, end, pitches, tie = score.parts[0].groups[0]
    assert (start, end, pitches, tie) == (0, 480, [60, 64, 67], False)


def test_two_staves_become_two_named_parts(tmp_path):
    score = read_musicxml_notation(build(
        tmp_path,
        note("C", 5) + rest(3, staff=1)
        + "<backup><duration>4</duration></backup>"
        + note("C", 3, staff=2, voice=5) + rest(3, staff=2, voice=5)))
    assert [part.name for part in score.parts] == ["Piano", "Piano (staff 2)"]


def test_tie_start_is_kept_for_the_renderer(tmp_path):
    score = read_musicxml_notation(build(
        tmp_path, note("C", 4, tie=True) + rest(3)))
    assert score.parts[0].groups[0][3] is True


def test_meter_key_and_tempo_are_read(tmp_path):
    content = ('<direction><sound tempo="90"/></direction>'
               + note("C", 4) + rest(2))
    score = read_musicxml_notation(build(
        tmp_path, content, key="<key><fifths>-2</fifths></key>",
        beats=3, beat_type=4))
    assert score.meters == [(0, 3, 4)]
    assert score.tempos == [(0, 90)]
    assert score.parts[0].key_fifths == -2


def test_unpitched_part_is_reported_not_written(tmp_path):
    content = ("<note><unpitched><display-step>C</display-step><display-octave>5"
               "</display-octave></unpitched><duration>1</duration><voice>1</voice></note>")
    score = read_musicxml_notation(build(tmp_path, content, name="Snare Drum"))
    assert score.parts == []
    assert any("Percussion part Snare Drum" in warning for warning in score.warnings)


def test_grace_notes_are_skipped_with_a_warning(tmp_path):
    content = ('<note><grace/><pitch><step>D</step><octave>4</octave></pitch>'
               '<voice>1</voice></note>' + note("C", 4) + rest(3))
    score = read_musicxml_notation(build(tmp_path, content))
    assert len(score.parts[0].groups) == 1
    assert any("grace note" in warning for warning in score.warnings)


KEY_CHANGE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Lead</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key>
      <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice></note>
    </measure>
    <measure number="2"><attributes><key><fifths>-1</fifths></key></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice></note>
    </measure>
  </part>
</score-partwise>
"""


def test_key_changes_are_kept_per_bar(tmp_path):
    path = tmp_path / "key.musicxml"
    path.write_text(KEY_CHANGE, encoding="utf-8")
    score = read_musicxml_notation(path)
    assert score.parts[0].key_fifths == 0
    assert score.parts[0].keys == [(0, 0), (1920, -1)]
    assert score.end_tick == 3840
