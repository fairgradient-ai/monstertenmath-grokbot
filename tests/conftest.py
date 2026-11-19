from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import pytest

from monsterbot.channels.fake import FakeInstagram
from monsterbot.config import Config
from monsterbot.desk import Desk
from monsterbot.engine import Engine
from monsterbot.knowledge import load_knowledge
from monsterbot.ledger import Ledger

NOW = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)  # 9 pm Eastern on Day 1
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def kn():
    return load_knowledge(ROOT / "knowledge")


@pytest.fixture
def fixture_data():
    path = resources.files("monsterbot").joinpath("fixtures/fake_instagram.json")
    return json.loads(path.read_text())


class Clock:
    def __init__(self, now: datetime = NOW):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def make_engine(tmp_path, kn, fixture_data):
    made = []

    def make(phase="building", mode="rehearsal", cfg=None, data=None, clock=None):
        desk = Desk(tmp_path / f"desk{len(made)}")
        desk.ensure()
        desk.set_phase(phase, NOW)
        desk.set_mode(mode, NOW)
        fake = FakeInstagram(copy.deepcopy(data or fixture_data))
        ledger = Ledger(desk.db_path)
        engine = Engine(cfg or Config(), desk, kn, fake, ledger, now=clock or Clock())
        made.append(ledger)
        return engine, fake

    yield make
    for ledger in made:
        ledger.close()


def item_by_external(engine, external_id):
    return engine.ledger.by_external("instagram", external_id)
