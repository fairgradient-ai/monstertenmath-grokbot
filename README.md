# Monster Ten Social Bot

A Grok Bot that runs [@monstertenmath](https://www.instagram.com/monstertenmath/)'s conversations under the
launch pack's rules: it answers every comment and DM, finds the right creators and writes them Collab emails,
and learns how you answer. It asks you only about a child's health, legal, rivals, complaints and money.

Built from the launch pack in [fairgradient-ai/monstertenmath_social](https://github.com/fairgradient-ai/monstertenmath_social)
(`instagram/README.md` sections 6–7, `instagram/growth-plan.md` 6.2 and 6.5), in the shape of
[kapadias/pickletime-grokbot](https://github.com/kapadias/pickletime-grokbot). The design and the reasons are in
[`DESIGN.md`](DESIGN.md); setting it up is [`SETUP.md`](SETUP.md).

## What it does

| On…                                       | The bot                                                                 |
| ----------------------------------------- | ----------------------------------------------------------------------- |
| "3!" on Reel #3                           | Replies "Yes! 7 and 3 make 10." by itself                               |
| "Is this AI?"                             | Replies with that Reel's own AI line, by itself                         |
| "How much?", "Where's the link?"          | The pack's answer for today's phase (being built / open), by itself     |
| "Love this!"                              | A thank-you, by itself                                                  |
| "Does it work for a 3 year old?"          | Writes a reply in the brand voice and posts it once it passes the check |
| A DM: "How much is it?"                   | The same answers, in the DM thread (once Meta grants DM access)         |
| "I was charged twice", "teacher license?" | A holding line ("email us at info@…") at once, and tells you            |
| "My son has ADHD, would this help?"       | Drafts a careful reply and waits for your one-word OK                   |
| "Promote it on @…"                        | Lists it as spam; "hide 16" hides it                                    |

It also posts each new post's first comment for you to pin, compares followers with the pace line, finds and
scores creators by the growth plan's criteria, drafts Collab emails you send with one tap, and three times a
day sends a **brief**: fresh posts from those creators, each with a comment written for it, for you or a helper
to post.

It never follows, likes, comments or DMs on _other_ accounts: Instagram's terms forbid automating that, and it
gets new accounts blocked. [`DESIGN.md`](DESIGN.md), section 3, says what does that job instead. Every reply
and email passes the pack's 30-second check in code first ([`knowledge/rules.toml`](knowledge/rules.toml)).

## Say these

| Say                        | It does                                                   | Your tap? |
| -------------------------- | --------------------------------------------------------- | --------- |
| "check the comments"       | A sweep, then writes and posts the replies that pass      | no        |
| "inbox"                    | Everything waiting for you                                | no        |
| "send 14" / "send all"     | Posts the drafts that wait for your OK                    | **yes**   |
| "edit 14: …"               | Your words instead of the bot's (and it learns from them) | send: yes |
| "skip 14"                  | No reply                                                  | no        |
| "hide 16"                  | Hides a comment                                           | **yes**   |
| "find creators"            | Scouts, scores, shortlists, drafts Collab emails          | no        |
| "send all outreach"        | Emails the drafted Collab offers                          | **yes**   |
| "brief"                    | Fresh creator posts, each with a comment ready to post    | no        |
| "done 12 13"               | Marks brief comments as posted                            | no        |
| "examples"                 | What the bot has learned from your replies                | no        |
| "stats"                    | Followers against the pace line, and the newest posts     | no        |
| "we're open"               | Switches the answers to the launch phase (after the gate) | **yes**   |
| "go live" / "stop posting" | Replies post by themselves / nothing posts                | **yes**   |

## What protects you

- **Rehearsal first.** It starts by posting nothing and showing what it would say.
- **The check in code.** Outcome promises, "test" or "screening", countdowns, hashtags, rivals, links before
  launch, half the trial terms, a store the app isn't in: any of these and nothing is posted.
- **Your tap where it matters.** Sensitive replies, Collab emails (they offer money), hiding, the phase and the
  mode go through Grok's Ask-first cards ([`routines/autoreview.txt`](routines/autoreview.txt)), and the
  engine refuses them without it.
- **Once only.** A SQLite ledger means a comment or DM is answered at most once, even when a sweep and a send
  overlap or Instagram times out.
- **Caps.** One canned reply per person per post a day, 20 a sweep, 60 posts a day without your tap, 10
  outreach emails a day. A creator who says no is never written to again.
- **Secrets** stay on the secret card and are never printed.

## Layout

| Path                          | What                                                                      |
| ----------------------------- | ------------------------------------------------------------------------- |
| `agents/`                     | The Grok Bot's profile and system prompt                                  |
| `skills/`                     | Setup, day-to-day operations, and the brand voice                         |
| `routines/`                   | When it runs (`manifest.toml`) and what needs your tap (`autoreview.txt`) |
| `knowledge/`                  | The pack as data: the rules, the replies, the 15 pieces, the Collab email |
| `src/monsterbot/`             | The engine: Python 3.11+, standard library only                           |
| `scripts/`                    | `run.sh` (the only entry point), `install.sh`, `env.sh`, `sync_social.py` |
| `config/config.template.toml` | The desk's config: account, caps, DMs, scout, outreach, pace line         |
| `tests/`                      | 137 offline tests against a fake Instagram, Graph and mailbox             |

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
