# Setting up the Monster Ten Social Bot

About an hour the first time for comments, most of it in Meta's App Dashboard; DMs, creator scouting and
outreach email each add a step (sections 12–14) once their access is ready. Nothing is posted until you say
"go live".

| Path                                | What                                                                     |
| ----------------------------------- | ------------------------------------------------------------------------ |
| `/workspace/monstertenmath-grokbot` | The release checkout (`v0.2.0`). Never edited on the computer.           |
| `/workspace/monsterten-desk`        | The desk: `config.toml`, `state/`, `secrets/`, `logs/`. Kept on updates. |

## 1. What you need

- @monstertenmath as a **professional account** (Business), which the launch pack already set up (README
  section 1), with your own login to it.
- A Meta developer account (developers.facebook.com, free, with your Facebook login).
- A Grok Bot computer (xAI's Grok Bot), and a way for it to clone this repo: your GitHub login on the computer,
  or a read-only deploy key for `fairgradient-ai/monstertenmath-grokbot`.

## 2. The Instagram token (Meta's App Dashboard)

Meta moves these screens around; the names below are from its 2025–26 docs. The goal: a long-lived token for
@monstertenmath with two permissions, **`instagram_business_basic`** and
**`instagram_business_manage_comments`**.

1. developers.facebook.com → **My Apps** → **Create app**. Name it "Monster Ten Social Bot". Use case:
   **Manage messaging & content on Instagram**. App type, if asked: Business.
2. In the app: **Instagram** → **API setup with Instagram login**.
3. If it asks for a tester first: **App roles** → **Roles** → **Instagram Testers** → add `monstertenmath`. Then
   in the Instagram app, as @monstertenmath, accept the invite (Settings → Website permissions → Apps and
   websites → Tester invites).
4. Back in **API setup with Instagram login** → **Generate access tokens** → **Add account** → log in as
   @monstertenmath and allow the permissions. Copy the token it shows. It lasts 60 days; the bot refreshes it
   every Sunday.
5. Leave the app in **Development** mode for now. Our own account, with a role on our own app, is covered by
   Standard Access for comments: no App Review. DMs need Advanced Access (section 12).

Keep the token out of chat, email and files. It goes on the card in the next step, and only there.

## 3. Create the Grok Bot

1. New Bot. Paste the profile and system prompt from [`agents/monsterten-social-bot.md`](agents/monsterten-social-bot.md).
   Set **Timezone** to America/New_York and **Notifications** on.
2. Add the three skills from [`skills/`](skills): `monsterten-social-bootstrap`, `monsterten-social-operations`,
   `monsterten-voice`.
3. **Secret card**: add `IG_ACCESS_TOKEN` with the token from step 2. Later, `FB_ACCESS_TOKEN` (section 13) and
   `SMTP_USER` / `SMTP_PASSWORD` (section 14). Every Bot on the same computer can see the card, so keep other
   people's Bots off this computer.
4. **Auto-review** (Settings → General): paste the two rules from [`routines/autoreview.txt`](routines/autoreview.txt).
5. Start it with:

   ```text
   Set yourself up with the monsterten-social-bootstrap skill and SETUP.md from fairgradient-ai/monstertenmath-grokbot
   at v0.2.0. Install under /workspace, take the Instagram token only from the IG_ACCESS_TOKEN card, stay in
   rehearsal, post nothing, and finish with the setup receipt.
   ```

## 4. What the setup does

The bootstrap skill clones the release into `/workspace/monstertenmath-grokbot`, runs
`scripts/install.sh` (Python 3.11+, the desk, `config.toml` from the template, mode **rehearsal**, phase
**building**), then `run.sh doctor --full`, then one rehearsal sweep, and ends with:

```text
SETUP DONE · release v0.2.0 · mode rehearsal · phase building
Instagram: @monstertenmath · reads comments: yes · token: secret card
Next: turn on the routines (SETUP.md 6), rehearse for a day, then say "go live".
```

## 5. Rehearse

Say "check the comments" a few times over a day. Each sweep shows **"Would reply"** for the canned answers and
drafts the rest; nothing is posted. Read what it would say. If a canned reply is wrong, change
`knowledge/` in a pull request (section 10), not on the computer.

## 6. Turn on the routines

From [`routines/manifest.toml`](routines/manifest.toml), for each routine:

1. Create it **paused**, with its time, days and prompt, word for word.
2. Ask the Bot to read it back, and compare.
3. Run it once by hand. The sweep routine should post a sweep and a list of drafts, and send nothing.
4. Unpause it.

Do `health` (Sundays) too: it refreshes the token. `stats-nightly` is optional.

## 7. Launch day

After the launch-day gate passes (pack, section 0), in this order:

1. Tell Claude Code "we're open" in the social repo, as the pack says (it unlocks the Buffer queue).
2. Tell the Bot **"we're open"** and tap the card: `run.sh phase open --owner-tapped`. From now on the
   answers point to the free check, and nothing says "being built".
3. Set the stores the app is really in (gate step 4) in `/workspace/monsterten-desk/config.toml`, for example
   `stores = ["app_store"]`. Ask the Bot to show you the file first, then approve the edit. Until it's set, "iPhone
   or Android?" comes to you instead of getting an answer.

If launch slips, nothing changes: the phase stays `building`. If you flipped it too early, say "back to
building".

## 8. Go live

After a day of rehearsal that reads right: say **"go live"** and tap the card (`run.sh go-live
--owner-tapped`). From the next sweep, canned replies, first comments and the replies the Grok Bot writes post
by themselves once they pass the check. Only the sensitive ones (a child's health, legal, rivals, complaints)
wait for your "send". "Stop posting" goes back to rehearsal at once.

If you'd rather approve every written reply for a while, set `autosend_written = false` under `[engage]`.

## 9. Running it without Grok (optional)

The engine runs anywhere with Python 3.11+ and a token in the environment:

```bash
MT_DESK=$HOME/monsterten-desk IG_ACCESS_TOKEN=... bash scripts/run.sh sweep
```

From cron, every 3 hours, it posts the canned replies (in live mode) and leaves the rest in `run.sh inbox`.
Drafting needs the Grok Bot, or the later xAI API mode (DESIGN.md, section 11).

## 10. Updates

Changes to replies, rules or pieces go by pull request into `main`, then a new release tag. To move the Bot to
a new release:

1. Ask the Bot to clone the new tag beside the old one (`/workspace/monstertenmath-grokbot-v0.1.1`), run its
   `install.sh` and `doctor --full`.
2. On a PASS, swap the folders (your tap). The desk, its config, state and token are untouched.

When the social repo's schedule changes, run `python3 scripts/sync_social.py ../monstertenmath_social` on a
laptop with both repos: it lists pieces to add or fix in `knowledge/pieces.toml`.

## 11. Troubleshooting

| You see                                   | Do                                                                                              |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `FAILED: the Instagram token is expired…` | Make a new token (section 2, step 4) and replace the card                                       |
| `FAILED: missing permission`              | Re-generate the token with both permissions ticked                                              |
| `FAILED: the token is for @…`             | The card holds another account's token                                                          |
| `FAILED: no Python 3.11 or newer`         | `bash /workspace/monstertenmath-grokbot/scripts/install.sh`                                     |
| `unknown timezone … no time zone data`    | The computer lacks tzdata: install it, or ask the Bot to                                        |
| `STOPPED: Instagram's rate limit`         | Nothing; the next sweep carries on                                                              |
| `DOCTOR: WARN` · token expiry unknown     | Normal until the first Sunday refresh. Or say "refresh the token" (the token must be a day old) |
| `DOCTOR: WARN` · phase vs bio link        | The bio and the phase disagree: check the profile, or say "we're open" / "back to building"     |
| A canned reply that's wrong               | Pull request to `knowledge/`; meanwhile "stop posting" puts the Bot back in rehearsal           |

## 12. DMs

DMs from people who have no role on our app need **Advanced Access** to `instagram_business_manage_messages`,
which means App Review. Start it now; it takes days to weeks.

1. **Business Verification** (Meta Business Suite → Settings → Business info → Verification), if the
   business isn't verified yet: legal name, address, a document.
2. A **privacy policy URL** on the app (App settings → Basic). monstertenmath.com's privacy page, once live.
3. **App Review → Permissions and features** → request Advanced Access to `instagram_business_manage_messages`
   (and `instagram_business_manage_comments`, `instagram_business_basic`). Describe the use: "Our account's own
   assistant answers questions parents send us by DM, within 24 hours, under our brand rules; a person
   reviews anything sensitive." Record a short screencast of a test DM and the reply arriving.
4. Make a new token with the messages permission ticked (section 2, step 4) and replace the card.
5. Set `[dms] enabled = true` in `/workspace/monsterten-desk/config.toml` (ask the Bot to show the file, then
   approve the edit), and run `run.sh doctor`.

Until then, Meta Business Suite → Inbox → Automations (instant reply, FAQs) can answer the commonest DM
questions without any app. Use the pack's replies for them.

## 13. Creator scouting

The scout reads public business and creator profiles (Business Discovery) and the top posts under the plan's
hashtags. Both are on Meta's **Facebook Login** side, so it needs a second token.

1. A **Facebook Page** linked to @monstertenmath (Instagram → Settings → Accounts Center, or the Page's
   settings → Linked accounts). An empty Page is fine.
2. In the same Meta app, add the **Instagram API with Facebook Login** product. Generate a long-lived user token
   (Graph API Explorer, then exchange it for a long-lived one) with `instagram_basic`, `pages_show_list` and
   `pages_read_engagement`.
3. Hashtag search also needs the **Instagram Public Content Access** feature: request it in App Review with
   the DM request (section 12). Until it's granted, the scout skips hashtags and uses seeds and commenters.
4. Put the token on the card as `FB_ACCESS_TOKEN`. Set `[scout] enabled = true` in the desk's config.toml.
5. Say "find creators". Add any creator you like the look of with "look at @name". Turn on the
   `scout-weekly` routine (section 6).

## 14. Outreach email

Collab emails go from your own mailbox, on your tap.

1. For Gmail or Google Workspace: turn on 2-Step Verification, then make an **App Password**
   (myaccount.google.com → Security → App passwords). Never your real password.
2. On the card: `SMTP_USER` (the full address) and `SMTP_PASSWORD` (the app password).
3. In the desk's config.toml, `[outreach]`: `from_name`, `from_email`, and a `postal_address` (a PO box is fine:
   US commercial email needs one), then `enabled = true`.
4. After a scout, the Bot drafts emails; say **"send all outreach"** and tap. At most 10 a day. Replies land in
   your inbox; tell the Bot "@name booked" or "@name said no".

## 15. Day to day

The phrases ("send 14", "edit 14: …", "skip 14", "hide 16", "inbox", "find creators", "send all outreach",
"examples", "stats") are in the operations skill:
[`skills/monsterten-social-operations/SKILL.md`](skills/monsterten-social-operations/SKILL.md).
