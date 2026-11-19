# Design: the Monster Ten social bot

A Grok Bot that runs @monstertenmath's conversations under the launch pack's rules: every comment on our posts,
every DM, and finding and emailing creators for Collabs. It learns how the owner answers, and asks the owner
only for what is theirs to decide. Instagram first; the engine is built so a second channel slots in later
(section 12).

It follows the shape of [kapadias/pickletime-grokbot](https://github.com/kapadias/pickletime-grokbot): a
deterministic engine behind one `run.sh`, run by a Grok Bot with a narrow persona, skills, routines and
Auto-review rules. The model writes and judges; the code decides what may be posted and keeps the record.

## 1. Who does what

| Who                                | What                                                                                                                                                                                                                                                                                                                                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **The bot, by itself** (live mode) | Answers every comment and DM: the pack's own answers where it has one (guesses, "Is this AI?", price, link, ages, praise), and a reply the Grok Bot writes for everything else, posted once it passes the brand check. Posts each new post's first comment. Answers billing and business messages with a holding line ("email us"). Finds and scores creators. Drafts Collab emails. |
| **The bot asks, you tap once**     | Replies about a child's health or development, legal, rivals and complaints (the bot drafts, you say "send 13" or "edit 13: …"). Collab emails, because they offer money ("send all outreach" sends a batch). Hiding a comment. Going live, and the launch-day phase.                                                                                                                |
| **Nobody: not allowed**            | The bot itself following, liking, commenting or DMing on _other_ accounts. Instagram's terms forbid automating it, the official API can't do it, and driving a logged-in browser to fake it gets new accounts action-blocked or disabled. Section 3 says what replaces it. |
| **A person, from the brief**       | Comments on creators' posts. Three times a day the bot picks fresh posts from the shortlisted creators and writes a comment for each; you or a helper posts them by hand from the list (section 9a). |
| **Never**                          | Posting anything that fails the 30-second check; naming a rival; a link or "link in bio" before launch; half the trial terms; claiming an AI-made Reel is filmed; writing to a creator who said no.                                                                                                                                                                                  |

## 2. How it fits together

```text
 Owner (phone)                Grok Bot computer (/workspace)                                    Meta, email
 ─────────────                ──────────────────────────────                                    ───────────
 chat: "send all outreach"    Grok Bot ──► bash run.sh <command> ──► engine (Python, stdlib)
 one-tap approval cards  ◄──  (persona,     │                         ├─ triage    replies.toml, pieces.toml
 notifications                 skills,      │                         ├─ policy    rules.toml = the 30-second check
                               routines,    │                         ├─ ledger    SQLite in /workspace/monsterten-desk
                               Auto-review) │                         ├─ instagram.py ──► graph.instagram.com (comments, DMs)
                                            │                         ├─ facebook.py  ──► graph.facebook.com (creator profiles)
                                            │                         └─ email.py     ──► SMTP (Collab emails)
                                            └── secret card: IG_ACCESS_TOKEN, FB_ACCESS_TOKEN, SMTP_USER, SMTP_PASSWORD
 monstertenmath_social (main) ──► knowledge/ is written from the pack; scripts/sync_social.py checks it
```

- **The engine** (`src/monsterbot/`) is plain Python 3.11+ with no packages, because the Grok Bot computer keeps
  `/workspace` but not installed packages. Commands: `sweep`, `reply`, `draft`, `send`, `inbox`, `discard`,
  `hide`, `examples`, `scout`, `creators`, `outreach`, `stats`, `status`, `doctor`, `phase`, `go-live`,
  `rehearse`, `token`.
- **The knowledge** (`knowledge/*.toml`) is the pack turned into data: the rules from section 6, the replies
  from section 7 and growth plan 6.2, one entry per piece in `schedule.json`, the holding lines, and the Collab
  email from growth plan 6.5. Changes go by pull request, like the pack.
- **The Grok Bot** runs the engine, writes the replies and the personal lines of emails, judges creator fit,
  and keeps the owner posted. Persona in `agents/`, skills in `skills/`, schedule in `routines/manifest.toml`,
  approvals in `routines/autoreview.txt`.

## 3. Why the bot doesn't comment on other accounts, and what does that job instead

The growth plan's commenting and following (6.3, 6.4) were there to put the Monster in front of parents who
follow parent and teacher creators. Automating that on the owner's behalf is the one thing this design refuses:

- Instagram's terms and Meta's spam policy forbid automated likes, follows and comments on other accounts, and
  the official API has no way to do them. The only route is a scripted, logged-in browser that hides from
  Instagram's bot detection.
- Meta detects that pattern. The usual result is an action block, then restrictions, and for a new account a
  real chance of being disabled: the account the launch ads and the creators send people to.

What does the job instead, all within the rules:

| Instead of…                    | The bot…                                                                                                                                                                            |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Commenting on creators' posts  | Finds the creators those comments were aimed at, scores them, writes them a Collab email you approve with one tap. A creator's Reel reaches their whole audience, with their trust. |
| Following parents and teachers | Answers every parent who comments or DMs within the hour, so the people already interested stay and share.                                                                          |
| Hunting for accounts by hand   | Reads the top posts under the plan's hashtags, the accounts tagged in them, and our own commenters who run creator accounts.                                                        |
| Writing comments on creators' posts | Writes them for you three times a day (the brief, section 9a). A person posts them, so the account stays safe; finding the posts and writing the comments is the bot's job. |

## 4. What pickletime-grokbot taught, and what changed

| Kept                                                                            | Changed, and why                                                                                                                                                                         |
| ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| One entry point (`run.sh`), output posted verbatim, a verdict on the first line | The model writes here (replies, email lines), so the brand check runs in code on every word before it posts, and anything sensitive stops at the owner.                                  |
| Rehearsal by default; risky commands need the owner's tap (Ask-first cards)     | The gate is in the code too: `send`, `hide`, `outreach send`, `phase`, `go-live` refuse without `--owner-tapped`. A routine never runs one, because an unattended approval card expires. |
| Install under `/workspace`; secrets only from the card; doctor with a fake site | The JSON ledger became SQLite with transactions and a lock, so a routine and a "sweep now" can't both answer one comment (pickletime's JSON ledger could race there).                    |
| Idempotency per target; an unconfirmed outcome is recorded, not retried blind   | A reply that times out is "unverified": the next sweep looks for it on Instagram before anything is retried.                                                                             |
| Routines fire early because they start 10–37 minutes late                       | Nothing is time-critical: each sweep picks up everything since the last. Sweeps sit around posting times so the first hour is covered.                                                   |

