"""v0.4: "Can I cancel anytime?" is a question about how cancelling works, not a billing problem. It gets the
pack's cancel reply, with the trial terms whole (launch pack README sections 6 and 7). A charge, a refund, the
person's own subscription, a cancel that already happened or a complaint still goes to the owner."""

import copy

import pytest

from monsterbot.config import Config
from monsterbot.policy import Context, check
from monsterbot.triage import triage
from tests.conftest import item_by_external
from tests.test_triage import c

PHASES = [
    ("building", "standard", "building"),
    ("building", "founding", "building"),  # the desk says founding, but launch hasn't happened
    ("open", "standard", "open"),
    ("open", "founding", "open_founding"),
]


def faq(kn, faq_id):
    return next(f for f in kn.faqs if f.id == faq_id)


def sort(kn, text, phase="open", pricing="standard", parent=None):
    return triage(
        c(text, parent="p" if parent else None),
        piece=kn.piece("#7"),
        handle="monstertenmath",
        parent=c("a question", user=parent) if parent else None,
        kn=kn,
        phase=phase,
        stores=(),
        thanks=True,
        pricing=pricing,
    )


def billing(v):
    return (v.category, v.reason) == ("escalate", "billing")


# --- the texts ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("phase, pricing, field", PHASES)
def test_cancel_texts_pass_the_check_where_they_are_used(kn, phase, pricing, field):
    text = getattr(faq(kn, "cancel"), field)
    assert check(text, Context(phase, "faq", pricing=pricing), kn.rules) == []


@pytest.mark.parametrize("field", ["building", "open", "open_founding"])
def test_cancel_texts_carry_every_trial_term(kn, field):
    text = getattr(faq(kn, "cancel"), field)
    for term in ("7-day free trial", "card at signup", "nothing is charged that day", "day 5", "cancel in 2 taps"):
        assert term in text
    if field == "open_founding":
        for term in ("$59.99 a year or $9.99 a month", "first 500 families", "for good", "$79.99 a year"):
            assert term in text
    else:
        assert "$79.99 a year or $12.99 a month" in text
        assert "founding" not in text


def test_standard_cancel_text_isnt_used_while_founding(kn):
    # With the founding price on, a new family pays $59.99, so the standard text would fail the check.
    founding = Context("open", "faq", pricing="founding")
    assert "trial-terms" in {v.id for v in check(faq(kn, "cancel").open, founding, kn.rules)}


# --- questions about how cancelling works get the reply -------------------------------------------------
HOW_IT_WORKS = [
    "Can I cancel anytime?",
    "Can I cancel any time?",
    "can u cancel whenever",
    "Can you cancel at any time?",
    "Is it easy to cancel?",
    "How easy is it to cancel?",
    "Is it hard to cancel?",
    "Is this one of those apps that's impossible to cancel?",
    "Can I cancel during the free week?",
    "Can we cancel before the 7 days are up?",
    "If we don't like it, can we cancel?",
    "What if I want to cancel?",
    "What happens if we cancel?",
    "How does cancelling work?",
    "How would I cancel if it's not for us?",
    "What's your cancellation policy?",
    "Love this! Can I cancel anytime?",
    "Can I cancel if my kid doesn't like it?",
    "Can I cancel it anytime?",
    "If I want to cancel, how does it work?",
    "Is cancelling easy?",
    "Is there a way to cancel?",
    "Will I be able to cancel?",
]


@pytest.mark.parametrize("text", HOW_IT_WORKS)
@pytest.mark.parametrize("phase, pricing, field", PHASES)
def test_how_cancelling_works_gets_the_cancel_reply(kn, text, phase, pricing, field):
    v = sort(kn, text, phase=phase, pricing=pricing)
    assert (v.category, v.tier, v.reason) == ("faq:cancel", "auto", "cancel")
    assert v.reply == getattr(faq(kn, "cancel"), field)


def test_never_the_billing_holding_line(kn):
    holding = kn.holding["billing"]
    for text in HOW_IT_WORKS:
        assert sort(kn, text).reply != holding


def test_a_statement_isnt_a_question(kn):
    # question_only: "Easy to cancel, love it" is a parent telling us, not asking.
    assert sort(kn, "Love that it's easy to cancel").category != "faq:cancel"


