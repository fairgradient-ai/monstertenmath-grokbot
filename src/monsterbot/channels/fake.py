"""Fakes of Instagram, Facebook's Graph (scouting) and email, for tests and `doctor --full`.

Fixture: {"account": {...}, "media": [{"id", "caption", "timestamp", "comments": [{"id", "text", "username",
"timestamp", "replies": [...]}]}], "conversations": [{"id", "messages": [{"id", "from": {"id", "username"},
"text", "timestamp"}]}], "creators": {username: {...}}, "hashtags": {tag: [{"caption", ...}]}}.
With a `state` path, what the bot posts is saved there, so separate CLI runs see each other's replies.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from ..errors import ChannelError
from ..models import Account, Comment, DirectMessage, Media, Profile
from .instagram import parse_time


class FakeInstagram:
    name = "instagram"

    def __init__(self, fixture: dict, state: Path | None = None):
        self.fixture = fixture
        self.state = state
        self.posted: list[dict] = []
        self.hidden: list[str] = []
        self.fail_next: ChannelError | None = None
        if state and state.exists():
            saved = json.loads(state.read_text())
            self.posted, self.hidden = saved["posted"], saved["hidden"]
        self._ids = itertools.count(len(self.posted) + 1)

    @classmethod
    def from_file(cls, path: Path, state: Path | None = None) -> FakeInstagram:
        return cls(json.loads(Path(path).read_text()), state)

    def _save(self) -> None:
        if self.state:
            self.state.write_text(json.dumps({"posted": self.posted, "hidden": self.hidden}, indent=1))

    def _maybe_fail(self) -> None:
        if self.fail_next:
            err, self.fail_next = self.fail_next, None
            raise err

    def me(self) -> Account:
        self._maybe_fail()
        a = self.fixture["account"]
        return Account(
            id=a["id"],
            username=a["username"],
            account_type=a.get("account_type", "BUSINESS"),
            followers_count=a.get("followers_count"),
            media_count=len(self.fixture["media"]),
        )

    def profile_extras(self) -> dict:
        return {k: v for k, v in self.fixture["account"].items() if k in ("biography", "website")}

    def recent_media(self, limit: int) -> list[Media]:
        self._maybe_fail()
        return [
            Media(
                id=m["id"],
                caption=m["caption"],
                timestamp=parse_time(m["timestamp"]),
                comments_count=len(m.get("comments", [])),
                like_count=m.get("like_count"),
            )
            for m in self.fixture["media"][:limit]
        ]

    def comments(self, media_id: str) -> list[Comment]:
        self._maybe_fail()
        media = next(m for m in self.fixture["media"] if m["id"] == media_id)
        me = self.fixture["account"]["username"]
        out: list[Comment] = []
        for c in media.get("comments", []):
            out.append(Comment(c["id"], media_id, c["text"], c["username"], parse_time(c["timestamp"])))
            for r in c.get("replies", []):
                out.append(
                    Comment(r["id"], media_id, r["text"], r["username"], parse_time(r["timestamp"]), parent_id=c["id"])
                )
            for p in self.posted:
                if p["kind"] == "reply" and p["parent"] == c["id"]:
                    out.append(
                        Comment(p["id"], media_id, p["text"], me, parse_time(media["timestamp"]), parent_id=c["id"])
                    )
        for p in self.posted:
            if p["kind"] == "comment" and p["parent"] == media_id:
                out.append(Comment(p["id"], media_id, p["text"], me, parse_time(media["timestamp"])))
        return out

    def conversations(self, our_id: str, handle: str, limit: int = 20) -> list[DirectMessage]:
        self._maybe_fail()
        out: list[DirectMessage] = []
        for conv in self.fixture.get("conversations", [])[:limit]:
            last = None
            for m in conv["messages"]:
                frm = m["from"]
                last = parse_time(m["timestamp"])
                out.append(
                    DirectMessage(
                        id=m["id"],
                        thread_id=conv["id"],
                        sender_id=frm["id"],
                        sender_username=frm["username"],
                        text=m.get("text", ""),
                        timestamp=last,
                        from_us=frm["id"] == our_id or frm["username"].lower() == handle.lower(),
                    )
                )
            for p in self.posted:
                if p["kind"] == "dm" and p["thread"] == conv["id"]:
                    out.append(
                        DirectMessage(p["id"], conv["id"], our_id, handle, p["text"], last, from_us=True)  # type: ignore[arg-type]
                    )
        return out

    def reply(self, comment_id: str, text: str) -> str:
        self._maybe_fail()
        new_id = f"fake-reply-{next(self._ids)}"
        self.posted.append({"kind": "reply", "id": new_id, "parent": comment_id, "text": text})
        self._save()
        return new_id

    def send_dm(self, recipient_id: str, text: str) -> str:
        self._maybe_fail()
        thread = next(
            (
                c["id"]
                for c in self.fixture.get("conversations", [])
                if any(m["from"]["id"] == recipient_id for m in c["messages"])
            ),
            None,
        )
        if thread is None:
            raise ChannelError("no conversation with that person", "bad_request")
        new_id = f"fake-dm-{next(self._ids)}"
        self.posted.append({"kind": "dm", "id": new_id, "thread": thread, "to": recipient_id, "text": text})
        self._save()
        return new_id

    def comment_on_media(self, media_id: str, text: str) -> str:
        self._maybe_fail()
        new_id = f"fake-comment-{next(self._ids)}"
        self.posted.append({"kind": "comment", "id": new_id, "parent": media_id, "text": text})
        self._save()
        return new_id

    def hide(self, comment_id: str, hide: bool = True) -> None:
        self._maybe_fail()
        self.hidden.append(comment_id)
        self._save()


class FakeGraph:
    """Business Discovery and hashtag search, from the fixture's "creators" and "hashtags"."""

    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.lookups: list[str] = []
        self.hashtag_calls: list[str] = []

    def business_discovery(self, username: str) -> Profile | None:
        self.lookups.append(username)
        raw = self.fixture.get("creators", {}).get(username.lower())
        if raw is None:
            return None  # a personal account, or no such account
        return Profile(
            username=username.lower(),
            name=raw.get("name", ""),
            biography=raw.get("biography", ""),
            website=raw.get("website", ""),
            followers=raw.get("followers_count", 0),
            media_count=raw.get("media_count", 0),
            posts=tuple(raw.get("media", [])),
        )

    def hashtag_top_media(self, tag: str) -> list[dict]:
        self.hashtag_calls.append(tag)
        return list(self.fixture.get("hashtags", {}).get(tag, []))


class FakeEmail:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, to: str, subject: str, body: str) -> str:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return f"fake-email-{len(self.sent)}"