## 5. Meta's APIs: what each part uses

| Need                                 | API                                                 | Permission / feature                                          | Access                                                                                                              |
| ------------------------------------ | --------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Our posts, follower count            | Instagram Login: `GET /me`, `/me/media`             | `instagram_business_basic`                                    | Standard: no App Review for our own account                                                                         |
| Comments on our posts; reply; hide   | `GET /{media}/comments`, `POST /{comment}/replies`  | `instagram_business_manage_comments`                          | Standard                                                                                                            |
| First comment on our post            | `POST /{media}/comments`                            | same                                                          | Standard                                                                                                            |
| **DMs**: read threads, reply         | `GET /me/conversations`, `POST /me/messages`        | `instagram_business_manage_messages`                          | **Advanced Access: App Review and Business Verification** (only people with a role on our app reach us before that) |
| **Creator profiles**                 | Facebook Login: `business_discovery` on our IG user | `instagram_basic`, `pages_read_engagement`, `pages_show_list` | Facebook Page linked to the account; check the reference for review                                                 |
| **Top posts under a hashtag**        | `ig_hashtag_search`, `/{hashtag}/top_media`         | **Instagram Public Content Access** feature                   | App Review; 30 different hashtags in a rolling 7 days                                                               |
| Keep the Instagram token alive       | `GET /refresh_access_token`                         |                                                               | every Sunday                                                                                                        |
| Pin, follow, like, comment elsewhere | none                                                |                                                               |                                                                                                                     |

- **Polling, not webhooks.** Webhooks need a public server and an app in Live mode, and the Grok Bot computer
  sleeps when nobody's connected. A sweep makes about 15 calls; 5 sweeps a day are far inside Meta's limits. A
  rate-limit answer stops the sweep at once.
- **DMs inside 24 hours.** Meta allows a business reply within 24 hours of the person's last message; the bot
  uses 23 to be safe. Older threads go to the owner, who can answer in the app.
- **Hashtag posts don't name their author.** The scout takes candidates from the accounts tagged in them, from
  seeds, and from our own commenters, then reads each profile with Business Discovery (business and creator
  accounts only; personal accounts are marked unreachable).
- These details come from Meta's docs and 2025–26 developer write-ups, not from a test on the account. The DM
  and scout code is tested against fakes; check it against the live API once access is granted.

## 6. How a comment or DM is handled

