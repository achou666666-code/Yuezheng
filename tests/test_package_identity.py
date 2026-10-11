def test_yuezheng_is_canonical_and_scorebridge_remains_compatible():
    import scorebridge
    import yuezheng
    from scorebridge.musicxml import parse_musicxml as legacy_parse
    from yuezheng.musicxml import parse_musicxml as canonical_parse

    assert yuezheng.__brand__ == "Yuezheng"
    assert scorebridge.__brand__ == yuezheng.__brand__
    assert callable(canonical_parse)
    assert callable(legacy_parse)
