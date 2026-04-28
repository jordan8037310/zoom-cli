"""User OAuth 2.0 flow with PKCE for Zoom (closes #12).

Reference: https://developers.zoom.us/docs/integrations/oauth/

For developers without S2S marketplace credentials, the user-OAuth flow
authenticates as the developer's own Zoom user instead of an account.
The flow:

1. Generate a PKCE ``code_verifier`` (random URL-safe string) and the
   matching ``code_challenge`` = ``base64url(sha256(verifier))``.
2. Start a loopback HTTP server on ``127.0.0.1:<ephemeral-port>``.
3. Build the authorize URL pointing back at that loopback as
   ``redirect_uri``; open it in the user's default browser.
4. The user authorizes in-browser; Zoom redirects to the loopback with
   ``?code=<auth-code>&state=<our-state>``.
5. The loopback handler captures the code; the CLI exchanges it for an
   access + refresh token pair at ``POST https://zoom.us/oauth/token``.
6. ``refresh_token`` is persisted in the OS keyring; ``access_token``
   stays in memory (1-hour lifetime).

Module surface:

  build_authorize_url(client_id, redirect_uri, code_challenge, state)
      Pure. Useful for tests + for printing the URL when ``webbrowser``
      can't open one (headless environments).

  exchange_code_for_tokens(client_id, redirect_uri, code, code_verifier,
                           *, http=None)
      The token exchange. HTTP — mock with ``httpx.MockTransport``.

  refresh_user_tokens(refresh_token, client_id, *, http=None)
      Use the refresh_token to get a new access_token (and possibly a
      rotated refresh_token).

  run_pkce_flow(client_id, *, port=0, browser=None, timeout=300, http=None)
      End-to-end flow. The integration is hard to unit-test (real socket
      + real browser callback); test the components above instead.

The Zoom user-OAuth ``access_token`` is short-lived (1 hour) like the
S2S token. Refresh tokens are also short-lived (~14 days) and are
**rotated** on each refresh, so the new ``refresh_token`` from a
refresh response must be persisted back to the keyring immediately.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

#: Zoom's user-OAuth authorize endpoint. Different from the API base
#: (api.zoom.us) and from the S2S token endpoint URL — those are pinned
#: separately so a future endpoint move doesn't silently break.
AUTHORIZE_URL = "https://zoom.us/oauth/authorize"

#: Same token endpoint as S2S; the ``grant_type`` distinguishes the two.
TOKEN_URL = "https://zoom.us/oauth/token"  # noqa: S105 - public endpoint URL

#: Default timeout for the token exchange / refresh round-trips.
DEFAULT_TIMEOUT_SECONDS = 15.0

#: Minimum allowed length for the PKCE code_verifier per RFC 7636 (43 chars
#: of [A-Z / a-z / 0-9 / "-" / "." / "_" / "~"]).
_PKCE_VERIFIER_MIN_LEN = 43


@dataclass(frozen=True)
class UserOAuthTokens:
    """Tokens returned by the OAuth token endpoint.

    ``access_token`` is short-lived (1 hour). ``refresh_token`` is
    longer-lived (~14 days) and **rotated** on every refresh — callers
    must persist the new value, not the old.
    """

    access_token: str
    refresh_token: str
    expires_at: datetime
    scopes: tuple[str, ...]


class ZoomUserAuthError(RuntimeError):
    """A non-2xx from the user-OAuth token endpoint, or a flow-level
    error (CSRF state mismatch, browser timeout, etc.)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


# ---- PKCE primitives (pure) --------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Generate a (code_verifier, code_challenge) pair per RFC 7636.

    Verifier is 64 chars from ``secrets.token_urlsafe`` (URL-safe base64
    of 48 random bytes, ~64 chars after padding strip — within the
    43..128 RFC range). Challenge is ``base64url(sha256(verifier))``
    with the trailing ``=`` stripped.
    """
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _random_state() -> str:
    """Random opaque string used as OAuth ``state`` (CSRF token)."""
    return secrets.token_urlsafe(24)


def build_authorize_url(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
) -> str:
    """Build the Zoom authorize URL for a PKCE flow.

    Pure — no I/O. Useful for tests and for headless environments where
    the operator pastes the URL into a browser by hand.
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


# ---- token exchange (HTTP) ---------------------------------------------


