"""v1: the Buffer bridge. Main is the approval; Buffer is what publishes; the ledger knows which is which."""

import json
from datetime import UTC, datetime

import pytest

from monsterbot.config import Config
from monsterbot.errors import Refused
from monsterbot.ledger import Ledger
from monsterbot.social import Calendar, FakeBuffer, Social, phase_at

NOW = datetime(2026, 11, 28, 13, 0, tzinfo=UTC)  # Sat 28 Nov, 8 am Eastern
CFG = Config(buffer_enabled=True)


def feed(name, due, text, **kw):
    return {
        "name": name,
        "et": "",
        "dueAt": due,
        "type": "reel",
        "media": [f"instagram/reels/v9/{name[1:4]}.mp4"],
        "cover": None,
        "ai": True,
        "text": text,
        "alt": None,
        **kw,
    }


FEED = [
    feed("#401 Past", "2026-11-21T01:30:00Z", "Already went out. No timer. No score."),
    feed("#601 Laundry day (realistic)", "2026-11-29T22:00:00Z", "Laundry day? Mix up the clean socks and pair them."),
    feed("#602 Big dinner (realistic)", "2026-11-30T22:00:00Z", "Big dinner tonight? Count the forks together."),
    feed(
        "#501 Hungry Monster",
        "2026-12-02T17:30:00Z",
        "Try it tonight: feed the hungry Monster. Link in bio!",
        publish="reminder",
    ),
    feed("#502 Held", "2026-12-03T17:30:00Z", "Held piece", hold="replaced-v7"),
]
STORIES = [
    {
        "name": "st-count",
        "et": "",
        "dueAt": "2026-11-29T15:00:00Z",
        "media": "instagram/images/stories/s1.mp4",
        "publish": "auto",
        "ai": True,
    },
    {
        "name": "st-count",
        "et": "",
        "dueAt": "2026-12-05T15:00:00Z",
        "media": "instagram/images/stories/s1.mp4",
        "publish": "reminder",
        "ai": True,
    },
]


def buffer_posts():
    return [
        {"id": "b1", "dueAt": "2026-11-29T22:00:00.000Z", "text": FEED[1]["text"], "schedulingType": "automatic"},
        {"id": "b2", "dueAt": "2026-11-30T22:00:00.000Z", "text": FEED[2]["text"], "schedulingType": "automatic"},
        {"id": "b3", "dueAt": "2026-12-02T17:30:00.000Z", "text": FEED[3]["text"], "schedulingType": "notification"},
        {
            "id": "b4",
            "dueAt": "2026-11-29T15:00:00.000Z",
            "text": "Posts by itself: nothing to do. [Story st-count]",
            "schedulingType": "automatic",
        },
        {
            "id": "b9",
            "dueAt": "2026-12-01T12:00:00.000Z",
            "text": "Something the owner added by hand",
            "schedulingType": "automatic",
        },
        {
            "id": "s1",
            "dueAt": "2026-11-21T01:30:00.000Z",
            "text": FEED[0]["text"],
            "schedulingType": "automatic",
            "status": "sent",
        },
    ]


@pytest.fixture
def env(tmp_path, kn):
    root = tmp_path / "social"
    (root / "instagram").mkdir(parents=True)
    (root / "instagram" / "schedule.json").write_text(json.dumps(FEED))
    (root / "instagram" / "stories.json").write_text(json.dumps(STORIES))
    bpath = tmp_path / "buffer.json"
    bpath.write_text(json.dumps({"posts": buffer_posts()}))
    ledger = Ledger(tmp_path / "l.sqlite3")

    def make(cfg=CFG, now=NOW, phase="building", pricing="standard"):
        cal = Calendar(root, "bucket")
        return Social(cfg, kn, ledger, FakeBuffer(bpath), cal, phase, pricing, now, head=lambda: None)

    def write(feed_entries=None, stories=None):
        if feed_entries is not None:
            (root / "instagram" / "schedule.json").write_text(json.dumps(feed_entries))
        if stories is not None:
            (root / "instagram" / "stories.json").write_text(json.dumps(stories))

    yield make, ledger, write, bpath
    ledger.close()


def test_phase_at():
    assert phase_at("2026-11-30T22:00:00Z") == "building"
    assert phase_at("2026-12-01T17:30:00Z") == "open"


def test_sync_refuses_before_adopt(env):
    make, *_ = env
    with pytest.raises(Refused, match="adopt"):
        make().sync(pull=False)


def test_adopt_records_and_changes_nothing(env):
    make, ledger, _, bpath = env
    s = make()
    lines = s.adopt()
    text = "\n".join(lines)
    assert "ADOPTED 4 of 5 expected" in text  # the second st-count Story isn't in Buffer
    assert "st-count@2026-12-05T15:00" in text  # listed as missing
    assert "Something the owner added" in text  # foreign
    assert s.buffer.calls == []
    keys = {r[0] for r in ledger.db.execute("SELECT key FROM buffer_posts WHERE key IS NOT NULL")}
    assert keys == {"#601", "#602", "#501", "st-count@2026-11-29T15:00"}
    with pytest.raises(Refused, match="already|adopted"):
        make().adopt()


