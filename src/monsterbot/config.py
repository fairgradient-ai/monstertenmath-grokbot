"""The desk's config.toml: everything about the bot that isn't a secret or a rule.

Unknown keys fail the load, so a typo can't silently fall back to a default.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError

KNOWN_STORES = ("app_store", "google_play")


@dataclass(frozen=True)
class Config:
    # [account]
    username: str = "monstertenmath"
    timezone: str = "America/New_York"
    # [instagram]
    graph_host: str = "https://graph.instagram.com"
    graph_version: str = "v24.0"
    media_lookback: int = 12
    timeout_seconds: int = 30
    # [engage]
    auto_reply_max_age_hours: int = 72
    max_auto_replies_per_sweep: int = 20
    max_auto_replies_per_day: int = 60
    first_comments: bool = True
    first_comment_max_age_hours: int = 24
    thanks: bool = True
    # top level
    stores: tuple[str, ...] = ()
    pace_line: dict[str, int] = field(default_factory=dict)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


SECTIONS = {
    "account": ("username", "timezone"),
    "instagram": ("graph_host", "graph_version", "media_lookback", "timeout_seconds"),
    "engage": (
        "auto_reply_max_age_hours",
        "max_auto_replies_per_sweep",
        "max_auto_replies_per_day",
        "first_comments",
        "first_comment_max_age_hours",
        "thanks",
    ),
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
                values[sub] = subval
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

    cfg = Config(**values)
    try:
        cfg.tz  # noqa: B018 - validates the name
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ConfigError(
            f"unknown timezone {cfg.timezone!r} (if the name is right, this computer has no time zone data: "
            "install the tzdata package)"
        ) from e
    return cfg


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"no config at {path}: run scripts/install.sh")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config.toml doesn't parse: {e}") from e
    return parse_config(data)
