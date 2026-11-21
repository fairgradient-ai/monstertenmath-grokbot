"""v1: insights, ad suggestions, pillars and timing, from the ledger."""

from datetime import UTC, datetime, timedelta

import pytest

from monsterbot.channels.fake import FakeInstagram
from monsterbot.config import Config
from monsterbot.insights import Insights
from monsterbot.ledger import Ledger
from monsterbot.policy import Context, check

NOW = datetime(2026, 12, 10, 3, 0, tzinfo=UTC)
CFG = Config(insights_enabled=True)

CAPTIONS = {
    "#501": "Try it tonight: feed the hungry Monster. Put five crackers on a plate.",
    "#502": "Try it tonight: count a cracker parade, one by one.",
    "#503": "Try it tonight: open Monster's café and take orders.",
    "#24": "Worm Ruler: a new Monster Ten game",
    "#25": "Line Up: a new Monster Ten game",
    "#26": "Wake the Monster: a new Monster Ten game",
    "#403": "Try it tonight: the Monster's menu",
}


def media_fixture(kn):
    media, insights = [], {}
    for i, (key, cap) in enumerate(CAPTIONS.items()):
        piece = kn.piece(key)
        caption = piece.caption_start + cap[len(piece.caption_start) :] if piece else cap
        mid = f"m{key[1:]}"
        media.append(
            {
                "id": mid,
                "caption": piece.caption_start + " and the rest" if piece else caption,
                "timestamp": (NOW - timedelta(days=4 + i)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
                "media_type": "VIDEO",
                "comments": [],
            }
        )
        # the game Reels #24-#26 share most
        shares = 40 if key in ("#24", "#25", "#26") else 8
        insights[mid] = {
            "reach": 2000,
            "shares": shares,
            "saved": 20,
            "likes": 100,
            "comments": 6,
            "total_interactions": 130 + shares,
        }
    return {
        "account": {"id": "1", "username": "monstertenmath", "followers_count": 500},
        "media": media,
        "insights": insights,
    }


@pytest.fixture
def ins(tmp_path, kn):
    ledger = Ledger(tmp_path / "l.sqlite3")
    i = Insights(CFG, kn, ledger, "open", "founding", NOW)
    i.collect(FakeInstagram(media_fixture(kn)))
    yield i
    ledger.close()


def test_collect_matches_pieces(ins):
    posts = ins.posts()
    assert len(posts) == len(CAPTIONS)
    assert {p["pillar"] for p in posts} == {"tonight", "games", "features"}
    assert all(p["v"]["reach"] == 2000 for p in posts)


def test_report_ranks_by_shares(ins):
    lines = ins.report(7, followers=500)
    best = lines[lines.index(next(line for line in lines if line.startswith("Best"))) + 1]
    assert "games" in best
    assert any(line.startswith("Weakest") for line in lines)


def test_too_early_with_few_posts(tmp_path, kn):
    ledger = Ledger(tmp_path / "e.sqlite3")
    i = Insights(CFG, kn, ledger, "building", "standard", NOW)
    assert any("Too early" in line for line in i.report())
    assert any("Too early" in line for line in i.ads())
    ledger.close()


def test_ads_pick_shared_posts_and_never_spend(ins):
    lines = ins.ads()
    assert "never spends" in lines[0]
    assert lines[1].startswith("1. #2")  # a game Reel: most shared
    assert "AI label" in lines[2]


def test_ads_skip_a_child_without_release(ins, kn):
    from dataclasses import replace

    ins.kn = replace(kn, pieces=tuple(replace(p, child=True) if p.key == "#24" else p for p in kn.pieces))
    assert any("#24" in line and "ad release" in line for line in ins.ads())


def test_pillars_score_and_demand(ins):
    ins.db.execute(
        "INSERT INTO items (channel, external_id, text, first_seen, status, category) VALUES "
        "('instagram', 'c1', 'my 3 year old loved it', ?, 'replied', 'praise'),"
        "('instagram', 'c2', 'we do not have crackers, can we use grapes?', ?, 'replied', 'question')",
        (NOW.isoformat(), NOW.isoformat()),
    )
    lines = ins.pillars()
    text = "\n".join(lines)
    assert "games" in text and "double down" in text
    assert "ages: 1" in text and "no crackers: 1" in text


def test_propose_runs_the_caption_check(ins):
    pid, problems = ins.propose("Swap the crackers\nThe same game with grapes, buttons or toy cars.")
    assert pid == 1 and problems == []
    pid, problems = ins.propose("Lesson 14 in real life\nYour child will be ahead!")
    assert problems


def test_timing_shrinks_toward_median(ins):
    lines = ins.timing()
    assert lines[0].startswith("TIMING")
    assert all("×" in line for line in lines[1:-1])


def test_caption_category():
    rules = {"max_hashtags": 0, "banned": [], "handle": "monstertenmath"}
    assert check("Fun! #a #b #c #d #e", Context("open", "caption"), rules) == []
    assert check("Fun! #a #b #c #d #e #f", Context("open", "caption"), rules)
    assert check("Fun! #a", Context("open", "draft"), rules)


def test_lesson_numbers_are_refused(kn):
    bad = check("This is lesson 14 of the program", Context("building", "caption"), kn.rules)
    assert any(v.id == "lesson-number" for v in bad)
    assert check("7 and 3 make 10", Context("building", "caption"), kn.rules) == []
