"""v1.1: Grok engages from the home feed (it picks, the engine checks), follows from day 0, and the owner's
standing yes ("auto engage on") lets routines run sessions."""

from datetime import timedelta

import pytest

from monsterbot import browser as browser_mod
from monsterbot.brief import Brief
from monsterbot.browser import Browser
from monsterbot.errors import Refused
from monsterbot.ledger import Ledger
from tests.conftest import Clock
from tests.test_browser import CFG, FEED, T0, add_brief


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(browser_mod.time, "sleep", lambda s: None)


@pytest.fixture
def env(tmp_path, kn):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = Clock(T0)

    def make(cfg=FEED, phase="building"):
        return Browser(cfg, kn, ledger, phase, clock)

    yield make, ledger, clock
    ledger.close()


LINK = "https://www.instagram.com/p/AbC123/"
GOOD = "The cardboard tube ramp is genius, my kids would race cars down it all afternoon!"


def started(make, cfg=FEED):
    b = make(cfg)
    s = b.plan()
    assert s
    b.start(s, owner_tapped=True)
    b.next(s)
    b.done(s, 0, [])
    return b, s


def feed_step(b, s, clock):
    line = b.next(s)
    assert "· feed ·" in line and "instagram.com/ (our home feed)" in line
    assert "pick S" in line and "Don't like, comment or follow" in line
    return int(line.split()[1].split(".")[1])


def test_plan_has_feed_steps(env):
    make, ledger, _ = env
    b = make(FEED)
    s = b.plan()
    kinds = [r[0] for r in ledger.db.execute("SELECT kind FROM browser_steps WHERE session=? ORDER BY seq", (s,))]
    assert kinds.count("feed") == 2
    assert "home feed" not in "\n".join(b.plan_lines(s))


def test_pick_checks_then_hands_out_the_actions(env):
    make, ledger, clock = env
    b, s = started(make)
    seq = feed_step(b, s, clock)
    with pytest.raises(Refused, match="has no post yet"):
        b.done(s, seq, ["like"])
    out = b.pick(s, seq, LINK + "?igsh=xyz", "@Playful.Mum", comment=GOOD, follow=True)
    assert out.startswith(f"STEP S{s}.{seq} · feed · open {LINK} and like it, comment, follow @playful.mum")
    assert GOOD in out and "--did like,comment,follow" in out
    clock.now += timedelta(seconds=30)
    assert b.done(s, seq, ["like", "comment", "follow"]).startswith("OK")
    assert b.used_today() == {"comment": 1, "like": 1, "follow": 1}
    assert ledger.db.execute("SELECT source FROM follows WHERE username='playful.mum'").fetchone()[0] == "browser-feed"


def test_pick_refuses_bad_posts_and_comments(env):
    make, ledger, clock = env
    b, s = started(make)
    seq = feed_step(b, s, clock)
    with pytest.raises(Refused, match="isn't a post link"):
        b.pick(s, seq, "https://www.instagram.com/playful.mum/", "playful.mum", comment=GOOD)
    with pytest.raises(Refused, match="never engage"):
        b.pick(s, seq, LINK, "funexpected", comment=GOOD)
    with pytest.raises(Refused, match="never engage"):
        b.pick(s, seq, LINK, "monstertenmath", comment=GOOD)
    with pytest.raises(Refused, match="giveaway"):
        b.pick(s, seq, LINK, "playful.mum", comment=GOOD, caption="GIVEAWAY time! Enter to win")
    with pytest.raises(Refused, match="didn't pass the check"):
        b.pick(s, seq, LINK, "playful.mum", comment="Try monstertenmath.com, your kid will get ahead! #math")
    with pytest.raises(Refused, match="write the comment"):
        b.pick(s, seq, LINK, "playful.mum")
    # nothing changed: the step still waits for a pick
    assert ledger.db.execute("SELECT target FROM browser_steps WHERE session=? AND seq=?", (s, seq)).fetchone()[0] == (
        "feed"
    )
    out = b.pick(s, seq, LINK, "playful.mum", like_only=True)
    assert "--did like" in out and "comment, exactly" not in out
    clock.now += timedelta(seconds=30)
    with pytest.raises(Refused, match="can't report comment"):
        b.done(s, seq, ["like", "comment"])
    with pytest.raises(Refused, match="can't report follow"):
        b.done(s, seq, ["like", "follow"])  # follow wasn't asked for in the pick


