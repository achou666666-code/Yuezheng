from fixture_score import fixture_score
from scorebridge.musicxml import compile_musicxml, parse_musicxml


NAMESPACED_MUSICXML = '''<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0" xmlns="http://www.musicxml.org/ns/musicxml">
  <work><work-title>Namespaced fixture</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Flute</part-name></score-part>
    <score-part id="P2"><part-name>Violin</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
      <backup><duration>4</duration></backup>
      <note><rest/><duration>4</duration><voice>2</voice><type>quarter</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes><divisions>4</divisions></attributes>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
      <note><chord/><pitch><step>B</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>'''

def test_musicxml_roundtrip_parser(tmp_path):
    source = tmp_path / "source.musicxml"
    compile_musicxml(fixture_score(), source)
    score = parse_musicxml(source)
    assert len(score.parts) == 4
    assert score.parts[0].name == "Flute"
    assert len(score.parts[3].staves) == 2
    assert score.parts[0].staves[0].measures[0].events[0].pitch == "C5"


def test_musicxml_parser_accepts_standard_namespace_and_third_party_shapes(tmp_path):
    source = tmp_path / "namespaced.musicxml"
    source.write_text(NAMESPACED_MUSICXML, encoding="utf-8")

    score = parse_musicxml(source)

    assert score.title == "Namespaced fixture"
    assert [part.name for part in score.parts] == ["Flute", "Violin"]
    assert [event.kind for event in score.parts[0].staves[0].measures[0].events] == ["note", "rest"]
    chord = score.parts[1].staves[0].measures[0].events[0]
    assert chord.kind == "chord"
    assert chord.pitches == ["G4", "B4"]
