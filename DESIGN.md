# Design: the Monster Ten social bot

A Grok Bot that looks after @monstertenmath's comments under the launch pack's rules, so every parent gets an
answer in the first hour, and the owner's time goes only to the comments that need a person. Instagram first;
the engine is built so a second channel slots in later (section 11).

It follows the shape of [kapadias/pickletime-grokbot](https://github.com/kapadias/pickletime-grokbot): a
deterministic engine behind one `run.sh`, run by a Grok Bot with a narrow persona, skills, routines and
Auto-review rules. The model writes and talks; the code decides what may be posted and keeps the record.

## 1. What it does, and what it never does

| Who                                | What                                                                                                                                                                                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **The bot, by itself** (live mode) | Reads every comment on our newest posts. Answers the ones the pack already has an answer for: play-along guesses, "Is this AI?", the FAQ (price, link, ages, iPhone or Android…), short praise. Posts each new post's first comment. |
| **The bot drafts, you tap "send"** | Every other real comment or question. The Grok Bot writes the reply in the brand voice; the engine checks it; you send it from chat ("send 14", "send all").                                                                         |
| **You, and only you**              | Money (refunds, charges, cancelling), a child's health or development, legal, business and partnerships, rivals, complaints, spam. The bot lists them and never answers.                                                             |
| **You, by hand, as now**           | Following, liking, commenting on other accounts, DMs, Collabs, pinning. Instagram's terms and the growth plan (6.7) forbid automating these, and the API can't do them anyway.                                                       |
| **Never**                          | Posting anything that fails the 30-second check; naming a rival; a link or "link in bio" before launch; half the trial terms; claiming an AI-made Reel is filmed.                                                                    |

## 2. How it fits together

```text
 Owner (phone)                     Grok Bot computer (/workspace)                         Meta
 ─────────────                     ──────────────────────────────                         ────
 chat: "send 14"  ──► Grok Bot ──► bash run.sh <command> ──► engine (Python, stdlib) ──► Instagram API
 approval cards   ◄── (persona,    │                          │                          (graph.instagram.com)
 notifications        skills,      │                          ├─ triage    (knowledge/replies.toml, pieces.toml)
                      routines,    │                          ├─ policy    (knowledge/rules.toml = the 30-second check)
                      Auto-review) │                          ├─ ledger    (SQLite in /workspace/monsterten-desk)
                                   │                          └─ channel   (instagram.py; fake.py for tests)
                                   └── secret card: IG_ACCESS_TOKEN
 monstertenmath_social (main) ──► knowledge/ is written from the pack; scripts/sync_social.py checks it
```

- **The engine** (`src/monsterbot/`) is plain Python 3.11+ with no packages, because the Grok Bot computer keeps
  `/workspace` but not installed packages. One command per job: `sweep`, `inbox`, `draft`, `send`, `discard`,
  `hide`, `status`, `stats`, `doctor`, `phase`, `go-live`, `rehearse`, `token`.
- **The knowledge** (`knowledge/*.toml`) is the pack turned into data: the rules from section 6, the replies from
  section 7 and growth plan 6.2, and one entry per piece in `schedule.json` (its caption opening, AI flag,
  answer key, first comment, "Is this AI?" line). Changes go by pull request, like the pack.
- **The Grok Bot** runs the engine and writes the replies the engine can't. Its persona has eight rules
  (`agents/`), its skills say how to run, write and set up (`skills/`), the routines say when
  (`routines/manifest.toml`), and Auto-review says which commands need your tap (`routines/autoreview.txt`).

## 3. What pickletime-grokbot taught, and what changed

| Kept                                                                                | Changed, and why                                                                                                                                                          |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| One entry point (`run.sh`), output posted verbatim, a verdict on the first line     | The model does write here (drafts), but it can only _save_ a draft. Posting a written reply is a separate command behind your tap.                                        |
| Rehearsal by default; going live and risky commands need your tap (Ask-first cards) | The gate is in the code too: `send`, `hide`, `phase`, `go-live` refuse without `--owner-tapped`, and every reply passes the policy check in code, not only in the prompt. |
| Install under `/workspace`; secrets only from the card; doctor with a fake site     | The JSON ledger became SQLite with transactions and a lock, so a routine and a "sweep now" can't both answer one comment (pickletime's JSON ledger could race there).     |
| Idempotency per target; an unconfirmed outcome is recorded, not retried blind       | A reply that times out is "unverified": the next sweep looks for it on Instagram before anything is retried, so a slow Meta never makes a double reply.                   |
| Routines fire early because they start 10–37 minutes late                           | Nothing here is time-critical: each sweep picks up everything since the last. Sweeps sit around posting times so the first hour is covered.                               |

## 4. Instagram: what the API allows

The bot uses Meta's official **Instagram API with Instagram Login** (`graph.instagram.com`), on our own
professional account.

