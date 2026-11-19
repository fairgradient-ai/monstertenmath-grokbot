"""v0.2: finding creators (read-only) and Collab outreach by email (on the owner's tap)."""

import json
from datetime import UTC, datetime

import pytest

from monsterbot.channels.fake import FakeEmail, FakeGraph
from monsterbot.config import Config
from monsterbot.errors import ChannelError, Refused
from monsterbot.models import Profile
from monsterbot.outreach import Outreach, first_name_of
from monsterbot.policy import Context, check
from monsterbot.scout import Scout, score_profile
from tests.conftest import NOW

SCOUT_CFG = Config(
    scout_enabled=True,
    scout_hashtags=("kindergartenmath", "preschoolactivities", "earlymath"),
    scout_hashtags_per_run=2,
)
OUT_CFG = Config(
    outreach_enabled=True,
    outreach_from_name="Sam Rivera",
    outreach_from_email="sam@monstertenmath.com",
    outreach_postal_address="123 Example St, Springfield, IL 62701",
)


def scouted(make_engine, fixture_data, cfg=SCOUT_CFG):
    engine, _ = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()  # our commenters become candidates
    graph = FakeGraph(fixture_data)
    looked, notes = Scout(cfg, engine.kn, engine.ledger, graph, NOW).run()
    return engine, graph, looked, notes


def test_scores_follow_the_growth_plan(kn):
    good = Profile(
        "kate",
        biography="Kindergarten teacher, mom of 2, math games kate@example.com",
        followers=24000,
        posts=tuple(
            {
                "caption": "ten frame counting",
                "like_count": 900,
                "comments_count": 60,
                "timestamp": "2026-11-19T15:00:00+0000",
            }
            for _ in range(6)
        ),
    )
    s = score_profile(good, Config(), kn, NOW)
    assert s.score >= 90 and s.email == "kate@example.com"
    huge = Profile(
        "brand",
        biography="toys",
        followers=900000,
        posts=({"caption": "toys", "like_count": 100, "comments_count": 1, "timestamp": "2026-11-19T15:00:00+0000"},),
    )
    assert score_profile(huge, Config(), kn, NOW).score < 30
    rival = Profile("r", biography="Funexpected ambassador, preschool math", followers=20000, posts=good.posts)
    assert score_profile(rival, Config(), kn, NOW).score == 0
    quiet = Profile(
        "q",
        biography="Homeschool mama, preschool math",
        followers=30000,
        posts=tuple(
            {"caption": "counting", "like_count": 20, "comments_count": 1, "timestamp": "2026-10-01T15:00:00+0000"}
            for _ in range(4)
        ),
    )
    assert score_profile(quiet, Config(), kn, NOW).score <= 40  # few real comments, nothing recent
    tiny = Profile("t", biography="mom of 2, preschool activities", followers=800, posts=good.posts)
    assert score_profile(tiny, Config(), kn, NOW).score <= 20


def test_scout_finds_and_ranks_creators(make_engine, fixture_data):
    engine, graph, looked, notes = scouted(make_engine, fixture_data)
    ledger = engine.ledger
    assert "kinder_with_kate" in looked and "fan_one" in looked
    assert ledger.creator("kinder_with_kate")["source"] == "tagged in a top #kindergartenmath post"
    top = ledger.creators(statuses=("new",))[0]
    assert top["username"] == "kinder_with_kate" and top["email"] == "kate.collabs@example.com"
    assert ledger.creator("rival_fan_mom")["status"] == "rejected"
    assert ledger.creator("jane_parent")["status"] == "unreachable"  # a personal account
    assert graph.hashtag_calls == ["kindergartenmath", "preschoolactivities"]
    # a second run soon after looks nobody up again
    looked2, _ = Scout(SCOUT_CFG, engine.kn, ledger, graph, NOW).run()
    assert looked2 == []


def test_hashtag_budget_is_30_a_week(make_engine):
    engine, _ = make_engine()
    for i in range(29):
        engine.ledger.record_hashtag(f"tag{i}", NOW)
    cfg = Config(scout_hashtags=("new1", "new2", "tag3"), scout_hashtags_per_run=3)
    assert Scout(cfg, engine.kn, engine.ledger, None, NOW).pick_hashtags() == ["new1", "tag3"]


def test_scout_without_hashtag_access_still_works(make_engine, fixture_data):
    engine, _ = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()
    graph = FakeGraph(fixture_data)

    def refused(tag):
        raise ChannelError("feature not approved", "permission")

    graph.hashtag_top_media = refused
    looked, notes = Scout(SCOUT_CFG, engine.kn, engine.ledger, graph, NOW).run()
    assert looked and any("Public Content Access" in n for n in notes)


