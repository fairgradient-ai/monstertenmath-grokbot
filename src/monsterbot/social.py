"""The Buffer bridge: the social repo's calendar (schedule.json, stories.json on main) and Buffer's queue, kept in
step by the Bot.

The calendar on `main` is the approval: a post reaches Buffer only after its pull request is merged. Buffer holds
what will publish. The ledger (`buffer_posts`) remembers which Buffer post is which calendar entry, the main commit
it came from, and hashes of what main said and what was sent, so the bridge can tell "main changed" from "someone
edited it in the Buffer app" from "both".

Rules the code keeps:
- `adopt` first, once: it records what is already in Buffer and changes nothing. `sync` refuses until it has run.
- A post whose time has passed is never created (Buffer would publish it at once), and a known post that went
  missing from Buffer is reported, never re-created: `restore` brings one back on the owner's tap.
- A post edited only in the Buffer app is left as it is and reported; `push` sends main's version on a tap.
- Nothing is deleted except by `delete` on a tap. A post in Buffer that matches no entry is "foreign": never touched.
- Media must already be public in the bucket (the studio uploads it with the content PR); sync checks each link
  answers before it creates a post.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from . import policy
from .errors import BotError, Refused

LAUNCH_UTC = "2026-11-24T05:00:00+00:00"  # Tue 24 Nov 2026, midnight Eastern: posts due from then are "open"
# (the owner moved the social launch from 1 Dec to 24 Nov on 21 Nov 2026: the site is already live, announced 24 Nov)
STORY_TAG = re.compile(r"\[Story ([^\]]+)\]")
OUT = """__typename ... on PostActionSuccess { post { id dueAt status schedulingType } }
  ... on InvalidInputError { message } ... on UnexpectedError { message } ... on LimitReachedError { message }
  ... on UnauthorizedError { message } ... on NotFoundError { message } ... on RestProxyError { message }"""
CREATE = "mutation($input: CreatePostInput!) { createPost(input: $input) { " + OUT + " } }"
EDIT = "mutation($input: EditPostInput!) { editPost(input: $input) { " + OUT + " } }"
DELETE = (
    "mutation($input: DeletePostInput!) { deletePost(input: $input) { __typename "
    "... on DeletePostSuccess { id } ... on NotFoundError { message } ... on UnexpectedError { message } } }"
)
FEED_FIELDS = ("name", "dueAt", "type", "text", "media")
STORY_FIELDS = ("name", "dueAt", "media", "publish")


class BufferError(BotError):
    exit_code = 3


def phase_at(due_at: str) -> str:
    return "open" if _dt(due_at) >= datetime.fromisoformat(LAUNCH_UTC) else "building"


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _h(*parts: object) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# --- Buffer's API ---------------------------------------------------------------------------------------
class BufferClient:
    """Buffer's GraphQL API, stdlib only. The key comes from the secret card (BUFFER_API_KEY), never from a file."""

    def __init__(self, api: str, key: str, timeout: int = 60):
        self.api, self.key, self.timeout = api, key, timeout
        self._org: str | None = None
        self._channel: str | None = None

    def gql(self, query: str, variables: dict | None = None) -> dict:
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(self.api, data=body, method="POST")
        req.add_header("content-type", "application/json")
        if self.key:
            req.add_header("authorization", f"Bearer {self.key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                out = json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise BufferError(f"FAILED: Buffer answered {e.code}. Check BUFFER_API_KEY on the secret card.") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise BufferError(f"FAILED: couldn't reach Buffer ({e}).") from None
        if out.get("errors") and not out.get("data"):
            raise BufferError("FAILED: Buffer refused: " + json.dumps(out["errors"])[:300])
        return out

    def ids(self) -> tuple[str, str]:
        if self._org is None:
            self._org = self.gql("{ account { organizations { id } } }")["data"]["account"]["organizations"][0]["id"]
            chs = self.gql(
                "query($o: OrganizationId!) { channels(input: {organizationId: $o}) { id service name } }",
                {"o": self._org},
            )["data"]["channels"]
            ig = [c for c in chs if c["service"] == "instagram"]
            if len(ig) != 1:
                raise BufferError(f"FAILED: expected one Instagram channel in Buffer, found {len(ig)}.")
            self._channel = ig[0]["id"]
        return self._org, self._channel  # type: ignore[return-value]

    def posts(self, status: str = "scheduled") -> list[dict]:
        org, ch = self.ids()
        q = (
            "query($o: OrganizationId!, $a: String) { posts(first: 100, after: $a, input: {organizationId: $o, "
            f'filter: {{channelIds: ["{ch}"], status: [{status}]}}}}) {{ pageInfo {{ hasNextPage endCursor }} '
            "edges { node { id dueAt text schedulingType } } } }"
        )
        out, after = [], None
        for _ in range(50):
            p = self.gql(q, {"o": org, "a": after})["data"]["posts"]
            out += [e["node"] for e in p["edges"]]
            if not p["pageInfo"]["hasNextPage"]:
                break
            after = p["pageInfo"]["endCursor"]
        return out

    def _mutate(self, query: str, field: str, inp: dict) -> dict:
        r = self.gql(query, {"input": inp})
        res = (r.get("data") or {}).get(field) or {}
        if res.get("__typename") not in ("PostActionSuccess", "DeletePostSuccess"):
            raise BufferError(f"FAILED: Buffer {field}: {res.get('message') or r.get('errors')}")
        return res.get("post") or res

    def create(self, inp: dict) -> dict:
        return self._mutate(CREATE, "createPost", {"channelId": self.ids()[1], **inp})

    def edit(self, inp: dict) -> dict:
        return self._mutate(EDIT, "editPost", inp)

    def delete(self, post_id: str) -> None:
        self._mutate(DELETE, "deletePost", {"id": post_id})


class FakeBuffer:
    """MT_BUFFER=fake:<file.json>: {"posts": [{id, dueAt, text, schedulingType, status}]}, saved back on change."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text())
        self.calls: list[tuple[str, dict]] = []

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=1, ensure_ascii=False))

    def ids(self) -> tuple[str, str]:
        return "org-1", "ch-ig"

    def posts(self, status: str = "scheduled") -> list[dict]:
        return [dict(p) for p in self.data["posts"] if p.get("status", "scheduled") == status]

    def create(self, inp: dict) -> dict:
        post = {
            "id": f"b{len(self.data['posts']) + 1}",
            "dueAt": inp["dueAt"],
            "text": inp["text"],
            "schedulingType": inp["schedulingType"],
            "status": "scheduled",
            "assets": inp.get("assets"),
        }
        self.data["posts"].append(post)
        self.calls.append(("create", inp))
        self._save()
        return post

    def edit(self, inp: dict) -> dict:
        for p in self.data["posts"]:
            if p["id"] == inp["id"]:
                p.update({k: v for k, v in inp.items() if k in ("text", "schedulingType", "dueAt", "assets")})
                self.calls.append(("edit", inp))
                self._save()
                return p
        raise BufferError("FAILED: Buffer editPost: not found")

    def delete(self, post_id: str) -> None:
        self.data["posts"] = [p for p in self.data["posts"] if p["id"] != post_id]
        self.calls.append(("delete", {"id": post_id}))
        self._save()


def buffer_from_env(cfg):
    spec = os.environ.get("MT_BUFFER", "")
    if spec.startswith("fake:"):
        return FakeBuffer(Path(spec[5:]))
    key = os.environ.get("BUFFER_API_KEY", "").strip()
    if not key:
        raise Refused("REFUSED: BUFFER_API_KEY isn't on the secret card (SETUP.md, section 17).")
    return BufferClient(cfg.buffer_api, key)


# --- the calendar --------------------------------------------------------------------------------------
class Calendar:
    """schedule.json and stories.json from the social checkout, validated."""

    def __init__(self, root: Path, bucket: str):
        self.root, self.bucket = Path(root), bucket
        ig = self.root / "instagram"
        if not (ig / "schedule.json").exists():
            raise Refused(
                f"REFUSED: no social checkout at {root} (instagram/schedule.json missing). "
                "Clone fairgradient-ai/monstertenmath_social there (SETUP.md, section 17)."
            )
        self.feed = json.loads((ig / "schedule.json").read_text(encoding="utf-8"))
        stories = ig / "stories.json"
        self.stories = json.loads(stories.read_text(encoding="utf-8")) if stories.exists() else []
        self._validate()

    def _validate(self) -> None:
        for kind, entries, need in (
            ("schedule.json", self.feed, FEED_FIELDS),
            ("stories.json", self.stories, STORY_FIELDS),
        ):
            for i, e in enumerate(entries):
                if e.get("hold"):
                    continue
                missing = [f for f in need if not e.get(f)]
                if missing:
                    raise Refused(
                        f"REFUSED: {kind} entry {i} ({e.get('name', '?')}) has no {', '.join(missing)}. "
                        "Fix it by pull request."
                    )
        keys = [self.key(e, "feed") for e in self.feed if not e.get("hold")]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise Refused(f"REFUSED: schedule.json uses {', '.join(sorted(dupes))} twice. Fix it by pull request.")

    @staticmethod
    def key(e: dict, kind: str) -> str:
        return e["name"].split()[0] if kind == "feed" else f"{e['name']}@{e['dueAt'][:16]}"

    def entries(self) -> list[tuple[str, str, dict]]:
        """(kind, key, entry) for every entry not on hold."""
        out = [("feed", self.key(e, "feed"), e) for e in self.feed if not e.get("hold")]
        out += [("story", self.key(e, "story"), e) for e in self.stories if not e.get("hold")]
        return out

    def commit(self) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return r.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    def url(self, path: str) -> str:
        url = f"https://storage.googleapis.com/{self.bucket}/{path}"
        local = self.root / path
        if local.exists():  # a new link whenever the file changes, so Buffer fetches it again
            url += "?v=" + hashlib.sha1(local.read_bytes()).hexdigest()[:10]
        return url

    def text(self, kind: str, e: dict) -> str:
        if kind == "feed":
            return e["text"]
        tag = f"[Story {e['name']}]"
        if e.get("publish") == "reminder":
            return "Locked until launch: it posts itself once the gate opens. Nothing to add. " + tag
        return "Posts by itself: nothing to do. " + tag

    def input(self, kind: str, e: dict) -> dict:
        """The Buffer CreatePostInput fields (without channelId), as schedule.py and stories.py build them."""
        mode = "notification" if e.get("publish") == "reminder" else "automatic"
        if kind == "story":
            asset = (
                {"video": {"url": self.url(e["media"])}}
                if e["media"].endswith(".mp4")
                else {"image": {"url": self.url(e["media"])}}
            )
            ig = {
                "type": "story",
                "isAiGenerated": bool(e.get("ai")),
                "shouldShareToFeed": False,
                "stickerFields": {"text": "", "music": "", "other": ""},
            }
            assets = [asset]
        else:
            if e["type"] == "reel":
                thumb = e.get("thumb_ms", 0 if e.get("cover") else 10000)
                assets = [{"video": {"url": self.url(e["media"][0]), "metadata": {"thumbnailOffset": thumb}}}]
            else:
                assets = [
                    {
                        "image": {
                            "url": self.url(m),
                            **({"metadata": {"altText": e["alt"]}} if e.get("alt") and i == 0 else {}),
                        }
                    }
                    for i, m in enumerate(e["media"])
                ]
            ig = {
                "type": "post" if e["type"] == "carousel" else e["type"],
                "isAiGenerated": bool(e.get("ai")),
                "shouldShareToFeed": True,
            }
        return {
            "text": self.text(kind, e),
            "mode": "customScheduled",
            "dueAt": e["dueAt"],
            "schedulingType": mode,
            "assets": assets,
            "metadata": {"instagram": ig},
        }

    def media_paths(self, kind: str, e: dict) -> list[str]:
        return [e["media"]] if kind == "story" else list(e["media"])


def match_key(kind: str, e: dict) -> tuple[str, str]:
    if kind == "story":
        return (e["dueAt"][:16], f"[Story {e['name']}]")
    return (e["dueAt"][:16], e["text"][:40])


def post_key(p: dict) -> tuple[str, str] | None:
    m = STORY_TAG.search(p.get("text") or "")
    return (p["dueAt"][:16], m.group(0)) if m else (p["dueAt"][:16], (p.get("text") or "")[:40])


# --- the bridge ----------------------------------------------------------------------------------------
class Social:
    def __init__(self, cfg, kn, ledger, buffer, calendar: Calendar, phase: str, pricing: str, now: datetime, head=None):
        self.cfg, self.kn, self.ledger, self.buffer, self.cal = cfg, kn, ledger, buffer, calendar
        self.phase, self.pricing, self.now = phase, pricing, now
        self.db = ledger.db
        self.head = head or self._head_ok

    def _future(self, e: dict, minutes: int = 10) -> bool:
        return _dt(e["dueAt"]) > self.now + timedelta(minutes=minutes)

    def _missing(self) -> dict[str, str]:
        return json.loads(self.ledger.kv_get("buffer.missing") or "{}")

    def _set_missing(self, missing: dict[str, str]) -> None:
        self.ledger.kv_set("buffer.missing", json.dumps(missing, sort_keys=True))

    def _entry_hash(self, kind: str, e: dict) -> str:
        files = []
        for path in self.cal.media_paths(kind, e):
            local = self.cal.root / path
            files.append(hashlib.sha1(local.read_bytes()).hexdigest()[:10] if local.exists() else path)
        return _h({k: v for k, v in e.items() if k not in ("et",)}, files)

    @staticmethod
    def _sent_hash(text: str, due_at: str, mode: str) -> str:
        return _h(text, due_at[:16], mode)

    def _record(self, post: dict, kind: str, key: str | None, entry_hash: str | None, source: str) -> None:
        self.db.execute(
            "INSERT INTO buffer_posts (buffer_id, kind, key, due_at, text_start, commit_sha, created_at, main_hash, "
            "sent_hash, updated_at, source) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(buffer_id) DO UPDATE SET "
            "key=excluded.key, due_at=excluded.due_at, text_start=excluded.text_start, commit_sha=excluded.commit_sha, "
            "main_hash=excluded.main_hash, sent_hash=excluded.sent_hash, updated_at=excluded.updated_at, "
            "missing_since=NULL",
            (
                post["id"],
                kind,
                key,
                post["dueAt"],
                (post.get("text") or "")[:60],
                self.cal.commit(),
                self.now.isoformat(),
                entry_hash,
                self._sent_hash(post.get("text") or "", post["dueAt"], post.get("schedulingType") or ""),
                self.now.isoformat(),
                source,
            ),
        )

    def _head_ok(self) -> None:
        root = str(self.cal.root)
        try:
            branch = subprocess.run(
                ["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=30
            ).stdout.strip()
            dirty = subprocess.run(
                ["git", "-C", root, "status", "--porcelain", "--untracked-files=no"],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as e:
            raise Refused(f"REFUSED: can't read the social checkout with git ({e}).") from None
        if branch != "main":
            raise Refused(
                f"REFUSED: the social checkout is on {branch or '?'}, not main. Only merged posts go to Buffer."
            )
        if dirty:
            raise Refused(
                "REFUSED: the social checkout has local changes. Only merged posts go to Buffer: "
                "git -C " + root + " checkout -- . to drop them."
            )

    def pull(self) -> str:
        self.head()
        r = subprocess.run(
            ["git", "-C", str(self.cal.root), "pull", "--ff-only", "--quiet", "origin", "main"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            raise Refused(f"REFUSED: git pull of main failed: {(r.stderr or r.stdout).strip()[:200]}")
        self.cal = Calendar(self.cal.root, self.cal.bucket)
        return self.cal.commit()

    # --- adopt -----------------------------------------------------------------------------------------
    def adopt(self, redo: bool = False) -> list[str]:
        if self.ledger.kv_get("buffer.adopted_at") and not redo:
            raise Refused(
                f"REFUSED: Buffer was adopted at {self.ledger.kv_get('buffer.adopted_at')}. "
                "Use buffer adopt --redo only if the owner asks."
            )
        posts = self.buffer.posts("scheduled")
        by_key: dict[tuple[str, str], dict] = {}
        for p in posts:
            by_key.setdefault(post_key(p), p)
        entries = self.cal.entries()
        expected = [(k, key, e) for k, key, e in entries if self._future(e)]
        past = [(k, key, e) for k, key, e in entries if not self._future(e)]
        adopted, missing, used = [], [], set()
        for kind, key, e in expected:
            p = by_key.get(match_key(kind, e))
            if p is None:
                missing.append((kind, key, e))
            else:
                adopted.append((kind, key, e, p))
                used.add(p["id"])
        held = sum(1 for e in self.cal.feed + self.cal.stories if e.get("hold"))
        local = self.now.astimezone(self.cfg.tz)
        org, ch = self.buffer.ids()
        lines = [f"BUFFER ADOPT · {local:%a %d %b %H:%M} ET · org {org[:6]}… · channel {ch[:10]}"]
        if expected and not adopted:
            lines.append(
                f"REFUSED: expected {len(expected)} posts in Buffer and found none of them. Nothing recorded. "
                "Run buffer status and check the Buffer key is for the Monster Ten organization."
            )
            return lines
        if redo:
            self.db.execute("DELETE FROM buffer_posts")
        for kind, key, e, p in adopted:
            self._record(p, kind, key, self._entry_hash(kind, e), "adopted")
        others = [p for p in posts if p["id"] not in used]
        for p in others:
            self._record(p, "foreign", None, None, "foreign")
        self._set_missing({key: self.now.isoformat() for _, key, _ in missing})
        self.ledger.kv_set("buffer.adopted_at", self.now.isoformat())
        feed = [key for k, key, *_ in adopted if k == "feed"]
        lines.append(
            f"ADOPTED {len(adopted)} of {len(expected)} expected (entries due after "
            f"{(self.now + timedelta(minutes=10)).astimezone(self.cfg.tz):%H:%M} ET today; "
            f"held entries skipped: {held})"
        )
        lines.append(f"  feed {len(feed)}: " + _span(feed) + f" · Stories {len(adopted) - len(feed)}")
        lines.append(f"PAST (due before now, not expected in Buffer): {len(past)}")
        lines.append(
            "MISSING (expected, not in Buffer): "
            + (", ".join(key for _, key, _ in missing[:20]) or "none")
            + (" · say buffer restore <key> to bring one back (your tap)" if missing else "")
        )
        lines.append(
            "IN BUFFER BUT NOT ADOPTED (foreign, never touched): "
            + (", ".join(f"{p['dueAt'][:16]} {(p.get('text') or '')[:30]!r}" for p in others[:10]) or "none")
        )
        return lines

    # --- status and audit ------------------------------------------------------------------------------
    def status(self) -> list[str]:
        posts = self.buffer.posts("scheduled")
        org, ch = self.buffer.ids()
        modes: dict[str, int] = {}
        for p in posts:
            modes[p.get("schedulingType") or "?"] = modes.get(p.get("schedulingType") or "?", 0) + 1
        adopted = self.ledger.kv_get("buffer.adopted_at")
        lines = [
            f"BUFFER · org {org[:6]}… · channel {ch[:10]} · {len(posts)} scheduled ("
            + ", ".join(f"{n} {m}" for m, n in sorted(modes.items()))
            + ")",
            f"calendar: main {self.cal.commit()} · {len(self.cal.entries())} entries not on hold · "
            + (f"adopted {adopted[:16]}" if adopted else "NOT ADOPTED YET: run buffer adopt once"),
            f"bridge: {'on' if self.cfg.buffer_enabled else 'off ([buffer] enabled = false)'}",
        ]
        nxt = sorted(posts, key=lambda p: p["dueAt"])[:5]
        for p in nxt:
            row = self.db.execute("SELECT key FROM buffer_posts WHERE buffer_id=?", (p["id"],)).fetchone()
            when = _dt(p["dueAt"]).astimezone(self.cfg.tz)
            lines.append(
                f"  next {when:%a %d %b %H:%M} · {(row['key'] if row and row['key'] else 'not adopted')} · "
                f"{p.get('schedulingType')}"
            )
        return lines

    def audit(self) -> list[str]:
        """Read-only. What the QA team's buffer_check doesn't cover: the AI label, same-minute clashes, the phase
        and price each post will meet, and the bridge's own view (missing, edited in the app, changed on both)."""
        posts = self.buffer.posts("scheduled")
        by_id = {p["id"]: p for p in posts}
        lines: list[str] = []
        minutes: dict[str, list[str]] = {}
        for p in posts:
            minutes.setdefault(p["dueAt"][:16], []).append((p.get("text") or "")[:30])
        for minute, texts in sorted(minutes.items()):
            if len(texts) > 1:
                lines.append(f"SAME MINUTE {minute}: {len(texts)} posts ({'; '.join(texts)})")
        for kind, key, e in self.cal.entries():
            if not self._future(e, 0):
                continue
            media = " ".join(self.cal.media_paths(kind, e))
            if re.search(r"/(reels|stories)/", media) and not e.get("ai"):
                lines.append(f'AI LABEL {key}: AI-made media without "ai": true, so Buffer won\'t set the label')
            if kind == "feed":
                ph = phase_at(e["dueAt"])
                bad = policy.check(
                    e["text"],
                    policy.Context(ph, "caption", stores=self.cfg.stores, pricing=self.pricing),
                    self.kn.rules,
                )
                if bad and not (e.get("publish") == "reminder" and all(v.id == "building-no-cta" for v in bad)):
                    lines.append(f"NO LONGER FITS {key} ({ph} at {e['dueAt'][:16]}): {bad[0]}")
        for row in self.db.execute("SELECT * FROM buffer_posts WHERE key IS NOT NULL"):
            p = by_id.get(row["buffer_id"])
            entry = next(((k, e) for k, key, e in self.cal.entries() if key == row["key"]), None)
            if p is None:
                if _dt(row["due_at"]) > self.now:
                    lines.append(
                        f"MISSING IN BUFFER {row['key']} (due {row['due_at'][:16]}): deleted in the app? "
                        "buffer restore <key> brings it back (your tap)"
                    )
                continue
            app_edit = (
                self._sent_hash(p.get("text") or "", p["dueAt"], p.get("schedulingType") or "") != row["sent_hash"]
            )
            main_edit = entry is not None and self._entry_hash(*entry) != row["main_hash"]
            if app_edit and main_edit:
                lines.append(
                    f"CHANGED ON BOTH SIDES {row['key']}: buffer push {row['key']} sends main's version (your tap)"
                )
            elif app_edit:
                lines.append(f"EDITED IN THE BUFFER APP {row['key']}: left as it is; buffer push {row['key']} to undo")
            elif main_edit:
                lines.append(f"MAIN CHANGED {row['key']}: the next buffer sync updates it")
        for key in self._missing():
            lines.append(f"NOT IN BUFFER {key}: missing since adopt; buffer restore {key} (your tap)")
        head = f"BUFFER AUDIT · {len(posts)} scheduled · main {self.cal.commit()}"
        return [head, *(lines or ["nothing to fix"])]

    # --- sync ------------------------------------------------------------------------------------------
    def sync(self, dry: bool = False, pull: bool = True, check_media=None) -> list[str]:
        if not self.ledger.kv_get("buffer.adopted_at"):
            raise Refused("REFUSED: run buffer adopt once first, so sync knows what's already in Buffer.")
        if not self.cfg.buffer_enabled and not dry:
            raise Refused(
                "REFUSED: the Buffer bridge is off ([buffer] enabled = false). "
                "buffer sync --dry shows what it would do."
            )
        commit = self.pull() if pull else self.cal.commit()
        check_media = check_media or _media_ok
        posts = {p["id"]: p for p in self.buffer.posts("scheduled")}
        sent_texts = {(p.get("text") or "")[:40] for p in self.buffer.posts("sent")}
        known = {r["key"]: r for r in self.db.execute("SELECT * FROM buffer_posts WHERE key IS NOT NULL")}
        missing = self._missing()
        minutes = {p["dueAt"][:16] for p in posts.values()}
        lines, created, updated = [], 0, 0
        for kind, key, e in self.cal.entries():
            if not self._future(e):
                continue
            row = known.get(key)
            h = self._entry_hash(kind, e)
            if key in missing:
                continue  # reported by audit; restore is the owner's tap
            if row is None:
                if kind == "feed" and e["text"][:40] in sent_texts:
                    lines.append(f"SKIP {key}: a post with this opening already went out")
                    continue
                if e["dueAt"][:16] in minutes:
                    lines.append(f"SKIP {key}: another post is already at {e['dueAt'][:16]} (no two in one minute)")
                    continue
                bad = [path for path in self.cal.media_paths(kind, e) if not check_media(self.cal.url(path))]
                if bad:
                    lines.append(f"SKIP {key}: media isn't public yet ({bad[0]})")
                    continue
                if dry:
                    lines.append(f"WOULD CREATE {key} at {e['dueAt'][:16]}")
                    continue
                post = self.buffer.create(self.cal.input(kind, e))
                post.setdefault("text", self.cal.text(kind, e))
                self._record(post, kind, key, h, "grok")
                minutes.add(e["dueAt"][:16])
                created += 1
                lines.append(f"CREATED {key} at {e['dueAt'][:16]}")
                continue
            p = posts.get(row["buffer_id"])
            if p is None:
                lines.append(f"MISSING {key}: in the ledger but not in Buffer; never re-created (buffer restore {key})")
                continue
            if h == row["main_hash"]:
                continue
            app_edit = (
                self._sent_hash(p.get("text") or "", p["dueAt"], p.get("schedulingType") or "") != row["sent_hash"]
            )
            if app_edit:
                lines.append(f"CHANGED ON BOTH SIDES {key}: left as it is (buffer push {key}, your tap)")
                continue
            if dry:
                lines.append(f"WOULD UPDATE {key}")
                continue
            inp = self.cal.input(kind, e)
            post = self.buffer.edit(
                {
                    "id": p["id"],
                    **{k: inp[k] for k in ("text", "dueAt", "schedulingType", "assets", "metadata", "mode")},
                }
            )
            post = {**p, **post, "text": inp["text"], "dueAt": inp["dueAt"], "schedulingType": inp["schedulingType"]}
            self._record(post, kind, key, h, row["source"])
            updated += 1
            lines.append(f"UPDATED {key}")
        verb = "DRY RUN" if dry else "SYNCED"
        return [f"BUFFER {verb} · main {commit} · {created} created · {updated} updated", *(lines or ["nothing to do"])]

    # --- the owner's taps ------------------------------------------------------------------------------
    def _row(self, key: str):
        row = self.db.execute("SELECT * FROM buffer_posts WHERE key=?", (key,)).fetchone()
        if row is None:
            raise Refused(f"REFUSED: {key} isn't a Buffer post the Bot knows. buffer status lists them.")
        return row

    def _entry(self, key: str) -> tuple[str, dict]:
        for kind, k, e in self.cal.entries():
            if k == key:
                return kind, e
        raise Refused(f"REFUSED: {key} isn't in the calendar on main.")

    def remind(self, key: str, owner_tapped: bool) -> str:
        _tap(owner_tapped, f"buffer remind {key}")
        row = self._row(key)
        self.buffer.edit({"id": row["buffer_id"], "schedulingType": "notification"})
        self.db.execute("UPDATE buffer_posts SET sent_hash=NULL WHERE buffer_id=?", (row["buffer_id"],))
        return f"REMINDER {key}: Buffer now waits for your tap in the app before it posts. Fix the calendar by PR too."

    def delete(self, key: str, owner_tapped: bool) -> str:
        _tap(owner_tapped, f"buffer delete {key}")
        row = self._row(key)
        self.buffer.delete(row["buffer_id"])
        missing = self._missing()
        missing[key] = self.now.isoformat()
        self._set_missing(missing)
        self.db.execute("DELETE FROM buffer_posts WHERE buffer_id=?", (row["buffer_id"],))
        return (
            f"DELETED {key} from Buffer. Sync won't re-create it; "
            "take it out of the calendar by PR (or buffer restore)."
        )

    def restore(self, key: str, owner_tapped: bool) -> str:
        _tap(owner_tapped, f"buffer restore {key}")
        kind, e = self._entry(key)
        if not self._future(e):
            raise Refused(f"REFUSED: {key} was due at {e['dueAt'][:16]}: Buffer would publish it at once.")
        post = self.buffer.create(self.cal.input(kind, e))
        post.setdefault("text", self.cal.text(kind, e))
        self._record(post, kind, key, self._entry_hash(kind, e), "restored")
        missing = self._missing()
        missing.pop(key, None)
        self._set_missing(missing)
        return f"RESTORED {key} at {e['dueAt'][:16]}."

    def push(self, key: str, owner_tapped: bool) -> str:
        _tap(owner_tapped, f"buffer push {key}")
        row = self._row(key)
        kind, e = self._entry(key)
        inp = self.cal.input(kind, e)
        post = self.buffer.edit(
            {
                "id": row["buffer_id"],
                **{k: inp[k] for k in ("text", "dueAt", "schedulingType", "assets", "metadata", "mode")},
            }
        )
        post = {
            "id": row["buffer_id"],
            **post,
            "text": inp["text"],
            "dueAt": inp["dueAt"],
            "schedulingType": inp["schedulingType"],
        }
        self._record(post, kind, key, self._entry_hash(kind, e), row["source"])
        return f"PUSHED {key}: Buffer now has main's version."


def _tap(owner_tapped: bool, what: str) -> None:
    if not owner_tapped:
        raise Refused(f"REFUSED: {what} is the owner's tap: run.sh {what} --owner-tapped.")


def _span(keys: list[str]) -> str:
    if not keys:
        return "none"
    nums = sorted(keys, key=lambda k: int(k.lstrip("#")) if k.lstrip("#").isdigit() else 0)
    return f"{nums[0]} … {nums[-1]}" if len(nums) > 1 else nums[0]


def _media_ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False
