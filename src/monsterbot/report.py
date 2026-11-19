"""What the bot posts in chat. The first line is always the verdict, so a routine's output reads at a glance."""

from __future__ import annotations

from .engine import Engine, SweepResult, short
from .ledger import Item
from .policy import check

STOPPED = {
    "token": "the Instagram token stopped working. Make a new one (SETUP.md, section 2) and put it on the card.",
    "rate": "Instagram's rate limit. Nothing more was posted; the next sweep carries on.",
    "network": "Instagram stopped answering. Nothing more was posted; the next sweep carries on.",
}


def _line(engine: Engine, item: Item, extra: str = "") -> str:
    return f'  [{item.id}] {engine.label(item)} · @{item.author}: "{short(item.text)}"{extra}'


def sweep_report(engine: Engine, res: SweepResult) -> list[str]:
    mode, phase = engine.desk.mode(), engine.desk.phase()
    when = engine.local(engine.now())
    head = f"SWEEP · {mode.upper()} · {phase} · {when}"
    fresh = [engine.ledger.get(i) for i in res.fresh]
    fresh_items = [i for i in fresh if i is not None]
    waiting = engine.ledger.items(statuses=("queued", "drafted", "unverified"))
    acted = res.replied or res.would_reply or res.first_comments or res.problems

    if not fresh_items and not acted:
        tail = f' Waiting for you: {len(waiting)} (say "inbox").' if waiting else ""
        return [f"{head} · quiet: nothing new on {res.posts} posts.{tail}"]

    verb = "replied" if mode == "live" else "would reply"
    count = len(res.replied) if mode == "live" else len(res.would_reply)
    out = [
        head,
        f"{len(fresh_items)} new comments on {res.posts} posts · {verb} {count} · waiting for you {len(waiting)}",
    ]
    if res.stopped:
        out.insert(0, f"STOPPED: {STOPPED.get(res.stopped, res.stopped)}")

    pairs = res.replied if mode == "live" else res.would_reply
    if pairs:
        out.append("Replied:" if mode == "live" else "Would reply (rehearsal, nothing posted):")
        for item_id, text in pairs:
            item = engine.ledger.get(item_id)
            if item:
                out.append(_line(engine, item, f' → "{short(text, 120)}"'))
    out.extend(res.first_comments)

    needs = [i for i in fresh_items if i.status == "queued" and i.tier == "draft"]
    if needs:
        out.append("Needs a written reply (I'll draft these next; you send them):")
        out.extend(_line(engine, i, f" · {i.reason}" if i.reason else "") for i in needs)
    owner = [i for i in fresh_items if i.status == "queued" and i.tier == "owner" and i.category != "spam"]
    if owner:
        out.append("For you (I won't answer these):")
        out.extend(_line(engine, i, f" · {i.reason}") for i in owner)
    spam = [i for i in fresh_items if i.category == "spam"]
    if spam:
        out.append('Spam (hide, delete or block it in the app, or say "hide <number>"):')
        out.extend(_line(engine, i) for i in spam)
    skipped = [i for i in fresh_items if i.status == "skipped"]
    if skipped:
        out.append(f"Skipped {len(skipped)}: our own comments and friends tagging friends.")
    if res.held:
        out.append(f"Held {res.held} canned replies for the next sweep (the per-sweep or daily cap).")
    if res.problems:
        out.append("Problems:")
        out.extend(f"  {p}" for p in res.problems)
    out.extend(res.notes)
    return out


def inbox_report(engine: Engine) -> list[str]:
    items = engine.ledger.items(statuses=("queued", "drafted", "unverified"))
    if not items:
        return ["INBOX · empty: nothing waits for you."]
    ready, blocked, needs, owner, unverified = [], [], [], [], []
    for i in items:
        if i.status == "unverified":
            unverified.append(i)
        elif i.status == "drafted":
            (blocked if check(i.draft_text or "", engine.ctx(i), engine.kn.rules) else ready).append(i)
        elif i.tier == "owner":
            owner.append(i)
        else:
            needs.append(i)
    out = [f"INBOX · {len(items)} waiting · {engine.desk.mode()} · {engine.desk.phase()}"]
    if ready:
        out.append('Drafts ready (say "send 14", "send all", "edit 14: ..." or "skip 14"):')
        for i in ready:
            out.append(_line(engine, i))
            out.append(f'      draft: "{short(i.draft_text, 300)}"')
    if blocked:
        out.append('Drafts that fail the check (edit them, or say "send 14 anyway"):')
        for i in blocked:
            out.append(_line(engine, i))
            out.append(f'      draft: "{short(i.draft_text, 300)}"')
            for v in check(i.draft_text or "", engine.ctx(i), engine.kn.rules):
                out.append(f"      ✗ {v}")
    if needs:
        out.append("Need a written reply:")
        out.extend(_line(engine, i, f" · {i.reason}" if i.reason else "") for i in needs)
    if owner:
        out.append("For you (spam, money, a child's health, legal, business, rivals):")
        out.extend(_line(engine, i, f" · {i.reason}") for i in owner)
    if unverified:
        out.append("Sent but not yet seen on Instagram (the next sweep checks):")
        out.extend(_line(engine, i) for i in unverified)
    return out


def draft_report(item: Item, violations: list) -> list[str]:
    if not violations:
        return [
            f'DRAFT [{item.id}] saved · passes the check · say "send {item.id}" to post it.',
            f'  "{short(item.draft_text, 300)}"',
        ]
    return [
        f"DRAFT [{item.id}] saved · FAILS the check, so it can't be sent as it is:",
        f'  "{short(item.draft_text, 300)}"',
        *[f"  ✗ {v}" for v in violations],
    ]
