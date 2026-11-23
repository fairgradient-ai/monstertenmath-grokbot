---
name: monsterten-browser-engagement
description: How to run a browser session for @monstertenmath, liking, commenting and following in the Grok browser one step at a time with human pauses, including posts Grok picks from the home feed. Use when the owner says "engage S<n>", when a brief routine made a browser plan, or when a run.sh browser command answers. The engine plans, paces and counts; you click only what it hands out.
license: Proprietary
metadata:
  version: "1.1.0"
  category: social
---

# Engaging in the Grok browser

The owner decided that the Bot may like, comment and follow from @monstertenmath in the Grok browser, with
breaks like a person's (DESIGN.md section 3). It carries a real risk to the account, so the engine holds the
limits: caps per day and per session that ramp up over the first two weeks, quiet hours, a random wait between
steps, a 90-minute gap between sessions, and a 48-hour stop after any warning. Your job is to follow it exactly.

## A session

1. A brief routine (or the owner's "engage now") runs `run.sh browser plan`. If it prints `PLAN S7 · …`, ask the
   owner to say "engage S7". The plan shows kinds and counts, never links or comment text.
2. The owner says "engage S7". Run `bash /workspace/monstertenmath-grokbot/scripts/run.sh browser start S7
   --owner-tapped` (the one Ask-first card for the whole session). If it's REFUSED (too soon after the last
   session, plan too old, quiet hours), post the line and stop. Say "engage S7" again at the time it gives.
   **Auto engage:** when `run.sh browser status` says "auto engage on" (the owner said "auto engage on" once,
   `run.sh browser auto on --owner-tapped`), a brief routine starts the session itself with `run.sh browser
   start S7 --auto` and runs it the same way. Everything else below still holds.
3. Loop, without doing anything else in between:
   - `run.sh browser next S7`. It may take up to about two and a half minutes to answer: that is the break. If it
     answers `WAIT …`, run it again.
   - It prints one `STEP S7.<k>`: open exactly that link in the Grok browser, look at the post for the time it
     gives (scroll it, read the caption), then do only what it names: like it, or like it and post the
     comment **exactly as printed**, or follow that account. Never change the comment's words.
   - A **feed** step (`STEP S7.<k> · feed`) asks you to choose: open our home feed, scroll for the time it
     gives, and pick ONE post from another account that fits Monster Ten's world (a parent, teacher or creator
     sharing young children, play, early learning, reading, numbers, family life). Not an ad, a giveaway, a
     child's own account, a rival, or anything sad, political or about a child's health. Write a fresh comment
     for that post alone, in the monsterten-voice: one or two short warm sentences about what's actually in it,
     like a parent would write. No app, link, price, hashtag, @mention, "follow us", and never a comment used
     before. Then run `run.sh browser pick S7 <k> --link <the post's link> --author <username> --caption
     "<first line of its caption>" --comment "<your comment>"`; add `--follow` when the account is a parent or
     creator in our world worth following, or use `--like-only`. If pick is REFUSED, it changed nothing: pick
     another post or write another comment (never argue with the check), or skip the step. When pick answers
     with a STEP line, do exactly what it names, like any other step. Don't touch anything before pick answers.
     If nothing in the feed fits, `run.sh browser done S7 <k> --skip "nothing fitting in the feed"`.
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

- Never like, comment, follow or open a profile that `browser next` or `browser pick` didn't hand out (a feed
  step's scrolling is only looking), and never act between
  steps or after `DONE`.
- Never unfollow anyone, never send a DM, never comment on a post of a child's account or a rival.
- Never run a session in a routine unless `browser status` says "auto engage on" and you start it with
  `browser start S<n> --auto`; otherwise a session starts only on the owner's "engage S<n>".
- In a feed step, never like, comment or follow before `browser pick` answers. If nothing fits, skip: a
  weak pick is worse than none.
- Never start the next session early, and never retry a refused start before the time it names.
