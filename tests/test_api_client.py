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


# ---- #47: 401 single-shot retry with token refresh -----------------------


def test_request_retries_once_on_401_with_force_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Closes #47 (partial): on a 401 the client must drop the cached
    token, fetch a fresh one, and retry the request once. The second
    attempt's success means the user never sees the transient 401."""

    fetch_calls = {"n": 0}

    def fake_fetch(*_args, **_kwargs) -> oauth.AccessToken:
        fetch_calls["n"] += 1
        return oauth.AccessToken(
            value=f"tok-{fetch_calls['n']}",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=(),
        )

    monkeypatch.setattr(oauth, "fetch_access_token", fake_fetch)

    request_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        if request_count["n"] == 1:
            # First request: server says token is invalid (revoked, scope
            # change, etc.). Local clock thought it was still good.
            return httpx.Response(401, json={"code": 124, "message": "Invalid access token."})
        # Second request: succeeds with the freshly fetched token.
        assert request.headers["Authorization"] == "Bearer tok-2"
        return httpx.Response(200, json={"id": "user-1", "email": "a@b.c"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http:
        api = client_mod.ApiClient(_creds(), http_client=http)
        result = api.request("GET", "/users/me")

    assert result == {"id": "user-1", "email": "a@b.c"}
    assert request_count["n"] == 2
    assert fetch_calls["n"] == 2  # initial + force-refresh after 401


def test_request_does_not_loop_on_persistent_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the second attempt also 401s, propagate as ZoomApiError. Never
    loop more than once — bad credentials would otherwise fetch tokens
    indefinitely."""

    fetch_calls = {"n": 0}

    def fake_fetch(*_args, **_kwargs) -> oauth.AccessToken:
        fetch_calls["n"] += 1
        return oauth.AccessToken(
            value=f"tok-{fetch_calls['n']}",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=(),
        )

    monkeypatch.setattr(oauth, "fetch_access_token", fake_fetch)

    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return httpx.Response(401, json={"code": 124, "message": "Invalid access token."})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http:
        api = client_mod.ApiClient(_creds(), http_client=http)
        with pytest.raises(client_mod.ZoomApiError) as excinfo:
            api.request("GET", "/users/me")

    assert excinfo.value.status_code == 401
    assert request_count["n"] == 2  # original + exactly one retry, then propagate
    assert fetch_calls["n"] == 2


def test_request_does_not_retry_on_non_401_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 403 / 404 / 429 should NOT trigger the auth-refresh retry path —
    those aren't auth problems and re-issuing wastes a token fetch."""

    fetch_calls = {"n": 0}

    def fake_fetch(*_args, **_kwargs) -> oauth.AccessToken:
        fetch_calls["n"] += 1
        return oauth.AccessToken(
            value="tok",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=(),
        )

    monkeypatch.setattr(oauth, "fetch_access_token", fake_fetch)

    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return httpx.Response(403, json={"code": 200, "message": "Insufficient privileges."})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http:
        api = client_mod.ApiClient(_creds(), http_client=http)
        with pytest.raises(client_mod.ZoomApiError):
            api.request("GET", "/users/me")

    assert request_count["n"] == 1  # no retry
    assert fetch_calls["n"] == 1


# ---- #16: 429 / Retry-After handling ------------------------------------


def test_request_retries_429_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """First response 429 with Retry-After: 0; second response 200."""
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sleeps.append(s))

    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        if request_count["n"] == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"code": 429, "message": "Too many requests"},
            )
        return httpx.Response(200, json={"id": "u-ok"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with ApiClient(_creds(), http_client=http) as c:
        result = c.get("/users/me")

    assert result == {"id": "u-ok"}
    assert request_count["n"] == 2
    assert len(sleeps) == 1  # one sleep before the retry
    assert sleeps[0] >= 0  # jittered around 0


def test_request_honours_retry_after_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry-After: 5 should produce a sleep of ~5 (4-6 with ±20% jitter)."""
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sleeps.append(s))

    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        if request_count["n"] == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "5"},
                json={"code": 429},
            )
        return httpx.Response(200, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with ApiClient(_creds(), http_client=http) as c:
        c.get("/users/me")

    assert len(sleeps) == 1
    # JITTER_RANGE is 0.2 → sleep is 5 * (0.8 to 1.2) = 4.0 to 6.0
    assert 4.0 <= sleeps[0] <= 6.0


def test_request_caps_retry_at_max_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pathological Retry-After must not produce an unbounded sleep."""
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sleeps.append(s))

    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        if request_count["n"] == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "9999"},
                json={"code": 429},
            )
        return httpx.Response(200, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with ApiClient(_creds(), http_client=http) as c:
        c.get("/users/me")

    # Capped at MAX_RETRY_DELAY_SECONDS (60s) ± jitter (0.8-1.2x) = 48-72.
    # 60 * 1.2 = 72 is the upper bound.
    assert sleeps[0] <= client_mod.MAX_RETRY_DELAY_SECONDS * (1.0 + client_mod.JITTER_RANGE)


def test_request_falls_back_to_exponential_backoff_without_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive 429s with no Retry-After: backoff doubles."""
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sleeps.append(s))

    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        if request_count["n"] <= 2:
            return httpx.Response(429, json={"code": 429})
        return httpx.Response(200, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with ApiClient(_creds(), http_client=http) as c:
        c.get("/users/me")

    assert request_count["n"] == 3  # two 429s + success
    assert len(sleeps) == 2
    # attempt 0: 2**0 = 1 → 0.8-1.2; attempt 1: 2**1 = 2 → 1.6-2.4
    assert 0.8 <= sleeps[0] <= 1.2
    assert 1.6 <= sleeps[1] <= 2.4


def test_request_propagates_after_max_429_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """If Zoom never relents, surface the 429 as ZoomApiError after
    MAX_429_RETRIES attempts. No infinite loop."""
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())
    monkeypatch.setattr(client_mod.time, "sleep", lambda _s: None)

    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return httpx.Response(429, json={"code": 429, "message": "still throttled"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        ApiClient(_creds(), http_client=http) as c,
        pytest.raises(client_mod.ZoomApiError) as excinfo,
    ):
        c.get("/users/me")

    assert excinfo.value.status_code == 429
    # Initial attempt + MAX_429_RETRIES retries.
    assert request_count["n"] == 1 + client_mod.MAX_429_RETRIES


def test_request_handles_http_date_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry-After can be an HTTP-date (RFC 7231)."""
    import email.utils
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sleeps.append(s))

    target = datetime.now(timezone.utc) + timedelta(seconds=3)
    http_date = email.utils.format_datetime(target)

    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        if request_count["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": http_date}, json={"code": 429})
        return httpx.Response(200, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with ApiClient(_creds(), http_client=http) as c:
        c.get("/users/me")

    assert len(sleeps) == 1
    # ~3 seconds ± jitter ± a fraction-of-a-second clock variance.
    assert 1.5 <= sleeps[0] <= 4.5


def test_request_does_not_retry_5xx_as_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 500/503 must not enter the 429 retry path — propagate immediately."""
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sleeps.append(s))

    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return httpx.Response(503, json={"code": 503, "message": "Service unavailable"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        ApiClient(_creds(), http_client=http) as c,
        pytest.raises(client_mod.ZoomApiError) as excinfo,
    ):
        c.get("/users/me")

    assert excinfo.value.status_code == 503
    assert request_count["n"] == 1  # no retry on 503
    assert sleeps == []


# ---- #16 constants pinned -----------------------------------------------


def test_max_429_retries_pinned() -> None:
    assert client_mod.MAX_429_RETRIES == 3


def test_max_retry_delay_pinned() -> None:
    assert client_mod.MAX_RETRY_DELAY_SECONDS == 60.0


def test_jitter_range_pinned() -> None:
    assert client_mod.JITTER_RANGE == 0.2
