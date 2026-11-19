"""The Instagram client's requests and error handling, with no network."""

import io
import json
import urllib.error
import urllib.parse

import pytest

from monsterbot.channels.instagram import InstagramChannel
from monsterbot.errors import ChannelError


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append(req)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return Resp(json.dumps(r).encode())


def http_error(code, body):
    return urllib.error.HTTPError(
        "https://graph.instagram.com/x", code, "err", {}, io.BytesIO(json.dumps(body).encode())
    )


def channel(opener):
    return InstagramChannel("SECRET-TOKEN", opener=opener, version="v24.0")


def test_token_goes_in_the_header_never_the_url():
    op = Opener({"user_id": "1", "username": "monstertenmath", "account_type": "BUSINESS"})
    me = channel(op).me()
    req = op.requests[0]
    assert me.username == "monstertenmath"
    assert req.get_header("Authorization") == "Bearer SECRET-TOKEN"
    assert "SECRET-TOKEN" not in req.full_url
    assert req.full_url.startswith("https://graph.instagram.com/v24.0/me?")


def test_comments_are_flattened_and_paged():
    page1 = {
        "data": [
            {
                "id": "c1",
                "text": "3!",
                "username": "a",
                "timestamp": "2026-11-20T01:35:00+0000",
                "replies": {
                    "data": [{"id": "r1", "text": "yes", "username": "b", "timestamp": "2026-11-20T01:36:00+0000"}]
                },
            }
        ],
        "paging": {"next": "https://graph.instagram.com/v24.0/m3/comments?after=X"},
    }
    page2 = {"data": [{"id": "c2", "text": "7", "username": "c", "timestamp": "2026-11-20T01:37:00+0000"}]}
    op = Opener(page1, page2)
    out = channel(op).comments("m3")
    assert [(c.id, c.parent_id) for c in out] == [("c1", None), ("r1", "c1"), ("c2", None)]
    assert op.requests[1].full_url.endswith("after=X")
    assert op.requests[1].get_header("Authorization") == "Bearer SECRET-TOKEN"


def test_reply_posts_form_data():
    op = Opener({"id": "new1"})
    assert channel(op).reply("c1", "Yes! 7 and 3 make 10.") == "new1"
    req = op.requests[0]
    assert req.get_method() == "POST" and req.full_url.endswith("/c1/replies")
    assert urllib.parse.parse_qs(req.data.decode()) == {"message": ["Yes! 7 and 3 make 10."]}


@pytest.mark.parametrize(
    "status, body, kind",
    [
        (400, {"error": {"code": 190, "message": "Error validating access token"}}, "token"),
        (400, {"error": {"code": 4, "message": "Application request limit reached"}}, "rate"),
        (403, {"error": {"code": 10, "message": "Permission denied"}}, "permission"),
        (400, {"error": {"code": 100, "message": "Unsupported get request"}}, "bad_request"),
    ],
)
def test_errors_are_sorted(status, body, kind):
    with pytest.raises(ChannelError) as e:
        channel(Opener(http_error(status, body))).me()
    assert e.value.kind == kind and not e.value.ambiguous


def test_a_timeout_on_a_post_is_ambiguous_but_not_on_a_read():
    with pytest.raises(ChannelError) as e:
        channel(Opener(TimeoutError())).reply("c1", "hi")
    assert e.value.ambiguous
    with pytest.raises(ChannelError) as e:
        channel(Opener(TimeoutError())).me()
    assert not e.value.ambiguous
    with pytest.raises(ChannelError) as e:
        channel(Opener(urllib.error.URLError("refused"))).reply("c1", "hi")
    assert not e.value.ambiguous  # never left the machine


def test_refresh_uses_the_documented_endpoint():
    op = Opener({"access_token": "NEW", "token_type": "bearer", "expires_in": 5184000})
    assert channel(op).refresh_token() == ("NEW", 5184000)
    req = op.requests[0]
    assert req.full_url.startswith("https://graph.instagram.com/refresh_access_token?")
    assert "grant_type=ig_refresh_token" in req.full_url
    assert req.get_header("Authorization") is None


def test_no_token_no_client():
    with pytest.raises(ChannelError) as e:
        InstagramChannel("")
    assert e.value.kind == "token"


# --- Facebook-side tokens (the dashboard's "API setup with Unified login") -------------------------------
from monsterbot.channels.instagram import FACEBOOK_HOST, INSTAGRAM_HOST, host_for, is_facebook_token  # noqa: E402


def test_the_token_picks_the_api_address():
    assert is_facebook_token("EAAGm0PX4ZCpsBA...") and not is_facebook_token("IGAAx...")
    assert host_for("EAAG...") == FACEBOOK_HOST
    assert host_for("IGAA...") == INSTAGRAM_HOST
    assert host_for("EAAG...", "https://example.test") == "https://example.test"


def fb(opener, ig_user_id="17841400000000000"):
    return InstagramChannel("EAAsecret", host=FACEBOOK_HOST, opener=opener, ig_user_id=ig_user_id)


def test_facebook_token_uses_our_instagram_id():
    op = Opener({"id": "17841400000000000", "username": "monstertenmath", "followers_count": 312}, {"data": []})
    ch = fb(op)
    me = ch.me()
    ch.recent_media(5)
    assert me.username == "monstertenmath" and me.account_type == "BUSINESS"
    assert op.requests[0].full_url.startswith("https://graph.facebook.com/v24.0/17841400000000000?")
    assert op.requests[1].full_url.startswith("https://graph.facebook.com/v24.0/17841400000000000/media?")
    assert "EAAsecret" not in op.requests[0].full_url


