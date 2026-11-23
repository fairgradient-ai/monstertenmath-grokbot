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
        assert "--owner-tapped" not in r["prompt"], r["id"]  # an unattended run never taps for the owner
        commands = re.findall(re.escape(RUN) + r" ([\w-]+)", r["prompt"])
        assert commands, r["id"]
        for cmd in commands:
            assert cmd in {
                "sweep",
                "stats",
                "doctor",
                "token",
                "scout",
                "brief",
                "browser",
                "buffer",
                "insights",
                "ads",
                "pillars",
                "timing",
            }, (r["id"], cmd)
        assert "--owner-tapped" not in r["prompt"] and "send" not in commands
        assert "outreach send" not in r["prompt"]


def test_every_command_has_an_auto_review_rule():
    rules = (ROOT / "routines" / "autoreview.txt").read_text()
    allow, ask = rules.split("=== Ask first ===")
    for cmd in cli_commands():  # each rule names run.sh once, then its commands (rules are 1,000 characters at most)
        assert f"run.sh {cmd}" in rules or re.search(rf"(?<![\w-]){re.escape(cmd)}(?![\w-])", rules), cmd
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


def test_auto_review_rules_fit_grok():
    """Grok keeps only the first 1,000 characters of a custom rule and at most 20 of each kind (FAI-891): each
    rule is pasted on its own, so each must fit, and the session rule must cover every form a browser action takes."""
    text = (ROOT / "routines" / "autoreview.txt").read_text()
    allow, ask = text.split("=== Allow automatically ===")[1].split("=== Ask first ===")
    for section in (allow, ask):
        rules = [r.strip() for r in re.split(r"^--- .+ ---$", section, flags=re.M)[1:]]
        assert 1 <= len(rules) <= 20
        for rule in rules:
            assert 0 < len(rule) <= 1000, (len(rule), rule[:60])
    session = re.split(r"^--- .+ ---$", allow, flags=re.M)[1]
    for form in ("navigate", "click", "type", "browser automation", "Playwright", "subagent", "browser pick"):
        assert form in session, form
    assert "instagram.com" not in ask.split("graph.instagram.com")[0]  # no Ask first rule catches the session