def _parse_token_response(response: httpx.Response) -> UserOAuthTokens:
    """Translate a 2xx token-endpoint response into :class:`UserOAuthTokens`.

    Raises :class:`ZoomUserAuthError` on non-2xx OR a 2xx that doesn't
    have a usable ``access_token``. Mirrors the pattern in
    :mod:`zoom_cli.api.oauth` (#42 hardening).
    """
    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        raise ZoomUserAuthError(
            payload.get("reason") or payload.get("error_description") or response.text,
            status_code=response.status_code,
            error_code=payload.get("error"),
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ZoomUserAuthError(
            "Token endpoint returned 2xx with non-JSON body "
            f"(content-type={response.headers.get('content-type', 'unknown')})",
            status_code=response.status_code,
        ) from exc

    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    if not access or not refresh:
        raise ZoomUserAuthError(
            "Token endpoint returned 2xx but access_token/refresh_token missing",
            status_code=response.status_code,
        )

    expires_in = int(payload.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    scopes_str = payload.get("scope", "")
    scopes = tuple(scopes_str.split()) if scopes_str else ()

    return UserOAuthTokens(
        access_token=access,
        refresh_token=refresh,
        expires_at=expires_at,
        scopes=scopes,
    )


def exchange_code_for_tokens(
    *,
    client_id: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
    http: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> UserOAuthTokens:
    """Trade an authorization code for a token pair.

    Raises:
        ZoomUserAuthError: Zoom rejected the exchange (bad code, wrong
            verifier, expired code, etc.) or returned a malformed body.
        httpx.HTTPError: never reached the endpoint (DNS / TCP / TLS /
            timeout). CLI translates this into a friendly message.
    """
    owns = http is None
    if http is None:
        http = httpx.Client(timeout=timeout)
    try:
        response = http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
        )
    finally:
        if owns:
            http.close()
    return _parse_token_response(response)


def refresh_user_tokens(
    *,
    refresh_token: str,
    client_id: str,
    http: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> UserOAuthTokens:
    """Use a refresh_token to mint a fresh access_token (and a rotated
    refresh_token — always persist the new one)."""
    owns = http is None
    if http is None:
        http = httpx.Client(timeout=timeout)
    try:
        response = http.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
        )
    finally:
        if owns:
            http.close()
    return _parse_token_response(response)


# ---- end-to-end flow ----------------------------------------------------


def run_pkce_flow(
    client_id: str,
    *,
    port: int = 0,
    browser: Any = None,
    timeout: float = 300.0,
    http: httpx.Client | None = None,
    on_url: Any = None,
) -> UserOAuthTokens:
    """End-to-end PKCE flow.

    Args:
        client_id: Zoom OAuth Client ID for a user-managed app.
        port: Loopback port to bind. ``0`` (default) picks an ephemeral
            port — recommended for prod; specific port useful for tests.
        browser: Optional callable taking the auth URL. Defaults to
            :func:`webbrowser.open`. Pass a no-op for headless flows.
        timeout: Seconds to wait for the browser callback before giving
            up. Default 5 minutes.
        http: Optional preconfigured ``httpx.Client`` for the token
            exchange — useful for tests.
        on_url: Optional callable invoked with the auth URL just before
            the browser launches; lets the CLI print the URL so the
            user can paste it manually if the browser doesn't open.

    Returns:
        :class:`UserOAuthTokens` on success.

    Raises:
        ZoomUserAuthError: state mismatch (CSRF), Zoom returned an
            ``error`` query param on the callback, or the token
            exchange failed.
        TimeoutError: the user didn't authorize within ``timeout``.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlsplit

    verifier, challenge = _pkce_pair()
    state = _random_state()

    captured: dict[str, str] = {}

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            captured["code"] = query.get("code", [""])[0]
            captured["state"] = query.get("state", [""])[0]
            captured["error"] = query.get("error", [""])[0]
            captured["error_description"] = query.get("error_description", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            body = (
                b"<html><body><h2>Authorization received.</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            # Silence the default stderr-spam on every request.
            pass

    # Bind first so we know the port (caller may have asked for ``0``).
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.socket.settimeout(timeout)
    bound_port = server.server_port
    redirect_uri = f"http://127.0.0.1:{bound_port}/callback"
    auth_url = build_authorize_url(client_id, redirect_uri, challenge, state)

    if on_url is not None:
        on_url(auth_url)

    if browser is None:
        import webbrowser

        browser = webbrowser.open
    browser(auth_url)

    server.timeout = timeout
    try:
        server.handle_request()
    except (TimeoutError, OSError) as exc:
        raise TimeoutError(f"OAuth callback didn't arrive within {timeout:.0f}s") from exc
    finally:
        server.server_close()

    if captured.get("error"):
        raise ZoomUserAuthError(
            captured.get("error_description") or captured["error"],
            error_code=captured["error"],
        )
    if not captured.get("code"):
        raise TimeoutError("OAuth callback didn't carry a code")
    if captured.get("state") != state:
        raise ZoomUserAuthError("OAuth state mismatch — possible CSRF attempt")

    return exchange_code_for_tokens(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code=captured["code"],
        code_verifier=verifier,
        http=http,
    )
