"""v0.2: written replies that post themselves, holding lines, DMs, and learning from the owner."""

from datetime import timedelta

from monsterbot.config import Config
from tests.conftest import NOW, Clock, item_by_external


def dm_item(engine, external_id):
    return engine.ledger.by_external("instagram-dm", external_id)


def test_a_written_reply_that_passes_posts_itself(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()
    q = item_by_external(engine, "c9")
    item, violations, outcome = engine.reply(
        q.id, "Our lessons are made for 4 to 6. Plenty of 3-year-olds love the cracker part with you, though."
    )
    assert violations == [] and outcome == "sent"
    assert fake.posted[-1]["parent"] == "c9"
    done = item_by_external(engine, "c9")
    assert done.status == "replied" and done.sent_by == "bot"


def test_a_written_reply_that_fails_is_held(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()
    before = len(fake.posted)
    q = item_by_external(engine, "c9")
    _, violations, outcome = engine.reply(q.id, "Sign up now and your child will be ahead! #earlymath")
    assert violations and outcome == "held"
    assert len(fake.posted) == before
    assert item_by_external(engine, "c9").status == "drafted"


def test_sensitive_ones_wait_for_the_owner(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()
    adhd = item_by_external(engine, "c13")
    assert adhd.tier == "owner" and adhd.reason == "child-or-health"
    before = len(fake.posted)
    _, violations, outcome = engine.reply(adhd.id, "Every child is different. We'd love to hear more by email.")
    assert violations == [] and outcome.startswith("waits for your OK")
    assert len(fake.posted) == before
    assert engine.send([adhd.id], owner_tapped=True)[0].startswith("SENT")


def test_written_replies_respect_rehearsal_and_the_switch(make_engine):
    engine, fake = make_engine(mode="rehearsal")
    engine.sweep()
    q = item_by_external(engine, "c9")
    assert engine.reply(q.id, "Our lessons are made for 4 to 6.")[2] == "rehearsal"
    assert fake.posted == []
    engine2, fake2 = make_engine(mode="live", cfg=Config(first_comments=False, autosend_written=False))
    engine2.sweep()
    q2 = item_by_external(engine2, "c9")
    assert engine2.reply(q2.id, "Our lessons are made for 4 to 6.")[2].startswith("waits for your send")


def test_written_replies_count_toward_the_daily_cap(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False, max_auto_replies_per_day=11))
    engine.sweep()  # 11 canned replies and holding lines
    q = item_by_external(engine, "c9")
    assert engine.reply(q.id, "Our lessons are made for 4 to 6.")[2].startswith("held: the daily cap")


def test_dms(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False, dms_enabled=True))
    res = engine.sweep()
    assert res.threads == 5
    dms = {p["to"]: p["text"] for p in fake.posted if p["kind"] == "dm"}
    assert dms["u100"].startswith("At launch: a 7-day free trial")  # canned price answer
    assert dms["u200"].startswith("We'd love to hear more!")  # business: holding line
    assert "u300" not in dms and "u400" not in dms and "u500" not in dms
    assert dm_item(engine, "dm3").status == "queued"  # a question: written by the Grok Bot
    assert dm_item(engine, "dm4") is None  # answered by the owner in the app
    late = dm_item(engine, "dm6")
    assert late.status == "queued" and late.tier == "owner" and "24-hour window" in late.reason
    assert engine.reply(late.id, "Very soon!")[2].startswith("outside Meta's 24-hour")

    kindle = dm_item(engine, "dm3")
    assert (
        engine.reply(kindle.id, "It's made for iPhone and Android phones. We'll say here if tablets join.")[2] == "sent"
    )
    assert fake.posted[-1] == {
        "kind": "dm",
        "id": fake.posted[-1]["id"],
        "thread": "t3",
        "to": "u300",
        "text": "It's made for iPhone and Android phones. We'll say here if tablets join.",
    }
    engine.sweep()  # our message is now in the thread: nothing is answered twice
    assert [p["to"] for p in fake.posted if p["kind"] == "dm"].count("u300") == 1


def test_a_newer_dm_replaces_the_older_item(make_engine, fixture_data):
    clock = Clock()
    engine, fake = make_engine(mode="rehearsal", cfg=Config(dms_enabled=True), data=fixture_data, clock=clock)
    engine.sweep()
    first = dm_item(engine, "dm3")
    fake.fixture["conversations"][2]["messages"].append(
        {
            "id": "dm3b",
            "from": {"id": "u300", "username": "dad_jo"},
            "text": "Or an old iPad?",
            "timestamp": "2026-11-20T01:58:00+0000",
        }
    )
    clock.now = NOW + timedelta(minutes=5)
    engine.sweep()
    assert dm_item(engine, "dm3").status == "skipped" and first.id == dm_item(engine, "dm3").id
    newer = dm_item(engine, "dm3b")
    assert newer.status == "queued" and "Kindle Fire" in newer.text and "old iPad" in newer.text


def test_learning_from_replies_typed_in_the_app(make_engine):
    engine, _ = make_engine(mode="live", cfg=Config(first_comments=False, dms_enabled=True))
    res = engine.sweep()
    assert res.learned == 2
    learned = {r["final"]: r["incoming"] for r in engine.ledger.examples()}
    assert learned["Our team drew him! Thank you, he says hi."].startswith("Who drew the Monster?")
    assert learned["He's just the Monster! He loves crackers."] == "Is the Monster a boy or a girl?"
    assert item_by_external(engine, "d3").status == "skipped"  # the owner already answered it
    assert engine.sweep().learned == 0  # learned once


def test_owner_edits_and_approvals_become_examples(make_engine):
    engine, _ = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()
    adhd = item_by_external(engine, "c13")
    engine.draft(adhd.id, "Every child is different.", by="bot")
    engine.draft(
        adhd.id, "Thank you for asking. Every child is different: write to us at info@monstertenmath.com.", by="owner"
    )
    engine.send([adhd.id], owner_tapped=True)
    rows = engine.ledger.examples()
    assert rows[0]["source"] == "owner-edit"
    assert rows[0]["bot_draft"] == "Every child is different."