def test_adopt_refuses_when_nothing_matches(env):
    make, ledger, _, bpath = env
    bpath.write_text(
        json.dumps(
            {"posts": [{"id": "x", "dueAt": "2027-01-01T00:00:00Z", "text": "other", "schedulingType": "automatic"}]}
        )
    )
    lines = make().adopt()
    assert lines[-1].startswith("REFUSED")
    assert ledger.kv_get("buffer.adopted_at") is None


def test_sync_creates_new_updates_changed_and_never_recreates(env, monkeypatch):
    make, ledger, write, bpath = env
    make().adopt()
    entries = json.loads(json.dumps(FEED))
    entries[2]["text"] = "Big dinner tonight? Count the forks and spoons together."  # main changed #602
    entries.append(feed("#603 Which spoon (realistic)", "2026-12-03T22:00:00Z", "Which spoon is longer? Check."))
    write(entries)
    data = json.loads(bpath.read_text())
    data["posts"] = [p for p in data["posts"] if p["id"] != "b1"]  # #601 deleted in the Buffer app
    bpath.write_text(json.dumps(data))
    s = make()
    lines = s.sync(pull=False, check_media=lambda url: True)
    text = "\n".join(lines)
    assert "CREATED #603" in text
    assert "UPDATED #602" in text
    assert "MISSING #601" in text  # reported, never re-created
    assert sorted(c[0] for c in s.buffer.calls) == ["create", "edit"]
    assert "1 created · 1 updated" in lines[0]
    again = make().sync(pull=False, check_media=lambda url: True)
    assert "0 created · 0 updated" in again[0]


def test_sync_leaves_app_edits_alone(env):
    make, ledger, write, bpath = env
    make().adopt()
    data = json.loads(bpath.read_text())
    data["posts"][1]["text"] = "Edited by hand in Buffer"
    bpath.write_text(json.dumps(data))
    entries = json.loads(json.dumps(FEED))
    entries[2]["text"] = "Big dinner tonight? A new version from main."
    write(entries)
    s = make()
    lines = s.sync(pull=False, check_media=lambda url: True)
    assert any("CHANGED ON BOTH SIDES #602" in line for line in lines)
    assert s.buffer.calls == []
    assert any("CHANGED ON BOTH SIDES #602" in line for line in make().audit())
    with pytest.raises(Refused, match="owner"):
        make().push("#602", owner_tapped=False)
    assert make().push("#602", owner_tapped=True).startswith("PUSHED")


def test_sync_skips_unpublished_media_and_same_minute(env):
    make, ledger, write, bpath = env
    make().adopt()
    entries = json.loads(json.dumps(FEED))
    entries.append(feed("#604 Clash", "2026-11-30T22:00:00Z", "Same minute as #602."))
    entries.append(feed("#605 No media", "2026-12-04T22:00:00Z", "Media not uploaded."))
    write(entries)
    lines = make().sync(pull=False, check_media=lambda url: "605" not in url)
    text = "\n".join(lines)
    assert "SKIP #604: another post is already at" in text
    assert "SKIP #605: media isn't public yet" in text


def test_sync_off_unless_enabled(env):
    make, *_ = env
    make().adopt()
    with pytest.raises(Refused, match="off"):
        make(cfg=Config()).sync(pull=False)
    assert "DRY RUN" in make(cfg=Config()).sync(dry=True, pull=False, check_media=lambda u: True)[0]


def test_audit_flags_what_no_longer_fits(env):
    make, ledger, write, bpath = env
    make().adopt()
    entries = json.loads(json.dumps(FEED))
    entries[1]["ai"] = False
    entries[2]["text"] = "Big dinner tonight? This is lesson 14."
    write(entries)
    text = "\n".join(make().audit())
    assert "AI LABEL #601" in text
    assert "NO LONGER FITS #602" in text and "lesson" in text
    assert (
        "#501" not in text.split("NO LONGER FITS")[-1] or "NO LONGER FITS #501" not in text
    )  # a reminder may say link in bio


def test_taps(env):
    make, ledger, write, bpath = env
    make().adopt()
    with pytest.raises(Refused):
        make().delete("#602", owner_tapped=False)
    assert make().delete("#602", owner_tapped=True).startswith("DELETED")
    assert "#602" not in [p["text"][:4] for p in json.loads(bpath.read_text())["posts"]]
    lines = make().sync(pull=False, check_media=lambda u: True)
    assert not any("#602" in line for line in lines[1:])  # never re-created by sync
    assert make().restore("#602", owner_tapped=True).startswith("RESTORED")
    assert make().remind("#601", owner_tapped=True).startswith("REMINDER")


def test_calendar_refuses_a_bad_entry(env):
    make, ledger, write, _ = env
    write([{"name": "#700 No date", "type": "post", "text": "x", "media": ["a.png"]}])
    with pytest.raises(Refused, match="no dueAt"):
        make()
