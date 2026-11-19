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
    mode, phase = engine.desk.mode(), engine.desk.phase_label()
    when = engine.local(engine.now())
    head = f"SWEEP · {mode.upper()} · {phase} · {when}"
    fresh = [engine.ledger.get(i) for i in res.fresh]
    fresh_items = [i for i in fresh if i is not None]
    waiting = engine.ledger.items(statuses=("queued", "drafted", "unverified"))
    acted = res.replied or res.would_reply or res.first_comments or res.problems

    where = f"{res.posts} posts" + (f" and {res.threads} DM threads" if res.threads else "")
    if not fresh_items and not acted:
        tail = f' Waiting for you: {len(waiting)} (say "inbox").' if waiting else ""
        learned = f" Learned {res.learned} replies you wrote in the app." if res.learned else ""
        return [f"{head} · quiet: nothing new on {where}.{learned}{tail}"]

    verb = "replied" if mode == "live" else "would reply"
    count = len(res.replied) if mode == "live" else len(res.would_reply)
    out = [head, f"{len(fresh_items)} new on {where} · {verb} {count} · waiting for you {len(waiting)}"]
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
        out.append("Needs a written reply (I'll write these next; each posts by itself if it passes the check):")
        out.extend(_line(engine, i, f" · {i.reason}" if i.reason else "") for i in needs)
    holding = [i for i in fresh_items if i.category == "escalate" and i.tier == "auto"]
    owner = [i for i in fresh_items if i.status == "queued" and i.tier == "owner" and i.category != "spam"]
    if holding or owner:
        out.append("For you:")
        verb_h = "answered" if mode == "live" else "would answer"
        out.extend(
            _line(engine, i, f" · {i.reason} · {verb_h} with the holding line; follow up by email") for i in holding
        )
        for i in owner:
            tail = i.reason if "24-hour" in i.reason else f"{i.reason} · I'll draft a reply and wait for your OK"
            out.append(_line(engine, i, f" · {tail}"))
    spam = [i for i in fresh_items if i.category == "spam"]
    if spam:
        out.append('Spam (hide, delete or block it in the app, or say "hide <number>"):')
        out.extend(_line(engine, i) for i in spam)
    skipped = [i for i in fresh_items if i.status == "skipped"]
    if skipped:
        out.append(f"Skipped {len(skipped)}: our own comments and friends tagging friends.")
    if res.learned:
        out.append(f'Learned {res.learned} replies you wrote in the app (say "examples" to see them).')
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
    out = [f"INBOX · {len(items)} waiting · {engine.desk.mode()} · {engine.desk.phase_label()}"]
    if ready:
        out.append('Drafts waiting for your OK (say "send 14", "send all", "edit 14: ..." or "skip 14"):')
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


SOURCE_LABEL = {"owner-edit": "you edited", "owner-instagram": "you, in the app", "owner-approved": "you approved"}


def examples_report(ledger) -> list[str]:
    rows = ledger.examples(limit=20, sources=tuple(SOURCE_LABEL))
    if not rows:
        return ["EXAMPLES · none yet. Every reply you write in the app, edit or approve is kept here."]
    out = [f"EXAMPLES · how you answer, newest first ({len(rows)})"]
    for r in rows:
        out.append(f'  [{SOURCE_LABEL[r["source"]]}, {r["kind"]}] "{short(r["incoming"], 90)}"')
        out.append(f'      → "{short(r["final"], 200)}"')
        if r["bot_draft"]:
            out.append(f'      (I had: "{short(r["bot_draft"], 160)}")')
    return out
