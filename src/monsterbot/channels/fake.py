"""A fake Instagram for tests and `doctor --full`: reads a JSON fixture and keeps what the bot posts.

Fixture: {"account": {...}, "media": [{"id", "caption", "timestamp", "comments": [{"id", "text",
"username", "timestamp", "replies": [...]}]}]}. With a `state` path, what the bot posts is saved there, so
separate CLI runs see each other's replies.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from ..errors import ChannelError
from ..models import Account, Comment, Media
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
                    Comment(
                        r["id"],
                        media_id,
                        r["text"],
                        r["username"],
                        parse_time(r["timestamp"]),
                        parent_id=c["id"],
                    )
                )
            for p in self.posted:
                if p["kind"] == "reply" and p["parent"] == c["id"]:
                    out.append(
                        Comment(
                            p["id"],
                            media_id,
                            p["text"],
                            me,
                            parse_time(media["timestamp"]),
                            parent_id=c["id"],
                        )
                    )
        for p in self.posted:
            if p["kind"] == "comment" and p["parent"] == media_id:
                out.append(Comment(p["id"], media_id, p["text"], me, parse_time(media["timestamp"])))
        return out

    def reply(self, comment_id: str, text: str) -> str:
        self._maybe_fail()
        new_id = f"fake-reply-{next(self._ids)}"
        self.posted.append({"kind": "reply", "id": new_id, "parent": comment_id, "text": text})
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
