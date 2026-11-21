"""v1: browser sessions. The engine plans, paces and counts; the Grok Bot clicks."""

from datetime import UTC, datetime, timedelta

import pytest

from monsterbot import browser as browser_mod
from monsterbot.browser import Browser, caps
from monsterbot.config import Config
from monsterbot.errors import Refused
from monsterbot.ledger import Ledger
from tests.conftest import Clock

# Tue 1 Dec 2026, 14:00 Eastern: day 11 of the ramp, inside waking hours.
T0 = datetime(2026, 12, 1, 19, 0, tzinfo=UTC)
CFG = Config(browser_enabled=True)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(browser_mod.time, "sleep", lambda s: None)


@pytest.fixture
def env(tmp_path, kn):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = Clock(T0)

    def make(cfg=CFG, phase="building"):
        return Browser(cfg, kn, ledger, phase, clock)

    yield make, ledger, clock
    ledger.close()


def add_brief(ledger, n, posted=T0 - timedelta(hours=2), comment="Love the counting jars, what a calm way to start!"):
    ids = []
    base = ledger.db.execute("SELECT COUNT(*) FROM brief_posts").fetchone()[0]
    for i in range(n):
        cur = ledger.db.execute(
            "INSERT INTO brief_posts (permalink, creator, caption, posted_at, created_at, comment, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'ready')",
            (
                f"https://www.instagram.com/p/post{base + i}/",
                f"creator{base + i}",
                "c",
                posted.isoformat(),
                T0.isoformat(),
                comment,
            ),
        )
        ids.append(cur.lastrowid)
    return ids


def run_session(b, clock, session, did_for=None):
    """Plays the Bot: next, wait the look time, done; until DONE."""
    out = []
    for _ in range(100):
        line = b.next(session)
        out.append(line)
        if line.startswith("DONE"):
            return out
        seq = int(line.split()[1].split(".")[1])
        step = b.db.execute("SELECT * FROM browser_steps WHERE session=? AND seq=?", (session, seq)).fetchone()
        clock.now += timedelta(seconds=step["dwell_seconds"] + 1)
        if step["kind"] == "check":
            b.done(session, seq, [])
        elif step["kind"] == "verify":
            out.append(b.verify(session, others=b.used_today()["comment"]))
            return out
        else:
            did = (did_for or {}).get(
                step["kind"], {"comment": ["comment", "like"], "follow": ["follow"]}.get(step["kind"], ["like"])
            )
            b.done(session, seq, did)
        clock.now += timedelta(seconds=200)
    raise AssertionError("session never ended")


def test_caps_ramp():
    c = caps(CFG, datetime(2026, 11, 22, 12, tzinfo=UTC))
    assert c["day"]["follow"] == 0 and c["session"]["comment"] == 8
    c = caps(CFG, datetime(2026, 11, 28, 12, tzinfo=UTC))
    assert c["day"]["follow"] == 10
    c = caps(CFG, datetime(2026, 12, 10, 12, tzinfo=UTC))
    assert c["day"]["comment"] == 30 and c["session"]["follow"] == 8


def test_off_by_default(env):
    make, ledger, _ = env
    add_brief(ledger, 2)
    with pytest.raises(Refused, match="off"):
        make(Config()).plan()


def test_plan_holds_brief_posts_and_prints_no_links(env, monkeypatch):
    make, ledger, _ = env
    monkeypatch.setattr(browser_mod.RNG, "random", lambda: 0.99)
    ids = add_brief(ledger, 3)
    b = make()
    s = b.plan()
    assert s == 1
    text = "\n".join(b.plan_lines(s))
    assert "instagram.com/p/" not in text and "counting jars" not in text
    statuses = {
        r[0] for r in ledger.db.execute(f"SELECT status FROM brief_posts WHERE id IN ({','.join(map(str, ids))})")
    }
    assert statuses == {"in-session"}
    kinds = [r[0] for r in ledger.db.execute("SELECT kind FROM browser_steps WHERE session=1 ORDER BY seq")]
    assert kinds[0] == "check" and kinds[-1] == "verify" and kinds.count("comment") == 3


def test_steps_need_the_owner_tap(env):
    make, ledger, _ = env
    add_brief(ledger, 1)
    b = make()
    s = b.plan()
    with pytest.raises(Refused, match="owner"):
        b.start(s, owner_tapped=False)
    with pytest.raises(Refused, match="planned"):
        b.next(s)


def test_a_whole_session_counts_and_verifies(env, monkeypatch):
    make, ledger, clock = env
    monkeypatch.setattr(browser_mod.RNG, "random", lambda: 0.99)
    add_brief(ledger, 2)
    b = make()
    s = b.plan()
    b.start(s, owner_tapped=True)
    out = run_session(b, clock, s)
    assert any(line.startswith("VERIFIED") for line in out)
    assert b.used_today() == {"comment": 2, "like": 2, "follow": 0}
    assert {r[0] for r in ledger.db.execute("SELECT status FROM brief_posts")} == {"done"}
    assert ledger.db.execute("SELECT status FROM browser_sessions WHERE session=?", (s,)).fetchone()[0] == "ended"


def test_gap_is_waited_and_each_step_handed_out_once(env, monkeypatch):
    make, ledger, clock = env
    monkeypatch.setattr(browser_mod.RNG, "random", lambda: 0.99)
    slept = []
    monkeypatch.setattr(browser_mod.time, "sleep", lambda s: slept.append(s))
    add_brief(ledger, 2)
    b = make()
    s = b.plan()
    b.start(s, owner_tapped=True)
    first = b.next(s)  # check
    assert "check" in first
    b.done(s, 0, [])
    step1 = b.next(s)
    assert slept and slept[-1] > 0  # waited the gap before the first action
    assert b.next(s) == step1  # asked again (a timeout): the same step, no new wait


