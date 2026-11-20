"""How a comment is sorted (triage.py, with knowledge/replies.toml and pieces.toml)."""

from datetime import UTC, datetime

import pytest

from monsterbot.models import Comment
from monsterbot.triage import looks_like_guess, triage

T = datetime(2026, 11, 20, 1, 40, tzinfo=UTC)


def c(text, user="parent_x", parent=None):
    return Comment(id="x", media_id="m", text=text, username=user, timestamp=T, parent_id=parent)


def sort(kn, text, piece="#3", phase="building", stores=(), parent=None, user="parent_x"):
    parent_comment = Comment("p", "m", "a question", parent, T) if parent else None
    return triage(
        c(text, user, "p" if parent else None),
        piece=kn.piece(piece),
        handle="monstertenmath",
        parent=parent_comment,
        kn=kn,
        phase=phase,
        stores=stores,
        thanks=True,
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("3!", "Yes! 7 and 3 make 10."),
        ("three", "Yes! 7 and 3 make 10."),
        ("my son said 3", "Yes! 7 and 3 make 10."),
        ("7 and 3 make 10", "Yes! 7 and 3 make 10."),
        ("4", "Let's check! Count up from 7: 8, 9, 10. He took 3."),
        ("He took 7", "Let's check! Count up from 7: 8, 9, 10. He took 3."),
    ],
)
def test_guesses_on_play_along(kn, text, expected):
    v = sort(kn, text)
    assert (v.category, v.tier, v.reply) == ("guess", "auto", expected)


def test_ambiguous_guess_goes_to_a_person(kn):
    v = sort(kn, "3 or 4?")
    assert v.tier == "draft"


def test_a_sentence_with_a_number_is_not_a_guess(kn):
    assert not looks_like_guess("My 5 year old loved it")
    assert sort(kn, "My 5 year old loved it").category == "played"


def test_flash_dots_sequence(kn):
    assert sort(kn, "4 5 3 6", piece="#15").reply.startswith("Yes! 4, 5, 3 and 6")
    assert sort(kn, "4, 5, 2, 6", piece="#15").reply.startswith("The cards were 4, 5, 3 and 6")


def test_no_guess_key_no_guess(kn):
    assert sort(kn, "3", piece="#4").category != "guess"


def test_own_spam_escalate_tags(kn):
    assert sort(kn, "Thanks all!", user="MonsterTenMath").tier == "skip"
    assert sort(kn, "Promote it on @growfast for real followers").category == "spam"
    assert sort(kn, "Check out my page for deals").category == "spam"
    v = sort(kn, "I was charged and want a refund")
    assert (v.category, v.reason) == ("escalate", "billing")
    assert sort(kn, "My son has ADHD, will this work?").reason == "child-or-health"
    assert sort(kn, "We'd love to collab!").reason == "business"
    assert sort(kn, "Can I use this in my kindergarten class?").reason == "business"
    assert sort(kn, "Can I use this in my kindergarten class?").tier == "auto"  # the holding line
    assert sort(kn, "We use Prodigy already").reason == "rival"
    assert sort(kn, "@bestie we need this").tier == "skip"
    assert sort(kn, "@bestie @other").tier == "skip"


def test_a_comment_tagging_us_is_never_skipped(kn):
    assert sort(kn, "@monstertenmath we need this").tier != "skip"


def test_parents_saying_partner_or_struggled_words_dont_misfire(kn):
    # "partner" and "the Monster took/stole" are everyday words here
    assert sort(kn, "My partner and I loved this").category != "escalate"
    assert sort(kn, "The Monster is so sneaky lol").category != "escalate"


def test_ai_question_uses_the_piece_line(kn):
    v = sort(kn, "Is this AI?")
    assert v.tier == "auto" and "AI-made stills" in v.reply
    assert sort(kn, "Is this AI?", piece="#1").tier == "draft"  # a designed post has no AI line


def test_faq_by_phase(kn):
    assert sort(kn, "Where's the link?").reply.startswith("There isn't one yet")
    assert sort(kn, "Where's the link?", phase="open").reply.startswith("Tap the link in our bio")
    assert sort(kn, "How much will it cost?", phase="open").reply.startswith("The check is free.")


def test_faq_needs_a_question(kn):
    # "love the price" isn't a price question
    assert sort(kn, "love the price").category != "faq:price"


def test_platform_reply_is_the_browser(kn):
    # Launch (1 Dec 2026) is web only; the store apps come later (the owner, 20 Nov 2026).
    assert sort(kn, "iPhone or Android?").reply.startswith("It will play in your browser")
    assert sort(kn, "iPhone or Android?", phase="open").reply.startswith("It plays in your browser")
    assert sort(kn, "Is it on the App Store?", phase="open", stores=("app_store",)).reply.startswith("It plays in your browser")


def test_card_question_has_no_building_reply(kn):
    assert sort(kn, "Do I need a card?", phase="building").tier == "draft"
    assert sort(kn, "Do I need a card?", phase="open").reply.startswith("No. The check is free")


def test_piece_limited_and_voice_limited_faqs(kn):
    assert sort(kn, "Can we play it in the car?", piece="#6").category == "faq:car"
    assert sort(kn, "Can we play it in the car?", piece="#3").category != "faq:car"
    assert sort(kn, "The voice sounds robotic").notify
    assert sort(kn, "The voice sounds robotic", piece="#15").tier == "draft"  # #15 has no voice


def test_praise_and_emoji(kn):
    assert sort(kn, "Love this!").category == "praise"
    assert sort(kn, "😍😍").category == "praise"
    assert sort(kn, "Love this! Where can I get it?").category != "praise"


def test_thread_replies(kn):
    assert sort(kn, "Following for the answer!", parent="someone").tier == "skip"
    assert sort(kn, "Same question, does it work at 3?", parent="someone").tier == "draft"
    # answers under our own pinned first comment are treated like top-level comments
    assert sort(kn, "3!", parent="monstertenmath").category == "guess"
