"""The desk's config.toml: everything about the bot that isn't a secret or a rule.

Unknown keys fail the load, so a typo can't silently fall back to a default.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError

KNOWN_STORES = ("app_store", "google_play")

# Hashtags from the growth plan's search list (6.3). Hashtag search allows 30 different tags a rolling week.
DEFAULT_HASHTAGS = (
    "kindergartenmath",
    "preschoolactivities",
    "prekathome",
    "numbersense",
    "tenframe",
    "homeschoolpreschool",
    "kindergartenteacher",
    "playbasedlearning",
    "earlymath",
    "mathgames",
    "preschoolmath",
    "learningthroughplay",
)


@dataclass(frozen=True)
class Config:
    # [account]
    username: str = "monstertenmath"
    timezone: str = "America/New_York"
    # [instagram]
    graph_host: str = "auto"  # auto: chosen from the token (channels/instagram.py, host_for)
    graph_version: str = "v24.0"
    ig_user_id: str = ""  # digits; blank: a Facebook-side token's account is found from the token
    media_lookback: int = 12
    timeout_seconds: int = 30
    # [engage]
    auto_reply_max_age_hours: int = 72
    max_auto_replies_per_sweep: int = 20
    max_auto_replies_per_day: int = 60
    first_comments: bool = True
    first_comment_max_age_hours: int = 24
    thanks: bool = True
    autosend_written: bool = True
    # [dms]
    dms_enabled: bool = False
    dm_window_hours: int = 23
    # [scout]
    scout_enabled: bool = False
    scout_ig_user_id: str = ""
    scout_graph_host: str = "https://graph.facebook.com"
    scout_graph_version: str = "v24.0"
    scout_hashtags: tuple[str, ...] = DEFAULT_HASHTAGS
    scout_hashtags_per_run: int = 4
    scout_max_lookups: int = 40
    scout_recheck_days: int = 14
    scout_followers_min: int = 5000
    scout_followers_max: int = 200000
    # [outreach]
    outreach_enabled: bool = False
    outreach_from_name: str = ""
    outreach_from_email: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    outreach_max_per_day: int = 10
    outreach_fee_usd: int = 200
    outreach_postal_address: str = ""
    # [brief]
    brief_per_run: int = 8
    brief_per_day: int = 30
    brief_max_age_hours: int = 24
    brief_min_score: int = 60
    brief_lookups: int = 25
    brief_email_to: str = ""
    # [browser]
    browser_enabled: bool = False
    browser_ramp_start: str = "2026-11-20"
    browser_max_comments_per_day: int = 30
    browser_max_likes_per_day: int = 60
    browser_max_follows_per_day: int = 25
    browser_max_following_total: int = 200
    browser_max_comments_per_session: int = 10
    browser_max_likes_per_session: int = 20
    browser_max_follows_per_session: int = 8
    browser_gap_seconds_min: int = 45
    browser_gap_seconds_max: int = 150
    browser_dwell_seconds_min: int = 6
    browser_dwell_seconds_max: int = 20
    browser_session_gap_minutes: int = 90
    browser_max_sessions_per_day: int = 3
    browser_plan_valid_minutes: int = 180
    browser_last_call_minutes: int = 15
    browser_quiet_start: str = "22:00"
    browser_quiet_end: str = "07:30"
    browser_cooldown_hours: int = 48
    browser_like_only_share: int = 25
    browser_feed_per_session: int = 4
    # [insights]
    insights_enabled: bool = False
    insights_lookback_days: int = 30
    insights_min_reach: int = 300
    insights_min_posts: int = 3
    # [buffer]
    buffer_enabled: bool = False
    buffer_social_checkout: str = "/workspace/monstertenmath_social"
    buffer_media_bucket: str = "monstertenmath-social-media"
    buffer_api: str = "https://api.buffer.com"
    # top level
    stores: tuple[str, ...] = ()
    pace_line: dict[str, int] = field(default_factory=dict)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


# section -> {key in config.toml: field name}
SECTIONS: dict[str, dict[str, str]] = {
    "account": {"username": "username", "timezone": "timezone"},
    "instagram": {k: k for k in ("graph_host", "graph_version", "ig_user_id", "media_lookback", "timeout_seconds")},
    "engage": {
        k: k
        for k in (
            "auto_reply_max_age_hours",
            "max_auto_replies_per_sweep",
            "max_auto_replies_per_day",
            "first_comments",
            "first_comment_max_age_hours",
            "thanks",
            "autosend_written",
        )
    },
    "dms": {"enabled": "dms_enabled", "window_hours": "dm_window_hours"},
    "scout": {
        "enabled": "scout_enabled",
        "ig_user_id": "scout_ig_user_id",
        "graph_host": "scout_graph_host",
        "graph_version": "scout_graph_version",
        "hashtags": "scout_hashtags",
        "hashtags_per_run": "scout_hashtags_per_run",
        "max_lookups": "scout_max_lookups",
        "recheck_days": "scout_recheck_days",
        "followers_min": "scout_followers_min",
        "followers_max": "scout_followers_max",
    },
    "outreach": {
        "enabled": "outreach_enabled",
        "from_name": "outreach_from_name",
        "from_email": "outreach_from_email",
        "smtp_host": "smtp_host",
        "smtp_port": "smtp_port",
        "max_per_day": "outreach_max_per_day",
        "fee_usd": "outreach_fee_usd",
        "postal_address": "outreach_postal_address",
    },
}
SECTIONS["brief"] = {
    "per_run": "brief_per_run",
    "per_day": "brief_per_day",
    "max_age_hours": "brief_max_age_hours",
    "min_score": "brief_min_score",
    "lookups": "brief_lookups",
    "email_to": "brief_email_to",
}
SECTIONS["browser"] = {
    k: "browser_" + k
    for k in (
        "enabled",
        "ramp_start",
        "max_comments_per_day",
        "max_likes_per_day",
        "max_follows_per_day",
        "max_following_total",
        "max_comments_per_session",
        "max_likes_per_session",
        "max_follows_per_session",
        "gap_seconds_min",
        "gap_seconds_max",
        "dwell_seconds_min",
        "dwell_seconds_max",
        "session_gap_minutes",
        "max_sessions_per_day",
        "plan_valid_minutes",
        "last_call_minutes",
        "quiet_start",
        "quiet_end",
        "cooldown_hours",
        "like_only_share",
        "feed_per_session",
    )
}
SECTIONS["insights"] = {k: "insights_" + k for k in ("enabled", "lookback_days", "min_reach", "min_posts")}
SECTIONS["buffer"] = {k: "buffer_" + k for k in ("enabled", "social_checkout", "media_bucket", "api")}
TOP_LEVEL = ("stores", "pace_line")


def parse_config(data: dict) -> Config:
    values: dict = {}
    for key, value in data.items():
        if key in SECTIONS:
            if not isinstance(value, dict):
                raise ConfigError(f"[{key}] must be a table")
            for sub, subval in value.items():
                if sub not in SECTIONS[key]:
                    raise ConfigError(f"unknown key {key}.{sub} in config.toml")
                values[SECTIONS[key][sub]] = subval
        elif key in TOP_LEVEL:
            values[key] = value
        else:
            raise ConfigError(f"unknown key {key} in config.toml")

    defaults = {f.name: f for f in fields(Config)}
    for name, value in list(values.items()):
        default = defaults[name].default
        if name == "stores":
            if not isinstance(value, list) or any(s not in KNOWN_STORES for s in value):
                raise ConfigError(f"stores must be a list drawn from {list(KNOWN_STORES)}")
            values[name] = tuple(value)
        elif name == "scout_hashtags":
            if not isinstance(value, list) or not all(isinstance(v, str) and v.strip("#") for v in value):
                raise ConfigError("scout.hashtags must be a list of hashtags")
            values[name] = tuple(v.strip("#").lower() for v in value)
        elif name == "pace_line":
            if not isinstance(value, dict) or not all(isinstance(v, int) for v in value.values()):
                raise ConfigError("pace_line maps a date (YYYY-MM-DD) to a follower count")
            values[name] = {str(k): v for k, v in value.items()}
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"{name} must be true or false")
        elif isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConfigError(f"{name} must be a whole number, 0 or more")
        elif isinstance(default, str) and not isinstance(value, str):
            raise ConfigError(f"{name} must be text")

    for name, key in (("ig_user_id", "instagram.ig_user_id"), ("scout_ig_user_id", "scout.ig_user_id")):
        if name in values:
            values[name] = _account_id(key, values[name])

    for name in ("browser_quiet_start", "browser_quiet_end"):
        if name in values and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", values[name]):
            raise ConfigError(f"browser.{name[8:]} must be a time like 22:00")
    if "browser_ramp_start" in values and not re.fullmatch(r"\d{4}-\d\d-\d\d", values["browser_ramp_start"]):
        raise ConfigError("browser.ramp_start must be a date like 2026-11-20")

    cfg = Config(**values)
    if (
        cfg.browser_gap_seconds_min > cfg.browser_gap_seconds_max
        or cfg.browser_dwell_seconds_min > cfg.browser_dwell_seconds_max
    ):
        raise ConfigError("[browser] each *_min must be at most its *_max")
    if cfg.browser_like_only_share > 100:
        raise ConfigError("browser.like_only_share is a percent, 0 to 100")
    try:
        cfg.tz  # noqa: B018 - validates the name
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ConfigError(
            f"unknown timezone {cfg.timezone!r} (if the name is right, this computer has no time zone data: "
            "install the tzdata package)"
        ) from e
    return cfg


def _account_id(key: str, value: str) -> str:
    """An Instagram account id is digits only. A dashboard link holds other ids (the app's, the business's), so
    nothing is taken out of one: the load fails and says what belongs here."""
    value = value.strip()
    if value and not re.fullmatch(r"[0-9]+", value):
        shown = "a link" if "://" in value or "/" in value else repr(value)
        raise ConfigError(
            f"{key} must be digits only, the number Meta shows next to the Instagram account (like "
            f'17841400000000000), not {shown}. Leave it "" and doctor finds the account from the token'
        )
    return value


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"no config at {path}: run scripts/install.sh")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config.toml doesn't parse: {e}") from e
    return parse_config(data)
