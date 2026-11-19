"""Errors with the exit code the CLI returns for them."""

from __future__ import annotations


class BotError(Exception):
    exit_code = 1


class ConfigError(BotError):
    exit_code = 2


class Refused(BotError):
    """A command that needs the owner's tap, or that would break a rule, was asked for without it."""

    exit_code = 1


class Busy(BotError):
    exit_code = 0


class ChannelError(BotError):
    """A failed call to a social platform.

    kind: token | rate | permission | network | bad_request | other.
    ambiguous: the request may have reached the platform (a timeout on a POST), so a retry could double it.
    """

    exit_code = 3

    def __init__(self, message: str, kind: str = "other", ambiguous: bool = False, code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.ambiguous = ambiguous
        self.code = code
