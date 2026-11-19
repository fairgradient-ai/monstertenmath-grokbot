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
"""

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
    )


class Ledger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

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
        sql = "SELECT COUNT(*) FROM items WHERE status = 'replied' AND tier = 'auto' AND replied_at >= ?"
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


def _sql(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def day_ago(now: datetime) -> datetime:
    return now - timedelta(hours=24)