def test_two_early_reports_end_the_session(env, monkeypatch):
    make, ledger, clock = env
    monkeypatch.setattr(browser_mod.RNG, "random", lambda: 0.99)
    add_brief(ledger, 3)
    b = make()
    s = b.plan()
    b.start(s, owner_tapped=True)
    b.next(s)
    b.done(s, 0, [])
    b.next(s)
    assert b.done(s, 1, ["comment", "like"]).startswith("NOTED")  # no time passed: early
    clock.now += timedelta(seconds=300)
    b.next(s)
    assert b.done(s, 2, ["comment", "like"]).startswith("ENDED")
    with pytest.raises(Refused):
        b.next(s)


def test_done_refuses_actions_the_step_doesnt_allow(env):
    make, ledger, clock = env
    add_brief(ledger, 1)
    b = make()
    s = b.plan()
    b.start(s, owner_tapped=True)
    b.next(s)
    with pytest.raises(Refused, match="can't report follow"):
        b.done(s, 0, ["follow"])


def test_stop_cools_down_and_still_records(env, monkeypatch):
    make, ledger, clock = env
    monkeypatch.setattr(browser_mod.RNG, "random", lambda: 0.99)
    add_brief(ledger, 2)
    b = make()
    s = b.plan()
    b.start(s, owner_tapped=True)
    b.next(s)
    b.done(s, 0, [])
    clock.now += timedelta(seconds=200)
    b.next(s)
    clock.now += timedelta(seconds=30)
    assert b.stop("Try again later").startswith("STOPPED")
    assert b.done(s, 1, ["comment", "like"]).startswith("RECORDED")  # a click already made is counted
    assert b.used_today()["comment"] == 1
    add_brief(ledger, 1)
    with pytest.raises(Refused, match="cooling down"):
        b.plan()
    clock.now += timedelta(hours=49)
    b.plan()


def test_quiet_hours(env):
    make, ledger, clock = env
    add_brief(ledger, 1)
    clock.now = datetime(2026, 12, 2, 4, 0, tzinfo=UTC)  # 11 pm Eastern
    with pytest.raises(Refused, match="quiet hours"):
        make().plan()


def test_one_session_at_a_time_and_the_gap(env, monkeypatch):
    make, ledger, clock = env
    monkeypatch.setattr(browser_mod.RNG, "random", lambda: 0.99)
    add_brief(ledger, 1)
    b = make()
    s = b.plan()
    b.start(s, owner_tapped=True)
    run_session(b, clock, s)
    add_brief(ledger, 1, comment="So simple and so clever, thank you!")
    s2 = b.plan()
    with pytest.raises(Refused, match="can start from"):
        b.start(s2, owner_tapped=True)
    clock.now += timedelta(minutes=91)
    s3 = b.plan()  # the old plan is replaced, its posts back in the pool
    assert ledger.db.execute("SELECT status FROM browser_sessions WHERE session=?", (s2,)).fetchone()[0] == "expired"
    assert b.start(s3, owner_tapped=True).startswith("STARTED")


def test_verify_mismatch_pauses(env, monkeypatch):
    make, ledger, clock = env
    monkeypatch.setattr(browser_mod.RNG, "random", lambda: 0.99)
    add_brief(ledger, 1)
    b = make()
    s = b.plan()
    b.start(s, owner_tapped=True)
    for _ in range(10):
        line = b.next(s)
        seq = int(line.split()[1].split(".")[1])
        kind = line.split("·")[1].strip()
        clock.now += timedelta(seconds=60)
        if kind == "check":
            b.done(s, seq, [])
        elif kind == "verify":
            assert b.verify(s, others=5).startswith("MISMATCH")
            break
        else:
            b.done(s, seq, ["comment", "like"])
    add_brief(ledger, 1)
    with pytest.raises(Refused, match="paused"):
        b.plan()
    b.resume(owner_tapped=True)
    clock.now += timedelta(minutes=95)
    assert b.plan()


def test_bad_comment_becomes_a_like(env, monkeypatch):
    make, ledger, _ = env
    monkeypatch.setattr(browser_mod.RNG, "random", lambda: 0.99)
    add_brief(ledger, 1, comment="Your child will be ahead of the class! #math")
    b = make()
    s = b.plan()
    kinds = [r[0] for r in ledger.db.execute("SELECT kind FROM browser_steps WHERE session=? ORDER BY seq", (s,))]
    assert "comment" not in kinds and "like" in kinds


def test_follows_only_from_day_7(env, monkeypatch):
    make, ledger, clock = env
    ledger.upsert_creator("kinder_with_kate", T0, status="shortlist")
    b = make()
    s = b.plan()
    kinds = [r[0] for r in ledger.db.execute("SELECT kind FROM browser_steps WHERE session=?", (s,))]
    assert "follow" in kinds  # day 11
    clock.now = datetime(2026, 11, 22, 18, tzinfo=UTC)  # day 2
    ledger.db.execute("DELETE FROM browser_steps")
    ledger.db.execute("DELETE FROM browser_sessions")
    assert make().plan() == 0  # nothing to do: no follows allowed yet


def test_manual_counts_toward_caps(env):
    make, ledger, _ = env
    b = make()
    b.manual(comments=24)
    assert b._left(1)["comment"] == 1  # day cap 25 on ramp days 7-13
