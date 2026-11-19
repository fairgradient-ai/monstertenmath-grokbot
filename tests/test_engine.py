"""Whole sweeps and the owner's commands, against the fake Instagram."""

from datetime import timedelta

import pytest

from monsterbot.config import Config
from monsterbot.errors import ChannelError, Refused
from tests.conftest import NOW, Clock, item_by_external


def test_rehearsal_posts_nothing(make_engine):
    engine, fake = make_engine(mode="rehearsal")
    res = engine.sweep()
    assert fake.posted == [] and fake.hidden == []
    assert len(res.would_reply) == 11  # 10 canned replies and 1 holding line
    assert len(res.first_comments) == 2


def test_live_posts_canned_replies_once(make_engine):
    engine, fake = make_engine(mode="live")
    res = engine.sweep()
    replies = [p for p in fake.posted if p["kind"] == "reply"]
    comments = [p for p in fake.posted if p["kind"] == "comment"]
    assert len(replies) == len(res.replied) == 11
    assert {p["parent"] for p in comments} == {"m3", "m14"}
    by_parent = {p["parent"]: p["text"] for p in replies}
    assert by_parent["c1"] == "Yes! 7 and 3 make 10."
    assert by_parent["c2"].startswith("Let's check!")
    # a second sweep posts nothing new
    engine.sweep()
    assert len(fake.posted) == 13


def test_rehearsal_then_live_does_the_planned_work(make_engine):
    engine, fake = make_engine(mode="rehearsal")
    planned = {i for i, _ in engine.sweep().would_reply}
    engine.desk.set_mode("live", NOW)
    done = {i for i, _ in engine.sweep().replied}
    assert planned == done


def test_waiting_items_are_sorted_for_the_owner(make_engine):
    engine, _ = make_engine(mode="live")
    engine.sweep()
    assert item_by_external(engine, "c7").category == "spam"
    billing = item_by_external(engine, "c8")
    assert billing.reason == "billing" and billing.status == "replied"
    assert "info@monstertenmath.com" in billing.reply_text
    assert item_by_external(engine, "c9").status == "queued"
    assert item_by_external(engine, "c6").status == "skipped"  # friends tagging friends
    assert item_by_external(engine, "c9r1").status == "skipped"  # chat in someone else's thread
    assert item_by_external(engine, "d0").status == "skipped"  # our own comment


def test_one_canned_reply_per_person_per_post_a_day(make_engine):
    engine, fake = make_engine(mode="live")
    engine.sweep()
    second = item_by_external(engine, "c11")
    assert second.status == "queued" and "second comment" in second.reason
    assert [p["parent"] for p in fake.posted].count("c11") == 0


def test_thank_you_lines_take_turns_on_a_post(make_engine):
    engine, fake = make_engine(mode="live")
    engine.sweep()
    texts = {p["parent"]: p["text"] for p in fake.posted}
    assert texts["c5"] != texts["c12"]


def test_caps_hold_replies_for_the_next_sweep(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(max_auto_replies_per_sweep=3))
    res = engine.sweep()
    assert len(res.replied) == 3 and res.held > 0
    res2 = engine.sweep()
    assert len(res2.replied) == 3


def test_old_comments_become_drafts(make_engine):
    clock = Clock(NOW + timedelta(days=4))
    engine, fake = make_engine(mode="live", clock=clock, cfg=Config(first_comments=False))
    res = engine.sweep()
    assert res.replied == []
    old = item_by_external(engine, "c1")
    assert old.status == "drafted" and old.draft_text == "Yes! 7 and 3 make 10."


def test_first_comment_not_posted_twice_or_over_ours(make_engine, fixture_data):
    engine, fake = make_engine(mode="live")
    engine.sweep()
    fake.posted.clear()  # the owner deleted it: never repost
    engine.sweep()
    assert not [p for p in fake.posted if p["kind"] == "comment"]

    data = fixture_data
    data["media"][1]["comments"].append(
        {
            "id": "own1",
            "text": "How many? Type it!",
            "username": "monstertenmath",
            "timestamp": "2026-11-20T01:31:00+0000",
        }
    )
    engine2, fake2 = make_engine(mode="live", data=data)
    engine2.sweep()
    assert [p["parent"] for p in fake2.posted if p["kind"] == "comment"] == ["m14"]


def test_rate_limit_stops_the_sweep(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False))
    original = fake.reply
    calls = {"n": 0}

    def flaky(comment_id, text):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ChannelError("rate limited", "rate", code=4)
        return original(comment_id, text)

    fake.reply = flaky
    res = engine.sweep()
    assert res.stopped == "rate"
    assert len(res.replied) == 1 and calls["n"] == 2


