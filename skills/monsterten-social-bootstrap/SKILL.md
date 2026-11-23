---
name: monsterten-social-bootstrap
description: First-time setup of the Monster Ten social bot on the Grok Bot computer. Use when the owner says "set up", "install", "start", or follows the Start prompt in README.md. Clones the pinned release, installs, checks Instagram access through the secret card, and ends with a receipt. Posts nothing.
license: Proprietary
metadata:
  version: "1.1.0"
  category: social
---

# Setting up the Monster Ten social bot

**Safety boundary.** Setup posts nothing and changes nothing on Instagram. The bot starts in **rehearsal** mode
and the **building** phase. The token comes only from the secret card. If the owner pastes a token in chat,
stop them and point to the card.

Follow SETUP.md in the checkout. In order:

1. **Clone `main`** (the owner's GitHub access on the computer, or a read-only GITHUB_TOKEN on the card):

   ```bash
   git clone --depth 1 https://github.com/fairgradient-ai/monstertenmath-grokbot.git /workspace/monstertenmath-grokbot
   ```

   If /workspace/monstertenmath-grokbot already exists, don't touch it: tell the owner and use SETUP.md,
   section 10 (updates).

2. **Install**: `bash /workspace/monstertenmath-grokbot/scripts/install.sh`. Post its output. Any `FAIL:` line
   stops setup.

3. **Check**: `bash /workspace/monstertenmath-grokbot/scripts/run.sh doctor --full`. Before the token is on the
   card, a FAIL on the token is expected; every other line must be `ok:` (or the WARN on token expiry).

4. **The token.** Ask the owner to add `IG_ACCESS_TOKEN` on the secret card (SETUP.md, sections 2 and 3). Wait
   for "done". Then run `run.sh doctor` again: it must answer as @monstertenmath and read comments. The engine
   finds the Instagram account from the token by itself; leave `[instagram] ig_user_id` blank.

   Only if doctor still says the token can't see an Instagram account, ask the owner for the digits Meta's
   dashboard shows next to @monstertenmath (a number like 17841400000000000). What goes in `ig_user_id` is
   those digits and nothing else. If the owner sends a link, a screenshot or a username, don't put it in
   config.toml, and don't take numbers out of a link: the numbers in a dashboard address are the app's and
   the business's, not the account's. Say so, and ask again for the digits beside @monstertenmath. Show the
   owner the one-line change before you make it (it's an Ask-first edit), then run doctor.

5. **A first look**: `run.sh sweep`. It's rehearsal: it shows what it would reply and posts nothing. Post the
   output and write replies for anything under "Needs a written reply" with `run.sh reply` (operations skill,
   "After a sweep"); in rehearsal they're saved, not posted.

6. **Receipt.** End with exactly these lines, filled in:

   ```text
   SETUP DONE · release v1.1.2 · mode rehearsal · phase building
   Instagram: @monstertenmath · reads comments: yes · token: secret card
   Next: turn on the routines (SETUP.md 6), rehearse for a day, then say "go live".
   Later: DMs (SETUP.md 12), creator scouting (13) and outreach email (14), each when its access is ready.
   ```
