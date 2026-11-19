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

    cfg = Config(**values)
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
