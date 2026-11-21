"""Insights: how each of our posts did, and what that says about pillars, ads and posting times.

`collect` reads Meta's per-post insights (one metric at a time) into the ledger. Everything else reads only the
ledger, so a report can be run as often as wanted without spending API calls:

- `report`: the nightly (or weekly) summary: best and weakest posts, the community, the growth work.
- `ads`: which posts are worth promoting, inside the pack's filters. It never spends and never touches Ads Manager.
- `pillars`: each pillar's score, what parents keep asking about, and proposals the owner can adopt.
- `timing`: engagement by posting slot, shrunk toward the account median so one lucky post doesn't move a slot.

Rates are per reach, compared with the account's own median (1.0 = typical), so small numbers in week one don't
read as verdicts: below `min_posts` posts with reach >= `min_reach`, a verdict is "too early".
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from statistics import median

from . import policy
from .knowledge import PILLARS

COMMON = ("reach", "likes", "comments", "saved", "shares", "total_interactions", "views")
FEED_ONLY = ("follows", "profile_visits")
REEL_ONLY = ("ig_reels_avg_watch_time",)

# Themes parents ask about (plan 6.7). Health and development are never a pillar: they stay with the owner.
THEMES = {
    "ages": r"\b[2-7][ -]?(year|yr)s?[ -]?old\b|\btoddler\b|\bpreschooler\b",
    "screen time": r"screen ?time|too much screen|on a screen",
    "no crackers": r"don'?t have crackers|instead of crackers|no crackers|allerg|gluten|cheerios|grapes|buttons",
    "siblings": r"\bsiblings?\b|\btwins?\b|older (brother|sister)|younger (brother|sister)|both kids",
    "classroom": r"\bclass(room)?\b|\bteacher\b|\bhomeschool",
    "how long": r"how long|how many minutes|every night|how often",
    "wrong answers": r"gets? it wrong|wrong answer|frustrat|gives? up|cries",
}
NEVER_A_PILLAR = r"speech|delay|autis|adhd|diagnos|therap|dyscalcul"


def _rate(n: int | None, reach: int) -> float:
    return (n or 0) / reach if reach else 0.0


class Insights:
    def __init__(self, cfg, kn, ledger, phase: str, pricing: str, now: datetime):
        self.cfg, self.kn, self.ledger, self.phase, self.pricing, self.now = cfg, kn, ledger, phase, pricing, now
        self.db = ledger.db

    # --- collecting ----------------------------------------------------------------------------------
    def collect(self, channel) -> list[str]:
        """Reads insights for our posts from the last lookback_days. Returns notes (one line each)."""
        day = self.now.astimezone(self.cfg.tz).date().isoformat()
        since = self.now - timedelta(days=self.cfg.insights_lookback_days)
        notes: list[str] = []
        n = 0
        for m in channel.recent_media(50):
            if m.timestamp < since:
                continue
            piece = self.kn.match_piece(m.caption)
            self.db.execute(
                "INSERT INTO media_posts (media_id, piece, kind, posted_at, caption_start, permalink, updated_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET piece=excluded.piece, kind=excluded.kind, "
                "posted_at=excluded.posted_at, caption_start=excluded.caption_start, permalink=excluded.permalink, "
                "updated_at=excluded.updated_at",
                (
                    m.id,
                    piece.key if piece else None,
                    m.media_type,
                    m.timestamp.isoformat(),
                    (m.caption or "")[:60],
                    m.permalink,
                    self.now.isoformat(),
                ),
            )
            metrics = COMMON + (REEL_ONLY if m.media_type in ("VIDEO", "REELS") else FEED_ONLY)
            values = channel.media_insights(m.id, metrics)
            for metric, value in values.items():
                self.db.execute(
                    "INSERT INTO media_insights (media_id, day, metric, value) VALUES (?,?,?,?) "
                    "ON CONFLICT(media_id, day, metric) DO UPDATE SET value=excluded.value",
                    (m.id, day, metric, value),
                )
            n += 1
        notes.append(f"read insights for {n} posts from the last {self.cfg.insights_lookback_days} days")
        return notes

    # --- reading the ledger --------------------------------------------------------------------------
    def posts(self, days: int | None = None) -> list[dict]:
        """Each post with its newest value of each metric."""
        since = (self.now - timedelta(days=days or self.cfg.insights_lookback_days)).isoformat()
        out = []
        for p in self.db.execute("SELECT * FROM media_posts WHERE posted_at >= ? ORDER BY posted_at", (since,)):
            values: dict[str, int] = {}
            for r in self.db.execute(
                "SELECT metric, value FROM media_insights WHERE media_id=? ORDER BY day", (p["media_id"],)
            ):
                values[r["metric"]] = r["value"]
            piece = self.kn.piece(p["piece"])
            out.append(
                {
                    "media_id": p["media_id"],
                    "piece": piece,
                    "label": piece.label if piece else (p["caption_start"] or p["media_id"])[:30],
                    "pillar": piece.pillar if piece else "unknown",
                    "kind": p["kind"] or "",
                    "posted_at": datetime.fromisoformat(p["posted_at"]),
                    "caption": p["caption_start"] or "",
                    "v": values,
                }
            )
        return out

    def _qualified(self, posts: list[dict], min_age_hours: int = 72, min_reach: int | None = None) -> list[dict]:
        floor = self.cfg.insights_min_reach if min_reach is None else min_reach
        cutoff = self.now - timedelta(hours=min_age_hours)
        return [p for p in posts if p["posted_at"] <= cutoff and (p["v"].get("reach") or 0) >= floor]

    @staticmethod
    def _rates(p: dict) -> dict[str, float]:
        v, reach = p["v"], p["v"].get("reach") or 0
        return {
            "shares": _rate(v.get("shares"), reach),
            "saved": _rate(v.get("saved"), reach),
            "follows": _rate(v.get("follows") or v.get("profile_visits"), reach),
            "comments": _rate(v.get("comments"), reach),
            "engagement": _rate(v.get("total_interactions"), reach),
        }

    def _relative(self, posts: list[dict]) -> list[tuple[dict, dict[str, float]]]:
        """Each post's rates divided by the account median for that rate (1.0 = typical)."""
        rates = [self._rates(p) for p in posts]
        meds = {k: median([r[k] for r in rates]) if rates else 0.0 for k in ("shares", "saved", "follows", "comments")}
        out = []
        for p, r in zip(posts, rates, strict=True):
            out.append((p, {k: (r[k] / meds[k] if meds[k] else (1.0 if r[k] == 0 else 2.0)) for k in meds}))
        return out

    # --- report --------------------------------------------------------------------------------------
    def report(self, days: int = 1, followers: int | None = None) -> list[str]:
        local = self.now.astimezone(self.cfg.tz)
        posts = self.posts()
        head = f"INSIGHTS · {local:%a %d %b} · " + (f"{followers:,} followers · " if followers is not None else "")
        lines = [head + f"{len(posts)} posts tracked" + (" · the last 7 days" if days == 7 else "")]
        window = [p for p in posts if p["posted_at"] >= self.now - timedelta(days=max(days, 3) + 27)]
        q = self._qualified(window)
        if len(q) < self.cfg.insights_min_posts:
            lines.append(
                f"Too early for best and weakest: {len(q)} posts are 3 days old with reach "
                f">= {self.cfg.insights_min_reach} (need {self.cfg.insights_min_posts})."
            )
        else:
            ranked = sorted(q, key=lambda p: self._rates(p)["shares"], reverse=True)
            med = median([self._rates(p)["shares"] for p in q]) or 0
            lines.append("Best 3 days ago or older, by shares per 1,000 reach:")
            for p in ranked[:3]:
                lines.append("  " + self._line(p))
            worst = ranked[-1]
            ratio = (self._rates(worst)["shares"] / med) if med else 0
            lines.append(f"Weakest: {self._line(worst)} ({ratio:.1f}× the median)")
        lines.append(self._community(days))
        lines.append(self._growth(days))
        return lines

    def _line(self, p: dict) -> str:
        r, reach = self._rates(p), p["v"].get("reach") or 0
        return (
            f"{p['label'][:28]:<28} reach {reach:,} · shares {r['shares'] * 1000:.1f}/1k · saves "
            f"{r['saved'] * 1000:.1f}/1k · follows {r['follows'] * 1000:.1f}/1k · pillar {p['pillar']}"
        )

    def _community(self, days: int) -> str:
        since = (self.now - timedelta(days=days)).isoformat()
        rows = self.db.execute(
            "SELECT status, category, first_seen, replied_at FROM items WHERE first_seen >= ?", (since,)
        ).fetchall()
        total = len(rows)
        needs = [r for r in rows if r["category"] not in ("spam", "own", "tag-only")]
        answered = [r for r in needs if r["status"] == "replied"]
        waits = [
            (datetime.fromisoformat(r["replied_at"]) - datetime.fromisoformat(r["first_seen"])).total_seconds() / 60
            for r in answered
            if r["replied_at"] and r["first_seen"]
        ]
        waiting = sum(1 for r in rows if r["status"] in ("queued", "drafted"))
        spam = sum(1 for r in rows if r["category"] == "spam")
        pct = f"{100 * len(answered) // len(needs)}% answered" if needs else "nothing to answer"
        med = f" · median first reply {int(median(waits))} min" if waits else ""
        return f"Community: {total} comments and DMs · {pct}{med} · {waiting} waiting for you · {spam} spam"

    def _growth(self, days: int) -> str:
        since = (self.now - timedelta(days=days)).isoformat()
        brief = dict(
            self.db.execute(
                "SELECT status, COUNT(*) FROM brief_posts WHERE created_at >= ? GROUP BY status", (since,)
            ).fetchall()
        )
        did: dict[str, int] = {"comment": 0, "like": 0, "follow": 0}
        for (d,) in self.db.execute("SELECT did FROM browser_steps WHERE status='done' AND done_at >= ?", (since,)):
            for a in (d or "").split(","):
                if a in did:
                    did[a] += 1
        stops = self.db.execute(
            "SELECT COUNT(*) FROM browser_sessions WHERE status='stopped' AND ended_at >= ?", (since,)
        ).fetchone()[0]
        return (
            f"Growth work: brief {brief.get('done', 0)} commented · {brief.get('liked', 0)} liked · "
            f"{brief.get('ready', 0) + brief.get('proposed', 0)} open · browser {did['like']} likes, "
            f"{did['comment']} comments, {did['follow']} follows · "
            + (f"{stops} stopped session(s): read browser status" if stops else "no warnings")
        )

    # --- ads -----------------------------------------------------------------------------------------
    def ads(self) -> list[str]:
        posts = self._qualified(self.posts(), min_age_hours=48, min_reach=max(500, self.cfg.insights_min_reach))
        lines = ["ADS · suggestions only: the Bot never spends and never touches Ads Manager"]
        keep, dropped = [], []
        for p in posts:
            why = self._ad_blocker(p)
            (dropped if why else keep).append((p, why))
        if len(keep) < self.cfg.insights_min_posts:
            lines.append(
                f"Too early: {len(keep)} posts pass the filters (48 hours old, reach >= 500); "
                f"need {self.cfg.insights_min_posts} to compare."
            )
        else:
            scored = []
            for p, rel in self._relative([p for p, _ in keep]):
                watch = rel["comments"]
                score = 0.45 * rel["shares"] + 0.25 * rel["follows"] + 0.15 * rel["saved"] + 0.15 * watch
                scored.append((score, p, rel))
            scored.sort(key=lambda t: t[0], reverse=True)
            goal = (
                "objective Profile visits or Reach (growth plan 5.1: pre-launch ads buy profile visits)"
                if self.phase == "building"
                else "objective Traffic to monstertenmath.com/insta; Sales only once the Meta Pixel and CAPI are on"
            )
            for i, (score, p, rel) in enumerate(scored[:3], 1):
                lines.append(
                    f"{i}. {p['label'][:34]} · ad score {score:.2f} · shares {rel['shares']:.1f}× · "
                    f"follows {rel['follows']:.1f}× · saves {rel['saved']:.1f}× the median"
                )
                lines.append(
                    f"   boost the existing post (keeps its AI label and its comments) · {goal}"
                    if p["piece"] and p["piece"].ai
                    else f"   boost the existing post · {goal}"
                )
        for p, why in dropped[:5]:
            lines.append(f"not an ad: {p['label'][:34]}: {why}")
        lines.append("Budget: the growth plan's rule only. You decide and you act in Ads Manager.")
        return lines

    def _ad_blocker(self, p: dict) -> str | None:
        piece, cap = p["piece"], p["caption"].lower()
        if piece is None:
            return "not in pieces.toml, so its rules can't be checked"
        if piece.pillar == "brand":
            return "a brand or launch post"
        if piece.child and not piece.ad_cleared:
            return "a real child on screen without an ad release (ad_cleared)"
        if self.phase == "building" and "link in bio" in cap:
            return "points to the site before launch"
        if self.phase == "open" and "being built" in cap:
            return 'says "being built" after launch'
        if self.pricing != "founding" and re.search(r"founding|\$59\.99|\$9\.99", cap):
            return "names the founding price, which is off"
        bad = policy.check(p["caption"] or piece.caption_start, policy.Context(self.phase, "caption"), self.kn.rules)
        if bad:
            return f"its caption breaks a rule ({bad[0].id})"
        return None

    # --- pillars -------------------------------------------------------------------------------------
    def pillars(self) -> list[str]:
        posts = self._qualified(self.posts())
        lines = ["PILLARS · score = shares 0.4, saves 0.3, follows 0.2, comments 0.1, against the account median"]
        groups: dict[str, list[float]] = {}
        for p, rel in self._relative(posts):
            s = 0.4 * rel["shares"] + 0.3 * rel["saved"] + 0.2 * rel["follows"] + 0.1 * rel["comments"]
            groups.setdefault(p["pillar"], []).append(s)
        for pid, name in PILLARS.items():
            if pid == "brand":
                continue
            scores = groups.get(pid, [])
            if len(scores) < self.cfg.insights_min_posts:
                verdict = f"too early ({len(scores)} posts)"
            else:
                m = median(scores)
                verdict = f"{m:.2f} · " + (
                    "double down: 2 more this fortnight, and a spin-off is worth proposing"
                    if m >= 1.3
                    else "rework the hook (first 2 seconds, cover) or rest it a fortnight"
                    if m <= 0.7
                    else "keep going"
                )
            lines.append(f"  {pid:<11} {verdict} · {name}")
        lines.append("Demand, the last 14 days of comments and DMs:")
        lines.extend("  " + t for t in self.demand())
        open_props = self.db.execute(
            "SELECT id, body FROM pillar_proposals WHERE status='proposed' ORDER BY id"
        ).fetchall()
        for r in open_props:
            lines.append(f"Proposal P{r['id']} (waiting for you): {r['body'].splitlines()[0][:90]}")
        return lines

    def demand(self) -> list[str]:
        since = (self.now - timedelta(days=14)).isoformat()
        texts = [r[0] or "" for r in self.db.execute("SELECT text FROM items WHERE first_seen >= ?", (since,))]
        counts = {name: sum(1 for t in texts if re.search(pat, t, re.I)) for name, pat in THEMES.items()}
        health = sum(1 for t in texts if re.search(NEVER_A_PILLAR, t, re.I))
        out = [
            f"{name}: {n}" + (" · a pillar candidate (5+)" if n >= 5 else "")
            for name, n in sorted(counts.items(), key=lambda kv: -kv[1])
            if n
        ]
        if health:
            out.append(f"health or development: {health} (never a pillar: these stay one-to-one with you)")
        return out or ["nothing repeated yet"]

    def propose(self, body: str) -> tuple[int, list[str]]:
        """Saves a pillar proposal the Bot wrote. Every line goes through the caption check."""
        problems = []
        for line in body.splitlines():
            if line.strip():
                problems += [str(v) for v in policy.check(line, policy.Context(self.phase, "caption"), self.kn.rules)]
        if re.search(NEVER_A_PILLAR, body, re.I):
            problems.append("health-topic: health and development questions are never a pillar")
        cur = self.db.execute(
            "INSERT INTO pillar_proposals (created_at, body, violations) VALUES (?,?,?)",
            (self.now.isoformat(), body.strip(), "; ".join(problems) or None),
        )
        return int(cur.lastrowid), problems

    # --- timing --------------------------------------------------------------------------------------
    def timing(self, k: int = 5) -> list[str]:
        """Median engagement per reach by local weekday and hour, shrunk toward the account median with k posts
        of weight: est = (n × slot + k × all) / (n + k). Buffer's study (9.6M posts) is the prior the owner knows;
        this is what our own posts say."""
        posts = self._qualified(self.posts(), min_age_hours=48)
        lines = [f"TIMING · {len(posts)} posts with reach >= {self.cfg.insights_min_reach}, by local slot (ET)"]
        if len(posts) < self.cfg.insights_min_posts:
            return [*lines, "Too early: keep Buffer's times (plan 0.6) until there are more posts."]
        all_med = median([self._rates(p)["engagement"] for p in posts])
        slots: dict[str, list[float]] = {}
        for p in posts:
            local = p["posted_at"].astimezone(self.cfg.tz)
            slots.setdefault(f"{local:%a} {local:%H}:00", []).append(self._rates(p)["engagement"])
        rows = []
        for slot, vals in slots.items():
            n = len(vals)
            est = (n * median(vals) + k * all_med) / (n + k)
            rows.append((est / all_med if all_med else 1.0, slot, n))
        rows.sort(reverse=True)
        for rel, slot, n in rows[:8]:
            lines.append(f"  {slot:<10} {rel:.2f}× · {n} post(s)")
        lines.append("A slot needs about 5 posts before it moves much. Moves go by pull request to schedule.json.")
        return lines
