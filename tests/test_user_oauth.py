"""Tests for zoom_cli.api.user_oauth — PKCE flow components.

The end-to-end ``run_pkce_flow`` is integration territory (real socket +
real browser) so we test the components individually:

- PKCE pair generation (charset, length, challenge derivation).
- Authorize URL construction (pure).
- Token exchange (httpx.MockTransport).
- Refresh token (httpx.MockTransport).
- Error paths on both (4xx + non-JSON 2xx).
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from zoom_cli.api import user_oauth

# ---- PKCE primitives ----------------------------------------------------


def test_pkce_pair_verifier_in_rfc7636_range() -> None:
    """RFC 7636 requires 43..128 chars from [A-Z / a-z / 0-9 / "-" / "." /
    "_" / "~"]. token_urlsafe(48) yields ~64 base64url chars; pin both
    bounds + the charset."""
    verifier, _challenge = user_oauth._pkce_pair()
    assert 43 <= len(verifier) <= 128
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert set(verifier) <= allowed


def test_pkce_pair_challenge_is_sha256_of_verifier() -> None:
    verifier, challenge = user_oauth._pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected


def test_pkce_pair_is_random() -> None:
    pairs = {user_oauth._pkce_pair() for _ in range(5)}
    # 5 calls should give 5 distinct pairs.
    assert len(pairs) == 5


def test_random_state_is_url_safe_and_random() -> None:
    states = {user_oauth._random_state() for _ in range(5)}
    assert len(states) == 5
    for s in states:
        assert s and not any(c in s for c in "+/=")


# ---- authorize URL ------------------------------------------------------


def test_build_authorize_url_has_required_params() -> None:
    url = user_oauth.build_authorize_url(
        client_id="cid-123",
        redirect_uri="http://127.0.0.1:8765/callback",
        code_challenge="abc",
        state="state-xyz",
    )
    parsed = urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "zoom.us"
    assert parsed.path == "/oauth/authorize"
    qs = parse_qs(parsed.query)
    assert qs["response_type"] == ["code"]
    assert qs["client_id"] == ["cid-123"]
    assert qs["redirect_uri"] == ["http://127.0.0.1:8765/callback"]
    assert qs["code_challenge"] == ["abc"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["state"] == ["state-xyz"]


def test_build_authorize_url_url_encodes_redirect_with_port() -> None:
    """Redirect URIs always end up percent-encoded by urlencode."""
    url = user_oauth.build_authorize_url(
        client_id="cid",
        redirect_uri="http://127.0.0.1:55555/callback?extra=1",
        code_challenge="c",
        state="s",
    )
    # The colon and slashes inside redirect_uri are percent-encoded.
    assert "%3A" in url and "%2F" in url


# ---- token exchange ----------------------------------------------------


def _ok_token_response(**overrides) -> dict:
    base = {
        "access_token": "access-tok-1",
        "refresh_token": "refresh-tok-1",
        "expires_in": 3600,
        "scope": "user:read meeting:read",
        "token_type": "bearer",
    }
    base.update(overrides)
    return base


def test_exchange_code_for_tokens_round_trips() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = bytes(request.content).decode()
        return httpx.Response(200, json=_ok_token_response())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        tokens = user_oauth.exchange_code_for_tokens(
            client_id="cid",
            redirect_uri="http://127.0.0.1:1234/callback",
            code="auth-code",
            code_verifier="verifier",
            http=http,
        )

    assert tokens.access_token == "access-tok-1"
    assert tokens.refresh_token == "refresh-tok-1"
    assert tokens.scopes == ("user:read", "meeting:read")
    assert tokens.expires_at > datetime.now(timezone.utc)
    # Body is form-encoded.
    body = parse_qs(captured["body"])
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["auth-code"]
    assert body["redirect_uri"] == ["http://127.0.0.1:1234/callback"]
    assert body["client_id"] == ["cid"]
    assert body["code_verifier"] == ["verifier"]


def test_exchange_code_raises_on_4xx_with_zoom_error_envelope() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": "invalid_grant", "reason": "Code expired"},
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(user_oauth.ZoomUserAuthError) as excinfo,
    ):
        user_oauth.exchange_code_for_tokens(
            client_id="c", redirect_uri="r", code="c", code_verifier="v", http=http
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "invalid_grant"
    assert "Code expired" in str(excinfo.value)


def test_exchange_code_raises_on_2xx_without_access_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"refresh_token": "r"})  # missing access_token

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(user_oauth.ZoomUserAuthError),
    ):
        user_oauth.exchange_code_for_tokens(
            client_id="c", redirect_uri="r", code="c", code_verifier="v", http=http
        )


def test_exchange_code_raises_on_2xx_html_body() -> None:
    """Captive-portal / proxy returning HTML on a 200."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<html>captive portal</html>", headers={"Content-Type": "text/html"}
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(user_oauth.ZoomUserAuthError) as excinfo,
    ):
        user_oauth.exchange_code_for_tokens(
            client_id="c", redirect_uri="r", code="c", code_verifier="v", http=http
        )
    assert "non-JSON" in str(excinfo.value)


# ---- refresh ------------------------------------------------------------


def test_refresh_user_tokens_round_trips() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = bytes(request.content).decode()
        return httpx.Response(
            200,
            json=_ok_token_response(refresh_token="rotated-refresh"),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        tokens = user_oauth.refresh_user_tokens(
            refresh_token="old-refresh",
            client_id="cid",
            http=http,
        )

    body = parse_qs(captured["body"])
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["old-refresh"]
    assert body["client_id"] == ["cid"]
    # Refresh tokens are rotated — caller must persist the new value.
    assert tokens.refresh_token == "rotated-refresh"


def test_refresh_user_tokens_raises_on_4xx() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": "invalid_grant", "reason": "Refresh token expired"}
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(user_oauth.ZoomUserAuthError) as excinfo,
    ):
        user_oauth.refresh_user_tokens(refresh_token="r", client_id="c", http=http)
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "invalid_grant"


# ---- module constants --------------------------------------------------


def test_authorize_and_token_urls_pinned() -> None:
    """Future URL renames would silently break every existing user."""
    assert user_oauth.AUTHORIZE_URL == "https://zoom.us/oauth/authorize"
    assert user_oauth.TOKEN_URL == "https://zoom.us/oauth/token"
