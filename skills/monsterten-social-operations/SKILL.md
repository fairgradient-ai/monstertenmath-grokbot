---
name: monsterten-social-operations
description: Day-to-day running of the Monster Ten social bot. Use for every routine run and for anything the owner says about comments, DMs, replies, drafts, the inbox, sending, hiding, spam, creators, influencers, Collabs, outreach emails, examples, the phase ("we're open"), going live, the token, followers or stats. Maps the owner's words to run.sh commands, says what to do after a sweep and after a scout, and how to read failures.
license: Proprietary
metadata:
  version: "0.4.2"
  category: social
---

# Running the Monster Ten social bot

All commands are `bash /workspace/monstertenmath-grokbot/scripts/run.sh <command>`. Post the output verbatim.

## The owner says → you run

| The owner says                                  | Run                                                    | Approval      |
| ----------------------------------------------- | ------------------------------------------------------ | ------------- |
| "check the comments", "sweep", "anything new?"  | `run.sh sweep`, then "After a sweep" below             | automatic     |
| "inbox", "what's waiting?"                      | `run.sh inbox`                                         | automatic     |
| "send 14", "send 14 and 15", "ok 14"            | `run.sh send 14 15 --owner-tapped`                     | **their tap** |
| "send all"                                      | `run.sh send all --owner-tapped` (drafts that pass)    | **their tap** |
| "send 14 anyway" (a draft that fails the check) | `run.sh send 14 --owner-tapped --force-lint`           | **their tap** |
| "edit 14: <their words>"                        | `run.sh draft 14 --by owner` (heredoc), then `send 14` | send: tap     |
| "skip 14", "no reply to 14"                     | `run.sh discard 14`                                    | automatic     |
| "hide 16"                                       | `run.sh hide 16 --owner-tapped`                        | **their tap** |
| "find creators", "influencers", "scout"         | `run.sh scout`, then "After a scout" below             | automatic     |
| "look at @name" (a creator to consider)         | `run.sh scout add name`, then `run.sh scout`           | automatic     |
| "creators", "who did you find?"                 | `run.sh creators`                                      | automatic     |
| "outreach", "what emails are waiting?"          | `run.sh outreach list`                                 | automatic     |
| "send all outreach", "send the emails"          | `run.sh outreach send all --owner-tapped`              | **their tap** |
| "send outreach to @name"                        | `run.sh outreach send name --owner-tapped`             | **their tap** |
| "@name said no", "@name booked"                 | `run.sh creators mark name declined` / `booked`        | automatic     |
| "examples", "what have you learned?"            | `run.sh examples`                                      | automatic     |
| "brief", "what should I comment on?"            | `run.sh brief`, then "The brief" below                 | automatic     |
| "show the comments"                             | `run.sh brief show`                                    | automatic     |
| "done 12 13", "posted 12-15"                    | `run.sh brief done 12 13 14 15`                        | automatic     |
| "skip B14"                                      | `run.sh brief skip 14`                                 | automatic     |
| "status"                                        | `run.sh status`                                        | automatic     |
| "followers", "stats", "how are we doing?"       | `run.sh stats`                                         | automatic     |
| "we're open" (after the launch-day gate passed) | `run.sh phase open --owner-tapped`                     | **their tap** |
| "back to building" (launch slipped)             | `run.sh phase building --owner-tapped`                 | **their tap** |
| "founding price on" (site's ticket shows it)    | `run.sh pricing founding --owner-tapped`               | **their tap** |
| "founding price closed" (500 in, or off site)   | `run.sh pricing standard --owner-tapped`               | **their tap** |
| "which price?"                                  | `run.sh pricing show`                                  | automatic     |
| "go live"                                       | `run.sh go-live --owner-tapped`                        | **their tap** |
| "stop posting", "rehearsal"                     | `run.sh rehearse --owner-tapped`                       | **their tap** |
| "refresh the token"                             | `run.sh token refresh`                                 | automatic     |
| "update yourself"                               | SETUP.md section 10 (clone `main`, test, swap)         | swap: tap     |
| "check yourself", "doctor"                      | `run.sh doctor`                                        | automatic     |

"We're open" also has a twin in the social repo: the owner tells Claude Code "we're open" there too, which
runs `gate.py open` and unlocks the after-launch posts in Buffer. Remind them if they mention only one.

**The founding price.** Right after "we're open", ask: "Did the site's ticket show the founding price,
$59.99 a year or $9.99 a month (gate step 3)?" Only on a yes, and on their tap, run `run.sh pricing founding`.
Then the price answers give it with its terms whole: the first 500 families who sign up, theirs for good, even
if they cancel and come back. When the owner says the first 500 are in (or the site stopped showing it), run
`run.sh pricing standard` on their tap: the answers go back to $79.99 or $12.99, and a question about the
founding price comes to them, since only they know who is a founding family. You never know how many places
are left, so never say, guess or hint at a number, and never write "filling fast", "only N left" or "before
it's gone": the engine holds any reply that does.

When the owner gives a store at launch ("it's on the App Store"), tell them to set `stores` in
/workspace/monsterten-desk/config.toml (SETUP.md, section 7). Don't edit it yourself.

## Writing text into a command

Always pass written text with this quoted heredoc (`<<'MT_EOF'`, quotes included). It keeps `$79.99`,
apostrophes and quotation marks exactly as written; `--text "..."` would let the shell eat a `$7`.

```bash
bash /workspace/monstertenmath-grokbot/scripts/run.sh reply 14 <<'MT_EOF'
Our lessons are made for 4 to 6, but plenty of 3-year-olds love the cracker part with you.
MT_EOF
```

## After a sweep

1. Post the sweep's output verbatim. If it says `quiet`, post that one line and stop.
2. Run `run.sh examples` once, and write the way the owner does.
3. For each item under **"Needs a written reply"**, write a reply (monsterten-voice skill) and post it with
   `run.sh reply <number>`. It goes out by itself if it passes the check.
   - `HELD`: rewrite once to fix every ✗ line and run `reply` again. If it still fails, leave it and say why.
   - `SAVED … waits for your OK`: it's the owner's (step 4).
4. For each item under **"For you"** that waits for an OK (not the ones answered with a holding line), write a
   careful, kind draft with `run.sh draft <number>` (no promises, no advice about a child's health, point to
   info@monstertenmath.com where it helps). Then tell the owner: "[13] waits for your OK: say send 13, edit
   13: …, or skip 13."
5. **Spam**: list it for the owner; "hide 16" hides it.
6. Never run `send`, `hide` or `outreach send` in a routine: an approval card nobody taps expires.
7. End with one short summary: what went out, what waits for the owner.

## After a scout

The scout reads public business and creator profiles and scores them by the growth plan (6.3 and 6.5): US
parents and teachers whose recent posts show 4–6 year olds learning at home, 5,000–200,000 followers (10,000–
40,000 is the Collab sweet spot), real comments, posting this week, no rival brand.

1. Post the scout's output verbatim.
2. For each candidate with a score of 60 or more, run `run.sh creators show <name>` and judge fit from the bio
   and captions: a real parent or teacher of 4–6 year olds, in the US as far as you can tell, a warm tone,
   nothing unsafe, no rival app.
   - Fit: `run.sh creators mark <name> shortlist --note "<why, in a few words>"`.
   - Not a fit: `run.sh creators mark <name> reject --note "<why>"`.
3. For each shortlisted creator with an email, write one or two sentences about one specific recent post of
   theirs (true to its caption, warm, no flattery overload), and draft the email:

   ```bash
   bash /workspace/monstertenmath-grokbot/scripts/run.sh outreach draft kinder_with_kate <<'MT_EOF'
   Your ten-frame snack game last week is exactly the kind of play we build for.
   MT_EOF
   ```

4. Post `run.sh outreach list` and ask: "Say send all outreach to email these (one tap)."
5. You may also look for creators yourself (your own web and X search) and add promising usernames with
   `run.sh scout add <names>` before a run. Never follow, like, comment on or DM them.

When a creator replies by email, the owner forwards or tells you; mark them `booked` or `declined`. A creator
marked `declined` or `rejected` is never written to again.

## The brief (three times a day)

The brief picks fresh posts (from the last day) from the shortlisted creators, one per creator a day, at most
30 a day. You write a comment for each; a person posts them from @monstertenmath by hand.

1. Post `run.sh brief`'s output verbatim. If it says no posts, post that and stop.
2. For each `[B<n>]`, read its caption and write one fresh comment (voice skill, "Comments on creators'
   posts"), then save it:

   ```bash
   bash /workspace/monstertenmath-grokbot/scripts/run.sh brief comment 12 <<'MT_EOF'
   7 is a full row and 2 more, so you can see it without counting one by one. Love this.
   MT_EOF
   ```

   `HELD`: fix every ✗ (usually a mention of the app, a link, or a comment used before) and save it again once.
3. Post `run.sh brief show` verbatim: it's the list the person posts from. If `[brief] email_to` is set, run
   `run.sh brief email` too.
4. When the owner says "done 12 13" (posted) or "skip 14", run `brief done` or `brief skip` with the numbers.
5. Never open Instagram to post them yourself.

## The first comment on a new post

In live mode the sweep posts a piece's first comment by itself (pieces.toml, `first_comment`), once, when the
post is less than a day old and has no comment from us yet. The API can't pin, so pass on the sweep's line:
"Pin it in the app: press and hold the comment, then Pin."

## When something fails

| Output starts with                     | What it means                                       | Do this                                                         |
| -------------------------------------- | --------------------------------------------------- | --------------------------------------------------------------- |
| `FAILED: the Instagram token…`         | The token expired or was revoked                    | Ask the owner for a new token on the card (SETUP.md, section 2) |
| `FAILED: no Facebook token`            | Scouting has no FB_ACCESS_TOKEN                     | SETUP.md, section 13                                            |
| `FAILED: the email login was refused`  | SMTP_USER / SMTP_PASSWORD wrong                     | SETUP.md, section 14                                            |
| `STOPPED: Instagram's rate limit`      | Meta paused us                                      | Nothing. The next routine carries on. Don't retry by hand.      |
| `STOPPED: Instagram stopped answering` | Network or Meta trouble                             | Nothing. The next routine carries on.                           |
| `UNVERIFIED [n]`                       | A post timed out; it may or may not be on Instagram | Nothing. The next sweep checks before anything is retried.      |
| `outside Meta's 24-hour DM window`     | The person wrote more than a day ago                | Tell the owner; only they can answer it, in the app             |
| `FAILED: missing permission`           | The token lacks a permission                        | SETUP.md, sections 2, 12 or 13                                  |
| `BUSY:`                                | Another command is running                          | Wait a minute, then run it again once                           |
| `REFUSED:`                             | A command needed the owner's tap, or a bad name     | Read it out; ask the owner                                      |
| `DOCTOR: FAIL`                         | Setup is broken                                     | Read out the FAIL lines; SETUP.md, section 11                   |

## Never

- Run `send`, `hide`, `outreach send`, `phase`, `go-live` or `rehearse` without the owner's tap on that command.
- Follow, unfollow, like, comment or DM on another account, by any means (the brief's comments are posted by a
  person).
- Answer a child's health, legal, rival or complaint message on your own.
- Edit files in /workspace/monstertenmath-grokbot, or config.toml, knowledge or state in the desk.
- Show, echo or store a token or password anywhere but the card.
