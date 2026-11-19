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