| Order | Kind                 | Example                                  | What happens                                                                                                                                        |
| ----- | -------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | Our own              | the pinned first comment                 | Nothing. A reply the owner typed in the app is kept as an example                                                                                   |
| 2     | Spam                 | "Promote it on @…"                       | Listed for the owner; "hide 16" hides it                                                                                                            |
| 3     | Escalation           | "I was charged twice", "my son has ADHD" | Billing and business: a holding line ("email us") at once, and the owner is told. Health, legal, rivals, complaints: the bot drafts, the owner taps |
| 4     | Friends tagging      | "@bestie we need this"                   | Nothing                                                                                                                                             |
| 5     | "Is this AI?"        | on Reel #3                               | That Reel's own line (growth plan 6.2)                                                                                                              |
| 6     | A guess              | "3!" on #3, "4 5 3 6" on #15             | The script's answer, never "No"                                                                                                                     |
| 7     | A known question     | "How much?", "Where's the link?"         | The pack's reply for today's phase                                                                                                                  |
| 8     | Praise / "we played" | "Love this!", "my daughter shouted 3!"   | A thank-you or a question back, taking turns so no line repeats on a post                                                                           |
| 9     | Anything else        | "Does this work for a 3 year old?"       | The Grok Bot writes a reply; it posts by itself if it passes the check                                                                              |

