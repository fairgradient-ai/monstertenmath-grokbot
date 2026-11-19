"""v0.3: the brief: fresh creator posts with a comment for each, for a person to post."""

import json
import re
import shutil
from datetime import timedelta

import pytest

from monsterbot.brief import Brief, ids_from
from monsterbot.channels.fake import FakeGraph
from monsterbot.config import Config
from monsterbot.errors import Refused
from monsterbot.policy import Context, check
from monsterbot.scout import Scout
from tests.conftest import NOW, ROOT

CFG = Config(scout_enabled=True, scout_hashtags=("kindergartenmath", "preschoolactivities"))


@pytest.fixture
def setup(make_engine, fixture_data):
    engine, _ = make_engine(mode="live", cfg=Config(first_comments=False))
    engine.sweep()
    graph = FakeGraph(fixture_data)
    Scout(CFG, engine.kn, engine.ledger, graph, NOW).run()
    engine.ledger.upsert_creator("kinder_with_kate", NOW, status="shortlist")

    def brief(now=NOW, cfg=CFG, data=None):
        return Brief(cfg, engine.kn, engine.ledger, FakeGraph(data or fixture_data), "building", now)

    return engine, brief


def test_picks_fresh_posts_from_the_right_creators(setup):
    engine, brief = setup
    ids, notes = brief().build()
    rows = [brief().row(i) for i in ids]
    creators = [r["creator"] for r in rows]
    assert creators[0] == "kinder_with_kate"  # shortlisted first
    assert "prek_play_lab" in creators  # a new creator with a score of 60+
    assert "rival_fan_mom" not in creators and "big_brand_kids" not in creators and "fan_one" not in creators
    assert "quiet_creator" not in creators  # nothing from the last day
    assert rows[0]["permalink"] == "https://www.instagram.com/p/kinder_with_kate-0/"  # the newest post
    assert len(creators) == len(set(creators))


def test_one_post_per_creator_a_day_and_never_twice(setup):
    _, brief = setup
    first, _ = brief().build()
    again, notes = brief(now=NOW + timedelta(hours=5)).build()
    assert again == [] and notes
    tomorrow, _ = brief(
        now=NOW + timedelta(hours=25), cfg=Config(**{**CFG.__dict__, "brief_max_age_hours": 48})
    ).build()
    # a new day, but the same posts are never briefed twice: the next-newest fresh one is picked instead
    links = {brief().row(i)["permalink"] for i in first}
    assert all(brief().row(i)["permalink"] not in links for i in tomorrow)


def test_skips_giveaways(setup, fixture_data):
    _, brief = setup
    data = json.loads(json.dumps(fixture_data))
    data["creators"]["kinder_with_kate"]["media"][0]["caption"] = "GIVEAWAY! Enter to win a math kit"
    ids, _ = brief(data=data).build()
    links = [brief().row(i)["permalink"] for i in ids]
    assert "https://www.instagram.com/p/kinder_with_kate-0/" not in links


def test_daily_limit(setup):
    _, brief = setup
    small = Config(**{**CFG.__dict__, "brief_per_day": 1})
    ids, _ = brief(cfg=small).build()
    assert len(ids) == 1
    assert brief(cfg=small, now=NOW + timedelta(hours=6)).build()[0] == []


def test_comments_are_held_to_the_outbound_rules(setup):
    _, brief = setup
    ids, _ = brief().build()
    b = brief()
    assert b.comment(ids[0], "Love this! Check out our app, link in bio #earlymath")  # held
    assert b.row(ids[0])["status"] == "proposed"
    assert b.comment(ids[0], "7 is a full row and 2 more, so you can see it without counting. Love this.") == []
    assert b.row(ids[0])["status"] == "ready"
    # never the same comment twice
    held = b.comment(ids[1], "7 is a full row and 2 more, so you can see it without counting. Love this.")
    assert any("used before" in v for v in held)


def test_the_list_and_marking_done(setup):
    _, brief = setup
    ids, _ = brief().build()
    b = brief()
    b.comment(ids[0], "Snack math is the best kind. Hiding a few under a cup makes it a game.")
    assert [r["id"] for r in b.ready()] == [ids[0]]
    assert b.mark([ids[0]], "posted") == [f"[B{ids[0]}] @kinder_with_kate: posted."]
    assert b.ready() == []
    with pytest.raises(Refused):
        b.comment(ids[0], "Another one")


def test_brief_numbers():
    assert ids_from(["B12", "13,b14"]) == [12, 13, 14]
    with pytest.raises(Refused):
        ids_from(["twelve"])


def test_the_plan_s_starting_points_pass_as_outbound(kn):
    voice = (ROOT / "skills" / "monsterten-voice" / "SKILL.md").read_text().split("## Comments on creators' posts")[1]
    lines = re.findall(r'^\| [^|]+\|\s+"([^|]+)"\s+\|$', voice, re.M)
    assert len(lines) >= 5
    for text in lines:
        assert check(text, Context("building", "outbound"), kn.rules) == [], text
        assert check(text, Context("open", "outbound"), kn.rules) == [], text
    assert check("Go see monstertenmath.com/insta", Context("open", "outbound"), kn.rules)  # no links, ever


def test_brief_end_to_end(tmp_path, monkeypatch, capsys):
    fixture = ROOT / "src" / "monsterbot" / "fixtures" / "fake_instagram.json"
    desk = tmp_path / "desk"
    desk.mkdir()
    cfg = (ROOT / "config" / "config.template.toml").read_text()
    cfg = cfg.replace("[scout]\nenabled = false", "[scout]\nenabled = true")
    cfg = cfg.replace('email_to = ""', 'email_to = "helper@example.com"')
    (desk / "config.toml").write_text(cfg)
    for k, v in {
        "MT_DESK": str(desk),
        "MT_CHANNEL": f"fake:{fixture}",
        "MT_GRAPH": f"fake:{fixture}",
        "MT_EMAIL": "fake",
        "MT_NOW": "2026-11-20T02:00:00+00:00",
    }.items():
        monkeypatch.setenv(k, v)
    from monsterbot import cli

    run = lambda *a: (cli.main(list(a)), capsys.readouterr().out)  # noqa: E731
    run("sweep")
    run("scout")
    run("creators", "mark", "kinder_with_kate", "shortlist")
    code, out = run("brief")
    assert code == 0 and out.startswith("BRIEF · ") and "@kinder_with_kate" in out
    n = re.search(r"\[B(\d+)\] @kinder_with_kate", out).group(1)
    code, out = run("brief", "comment", f"B{n}", "--text", "Love a ten-frame snack game. 7 and 3 is such a good pair.")
    assert code == 0 and out.startswith("READY")
    code, out = run("brief", "show")
    assert "COMMENTS TO POST · 1" in out and "https://www.instagram.com/p/kinder_with_kate-0/" in out
    code, out = run("brief", "email")
    assert code == 0 and "helper@example.com" in out
    sent = json.loads((desk / "state" / "fake-emails.json").read_text())
    assert "7 and 3 is such a good pair" in sent[0]["body"]
    code, out = run("brief", "done", n)
    assert "posted" in out
    shutil.rmtree(desk)
