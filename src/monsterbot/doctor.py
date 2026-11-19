"""doctor: is the bot ready? Prints ok / WARN / FAIL per check and a verdict line. Never prints a token."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path

from . import __version__, policy
from .channels.fake import FakeInstagram
from .config import Config, load_config
from .desk import Desk
from .engine import Engine
from .errors import BotError, ChannelError
from .knowledge import Knowledge, load_knowledge
from .ledger import Ledger
from .token import expiry, load_token

FIXTURE_NOW = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)


class Checks:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.worst = "PASS"

    def ok(self, msg: str) -> None:
        self.lines.append(f"ok: {msg}")

    def warn(self, msg: str) -> None:
        self.lines.append(f"WARN: {msg}")
        if self.worst == "PASS":
            self.worst = "WARN"

    def fail(self, msg: str) -> None:
        self.lines.append(f"FAIL: {msg}")
        self.worst = "FAIL"


def pinned_release(checkout: Path) -> str | None:
    try:
        for line in (checkout / "pins.env").read_text().splitlines():
            if line.startswith("BOT_RELEASE="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        return None
    return None


def lint_knowledge(kn: Knowledge) -> list[str]:
    """Every canned text must pass the check in each phase it can be used in."""
    problems = []
    for where, text, phase, category in kn.canned_texts():
        if phase == "both":
            contexts = [policy.Context("building", category or "draft"), policy.Context("open", category or "draft")]
        elif phase.startswith("open:"):
            contexts = [policy.Context("open", category or "draft", stores=tuple(phase[5:].split("+")))]
        else:
            contexts = [policy.Context(phase, category or "draft")]
        for ctx in contexts:
            for v in policy.check(text, ctx, kn.rules):
                problems.append(f"{where} ({ctx.phase}): {v}")
    return problems


def run(desk: Desk, full: bool, channel_factory) -> tuple[list[str], int]:
    c = Checks()
    checkout = Path(__file__).resolve().parents[2]

    pin = pinned_release(checkout)
    if pin is None:
        c.warn("no pins.env next to the engine")
    elif pin.lstrip("v") != __version__:
        c.fail(f"engine {__version__} but pins.env says {pin}: re-run scripts/install.sh")
    else:
        c.ok(f"release {pin}")

    # (Python older than 3.11 can't import tomllib, so it never gets here: install.sh checks it.)
    c.ok(f"Python {sys.version.split()[0]}")

    cfg: Config | None = None
    try:
        cfg = load_config(desk.config_path)
        c.ok(f"config {desk.config_path} (@{cfg.username}, {cfg.timezone}, stores {list(cfg.stores) or 'none'})")
    except BotError as e:
        c.fail(str(e))

    kn: Knowledge | None = None
    try:
        kn = load_knowledge()
        problems = lint_knowledge(kn)
        if problems:
            for p in problems:
                c.fail(f"canned text fails the check: {p}")
        else:
            c.ok(f"knowledge: {len(kn.pieces)} pieces, {len(kn.faqs)} questions, every canned reply passes the check")
    except BotError as e:
        c.fail(str(e))

    try:
        desk.ensure()
        ledger = Ledger(desk.db_path)
        c.ok(f"desk {desk.root} · mode {desk.mode()} · phase {desk.phase()}")
    except OSError as e:
        c.fail(f"desk {desk.root} isn't writable: {e}")
        return _finish(c)

    if cfg is not None:
        token, source = load_token(desk, ledger)
        if not token and channel_factory is None:
            c.fail("no Instagram token: the owner adds IG_ACCESS_TOKEN on the secret card (SETUP.md, section 3)")
        else:
            if token:
                c.ok(f"token from the {source}")
            exp = expiry(ledger)
            now = datetime.now(UTC)
            if exp is None:
                c.warn("token expiry unknown until the first refresh (the weekly health routine does it)")
            elif exp - now < timedelta(days=10):
                c.warn(f'token expires {exp.date()}: say "refresh the token" (or make a new one, SETUP.md 2)')
            else:
                c.ok(f"token good until about {exp.date()}")
            try:
                channel = channel_factory(token) if channel_factory else None
                if channel is not None:
                    _check_instagram(c, channel, cfg, desk)
            except ChannelError as e:
                c.fail(f"Instagram: {e}")

    if full:
        _full(c)
    return _finish(c)


def _check_instagram(c: Checks, channel, cfg: Config, desk: Desk) -> None:
    me = channel.me()
    if me.username.lower() != cfg.username.lower():
        c.fail(f"the token is for @{me.username}, config says @{cfg.username}")
    else:
        c.ok(
            f"Instagram answers as @{me.username} ({me.account_type or 'type unknown'}, "
            f"{me.followers_count if me.followers_count is not None else '?'} followers)"
        )
    if me.account_type and me.account_type not in ("BUSINESS", "MEDIA_CREATOR"):
        c.warn(f"account type {me.account_type}: comment replies need a professional account")
    media = channel.recent_media(1)
    if media:
        channel.comments(media[0].id)
        c.ok("can read comments on the newest post")
    else:
        c.warn("no posts yet, so comment access is untested")
    extras = channel.profile_extras() if hasattr(channel, "profile_extras") else {}
    if "website" in extras:
        link = (extras.get("website") or "").strip()
        if desk.phase() == "building" and link:
            c.warn(f'phase is building but the bio has a link ({link}): run the gate, then say "we\'re open"')
        elif desk.phase() == "open" and not link:
            c.warn("phase is open but the bio has no link: check the profile (README section 1)")
        else:
            c.ok(f"bio link matches the {desk.phase()} phase")
    else:
        c.ok("bio link not readable through this API version (skipped)")


def _full(c: Checks) -> None:
    """A whole sweep against the fake Instagram, in both modes and both phases, in a throwaway desk."""
    fixture = resources.files("monsterbot").joinpath("fixtures/fake_instagram.json")
    with tempfile.TemporaryDirectory() as tmp, resources.as_file(fixture) as fx:
        for phase in ("building", "open"):
            for mode in ("rehearsal", "live"):
                desk = Desk(Path(tmp) / f"{phase}-{mode}")
                desk.ensure()
                desk.set_mode(mode, FIXTURE_NOW)
                desk.set_phase(phase, FIXTURE_NOW)
                fake = FakeInstagram.from_file(fx)
                ledger = Ledger(desk.db_path)
                engine = Engine(Config(), desk, load_knowledge(), fake, ledger, now=lambda: FIXTURE_NOW)
                res = engine.sweep()
                planned = res.replied if mode == "live" else res.would_reply
                posted = len(fake.posted)
                expect_posted = (len(planned) + len(res.first_comments)) if mode == "live" else 0
                if not planned:
                    c.fail(f"fake sweep ({phase}, {mode}): no canned replies planned")
                elif posted != expect_posted:
                    c.fail(f"fake sweep ({phase}, {mode}): posted {posted}, expected {expect_posted}")
                else:
                    c.ok(
                        f"fake sweep ({phase}, {mode}): {len(planned)} replies, "
                        f"{len(res.first_comments)} first comments, {posted} posted"
                    )
                ledger.close()


def _finish(c: Checks) -> tuple[list[str], int]:
    c.lines.insert(0, f"DOCTOR: {c.worst}")
    return c.lines, (0 if c.worst != "FAIL" else 3)


def env_desk() -> Desk:
    return Desk(Path(os.environ.get("MT_DESK", "/workspace/monsterten-desk")))
