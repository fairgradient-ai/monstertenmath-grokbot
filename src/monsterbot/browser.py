"""Browser sessions: likes, comments and follows that the Grok Bot carries out in the Grok browser, one step at a
time, at a person's pace. The engine plans, counts and paces; the Grok Bot clicks. Nothing here touches Instagram.

What this can enforce: caps (day and session), the ramp, quiet hours, cooldowns, one session at a time, the gap
between sessions and the number per day (checked when the owner's tap *starts* a session, not only when it is
planned), and *when* each target is revealed (`next` hands out one link and one comment only after its gap). What
it can't: what the Bot does in the browser. It checks the Bot's reports instead (`done` sooner than the look time
is "early"; two end the session) and compares them with our own activity page (`verify`).

Two kinds of check, kept apart on purpose:
- guards on NEW actions (`plan`, `start`, `next`): off, paused, cooling down, quiet hours, lapsed, spacing;
- RECORDING (`done`, `verify`): never refused for those reasons. A like or comment the Bot already made must be
  counted, or the day caps undercount and that night's verify pauses everything for a click that really happened.

All timestamps are engine.now(): UTC ISO strings, like the rest of the ledger, so they compare as text. "Today" is
the desk's local day (America/New_York), turned into a UTC range for queries.
"""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime, timedelta

from . import policy
from .errors import Refused

RNG = random.SystemRandom()
MAX_SLEEP = 150  # one call never sleeps longer, so a Grok command timeout can't lose state
LAPSE = timedelta(hours=3)  # a started session gets no new steps after this
STALE = timedelta(hours=6)  # an issued step never reported by then is marked 'handed out, never reported'
ACTIONS = ("comment", "like", "follow")  # the only things that count toward caps
ALLOWED = {  # what `done --did` may report for each step kind
    "check": set(),
    "glance": set(),
    "verify": set(),
    "comment": {"comment", "like", "already-liked"},
    "like": {"like", "already-liked"},
    "like_reply": {"like", "already-liked"},
    "follow": {"follow", "already-following"},
}
NEEDS = {"comment": "comment", "like": "like", "like_reply": "like", "follow": "follow"}  # the cap a step uses


def caps(cfg, now_local: datetime) -> dict[str, dict[str, int]]:
    """Day and session caps. One table, the same one as plan 6.6 and the config comments."""
    days = (now_local.date() - datetime.fromisoformat(cfg.browser_ramp_start).date()).days
    if days < 7:
        return {"day": {"comment": 15, "like": 30, "follow": 0}, "session": {"comment": 8, "like": 12, "follow": 0}}
    if days < 14:
        return {"day": {"comment": 25, "like": 50, "follow": 10}, "session": {"comment": 8, "like": 15, "follow": 5}}
    return {
        "day": {
            "comment": cfg.browser_max_comments_per_day,
            "like": cfg.browser_max_likes_per_day,
            "follow": cfg.browser_max_follows_per_day,
        },
        "session": {
            "comment": cfg.browser_max_comments_per_session,
            "like": cfg.browser_max_likes_per_session,
            "follow": cfg.browser_max_follows_per_session,
        },
    }


