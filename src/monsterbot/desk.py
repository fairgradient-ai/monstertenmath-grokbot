"""The desk: the bot's writable folder (/workspace/monsterten-desk on the Grok Bot computer).

It holds config.toml, the state (mode, phase, pricing, the ledger database) and the refreshed token. The release
checkout is never written to.
"""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .errors import Busy

MODES = ("rehearsal", "live")
PHASES = ("building", "open")
PRICINGS = ("standard", "founding")


class Desk:
    def __init__(self, root: Path):
        self.root = Path(root)

    @classmethod
    def from_env(cls) -> Desk:
        return cls(Path(os.environ.get("MT_DESK", "/workspace/monsterten-desk")))

    @property
    def config_path(self) -> Path:
        return self.root / "config.toml"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def db_path(self) -> Path:
        return self.state / "monsterbot.db"

    @property
    def secrets_file(self) -> Path:
        return self.root / "secrets" / "instagram.env"

    def ensure(self) -> None:
        self.state.mkdir(parents=True, exist_ok=True)

    # --- mode: rehearsal (nothing is posted) or live -------------------------------------------------
    def mode(self) -> str:
        return self._read_choice("mode", MODES, "rehearsal")

    def set_mode(self, mode: str, now: datetime) -> None:
        self._write_choice("mode", mode, MODES, "rehearsal", now)

    # --- phase: building (Days 1-4) or open (after the launch-day gate) -------------------------------
    def phase(self) -> str:
        return self._read_choice("phase", PHASES, "building")

    def set_phase(self, phase: str, now: datetime) -> None:
        self._write_choice("phase", phase, PHASES, "building", now)

    # --- pricing: standard, or the founding price (from launch day until the first 500 families) -------
    # Standard is the safe default: the bot quotes the founding price only once the owner has seen it on the
    # site's ticket (launch-day gate, step 3) and said "founding price on".
    def pricing(self) -> str:
        return self._read_choice("pricing", PRICINGS, "standard")

    def set_pricing(self, pricing: str, now: datetime) -> None:
        self._write_choice("pricing", pricing, PRICINGS, "standard", now)

    def phase_label(self) -> str:
        """The phase as the reports show it, with the founding price when it's on."""
        phase = self.phase()
        if self.pricing() != "founding":
            return phase
        return f"{phase} · founding price" + ("" if phase == "open" else " from launch")

    def _read_choice(self, name: str, choices: tuple[str, ...], default: str) -> str:
        try:
            value = (self.state / name).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return default
        # Anything unexpected reads as the safe default.
        return value if value in choices else default

    def _write_choice(self, name: str, value: str, choices: tuple[str, ...], default: str, now: datetime) -> None:
        if value not in choices:
            raise ValueError(f"{name} must be one of {choices}")
        self.ensure()
        old = self._read_choice(name, choices, default)
        tmp = self.state / f".{name}.tmp"
        tmp.write_text(value + "\n", encoding="utf-8")
        tmp.replace(self.state / name)
        with open(self.state / "changes.log", "a", encoding="utf-8") as log:
            log.write(f"{now.isoformat()} {name} {old} -> {value}\n")

    @contextmanager
    def lock(self, wait_seconds: float = 0) -> Iterator[None]:
        """One engine command at a time. A sweep doesn't wait (a routine and a "sweep now" can overlap);
        a send waits a little for a running sweep to finish."""
        self.ensure()
        with open(self.state / "engine.lock", "w") as fh:
            deadline = time.monotonic() + wait_seconds
            while True:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise Busy("BUSY: another bot command is running. Try again in a minute.") from None
                    time.sleep(0.5)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
