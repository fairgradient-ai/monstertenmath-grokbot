"""Sorting a comment: what kind it is, and whether the bot may answer it by itself.

Tiers:
  auto   a canned reply from knowledge/ (posted by itself in live mode)
  draft  needs a written reply: the Grok Bot drafts one, the owner sends it
  owner  never answered by the bot: spam, money, a child's health, the law, partnerships, rivals
  skip   needs nothing
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .knowledge import Knowledge, Piece
from .models import Comment

NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
# Words that can sit around a guess without making it something else ("my son said 3!").
FILLER = set(
    """
a an and are answer answered asleep awake but cards card crackers cracker cup did dots easy equals finger fingers
first got guess guessed haha he he's hidden hiding i i'm is it it's its left lol make makes monster my oh ok okay
only plus right said say says saw see shouted so son daughter kid kids child that the them then there they think
this took takes under was we were wow yay yeah yelled yes hmm um maybe
""".split()
)
QUESTION = re.compile(
    r"\?|^\s*(how|what|when|where|which|who|why|is|are|can|could|do|does|will|would|should)\b", re.IGNORECASE
)
TOKENS = re.compile(r"[a-z][a-z']*|\d+")


@dataclass(frozen=True)
class Verdict:
    category: str
    tier: str
    reply: str | None = None
    reason: str = ""
    notify: str | None = None


def escalation(kn: Knowledge, reason: str) -> Verdict:
    """Escalations are the owner's. Some get a holding line at once (it moves the talk to email); the rest wait
    for the owner's OK on a draft."""
    holding = kn.holding.get(reason)
    if holding:
        return Verdict(
            "escalate",
            "auto",
            holding,
            reason,
            notify=f"{reason}: answered with the holding line (email us). Follow up from info@monstertenmath.com.",
        )
    return Verdict("escalate", "owner", reason=reason)


def numbers_in(text: str) -> list[int]:
    out = []
    for tok in TOKENS.findall(text.lower()):
        if tok.isdigit() and len(tok) <= 2:
            out.append(int(tok))
        elif tok in NUMBER_WORDS:
            out.append(NUMBER_WORDS[tok])
    return out


def looks_like_guess(text: str) -> bool:
    """Short, mostly numbers: "3!", "he took 3", "my son said three". Not "my 5 year old loved it"."""
    if len(text.strip()) > 60:
        return False
    toks = TOKENS.findall(text.lower())
    nums = [t for t in toks if t.isdigit() or t in NUMBER_WORDS]
    rest = [t for t in toks if not (t.isdigit() or t in NUMBER_WORDS or t in FILLER)]
    return bool(nums) and len(rest) <= 1


def answer_guess(piece: Piece, text: str) -> Verdict | None:
    play = piece.play_along
    if play is None or not looks_like_guess(text):
        return None
    nums = numbers_in(text)
    if play.sequence:
        if tuple(nums) == play.sequence:
            return Verdict("guess", "auto", play.right, "all four right")
        if 1 <= len(nums) <= 6:
            return Verdict("guess", "auto", play.wrong, "a guess")
        return None
    distinct = set(nums)
    if play.answer in distinct:
        if distinct - {play.answer} <= play.context:  # "3", "7 and 3 make 10"
            return Verdict("guess", "auto", play.right, f"right ({play.answer})")
        return Verdict("guess", "draft", reason="more than one number: which is the guess?")
    if len(distinct) == 1:
        return Verdict("guess", "auto", play.wrong, f"a guess ({nums[0]}, not {play.answer})")
    return Verdict("guess", "draft", reason="more than one number: which is the guess?")


