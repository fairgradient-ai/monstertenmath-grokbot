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

    @property
    def label(self) -> str:
        return f"{self.key} {self.name}"


@dataclass(frozen=True)
class Faq:
    id: str
    pattern: re.Pattern[str]
    building: str | None = None
    open: str | None = None
    open_by_stores: dict[str, str] = field(default_factory=dict)
    question_only: bool = False
    pieces: tuple[str, ...] = ()
    needs_voice: bool = False
    notify: str | None = None

    def text_for(self, phase: str, stores: tuple[str, ...]) -> str | None:
        if phase == "open" and self.open_by_stores:
            return self.open_by_stores.get("+".join(sorted(stores))) if stores else None
        return self.open if phase == "open" else self.building


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
        cap = _norm(caption)
        for piece in self.pieces:
            if cap.startswith(_norm(piece.caption_start)):
                return piece
        return None

    def piece(self, key: str | None) -> Piece | None:
        return next((p for p in self.pieces if p.key == key), None) if key else None

    def canned_texts(self) -> list[tuple[str, str, str, str | None]]:
        """Every text the bot may post without asking: (where, text, phase or "both", category)."""
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
                out.append((f"faq {f.id} open", f.open, "open", "faq"))
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
                open_by_stores=dict(raw.get("open_by_stores", {})),
                question_only=bool(raw.get("question_only", False)),
                pieces=tuple(raw.get("pieces", ())),
                needs_voice=raw["id"] == "robotic-voice" or bool(raw.get("needs_voice", False)),
                notify=raw.get("notify"),
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
