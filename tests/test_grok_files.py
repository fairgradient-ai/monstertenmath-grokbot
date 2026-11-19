"""The Grok Bot's files agree with the engine: routines call real commands, every command has an approval
rule, the persona's skills exist, and the voice skill's examples pass the check."""

import re
import tomllib

from monsterbot.cli import build_parser
from monsterbot.policy import Context, check
from tests.conftest import ROOT

RUN = "bash /workspace/monstertenmath-grokbot/scripts/run.sh"


def cli_commands():
    sub = next(a for a in build_parser()._actions if a.dest == "cmd")
    return set(sub.choices)


def test_run_sh_lists_exactly_the_cli_commands():
    text = (ROOT / "scripts" / "run.sh").read_text()
    listed = set(re.search(r'^COMMANDS="([^"]+)"', text, re.M).group(1).split())
    assert listed == cli_commands()


def test_routines_call_only_safe_commands():
    manifest = tomllib.loads((ROOT / "routines" / "manifest.toml").read_text())
    assert manifest["schema_version"] == 1
    ids = [r["id"] for r in manifest["routine"]]
    assert len(ids) == len(set(ids))
    for r in manifest["routine"]:
        assert re.fullmatch(r"\d\d:\d\d", r["slot"]), r["id"]
        commands = re.findall(re.escape(RUN) + r" (\S+)", r["prompt"])
        assert commands, r["id"]
        for cmd in commands:
            assert cmd in {"sweep", "stats", "doctor", "token", "scout"}, (r["id"], cmd)
        assert "--owner-tapped" not in r["prompt"] and "send" not in commands
        assert "outreach send" not in r["prompt"]


def test_every_command_has_an_auto_review_rule():
    rules = (ROOT / "routines" / "autoreview.txt").read_text()
    allow, ask = rules.split("=== Ask first ===")
    for cmd in cli_commands():
        assert f"run.sh {cmd}" in rules or (cmd in ask), cmd
    for risky in ("send", "hide", "outreach send", "go-live", "rehearse", "--owner-tapped", "--force-lint"):
        assert risky in ask, risky
        assert f"run.sh {risky}" not in allow, risky


def test_persona_skills_exist_and_name_themselves():
    persona = (ROOT / "agents" / "monsterten-social-bot.md").read_text()
    front = persona.split("---")[1]
    skills = re.findall(r"^\s+-\s+(\S+)$", front, re.M)
    assert skills
    for name in skills:
        skill = (ROOT / "skills" / name / "SKILL.md").read_text()
        assert re.search(rf"^name: {re.escape(name)}$", skill, re.M), name


def test_operations_skill_uses_the_quoted_heredoc():
    ops = (ROOT / "skills" / "monsterten-social-operations" / "SKILL.md").read_text()
    assert "<<'MT_EOF'" in ops


def test_voice_examples_pass_the_check(kn):
    voice = (ROOT / "skills" / "monsterten-voice" / "SKILL.md").read_text().split("## Examples")[1]
    examples = re.findall(r'^\| "[^|]+\|\s+"([^|]+)"\s+\|$', voice, re.M)
    assert len(examples) >= 3
    for text in examples:
        assert check(text, Context("building"), kn.rules) == [], text
