---
name: monsterten-social-operations
description: Day-to-day running of the Monster Ten social bot on Instagram. Use for every routine run and for anything the owner says about comments, replies, drafts, the inbox, sending, hiding, spam, the phase ("we're open"), going live, the token, followers or stats. Maps the owner's words to run.sh commands, says what to do after a sweep, and how to read failures.
license: Proprietary
metadata:
  version: "0.1.0"
  category: social
---

# Running the Monster Ten social bot

All commands are `bash /workspace/monstertenmath-grokbot/scripts/run.sh <command>`. Post the output verbatim.

## The owner says → you run

| The owner says                                  | Run                                                 | Approval      |
| ----------------------------------------------- | --------------------------------------------------- | ------------- |
| "check the comments", "sweep", "anything new?"  | `run.sh sweep`, then "After a sweep" below          | automatic     |
| "inbox", "what's waiting?"                      | `run.sh inbox`                                      | automatic     |
| "send 14", "send 14 and 15"                     | `run.sh send 14 15 --owner-tapped`                  | **their tap** |
| "send all"                                      | `run.sh send all --owner-tapped` (drafts that pass) | **their tap** |
| "send 14 anyway" (a draft that fails the check) | `run.sh send 14 --owner-tapped --force-lint`        | **their tap** |
| "edit 14: <their words>"                        | `run.sh draft 14` with their words (heredoc below)  | automatic     |
| "skip 14", "no reply to 14"                     | `run.sh discard 14`                                 | automatic     |
| "hide 16"                                       | `run.sh hide 16 --owner-tapped`                     | **their tap** |
| "status"                                        | `run.sh status`                                     | automatic     |
| "followers", "stats", "how are we doing?"       | `run.sh stats`                                      | automatic     |
| "we're open" (after the launch-day gate passed) | `run.sh phase open --owner-tapped`                  | **their tap** |
| "back to building" (launch slipped)             | `run.sh phase building --owner-tapped`              | **their tap** |
| "go live"                                       | `run.sh go-live --owner-tapped`                     | **their tap** |
| "stop posting", "rehearsal"                     | `run.sh rehearse --owner-tapped`                    | **their tap** |
| "refresh the token"                             | `run.sh token refresh`                              | automatic     |
| "check yourself", "doctor"                      | `run.sh doctor`                                     | automatic     |

"We're open" also has a twin in the social repo: the owner tells Claude Code "we're open" there too, which
runs `gate.py open` and unlocks the after-launch posts in Buffer. Remind them if they mention only one.

When the owner gives a store at launch ("it's on the App Store"), tell them to set `stores` in
/workspace/monsterten-desk/config.toml (SETUP.md, section 7). Don't edit it yourself.

## After a sweep

1. Post the sweep's output verbatim.
2. For each item under **"Needs a written reply"**, write a reply with the monsterten-voice skill and save it:

   ```bash
   bash /workspace/monstertenmath-grokbot/scripts/run.sh draft 14 <<'MT_EOF'
   Our games start at 4, but plenty of 3-year-olds love the cracker part with you.
   MT_EOF
   ```

   Always save drafts with this quoted heredoc (`<<'MT_EOF'`, quotes included). It keeps `$79.99`,
   apostrophes and quotation marks exactly as written; `--text "..."` would let the shell eat a `$7`.

3. If a draft comes back **FAILS the check**, rewrite it once to fix every ✗ line and save it again. If it
   still fails, leave it for the owner and say why.
4. Post a short list: `Drafts ready: [14] @mo_asks · "…"`, then "Say send 14, send all, edit 14: …, or skip 14."
5. **Send nothing.** In a routine nobody is there to tap, and an approval card left waiting expires.
6. Items under **"For you"** and **"Spam"**: list them for the owner. Don't draft them unless asked.

If the sweep says `quiet`, post that one line and stop.

## The first comment on a new post

In live mode the sweep posts a piece's first comment by itself (pieces.toml, `first_comment`), once, when the
post is less than a day old and has no comment from us yet. The API can't pin, so pass on the sweep's line:
"Pin it in the app: press and hold the comment, then Pin."

## When something fails

| Output starts with                     | What it means                                       | Do this                                                         |
| -------------------------------------- | --------------------------------------------------- | --------------------------------------------------------------- |
| `FAILED: the Instagram token…`         | The token expired or was revoked                    | Ask the owner for a new token on the card (SETUP.md, section 2) |
| `STOPPED: Instagram's rate limit`      | Meta paused us                                      | Nothing. The next routine carries on. Don't retry by hand.      |
| `STOPPED: Instagram stopped answering` | Network or Meta trouble                             | Nothing. The next routine carries on.                           |
| `UNVERIFIED [n]`                       | A post timed out; it may or may not be on Instagram | Nothing. The next sweep checks before anything is retried.      |
| `FAILED: missing permission`           | The token lacks instagram_business_manage_comments  | Owner makes a token with that permission (SETUP.md, section 2)  |
| `FAILED: the token is for @…`          | A token for another account                         | Owner fixes the card                                            |
| `BUSY:`                                | Another command is running                          | Wait a minute, then run it again once                           |
| `REFUSED:`                             | A command needed the owner's tap, or a bad number   | Read it out; ask the owner                                      |
| `DOCTOR: FAIL`                         | Setup is broken                                     | Read out the FAIL lines; SETUP.md, section 11                   |

## Never

- Run `send`, `hide`, `phase`, `go-live` or `rehearse` without the owner's tap on that exact command.
- Post, like, follow, comment or DM anywhere except through run.sh, and never on another account.
- Answer an escalation (money, health, legal, business, rivals, complaints) on your own.
- Edit files in /workspace/monstertenmath-grokbot, or config.toml, knowledge or state in the desk.
- Show, echo or store the token anywhere but the card.
