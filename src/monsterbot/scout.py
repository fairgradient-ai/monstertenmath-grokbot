"""Finding the right creators, by the growth plan's criteria (6.3 and 6.5), through Meta's read-only APIs.

Candidates come from three places:
  1. seeds: usernames the owner or the Grok Bot adds ("scout add @name"), e.g. from Grok's own web search;
  2. our commenters: parents who already comment on our posts and run a creator account are the warmest leads;
  3. hashtags: the @mentions in the top posts under the plan's hashtags (hashtag posts don't name their author).
Each candidate's public profile is read with Business Discovery and scored. Nothing is posted, followed or
liked anywhere: the scout only reads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .channels.instagram import parse_time
from .config import Config
from .errors import ChannelError
from .knowledge import Knowledge
from .ledger import Ledger
from .models import Profile

TOPIC = re.compile(
    r"\b(kindergarten|kinder|preschool\w*|pre-?k|homeschool\w*|math\w*|counting|numbers?|number sense|montessori|"
    r"toddler\w*|learning|play[- ]based|teacher|educator|mom of|mama|mum of|dad of|kids activities|activities|"
    r"early years|early childhood|ten[- ]frame|stem)\b",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MENTION = re.compile(r"(?<![\w.])@([A-Za-z0-9_.]*[A-Za-z0-9_])")
GIVEAWAY = re.compile(r"giveaway|enter to win|\bwin a\b", re.IGNORECASE)
STATUSES = ("seed", "new", "shortlist", "drafted", "contacted", "booked", "declined", "rejected", "unreachable")


@dataclass
class Score:
    score: int
    notes: list[str] = field(default_factory=list)
    email: str | None = None
    engagement: float = 0.0
    last_post: datetime | None = None


def score_profile(p: Profile, cfg: Config, kn: Knowledge, now: datetime) -> Score:
    notes: list[str] = []
    f = p.followers
    if 10_000 <= f <= 40_000:
        pts = 30
        notes.append("10k–40k followers: the Collab sweet spot (6.5)")
    elif cfg.scout_followers_min <= f <= cfg.scout_followers_max:
        pts = 20
    else:
        pts = 0
        notes.append(f"{f:,} followers: outside {cfg.scout_followers_min:,}–{cfg.scout_followers_max:,}")

    rates = [((post.get("like_count") or 0) + (post.get("comments_count") or 0)) / f for post in p.posts if f]
    eng = sum(rates) / len(rates) if rates else 0.0
    pts += 25 if eng >= 0.03 else 15 if eng >= 0.01 else 5 if eng >= 0.005 else 0
    if rates and eng < 0.005:
        notes.append(f"engagement {eng:.1%}: few real comments")

    times = [parse_time(post["timestamp"]) for post in p.posts if post.get("timestamp")]
    last = max(times) if times else None
    if last is not None:
        days = (now - last).days
        pts += 15 if days <= 7 else 8 if days <= 30 else 0
        if days > 30:
            notes.append(f"last post {days} days ago")

    text = " ".join([p.biography, *[post.get("caption") or "" for post in p.posts]])
    topics = {m.group(0).lower() for m in TOPIC.finditer(text)}
    pts += min(30, 6 * len(topics))
    if not topics:
        notes.append("nothing about young children's learning in the bio or recent posts")

    rivals = [r for r in kn.rules.get("rivals", []) if r.lower() in text.lower()]
    rival_re = next((pat for reason, pat in kn.escalate if reason == "rival"), None)
    if rivals or (rival_re and rival_re.search(text)):
        pts = 0
        notes.append("works with or mentions a rival: never contact")
    giveaways = sum(1 for post in p.posts if GIVEAWAY.search(post.get("caption") or ""))
    if giveaways >= 3:
        pts = max(0, pts - 10)
        notes.append(f"{giveaways} giveaway posts of {len(p.posts)}")

    # The growth plan wants real comments on recent posts, and the follower range: without them, never near the top.
    if f and not (cfg.scout_followers_min <= f <= cfg.scout_followers_max):
        pts = min(pts, 20)
    if (rates and eng < 0.005) or (last is not None and (now - last).days > 30):
        pts = min(pts, 40)

    email = None
    m = EMAIL.search(p.biography or "")
    if m:
        email = m.group(0).rstrip(".")
    else:
        notes.append("no email in the bio: outreach needs one")
    return Score(score=pts, notes=notes, email=email, engagement=eng, last_post=last)


class Scout:
    def __init__(self, cfg: Config, kn: Knowledge, ledger: Ledger, graph, now: datetime):
        self.cfg, self.kn, self.ledger, self.graph, self.now = cfg, kn, ledger, graph, now

    def pick_hashtags(self) -> list[str]:
        """At most 30 different hashtags in a rolling 7 days; re-asking one already used is free."""
        used = self.ledger.hashtags_since(self.now - timedelta(days=7))
        budget = max(0, 30 - len(used))
        fresh = [t for t in self.cfg.scout_hashtags if t not in used][:budget]
        reused = sorted((t for t in self.cfg.scout_hashtags if t in used), key=lambda t: used[t])
        return (fresh + reused)[: self.cfg.scout_hashtags_per_run]

    def candidates(self, notes: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in self.ledger.creators(statuses=("seed",), limit=500):
            out[row["username"]] = "seed"
        since = (self.now - timedelta(days=30)).isoformat()
        handle = self.cfg.username.lower()
        rows = self.ledger.db.execute(
            "SELECT DISTINCT author FROM items WHERE channel = 'instagram' AND created_at >= ? AND author IS NOT NULL",
            (since,),
        )
        for (author,) in rows:
            if author and author.lower() != handle:
                out.setdefault(author.lower(), "commented on our posts")
        for tag in self.pick_hashtags():
            try:
                posts = self.graph.hashtag_top_media(tag)
            except ChannelError as e:
                if e.kind in ("permission", "bad_request"):
                    notes.append(f"hashtag search skipped ({e}): it needs Instagram Public Content Access (App Review)")
                    break
                raise
            self.ledger.record_hashtag(tag, self.now)
            for post in posts:
                for name in MENTION.findall(post.get("caption") or ""):
                    if name.lower() != handle:
                        out.setdefault(name.lower(), f"tagged in a top #{tag} post")
        return out

    def run(self) -> tuple[list[str], list[str]]:
        """Returns (looked-up usernames, notes)."""
        notes: list[str] = []
        recheck = self.now - timedelta(days=self.cfg.scout_recheck_days)
        looked: list[str] = []
        for username, source in self.candidates(notes).items():
            if len(looked) >= self.cfg.scout_max_lookups:
                notes.append(f"stopped at {self.cfg.scout_max_lookups} lookups; the rest wait for the next run")
                break
            row = self.ledger.creator(username)
            if row and row["status"] != "seed" and row["checked_at"] and row["checked_at"] >= recheck.isoformat():
                continue
            if row and row["status"] in ("rejected", "declined", "booked"):
                continue
            profile = self.graph.business_discovery(username)
            looked.append(username)
            if profile is None:
                self.ledger.upsert_creator(
                    username,
                    self.now,
                    status="unreachable",
                    source=source,
                    checked_at=self.now.isoformat(),
                    score_notes=json.dumps(["personal or private account"]),
                )
                continue
            s = score_profile(profile, self.cfg, self.kn, self.now)
            status = row["status"] if row and row["status"] not in ("seed", "unreachable") else "new"
            if s.score == 0 and any("rival" in n for n in s.notes):
                status = "rejected"
            self.ledger.upsert_creator(
                username,
                self.now,
                name=profile.name,
                followers=profile.followers,
                media_count=profile.media_count,
                engagement=round(s.engagement, 4),
                last_post=s.last_post.isoformat() if s.last_post else None,
                biography=profile.biography,
                website=profile.website,
                email=s.email,
                captions=json.dumps([post.get("caption") or "" for post in profile.posts[:6]], ensure_ascii=False),
                score=s.score,
                score_notes=json.dumps(s.notes, ensure_ascii=False),
                source=(row["source"] if row and row["source"] and row["source"] != "seed" else source),
                status=status,
                checked_at=self.now.isoformat(),
            )
        return looked, notes