DMs go through the same sorting, one item per thread (the person's latest unanswered messages together). A
newer message replaces the older item; a thread the owner answered in the app needs nothing.

Safety valves on everything posted without a tap: one canned reply per person per post a day, 20 per sweep,
60 a day in all (canned and written), nothing older than 72 hours (it becomes a draft), and anything that fails
the check is held.

## 7. The 30-second check, in code

`knowledge/rules.toml` is section 6 of the pack, rule by rule; `policy.py` applies it to every reply, every
holding line and every Collab email:

- No outcome promises; the check is never a test, quiz or screening; no streaks, guilt or countdowns; never
  the Monster's retired name; no rival named or tagged; no hashtags; no @mention but the person answered.
- Trial terms whole or not at all, and any dollar amount must be a real price. (A Collab email's fee is not a
  product price, so emails are checked as category "email".)
- **Building phase:** no link, "link in bio", "sign up", "download" or launch day. **Open phase:** no "being
  built"; the only link is monstertenmath.com/insta; a store is named only once the app is in it.
- AI honesty; never ask for a child's photo; a price that lost its `$` to the shell is caught.

CI fails if any canned text in `knowledge/` breaks a rule. The first smoke run caught one: the pack's own "you
add a card at signup" tripped the "sign up" rule.

## 8. Learning from the owner

The bot keeps three kinds of example, newest first (`run.sh examples`):

- **replies the owner typed in the app**, on comments or DMs (found by the sweep: ours on Instagram, but not
  posted by the bot). The comment they answered needs nothing more;
- **edits**: "edit 14: …" saves the owner's words next to what the bot had written;
- **approvals**: a bot draft the owner sent unchanged.

The Grok Bot reads them before writing (the voice skill says so) and matches the owner's length, warmth and
phrasing. When the same kind of question keeps getting the same answer, it's worth adding to
`knowledge/replies.toml` as a canned reply, in a pull request.

## 9. Finding creators and writing to them

- **Score** (0–100, `scout.py`), from the growth plan: followers (10,000–40,000 is the Collab sweet spot,
  5,000–200,000 in range), engagement on the last 12 posts, posting in the last week, words about young
  children's learning in the bio and captions. A rival brand anywhere scores 0 and is rejected; giveaway
  accounts lose points; no email in the bio means no outreach.
- **Judge**: the Grok Bot reads the top candidates' bios and captions and marks each shortlist or reject with a
  note. You can add any username for a look ("look at @name").
- **Write**: the email is the growth plan's 6.5 template; the Grok Bot writes only the personal line about one
  of their real posts. Every email carries the sender, a postal address and "reply no thanks and we won't write
  again" (US CAN-SPAM). A creator who declines is never written to again.
- **Send**: on your tap, at most 10 a day, through your own mailbox (SMTP with an app password). Replies come
  back to your inbox; tell the bot "@name booked" or "@name said no".

## 9a. The brief: comments a person posts

Three times a day (08:40, 13:10, 19:10 Eastern) the bot:

1. reads the newest posts of the shortlisted creators (and new ones scoring 60+) with Business Discovery;
2. keeps posts from the last 24 hours (early comments travel furthest), one per creator a day, never one it has
   briefed before, never a giveaway or a post naming a rival, at most 8 a brief and 30 a day (growth plan 6.3);
3. writes one comment for each, held to 6.3's rules in code: one or two sentences about their post, never the
   app, a link, a price, "follow us", a hashtag or an @mention, and never a comment it has used before;
4. posts the list in chat (and emails it to a helper if `[brief] email_to` is set): a link and a comment each.

A person opens each link, pastes, posts, and says "done 12 13". The brief only reads and writes a list; it never
touches Instagram as the account.

## 10. State and failure

- **The desk** (`/workspace/monsterten-desk`): `config.toml`, `state/` (mode, phase, `monsterbot.db`,
  `changes.log`), `secrets/instagram.env` (the refreshed token, 0600). The checkout is never written to.
- **The ledger** (SQLite): every comment and DM seen and what happened to it, every action, the examples, the
  creators and the hashtag budget. A reply goes out at most once: `sending` is set inside a transaction before
  the post, `replied` with Meta's id after it.
- **Exit codes**: 0 done, 1 refused or held, 2 config, 3 Meta, email or the computer.

## 11. Routines and approvals

| Routine            | When (Eastern)   | Does                                                                         |
| ------------------ | ---------------- | ---------------------------------------------------------------------------- |
| `sweep-morning`    | 08:05 daily      | Overnight comments and DMs; writes and posts the replies                     |
| `sweep-midday`     | 12:50            | Day 1's 12:30 post                                                           |
| `sweep-afternoon`  | 17:50            | Day 1's 17:30 post                                                           |
| `sweep-first-hour` | 20:45            | The first hour after the 8:30 pm post (growth plan 6.2)                      |
| `sweep-evening`    | 21:30            | The rest of the first hour                                                   |
| `stats-nightly`    | 22:05 (optional) | Followers against the pace line                                              |
| `scout-weekly`     | Mon, Thu 10:05   | New creators, shortlisted, emails drafted for one tap (once scout is set up) |
| `brief-morning`, `brief-midday`, `brief-evening` | 08:40, 13:10, 19:10 | Fresh creator posts with a comment for each, for a person to post |
| `health`           | Sun 18:05        | `doctor`, then a fresh 60 days on the token                                  |

## 12. Testing

132 offline tests: the rules, the sorting, whole sweeps against a fake Instagram (comments and DMs, rehearsal
and live, both phases), written replies, holding lines, learning, double-reply and timeout cases, scoring and
the scout and the brief against a fake Graph, outreach against a fake mailbox, the HTTP clients' requests and errors, the
CLI as the Grok Bot calls it, and checks that the routines, Auto-review rules, persona and skills agree with
the engine. CI runs them on Python 3.11 and 3.13, then installs into a temporary desk and runs `doctor --full`.

## 13. Roadmap

| Version | Adds                                                                                                                                         | Needs                                            |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| 0.1     | Comments on our posts, canned replies, first comments, the check in code, stats                                                              | A Meta app and token                             |
| **0.2** | **Written replies post themselves; holding lines; DMs; learning from the owner; creator scout; Collab emails on one tap**                    | App Review for DMs and hashtags; an app password |
| **0.3** | **The brief, three times a day: fresh posts from shortlisted creators, a comment written for each, posted by a person** | The scout's token |
| 0.4     | Reading creators' email replies (IMAP) and drafting the answer; follow-ups after 5 days, once; the creator brief and parent release attached | The same mailbox                                 |
| 0.5     | Replies where we're @mentioned on other people's posts (allowed by the API), and tagged-media thank-yous                                     | Facebook Login token                             |
| 0.6     | Per-post insights and the growth plan's nightly money rules for the ads, through the Marketing API, with a tap above a spend line            | `ads_management`                                 |
| 0.7     | A second channel through the same `Channel` interface: Facebook Page first (same Meta app, the parents' age group), then Threads or YouTube  | A channel module                                 |

## 14. Assumptions and open questions

- **Grok Bot behaviour** (routines, secret cards, Auto-review, approval cards expiring after about 30 minutes,
  `/workspace` persisting) comes from pickletime-grokbot's docs and 2026 write-ups. Check the screens at setup.
- **App Review** for messages and hashtag search takes days to weeks and needs a business verification, a
  privacy policy URL and a screencast. Start it now: until it passes, DMs from the public can't be read by any
  app of ours (Meta Business Suite's own automated replies can cover the commonest questions meanwhile).
- **Text written for the bot** (marked `source = "bot"`): thank-you lines, "we played" questions, holding
  lines, answer keys and first comments for #6, #12 and #15's "all right". Read them once before going live.
- **Escalation words** are broad on purpose: a false alarm costs a glance; a missed one could cost a family's
  trust.
- **Outreach is US-style** (CAN-SPAM footer and postal address). For creators outside the US, other rules can
  apply; the scout can't reliably tell where a creator lives, so the Grok Bot judges from the profile.
- **The bot doesn't pin**: the API can't. The sweep tells you when there's a first comment to pin.
