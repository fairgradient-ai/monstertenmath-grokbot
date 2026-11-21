---
name: monsterten-browser-engagement
description: How to run a browser session for @monstertenmath, liking, commenting and following in the Grok browser one step at a time with human pauses. Use when the owner says "engage S<n>", when a brief routine made a browser plan, or when a run.sh browser command answers. The engine plans, paces and counts; you click only what it hands out.
license: Proprietary
metadata:
  version: "1.0.0"
  category: social
---

# Engaging in the Grok browser

The owner decided that the Bot may like, comment and follow from @monstertenmath in the Grok browser, with
breaks like a person's (DESIGN.md section 3). It carries a real risk to the account, so the engine holds the
limits: caps per day and per session that ramp up over the first two weeks, quiet hours, a random wait between
steps, a 90-minute gap between sessions, and a 48-hour stop after any warning. Your job is to follow it exactly.

## A session

1. A brief routine runs `run.sh browser plan`. If it prints `PLAN S7 · …`, ask the owner to say "engage S7".
   The plan shows kinds and counts, never links or comment text.
2. The owner says "engage S7". Run `bash /workspace/monstertenmath-grokbot/scripts/run.sh browser start S7
   --owner-tapped` (the one Ask-first card for the whole session). If it's REFUSED (too soon after the last
   session, plan too old, quiet hours), post the line and stop. Say "engage S7" again at the time it gives.
3. Loop, without doing anything else in between:
   - `run.sh browser next S7`. It may take up to about two and a half minutes to answer: that is the break. If it
     answers `WAIT …`, run it again.
   - It prints one `STEP S7.<k>`: open exactly that link in the Grok browser, look at the post for the time it
     gives (scroll it, read the caption), then do only what it names: like it, or like it and post the
     comment **exactly as printed**, or follow that account. Never change the comment's words.
   - Report what you really did: `run.sh browser done S7 <k> --did like,comment` (or `--did like`,
     `--did follow`, `--did already-liked`). For step 0 (the check), `--ok`. If the post is gone, private or
     clearly not a fit, `--skip "<why>"` and do nothing on it.
   - The last step is `verify`: open Your activity → Comments, count today's comments on other accounts'
     posts, and run `run.sh browser verify S7 --others <n>`.
   - Stop when it says `DONE`, `ENDED` or `MISMATCH`, and post that line.
4. Post a one-line summary: `run.sh browser status S7`.

## Stop signs: stop at once

Any of these: "Try again later", "We restrict certain activity", "Action blocked", a login or captcha check,
a phone or email confirmation, the account logged out, or anything unusual on screen. Run
`run.sh browser stop "<exactly what it said>"`, which pauses all sessions for 48 hours, and tell the owner.
If you had already liked or commented on the current step, still report it with `browser done` (it must be
counted).

## Never

- Never like, comment, follow or open a profile that `browser next` didn't hand out, and never act between
  steps or after `DONE`.
- Never unfollow anyone, never send a DM, never comment on a post of a child's account or a rival.
- Never run a session in a routine: a session starts only on the owner's "engage S<n>".
- Never start the next session early, and never retry a refused start before the time it names.