# --- real billing problems still go to the owner --------------------------------------------------------
STILL_BILLING = [
    # a charge or a refund
    "I was charged, can I cancel?",
    "Can I cancel before I get charged?",
    "Can I cancel and get a refund?",
    "Is it easy to cancel? I got charged twice",
    "Can I cancel and get my money back?",
    "Can I cancel anytime or will you bill me for the year?",
    # the person's own subscription or account
    "How do I cancel my subscription?",
    "Can I cancel my subscription?",
    "Can I cancel my account?",
    "Can we cancel our membership anytime?",
    "Can I cancel my free trial?",
    "Please cancel my account?",
    "Can you cancel it for me?",
    # a cancel that already happened
    "I cancelled but it still says I'm a member?",
    "I canceled yesterday, is that it?",
    "Cancelled yesterday. Can I cancel anytime and come back?",
    # a complaint
    "Why can't I cancel?",
    "I tried to cancel and it won't let me?",
    "Can I cancel anytime? This app is useless",
    "Is it easy to cancel or is this a scam?",
    "Can I cancel anytime or is that a rip off too?",
    # how to do it, now: likely a member, and only the owner knows where they are
    "How do I cancel?",
    # not about cancelling at all
    "I was charged twice",
    "I want a refund",
    "I want to cancel.",
    "We need to cancel, can we cancel today?",
]


@pytest.mark.parametrize("text", STILL_BILLING)
@pytest.mark.parametrize("phase, pricing", [("building", "standard"), ("open", "standard"), ("open", "founding")])
def test_real_billing_problems_still_escalate(kn, text, phase, pricing):
    v = sort(kn, text, phase=phase, pricing=pricing)
    assert v.category == "escalate"
    assert v.reason in ("billing", "complaint")
    if v.reason == "billing":
        assert v.reply == kn.holding["billing"]


def test_founding_question_isnt_taken_by_the_cancel_reply(kn):
    # "If I cancel, do I keep the founding price?" is the founding faq's. While the founding price isn't on, only
    # the owner can answer it (they know who is a founding family), so it stays with them, not the cancel reply.
    for text in ("If I cancel, do I keep the founding price?", "What if I cancel, do I keep my price?"):
        assert sort(kn, text, pricing="founding").category == "faq:founding"
        assert billing(sort(kn, text, pricing="standard"))
        assert billing(sort(kn, text, phase="building"))


def test_cancel_reply_is_for_top_level_comments_and_dms(kn):
    # Under another person's comment the bot never posts an faq reply (a person writes back, or nothing). That path
    # is unchanged by this: there, a cancel question still escalates.
    assert sort(kn, "Can I cancel anytime?", parent="other_parent").category != "faq:cancel"


# --- a whole sweep --------------------------------------------------------------------------------------
def test_sweep_answers_cancel_questions_and_escalates_charges(make_engine, fixture_data):
    data = copy.deepcopy(fixture_data)
    m3 = next(m for m in data["media"] if m["id"] == "m3")
    m3["comments"] += [
        {
            "id": "c90",
            "text": "Can I cancel anytime?",
            "username": "maybe_mom",
            "timestamp": "2026-11-20T01:50:00+0000",
        },
        {
            "id": "c91",
            "text": "I cancelled but was charged?",
            "username": "upset_dad",
            "timestamp": "2026-11-20T01:51:00+0000",
        },
    ]
    data["conversations"].append(
        {
            "id": "t90",
            "messages": [
                {
                    "id": "dm90",
                    "from": {"id": "u900", "username": "dm_parent"},
                    "text": "Is it easy to cancel?",
                    "timestamp": "2026-11-20T01:52:00+0000",
                }
            ],
        }
    )
    engine, fake = make_engine(phase="open", mode="live", cfg=Config(first_comments=False, dms_enabled=True), data=data)
    engine.sweep()
    cancel = faq(engine.kn, "cancel")
    comments = {p["parent"]: p["text"] for p in fake.posted if p.get("parent")}
    dms = {p["to"]: p["text"] for p in fake.posted if p["kind"] == "dm"}
    assert comments["c90"] == cancel.open
    assert item_by_external(engine, "c90").category == "faq:cancel"
    assert comments["c91"] == engine.kn.holding["billing"]
    assert item_by_external(engine, "c91").category == "escalate"
    assert dms["u900"] == cancel.open