| Need                                           | API                                      | Permission                           | Access                                                  |
| ---------------------------------------------- | ---------------------------------------- | ------------------------------------ | ------------------------------------------------------- |
| Our posts, follower count                      | `GET /me`, `GET /me/media`               | `instagram_business_basic`           | Standard, no App Review for our own account             |
| Comments and replies on our posts              | `GET /{media}/comments` (with `replies`) | `instagram_business_manage_comments` | Same                                                    |
| Reply under a comment                          | `POST /{comment}/replies`                | same                                 | Same                                                    |
| First comment on our post                      | `POST /{media}/comments`                 | same                                 | Same                                                    |
| Hide a comment                                 | `POST /{comment}?hide=true`              | same                                 | Same                                                    |
| Keep the token alive (60 days)                 | `GET /refresh_access_token`              |                                      |                                                         |
| DMs (later)                                    | Messaging API                            | `instagram_business_manage_messages` | **Advanced Access: App Review + Business Verification** |
| Post insights (later)                          | `GET /{media}/insights`                  | `instagram_business_manage_insights` | Standard                                                |
| Pin a comment, follow, like, comment elsewhere | not in the API                           |                                      |                                                         |

- **Polling, not webhooks.** Webhooks need a public server and an app in Live mode, and the Grok Bot computer
  sleeps when nobody's connected. A sweep reads the newest 12 posts and their comments: about 13 calls, 7
  times a day, far inside Meta's limits. A rate-limit answer stops the sweep at once; the next one carries on.
- **Replies attach to the top-level comment** (threads are one level deep), so answering a reply goes under its
  parent with an @mention.
- **The token** sits on the secret card. The Sunday routine refreshes it and keeps the new one in the desk
  (mode 0600); a new token pasted on the card always wins over the refreshed one.
- These details come from Meta's docs and 2025–26 developer write-ups, not from a test on the account. Check the
  permissions and access levels in the App Dashboard when you set it up (SETUP.md, section 2).

## 5. How a comment is handled

Each sweep sorts every new comment. The first match wins:

| Order | Kind                 | Example                                  | What happens                                                                |
| ----- | -------------------- | ---------------------------------------- | --------------------------------------------------------------------------- |
| 1     | Our own              | the pinned first comment                 | Nothing                                                                     |
| 2     | Spam                 | "Promote it on @…"                       | Listed for you to hide, delete or block (growth plan 6.2)                   |
| 3     | Escalation           | "I was charged twice", "my son has ADHD" | Listed for you, with the reason. Never answered by the bot                  |
| 4     | Friends tagging      | "@bestie we need this"                   | Nothing                                                                     |
| 5     | "Is this AI?"        | on Reel #3                               | That Reel's own line (growth plan 6.2). A post with no line comes to you    |
| 6     | A guess              | "3!" on #3, "4 5 3 6" on #15             | The script's answer: "Yes! 7 and 3 make 10." or "Let's check!…", never "No" |
| 7     | A known question     | "How much?", "Where's the link?"         | The pack's reply for today's phase (section 7)                              |
| 8     | Praise / "we played" | "Love this!", "my daughter shouted 3!"   | A thank-you or a question back, taking turns so no line repeats on a post   |
| 9     | Anything else        | "Does this work for a 3 year old?"       | The Grok Bot drafts a reply; you send it                                    |

Safety valves on the canned replies: at most one per person per post per day (a second comment goes to a draft),
20 per sweep and 60 a day (cautious for a new account), nothing older than 72 hours (it becomes a draft for you
to check), and any canned reply that fails the check goes to you instead. A reply under someone else's comment
is a conversation, so it's drafted only if it's a question or tags us.

## 6. The 30-second check, in code

`knowledge/rules.toml` is section 6 of the pack, rule by rule, and `policy.py` applies it to every reply,
canned or drafted:

- No outcome promises; the check is never a test, quiz or screening; no streaks, guilt or countdowns; never the
  Monster's retired name; no rival named or tagged; no hashtags; no @mention but the person we answer.
- Trial terms whole or not at all: a reply that mentions the free week or a price must carry the card, "nothing
  charged", day 5, "cancel in 2 taps" and $79.99 a year. Any dollar amount must be a real price.
- **Building phase:** no link, no "link in bio", "sign up", "download" or "available now", no launch day.
  **Open phase:** no "being built"; the only link is monstertenmath.com/insta; a store is named only if
  `stores` in the config says the app is in it (gate step 4).
- AI honesty: never "not AI", "filmed at home", "real family" or "word for word".
- A price that lost its `$` (the shell eats `$7` inside double quotes) is caught too; drafts are saved with a
  quoted heredoc so it can't happen.

CI fails if any canned reply in `knowledge/` breaks a rule, so the rules and the replies can't drift apart.
The first smoke run caught one: the pack's own "you add a card at signup" tripped the "sign up" rule.

## 7. Phase and mode

- **Mode** (`rehearsal` → `live`): rehearsal reads everything and posts nothing; it shows exactly what live
  would do. Going live is your tap after a day of rehearsal.
