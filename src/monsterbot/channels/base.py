"""What the engine needs from a platform. A second channel (Facebook Page, Threads, YouTube) implements this."""

from __future__ import annotations

from typing import Protocol

from ..models import Account, Comment, Media


class Channel(Protocol):
    name: str

    def me(self) -> Account: ...

    def recent_media(self, limit: int) -> list[Media]: ...

    def comments(self, media_id: str) -> list[Comment]:
        """Top-level comments and their replies, flattened (a reply carries parent_id)."""
        ...

    def reply(self, comment_id: str, text: str) -> str:
        """Reply under a top-level comment. Returns the new comment's id."""
        ...

    def comment_on_media(self, media_id: str, text: str) -> str: ...

    def hide(self, comment_id: str, hide: bool = True) -> None: ...