def _hhmm_minus(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    t = (h * 60 + m - minutes) % (24 * 60)
    return f"{t // 60:02d}:{t % 60:02d}"


class Browser:
    def __init__(self, cfg, kn, ledger, phase: str, now):
        self.cfg, self.kn, self.ledger, self.phase, self.now = cfg, kn, ledger, phase, now  # now() is UTC
        self.db = ledger.db

    # --- guards on new actions ---------------------------------------------------------------------------
    def _blocked(self, quiet: bool = True) -> str | None:
        """Why no NEW step may begin now, or None."""
        if not self.cfg.browser_enabled:
            return "browser sessions are off ([browser] enabled = false)"
        paused = self.ledger.kv_get("browser.paused")
        if paused:
            return f"paused: {paused}. The owner looks at the activity page, then says browser resume"
        until = self.ledger.kv_get("browser.cooldown_until")
        if until and datetime.fromisoformat(until) > self.now():
            return f"cooling down until {until} after: {self.ledger.kv_get('browser.stop_reason')}"
        if quiet:
            local = self.now().astimezone(self.cfg.tz).strftime("%H:%M")
            if not (self.cfg.browser_quiet_end <= local < self.cfg.browser_quiet_start):
                return (
                    f"quiet hours: nothing in the browser between {self.cfg.browser_quiet_start} and "
                    f"{self.cfg.browser_quiet_end}"
                )
        return None

    def _guard(self, quiet: bool = True) -> None:
        why = self._blocked(quiet)
        if why:
            raise Refused(f"REFUSED: {why}.")

    def _session(self, session: int):
        row = self.db.execute("SELECT * FROM browser_sessions WHERE session=?", (session,)).fetchone()
        if row is None:
            raise Refused(f"REFUSED: there's no session S{session}. Run run.sh browser plan.")
        return row

    def _end(self, session: int, status: str, reason: str) -> None:
        """Ends a session: its planned steps expire (or stop), and the brief posts they held go back to the brief.
        Issued steps are left as they are, so a late `done` can still record a click the Bot made."""
        step_status = "stopped" if status == "stopped" else "expired"
        self.db.execute(
            "UPDATE browser_steps SET status=? WHERE session=? AND status='planned'", (step_status, session)
        )
        self.db.execute(
            "UPDATE brief_posts SET status='ready' WHERE status='in-session' AND id IN "
            "(SELECT brief_id FROM browser_steps WHERE session=? AND status=? AND brief_id IS NOT NULL)",
            (session, step_status),
        )
        self.db.execute(
            "UPDATE browser_sessions SET status=?, ended_at=?, end_reason=? WHERE session=? AND ended_at IS NULL",
            (status, self.now().isoformat(), reason[:200], session),
        )
        self.db.commit()

    def _lapse(self) -> None:
        """Housekeeping before any new action: started sessions past LAPSE end; steps handed out but never
        reported for STALE hours release their brief post as 'skipped' (a person checks it by hand: verify
        will show it if the Bot did comment)."""
        cutoff = (self.now() - LAPSE).isoformat()
        for (s,) in self.db.execute(
            "SELECT session FROM browser_sessions WHERE status='started' AND started_at < ?", (cutoff,)
        ).fetchall():
            self._end(s, "ended", "lapsed (3 hours)")
        stale = (self.now() - STALE).isoformat()
        for st in self.db.execute(
            "SELECT id, brief_id FROM browser_steps WHERE status='issued' AND issued_at < ?", (stale,)
        ).fetchall():
            self.db.execute(
                "UPDATE browser_steps SET status='expired', note='handed out, never reported' WHERE id=?", (st["id"],)
            )
            if st["brief_id"]:
                self.db.execute(
                    "UPDATE brief_posts SET status='skipped' WHERE id=? AND status='in-session'", (st["brief_id"],)
                )
        self.db.commit()

    def _running(self) -> int | None:
        row = self.db.execute("SELECT session FROM browser_sessions WHERE status='started'").fetchone()
        return row[0] if row else None

    def _spacing(self, session: int) -> None:
        """At most max_sessions_per_day STARTED sessions today, and session_gap_minutes since the last one
        ended (or its last reported step, whichever is later). Checked at start, where it matters."""
        _, lo, hi = self._today_utc()
        n = self.db.execute(
            "SELECT COUNT(*) FROM browser_sessions WHERE started_at >= ? AND started_at < ?", (lo, hi)
        ).fetchone()[0]
        if n >= self.cfg.browser_max_sessions_per_day:
            raise Refused(
                f"REFUSED: {n} sessions already started today; the most is {self.cfg.browser_max_sessions_per_day}."
            )
        last = self.db.execute(
            "SELECT MAX(t) FROM (SELECT MAX(ended_at) AS t FROM browser_sessions WHERE started_at IS NOT NULL "
            "UNION ALL SELECT MAX(done_at) FROM browser_steps WHERE status IN ('done','skipped'))"
        ).fetchone()[0]
        gap = timedelta(minutes=self.cfg.browser_session_gap_minutes)
        if last and self.now() - datetime.fromisoformat(last) < gap:
            ok_at = (datetime.fromisoformat(last) + gap).astimezone(self.cfg.tz)
            raise Refused(
                f"REFUSED: the last session ended at {last}. S{session} can start from "
                f"{ok_at:%H:%M}; say engage S{session} again then."
            )

    # --- counting --------------------------------------------------------------------------------------
    def _today_utc(self) -> tuple[str, str, str]:
        """The desk's local day as a UTC range [lo, hi). zoneinfo adds a day by the wall clock, so DST days are
        23 or 25 hours long, as they should be."""
        local = self.now().astimezone(self.cfg.tz)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return local.date().isoformat(), start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()

    def _count(self, where: str, params: tuple) -> dict[str, int]:
        """Counts what was actually done, from `did`, not from the step kind: a comment step usually also likes."""
        used = dict.fromkeys(ACTIONS, 0)
        for (did,) in self.db.execute(f"SELECT did FROM browser_steps WHERE status='done' AND {where}", params):
            for action in (did or "").split(","):
                if action in used:
                    used[action] += 1
        return used

    def used_today(self) -> dict[str, int]:
        """Browser steps + brief posts a person marked done by hand today (brief done) + browser manual."""
        day, lo, hi = self._today_utc()
        used = self._count("done_at >= ? AND done_at < ?", (lo, hi))
        used["comment"] += self.db.execute(
            "SELECT COUNT(*) FROM brief_posts WHERE status='done' AND done_at >= ? AND done_at < ? AND id NOT IN "
            "(SELECT brief_id FROM browser_steps WHERE brief_id IS NOT NULL AND status='done')",
            (lo, hi),
        ).fetchone()[0]
        for action in ACTIONS:
            used[action] += int(self.ledger.kv_get(f"browser.manual.{day}.{action}") or 0)
        return used

    def used_in_session(self, session: int) -> dict[str, int]:
        return self._count("session = ?", (session,))

    def _left(self, session: int) -> dict[str, int]:
        c = caps(self.cfg, self.now().astimezone(self.cfg.tz))
        today, sess = self.used_today(), self.used_in_session(session)
        left = {a: min(c["day"][a] - today[a], c["session"][a] - sess[a]) for a in ACTIONS}
        following = self.db.execute("SELECT COUNT(*) FROM follows").fetchone()[0] + int(
            self.ledger.kv_get("browser.following_before") or 0
        )
        left["follow"] = min(left["follow"], self.cfg.browser_max_following_total - following)
        return left

    # --- plan --------------------------------------------------------------------------------------------
    def plan(self) -> int:
        """Builds session S<n>. Any older plan that was never started expires here ('replaced by S<n>') and its
        brief posts go back to the pool, so a skipped tap never strands them. Refuses while a session is running
        or when the day's sessions are used up. (The 90-minute gap is checked at start: a plan made at 13:10 may be
        started at 13:40.) Takes, in order and within _left(): the brief's ready comments (fresh, not engaged
        before), likes on parents' comments on our posts, then (from day 7) the warm list's follows. 1 in 4 brief
        posts is 'like' only. Every comment is re-checked as category "outbound". Gaps RNG.randint(gap_min,
        gap_max), redrawn if within 10 s of the previous; dwell RNG.randint(dwell_min, dwell_max). Step 0 is
        'check'; the last step is 'verify' when the session has a comment. The printed plan shows kinds, not links
        or text."""
        self._guard()
        self._lapse()
        running = self._running()
        if running:
            raise Refused(f"REFUSED: S{running} is still running. Plan after it ends.")
        _, lo, hi = self._today_utc()
        if (
            self.db.execute(
                "SELECT COUNT(*) FROM browser_sessions WHERE started_at >= ? AND started_at < ?", (lo, hi)
            ).fetchone()[0]
            >= self.cfg.browser_max_sessions_per_day
        ):
            raise Refused("REFUSED: today's sessions are used up.")
        session = (self.db.execute("SELECT MAX(session) FROM browser_sessions").fetchone()[0] or 0) + 1
        for (old,) in self.db.execute("SELECT session FROM browser_sessions WHERE status='planned'").fetchall():
            self._end(old, "expired", f"never started; replaced by S{session}")
        left = self._left(session)
        engaged = {r[0] for r in self.db.execute("SELECT target FROM browser_steps WHERE status IN ('done','issued')")}
        steps: list[tuple[str, str, int | None, int | None, str | None]] = [("check", "self", None, None, None)]

        # 1. brief posts with a ready comment, fresh, never engaged
        for b in self.db.execute(
            "SELECT id, permalink, comment, posted_at FROM brief_posts WHERE status='ready' AND comment IS NOT NULL "
            "ORDER BY posted_at DESC"
        ).fetchall():
            if b["permalink"] in engaged or not self._fresh_at(b["posted_at"]):
                continue
            like_only = RNG.random() * 100 < self.cfg.browser_like_only_share
            if not like_only and left["comment"] > 0:
                bad = [
                    str(v) for v in policy.check(b["comment"], policy.Context(self.phase, "outbound"), self.kn.rules)
                ]
                if bad:  # re-checked now: rules or phase may have changed
                    self.db.execute("UPDATE brief_posts SET violations=? WHERE id=?", ("; ".join(bad), b["id"]))
                    like_only = True  # the comment never enters the plan
                else:
                    steps.append(("comment", b["permalink"], b["id"], None, b["comment"]))
                    left["comment"] -= 1
                    left["like"] -= 1 if left["like"] > 0 else 0
                    continue
            if left["like"] > 0:
                steps.append(("like", b["permalink"], b["id"], None, None))
                left["like"] -= 1

        # 2. likes on parents' comments on our posts (the warm list's first touch), not yet liked
        for it in self.db.execute(
            "SELECT id, external_id, author FROM items WHERE channel='instagram' AND parent_external_id IS NULL "
            "AND category IN ('praise','played','guess','thread') AND first_seen >= ? ORDER BY first_seen DESC",
            ((self.now() - timedelta(days=2)).isoformat(),),
        ).fetchall():
            if left["like"] <= 0:
                break
            if f"comment:{it['external_id']}" in engaged:
                continue
            steps.append(("like_reply", f"comment:{it['external_id']}", None, it["id"], None))
            left["like"] -= 1

        # 3. follows from the warm list (4.3), from day 7, never someone already followed
        for username in self.warm_list():
            if left["follow"] <= 0:
                break
            if self.db.execute("SELECT 1 FROM follows WHERE username=?", (username,)).fetchone():
                continue
            steps.append(("follow", username, None, None, None))
            left["follow"] -= 1

        if len(steps) == 1:
            self.db.commit()
            return 0  # nothing to do: cli prints "NO PLAN"
        if any(k == "comment" for k, *_ in steps):
            steps.append(("verify", "self", None, None, None))
        self.db.execute(
            "INSERT INTO browser_sessions (session, planned_at) VALUES (?, ?)", (session, self.now().isoformat())
        )
        prev_gap = None
        for seq, (kind, target, brief_id, item_id, text) in enumerate(steps):
            gap = RNG.randint(self.cfg.browser_gap_seconds_min, self.cfg.browser_gap_seconds_max)
            while prev_gap is not None and abs(gap - prev_gap) < 10:
                gap = RNG.randint(self.cfg.browser_gap_seconds_min, self.cfg.browser_gap_seconds_max)
            prev_gap = gap
            dwell = RNG.randint(self.cfg.browser_dwell_seconds_min, self.cfg.browser_dwell_seconds_max)
            self.db.execute(
                "INSERT INTO browser_steps (session, seq, kind, target, brief_id, item_id, text, dwell_seconds, "
                "gap_seconds) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    session,
                    seq,
                    kind,
                    target,
                    brief_id,
                    item_id,
                    text,
                    0 if kind in ("check", "verify") else dwell,
                    0 if kind in ("check", "verify") else gap,
                ),
            )
            if brief_id:  # held: off the brief, so nobody posts it by hand too
                self.db.execute("UPDATE brief_posts SET status='in-session' WHERE id=? AND status='ready'", (brief_id,))
        self.db.commit()
        return session

    def start(self, session: int, owner_tapped: bool) -> str:
        """The one Ask-first step of a session. Checks everything that decides whether a session may begin NOW:
        the plan is the newest and under plan_valid_minutes old, nothing else is running, the day's count and the
        gap since the last session."""
        if not owner_tapped:
            raise Refused(
                f"REFUSED: starting S{session} is the owner's tap: run.sh browser start S{session} --owner-tapped."
            )
        self._guard()
        self._lapse()
        s = self._session(session)
        if s["status"] != "planned":
            raise Refused(
                f"REFUSED: S{session} is {s['status']} ({s['end_reason'] or 'already started'}). "
                "Run run.sh browser plan for a fresh one."
            )
        if self.now() - datetime.fromisoformat(s["planned_at"]) > timedelta(
            minutes=self.cfg.browser_plan_valid_minutes
        ):
            self._end(session, "expired", "plan too old to start")
            raise Refused(
                f"REFUSED: S{session} was planned at {s['planned_at']}, more than "
                f"{self.cfg.browser_plan_valid_minutes} minutes ago. Run run.sh browser plan for a fresh one."
            )
        running = self._running()
        if running:
            raise Refused(f"REFUSED: S{running} is still running. One session at a time.")
        self._spacing(session)
        self.db.execute(
            "UPDATE browser_sessions SET status='started', started_at=? WHERE session=?",
            (self.now().isoformat(), session),
        )
        self.db.commit()
        return f"STARTED S{session}. Next: run.sh browser next S{session}."

    def resume(self, owner_tapped: bool) -> str:
        if not owner_tapped:
            raise Refused("REFUSED: resuming after a verify mismatch is the owner's tap.")
        self.ledger.kv_set("browser.paused", "")
        return "RESUMED: browser sessions may be planned again."

    def warm_list(self) -> list[str]:
        """4.3, from day 7 only: parents who commented on our posts twice or more in 14 days, then shortlisted
        creators (creators.status = 'shortlist'), excluding rivals, brands and anyone marked 'skip'."""
        c = caps(self.cfg, self.now().astimezone(self.cfg.tz))
        if c["day"]["follow"] <= 0:
            return []
        skip = {r.lower() for r in self.kn.rules.get("rivals", [])} | {self.cfg.username.lower()}
        skip |= {r[0] for r in self.db.execute("SELECT username FROM creators WHERE status = 'skip'")}
        since = (self.now() - timedelta(days=14)).isoformat()
        out: list[str] = []
        for r in self.db.execute(
            "SELECT lower(author) AS a, COUNT(*) AS n, MAX(first_seen) AS last FROM items WHERE channel = 'instagram' "
            "AND parent_external_id IS NULL AND author IS NOT NULL AND first_seen >= ? "
            "AND category NOT IN ('spam', 'escalate', 'own') GROUP BY lower(author) HAVING n >= 2 ORDER BY last DESC",
            (since,),
        ):
            if r["a"] not in skip and r["a"] not in out:
                out.append(r["a"])
        for r in self.db.execute(
            "SELECT username FROM creators WHERE status = 'shortlist' ORDER BY COALESCE(score, 0) DESC"
        ):
            if r[0] not in skip and r[0] not in out:
                out.append(r[0])
        return out

    def _fresh_at(self, posted_at: str | None) -> bool:
        return bool(posted_at) and self.now() - datetime.fromisoformat(posted_at) <= timedelta(
            hours=self.cfg.brief_max_age_hours
        )

    # --- run ---------------------------------------------------------------------------------------------
    def next(self, session: int) -> str:
        self._guard(quiet=False)  # quiet hours are checked per step below: verify may run late
        self._lapse()
        s = self._session(session)
        if s["status"] != "started":
            raise Refused(
                f"REFUSED: S{session} is {s['status']}"
                f"{' (' + s['end_reason'] + ')' if s['end_reason'] else ''}. The owner says engage "
                f"S{session} to start a planned session (run.sh browser start S{session} --owner-tapped)."
            )
        step = self.db.execute(
            "SELECT * FROM browser_steps WHERE session=? AND status IN ('planned','issued') ORDER BY seq LIMIT 1",
            (session,),
        ).fetchone()
        if step is None:
            self._end(session, "ended", "all steps done")
            return f"DONE S{session}: nothing left. Run run.sh browser status S{session}."
        if step["status"] == "issued":
            # the Bot asked again (a timeout): the same step, no new wait
            return self._describe(step, with_like=step["kind"] == "comment" and self._left(session)["like"] > 0)
        if step["kind"] in NEEDS:
            # no new action that could run into quiet hours: the last one is handed out last_call_minutes before
            local = self.now().astimezone(self.cfg.tz).strftime("%H:%M")
            last_call = _hhmm_minus(self.cfg.browser_quiet_start, self.cfg.browser_last_call_minutes)
            if not (self.cfg.browser_quiet_end <= local < last_call):
                self._mark(step["id"], "skipped", note="too close to quiet hours")
                return self.next(session)  # on to the next step: in the end verify, or DONE
        last = self.db.execute("SELECT MAX(done_at) FROM browser_steps WHERE status IN ('done','skipped')").fetchone()[
            0
        ]
        if last and step["kind"] not in ("check", "verify"):
            wait = (datetime.fromisoformat(last) + timedelta(seconds=step["gap_seconds"]) - self.now()).total_seconds()
            if wait > 0:
                time.sleep(min(wait, MAX_SLEEP))
                if wait > MAX_SLEEP:
                    return f"WAIT {int(wait - MAX_SLEEP)}s: run browser next S{session} again."
        if step["kind"] in ("comment", "like") and not self._still_fresh(step):
            self._mark(step["id"], "skipped", note="no longer fresh")
            return self.next(session)
        need = NEEDS.get(step["kind"])  # None for check / glance / verify: they use no cap
        left = self._left(session)
        if need and left[need] <= 0:
            self._mark(step["id"], "skipped", note=f"{need} cap reached (day, session or following total)")
            return self.next(session)
        self._mark(step["id"], "issued")  # sets issued_at = self.now().isoformat()
        # a comment step likes too only while likes are left
        return self._describe(step, with_like=step["kind"] == "comment" and left["like"] > 0)

    def done(self, session: int, seq: int, did: list[str], skip: str | None = None) -> str:
        """Records what the Bot says it did, for a step `next` handed out, with only the actions that step allows.
        NOT refused for quiet hours, a lapse, a pause, a cooldown or a stop: those stop new steps, but a click
        already made must be counted. (`check` is closed with `--ok`, which the CLI turns into did=[].)"""
        s = self._session(session)
        if s["started_at"] is None:
            raise Refused(f"REFUSED: S{session} was never started, so nothing in it was handed out.")
        step = self.db.execute("SELECT * FROM browser_steps WHERE session=? AND seq=?", (session, seq)).fetchone()
        if step is None or step["issued_at"] is None or step["status"] in ("done", "skipped"):
            raise Refused(f"REFUSED: S{session}.{seq} wasn't handed out by browser next, or is already recorded.")
        if step["kind"] == "verify":
            if not skip:
                raise Refused(
                    f"REFUSED: report the count with run.sh browser verify S{session} --others <n>, "
                    'or skip with --skip "<why>".'
                )
        bad = sorted(set(did) - ALLOWED[step["kind"]])
        if bad:
            raise Refused(f"REFUSED: a {step['kind']} step can't report {', '.join(bad)}.")
        now = self.now()
        spent = (now - datetime.fromisoformat(step["issued_at"])).total_seconds()
        early = not skip and step["kind"] in NEEDS and spent < step["dwell_seconds"]
        self.db.execute(
            "UPDATE browser_steps SET status=?, done_at=?, did=?, note=? WHERE id=?",
            (
                "skipped" if skip else "done",
                now.isoformat(),
                ",".join(did),
                skip or ("early" if early else None),
                step["id"],
            ),
        )
        if "follow" in did:
            self.db.execute(
                "INSERT OR IGNORE INTO follows (username, source, followed_at) VALUES (?, ?, ?)",
                (step["target"], "browser", now.isoformat()),
            )
        if step["brief_id"]:  # the brief learns what happened, so it never offers the post again
            new = "skipped" if skip else ("done" if "comment" in did else ("liked" if did else "skipped"))
            self.db.execute(
                "UPDATE brief_posts SET status=?, done_at=? WHERE id=? AND status='in-session'",
                (new, now.isoformat(), step["brief_id"]),
            )
        self.db.commit()
        if s["status"] != "started" or self._blocked():
            why = s["end_reason"] if s["status"] != "started" else self._blocked()
            return f"RECORDED S{session}.{seq} ({','.join(did) or skip}). No more steps now: {why}."
        if early:
            n = self.db.execute(
                "SELECT COUNT(*) FROM browser_steps WHERE session=? AND note='early'", (session,)
            ).fetchone()[0]
            if n >= 2:
                self._end(session, "stopped", "two steps reported done sooner than their look time")
                return (
                    f"ENDED S{session}: two steps reported done sooner than their look time. Tell the owner; "
                    "no more steps in this session."
                )
            return (
                f"NOTED S{session}.{seq}: done {int(spent)} s after it was given, under the {step['dwell_seconds']} s "
                f"look. Look at each post for the time given. Next: run.sh browser next S{session}."
            )
        return f"OK S{session}.{seq}. Next: run.sh browser next S{session}."

    def _api_comments_today(self) -> int:
        """Comments the account itself posted today through the API or the app: live replies and first comments
        (the sweeps, run.sh reply), and owner replies typed in the app that a sweep has seen. They show on the
        activity page too, mostly on our own posts."""
        _, lo, hi = self._today_utc()
        api = self.db.execute(
            "SELECT COUNT(*) FROM actions WHERE mode='live' AND ok=1 AND action IN ('reply','first_comment') "
            "AND detail != 'already there' AND ts >= ? AND ts < ?",
            (lo, hi),
        ).fetchone()[0]
        typed = self.db.execute(
            "SELECT COUNT(*) FROM examples WHERE source='owner-instagram' AND kind='comment' AND ts >= ? AND ts < ?",
            (lo, hi),
        ).fetchone()[0]
        return api + typed

    def verify(self, session: int, others: int | None = None, total: int | None = None) -> str:
        """Closes the session's verify step with the Bot's count from our own Your activity -> Comments page.
        Preferred: --others, today's comments on other accounts' posts, which only browser steps, brief posts done
        by hand and `browser manual` make. Fallback: --total, compared with those plus the account's own API and
        app comments. A surplus pauses sessions (never a cooldown on a count alone) and the owner decides. Like
        `done`, it records even in quiet hours or after a lapse."""
        if (others is None) == (total is None):
            raise Refused("REFUSED: give exactly one of --others <n> or --total <n>.")
        step = self.db.execute("SELECT * FROM browser_steps WHERE session=? AND kind='verify'", (session,)).fetchone()
        if step is None or step["issued_at"] is None or step["status"] in ("done", "skipped"):
            raise Refused(f"REFUSED: S{session} has no verify step handed out. Run run.sh browser next S{session}.")
        browser = self.used_today()["comment"]
        if others is not None:
            seen, allowed, slack = others, browser, 0
        else:
            seen, allowed, slack = total, browser + self._api_comments_today(), 2  # a reply typed after the last sweep
        self.db.execute(
            "UPDATE browser_steps SET status='done', done_at=?, did='', note=? WHERE id=?",
            (self.now().isoformat(), f"seen {seen}, allowed {allowed}", step["id"]),
        )
        self._end(session, "ended", "all steps done")  # verify is always the last step
        self.ledger.log(self.now(), "live", "browser_verify", detail=f"S{session} seen={seen} allowed={allowed}")
        if seen > allowed + slack:
            why = (
                f"activity page shows {seen} comments today ({'others' if others is not None else 'total'}), "
                f"the ledger allows {allowed}"
            )
            self.ledger.kv_set("browser.paused", why)
            return (
                f"MISMATCH S{session}: {why}. Browser sessions are paused. Tell the owner: look at Your activity "
                "-> Comments, then say browser resume or browser stop."
            )
        if seen > allowed:
            return (
                f"VERIFIED S{session} (note): {seen} seen, {allowed} in the ledger; within {slack} for replies "
                "typed in the app since the last sweep. DONE."
            )
        return f"VERIFIED S{session}: {seen} seen, {allowed} allowed. DONE."

    # --- helpers ----------------------------------------------------------------------------------------
    def _mark(self, step_id: int, status: str, note: str | None = None) -> None:
        now = self.now().isoformat()
        if status == "issued":
            self.db.execute("UPDATE browser_steps SET status='issued', issued_at=? WHERE id=?", (now, step_id))
            return
        self.db.execute("UPDATE browser_steps SET status=?, done_at=?, note=? WHERE id=?", (status, now, note, step_id))
        if status == "skipped":  # an engine skip says nothing about the post: a person may still post it
            self.db.execute(
                "UPDATE brief_posts SET status='ready' WHERE status='in-session' AND id = "
                "(SELECT brief_id FROM browser_steps WHERE id=?)",
                (step_id,),
            )

    def _still_fresh(self, step) -> bool:
        if not step["brief_id"]:
            return True
        row = self.db.execute("SELECT posted_at FROM brief_posts WHERE id=?", (step["brief_id"],)).fetchone()
        return bool(row) and self._fresh_at(row["posted_at"])

    def _describe(self, step, with_like: bool = False) -> str:
        """The only place a target's link and a comment's text are printed during a session."""
        sid = f"S{step['session']}.{step['seq']}"
        kind = step["kind"]
        if kind == "check":
            return (
                f"STEP {sid} · check · open https://www.instagram.com/{self.cfg.username}/ and confirm the Grok "
                f"browser is logged in as @{self.cfg.username} with no warning on screen. Then: run.sh browser "
                f'done S{step["session"]} {step["seq"]} --ok (or browser stop "<what you saw>").'
            )
        if kind == "verify":
            return (
                f"STEP {sid} · verify · open Your activity -> Comments on @{self.cfg.username} and count today's "
                "comments on OTHER accounts' posts. Then: run.sh browser verify "
                f'S{step["session"]} --others <n> (or --skip "<why>" if the page won\'t load).'
            )
        target = step["target"]
        if kind == "like_reply":
            where = f"open our post with the comment {target.split(':', 1)[1]} and like that comment"
        elif kind == "follow":
            where = f"open https://www.instagram.com/{target}/ and follow"
        elif kind == "comment":
            where = f"open {target}" + (
                ", like it, and comment" if with_like else " and comment (no like: today's likes are used up)"
            )
        else:
            where = f"open {target} and like it"
        text = f' · comment, exactly: "{step["text"]}"' if kind == "comment" else ""
        did = {
            "comment": "comment,like" if with_like else "comment",
            "like": "like",
            "like_reply": "like",
            "follow": "follow",
        }[kind]
        return (
            f"STEP {sid} · {kind.replace('_', ' ')} · {where} · look {step['dwell_seconds']} s first{text}\n"
            f"Then: run.sh browser done S{step['session']} {step['seq']} --did {did} "
            '(only what you really did), or --skip "<why>". If Instagram shows any warning, '
            '"Try again later" or a login check: run.sh browser stop "<what it said>".'
        )

    def manual(self, comments: int = 0, likes: int = 0, follows: int = 0, following: int | None = None) -> str:
        """Things a person did by hand in the app today, so the caps count them."""
        day, _, _ = self._today_utc()
        for action, n in (("comment", comments), ("like", likes), ("follow", follows)):
            if n:
                key = f"browser.manual.{day}.{action}"
                self.ledger.kv_set(key, str(int(self.ledger.kv_get(key) or 0) + n))
        if following is not None:
            self.ledger.kv_set("browser.following_before", str(following))
        used = self.used_today()
        return f"COUNTED: today {used['comment']} comments, {used['like']} likes, {used['follow']} follows."

    def status(self, session: int | None = None) -> list[str]:
        self._lapse()
        c = caps(self.cfg, self.now().astimezone(self.cfg.tz))
        used = self.used_today()
        blocked = self._blocked(quiet=False)
        days = (
            self.now().astimezone(self.cfg.tz).date() - datetime.fromisoformat(self.cfg.browser_ramp_start).date()
        ).days
        lines = [
            f"BROWSER · {'on' if self.cfg.browser_enabled else 'off'} · ramp day {days}"
            + (f" · {blocked}" if blocked else ""),
            "today: " + " · ".join(f"{used[a]}/{c['day'][a]} {a}s" for a in ACTIONS),
        ]
        rows = self.db.execute(
            "SELECT * FROM browser_sessions " + ("WHERE session=?" if session else "ORDER BY session DESC LIMIT 3"),
            (session,) if session else (),
        ).fetchall()
        for s in rows:
            steps = self.db.execute(
                "SELECT kind, status, did, note FROM browser_steps WHERE session=? ORDER BY seq", (s["session"],)
            ).fetchall()
            done = sum(1 for st in steps if st["status"] == "done")
            kinds: dict[str, int] = {}
            for st in steps:
                kinds[st["kind"]] = kinds.get(st["kind"], 0) + 1
            lines.append(
                f"S{s['session']} {s['status']} · {done}/{len(steps)} steps done · "
                + ", ".join(f"{n} {k}" for k, n in kinds.items())
                + (f" · {s['end_reason']}" if s["end_reason"] else "")
            )
        if not rows:
            lines.append("no sessions yet")
        return lines

    def plan_lines(self, session: int) -> list[str]:
        """The printed plan: kinds and timing, never links or comment text."""
        steps = self.db.execute(
            "SELECT kind, gap_seconds FROM browser_steps WHERE session=? ORDER BY seq", (session,)
        ).fetchall()
        kinds: dict[str, int] = {}
        for st in steps:
            kinds[st["kind"]] = kinds.get(st["kind"], 0) + 1
        minutes = sum(st["gap_seconds"] for st in steps) // 60 + 1
        return [
            f"PLAN S{session} · {len(steps)} steps ("
            + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in kinds.items())
            + f") · about {minutes} min with breaks",
            f'Ask the owner to say "engage S{session}" (run.sh browser start S{session} --owner-tapped). '
            f"It can be started for {self.cfg.browser_plan_valid_minutes} minutes.",
        ]

    def stop(self, reason: str) -> str:
        until = self.now() + timedelta(hours=self.cfg.browser_cooldown_hours)
        self.ledger.kv_set("browser.cooldown_until", until.isoformat())
        self.ledger.kv_set("browser.stop_reason", reason[:200])
        for (s,) in self.db.execute(
            "SELECT session FROM browser_sessions WHERE status IN ('planned','started')"
        ).fetchall():
            self._end(s, "stopped", f"stop: {reason}")
        return (
            f"STOPPED: no browser sessions until {until.astimezone(self.cfg.tz):%a %d %b %H:%M}. If you had already "
            f"liked or commented on the current step, still report it with browser done. Tell the owner: {reason}"
        )
