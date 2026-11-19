"""v0.4: the founding price ($59.99 a year or $9.99 a month for the first 500 families, theirs for good), on
from launch day only while the owner has it on, and never a count of places left."""

import pytest

from monsterbot.config import Config
from monsterbot.desk import Desk
from monsterbot.policy import Context, check
from tests.conftest import NOW, item_by_external
from tests.test_cli import run  # noqa: F401  (the CLI fixture)
from tests.test_triage import c

BUILDING = Context("building")
OPEN = Context("open")
FOUNDING = Context("open", pricing="founding")

FOUNDING_OK = (
    "The check is free. Then a 7-day free trial: you add a card at signup and nothing is charged that day. "
    "We remind you on day 5, and you can cancel in 2 taps. After the 7 days it's $59.99 a year or $9.99 a month. "
    "That's our founding price for the first 500 families who sign up, and it's yours for good, even if you "
    "cancel and come back later. After the first 500, it's $79.99 a year or $12.99 a month."
)
STANDARD_OK = (
    "The check is free. Then a 7-day free trial: you add a card at signup and nothing is charged that day. "
    "We remind you on day 5, and you can cancel in 2 taps. After the 7 days it's $79.99 a year or $12.99 a month."
)


def ids(text, ctx, kn):
    return {v.id for v in check(text, ctx, kn.rules)}


def faq(kn, faq_id):
    return next(f for f in kn.faqs if f.id == faq_id)


# --- the desk and the command ---------------------------------------------------------------------------
def test_pricing_defaults_to_standard_and_is_logged(tmp_path):
    desk = Desk(tmp_path)
    assert desk.pricing() == "standard"
    desk.ensure()
    (desk.state / "pricing").write_text("FOUNDING!!\n")
    assert desk.pricing() == "standard"  # anything unexpected reads as the safe default
    desk.set_pricing("founding", NOW)
    assert desk.pricing() == "founding"
    assert "pricing standard -> founding" in (desk.state / "changes.log").read_text()
    with pytest.raises(ValueError):
        desk.set_pricing("half-price", NOW)


def test_phase_label_shows_the_founding_price(tmp_path):
    desk = Desk(tmp_path)
    assert desk.phase_label() == "building"
    desk.set_pricing("founding", NOW)
    assert desk.phase_label() == "building · founding price from launch"
    desk.set_phase("open", NOW)
    assert desk.phase_label() == "open · founding price"


def test_pricing_needs_the_tap(run):  # noqa: F811
    assert run("pricing")[1].startswith("PRICING: standard")
    code, out = run("pricing", "founding")
    assert code == 1 and "needs your tap" in out
    code, out = run("pricing", "founding", "--owner-tapped")
    assert code == 0 and out.startswith("PRICING: founding.")
    assert run("pricing", "show")[1].startswith("PRICING: founding")
    assert "pricing founding" in run("status")[1]
    run("phase", "open", "--owner-tapped")
    assert run("sweep")[1].startswith("SWEEP · REHEARSAL · open · founding price")


# --- the check ------------------------------------------------------------------------------------------
def test_founding_text_passes_only_while_founding_is_in_force(kn):
    assert check(FOUNDING_OK, FOUNDING, kn.rules) == []
    assert {"founding-off", "price"} <= ids(FOUNDING_OK, OPEN, kn)  # closed, or not on the site
    building = Context("building", pricing="founding")  # the desk says founding, but launch hasn't happened
    assert "founding-off" in ids(FOUNDING_OK, building, kn)


def test_standard_text_fails_while_founding(kn):
    assert check(STANDARD_OK, OPEN, kn.rules) == []
    assert "trial-terms" in ids(STANDARD_OK, FOUNDING, kn)  # a new family would pay $59.99, not $79.99


@pytest.mark.parametrize(
    "drop, keep",
    [
        ("for the first 500 families who sign up", "for families"),
        ("it's yours for good, even if you cancel and come back later", "it's yours"),
        ("$59.99 a year", "$59.99 yearly"),
    ],
)
def test_founding_terms_whole_or_not_at_all(kn, drop, keep):
    assert "trial-terms" in ids(FOUNDING_OK.replace(drop, keep), FOUNDING, kn)


