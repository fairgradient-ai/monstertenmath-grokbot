"""Collab outreach by email: the growth plan's 6.5 email, made personal by the Grok Bot, sent on the owner's tap.

Every email offers money (the flat Collab fee), so sending always needs the owner's OK; one tap can approve a
batch ("send all outreach"). A creator who says no, or was rejected, is never written to again.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import datetime

from . import policy
from .config import Config
from .errors import ChannelError, Refused
from .knowledge import Knowledge, default_dir
from .ledger import Ledger, day_ago

NEVER_AGAIN = ("contacted", "booked", "declined", "rejected", "unreachable")


@dataclass(frozen=True)
class Template:
    subject: str
    body: str
    status_line: dict[str, str]


def load_template() -> Template:
    raw = tomllib.loads((default_dir() / "outreach.toml").read_text(encoding="utf-8"))
    return Template(subject=raw["subject"], body=raw["body"], status_line=dict(raw["status_line"]))


def first_name_of(name: str | None, username: str) -> str:
    for part in (name or "").replace("|", " ").split():
        if part.isalpha() and part[0].isupper() and len(part) > 1:
            return part
    return "there"


class Outreach:
    def __init__(self, cfg: Config, kn: Knowledge, ledger: Ledger, phase: str, mode: str, now: datetime):
        self.cfg, self.kn, self.ledger, self.phase, self.mode, self.now = cfg, kn, ledger, phase, mode, now
        self.template = load_template()

    def compose(self, username: str, personal_line: str, first_name: str | None = None) -> tuple[str, list[str]]:
        row = self.ledger.creator(username)
        if row is None:
            raise Refused(f'REFUSED: @{username} isn\'t in the creator list. Run the scout, or "scout add" them.')
        if row["status"] in NEVER_AGAIN:
            raise Refused(f"REFUSED: @{username} is {row['status']}: no email.")
        if not row["email"]:
            raise Refused(f"REFUSED: no email for @{username} (none in their bio).")
        if not (self.cfg.outreach_from_name and self.cfg.outreach_from_email and self.cfg.outreach_postal_address):
            raise Refused("REFUSED: set outreach.from_name, from_email and postal_address in config.toml first.")
        line = " ".join(personal_line.split())
        body = self.template.body.format(
            first_name=first_name or first_name_of(row["name"], username),
            personal_line=line,
            status_line=self.template.status_line[self.phase],
            fee=self.cfg.outreach_fee_usd,
            from_name=self.cfg.outreach_from_name,
            postal_address=self.cfg.outreach_postal_address,
        )
        violations = [str(v) for v in policy.check(body, policy.Context(self.phase, "email"), self.kn.rules)]
        if not line:
            violations.insert(0, "empty: write one or two sentences about one of their recent posts")
        self.ledger.upsert_creator(
            username,
            self.now,
            outreach_subject=self.template.subject,
            outreach_body=body,
            outreach_violations=json.dumps(violations),
            status="drafted",
        )
        return body, violations

    def ready(self) -> list[str]:
        return [
            r["username"]
            for r in self.ledger.creators(statuses=("drafted",), limit=500)
            if r["outreach_body"] and not json.loads(r["outreach_violations"] or "[]")
        ]

    def send(self, usernames: list[str], email_channel, *, owner_tapped: bool) -> list[str]:
        if not owner_tapped:
            raise Refused("REFUSED: outreach offers money, so it needs your tap (--owner-tapped).")
        out: list[str] = []
        sent_today = self.ledger.emails_sent_since(day_ago(self.now))
        for username in usernames:
            row = self.ledger.creator(username)
            if row is None or row["status"] != "drafted" or not row["outreach_body"]:
                out.append(f"NOT SENT @{username}: no outreach draft.")
                continue
            if json.loads(row["outreach_violations"] or "[]"):
                out.append(f'NOT SENT @{username}: the draft fails the check ("outreach list" shows why).')
                continue
            if sent_today >= self.cfg.outreach_max_per_day:
                out.append(f"NOT SENT @{username}: today's limit of {self.cfg.outreach_max_per_day} emails.")
                continue
            if self.mode == "rehearsal":
                out.append(f"REHEARSAL: would email @{username} at {row['email']}.")
                continue
            try:
                email_channel.send(row["email"], row["outreach_subject"], row["outreach_body"])
            except ChannelError as e:
                out.append(f"NOT SENT @{username}: {e}")
                if e.kind == "token":
                    break
                continue
            sent_today += 1
            self.ledger.upsert_creator(username, self.now, status="contacted", outreach_sent_at=self.now.isoformat())
            out.append(f"SENT the Collab email to @{username} ({row['email']}).")
        return out
