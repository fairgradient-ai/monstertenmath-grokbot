"""The 30-second check, in code: every reply the bot posts or saves as a draft passes through check().

The rules live in knowledge/rules.toml. A reply with any violation is never posted by itself; a draft with
one can be sent only with the owner's explicit "send anyway" (--force-lint).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FLAGS = re.IGNORECASE
HASHTAG = re.compile(r"(?<![\w&])#[A-Za-z_]\w*")
MENTION = re.compile(r"(?<![\w.])@([A-Za-z0-9_.]*[A-Za-z0-9_])")
PRICE = re.compile(r"\$\s?\d[\d,]*(?:\.\d\d)?")


@dataclass(frozen=True)
class Violation:
    id: str
    why: str
    excerpt: str = ""

    def __str__(self) -> str:
        return f"{self.id}: {self.why}" + (f' ("{self.excerpt}")' if self.excerpt else "")


@dataclass(frozen=True)
class Context:
    phase: str  # building | open
    category: str = "draft"
    author: str | None = None  # the person we're answering; the only account a reply may @mention
    stores: tuple[str, ...] = ()


def check(text: str, ctx: Context, rules: dict) -> list[Violation]:
    out: list[Violation] = []
    body = (text or "").strip()
    if not body:
        return [Violation("empty", "The reply is empty.")]

    max_length = 3000 if ctx.category == "email" else int(rules.get("max_length", 600))
    if len(body) > max_length:
        out.append(Violation("too-long", f"Keep replies under {max_length} characters (this is {len(body)})."))

    allowed_always = [a.lower() for a in rules.get("links", {}).get("allowed_always", [])]
    scrubbed = body
    for allowed in allowed_always:
        scrubbed = re.sub(re.escape(allowed), " ", scrubbed, flags=FLAGS)

    tags = HASHTAG.findall(scrubbed)
    if len(tags) > int(rules.get("max_hashtags", 0)):
        out.append(Violation("hashtags", "Replies carry no hashtags: captions already use all 5.", " ".join(tags)))

    handle = str(rules.get("handle", "")).lower()
    allowed_mentions = {handle, (ctx.author or "").lower()} - {""}
    for name in MENTION.findall(scrubbed):
        if name.lower() not in allowed_mentions:
            out.append(Violation("mention", "Tag no one but the person you're answering.", "@" + name))

    for rival in rules.get("rivals", []):
        if re.search(re.escape(rival), body, FLAGS):
            out.append(Violation("rival", "Never name a rival account.", rival))

    for rule in rules.get("banned", []):
        if rule.get("phase") and rule["phase"] != ctx.phase:
            continue
        if rule.get("categories") and ctx.category not in rule["categories"]:
            continue
        if ctx.category in rule.get("skip_categories", ()):
            continue
        pattern = rule.get("_re") or re.compile(rule["pattern"], FLAGS)
        m = pattern.search(body)
        if m:
            out.append(Violation(rule["id"], rule["why"], m.group(0).strip()))

    trial = rules.get("trial", {})
    email = ctx.category == "email"  # a Collab fee isn't a product price
    trigger = trial.get("trigger", "")
    if email:
        trigger = trigger.replace(r"|\$\s?\d", "")
    if trial and re.search(trigger, body, FLAGS):
        missing = [req["why"] for req in trial["required"] if not re.search(req["pattern"], body, FLAGS)]
        if missing:
            out.append(
                Violation(
                    "trial-terms",
                    "Trial terms whole, or not at all. Missing: " + "; ".join(missing) + ".",
                )
            )
    prices = {p.replace(" ", "") for p in trial.get("prices", [])}
    for price in [] if email else PRICE.findall(body):
        if price.replace(" ", "").replace(",", "") not in prices:
            out.append(
                Violation("price", "That price isn't one of the real prices ($79.99 a year, $12.99 a month).", price)
            )

    links = rules.get("links", {})
    if links:
        link_text = scrubbed
        allowed_now = list(links.get("allowed_open", [])) if ctx.phase == "open" else []
        if email:
            allowed_now += links.get("allowed_email", [])
        for allowed in allowed_now:
            link_text = re.sub(re.escape(allowed), " ", link_text, flags=FLAGS)
        m = re.search(links["pattern"], link_text, FLAGS)
        if m:
            why = (
                "Before launch, replies carry no links."
                if ctx.phase == "building"
                else "The only link a reply gives is monstertenmath.com/insta."
            )
            out.append(Violation("link", why, m.group(0)))

    stores = rules.get("stores", {})
    if stores:
        for store in ("app_store", "google_play"):
            m = re.search(stores[store], body, FLAGS)
            if m and store not in ctx.stores:
                out.append(
                    Violation("store", "Name a store only once the app is really in it (gate step 4).", m.group(0))
                )
        m = re.search(stores["any"], body, FLAGS)
        if m and not ctx.stores:
            out.append(Violation("store", 'No "download" until the app is in a store (gate step 4).', m.group(0)))

    return _dedupe(out)


def _dedupe(violations: list[Violation]) -> list[Violation]:
    seen: set[tuple[str, str]] = set()
    out = []
    for v in violations:
        if (v.id, v.excerpt.lower()) not in seen:
            seen.add((v.id, v.excerpt.lower()))
            out.append(v)
    return out
