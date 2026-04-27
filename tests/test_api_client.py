"""Tests for zoom_cli.api.client — ApiClient + token lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from zoom_cli.api import client as client_mod
from zoom_cli.api import oauth
from zoom_cli.api.client import API_BASE_URL, ApiClient, ZoomApiError
from zoom_cli.auth import S2SCredentials


def _creds() -> S2SCredentials:
    return S2SCredentials(account_id="acc-1", client_id="cid", client_secret="csec")


def _fresh_token(value: str = "tok-fresh", *, lifetime_seconds: int = 3600) -> oauth.AccessToken:
    return oauth.AccessToken(
        value=value,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=lifetime_seconds),
        scopes=("user:read:user",),
    )


def test_get_injects_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "user-123", "email": "u@example.com"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token("tok-X"))

    with ApiClient(_creds(), http_client=http) as c:
        result = c.get("/users/me")

    assert result == {"id": "user-123", "email": "u@example.com"}
    assert captured["url"] == f"{API_BASE_URL}/users/me"
    assert captured["auth"] == "Bearer tok-X"


def test_request_caches_token_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single CLI invocation hitting two endpoints should fetch one token,
    not two. Pin this so a future refactor can't accidentally regress."""
    fetch_calls = {"n": 0}

    def fake_fetch(*_a, **_k):
        fetch_calls["n"] += 1
        return _fresh_token()

    monkeypatch.setattr(oauth, "fetch_access_token", fake_fetch)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler))

    with ApiClient(_creds(), http_client=http) as c:
        c.get("/users/me")
        c.get("/users/123")
        c.get("/meetings/999")

    assert fetch_calls["n"] == 1


def test_request_refetches_token_after_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_calls = {"n": 0}

    def fake_fetch(*_a, **_k):
        fetch_calls["n"] += 1
        # First call returns an already-expired token; second call returns fresh.
        if fetch_calls["n"] == 1:
            return oauth.AccessToken(
                value="expired",
                expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                scopes=(),
            )
        return _fresh_token()

    monkeypatch.setattr(oauth, "fetch_access_token", fake_fetch)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler))

    with ApiClient(_creds(), http_client=http) as c:
        c.get("/users/me")  # populates cache with already-expired token
        c.get("/users/me")  # cache invalid → refetches

    assert fetch_calls["n"] == 2


def test_request_raises_on_4xx_with_zoom_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"code": 1001, "message": "User does not exist: 123."},
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))

    with ApiClient(_creds(), http_client=http) as c, pytest.raises(ZoomApiError) as exc_info:
        c.get("/users/123")

    err = exc_info.value
    assert err.status_code == 404
    assert err.code == 1001
    assert "does not exist" in str(err)


def test_request_handles_non_json_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502, content=b"<html>bad gateway</html>", headers={"content-type": "text/html"}
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))

    with ApiClient(_creds(), http_client=http) as c, pytest.raises(ZoomApiError) as exc_info:
        c.get("/users/me")

    assert exc_info.value.status_code == 502
    assert exc_info.value.code is None


def test_request_passes_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())

    with ApiClient(_creds(), http_client=http) as c:
        c.get("/users", params={"page_size": 100, "status": "active"})

    assert "page_size=100" in captured["url"]
    assert "status=active" in captured["url"]


def test_api_base_url_is_pinned() -> None:
    """A future rename of the API base would silently break every endpoint
    helper. Pin it here so the test fails loudly."""
    assert client_mod.API_BASE_URL == "https://api.zoom.us/v2"


# ---- #46 / #42: malformed-JSON 2xx bodies on REST endpoints --------------


def test_request_raises_zoom_api_error_on_html_2xx() -> None:
    """Closes #46 / verifies #42 fix: a non-JSON 2xx body should surface as
    ZoomApiError, not raw ValueError."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "tok",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "scope": "user:read:user",
                },
            )
        return httpx.Response(
            200,
            text="<html>nope</html>",
            headers={"Content-Type": "text/html"},
        )

    transport = httpx.MockTransport(handler)
    with (
        httpx.Client(transport=transport) as http,
        pytest.raises(client_mod.ZoomApiError) as excinfo,
    ):
        api = client_mod.ApiClient(_creds(), http_client=http)
        api.request("GET", "/users/me")
    assert "non-JSON body" in str(excinfo.value)


def test_request_raises_zoom_api_error_on_garbage_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "tok",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "scope": "",
                },
            )
        return httpx.Response(200, text="not json")

    transport = httpx.MockTransport(handler)
    with (
        httpx.Client(transport=transport) as http,
        pytest.raises(client_mod.ZoomApiError),
    ):
        api = client_mod.ApiClient(_creds(), http_client=http)
        api.request("GET", "/users/me")
