"""Instagram, through Meta's official Instagram API with Instagram Login (graph.instagram.com).

Only what the API allows on our own account: read our posts and their comments, reply under a comment, comment
on our own post, hide a comment, refresh the token. It can't follow, like, or comment on anyone else's posts,
and this module doesn't try.

Permissions (Instagram Login): instagram_business_basic, instagram_business_manage_comments. With your own
account added to your own Meta app, Standard Access covers this without App Review (SETUP.md, section 2).
The token travels in the Authorization header, never in a logged URL.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime

from ..errors import ChannelError
from ..models import Account, Comment, DirectMessage, Media

COMMENT_FIELDS = "id,text,timestamp,username,parent_id"
MEDIA_FIELDS = "id,caption,timestamp,permalink,media_type,comments_count,like_count"
RATE_CODES = {4, 17, 32, 613}
PERMISSION_CODES = {3, 10, 200}
MAX_PAGES = 10


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")


def _error_from(status: int, body: str, ambiguous: bool) -> ChannelError:
    try:
        err = json.loads(body).get("error", {})
    except (json.JSONDecodeError, AttributeError):
        err = {}
    code = err.get("code")
    message = err.get("message") or f"HTTP {status}"
    if code == 190 or status == 401:
        return ChannelError(f"the Instagram token is expired or revoked ({message})", "token", code=code)
    if code in RATE_CODES or status == 429:
        return ChannelError(f"Instagram's rate limit ({message})", "rate", code=code)
    if code in PERMISSION_CODES or status == 403:
        return ChannelError(f"missing permission ({message})", "permission", code=code)
    if status >= 500:
        return ChannelError(f"Instagram error {status} ({message})", "network", ambiguous=ambiguous, code=code)
    return ChannelError(message, "bad_request", code=code)


class InstagramChannel:
    name = "instagram"

    def __init__(
        self,
        token: str,
        *,
        host: str = "https://graph.instagram.com",
        version: str = "v24.0",
        timeout: int = 30,
        opener: Callable[..., object] | None = None,
    ):
        if not token:
            raise ChannelError("no Instagram token: add IG_ACCESS_TOKEN on the secret card", "token")
        self._token = token
        self._base = f"{host.rstrip('/')}/{version}"
        self._host = host.rstrip("/")
        self._timeout = timeout
        self._open = opener or urllib.request.urlopen

    # --- HTTP ------------------------------------------------------------------------------------------
    def _call(
        self, method: str, url: str, params: dict | None = None, *, auth: bool = True, json_body: dict | None = None
    ) -> dict:
        data = None
        if method == "GET" and params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        elif params:
            data = urllib.parse.urlencode(params).encode()
        if json_body is not None:
            data = json.dumps(json_body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        if json_body is not None:
            req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self._token}")
        ambiguous = method != "GET"
        try:
            with self._open(req, timeout=self._timeout) as resp:  # type: ignore[attr-defined]
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace") if e.fp else ""
            raise _error_from(e.code, body, ambiguous) from None
        except TimeoutError as e:
            raise ChannelError(f"Instagram didn't answer in {self._timeout} s", "network", ambiguous=ambiguous) from e
        except urllib.error.URLError as e:
            # The request never left (DNS, refused connection), so it can't have been posted.
            raise ChannelError(f"can't reach Instagram ({e.reason})", "network") from e

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._call("GET", f"{self._base}/{path}", params)

    def _paged(self, path: str, params: dict) -> list[dict]:
        out: list[dict] = []
        page = self._get(path, params)
        for _ in range(MAX_PAGES):
            out.extend(page.get("data", []))
            nxt = (page.get("paging") or {}).get("next")
            if not nxt:
                break
            page = self._call("GET", nxt)
        return out

    # --- reads -----------------------------------------------------------------------------------------
    def me(self) -> Account:
        d = self._get("me", {"fields": "user_id,username,account_type,followers_count,media_count"})
        return Account(
            id=str(d.get("user_id") or d.get("id")),
            username=d.get("username", ""),
            account_type=d.get("account_type", ""),
            followers_count=d.get("followers_count"),
            media_count=d.get("media_count"),
        )

    def profile_extras(self) -> dict:
        """The bio and the bio link, if this API version returns them ({} if not)."""
        try:
            return self._get("me", {"fields": "biography,website"})
        except ChannelError as e:
            if e.kind == "bad_request":
                return {}
            raise

    def recent_media(self, limit: int) -> list[Media]:
        d = self._get("me/media", {"fields": MEDIA_FIELDS, "limit": max(1, min(limit, 50))})
        return [
            Media(
                id=m["id"],
                caption=m.get("caption", ""),
                timestamp=parse_time(m["timestamp"]),
                permalink=m.get("permalink", ""),
                media_type=m.get("media_type", ""),
                comments_count=int(m.get("comments_count") or 0),
                like_count=m.get("like_count"),
            )
            for m in d.get("data", [])[:limit]
        ]

    def comments(self, media_id: str) -> list[Comment]:
        fields = f"{COMMENT_FIELDS},replies{{{COMMENT_FIELDS}}}"
        out: list[Comment] = []
        for c in self._paged(f"{media_id}/comments", {"fields": fields, "limit": 50}):
            out.append(self._comment(c, media_id, None))
            for r in (c.get("replies") or {}).get("data", []):
                out.append(self._comment(r, media_id, c["id"]))
        return out

    @staticmethod
    def _comment(c: dict, media_id: str, parent: str | None) -> Comment:
        return Comment(
            id=c["id"],
            media_id=media_id,
            text=c.get("text", ""),
            username=c.get("username") or (c.get("from") or {}).get("username", ""),
            timestamp=parse_time(c["timestamp"]),
            parent_id=c.get("parent_id") or parent,
        )

    def conversations(self, our_id: str, handle: str, limit: int = 20) -> list[DirectMessage]:
        """The newest DM threads and their latest messages. Needs instagram_business_manage_messages with
        Advanced Access (App Review) to see people who have no role on our app."""
        fields = "id,updated_time,messages.limit(10){id,created_time,from,to,message}"
        d = self._get("me/conversations", {"platform": "instagram", "fields": fields, "limit": limit})
        out: list[DirectMessage] = []
        for conv in d.get("data", []):
            for m in (conv.get("messages") or {}).get("data", []):
                frm = m.get("from") or {}
                sender_id, sender = str(frm.get("id", "")), frm.get("username", "")
                out.append(
                    DirectMessage(
                        id=m["id"],
                        thread_id=conv["id"],
                        sender_id=sender_id,
                        sender_username=sender,
                        text=m.get("message") or "",
                        timestamp=parse_time(m["created_time"]),
                        from_us=sender_id == our_id or sender.lower() == handle.lower(),
                    )
                )
        return out

    # --- writes ----------------------------------------------------------------------------------------
    def send_dm(self, recipient_id: str, text: str) -> str:
        """A reply inside Meta's 24-hour window after the person's last message."""
        d = self._call(
            "POST",
            f"{self._base}/me/messages",
            json_body={"recipient": {"id": recipient_id}, "message": {"text": text}},
        )
        return str(d.get("message_id") or d.get("id"))

    def reply(self, comment_id: str, text: str) -> str:
        return str(self._call("POST", f"{self._base}/{comment_id}/replies", {"message": text})["id"])

    def comment_on_media(self, media_id: str, text: str) -> str:
        return str(self._call("POST", f"{self._base}/{media_id}/comments", {"message": text})["id"])

    def hide(self, comment_id: str, hide: bool = True) -> None:
        self._call("POST", f"{self._base}/{comment_id}", {"hide": "true" if hide else "false"})

    def refresh_token(self) -> tuple[str, int]:
        """A long-lived token lasts 60 days; refreshing (once it's 24 hours old) gives a new 60 days."""
        d = self._call(
            "GET",
            f"{self._host}/refresh_access_token",
            {"grant_type": "ig_refresh_token", "access_token": self._token},
            auth=False,
        )
        return str(d["access_token"]), int(d.get("expires_in", 0))