- **Phase** (`building` → `open`): which answers and rules apply. You flip it on launch day, once the gate has
  passed, by saying "we're open" (the same words that unlock the Buffer queue in the social repo). If launch
  slips, "back to building" flips it back. `doctor` warns if the bio link and the phase disagree.

## 8. State and failure

- **The desk** (`/workspace/monsterten-desk`): `config.toml`, `state/` (mode, phase, `monsterbot.db`,
  `changes.log`), `secrets/instagram.env` (the refreshed token, 0600). The checkout is never written to.
- **The ledger** (SQLite): every comment seen, its kind, what was planned, drafted and posted, and every
  action. Item numbers are what you type in chat. A comment is answered at most once: the row moves to
  `sending` inside a transaction before the post, and to `replied` with Instagram's id after it.
- **Exit codes**: 0 done, 1 refused or not done, 2 config, 3 Instagram or the computer. A dead token makes the
  sweep say `FAILED` on its first line, so the routine's message tells you.

## 9. Routines and approvals

| Routine            | When (Eastern)   | Does                                                         |
| ------------------ | ---------------- | ------------------------------------------------------------ |
| `sweep-morning`    | 08:05 daily      | Overnight comments; drafts the rest                          |
| `sweep-midday`     | 12:50            | Day 1's 12:30 post: first comment, first replies             |
| `sweep-afternoon`  | 17:50            | Day 1's 17:30 post                                           |
| `sweep-first-hour` | 20:45            | The first hour after the 8:30 pm post (growth plan 6.2)      |
| `sweep-evening`    | 21:30            | The rest of the first hour                                   |
| `stats-nightly`    | 22:05 (optional) | Followers against the pace line, for the 10 pm nightly check |
| `health`           | Sun 18:05        | `doctor`, then a fresh 60 days on the token                  |

No routine sends a written reply or changes mode or phase: an approval card in an unattended run expires, and
those are yours. Auto-review allows only the read-and-draft commands by themselves.

## 10. Testing

104 tests (`pytest`), all offline: the rules, the sorting, whole sweeps against a fake Instagram (rehearsal and
live, both phases), double-reply and timeout cases, the Instagram client's requests and errors, the CLI as the
Grok Bot calls it, and checks that the routines, Auto-review rules, persona and skills agree with the engine.
CI runs them on Python 3.11 and 3.13, then installs into a temporary desk and runs `doctor --full`.

## 11. Roadmap

| Version | Adds                                                                                                                                                                                                                                                                                                     | Needs                                                |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 0.1     | This: comments on our posts, canned replies, drafts, first comments, the check in code, stats against the pace line                                                                                                                                                                                      | A Meta app and token (no review)                     |
| 0.2     | Per-post insights in `stats` (reach, saves, shares, sends) and a nightly report in the growth plan's section 8 format; story-reply and mention counts                                                                                                                                                    | `instagram_business_manage_insights`                 |
| 0.3     | **DMs**: answer inbound DMs and story replies with the same tiers, inside Meta's 24-hour window; one private reply to a comment when someone asks for the link                                                                                                                                           | App Review + Business Verification (about 1–2 weeks) |
| 0.4     | **The growth brief**: each morning, recent posts from a watchlist of parent and teacher creators (the growth plan's 6.3 criteria) with a fresh draft comment for each, for you to post by hand. Never posted by the bot                                                                                  | Business Discovery (Facebook Login for Business)     |
| 0.5     | **A second channel** through the same `Channel` interface. Facebook Page first: the same Meta app, the parents' age group, and Reels can cross-post from Buffer. Then Threads (reply management API) or YouTube Shorts (comment threads API). TikTok depends on access to its Business API for comments. | A channel module and its knowledge entries           |
| later   | A cron or GitHub Actions mode outside Grok: sweeps with canned replies only, and drafts written through the xAI API (`api.x.ai`, OpenAI-compatible; model from config) waiting in `inbox`                                                                                                                | `XAI_API_KEY`, somewhere to run                      |

## 12. Assumptions and open questions

- **Grok Bot behaviour** (routines, secret cards, Auto-review, approval cards expiring after about 30 minutes,
  `/workspace` persisting) comes from pickletime-grokbot's docs and 2026 write-ups, not from xAI's own
  reference. Check the routine and Auto-review screens when you set it up.
- **Instagram API details** (section 4) should be checked in the App Dashboard: the permission names, that
  Standard Access covers our own account without review, and the Graph version in the config (v24.0).
- **Canned text written for the bot** (marked `source = "bot"` in knowledge/): the thank-you lines, the "we
  played" questions back, the answer keys and first comments for #6, #12 and #15's "all right". Read them once
  before going live.
- **Escalation words** are deliberately broad ("cancel", "charged", "struggled", "collab"): a false alarm costs you
  a glance; a missed one could cost a family's trust.
- **The bot doesn't pin**: the API can't. The sweep tells you when there's a first comment to pin.
- **Voice re-cuts**: when a Reel is re-cut to your voice, its `ai_reply` in pieces.toml changes to the pack's
  "That's my voice!" line, in a pull request.