def test_facebook_token_finds_the_account_through_its_page():
    op = Opener(
        {"data": [{"id": "page1", "instagram_business_account": {"id": "1784", "username": "monstertenmath"}}]},
        {"id": "1784", "username": "monstertenmath"},
    )
    assert fb(op, ig_user_id="").me().id == "1784"
    assert "/me/accounts?" in op.requests[0].full_url


def test_facebook_token_without_an_account_says_what_to_set():
    no_pages = {"data": []}
    no_instagram = {"data": {"granular_scopes": [{"scope": "pages_show_list", "target_ids": ["page1"]}]}}
    with pytest.raises(ChannelError) as e:
        fb(Opener(no_pages, no_instagram), ig_user_id="").me()
    assert "ig_user_id" in str(e.value) and "not a link" in str(e.value)


# A system user from the dashboard's Unified login is given the Instagram account itself, with no Facebook Page:
# me/accounts is empty, and only Meta's record of the token names the account.
SYSTEM_USER_TOKEN = {
    "data": {
        "type": "SYSTEM_USER",
        "is_valid": True,
        "granular_scopes": [
            {"scope": "instagram_basic", "target_ids": ["17841400000000000"]},
            {"scope": "instagram_manage_comments", "target_ids": ["17841400000000000"]},
            {"scope": "business_management", "target_ids": ["4768245130126459"]},
        ],
    }
}


def fb_named(opener, ig_user_id=""):
    return InstagramChannel(
        "EAAsecret", host=FACEBOOK_HOST, opener=opener, ig_user_id=ig_user_id, username="monstertenmath"
    )


def test_a_system_user_token_without_a_page_finds_its_account():
    op = Opener(
        {"data": []},
        SYSTEM_USER_TOKEN,
        {"id": "17841400000000000", "username": "monstertenmath"},
        {"id": "17841400000000000", "username": "monstertenmath", "followers_count": 0},
        {"data": []},
    )
    ch = fb_named(op)
    me = ch.me()
    ch.recent_media(1)
    assert me.id == "17841400000000000" and me.username == "monstertenmath"
    urls = [r.full_url for r in op.requests]
    assert "/me/accounts?" in urls[0]
    assert urls[1].startswith("https://graph.facebook.com/v24.0/debug_token?")
    assert urls[2].startswith("https://graph.facebook.com/v24.0/17841400000000000?")
    assert urls[4].startswith("https://graph.facebook.com/v24.0/17841400000000000/media?")
    assert len(op.requests) == 5  # found once, then remembered
    # Only debug_token carries the token in its query (Meta's endpoint takes it no other way).
    assert all("EAAsecret" not in u for i, u in enumerate(urls) if i != 1)


def test_the_configured_account_is_taken_and_another_never_used():
    token = {
        "data": {
            "granular_scopes": [
                {
                    "scope": "instagram_basic",
                    "target_ids": ["2709766512793216", "17841400000000001", "17841400000000000"],
                }
            ]
        }
    }
    op = Opener(
        {"data": [{"id": "page1", "instagram_business_account": {"id": "17841400000000001", "username": "otheracct"}}]},
        token,
        http_error(400, {"error": {"code": 100, "message": "Tried accessing nonexisting field (username)"}}),
        {"id": "17841400000000000", "username": "MonsterTenMath"},
    )
    assert fb_named(op).find_account() == "17841400000000000"
    # The other account, already seen on the Page, isn't looked up twice.
    assert len(op.requests) == 4


def test_a_token_for_another_account_names_it_and_stops():
    op = Opener(
        {"data": [{"id": "page1", "instagram_business_account": {"id": "1784", "username": "otheracct"}}]},
        {"data": {"granular_scopes": []}},
    )
    with pytest.raises(ChannelError) as e:
        fb_named(op).me()
    assert "@otheracct, not @monstertenmath" in str(e.value)
    assert len(op.requests) == 2  # never read as if it were ours


def test_a_token_without_pages_still_asks_meta():
    op = Opener(
        http_error(400, {"error": {"code": 100, "message": "nonexisting field (accounts)"}}),
        SYSTEM_USER_TOKEN,
        {"id": "17841400000000000", "username": "monstertenmath"},
    )
    assert fb_named(op).find_account() == "17841400000000000"


def test_a_lookup_that_fails_on_the_token_or_network_isnt_hidden():
    with pytest.raises(ChannelError) as e:
        fb_named(Opener({"data": []}, http_error(400, {"error": {"code": 190, "message": "expired"}}))).me()
    assert e.value.kind == "token"


def test_a_configured_id_that_isnt_an_account_says_to_clear_it():
    # The app's id, copied out of the dashboard's address bar.
    err = http_error(400, {"error": {"code": 100, "message": "Tried accessing nonexisting field (username)"}})
    with pytest.raises(ChannelError) as e:
        fb_named(Opener(err), ig_user_id="2709766512793216").me()
    msg = str(e.value)
    assert "ig_user_id 2709766512793216" in msg and 'back to ""' in msg


def test_the_scout_finds_the_account_the_same_way():
    from monsterbot.channels.facebook import FacebookGraph

    op = Opener(
        {"data": []},
        SYSTEM_USER_TOKEN,
        {"id": "17841400000000000", "username": "monstertenmath"},
        {"business_discovery": {"username": "creator", "followers_count": 12000}},
    )
    graph = FacebookGraph("EAAsecret", username="monstertenmath", opener=op)
    profile = graph.business_discovery("creator")
    assert profile is not None and profile.followers == 12000
    assert op.requests[3].full_url.startswith("https://graph.facebook.com/v24.0/17841400000000000?")
