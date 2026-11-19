"""The commands scripts/run.sh runs. The Grok Bot posts their output verbatim.

Exit codes: 0 done, 1 refused or not done, 2 config, 3 Instagram or the computer.
Environment: MT_DESK (the desk folder); from the secret card IG_ACCESS_TOKEN, FB_ACCESS_TOKEN (scouting),
SMTP_USER and SMTP_PASSWORD (outreach); for tests MT_CHANNEL / MT_GRAPH ("fake:<fixture.json>"), MT_EMAIL
("fake") and MT_NOW (a fixed ISO time).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, doctor
from .brief import Brief, ago, ids_from
from .channels.email import SmtpEmail
from .channels.facebook import FacebookGraph
from .channels.fake import FakeEmail, FakeGraph, FakeInstagram
from .channels.instagram import InstagramChannel
from .config import load_config
from .desk import Desk
from .engine import Engine, short
from .errors import BotError, ChannelError, Refused
from .knowledge import load_knowledge
from .ledger import Ledger
from .outreach import Outreach
from .report import draft_report, examples_report, inbox_report, sweep_report
from .scout import STATUSES, Scout
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


def graph_factory(cfg):
    spec = os.environ.get("MT_GRAPH", "facebook")
    if spec.startswith("fake:"):
        return FakeGraph(json.loads(Path(spec[5:]).read_text()))
    return FacebookGraph(
        os.environ.get("FB_ACCESS_TOKEN", "").strip(),
        ig_user_id=cfg.scout_ig_user_id,
        host=cfg.scout_graph_host,
        version=cfg.scout_graph_version,
        timeout=cfg.timeout_seconds,
    )


class FileEmail(FakeEmail):
    """MT_EMAIL=fake: emails are written to the desk instead of sent."""

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def send(self, to: str, subject: str, body: str) -> str:
        sent = json.loads(self.path.read_text()) if self.path.exists() else []
        sent.append({"to": to, "subject": subject, "body": body})
        self.path.write_text(json.dumps(sent, indent=1, ensure_ascii=False))
        return f"fake-email-{len(sent)}"


def email_factory(cfg, desk: Desk):
    if os.environ.get("MT_EMAIL") == "fake":
        return FileEmail(desk.state / "fake-emails.json")
    return SmtpEmail(
        host=cfg.smtp_host,
        port=cfg.smtp_port,
        user=os.environ.get("SMTP_USER", ""),
        password=os.environ.get("SMTP_PASSWORD", ""),
        from_name=cfg.outreach_from_name,
        from_email=cfg.outreach_from_email,
    )


def handles(values: list[str]) -> list[str]:
    return [v.strip().lstrip("@").lower() for value in values for v in value.replace(",", " ").split() if v.strip()]


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
    r = sub.add_parser("reply", help="the Grok Bot's written reply: posted at once if it passes the check")
    r.add_argument("item", type=int)
    r.add_argument("--text")
    d = sub.add_parser("draft", help="save a reply for an item without posting it (--text or standard input)")
    d.add_argument("item", type=int)
    d.add_argument("--text")
    d.add_argument("--by", choices=["bot", "owner"], default="bot", help="owner: the owner gave these words")
    s = sub.add_parser("send", help="post drafts (needs the owner's tap)")
    s.add_argument("items", nargs="+")
    s.add_argument("--owner-tapped", action="store_true")
    s.add_argument("--force-lint", action="store_true", help=argparse.SUPPRESS)
    x = sub.add_parser("discard", help="mark items as needing no reply")
    x.add_argument("items", nargs="+")
    h = sub.add_parser("hide", help="hide comments on Instagram (needs the owner's tap)")
    h.add_argument("items", nargs="+")
    h.add_argument("--owner-tapped", action="store_true")
    sub.add_parser("status", help="mode, phase, pricing, token, last sweep, what's waiting")
    sub.add_parser("stats", help="followers against the pace line, and the newest posts")
    dr = sub.add_parser("doctor", help="check the install, the config, the token and Instagram")
    dr.add_argument("--full", action="store_true", help="also run whole sweeps against the fake Instagram")
    ph = sub.add_parser("phase", help="show or change the phase (building/open)")
    ph.add_argument("value", nargs="?", choices=["show", "building", "open"], default="show")
    ph.add_argument("--owner-tapped", action="store_true")
    pr = sub.add_parser("pricing", help="show or change the pricing (standard/founding)")
    pr.add_argument("value", nargs="?", choices=["show", "standard", "founding"], default="show")
    pr.add_argument("--owner-tapped", action="store_true")
    for name in ("go-live", "rehearse"):
        m = sub.add_parser(name, help=f"switch to {'live' if name == 'go-live' else 'rehearsal'} mode")
        m.add_argument("--owner-tapped", action="store_true")
    t = sub.add_parser("token", help="show or refresh the Instagram token's expiry (never the token)")
    t.add_argument("action", choices=["status", "refresh"])
    sub.add_parser("examples", help="how the owner answers: replies they wrote, edited or approved")
    sc = sub.add_parser("scout", help="find creators (read-only), or add usernames to look at")
    sc.add_argument("action", nargs="?", choices=["run", "add"], default="run")
    sc.add_argument("usernames", nargs="*")
    cr = sub.add_parser("creators", help="the creator list: show, or mark one")
    cr.add_argument("action", nargs="?", choices=["list", "show", "mark"], default="list")
    cr.add_argument("username", nargs="?")
    cr.add_argument("status", nargs="?", choices=STATUSES)
    cr.add_argument("--note", default="")
    cr.add_argument("--all", action="store_true")
    ou = sub.add_parser("outreach", help="Collab emails: draft one, list them, or send (needs the owner's tap)")
    ou.add_argument("action", choices=["draft", "list", "send"])
    ou.add_argument("usernames", nargs="*")
    ou.add_argument("--first-name")
    ou.add_argument("--text")
    ou.add_argument("--owner-tapped", action="store_true")
    br = sub.add_parser("brief", help="fresh creator posts with a comment for each, for a person to post")
    br.add_argument("action", nargs="?", choices=["new", "comment", "show", "done", "skip", "email"], default="new")
    br.add_argument("items", nargs="*")
    br.add_argument("--text")
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
            item, violations = engine.draft(args.item, text, by=args.by)
        print("\n".join(draft_report(item, violations)))
        return 0 if not violations else 1

    if args.cmd == "reply":
        text = args.text if args.text is not None else sys.stdin.read()
        with desk.lock(wait_seconds=120):
            item, violations, outcome = engine.reply(args.item, text)
        print("\n".join(reply_report(engine, item, violations, outcome)))
        return 0 if outcome in ("sent", "rehearsal") or outcome.startswith("waits") else 1

    if args.cmd == "examples":
        print("\n".join(examples_report(ledger)))
        return 0

    if args.cmd == "scout":
        if args.action == "add":
            names = handles(args.usernames)
            for name in names:
                if ledger.creator(name) is None:
                    ledger.upsert_creator(name, now(), status="seed", source="added for a look")
            print(f"SCOUT: {len(names)} added to look at on the next scout run: " + ", ".join("@" + n for n in names))
            return 0
        if not cfg.scout_enabled:
            raise Refused("REFUSED: scouting is off. Set [scout] enabled = true in config.toml (SETUP.md, 13).")
        with desk.lock(wait_seconds=120):
            looked, notes = Scout(cfg, kn, ledger, graph_factory(cfg), now()).run()
        print("\n".join(scout_report(ledger, looked, notes)))
        return 0

    if args.cmd == "creators":
        return creators_command(args, ledger, now())

    if args.cmd == "brief":
        return brief_command(args, cfg, kn, ledger, desk, now())

    if args.cmd == "outreach":
        out = Outreach(cfg, kn, ledger, desk.phase(), desk.mode(), now())
        if args.action == "list":
            print("\n".join(outreach_list(ledger)))
            return 0
        if args.action == "draft":
            if len(args.usernames) != 1:
                raise Refused("REFUSED: draft one creator at a time: outreach draft <username>.")
            line = args.text if args.text is not None else sys.stdin.read()
            with desk.lock(wait_seconds=120):
                body, violations = out.compose(handles(args.usernames)[0], line, args.first_name)
            head = (
                "OUTREACH DRAFT saved · passes the check"
                if not violations
                else "OUTREACH DRAFT saved · FAILS the check"
            )
            print("\n".join([head, "", body, *[f"✗ {v}" for v in violations]]))
            return 0 if not violations else 1
        if not cfg.outreach_enabled:
            raise Refused("REFUSED: outreach is off. Set [outreach] enabled = true in config.toml (SETUP.md, 14).")
        names = out.ready() if args.usernames == ["all"] else handles(args.usernames)
        if not names:
            print("NOTHING TO SEND: no outreach draft passes the check.")
            return 1
        with desk.lock(wait_seconds=120):
            lines = out.send(
                names, None if desk.mode() == "rehearsal" else email_factory(cfg, desk), owner_tapped=args.owner_tapped
            )
        print("\n".join(lines))
        return 0 if all(line.startswith(("SENT", "REHEARSAL")) for line in lines) else 1

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
                + (
                    ' If the site\'s ticket shows the founding price, say "founding price on".'
                    if desk.pricing() == "standard"
                    else " Price answers give the founding price."
                )
                if args.value == "open"
                else ' Replies say "being built" again and give no link.'
            )
        )
        return 0

    if args.cmd == "pricing":
        if args.value == "show":
            print(f"PRICING: {desk.pricing()}." + pricing_note(desk.pricing(), desk.phase()))
            return 0
        if not args.owner_tapped:
            raise Refused(f"REFUSED: changing the pricing to {args.value} needs your tap (--owner-tapped).")
        desk.set_pricing(args.value, now())
        print(f"PRICING: {args.value}." + pricing_note(args.value, desk.phase()))
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


def pricing_note(pricing: str, phase: str) -> str:
    if pricing == "standard":
        return " Price answers give $79.99 a year or $12.99 a month, and never name the founding price."
    if phase == "open":
        return (
            " Price answers give the founding price, $59.99 a year or $9.99 a month for the first 500 families,"
            " with its terms whole."
        )
    return " The founding price starts with the open phase; until then the answers stay as they are."


def reply_report(engine: Engine, item, violations, outcome: str) -> list[str]:
    text = f'"{short(item.draft_text, 300)}"'
    if violations:
        return [
            f"HELD [{item.id}]: the reply fails the check, so it wasn't posted:",
            f"  {text}",
            *[f"  ✗ {v}" for v in violations],
        ]
    if outcome == "sent":
        return [f"SENT [{item.id}] to @{item.author} on {engine.label(item)}: {text}"]
    if outcome == "rehearsal":
        return [f"REHEARSAL [{item.id}]: would send to @{item.author}: {text}"]
    return [f"SAVED [{item.id}], not posted: {outcome}.", f"  {text}"]


def scout_report(ledger: Ledger, looked: list[str], notes: list[str]) -> list[str]:
    top = [r for r in ledger.creators(statuses=("new", "shortlist", "drafted"), limit=12)]
    out = [f"SCOUT · looked up {len(looked)} profiles · {len(top)} candidates to consider"]
    for r in top:
        out.append(creator_line(r))
    out.extend(f"Note: {n}" for n in notes)
    out.append('Say "creators show <name>" for a profile, "creators mark <name> shortlist" or "reject".')
    return out


def creator_line(r) -> str:
    eng = f"{(r['engagement'] or 0):.1%}" if r["engagement"] is not None else "?"
    email = "email ✓" if r["email"] else "no email"
    followers = f"{r['followers']:,}" if r["followers"] is not None else "?"
    score = r["score"] if r["score"] is not None else "–"
    return f"  {score:>3} @{r['username']} · {followers} followers · {eng} engagement · {email} · {r['status']}"


def creators_command(args, ledger: Ledger, now) -> int:
    if args.action == "list":
        statuses = None if args.all else ("new", "shortlist", "drafted", "contacted", "booked")
        rows = ledger.creators(statuses=statuses, limit=40)
        print("\n".join(["CREATORS · by score", *[creator_line(r) for r in rows]] if rows else ["CREATORS · none yet"]))
        return 0
    name = (args.username or "").lstrip("@").lower()
    row = ledger.creator(name) if name else None
    if row is None:
        raise Refused(f"REFUSED: @{name} isn't in the creator list.")
    if args.action == "show":
        lines = [
            f"@{row['username']} · {row['name'] or ''}",
            creator_line(row).strip(),
            f"Bio: {row['biography'] or ''}",
            f"Website: {row['website'] or ''}",
            f"Found: {row['source'] or ''} · checked {row['checked_at'] or 'never'}",
        ]
        lines += [f"Note: {n}" for n in json.loads(row["score_notes"] or "[]")]
        if row["note"]:
            lines.append(f"Our note: {row['note']}")
        lines += ["Recent captions:", *[f"  - {short(c, 160)}" for c in json.loads(row["captions"] or "[]")]]
        print("\n".join(lines))
        return 0
    if not args.status:
        raise Refused("REFUSED: say which: creators mark <name> shortlist|reject|declined|booked|new.")
    ledger.upsert_creator(name, now, status=args.status, **({"note": args.note} if args.note else {}))
    print(f"CREATOR @{name}: {args.status}" + (f" · {args.note}" if args.note else ""))
    return 0


def brief_command(args, cfg, kn, ledger: Ledger, desk: Desk, now) -> int:
    if args.action in ("new", "email") and not cfg.scout_enabled:
        raise Refused("REFUSED: the brief reads creators' posts, so it needs the scout set up (SETUP.md, 13).")
    b = Brief(cfg, kn, ledger, graph_factory(cfg) if args.action == "new" else None, desk.phase(), now)
    if args.action == "new":
        with desk.lock(wait_seconds=120):
            ids, notes = b.build()
        rows = [b.row(i) for i in ids]
        head = f"BRIEF · {len(rows)} fresh posts to comment on · {now.astimezone(cfg.tz).strftime('%a %d %b %H:%M %Z')}"
        out = [head]
        for r in rows:
            out.append(
                f"  [B{r['id']}] @{r['creator']} · {ago(now, datetime.fromisoformat(r['posted_at']))} · "
                f'"{short(r["caption"], 140)}"'
            )
            out.append(f"        {r['permalink']}")
        out.extend(f"Note: {n}" for n in notes)
        if rows:
            out.append(
                "Next: write one comment for each with run.sh brief comment <number> "
                '(voice skill, "Comments on creators\' posts"), then run.sh brief show.'
            )
        print("\n".join(out))
        return 0
    if args.action == "comment":
        if len(args.items) != 1:
            raise Refused("REFUSED: one at a time: brief comment B12.")
        text = args.text if args.text is not None else sys.stdin.read()
        n = ids_from(args.items)[0]
        violations = b.comment(n, text)
        r = b.row(n)
        if violations:
            print(
                "\n".join(
                    [
                        f"HELD [B{n}]: the comment fails the check:",
                        f'  "{r["comment"]}"',
                        *[f"  ✗ {v}" for v in violations],
                    ]
                )
            )
            return 1
        print(f'READY [B{n}] for @{r["creator"]}: "{r["comment"]}"')
        return 0
    if args.action in ("done", "skip"):
        print("\n".join(b.mark(ids_from(args.items), "posted" if args.action == "done" else "skipped")))
        return 0
    lines = brief_list(b, now)
    if args.action == "show":
        print("\n".join(lines))
        return 0
    # email: the ready list to the helper's address in config.toml
    if not cfg.brief_email_to:
        raise Refused("REFUSED: set [brief] email_to in config.toml to email the brief.")
    if not b.ready():
        print("NOTHING TO EMAIL: no comment is ready.")
        return 1
    part = (
        "morning"
        if now.astimezone(cfg.tz).hour < 12
        else "afternoon"
        if now.astimezone(cfg.tz).hour < 17
        else "evening"
    )
    email_factory(cfg, desk).send(
        cfg.brief_email_to, f"Monster Ten: comments to post ({part})", "\n".join(lines) + "\n"
    )
    print(f"EMAILED the brief ({len(b.ready())} comments) to {cfg.brief_email_to}.")
    return 0


def brief_list(b: Brief, now) -> list[str]:
    ready, waiting = b.ready(), b.waiting()
    if not ready:
        tail = f" {len(waiting)} still need a comment." if waiting else ""
        return [f"COMMENTS TO POST · none ready.{tail}"]
    out = [
        f"COMMENTS TO POST · {len(ready)} · from @monstertenmath, by hand, one every minute or two",
        'Open each link, paste the comment, post. Then say "done" with the numbers (or "skip").',
        "",
    ]
    for r in ready:
        out.append(f"[B{r['id']}] @{r['creator']} · {ago(now, datetime.fromisoformat(r['posted_at']))}")
        out.append(f"  {r['permalink']}")
        out.append(f"  {r['comment']}")
        out.append("")
    if waiting:
        out.append(f"{len(waiting)} more still need a comment.")
    return out


def outreach_list(ledger: Ledger) -> list[str]:
    rows = ledger.creators(statuses=("drafted", "contacted", "booked", "declined"), limit=100)
    if not rows:
        return ["OUTREACH · nothing drafted or sent yet"]
    out = ["OUTREACH"]
    for r in rows:
        bad = json.loads(r["outreach_violations"] or "[]")
        state = r["status"] + (f" {r['outreach_sent_at'][:10]}" if r["outreach_sent_at"] else "")
        out.append(f"  @{r['username']} · {r['email'] or 'no email'} · {state}" + (" · FAILS the check" if bad else ""))
        out.extend(f"      ✗ {v}" for v in bad)
    out.append('Say "send all outreach" to email every draft that passes (one tap), or "send outreach to @name".')
    return out


def status_lines(engine: Engine, source: str) -> list[str]:
    ledger, desk = engine.ledger, engine.desk
    last = ledger.kv_get("last_sweep")
    exp = expiry(ledger)
    waiting = ledger.items(statuses=("queued", "drafted", "unverified"))
    drafts = [i for i in waiting if i.status == "drafted"]
    owner = [i for i in waiting if i.status == "queued" and i.tier == "owner"]
    from .ledger import day_ago

    lines = [
        f"STATUS · mode {desk.mode()} · phase {desk.phase()} · pricing {desk.pricing()}",
        (f"Token: from the {source}" + (f", good until about {exp.date()}" if exp else ", expiry unknown"))
        if source != "none"
        else "Token: none. The owner adds IG_ACCESS_TOKEN on the secret card (SETUP.md, section 3).",
        "Last sweep: "
        + (f"{engine.local(datetime.fromisoformat(last))} ({ledger.kv_get('last_sweep_result')})" if last else "never"),
        f"Waiting for you: {len(waiting)} ({len(drafts)} drafts, {len(owner)} for you only)",
        f"Posted without your tap in the last 24 h: {ledger.auto_replies_since(day_ago(engine.now()))} "
        f"(cap {engine.cfg.max_auto_replies_per_day})",
        "On: comments"
        + ", written replies" * engine.cfg.autosend_written
        + ", DMs" * engine.cfg.dms_enabled
        + ", scout" * engine.cfg.scout_enabled
        + ", outreach" * engine.cfg.outreach_enabled,
        f"Creators: {len(ledger.creators(statuses=('shortlist',), limit=999))} shortlisted, "
        f"{len(ledger.creators(statuses=('drafted',), limit=999))} emails waiting for your OK, "
        f"{len(ledger.creators(statuses=('contacted',), limit=999))} contacted, "
        f"{len(ledger.creators(statuses=('booked',), limit=999))} booked",
    ]
    counts = Brief(engine.cfg, engine.kn, ledger, None, desk.phase(), engine.now()).stats()
    if counts:
        lines.append(
            f"Brief, last 24 h: {sum(counts.values())} posts · {counts.get('ready', 0)} comments ready to post · "
            f"{counts.get('posted', 0)} posted · {counts.get('proposed', 0)} need a comment"
        )
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
