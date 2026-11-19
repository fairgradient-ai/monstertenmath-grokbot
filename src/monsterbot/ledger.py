"""The ledger: every comment the bot has seen and what happened to it, in SQLite.

SQLite gives real transactions, so a sweep and a send that overlap can't both answer one comment (the JSON
ledger in pickletime-grokbot could race there). Item ids are small integers the owner can type in chat:
"send 14".

Item status:
  new         seen, nothing done yet
  rehearsed   a canned reply was planned in rehearsal mode; a live sweep plans it again
  queued      waits for a draft, or for the owner (spam, escalations)
  drafted     a draft is saved; "send" posts it
  sending     a post is in flight
  unverified  the post timed out; the next sweep looks for it before anything is retried
  retry       an unverified canned reply that wasn't found; the next sweep plans it again
  replied     answered (reply_external_id is ours)
  discarded   the owner chose not to answer
  hidden      hidden on Instagram
  skipped     needs nothing (our own comment, friends tagging each other)
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  external_id TEXT NOT NULL,
  media_id TEXT,
  piece TEXT,
  parent_external_id TEXT,
  parent_author TEXT,
  author TEXT,
  text TEXT,
  created_at TEXT,
  first_seen TEXT,
  category TEXT,
  tier TEXT,
  reason TEXT,
  suggested TEXT,
  notify TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  draft_text TEXT,
  draft_violations TEXT,
  reply_text TEXT,
  reply_external_id TEXT,
  attempted_at TEXT,
  replied_at TEXT,
  error TEXT,
  recipient_id TEXT,
  draft_by TEXT,
  sent_by TEXT,
  UNIQUE(channel, external_id)
);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  mode TEXT NOT NULL,
  action TEXT NOT NULL,
  item_id INTEGER,
  media_id TEXT,
  detail TEXT,
  ok INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS followers (day TEXT PRIMARY KEY, count INTEGER NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS examples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  item_id INTEGER,
  incoming TEXT,
  bot_draft TEXT,
  final TEXT NOT NULL,
  external_id TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS creators (
  username TEXT PRIMARY KEY,
  name TEXT,
  followers INTEGER,
  media_count INTEGER,
  engagement REAL,
  last_post TEXT,
  biography TEXT,
  website TEXT,
  email TEXT,
  captions TEXT,
  score INTEGER,
  score_notes TEXT,
  source TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  note TEXT,
  checked_at TEXT,
  outreach_subject TEXT,
  outreach_body TEXT,
  outreach_violations TEXT,
  outreach_sent_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS hashtag_queries (tag TEXT NOT NULL, ts TEXT NOT NULL);
"""

# Columns added after v0.1.0; added in place to an older database.
MIGRATIONS = [("items", "recipient_id", "TEXT"), ("items", "draft_by", "TEXT"), ("items", "sent_by", "TEXT")]

OPEN_STATUSES = ("queued", "drafted", "unverified")


@dataclass
class Item:
    id: int
    channel: str
    external_id: str
    media_id: str | None
    piece: str | None
    parent_external_id: str | None
    parent_author: str | None
    author: str
    text: str
    created_at: datetime
    category: str
    tier: str
    reason: str
    suggested: str | None
    notify: str | None
    status: str
    draft_text: str | None
    draft_violations: list[str]
    reply_text: str | None
    reply_external_id: str | None
    attempted_at: datetime | None
    replied_at: datetime | None
    error: str | None
    recipient_id: str | None = None
    draft_by: str | None = None
    sent_by: str | None = None

    @property
    def is_dm(self) -> bool:
        return self.channel.endswith("-dm")


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_item(row: sqlite3.Row) -> Item:
    return Item(
        id=row["id"],
        channel=row["channel"],
        external_id=row["external_id"],
        media_id=row["media_id"],
        piece=row["piece"],
        parent_external_id=row["parent_external_id"],
        parent_author=row["parent_author"],
        author=row["author"] or "",
        text=row["text"] or "",
        created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
        category=row["category"] or "",
        tier=row["tier"] or "",
        reason=row["reason"] or "",
        suggested=row["suggested"],
        notify=row["notify"],
        status=row["status"],
        draft_text=row["draft_text"],
        draft_violations=json.loads(row["draft_violations"] or "[]"),
        reply_text=row["reply_text"],
        reply_external_id=row["reply_external_id"],
        attempted_at=_dt(row["attempted_at"]),
        replied_at=_dt(row["replied_at"]),
        error=row["error"],
        recipient_id=row["recipient_id"],
        draft_by=row["draft_by"],
        sent_by=row["sent_by"],
    )


