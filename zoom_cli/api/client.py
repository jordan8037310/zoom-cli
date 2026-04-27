"""Authenticated HTTP client for the Zoom REST API.

This module exposes :class:`ApiClient`, a thin wrapper over ``httpx.Client``
that adds:

- automatic bearer-token injection on every request,
- an in-memory access-token cache (Zoom tokens live for 1 hour and there's
  no value in persisting them — they're cheaper to re-fetch than to keep
  in a keyring); cache uses a 60s expiry skew (see
  :data:`oauth.EXPIRY_SKEW_SECONDS`) so we don't send requests with
  about-to-expire tokens,
- a single-shot 401 retry that force-refreshes the token and re-issues the
  request once (closes #47, partial) — covers the "Zoom revoked the token
  before our clock said it expired" race,
- a :class:`ZoomApiError` raised on non-2xx responses with the parsed
  Zoom error envelope (``{"code": ..., "message": ...}``).

Out of scope here, deliberately:

- Per-tier rate-limit handling and 429 retry — that's issue #16. The
  shape of the client is stable enough that adding a token-bucket
  decorator later will be additive.
- Pagination helpers — folded into issue #16 alongside the limiter.
"""

from __future__ import annotations

from typing import Any

import httpx

from zoom_cli.api import oauth
from zoom_cli.auth import S2SCredentials

#: Zoom REST API base URL. All paths are relative to this.
API_BASE_URL = "https://api.zoom.us/v2"

#: Default request timeout in seconds. Higher than the OAuth timeout
#: because some endpoints (recordings list, dashboards) are slower.
DEFAULT_TIMEOUT_SECONDS = 30.0


class ZoomApiError(RuntimeError):
    """A non-2xx response from a Zoom REST API endpoint.

    Distinct from :class:`oauth.ZoomAuthError` so callers can tell a
    bad-credentials problem from a genuine API error.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class ApiClient:
    """Authenticated client for ``api.zoom.us``.

    Construct once per CLI invocation (or once per long-running process)
    and pass into the per-resource helper modules (``users.py``, etc.).
    The client owns its underlying ``httpx.Client``; use as a context
    manager to ensure connections are closed.
    """

    def __init__(
        self,
        credentials: S2SCredentials,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._credentials = credentials
        self._owns_client = http_client is None
        self._http = http_client if http_client is not None else httpx.Client(timeout=timeout)
        self._cached_token: oauth.AccessToken | None = None

    # ---- context-manager hooks ---------------------------------------

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    # ---- token lifecycle ---------------------------------------------

    def _access_token(self, *, force_refresh: bool = False) -> oauth.AccessToken:
        """Return a usable access token, fetching a new one if needed.

        We re-use the cached token while it's still valid (with a 60s
        expiry skew — see :data:`oauth.EXPIRY_SKEW_SECONDS`). Long-running
        callers (a future ``zoom watch``) will hit the refresh path
        naturally as the token approaches expiry.

        ``force_refresh=True`` is used by the 401 retry path: even if the
        cached token *thinks* it's still valid, the server has told us
        otherwise, so we drop the cache and re-fetch.
        """
        if force_refresh:
            self._cached_token = None
        if self._cached_token is None or self._cached_token.is_expired:
            self._cached_token = oauth.fetch_access_token(self._credentials, client=self._http)
        return self._cached_token

    # ---- HTTP --------------------------------------------------------

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        json: dict[str, Any] | None,
        force_refresh: bool = False,
    ) -> httpx.Response:
        token = self._access_token(force_refresh=force_refresh)
        return self._http.request(
            method,
            url,
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {token.value}"},
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue an authenticated request and return the parsed JSON body.

        On a 401, force-refresh the token and retry once (closes #47,
        partial) — covers the case where Zoom revoked the token before
        our local clock said it expired (rotation, scope change). A second
        401 propagates as :class:`ZoomApiError` so we never loop.

        Raises :class:`ZoomApiError` for any non-2xx response.
        """
        url = f"{API_BASE_URL}{path}" if path.startswith("/") else f"{API_BASE_URL}/{path}"
        response = self._send(method, url, params=params, json=json)
        if response.status_code == 401:
            response = self._send(method, url, params=params, json=json, force_refresh=True)
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            raise ZoomApiError(
                payload.get("message") or response.text,
                status_code=response.status_code,
                code=payload.get("code"),
            )
        if not response.content:
            return {}
        # Closes #42: a 2xx body that isn't JSON used to leak raw ValueError.
        # Translate to ZoomApiError so callers always see the same typed
        # exception envelope regardless of which side of the proxy chain
        # corrupted the response.
        try:
            return response.json()
        except ValueError as exc:
            raise ZoomApiError(
                "Zoom API returned 2xx with non-JSON body "
                f"(content-type={response.headers.get('content-type', 'unknown')})",
                status_code=response.status_code,
            ) from exc

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Convenience wrapper for ``GET``."""
        return self.request("GET", path, params=params)
