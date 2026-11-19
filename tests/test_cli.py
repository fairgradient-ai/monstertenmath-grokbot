"""The commands as the Grok Bot runs them, against the fake Instagram."""

import io
import shutil

import pytest

from monsterbot import cli
from tests.conftest import ROOT

FIXTURE = ROOT / "src" / "monsterbot" / "fixtures" / "fake_instagram.json"


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    desk = tmp_path / "desk"
    desk.mkdir()
    shutil.copy(ROOT / "config" / "config.template.toml", desk / "config.toml")
    monkeypatch.setenv("MT_DESK", str(desk))
    monkeypatch.setenv("MT_CHANNEL", f"fake:{FIXTURE}")
    monkeypatch.setenv("MT_NOW", "2026-11-20T02:00:00+00:00")
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)

    def go(*args, stdin=None):
        if stdin is not None:
            monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        code = cli.main(list(args))
        return code, capsys.readouterr().out

    return go


def item_number(out, author):
    line = next(line for line in out.splitlines() if f"@{author}:" in line)
    return line.split("[", 1)[1].split("]", 1)[0]


def test_rehearsal_day_one(run):
    code, out = run("sweep")
    assert code == 0
    assert out.startswith("SWEEP · REHEARSAL · building")
    assert "Would reply (rehearsal, nothing posted):" in out
    assert "For you (I won't answer these):" in out


def test_draft_from_heredoc_keeps_dollar_signs_and_quotes(run):
    _, out = run("sweep")
    n = item_number(out, "mo_asks")
    text = (
        "Our lessons are made for 4 to 6. If you start the free week later, you add a card at signup and "
        "nothing is charged that day. We remind you on day 5, you can cancel in 2 taps, and after the 7 days "
        "it's $79.99 a year or $12.99 a month.\n"
    )
    code, out = run("draft", n, stdin=text)
    assert code == 0, out
    assert "passes the check" in out and "$79.99" in out


def test_send_needs_the_tap_and_rehearsal_posts_nothing(run, tmp_path):
    _, out = run("sweep")
    n = item_number(out, "mo_asks")
    run("draft", n, "--text", "Our lessons are made for 4 to 6.")
    code, out = run("send", n)
    assert code == 1 and out.startswith("REFUSED")
    code, out = run("send", n, "--owner-tapped")
    assert code == 0 and out.startswith("REHEARSAL")
    assert not (tmp_path / "desk" / "state" / "fake-outbox.json").exists()


def test_live_send(run, tmp_path):
    run("go-live", "--owner-tapped")
    _, out = run("sweep")
    assert "Replied:" in out
    _, inbox = run("inbox")
    n = item_number(inbox, "mo_asks")
    run("draft", n, "--text", "Our lessons are made for 4 to 6.")
    code, out = run("send", "all", "--owner-tapped")
    assert code == 0 and out.startswith(f"SENT [{n}]")
    assert "Our lessons are made for 4 to 6." in (tmp_path / "desk" / "state" / "fake-outbox.json").read_text()


def test_mode_and_phase_need_the_tap(run):
    assert run("go-live")[0] == 1
    assert run("phase", "open")[0] == 1
    code, out = run("phase", "open", "--owner-tapped")
    assert code == 0 and out.startswith("PHASE: open")
    assert run("phase")[1].strip() == "PHASE: open"


def test_failing_draft_exit_code(run):
    _, out = run("sweep")
    n = item_number(out, "mo_asks")
    code, out = run("draft", n, "--text", "Sign up now! Link in bio #earlymath")
    assert code == 1 and "FAILS the check" in out


def test_unknown_item(run):
    code, out = run("send", "999", "--owner-tapped")
    assert code == 1 and "no item [999]" in out


def test_doctor_full_against_the_fake(run):
    code, out = run("doctor", "--full")
    assert code == 0, out
    assert out.splitlines()[0] in ("DOCTOR: PASS", "DOCTOR: WARN")
    assert "fake sweep (open, live)" in out
