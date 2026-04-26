"""Tests for zoom_cli.api.oauth — Server-to-Server token exchange.

The test strategy is httpx.MockTransport: we hand fetch_access_token a
real httpx.Client wrapped around a fake transport, so the production
code is exercised end-to-end (auth header, query params, JSON parsing)
without ever opening a socket.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import httpx
import pytest
from zoom_cli.api import oauth
from zoom_cli.auth import S2SCredentials


def _creds() -> S2SCredentials:
    return S2SCredentials(
        account_id="acc-123",
        client_id="cid-456",
        client_secret="csecret-789",
    )


def _client_with_handler(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_access_token_success() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["method"] = request.method
        return httpx.Response(
            200,
            json={
                "access_token": "tok-abc",
                "token_type": "bearer",
                "expires_in": 3600,
                "scope": "user:read:user meeting:read:meeting",
            },
        )

    with _client_with_handler(handler) as client:
        token = oauth.fetch_access_token(_creds(), client=client)

    assert token.value == "tok-abc"
    assert token.scopes == ("user:read:user", "meeting:read:meeting")
    assert token.expires_at > datetime.now(timezone.utc)
    assert token.is_expired is False

    # Verify the request shape Zoom requires.
    assert captured["method"] == "POST"
    assert captured["url"].startswith(oauth.TOKEN_URL)
    assert "grant_type=account_credentials" in captured["url"]
    assert "account_id=acc-123" in captured["url"]

    # HTTP Basic auth: base64(client_id:client_secret)
    expected_auth = base64.b64encode(b"cid-456:csecret-789").decode()
    assert captured["auth"] == f"Basic {expected_auth}"


def test_fetch_access_token_uses_default_expiry_when_missing() -> None:
    """Zoom always sends ``expires_in`` but be defensive — fall back to
    the documented 1-hour default if the field is somehow absent."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "t", "scope": ""})

    with _client_with_handler(handler) as client:
        token = oauth.fetch_access_token(_creds(), client=client)

    delta = (token.expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 3500 <= delta <= 3700  # ~1 hour, allow for tiny scheduler jitter


def test_fetch_access_token_raises_on_invalid_credentials() -> None:
    """The classic 4xx case — wrong client_id or client_secret. Surface
    Zoom's error code and reason verbatim so the CLI can tell the user."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": "invalid_client",
                "reason": "Invalid client_id or client_secret",
            },
        )

    with _client_with_handler(handler) as client, pytest.raises(oauth.ZoomAuthError) as exc_info:
        oauth.fetch_access_token(_creds(), client=client)

    err = exc_info.value
    assert err.status_code == 401
    assert err.error_code == "invalid_client"
    assert "Invalid client_id" in str(err)


def test_fetch_access_token_handles_non_json_error_body() -> None:
    """Misconfigured proxies sometimes return HTML or empty bodies. Don't
    crash — surface what we have."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502, content=b"<html>bad gateway</html>", headers={"content-type": "text/html"}
        )

    with _client_with_handler(handler) as client, pytest.raises(oauth.ZoomAuthError) as exc_info:
        oauth.fetch_access_token(_creds(), client=client)

    err = exc_info.value
    assert err.status_code == 502
    assert err.error_code is None
    assert "bad gateway" in str(err).lower()


def test_fetch_access_token_raises_when_2xx_body_missing_token() -> None:
    """Defensive: if the endpoint returns 200 but no access_token, treat
    as an auth failure rather than handing back an empty AccessToken."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "bearer", "expires_in": 3600})

    with _client_with_handler(handler) as client, pytest.raises(oauth.ZoomAuthError) as exc_info:
        oauth.fetch_access_token(_creds(), client=client)

    assert "access_token" in str(exc_info.value).lower()


def test_fetch_access_token_propagates_network_errors() -> None:
    """Connection / DNS / TLS failures should bubble out as httpx.HTTPError
    (not ZoomAuthError) so the CLI can distinguish bad creds from bad network."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated DNS failure")

    with _client_with_handler(handler) as client, pytest.raises(httpx.HTTPError):
        oauth.fetch_access_token(_creds(), client=client)


def test_access_token_is_expired_when_past_expiry() -> None:
    expired = oauth.AccessToken(
        value="t",
        expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        scopes=(),
    )
    assert expired.is_expired is True


def test_access_token_not_expired_when_in_future() -> None:
    fresh = oauth.AccessToken(
        value="t",
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        scopes=(),
    )
    assert fresh.is_expired is False


def test_token_url_is_zoom_oauth_endpoint() -> None:
    """Pin the URL — different from the API base (api.zoom.us). A future
    rename would silently break every existing user."""
    assert oauth.TOKEN_URL == "https://zoom.us/oauth/token"
