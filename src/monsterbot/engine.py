"""The engine: sweep, draft, send, discard, hide.

The Grok Bot never talks to Instagram itself. It runs these commands through scripts/run.sh and posts what
they print. The engine decides what may be posted (knowledge/ and the policy check), keeps the ledger, and
posts nothing in rehearsal mode.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from . import policy
from .config import Config
from .desk import Desk
from .errors import ChannelError, Refused
from .knowledge import Knowledge, Piece, _norm
from .ledger import Item, Ledger, day_ago
from .models import Comment, Media
from .triage import triage

STATUS_FOR_TIER = {"skip": "skipped", "owner": "queued", "draft": "queued", "auto": "new"}
REPLAN = ("new", "rehearsed", "retry")


def short(text: str | None, n: int = 80) -> str:
    t = _norm(text or "")
    return t if len(t) <= n else t[: n - 1] + "…"


@dataclass
class SweepResult:
    posts: int = 0
    fresh: list[int] = field(default_factory=list)
    replied: list[tuple[int, str]] = field(default_factory=list)
    would_reply: list[tuple[int, str]] = field(default_factory=list)
    first_comments: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    held: int = 0
    stopped: str | None = None


class Engine:
    def __init__(
        self,
        cfg: Config,
        desk: Desk,
        kn: Knowledge,
        channel,
        ledger: Ledger,
        now: Callable[[], datetime] | None = None,
    ):
        self.cfg = cfg
        self.desk = desk
        self.kn = kn
        self.channel = channel
        self.ledger = ledger
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        # Always UTC, so the ledger's ISO timestamps compare correctly as text.
        return self._now().astimezone(UTC)

    def local(self, dt: datetime) -> str:
        return dt.astimezone(self.cfg.tz).strftime("%a %d %b %H:%M %Z")

    def ctx(self, item: Item | None = None, category: str = "draft") -> policy.Context:
        return policy.Context(
            phase=self.desk.phase(),
            category=category,
            author=item.author if item else None,
            stores=self.cfg.stores,
        )

    def label(self, item: Item) -> str:
        piece = self.kn.piece(item.piece)
        return piece.label if piece else "a post"

    # =============================================================================================
    # sweep
    # =============================================================================================
    def sweep(self) -> SweepResult:
        now, mode, phase = self.now(), self.desk.mode(), self.desk.phase()
        res = SweepResult()
        me = self.channel.me()
        handle = me.username or self.cfg.username
        if self.cfg.username and handle.lower() != self.cfg.username.lower():
            raise Refused(f"FAILED: the token is for @{handle}, but config.toml says @{self.cfg.username}.")

        media = self.channel.recent_media(self.cfg.media_lookback)
        res.posts = len(media)
        seen_media: set[str] = set()
        for m in media:
            seen_media.add(m.id)
            piece = self.kn.match_piece(m.caption)
            comments = self.channel.comments(m.id)
            ours = [c for c in comments if c.username.lower() == handle.lower()]
            self._verify_unverified(m, ours, now)
            if piece and piece.first_comment and self.cfg.first_comments and res.stopped is None:
                self._first_comment(m, piece, ours, now, mode, phase, res)
            self._record_comments(m, piece, comments, handle, now, phase, res)

        self._act_on_auto(seen_media, now, mode, res)
        self.ledger.kv_set("last_sweep", now.isoformat())
        self.ledger.kv_set("last_sweep_result", res.stopped or "ok")
        return res

    def _record_comments(
        self,
        m: Media,
        piece: Piece | None,
        comments: list[Comment],
        handle: str,
        now: datetime,
        phase: str,
        res: SweepResult,
    ) -> None:
        by_id = {c.id: c for c in comments}
        # Thank-you lines take turns on each post, so the same line never comes twice in a row.
        rotation = self.ledger.count_category_replies(m.id, "praise") + self.ledger.count_category_replies(
            m.id, "played"
        )
        for c in comments:
            existing = self.ledger.by_external(self.channel.name, c.id)
            if existing is not None and existing.status not in REPLAN:
                continue
            parent = by_id.get(c.parent_id) if c.parent_id else None
            v = triage(
                c,
                piece=piece,
                handle=handle,
                parent=parent,
                kn=self.kn,
                phase=phase,
                stores=self.cfg.stores,
                thanks=self.cfg.thanks,
                line_index=rotation,
            )
            item_id = self.ledger.upsert_seen(
                self.channel.name,
                c.id,
                now,
                media_id=m.id,
                piece=piece.key if piece else None,
                parent_external_id=c.parent_id,
                parent_author=parent.username if parent else None,
                author=c.username,
                text=c.text,
                created_at=c.timestamp,
                category=v.category,
                tier=v.tier,
                reason=v.reason,
                suggested=v.reply,
                notify=v.notify,
                status=STATUS_FOR_TIER[v.tier] if (existing is None or v.tier != "auto") else existing.status,
            )
            if v.category in ("praise", "played"):
                rotation += 1
            if existing is None:
                res.fresh.append(item_id)

    def _act_on_auto(self, media_ids: set[str], now: datetime, mode: str, res: SweepResult) -> None:
        """Post the canned replies. Rehearsal plans exactly what live would do and posts nothing."""
        max_age = timedelta(hours=self.cfg.auto_reply_max_age_hours)
        sent_today = self.ledger.auto_replies_since(day_ago(now))
        planned: set[tuple[str, str]] = set()
        done_this_sweep = 0
        fresh = set(res.fresh)
        for item in self.ledger.items(statuses=REPLAN):
            if item.tier != "auto" or item.media_id not in media_ids or not item.suggested:
                continue
            if res.stopped:
                break
            if now - item.created_at > max_age:
                self.ledger.update(
                    item.id,
                    status="drafted",
                    tier="draft",
                    draft_text=item.suggested,
                    draft_violations=[str(v) for v in self._lint(item, item.suggested)],
                    reason=f"older than {self.cfg.auto_reply_max_age_hours} h: check the "
                    "canned reply still fits, then send it",
                )
                continue
            key = (item.author.lower(), item.media_id or "")
            if key in planned or self.ledger.auto_replies_since(
                day_ago(now), media_id=item.media_id, author=item.author
            ):
                self.ledger.update(
                    item.id,
                    status="queued",
                    tier="draft",
                    reason=f"@{item.author}'s second comment on this post today",
                )
                continue
            if (
                done_this_sweep >= self.cfg.max_auto_replies_per_sweep
                or sent_today + done_this_sweep >= self.cfg.max_auto_replies_per_day
            ):
                res.held += 1
                continue
            violations = self._lint(item, item.suggested)
            if violations:
                # A canned reply that fails the check means knowledge/ and rules.toml disagree: hand it over.
                self.ledger.update(
                    item.id,
                    status="queued",
                    tier="draft",
                    reason="the canned reply failed the check: " + str(violations[0]),
                )
                res.problems.append(f"[{item.id}] canned reply failed the check: {violations[0]}")
                continue
            planned.add(key)
            if mode == "rehearsal":
                self.ledger.update(item.id, status="rehearsed")
                if item.id in fresh:
                    done_this_sweep += 1
                    res.would_reply.append((item.id, item.suggested))
                continue
            if self._post_reply(item, item.suggested, res):
                done_this_sweep += 1
                res.replied.append((item.id, item.suggested))
                if item.notify:
                    res.notes.append(f"[{item.id}] {item.notify}")

    def _first_comment(
        self,
        m: Media,
        piece: Piece,
        ours: list[Comment],
        now: datetime,
        mode: str,
        phase: str,
        res: SweepResult,
    ) -> None:
        if any(c.parent_id is None for c in ours):
            if not self.ledger.has_action("first_comment", m.id):
                self.ledger.log(now, "live", "first_comment", media_id=m.id, detail="already there")
            return
        if self.ledger.has_action("first_comment", m.id, "live"):
            return  # posted once and since deleted: the owner's call, never repost
        if now - m.timestamp > timedelta(hours=self.cfg.first_comment_max_age_hours):
            return
        violations = policy.check(piece.first_comment or "", policy.Context(phase, "first_comment"), self.kn.rules)
        if violations:
            res.problems.append(f"{piece.label}: the first comment fails the check: {violations[0]}")
            return
        if mode == "rehearsal":
            if not self.ledger.has_action("first_comment", m.id, "rehearsal"):
                self.ledger.log(now, "rehearsal", "first_comment", media_id=m.id, detail=piece.first_comment or "")
                res.first_comments.append(f'Would post the first comment on {piece.label}: "{piece.first_comment}"')
            return
        try:
            self.channel.comment_on_media(m.id, piece.first_comment)
        except ChannelError as e:
            self.ledger.log(now, "live", "first_comment", media_id=m.id, detail=str(e), ok=False)
            res.problems.append(f"{piece.label}: first comment not posted: {e}")
            if e.kind in ("rate", "network", "token"):
                res.stopped = e.kind
            return
        self.ledger.log(now, "live", "first_comment", media_id=m.id, detail=piece.first_comment or "")
        res.first_comments.append(
            f'Posted the first comment on {piece.label}: "{piece.first_comment}" '
            "Pin it in the app: press and hold the comment, then Pin."
        )

    def _verify_unverified(self, m: Media, ours: list[Comment], now: datetime) -> None:
        for item in self.ledger.items(statuses=("unverified",), media_id=m.id):
            target = item.parent_external_id or item.external_id
            start = _norm(item.reply_text or "")[:30].lower()
            found = next((c for c in ours if c.parent_id == target and _norm(c.text).lower().startswith(start)), None)
            if found:
                self.ledger.update(item.id, status="replied", reply_external_id=found.id, replied_at=now, error=None)
                self.ledger.log(now, "live", "verified", item_id=item.id, media_id=m.id, detail=found.id)
            elif item.attempted_at and now - item.attempted_at > timedelta(minutes=5):
                self.ledger.update(
                    item.id,
                    status="retry" if item.tier == "auto" else "drafted",
                    error="the reply never showed up on Instagram",
                )

    def _lint(self, item: Item, text: str) -> list[policy.Violation]:
        return policy.check(text, self.ctx(item, item.category if item.tier == "auto" else "draft"), self.kn.rules)

    def _post_reply(self, item: Item, text: str, res: SweepResult | None = None) -> bool:
        """Post a reply, at most once. Instagram replies attach to the top-level comment, so a reply to a
        reply goes under its parent with an @mention."""
        now = self.now()
        target = item.parent_external_id or item.external_id
        body = text
        if item.parent_external_id and not body.lower().startswith(f"@{item.author.lower()}"):
            body = f"@{item.author} {body}"
        with self.ledger.tx():
            current = self.ledger.get(item.id)
            if current is None or current.status in ("replied", "sending", "unverified"):
                return False
            self.ledger.update(item.id, status="sending", reply_text=body, attempted_at=now)
        try:
            new_id = self.channel.reply(target, body)
        except ChannelError as e:
            if e.ambiguous:
                self.ledger.update(item.id, status="unverified", error=str(e))
                msg = f"[{item.id}] UNVERIFIED: {e}. The next sweep checks whether it went out before retrying."
            else:
                back = "new" if item.tier == "auto" else "drafted"
                self.ledger.update(item.id, status=back, error=str(e))
                msg = f"[{item.id}] not sent: {e}"
            self.ledger.log(now, "live", "reply", item_id=item.id, media_id=item.media_id, detail=str(e), ok=False)
            if res is not None:
                res.problems.append(msg)
                if e.kind in ("rate", "network", "token"):
                    res.stopped = e.kind
                return False
            raise
        self.ledger.update(item.id, status="replied", reply_external_id=new_id, replied_at=now, error=None)
        self.ledger.log(now, "live", "reply", item_id=item.id, media_id=item.media_id, detail=new_id)
        return True

    # =============================================================================================
    # owner-side commands
    # =============================================================================================
    def _item(self, item_id: int) -> Item:
        item = self.ledger.get(item_id)
        if item is None:
            raise Refused(f'REFUSED: there\'s no item [{item_id}]. Say "inbox" to see the open ones.')
        return item

    def draft(self, item_id: int, text: str) -> tuple[Item, list[policy.Violation]]:
        item = self._item(item_id)
        if item.status in ("replied", "sending", "unverified", "hidden"):
            raise Refused(f"REFUSED: [{item_id}] is already {item.status}.")
        text = text.strip()
        violations = policy.check(text, self.ctx(item), self.kn.rules)
        self.ledger.update(
            item.id,
            status="drafted",
            tier="draft",
            draft_text=text,
            draft_violations=[str(v) for v in violations],
        )
        self.ledger.log(
            self.now(),
            self.desk.mode(),
            "draft",
            item_id=item.id,
            media_id=item.media_id,
            detail=text,
            ok=not violations,
        )
        return self._item(item_id), violations

    def drafted_ids(self) -> list[int]:
        return [
            i.id
            for i in self.ledger.items(statuses=("drafted",))
            if i.draft_text and not policy.check(i.draft_text, self.ctx(i), self.kn.rules)
        ]

    def send(self, ids: list[int], *, owner_tapped: bool, force_lint: bool = False) -> list[str]:
        if not owner_tapped:
            raise Refused('REFUSED: sending needs your tap. Approve the card for "run.sh send ... --owner-tapped".')
        out = []
        mode = self.desk.mode()
        for item_id in ids:
            item = self._item(item_id)
            if item.status != "drafted" or not item.draft_text:
                out.append(f"NOT SENT [{item_id}]: no draft to send (it's {item.status}).")
                continue
            violations = policy.check(item.draft_text, self.ctx(item), self.kn.rules)
            if violations and not force_lint:
                out.append(f"NOT SENT [{item_id}]: the draft fails the check: " + "; ".join(str(v) for v in violations))
                continue
            if mode == "rehearsal":
                out.append(f'REHEARSAL [{item_id}]: would send to @{item.author}: "{short(item.draft_text, 200)}"')
                continue
            try:
                ok = self._post_reply(item, item.draft_text)
            except ChannelError as e:
                if e.ambiguous:
                    out.append(f"UNVERIFIED [{item_id}]: {e}. The next sweep checks whether it went out.")
                else:
                    out.append(f"NOT SENT [{item_id}]: {e}")
                if e.kind in ("rate", "token", "network"):
                    out.append("Stopped: nothing else was sent.")
                    break
                continue
            out.append(
                f'SENT [{item_id}] to @{item.author} on {self.label(item)}: "{short(item.draft_text, 200)}"'
                if ok
                else f"NOT SENT [{item_id}]: it was already answered."
            )
        return out

    def discard(self, ids: list[int]) -> list[str]:
        out = []
        for item_id in ids:
            item = self._item(item_id)
            if item.status in ("replied", "sending", "unverified"):
                out.append(f"[{item_id}] is already {item.status}: left as it is.")
                continue
            self.ledger.update(item.id, status="discarded")
            self.ledger.log(self.now(), self.desk.mode(), "discard", item_id=item.id, media_id=item.media_id)
            out.append(f"DISCARDED [{item_id}] @{item.author}: no reply.")
        return out

    def hide(self, ids: list[int], *, owner_tapped: bool) -> list[str]:
        if not owner_tapped:
            raise Refused("REFUSED: hiding a comment needs your tap (--owner-tapped).")
        out = []
        mode = self.desk.mode()
        for item_id in ids:
            item = self._item(item_id)
            if mode == "rehearsal":
                out.append(f'REHEARSAL [{item_id}]: would hide @{item.author}: "{short(item.text)}"')
                continue
            try:
                self.channel.hide(item.external_id, True)
            except ChannelError as e:
                out.append(f"NOT HIDDEN [{item_id}]: {e}")
                continue
            self.ledger.update(item.id, status="hidden")
            self.ledger.log(self.now(), "live", "hide", item_id=item.id, media_id=item.media_id)
            out.append(f"HIDDEN [{item_id}] @{item.author}. Delete it or block the account in the app if needed.")
        return out