def test_founding_price_named_without_a_dollar_still_needs_its_terms(kn):
    assert "trial-terms" in ids("Yes, the founding price is still on!", FOUNDING, kn)
    assert "founding-off" in ids("Sorry, the founding price is closed.", OPEN, kn)


def test_founding_prices_are_real_only_while_founding(kn):
    assert "price" in ids(STANDARD_OK.replace("$12.99 a month", "$9.99 a month"), OPEN, kn)
    assert "price" not in ids(FOUNDING_OK, FOUNDING, kn)
    assert "price" in ids(FOUNDING_OK.replace("$9.99", "$8.99"), FOUNDING, kn)


@pytest.mark.parametrize(
    "text",
    [
        "Only 40 spots left!",
        "There are 12 places left.",
        "Just 37 families to go.",
        "Spots are filling fast.",
        "Grab it while it lasts.",
        "Sign up before it's gone.",
        "It's almost full.",
        "Limited spots, act now.",
        "We're nearly sold out.",
        "Only 3 left.",
    ],
)
def test_never_a_count_of_places_left(kn, text):
    assert "no-scarcity" in ids(text, FOUNDING, kn)
    assert "no-scarcity" in ids(text, BUILDING, kn)


def test_the_plain_fact_passes(kn):
    assert "no-scarcity" not in ids(FOUNDING_OK, FOUNDING, kn)
    assert "no-scarcity" not in ids("It's for the first 500 families who sign up.", FOUNDING, kn)


# --- sorting comments -----------------------------------------------------------------------------------
def sort(kn, text, phase="open", pricing="founding"):
    from monsterbot.triage import triage

    return triage(
        c(text),
        piece=kn.piece("#7"),
        handle="monstertenmath",
        parent=None,
        kn=kn,
        phase=phase,
        stores=(),
        thanks=True,
        pricing=pricing,
    )


def billing(v):
    return (v.category, v.reason) == ("escalate", "billing")


def test_price_question_gets_the_price_in_force(kn):
    assert sort(kn, "How much is it?").reply == faq(kn, "price").open_founding
    assert sort(kn, "How much is it?", pricing="standard").reply == faq(kn, "price").open
    assert sort(kn, "How much is it?", phase="building", pricing="founding").reply == faq(kn, "price").building
    assert sort(kn, "Do I need a card for the check?").reply == faq(kn, "card-for-check").open_founding


@pytest.mark.parametrize(
    "text",
    [
        "How much is the founding price?",
        "How many spots are left?",
        "Is it the first 500 families only?",
        "Do I keep my price if I take a break?",
    ],
)
def test_founding_questions(kn, text):
    v = sort(kn, text)
    assert (v.category, v.tier, v.reply) == ("faq:founding", "auto", faq(kn, "founding").open_founding)
    closed = sort(kn, text, pricing="standard")
    assert (closed.category, closed.tier) == ("faq:founding", "draft")  # the owner answers once it's closed


def test_cancel_question_is_about_the_founding_price_not_billing(kn):
    text = "If I cancel, do I keep the founding price?"
    v = sort(kn, text)
    assert (v.category, v.tier, v.reply) == ("faq:founding", "auto", faq(kn, "founding").open_founding)
    assert billing(sort(kn, text, pricing="standard"))
    assert billing(sort(kn, text, phase="building"))


def test_a_charge_is_still_billing(kn):
    assert billing(sort(kn, "I was charged twice, is the founding price gone?"))
    assert billing(sort(kn, "Can I get a refund and keep the founding price?"))
    assert billing(sort(kn, "Is the founding price a scam?"))


# --- a whole sweep --------------------------------------------------------------------------------------
def test_sweep_quotes_the_founding_price_only_when_on(make_engine):
    engine, fake = make_engine(phase="open", mode="live", cfg=Config(first_comments=False))
    engine.desk.set_pricing("founding", NOW)
    engine.sweep()
    sent = {p["parent"]: p["text"] for p in fake.posted if p.get("parent")}
    assert "$59.99 a year" in sent["c4"] and "first 500 families" in sent["c4"]
    assert item_by_external(engine, "c4").status == "replied"

    engine2, fake2 = make_engine(phase="open", mode="live", cfg=Config(first_comments=False))
    engine2.sweep()
    sent2 = {p["parent"]: p["text"] for p in fake2.posted if p.get("parent")}
    assert "$79.99 a year" in sent2["c4"] and "founding" not in sent2["c4"]
