"""The commands scripts/run.sh runs. The Grok Bot posts their output verbatim.

Exit codes: 0 done, 1 refused or not done, 2 config, 3 Instagram or the computer.
Environment: MT_DESK (the desk folder), IG_ACCESS_TOKEN (secret card), MT_CHANNEL ("instagram", or
"fake:<fixture.json>" for tests), MT_NOW (a fixed ISO time, for tests).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, doctor
from .channels.fake import FakeInstagram
from .channels.instagram import InstagramChannel
from .config import load_config
from .desk import Desk
from .engine import Engine, short
from .errors import BotError, ChannelError, Refused
from .knowledge import load_knowledge
from .ledger import Ledger
from .report import draft_report, inbox_report, sweep_report
from .token import expiry, load_token, save_refreshed


def now_fn():
    fixed = os.environ.get("MT_NOW")
    if fixed:
        value = datetime.fromisoformat(fixed)
        return lambda: value
    return lambda: datetime.now(UTC)


def channel_factory(desk: Desk, cfg):
    spec = os.environ.get("MT_CHANNEL", "instagram")
    if spec.startswith("fake:"):
        return lambda token: FakeInstagram.from_file(Path(spec[5:]), desk.state / "fake-outbox.json")
    return lambda token: InstagramChannel(
        token or "", host=cfg.graph_host, version=cfg.graph_version, timeout=cfg.timeout_seconds
    )


def ids_arg(values: list[str], engine: Engine | None = None) -> list[int]:
    if values == ["all"] and engine is not None:
        return engine.drafted_ids()
    out = []
    for v in values:
        for part in v.replace(",", " ").split():
            if not part.isdigit():
                raise Refused(f'REFUSED: "{part}" isn\'t an item number.')
            out.append(int(part))
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run.sh", description="Monster Ten's social bot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sweep", help="read new comments, post canned replies (live), list the rest")
    sub.add_parser("inbox", help="what waits for you: drafts, questions, escalations, spam")
    d = sub.add_parser("draft", help="save a reply for an item (read from --text or standard input)")
    d.add_argument("item", type=int)
    d.add_argument("--text")
    s = sub.add_parser("send", help="post drafts (needs the owner's tap)")
    s.add_argument("items", nargs="+")
    s.add_argument("--owner-tapped", action="store_true")
    s.add_argument("--force-lint", action="store_true", help=argparse.SUPPRESS)
    x = sub.add_parser("discard", help="mark items as needing no reply")
    x.add_argument("items", nargs="+")
    h = sub.add_parser("hide", help="hide comments on Instagram (needs the owner's tap)")
    h.add_argument("items", nargs="+")
    h.add_argument("--owner-tapped", action="store_true")
    sub.add_parser("status", help="mode, phase, token, last sweep, what's waiting")
    sub.add_parser("stats", help="followers against the pace line, and the newest posts")
    dr = sub.add_parser("doctor", help="check the install, the config, the token and Instagram")
    dr.add_argument("--full", action="store_true", help="also run whole sweeps against the fake Instagram")
    ph = sub.add_parser("phase", help="show or change the phase (building/open)")
    ph.add_argument("value", nargs="?", choices=["show", "building", "open"], default="show")
    ph.add_argument("--owner-tapped", action="store_true")
    for name in ("go-live", "rehearse"):
        m = sub.add_parser(name, help=f"switch to {'live' if name == 'go-live' else 'rehearsal'} mode")
        m.add_argument("--owner-tapped", action="store_true")
    t = sub.add_parser("token", help="show or refresh the Instagram token's expiry (never the token)")
    t.add_argument("action", choices=["status", "refresh"])
    sub.add_parser("version")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    desk = Desk.from_env()
    try:
        return _run(args, desk)
    except BotError as e:
        msg = str(e)
        if isinstance(e, ChannelError):
            msg = f"FAILED: {e}" + (" Make a new token: SETUP.md, section 2." if e.kind == "token" else "")
        print(msg)
        return e.exit_code


def _run(args, desk: Desk) -> int:
    now = now_fn()
    if args.cmd == "version":
        print(f"monsterbot {__version__}")
        return 0
    if args.cmd == "doctor":
        try:
            cfg = load_config(desk.config_path)
            factory = channel_factory(desk, cfg)
        except BotError:
            factory = None
        lines, code = doctor.run(desk, args.full, factory)
        print("\n".join(lines))
        return code

    desk.ensure()
    cfg = load_config(desk.config_path)
    kn = load_knowledge()
    ledger = Ledger(desk.db_path)
    token, source = load_token(desk, ledger)
    lazy: dict = {}

    def channel():
        if "c" not in lazy:
            lazy["c"] = channel_factory(desk, cfg)(token)
        return lazy["c"]

    class LazyChannel:
        name = "instagram"

        def __getattr__(self, attr):
            return getattr(channel(), attr)

    engine = Engine(cfg, desk, kn, LazyChannel(), ledger, now=now)

    if args.cmd == "sweep":
        with desk.lock():
            res = engine.sweep()
        print("\n".join(sweep_report(engine, res)))
        return 3 if res.stopped == "token" else 0

    if args.cmd == "inbox":
        print("\n".join(inbox_report(engine)))
        return 0

    if args.cmd == "draft":
        text = args.text if args.text is not None else sys.stdin.read()
        with desk.lock(wait_seconds=120):
            item, violations = engine.draft(args.item, text)
        print("\n".join(draft_report(item, violations)))
        return 0 if not violations else 1

    if args.cmd == "send":
        with desk.lock(wait_seconds=120):
            ids = ids_arg(args.items, engine)
            if not ids:
                print('NOTHING TO SEND: no draft passes the check. Say "inbox".')
                return 1
            lines = engine.send(ids, owner_tapped=args.owner_tapped, force_lint=args.force_lint)
        print("\n".join(lines))
        return 0 if all(line.startswith(("SENT", "REHEARSAL")) for line in lines) else 1

    if args.cmd == "discard":
        with desk.lock(wait_seconds=120):
            print("\n".join(engine.discard(ids_arg(args.items))))
        return 0

    if args.cmd == "hide":
        with desk.lock(wait_seconds=120):
            print("\n".join(engine.hide(ids_arg(args.items), owner_tapped=args.owner_tapped)))
        return 0

    if args.cmd == "status":
        print("\n".join(status_lines(engine, source)))
        return 0

    if args.cmd == "stats":
        print("\n".join(stats_lines(engine)))
        return 0

    if args.cmd == "phase":
        if args.value == "show":
            print(f"PHASE: {desk.phase()}")
            return 0
        if not args.owner_tapped:
            raise Refused(f"REFUSED: changing the phase to {args.value} needs your tap (--owner-tapped).")
        desk.set_phase(args.value, now())
        print(
            f"PHASE: {args.value}."
            + (
                " Replies now point to the free check (link in bio)."
                if args.value == "open"
                else ' Replies say "being built" again and give no link.'
            )
        )
        return 0

    if args.cmd in ("go-live", "rehearse"):
        mode = "live" if args.cmd == "go-live" else "rehearsal"
        if not args.owner_tapped:
            raise Refused(f"REFUSED: switching to {mode} needs your tap (--owner-tapped).")
        desk.set_mode(mode, now())
        print(
            f"MODE: {mode}."
            + (
                " Canned replies and first comments now post by themselves; drafts still wait for your tap."
                if mode == "live"
                else " Nothing posts by itself."
            )
        )
        return 0

    if args.cmd == "token":
        if args.action == "status":
            exp = expiry(ledger)
            print(
                f"TOKEN: from the {source}"
                + (f", good until about {exp.date()}" if exp else ", expiry unknown until the first refresh")
            )
            return 0 if token else 3
        with desk.lock(wait_seconds=120):
            new_token, expires_in = channel().refresh_token()
            save_refreshed(desk, ledger, new_token, expires_in, now())
        exp = expiry(ledger)
        print(f"TOKEN REFRESHED: good until about {exp.date() if exp else '?'}. Kept in the desk, not shown.")
        return 0

    raise Refused(f"unknown command {args.cmd}")


def status_lines(engine: Engine, source: str) -> list[str]:
    ledger, desk = engine.ledger, engine.desk
    last = ledger.kv_get("last_sweep")
    exp = expiry(ledger)
    waiting = ledger.items(statuses=("queued", "drafted", "unverified"))
    drafts = [i for i in waiting if i.status == "drafted"]
    owner = [i for i in waiting if i.status == "queued" and i.tier == "owner"]
    from .ledger import day_ago

    lines = [
        f"STATUS · mode {desk.mode()} · phase {desk.phase()}",
        (f"Token: from the {source}" + (f", good until about {exp.date()}" if exp else ", expiry unknown"))
        if source != "none"
        else "Token: none. The owner adds IG_ACCESS_TOKEN on the secret card (SETUP.md, section 3).",
        "Last sweep: "
        + (f"{engine.local(datetime.fromisoformat(last))} ({ledger.kv_get('last_sweep_result')})" if last else "never"),
        f"Waiting for you: {len(waiting)} ({len(drafts)} drafts, {len(owner)} for you only)",
        f"Canned replies in the last 24 h: {ledger.auto_replies_since(day_ago(engine.now()))} "
        f"(cap {engine.cfg.max_auto_replies_per_day})",
    ]
    return lines


def stats_lines(engine: Engine) -> list[str]:
    now = engine.now()
    me = engine.channel.me()
    local_day = now.astimezone(engine.cfg.tz).date()
    day = local_day.isoformat()
    lines = [f"STATS · @{me.username} · {engine.local(now)}"]
    if me.followers_count is not None:
        engine.ledger.record_followers(day, me.followers_count, now)
        pace = engine.cfg.pace_line.get(day)
        prev = engine.ledger.followers_on((local_day.fromordinal(local_day.toordinal() - 1)).isoformat())
        parts = [f"Followers: {me.followers_count}"]
        if pace is not None:
            gap = me.followers_count - pace
            parts.append(f"pace line today {pace} ({'+' if gap >= 0 else ''}{gap})")
        if prev is not None:
            parts.append(f"yesterday {prev} (+{me.followers_count - prev})")
        lines.append(" · ".join(parts))
    for m in engine.channel.recent_media(min(engine.cfg.media_lookback, 8)):
        piece = engine.kn.match_piece(m.caption)
        name = piece.label if piece else short(m.caption, 40)
        likes = f"{m.like_count} likes · " if m.like_count is not None else ""
        lines.append(f"  {name}: {likes}{m.comments_count} comments")
    return lines


if __name__ == "__main__":
    sys.exit(main())
