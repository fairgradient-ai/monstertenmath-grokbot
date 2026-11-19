"""Plain records shared by the channels and the engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Account:
    id: str
    username: str
    account_type: str = ""
    followers_count: int | None = None
    media_count: int | None = None


@dataclass(frozen=True)
class Media:
    id: str
    caption: str
    timestamp: datetime
    permalink: str = ""
    media_type: str = ""
    comments_count: int = 0
    like_count: int | None = None


@dataclass(frozen=True)
class Comment:
    """A comment on one of our posts. Instagram threads are one level deep: a reply's parent_id is
    always a top-level comment."""

    id: str
    media_id: str
    text: str
    username: str
    timestamp: datetime
    parent_id: str | None = None


@dataclass(frozen=True)
class DirectMessage:
    """One message in an Instagram DM thread. from_us marks the ones our account sent."""

    id: str
    thread_id: str
    sender_id: str
    sender_username: str
    text: str
    timestamp: datetime
    from_us: bool = False


@dataclass(frozen=True)
class Profile:
    """A creator's public business or creator profile (Business Discovery)."""

    username: str
    name: str = ""
    biography: str = ""
    website: str = ""
    followers: int = 0
    media_count: int = 0
    posts: tuple[dict, ...] = ()  # recent posts: caption, like_count, comments_count, timestamp, permalink
