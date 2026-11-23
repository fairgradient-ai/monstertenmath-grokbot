"""The brief: fresh posts from the right creators, each with a comment written for it, for a person to post.

Three times a day the brief picks posts from the shortlisted creators that went up in the last day (comments in
the first hours travel furthest, growth plan 6.3), at most one per creator a day and 30 a day in all. The Grok
Bot writes one fresh comment for each; the policy check holds it to 6.3's rules (no app, link, price or
"follow us"; no hashtags; never the same comment twice). A person posts them from @monstertenmath, by hand:
the bot never comments on another account itself (DESIGN.md, section 3).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import policy
from .channels.instagram import parse_time
from .config import Config
from .errors import Refused
from .knowledge import Knowledge, _norm
from .ledger import Ledger, day_ago
from .scout import GIVEAWAY

STATUS_RANK = {"shortlist": 0, "booked": 1, "contacted": 2, "drafted": 3, "new": 4}
OPEN = ("proposed", "ready")


@dataclass
class Pick:
    creator: str
    permalink: str
    caption: str
    posted_at: datetime
    rank: tuple


class Brief:
    def __init__(self, cfg: Config, kn: Knowledge, ledger: Ledger, graph, phase: str, now: datetime):
        self.cfg, self.kn, self.ledger, self.graph, self.phase, self.now = cfg, kn, ledger, graph, phase, now

    # --- picking posts ---------------------------------------------------------------------------------
    def build(self) -> tuple[list[int], list[str]]:
        notes: list[str] = []
        db = self.ledger.db
        since = day_ago(self.now).isoformat()
        today = int(db.execute("SELECT COUNT(*) FROM brief_posts WHERE created_at >= ?", (since,)).fetchone()[0])
        room = min(self.cfg.brief_per_run, self.cfg.brief_per_day - today)
        if room <= 0:
            return [], [f"today's {self.cfg.brief_per_day} comments are already in earlier briefs"]

        creators = self.ledger.creators(statuses=("shortlist", "booked", "contacted", "drafted"), limit=200)
        creators += [
            r
            for r in self.ledger.creators(statuses=("new",), limit=200)
            if (r["score"] or 0) >= self.cfg.brief_min_score
        ]
        if not creators:
            return [], ['no creators to draw from yet: say "find creators" first (the scout)']
        creators.sort(key=lambda r: (STATUS_RANK.get(r["status"], 9), -(r["score"] or 0)))

        rivals = [r.lower() for r in self.kn.rules.get("rivals", [])]
        max_age = timedelta(hours=self.cfg.brief_max_age_hours)
        picks: list[Pick] = []
        looked = 0
        for row in creators:
            if looked >= self.cfg.brief_lookups:
                notes.append(f"looked at {looked} creators; the rest are for the next brief")
                break
            seen_today = db.execute(
                "SELECT 1 FROM brief_posts WHERE creator = ? AND created_at >= ? LIMIT 1", (row["username"], since)
            ).fetchone()
            if seen_today:
                continue
            looked += 1
            profile = self.graph.business_discovery(row["username"])
            if profile is None:
                continue
            for post in sorted(profile.posts, key=lambda p: p.get("timestamp") or "", reverse=True):
                link, caption = post.get("permalink"), post.get("caption") or ""
                if not link or not post.get("timestamp"):
                    continue
                posted = parse_time(post["timestamp"])
                if self.now - posted > max_age:
                    break  # newest first: the rest are older still
                if db.execute("SELECT 1 FROM brief_posts WHERE permalink = ?", (link,)).fetchone():
                    continue
                if GIVEAWAY.search(caption) or any(r in caption.lower() for r in rivals):
                    continue
                picks.append(
                    Pick(
                        row["username"],
                        link,
                        caption,
                        posted,
                        (STATUS_RANK.get(row["status"], 9), posted.timestamp() * -1),
                    )
                )
                break  # one post per creator per brief
        picks.sort(key=lambda p: p.rank)
        ids = []
        for p in picks[:room]:
            cur = db.execute(
                "INSERT INTO brief_posts (permalink, creator, caption, posted_at, created_at, status) "
                "VALUES (?, ?, ?, ?, ?, 'proposed')",
                (p.permalink, p.creator, p.caption, p.posted_at.isoformat(), self.now.isoformat()),
            )
            ids.append(int(cur.lastrowid))  # type: ignore[arg-type]
        if not ids:
            notes.append(f"no new posts in the last {self.cfg.brief_max_age_hours} hours from the creators on the list")
        return ids, notes

    # --- writing the comment ---------------------------------------------------------------------------
    def row(self, brief_id: int):
        r = self.ledger.db.execute("SELECT * FROM brief_posts WHERE id = ?", (brief_id,)).fetchone()
        if r is None:
            raise Refused(f"REFUSED: there's no brief item [B{brief_id}].")
        return r

    def comment(self, brief_id: int, text: str) -> list[str]:
        r = self.row(brief_id)
        if r["status"] not in OPEN:
            raise Refused(f"REFUSED: [B{brief_id}] is already {r['status']}.")
        text = " ".join(text.split())
        violations = [str(v) for v in policy.check(text, policy.Context(self.phase, "outbound"), self.kn.rules)]
        used = self.ledger.db.execute(
            "SELECT comment FROM brief_posts WHERE comment IS NOT NULL AND id != ? "
            "UNION ALL SELECT text FROM browser_steps WHERE text IS NOT NULL",
            (brief_id,),
        ).fetchall()
        key = _norm(text).lower()
        if any(_norm(u[0]).lower() == key or _norm(u[0]).lower()[:40] == key[:40] for u in used):
            violations.append("used before: write each comment fresh, never the same one twice (growth plan 6.3)")
        self.ledger.db.execute(
            "UPDATE brief_posts SET comment = ?, violations = ?, status = ? WHERE id = ?",
            (text, json.dumps(violations), "proposed" if violations else "ready", brief_id),
        )
        return violations

    # --- the list a person posts from ------------------------------------------------------------------
    def ready(self):
        return self.ledger.db.execute(
            "SELECT * FROM brief_posts WHERE status = 'ready' AND created_at >= ? ORDER BY id",
            ((self.now - timedelta(hours=self.cfg.brief_max_age_hours)).isoformat(),),
        ).fetchall()

    def waiting(self):
        return self.ledger.db.execute(
            "SELECT * FROM brief_posts WHERE status = 'proposed' AND created_at >= ? ORDER BY id",
            ((self.now - timedelta(hours=self.cfg.brief_max_age_hours)).isoformat(),),
        ).fetchall()

    def mark(self, ids: list[int], status: str) -> list[str]:
        out = []
        for i in ids:
            r = self.row(i)
            if r["status"] not in OPEN:
                out.append(f"[B{i}] is already {r['status']}.")
                continue
            self.ledger.db.execute(
                "UPDATE brief_posts SET status = ?, done_at = ? WHERE id = ?", (status, self.now.isoformat(), i)
            )
            out.append(f"[B{i}] @{r['creator']}: {status}.")
        return out

    def stats(self) -> dict[str, int]:
        since = day_ago(self.now).isoformat()
        rows = self.ledger.db.execute(
            "SELECT status, COUNT(*) FROM brief_posts WHERE created_at >= ? GROUP BY status", (since,)
        )
        return {s: n for s, n in rows}


def ago(now: datetime, then: datetime) -> str:
    hours = int((now - then).total_seconds() // 3600)
    return "just now" if hours < 1 else f"{hours} h ago"


def ids_from(values: list[str]) -> list[int]:
    out = []
    for v in values:
        for part in v.replace(",", " ").split():
            m = re.fullmatch(r"[Bb]?(\d+)", part)
            if not m:
                raise Refused(f'REFUSED: "{part}" isn\'t a brief number (like B12).')
            out.append(int(m.group(1)))
    return out
