"""Tests for the MoodleClient chokepoint: the HTTP-200-error parse is the star."""
from __future__ import annotations

import httpx
import pytest

from moodle_mcp import client as mod
from moodle_mcp.client import (
    MoodleAPIError,
    MoodleAuthError,
    MoodleClient,
    MoodleFunctionUnavailable,
    flatten_params,
)


def make_client(handler, **kw) -> MoodleClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return MoodleClient("tok", base_url="https://m.test", http_client=http, **kw)


# -- flatten ---------------------------------------------------------------
def test_flatten_scalars_lists_dicts():
    out = flatten_params({"courseids": [23189, 7], "flag": True, "none": None})
    assert out == {"courseids[0]": "23189", "courseids[1]": "7", "flag": "1"}


def test_flatten_list_of_dicts():
    out = flatten_params({"options": [{"name": "x", "value": 1}]})
    assert out == {"options[0][name]": "x", "options[0][value]": "1"}


# -- the 200-with-exception gotcha ----------------------------------------
def test_ok_response_returns_body():
    c = make_client(lambda r: httpx.Response(200, json={"userid": 5, "functions": []}))
    assert c.site_info()["userid"] == 5


def test_invalidtoken_raises_auth_error():
    body = {"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "bad"}
    c = make_client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(MoodleAuthError):
        c.get_course_contents(1)


def test_accessexception_raises_unavailable():
    body = {"exception": "webservice_access_exception", "errorcode": "accessexception", "message": "no"}
    c = make_client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(MoodleFunctionUnavailable):
        c.get_quizzes_by_courses([1])


def test_other_errorcode_raises_api_error():
    body = {"exception": "x", "errorcode": "somethingelse", "message": "boom"}
    c = make_client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(MoodleAPIError):
        c.get_course_contents(1)


def test_malformed_body_raises_api_error():
    c = make_client(lambda r: httpx.Response(200, content=b"not json"))
    with pytest.raises(MoodleAPIError):
        c.get_course_contents(1)


def test_non_200_raises_api_error():
    c = make_client(lambda r: httpx.Response(500))
    with pytest.raises(MoodleAPIError):
        c.get_course_contents(1)


def test_network_error_retries_then_raises(monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        raise httpx.ConnectError("down")

    c = make_client(handler, max_retries=3)
    with pytest.raises(MoodleAPIError):
        c.get_course_contents(1)
    assert calls["n"] == 3  # retried the full budget


def test_site_info_caches_and_has_function():
    hits = {"n": 0}

    def handler(_req):
        hits["n"] += 1
        return httpx.Response(200, json={"userid": 1, "functions": [{"name": "core_x"}]})

    c = make_client(handler)
    assert c.has_function("core_x")
    assert not c.has_function("nope")
    c.site_info()  # cached — no second HTTP call
    assert hits["n"] == 1
