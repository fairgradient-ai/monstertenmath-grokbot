# Monster Ten Social Bot

A Grok Bot that looks after the comments on [@monstertenmath](https://www.instagram.com/monstertenmath/)
under the launch pack's rules. It answers what the pack already has an answer for, drafts the rest for you to
send, and hands you anything that touches money, a child, the law or a partnership.

Built from the launch pack in [fairgradient-ai/monstertenmath_social](https://github.com/fairgradient-ai/monstertenmath_social)
(`instagram/README.md` sections 6–7, `instagram/growth-plan.md` 6.2), in the shape of
[kapadias/pickletime-grokbot](https://github.com/kapadias/pickletime-grokbot). The design and the reasons are in
[`DESIGN.md`](DESIGN.md); setting it up is [`SETUP.md`](SETUP.md).

## What it does

| On a comment like…                       | The bot                                                             |
| ---------------------------------------- | ------------------------------------------------------------------- |
| "3!" on Reel #3                          | Replies "Yes! 7 and 3 make 10." by itself                           |
| "Is this AI?"                            | Replies with that Reel's own AI line, by itself                     |
| "How much?", "Where's the link?"         | The pack's answer for today's phase (being built / open), by itself |
| "Love this!"                             | A thank-you, by itself                                              |
| "Does it work for a 3 year old?"         | Drafts a reply in the brand voice. **You** say "send 14"            |
| "I was charged twice", "my son has ADHD" | Tells you. Never answers                                            |
| "Promote it on @…"                       | Lists it as spam for you to hide or block                           |

It also posts each new post's first comment ("How many is he hiding? Type your child's answer here.") for you
to pin, and compares the follower count with the growth plan's pace line.

It never follows, likes, comments on other accounts or DMs: Instagram's terms and the growth plan (6.7)
forbid it, and those stay yours. Every reply, canned or drafted, passes the pack's 30-second check in code
first ([`knowledge/rules.toml`](knowledge/rules.toml)).

## Say these

| Say                        | It does                                                   | Your tap? |
| -------------------------- | --------------------------------------------------------- | --------- |
| "check the comments"       | A sweep, then drafts for anything that needs writing      | no        |
| "inbox"                    | Everything waiting for you                                | no        |
| "send 14" / "send all"     | Posts drafts                                              | **yes**   |
| "edit 14: …"               | Replaces a draft with your words                          | no        |
| "skip 14"                  | No reply                                                  | no        |
| "hide 16"                  | Hides a comment                                           | **yes**   |
| "stats"                    | Followers against the pace line, and the newest posts     | no        |
| "we're open"               | Switches the answers to the launch phase (after the gate) | **yes**   |
| "go live" / "stop posting" | Canned replies post by themselves / nothing posts         | **yes**   |

## What protects you

- **Rehearsal first.** It starts by posting nothing and showing what it would say.
- **The check in code.** Outcome promises, "test" or "screening", countdowns, hashtags, rivals, links before
  launch, half the trial terms, a store the app isn't in: any of these and the reply isn't posted.
- **Your tap.** Written replies, hiding, the phase and the mode all go through Grok's Ask-first cards
  ([`routines/autoreview.txt`](routines/autoreview.txt)), and the engine refuses them without it.
- **Once only.** A SQLite ledger means a comment is answered at most once, even when a sweep and a send overlap
  or Instagram times out.
- **Caps.** One canned reply per person per post a day, 20 a sweep, 60 a day.
- **The token** stays on the secret card and is never printed.

## Layout

| Path                          | What                                                                      |
| ----------------------------- | ------------------------------------------------------------------------- |
| `agents/`                     | The Grok Bot's profile and system prompt                                  |
| `skills/`                     | Setup, day-to-day operations, and the brand voice                         |
| `routines/`                   | When it runs (`manifest.toml`) and what needs your tap (`autoreview.txt`) |
| `knowledge/`                  | The pack as data: the rules, the canned replies, the 15 scheduled pieces  |
| `src/monsterbot/`             | The engine: Python 3.11+, standard library only                           |
| `scripts/`                    | `run.sh` (the only entry point), `install.sh`, `env.sh`, `sync_social.py` |
| `config/config.template.toml` | The desk's config: account, caps, stores, pace line                       |
| `tests/`                      | 104 offline tests against a fake Instagram                                |

## Development

```bash
pip install pytest ruff
```

```bash
pytest -q && ruff check src tests scripts
```

```bash
MT_DESK=/tmp/desk MT_CHANNEL=fake:src/monsterbot/fixtures/fake_instagram.json bash scripts/install.sh
```

```bash
MT_DESK=/tmp/desk MT_CHANNEL=fake:src/monsterbot/fixtures/fake_instagram.json MT_NOW=2026-11-20T02:00:00+00:00 bash scripts/run.sh sweep
```

Changes arrive by pull request into `main`. A change to replies or rules is a change to what the account says:
keep it in step with the launch pack.