def test_timeout_is_verified_before_any_retry(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False, max_auto_replies_per_sweep=1))
    original = fake.reply

    def lands_then_times_out(comment_id, text):
        original(comment_id, text)  # it reached Instagram...
        raise ChannelError("timed out", "network", ambiguous=True)  # ...but we never heard back

    fake.reply = lands_then_times_out
    engine.sweep()
    first = item_by_external(engine, "c1")
    assert first.status == "unverified"

    fake.reply = original
    engine.sweep()
    first = item_by_external(engine, "c1")
    assert first.status == "replied"
    assert [p["parent"] for p in fake.posted].count("c1") == 1


def test_draft_and_send_flow(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()
    q = item_by_external(engine, "c9")
    item, violations = engine.draft(q.id, "Our games start at 4. At 3, try the counting part together!")
    assert violations == [] and item.status == "drafted"

    with pytest.raises(Refused):
        engine.send([q.id], owner_tapped=False)
    lines = engine.send([q.id], owner_tapped=True)
    assert lines[0].startswith("SENT")
    assert fake.posted[-1]["parent"] == "c9"
    assert item_by_external(engine, "c9").status == "replied"
    assert engine.send([q.id], owner_tapped=True)[0].startswith("NOT SENT")  # never twice


def test_a_draft_that_fails_the_check_is_held(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()
    q = item_by_external(engine, "c9")
    _, violations = engine.draft(q.id, "Sign up now, link in bio! Your child will love it #earlymath")
    assert violations
    before = len(fake.posted)
    assert engine.send([q.id], owner_tapped=True)[0].startswith("NOT SENT")
    assert len(fake.posted) == before
    assert engine.drafted_ids() == []
    assert engine.send([q.id], owner_tapped=True, force_lint=True)[0].startswith("SENT")


def test_rehearsal_send_posts_nothing(make_engine):
    engine, fake = make_engine(mode="rehearsal")
    engine.sweep()
    q = item_by_external(engine, "c9")
    engine.draft(q.id, "Our games start at 4.")
    assert engine.send([q.id], owner_tapped=True)[0].startswith("REHEARSAL")
    assert fake.posted == []


def test_reply_to_a_reply_goes_under_the_parent_with_a_mention(make_engine, fixture_data):
    data = fixture_data
    data["media"][1]["comments"][8]["replies"].append(
        {
            "id": "c9r2",
            "text": "Same here, does it work at 3?",
            "username": "asker_two",
            "timestamp": "2026-11-20T01:49:00+0000",
        }
    )
    engine, fake = make_engine(mode="live", data=data, cfg=Config(first_comments=False))
    engine.sweep()
    q = item_by_external(engine, "c9r2")
    assert q.status == "queued"
    engine.draft(q.id, "Our games start at 4.")
    engine.send([q.id], owner_tapped=True)
    assert fake.posted[-1] == {
        "kind": "reply",
        "id": fake.posted[-1]["id"],
        "parent": "c9",
        "text": "@asker_two Our games start at 4.",
    }


def test_hide_and_discard(make_engine):
    engine, fake = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()
    spam = item_by_external(engine, "c7")
    with pytest.raises(Refused):
        engine.hide([spam.id], owner_tapped=False)
    engine.hide([spam.id], owner_tapped=True)
    assert fake.hidden == ["c7"]
    other = item_by_external(engine, "c9")
    engine.discard([other.id])
    assert item_by_external(engine, "c9").status == "discarded"


def test_open_phase_changes_the_answers(make_engine):
    engine, fake = make_engine(mode="live", phase="open", cfg=Config(first_comments=False))
    engine.sweep()
    texts = {p["parent"]: p["text"] for p in fake.posted}
    assert texts["d1"].startswith("Tap the link in our bio")
    assert texts["d2"].startswith("Now! Start with the free 2-minute check")


def test_wrong_account_is_refused(make_engine):
    engine, _ = make_engine(cfg=Config(username="someone_else"))
    with pytest.raises(Refused):
        engine.sweep()


def test_a_timeout_that_never_landed_is_retried_later(make_engine):
    clock = Clock()
    engine, fake = make_engine(mode="live", clock=clock, cfg=Config(first_comments=False, max_auto_replies_per_sweep=1))
    original = fake.reply

    def times_out(comment_id, text):
        raise ChannelError("timed out", "network", ambiguous=True)

    fake.reply = times_out
    engine.sweep()
    assert item_by_external(engine, "c1").status == "unverified"

    fake.reply = original
    engine.sweep()  # too soon to give up on it: nothing is retried
    assert item_by_external(engine, "c1").status == "unverified"

    clock.now = NOW + timedelta(minutes=10)
    engine.sweep()  # not on Instagram after 10 minutes: marked for retry...
    engine.sweep()  # ...and answered once
    assert item_by_external(engine, "c1").status == "replied"
    assert [p["parent"] for p in fake.posted].count("c1") == 1