def triage(
    comment: Comment,
    *,
    piece: Piece | None,
    handle: str,
    parent: Comment | None,
    kn: Knowledge,
    phase: str,
    stores: tuple[str, ...],
    thanks: bool,
    line_index: int = 0,
    pricing: str = "standard",
) -> Verdict:
    text = comment.text or ""
    is_question = bool(QUESTION.search(text))
    mentions_us = f"@{handle.lower()}" in text.lower()

    if comment.username.lower() == handle.lower():
        return Verdict("own", "skip")

    # A reply under someone else's comment is a conversation: a person writes back, or nothing.
    if parent is not None and parent.username.lower() != handle.lower():
        if kn.tag_only.search(text) and not mentions_us:
            return Verdict("tag-only", "skip")
        if kn.spam.search(text):
            return Verdict("spam", "owner", reason="spam")
        for reason, pattern in kn.escalate:
            if pattern.search(text):
                return escalation(kn, reason)
        if is_question or mentions_us:
            return Verdict("thread", "draft", reason=f"a reply under @{parent.username}'s comment")
        return Verdict("thread", "skip", reason="people talking in someone else's thread")

    if kn.spam.search(text):
        return Verdict("spam", "owner", reason="spam")
    reasons = [reason for reason, pattern in kn.escalate if pattern.search(text)]
    if reasons:
        ahead = _ahead_of_escalation(kn, text, is_question, reasons, phase, stores, pricing)
        return ahead or escalation(kn, reasons[0])
    if kn.tag_only.search(text) and not mentions_us:
        return Verdict("tag-only", "skip")

    if kn.ai_question.search(text):
        if piece and piece.ai_reply:
            return Verdict("ai_question", "auto", piece.ai_reply, f"the AI line for {piece.key}")
        return Verdict("ai_question", "draft", reason="an AI question on a post with no AI line")

    if piece is not None:
        guess = answer_guess(piece, text)
        if guess is not None:
            return guess

    for faq in kn.faqs:
        if faq.question_only and not is_question:
            continue
        if faq.pieces and (piece is None or piece.key not in faq.pieces):
            continue
        if faq.needs_voice and (piece is None or piece.voice != "ai"):
            continue
        if not faq.pattern.search(text):
            continue
        reply = faq.text_for(phase, stores, pricing)
        if reply is None:
            return Verdict(f"faq:{faq.id}", "draft", reason=f"no canned {phase} reply for this question")
        return Verdict(f"faq:{faq.id}", "auto", reply, faq.id, notify=faq.notify)

    if not is_question:
        stripped = text.strip()
        if thanks and _emoji_only(stripped):
            return Verdict("praise", "auto", kn.praise.lines[line_index % len(kn.praise.lines)], "emoji")
        if thanks and len(stripped) <= kn.praise.max_length and kn.praise.pattern.search(stripped):
            return Verdict("praise", "auto", kn.praise.lines[line_index % len(kn.praise.lines)], "praise")
        if len(stripped) <= kn.played.max_length and kn.played.pattern.search(stripped):
            return Verdict("played", "auto", kn.played.lines[line_index % len(kn.played.lines)], "played")

    return Verdict("draft", "draft", reason="a question" if is_question else "needs a written reply")


def _ahead_of_escalation(
    kn: Knowledge,
    text: str,
    is_question: bool,
    reasons: list[str],
    phase: str,
    stores: tuple[str, ...],
    pricing: str,
) -> Verdict | None:
    """A question an faq may answer although it also matches an escalation (faq.ahead_of_escalation): only
    when every escalation it matches is one of those, `unless` doesn't match, and there's a canned text now."""
    for faq in kn.faqs:
        if not faq.ahead_of_escalation or not set(reasons) <= set(faq.ahead_of_escalation):
            continue
        if (faq.question_only and not is_question) or not faq.pattern.search(text):
            continue
        if faq.unless is not None and faq.unless.search(text):
            continue
        reply = faq.text_for(phase, stores, pricing)
        if reply is not None:
            return Verdict(f"faq:{faq.id}", "auto", reply, faq.id, notify=faq.notify)
    return None


def _emoji_only(text: str) -> bool:
    return bool(text) and not re.search(r"[A-Za-z0-9]", text) and len(text) <= 24
