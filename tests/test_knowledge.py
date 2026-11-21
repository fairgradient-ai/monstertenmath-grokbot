"""The knowledge files stay consistent with each other and with the rules."""

from monsterbot.doctor import lint_knowledge


def test_every_canned_reply_passes_the_check(kn):
    assert lint_knowledge(kn) == []


def test_pieces_are_unique_and_matchable(kn):
    keys = [p.key for p in kn.pieces]
    assert len(keys) == len(set(keys))
    for p in kn.pieces:
        assert kn.match_piece(p.caption_start + " and the rest of the caption") is p, p.key
    assert kn.match_piece("Something else entirely") is None


def test_captions_match_with_line_breaks(kn):
    assert kn.match_piece("Hello. We're Monster Ten.\n\nMath for 4–6 year olds").key == "#1"


def test_play_along_keys_make_ten(kn):
    for p in kn.pieces:
        pa = p.play_along
        if pa and pa.answer is not None:
            assert 10 - pa.answer in pa.context and 10 in pa.context
            assert str(pa.answer) in pa.right or str(pa.answer) in pa.wrong
        if pa and pa.sequence:
            assert len(pa.sequence) == 4


def test_ai_pieces_have_an_ai_line(kn):
    for p in kn.pieces:
        if p.ai:
            assert p.ai_reply and "AI" in p.ai_reply, p.key
        else:
            assert p.ai_reply is None, p.key


def test_longest_caption_start_wins(kn):
    # #4's start "Try it tonight: Monster's Cave" is a prefix of #402's, which must still match #402.
    assert kn.match_piece("Try it tonight: Monster's Cave, a 5-minute game for 4–6 year olds.").key == "#402"
    assert kn.match_piece("Try it tonight: Monster's Cave! Ten crackers and a cup.").key == "#4"