def test_outreach_draft_and_send(make_engine, fixture_data):
    engine, _, _, _ = scouted(make_engine, fixture_data)
    out = Outreach(OUT_CFG, engine.kn, engine.ledger, "building", "live", NOW)
    body, violations = out.compose("kinder_with_kate", "Your ten-frame snack game last week was so clever.")
    assert violations == []
    assert body.startswith("Hi Kate,") and "$200 when it's posted" in body and "We're being built now." in body
    assert "123 Example St" in body and "no thanks" in body

    email = FakeEmail()
    with pytest.raises(Refused):
        out.send(["kinder_with_kate"], email, owner_tapped=False)
    lines = out.send(out.ready(), email, owner_tapped=True)
    assert lines == ["SENT the Collab email to @kinder_with_kate (kate.collabs@example.com)."]
    assert email.sent[0]["to"] == "kate.collabs@example.com"
    with pytest.raises(Refused):  # never twice
        out.compose("kinder_with_kate", "Another note.")


def test_outreach_checks_the_personal_line_and_refuses_the_wrong_people(make_engine, fixture_data):
    engine, _, _, _ = scouted(make_engine, fixture_data)
    out = Outreach(OUT_CFG, engine.kn, engine.ledger, "building", "live", NOW)
    _, violations = out.compose("prek_play_lab", "Your kids will be smarter and ahead after this, proven!")
    assert violations
    assert out.ready() == []
    with pytest.raises(Refused):
        out.compose("rival_fan_mom", "Hi!")  # rejected: works with a rival
    with pytest.raises(Refused):
        Outreach(Config(), engine.kn, engine.ledger, "building", "live", NOW).compose("kinder_with_kate", "Hi")


def test_rehearsal_and_daily_limit(make_engine, fixture_data):
    engine, _, _, _ = scouted(make_engine, fixture_data)
    cfg = Config(**{**OUT_CFG.__dict__, "outreach_max_per_day": 1})
    out = Outreach(cfg, engine.kn, engine.ledger, "open", "live", NOW)
    out.compose("kinder_with_kate", "Your ten-frame snack game was so clever.")
    out.compose("prek_play_lab", "Your rainy-day activity list is a favorite here.")
    email = FakeEmail()
    lines = out.send(out.ready(), email, owner_tapped=True)
    assert sum(line.startswith("SENT") for line in lines) == 1 and "limit" in lines[1]
    rehearsal = Outreach(cfg, engine.kn, engine.ledger, "open", "rehearsal", datetime(2026, 11, 22, tzinfo=UTC))
    assert rehearsal.send(rehearsal.ready(), None, owner_tapped=True)[0].startswith("REHEARSAL")


def test_email_category_of_the_check(kn):
    text = "I'd love to pay you $200 for one Reel, posted on Sunday. instagram.com/monstertenmath"
    assert check(text, Context("building", "email"), kn.rules) == []
    assert check(text, Context("building"), kn.rules)  # but never in a comment reply
    assert check("Your child will learn math in a week.", Context("building", "email"), kn.rules)


def test_first_names():
    assert first_name_of("Kate | Kindergarten Teacher", "x") == "Kate"
    assert first_name_of("", "x") == "there"


def test_scout_commands_end_to_end(tmp_path, monkeypatch, capsys):
    import shutil

    from monsterbot import cli
    from tests.conftest import ROOT

    fixture = ROOT / "src" / "monsterbot" / "fixtures" / "fake_instagram.json"
    desk = tmp_path / "desk"
    desk.mkdir()
    cfg = (ROOT / "config" / "config.template.toml").read_text()
    cfg = cfg.replace("[scout]\nenabled = false", "[scout]\nenabled = true")
    cfg = cfg.replace("[outreach]\nenabled = false", "[outreach]\nenabled = true")
    cfg = cfg.replace('from_name = ""', 'from_name = "Sam Rivera"')
    cfg = cfg.replace('from_email = ""', 'from_email = "sam@monstertenmath.com"')
    cfg = cfg.replace('postal_address = ""', 'postal_address = "123 Example St, Springfield, IL 62701"')
    (desk / "config.toml").write_text(cfg)
    for k, v in {
        "MT_DESK": str(desk),
        "MT_CHANNEL": f"fake:{fixture}",
        "MT_GRAPH": f"fake:{fixture}",
        "MT_EMAIL": "fake",
        "MT_NOW": "2026-11-20T02:00:00+00:00",
    }.items():
        monkeypatch.setenv(k, v)
    run = lambda *a: (cli.main(list(a)), capsys.readouterr().out)  # noqa: E731
    run("go-live", "--owner-tapped")
    run("scout", "add", "@quiet_creator")
    code, out = run("scout")
    assert code == 0 and "@kinder_with_kate" in out
    code, out = run("creators", "show", "kinder_with_kate")
    assert "Kindergarten teacher" in out and "Recent captions:" in out
    run("creators", "mark", "kinder_with_kate", "shortlist", "--note", "great fit")
    code, out = run("outreach", "draft", "kinder_with_kate", "--text", "Your ten-frame snack game was so clever.")
    assert code == 0 and "passes the check" in out
    assert run("outreach", "send", "all")[0] == 1  # no tap
    code, out = run("outreach", "send", "all", "--owner-tapped")
    assert code == 0 and out.startswith("SENT")
    sent = json.loads((desk / "state" / "fake-emails.json").read_text())
    assert sent[0]["to"] == "kate.collabs@example.com"
    shutil.rmtree(desk)