def test_no_post_or_comment_twice_and_one_pick_per_account_a_week(env):
    make, ledger, clock = env
    b, s = started(make)
    seq = feed_step(b, s, clock)
    b.pick(s, seq, LINK, "playful.mum", comment=GOOD)
    clock.now += timedelta(seconds=30)
    b.done(s, seq, ["like", "comment"])
    clock.now += timedelta(seconds=200)
    seq2 = feed_step(b, s, clock)
    with pytest.raises(Refused, match="already engaged"):
        b.pick(s, seq2, LINK, "someone.else", comment="What a lovely calm morning routine, thank you!")
    with pytest.raises(Refused, match="last 7 days"):
        b.pick(s, seq2, "https://www.instagram.com/reel/Zz9/", "playful.mum", comment="Such a sweet idea!")
    with pytest.raises(Refused, match="used before"):
        b.pick(s, seq2, "https://www.instagram.com/reel/Zz9/", "dad.at.play", comment=GOOD)
    # the brief's own check knows feed comments too
    add_brief(ledger, 1, comment=None)
    bid = ledger.db.execute("SELECT MAX(id) FROM brief_posts").fetchone()[0]
    ledger.db.execute("UPDATE brief_posts SET status='proposed' WHERE id=?", (bid,))
    brief = Brief(CFG, b.kn, ledger, None, "building", T0)
    assert any("used before" in v for v in brief.comment(bid, GOOD))


def test_follow_on_a_pick_respects_the_caps(env):
    make, ledger, clock = env
    b, s = started(make)
    b.manual(follows=20)  # day 11: day cap 20
    seq = feed_step(b, s, clock)
    out = b.pick(s, seq, LINK, "playful.mum", comment=GOOD, follow=True)
    assert "no follow: today's follows are used up" in out and "--did like,comment " in out


def test_warm_list_sources(env):
    make, ledger, _ = env
    ledger.upsert_creator("kate_shortlist", T0, status="shortlist", score=70)
    ledger.upsert_creator("new_good", T0, status="new", score=75)
    ledger.upsert_creator("new_weak", T0, status="new", score=20)
    ledger.upsert_creator("said_no", T0, status="declined", score=90)
    names = make(CFG).warm_list()
    assert names[:2] == ["kate_shortlist", "new_good"]
    assert "new_weak" not in names and "said_no" not in names


def test_auto_engage(env):
    make, ledger, clock = env
    add_brief(ledger, 1)
    b = make(CFG)
    s = b.plan()
    with pytest.raises(Refused, match="auto engage is off"):
        b.start(s, owner_tapped=False, auto=True)
    with pytest.raises(Refused, match="owner's tap"):
        b.auto(True, owner_tapped=False)
    assert b.auto(True, owner_tapped=True).startswith("AUTO ON")
    assert "auto engage on" in b.status()[0]
    assert b.start(s, owner_tapped=False, auto=True).startswith("STARTED")
    b.stop("Try again later")
    assert not b.auto_on()  # any warning: the owner decides again
    assert b.auto(False, owner_tapped=False).startswith("AUTO OFF")


def test_feed_steps_skip_when_caps_are_spent(env, monkeypatch):
    make, ledger, clock = env
    monkeypatch.setattr(browser_mod.RNG, "random", lambda: 0.99)
    b, s = started(make)
    b.manual(comments=25, likes=50)
    line = b.next(s)  # both feed steps skipped (no comment or like left): straight to verify
    assert "· verify ·" in line
    assert [r[0] for r in ledger.db.execute("SELECT status FROM browser_steps WHERE kind='feed'")] == ["skipped"] * 2


def test_a_feed_session_ends_with_verify(env):
    make, ledger, clock = env
    b, s = started(make)
    for _ in range(2):
        clock.now += timedelta(seconds=200)
        seq = feed_step(b, s, clock)
        b.pick(s, seq, f"https://www.instagram.com/p/Feed{seq}/", f"parent{seq}", comment=f"Such a lovely idea {seq}!")
        clock.now += timedelta(seconds=30)
        b.done(s, seq, ["like", "comment"])
    clock.now += timedelta(seconds=200)
    assert "· verify ·" in b.next(s)
    assert b.verify(s, others=2).startswith("VERIFIED")
