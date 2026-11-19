"""Where the Instagram token comes from.

The owner puts it on the Grok Bot's secret card as IG_ACCESS_TOKEN. A long-lived token lasts 60 days, so the
weekly health routine refreshes it and keeps the new one in the desk (secrets/instagram.env, mode 0600),
because a script can't write to the secret card.

Which one wins: the refreshed file, but only while the card still holds the token it was refreshed from.
If the owner pastes a new token on the card, the card wins again. No step to remember.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta

from .desk import Desk
from .ledger import Ledger


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _read_file_token(desk: Desk) -> str | None:
    try:
        for line in desk.secrets_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("IG_ACCESS_TOKEN="):
                return line.split("=", 1)[1].strip() or None
    except FileNotFoundError:
        return None
    return None


def load_token(desk: Desk, ledger: Ledger) -> tuple[str | None, str]:
    card = os.environ.get("IG_ACCESS_TOKEN", "").strip() or None
    refreshed = _read_file_token(desk)
    if refreshed and (card is None or ledger.kv_get("token.card_sha") == _sha(card)):
        return refreshed, "refreshed (desk)"
    if card:
        return card, "secret card"
    return None, "none"


def save_refreshed(desk: Desk, ledger: Ledger, new_token: str, expires_in: int, now: datetime) -> None:
    card = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    path = desk.secrets_file
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"IG_ACCESS_TOKEN={new_token}\n")
    tmp.replace(path)
    ledger.kv_set("token.card_sha", _sha(card) if card else "")
    ledger.kv_set("token.refreshed_at", now.isoformat())
    if expires_in:
        ledger.kv_set("token.expires_at", (now + timedelta(seconds=expires_in)).isoformat())


def expiry(ledger: Ledger) -> datetime | None:
    value = ledger.kv_get("token.expires_at")
    return datetime.fromisoformat(value) if value else None
