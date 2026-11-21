"""The knowledge files: the brand rules, the canned replies and the pieces (knowledge/*.toml)."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError

FLAGS = re.IGNORECASE


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


@dataclass(frozen=True)
class PlayAlong:
    right: str
    wrong: str
    answer: int | None = None
    sequence: tuple[int, ...] = ()
    context: frozenset[int] = frozenset()


PILLARS = {
    "games": "Game Reels: the Monster's games, animated",
    "tonight": "Try it tonight: a game with things at home",
    "realistic": "Realistic Reels: a parent's phone over a child's hands",
    "play-along": "Play along: guess with the Monster",
    "features": "What's inside: the standards, Monster Writes, check-ups, How it's going",
    "brand": "Brand and launch (not scored as a pillar)",
}


def pillar_for(key: str) -> str:
    """Today's pillars, from the calendar's numbering. pieces.toml may name one instead (pillar = "...")."""
    n = int(key.lstrip("#")) if key.lstrip("#").isdigit() else 0
    if n in (3, 14, 15):
        return "play-along"
    if n in (4, 6) or 500 <= n < 600:
        return "tonight"
    if 22 <= n <= 32:
        return "games"
    if 600 <= n < 700:
        return "realistic"
    if 401 <= n <= 411:
        return "features"
    return "brand"


@dataclass(frozen=True)
class Piece:
    key: str
    name: str
    type: str
    ai: bool
    voice: str
    caption_start: str
    first_comment: str | None = None
    ai_reply: str | None = None
    play_along: PlayAlong | None = None
    pillar: str = ""  # set from the key when pieces.toml leaves it out (pillar_for)
    child: bool = False  # a real child on screen
    ad_cleared: bool = False  # a real child's release allows ads (release box 2, checked by the lawyer)

    @property
    def label(self) -> str:
        return f"{self.key} {self.name}"


@dataclass(frozen=True)
class Faq:
    id: str
    pattern: re.Pattern[str]
    building: str | None = None
    open: str | None = None
    open_founding: str | None = None  # from launch day while the founding price is on; else `open`
    open_by_stores: dict[str, str] = field(default_factory=dict)
    question_only: bool = False
    pieces: tuple[str, ...] = ()
    needs_voice: bool = False
    notify: str | None = None
    # Escalation reasons this question may answer ahead of ("If I cancel, do I keep the founding price?" is a
    # founding question, not a billing problem), unless `unless` matches too.
    ahead_of_escalation: tuple[str, ...] = ()
    unless: re.Pattern[str] | None = None

    def text_for(self, phase: str, stores: tuple[str, ...], pricing: str = "standard") -> str | None:
        if phase != "open":
            return self.building
        if self.open_by_stores:
            return self.open_by_stores.get("+".join(sorted(stores))) if stores else None
        if pricing == "founding" and self.open_founding:
            return self.open_founding
        return self.open


@dataclass(frozen=True)
class Lines:
    pattern: re.Pattern[str]
    lines: tuple[str, ...]
    max_length: int


@dataclass(frozen=True)
class Knowledge:
    rules: dict
    pieces: tuple[Piece, ...]
    spam: re.Pattern[str]
    escalate: tuple[tuple[str, re.Pattern[str]], ...]
    tag_only: re.Pattern[str]
    ai_question: re.Pattern[str]
    faqs: tuple[Faq, ...]
    praise: Lines
    played: Lines
    holding: dict[str, str] = field(default_factory=dict)

    def match_piece(self, caption: str) -> Piece | None:
        # The longest matching start wins: "Try it tonight: Monster's Cave" (#4) is a prefix of #402's start.
        cap = _norm(caption)
        hits = [p for p in self.pieces if cap.startswith(_norm(p.caption_start))]
        return max(hits, key=lambda p: len(_norm(p.caption_start)), default=None)

    def piece(self, key: str | None) -> Piece | None:
        return next((p for p in self.pieces if p.key == key), None) if key else None

    def canned_texts(self) -> list[tuple[str, str, str, str | None]]:
        """Every text the bot may post without asking: (where, text, when, category).

        when: "both" (any phase and pricing), "building", "open" (open, either pricing), "open-standard" or
        "open-founding" (open, that pricing only), or "open:<stores>" (open, those stores, either pricing)."""
        out: list[tuple[str, str, str, str | None]] = []
        for p in self.pieces:
            if p.first_comment:
                out.append((f"{p.key} first_comment", p.first_comment, "both", "first_comment"))
            if p.ai_reply:
                out.append((f"{p.key} ai_reply", p.ai_reply, "both", "ai_question"))
            if p.play_along:
                out.append((f"{p.key} play_along.right", p.play_along.right, "both", "guess"))
                out.append((f"{p.key} play_along.wrong", p.play_along.wrong, "both", "guess"))
        for f in self.faqs:
            if f.building:
                out.append((f"faq {f.id} building", f.building, "building", "faq"))
            if f.open:
                out.append((f"faq {f.id} open", f.open, "open-standard" if f.open_founding else "open", "faq"))
            if f.open_founding:
                out.append((f"faq {f.id} open_founding", f.open_founding, "open-founding", "faq"))
            for stores, text in f.open_by_stores.items():
                out.append((f"faq {f.id} open[{stores}]", text, f"open:{stores}", "faq"))
        for reason, text in self.holding.items():
            out.append((f"holding {reason}", text, "both", "holding"))
        for name, lines in (("praise", self.praise), ("played", self.played)):
            for i, text in enumerate(lines.lines):
                out.append((f"{name} line {i + 1}", text, "both", name))
        return out


def _compile(pattern: str, where: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, FLAGS)
    except re.error as e:
        raise ConfigError(f"bad pattern in {where}: {e}") from e


def _load(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"missing knowledge file {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name} doesn't parse: {e}") from e


def default_dir() -> Path:
    env = os.environ.get("MT_KNOWLEDGE")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "knowledge"


def load_knowledge(directory: Path | None = None) -> Knowledge:
    d = directory or default_dir()
    rules = _load(d / "rules.toml")
    replies = _load(d / "replies.toml")
    pieces_raw = _load(d / "pieces.toml")

    for rule in rules.get("banned", []):
        rule["_re"] = _compile(rule["pattern"], f"rules.toml {rule['id']}")

    pieces = []
    for raw in pieces_raw.get("piece", []):
        pa = raw.get("play_along")
        play = None
        if pa:
            answer = pa.get("answer")
            context = set(pa.get("context", []))
            if answer is not None and not context:
                context = {10, 10 - int(answer)}  # every game so far is a make-10 game
            play = PlayAlong(
                right=pa["right"],
                wrong=pa["wrong"],
                answer=answer,
                sequence=tuple(pa.get("sequence", ())),
                context=frozenset(context),
            )
        pieces.append(
            Piece(
                key=raw["key"],
                name=raw["name"],
                type=raw["type"],
                ai=bool(raw["ai"]),
                voice=raw.get("voice", "none"),
                caption_start=raw["caption_start"],
                first_comment=raw.get("first_comment"),
                ai_reply=raw.get("ai_reply"),
                play_along=play,
                pillar=raw.get("pillar") or pillar_for(raw["key"]),
                child=bool(raw.get("child", False)),
                ad_cleared=bool(raw.get("ad_cleared", False)),
            )
        )

    faqs = []
    for raw in replies.get("faq", []):
        faqs.append(
            Faq(
                id=raw["id"],
                pattern=_compile(raw["pattern"], f"replies.toml faq {raw['id']}"),
                building=raw.get("building"),
                open=raw.get("open"),
                open_founding=raw.get("open_founding"),
                open_by_stores=dict(raw.get("open_by_stores", {})),
                question_only=bool(raw.get("question_only", False)),
                pieces=tuple(raw.get("pieces", ())),
                needs_voice=raw["id"] == "robotic-voice" or bool(raw.get("needs_voice", False)),
                notify=raw.get("notify"),
                ahead_of_escalation=tuple(raw.get("ahead_of_escalation", ())),
                unless=_compile(raw["unless"], f"replies.toml faq {raw['id']} unless") if raw.get("unless") else None,
            )
        )

    def lines(section: str) -> Lines:
        raw = replies[section]
        return Lines(
            pattern=_compile(raw["pattern"], f"replies.toml {section}"),
            lines=tuple(raw["lines"]),
            max_length=int(raw.get("max_length", 120)),
        )

    return Knowledge(
        rules=rules,
        pieces=tuple(pieces),
        spam=_compile(replies["spam"]["pattern"], "replies.toml spam"),
        escalate=tuple(
            (e["reason"], _compile(e["pattern"], f"replies.toml escalate {e['reason']}"))
            for e in replies.get("escalate", [])
        ),
        tag_only=_compile(replies["tag_only"]["pattern"], "replies.toml tag_only"),
        ai_question=_compile(replies["ai_question"]["pattern"], "replies.toml ai_question"),
        faqs=tuple(faqs),
        praise=lines("praise"),
        played=lines("played"),
        holding={h["reason"]: h["text"] for h in replies.get("holding", [])},
    )
