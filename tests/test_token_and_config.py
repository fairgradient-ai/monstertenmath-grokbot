from datetime import UTC, datetime

import pytest

from monsterbot.config import parse_config
from monsterbot.desk import Desk
from monsterbot.errors import ConfigError
from monsterbot.ledger import Ledger
from monsterbot.token import expiry, load_token, save_refreshed

NOW = datetime(2026, 11, 20, tzinfo=UTC)


@pytest.fixture
def desk_ledger(tmp_path):
    desk = Desk(tmp_path)
    desk.ensure()
    ledger = Ledger(desk.db_path)
    yield desk, ledger
    ledger.close()


def test_card_then_refreshed_then_new_card(desk_ledger, monkeypatch):
    desk, ledger = desk_ledger
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    assert load_token(desk, ledger) == (None, "none")

    monkeypatch.setenv("IG_ACCESS_TOKEN", "card-1")
    assert load_token(desk, ledger) == ("card-1", "secret card")

    save_refreshed(desk, ledger, "refreshed-1", 5184000, NOW)
    assert load_token(desk, ledger) == ("refreshed-1", "refreshed (desk)")
    assert desk.secrets_file.stat().st_mode & 0o777 == 0o600
    assert expiry(ledger).date().isoformat() == "2027-01-19"

    monkeypatch.setenv("IG_ACCESS_TOKEN", "card-2")  # the owner pasted a new token: it wins
    assert load_token(desk, ledger) == ("card-2", "secret card")


def test_mode_and_phase_default_safe(tmp_path):
    desk = Desk(tmp_path)
    assert (desk.mode(), desk.phase()) == ("rehearsal", "building")
    desk.ensure()
    (desk.state / "mode").write_text("LIVE!!\n")
    assert desk.mode() == "rehearsal"  # anything unexpected reads as rehearsal
    desk.set_mode("live", NOW)
    desk.set_phase("open", NOW)
    assert (desk.mode(), desk.phase()) == ("live", "open")
    assert "phase building -> open" in (desk.state / "changes.log").read_text()


def test_config_rejects_unknown_keys_and_bad_values():
    assert parse_config({"stores": ["app_store"]}).stores == ("app_store",)
    for bad in (
        {"engage": {"max_auto_reply": 3}},
        {"stores": ["ios"]},
        {"account": {"timezone": "Mars/Base"}},
        {"engage": {"thanks": "yes"}},
        {"whatever": 1},
    ):
        with pytest.raises(ConfigError):
            parse_config(bad)
