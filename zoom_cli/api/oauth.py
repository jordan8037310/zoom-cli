"""Server-to-Server OAuth token exchange against Zoom.

Reference: https://developers.zoom.us/docs/internal-apps/s2s-oauth/

The Zoom token endpoint expects:
    POST https://zoom.us/oauth/token?grant_type=account_credentials&account_id=...
    Authorization: Basic <base64(client_id:client_secret)>

On 2xx it responds with::

    {
      "access_token": "<JWT>",
      "token_type": "bearer",
      "expires_in": 3600,
      "scope": "user:read:user ..."
    }

On 4xx it responds with::

    {"reason": "Invalid client_id or client_secret", "error": "invalid_client"}

We surface that as a ``ZoomAuthError`` with the parsed fields so the CLI
can print a useful message rather than a stack trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from zoom_cli.auth import S2SCredentials

#: Zoom's public OAuth token endpoint. Hard-coded — different from the
#: API base URL because OAuth lives on ``zoom.us``, not ``api.zoom.us``.
TOKEN_URL = "https://zoom.us/oauth/token"  # noqa: S105 - public endpoint URL, not a password

#: Default timeout for the token round-trip. Slightly more generous than
#: the typical 5s ceiling because corporate proxies + first-cold-DNS can
#: legitimately spike up to ~10s.
DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class AccessToken:
    """A short-lived bearer token returned by the token endpoint.

    ``expires_at`` is an absolute timezone-aware UTC ``datetime`` rather
    than the relative ``expires_in`` we get from Zoom — saves every
    caller from re-doing the math and avoids drift if the token is held
    in a cache. ``scopes`` is the parsed ``scope`` string Zoom returns;
    we preserve it for ``zoom auth s2s test`` to display.
    """

    value: str
    expires_at: datetime
    scopes: tuple[str, ...]

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


class ZoomAuthError(RuntimeError):
    """The token endpoint refused the credentials.

    Carries the HTTP status, Zoom's machine-readable ``error`` code (e.g.
    ``invalid_client``), and the human-readable ``reason`` so callers
    can decide how to surface each one.
    """

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


def fetch_access_token(
    creds: S2SCredentials,
    *,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> AccessToken:
    """Exchange Server-to-Server OAuth credentials for a 1-hour bearer token.

    The optional ``client`` parameter exists so tests can inject a
    pre-configured ``httpx.Client`` (typically wrapped around a
    ``httpx.MockTransport``). Production callers can leave it ``None``.

    Raises:
        ZoomAuthError: the token endpoint responded with a non-2xx status,
            or returned a 2xx body without a usable ``access_token``.
        httpx.HTTPError: the request never reached the endpoint
            (DNS, TCP, TLS, or timeout failure). Callers in the CLI
            translate this into a friendly "couldn't reach api.zoom.us"
            message; lower layers can reason about the typed exception.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)

    try:
        response = client.post(
            TOKEN_URL,
            params={
                "grant_type": "account_credentials",
                "account_id": creds.account_id,
            },
            auth=(creds.client_id, creds.client_secret),
        )
    finally:
        if owns_client:
            client.close()

    if response.status_code >= 400:
        # Zoom's error body is a small JSON dict. If the body isn't JSON
        # (proxy returning HTML, etc.) we still surface a useful message.
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        raise ZoomAuthError(
            payload.get("reason") or payload.get("error_description") or response.text,
            status_code=response.status_code,
            error_code=payload.get("error"),
        )

    # Closes #42: a 2xx body that isn't JSON (corporate proxy returning HTML,
    # captive portal, intermediate cache returning empty) used to leak raw
    # ValueError. Translate to ZoomAuthError so callers see the same typed
    # exception they'd see for an auth refusal — different status, same
    # error class, easier to handle uniformly.
    try:
        payload = response.json()
    except ValueError as exc:
        raise ZoomAuthError(
            "Token endpoint returned 2xx with non-JSON body "
            f"(content-type={response.headers.get('content-type', 'unknown')})",
            status_code=response.status_code,
        ) from exc

    token_value = payload.get("access_token")
    if not token_value:
        raise ZoomAuthError(
            "Token endpoint returned 2xx but no access_token field",
            status_code=response.status_code,
        )

    expires_in = int(payload.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    scopes_str = payload.get("scope", "")
    scopes = tuple(scopes_str.split()) if scopes_str else ()

    return AccessToken(value=token_value, expires_at=expires_at, scopes=scopes)
