#!/usr/bin/env python3
"""sync_social.py SOCIAL_CHECKOUT : compare knowledge/pieces.toml with the social repo's schedule.

Reads monstertenmath_social/instagram/schedule.json (the approved Buffer calendar on main) and checks that
every scheduled piece is in pieces.toml, that its caption still starts with `caption_start`, and that the AI
flag agrees. It changes nothing: fix pieces.toml by hand, in a pull request. Exit 1 if anything differs.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    schedule = json.loads((Path(argv[1]) / "instagram" / "schedule.json").read_text(encoding="utf-8"))
    pieces = {p["key"]: p for p in tomllib.loads((HERE.parent / "knowledge" / "pieces.toml").read_text())["piece"]}
    problems = 0
    for entry in schedule:
        key = entry["name"].split()[0]
        piece = pieces.pop(key, None)
        if piece is None:
            print(f"MISSING  {entry['name']}: add it to knowledge/pieces.toml")
            problems += 1
            continue
        if not norm(entry["text"]).startswith(norm(piece["caption_start"])):
            print(
                f"CHANGED  {key}: the caption no longer starts with {piece['caption_start']!r}; "
                f"it starts {norm(entry['text'])[:50]!r}"
            )
            problems += 1
        if bool(entry.get("ai")) != bool(piece["ai"]):
            print(f"CHANGED  {key}: ai is {entry.get('ai')} in the schedule, {piece['ai']} in pieces.toml")
            problems += 1
    for key in pieces:
        print(f"EXTRA    {key}: in pieces.toml but not in the schedule (fine if it was posted by hand)")
    print("OK: pieces.toml matches the schedule" if not problems else f"{problems} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
