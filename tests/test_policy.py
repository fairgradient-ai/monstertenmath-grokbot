"""The 30-second check as code (knowledge/rules.toml, applied by policy.check)."""

import pytest

from monsterbot.policy import Context, check

BUILDING = Context("building")
OPEN = Context("open")

TRIAL_OK = (
    "The check is free. Then a 7-day free trial: you add a card at signup and nothing is charged that day. "
    "We remind you on day 5, and you can cancel in 2 taps. After the 7 days it's $59.99 a year or $12.99 a month."
)


def ids(text, ctx, kn):
    return {v.id for v in check(text, ctx, kn.rules)}


@pytest.mark.parametrize(
    "text, rule",
    [
        ("Your child will be reading numbers in a week!", "outcome-promise"),
        ("It's proven to work.", "outcome-promise"),
        ("Help them get ahead before kindergarten.", "outcome-promise"),
        ("It's a quick test you do together.", "check-not-test"),
        ("Think of it as a screening.", "check-not-test"),
        ("Keep your streak going!", "no-pressure"),
        ("Don't let them fall behind.", "no-pressure"),
        ("3 days to go!", "no-pressure"),
        ("The Snack Monster loves crackers.", "retired-name"),
        ("This was filmed at home with a real family.", "ai-honesty"),
        ("It's not AI, promise.", "ai-honesty"),
        ("That's lesson 14 word for word.", "ai-honesty"),
        ("Send us a video of your child playing!", "child-content"),
        ("It's 9.99 a year.", "mangled-price"),
        ("Love it #earlymath", "hashtags"),
        ("Ask @someone_else about it.", "mention"),
        ("Better than funexpected!", "rival"),
    ],
)
def test_banned_in_any_phase(kn, text, rule):
    assert rule in ids(text, BUILDING, kn)
    assert rule in ids(text, OPEN, kn)


@pytest.mark.parametrize(
    "text",
    [
        "Link in bio!",
        "Sign up now.",
        "Download it today.",
        "Available now.",
        "Start your free trial.",
        "It launches on Monday.",
    ],
)
def test_building_phase_points_nowhere(kn, text):
    assert check(text, BUILDING, kn.rules)


def test_signup_as_a_noun_is_fine_before_launch(kn):
    building_price = (
        "At launch: a 7-day free trial. You add a card at signup and nothing is charged that day. We remind you "
        "on day 5, and you can cancel in 2 taps. After the 7 days it's $59.99 a year or $12.99 a month."
    )
    assert check(building_price, BUILDING, kn.rules) == []


def test_open_phase_drops_being_built(kn):
    assert "open-no-building" in ids("It's being built now, follow along.", OPEN, kn)
    assert "open-no-building" not in ids("It's being built now, follow along.", BUILDING, kn)


def test_trial_terms_whole_or_not_at_all(kn):
    assert check(TRIAL_OK, OPEN, kn.rules) == []
    v = check("Try the 7 days free!", OPEN, kn.rules)
    assert any(x.id == "trial-terms" for x in v)
    v = check("It's $59.99 a year.", OPEN, kn.rules)
    assert any(x.id == "trial-terms" for x in v)


def test_only_real_prices(kn):
    text = TRIAL_OK.replace("$12.99 a month", "$9.99 a month")
    assert "price" in ids(text, OPEN, kn)


def test_links_by_phase(kn):
    assert "link" in ids("Go to monstertenmath.com/insta", BUILDING, kn)
    assert "link" not in ids("Tap the link in our bio, monstertenmath.com/insta.", OPEN, kn)
    assert "link" in ids("See https://example.com/deal", OPEN, kn)
    # the contact address is fine in either phase
    assert check("Email us at info@monstertenmath.com and we'll help.", BUILDING, kn.rules) == []


def test_stores_only_when_true(kn):
    text = "It's on the App Store now."
    assert "store" in ids(text, Context("open"), kn)
    assert "store" not in ids(text, Context("open", stores=("app_store",)), kn)
    assert "store" in ids("You can download it.", Context("open"), kn)


def test_mentioning_the_person_we_answer_is_fine(kn):
    assert (
        check("@jane_parent Yes! 7 and 3 make 10.", Context("building", "guess", author="jane_parent"), kn.rules) == []
    )


def test_never_open_a_guess_reply_with_no(kn):
    assert "never-no" in ids("No, it was 3.", Context("building", "guess"), kn)
    # ...but a plain question can be answered "No." (the pack's card-for-check reply does)
    assert "never-no" not in ids("No. The check is free and asks for no card.", Context("open", "faq"), kn)


def test_empty_and_long(kn):
    assert ids("   ", BUILDING, kn) == {"empty"}
    assert "too-long" in ids("Thank you! " * 80, BUILDING, kn)
