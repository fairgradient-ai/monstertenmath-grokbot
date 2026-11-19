"""Finding creators, through Meta's Instagram API with Facebook Login (graph.facebook.com).

Read-only, public business and creator profiles:
- Business Discovery: a creator's follower count, bio, website and recent posts, by username.
- Hashtag search: the top posts under a hashtag (30 different hashtags in a rolling 7 days). Hashtag posts don't
  name their author, so the scout takes candidates from the @mentions in their captions.

This needs a second token, from Facebook Login for Business, with instagram_basic and pages_read_engagement
(and pages_show_list), on a Facebook Page linked to @monstertenmath. Hashtag search also needs the
"Instagram Public Content Access" feature, which needs App Review (SETUP.md, section 13).
Nothing here writes anything anywhere.
"""

from __future__ import annotations

from collections.abc import Callable

from ..errors import ChannelError
from ..models import Profile
from .instagram import InstagramChannel

POST_FIELDS = "id,caption,like_count,comments_count,timestamp,permalink,media_type"


class FacebookGraph:
    def __init__(
        self,
        token: str,
        *,
        ig_user_id: str = "",
        username: str = "",
        host: str = "https://graph.facebook.com",
        version: str = "v24.0",
        timeout: int = 30,
        opener: Callable[..., object] | None = None,
    ):
        if not token:
            raise ChannelError("no Facebook token: add FB_ACCESS_TOKEN on the secret card (SETUP.md, 13)", "token")
        # The same HTTP, error handling, header-only token and account lookup as the Instagram client.
        self._http = InstagramChannel(
            token, host=host, version=version, timeout=timeout, opener=opener, username=username
        )
        self._ig_user_id = ig_user_id

    def ig_user_id(self) -> str:
        if not self._ig_user_id:
            self._ig_user_id = self._http.find_account()
        return self._ig_user_id

    def business_discovery(self, username: str) -> Profile | None:
        fields = (
            f"business_discovery.username({username})"
            "{username,name,biography,website,followers_count,media_count,"
            f"media.limit(12){{{POST_FIELDS}}}}}"
        )
        try:
            d = self._http._get(self.ig_user_id(), {"fields": fields})
        except ChannelError as e:
            if e.kind == "bad_request":
                return None  # a personal account, a private one, or no such username
            raise
        b = d.get("business_discovery") or {}
        if not b:
            return None
        return Profile(
            username=b.get("username", username).lower(),
            name=b.get("name", ""),
            biography=b.get("biography", ""),
            website=b.get("website", ""),
            followers=int(b.get("followers_count") or 0),
            media_count=int(b.get("media_count") or 0),
            posts=tuple((b.get("media") or {}).get("data", [])),
        )

    def hashtag_top_media(self, tag: str) -> list[dict]:
        uid = self.ig_user_id()
        found = self._http._get("ig_hashtag_search", {"user_id": uid, "q": tag}).get("data", [])
        if not found:
            return []
        d = self._http._get(f"{found[0]['id']}/top_media", {"user_id": uid, "fields": POST_FIELDS, "limit": 50})
        return list(d.get("data", []))