class Ledger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        for table, column, kind in MIGRATIONS:
            cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    # --- items -----------------------------------------------------------------------------------------
    def get(self, item_id: int) -> Item | None:
        row = self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row else None

    def by_external(self, channel: str, external_id: str) -> Item | None:
        row = self.db.execute(
            "SELECT * FROM items WHERE channel = ? AND external_id = ?", (channel, external_id)
        ).fetchone()
        return _row_to_item(row) if row else None

    def upsert_seen(self, channel: str, external_id: str, now: datetime, **fields: object) -> int:
        """Record a comment (or re-triage one that was only rehearsed). Returns the item id."""
        existing = self.by_external(channel, external_id)
        cols = dict(fields)
        if existing is None:
            cols.update(channel=channel, external_id=external_id, first_seen=now.isoformat())
            names = ", ".join(cols)
            marks = ", ".join("?" for _ in cols)
            cur = self.db.execute(f"INSERT INTO items ({names}) VALUES ({marks})", tuple(map(_sql, cols.values())))
            return int(cur.lastrowid)  # type: ignore[arg-type]
        sets = ", ".join(f"{k} = ?" for k in cols)
        self.db.execute(f"UPDATE items SET {sets} WHERE id = ?", (*map(_sql, cols.values()), existing.id))
        return existing.id

    def update(self, item_id: int, **fields: object) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE items SET {sets} WHERE id = ?", (*map(_sql, fields.values()), item_id))

    def items(self, statuses: tuple[str, ...] | None = None, media_id: str | None = None) -> list[Item]:
        sql, args = "SELECT * FROM items WHERE 1=1", []
        if statuses:
            sql += f" AND status IN ({', '.join('?' for _ in statuses)})"
            args += list(statuses)
        if media_id:
            sql += " AND media_id = ?"
            args.append(media_id)
        return [_row_to_item(r) for r in self.db.execute(sql + " ORDER BY id", args)]

    def auto_replies_since(
        self,
        since: datetime,
        *,
        media_id: str | None = None,
        author: str | None = None,
        category: str | None = None,
    ) -> int:
        # Everything the bot posted without the owner's tap: canned replies and its own written ones.
        sql = "SELECT COUNT(*) FROM items WHERE status = 'replied' AND sent_by IN ('auto', 'bot') AND replied_at >= ?"
        args: list[object] = [since.isoformat()]
        for col, val in (("media_id", media_id), ("author", author), ("category", category)):
            if val is not None:
                sql += f" AND {col} = ?"
                args.append(val)
        return int(self.db.execute(sql, args).fetchone()[0])

    def count_category_replies(self, media_id: str, category: str) -> int:
        return int(
            self.db.execute(
                "SELECT COUNT(*) FROM items WHERE media_id = ? AND category = ? AND status = 'replied'",
                (media_id, category),
            ).fetchone()[0]
        )

    # --- actions log -----------------------------------------------------------------------------------
    def log(
        self,
        now: datetime,
        mode: str,
        action: str,
        *,
        item_id: int | None = None,
        media_id: str | None = None,
        detail: str = "",
        ok: bool = True,
    ) -> None:
        self.db.execute(
            "INSERT INTO actions (ts, mode, action, item_id, media_id, detail, ok) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now.isoformat(), mode, action, item_id, media_id, detail, int(ok)),
        )

    def has_action(self, action: str, media_id: str, mode: str = "live") -> bool:
        row = self.db.execute(
            "SELECT 1 FROM actions WHERE action = ? AND media_id = ? AND mode = ? AND ok = 1 LIMIT 1",
            (action, media_id, mode),
        ).fetchone()
        return row is not None

    # --- key/value -------------------------------------------------------------------------------------
    def kv_get(self, key: str) -> str | None:
        row = self.db.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        return row[0] if row else None

    def kv_set(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, value))

    # --- followers -------------------------------------------------------------------------------------
    def record_followers(self, day: str, count: int, now: datetime) -> None:
        self.db.execute(
            "INSERT INTO followers (day, count, recorded_at) VALUES (?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET count = excluded.count, recorded_at = excluded.recorded_at",
            (day, count, now.isoformat()),
        )

    def followers_on(self, day: str) -> int | None:
        row = self.db.execute("SELECT count FROM followers WHERE day = ?", (day,)).fetchone()
        return int(row[0]) if row else None

    # --- examples: how the owner answers, for the bot to learn from ------------------------------------
    def add_example(
        self,
        now: datetime,
        *,
        source: str,
        kind: str,
        final: str,
        incoming: str | None = None,
        bot_draft: str | None = None,
        item_id: int | None = None,
        external_id: str | None = None,
    ) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO examples (ts, source, kind, item_id, incoming, bot_draft, final, external_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now.isoformat(), source, kind, item_id, incoming, bot_draft, final, external_id),
        )
        return cur.rowcount > 0

    def examples(self, limit: int = 20, sources: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM examples", []
        if sources:
            sql += f" WHERE source IN ({', '.join('?' for _ in sources)})"
            args = list(sources)
        return list(self.db.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)))

    def our_reply_ids(self) -> set[str]:
        return {
            r[0] for r in self.db.execute("SELECT reply_external_id FROM items WHERE reply_external_id IS NOT NULL")
        }

    # --- creators --------------------------------------------------------------------------------------
    def creator(self, username: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM creators WHERE username = ?", (username.lower(),)).fetchone()

    def upsert_creator(self, username: str, now: datetime, **fields: object) -> None:
        username = username.lower()
        fields["updated_at"] = now.isoformat()
        if self.creator(username) is None:
            fields.setdefault("status", "new")
            cols = ["username", *fields]
            self.db.execute(
                f"INSERT INTO creators ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                (username, *map(_sql, fields.values())),
            )
        else:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self.db.execute(f"UPDATE creators SET {sets} WHERE username = ?", (*map(_sql, fields.values()), username))

    def creators(self, statuses: tuple[str, ...] | None = None, limit: int = 50) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM creators", []
        if statuses:
            sql += f" WHERE status IN ({', '.join('?' for _ in statuses)})"
            args = list(statuses)
        return list(self.db.execute(sql + " ORDER BY COALESCE(score, -1) DESC, username LIMIT ?", (*args, limit)))

    def emails_sent_since(self, since: datetime) -> int:
        return int(
            self.db.execute(
                "SELECT COUNT(*) FROM creators WHERE outreach_sent_at >= ?", (since.isoformat(),)
            ).fetchone()[0]
        )

    # --- hashtag searches (30 different tags in a rolling 7 days) --------------------------------------
    def record_hashtag(self, tag: str, now: datetime) -> None:
        self.db.execute("INSERT INTO hashtag_queries (tag, ts) VALUES (?, ?)", (tag, now.isoformat()))

    def hashtags_since(self, since: datetime) -> dict[str, str]:
        rows = self.db.execute(
            "SELECT tag, MAX(ts) FROM hashtag_queries WHERE ts >= ? GROUP BY tag", (since.isoformat(),)
        )
        return {r[0]: r[1] for r in rows}


def _sql(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def day_ago(now: datetime) -> datetime:
    return now - timedelta(hours=24)
