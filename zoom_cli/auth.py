"""Authentication credential storage for the Zoom REST API.

This module is the persistence layer for Server-to-Server OAuth credentials
(account_id, client_id, client_secret). It does **not** do any HTTP — token
exchange against ``https://zoom.us/oauth/token`` is implemented in a
follow-up PR. Splitting the storage layer out keeps this PR small and lets
the credential set/clear lifecycle be reviewed independently from the
network code.

Why we use the same OS keyring backend as ``zoom_cli.secrets``: API client
secrets are at least as sensitive as meeting passwords, so the same
"never plaintext on disk" guarantee applies. The two are namespaced by
distinct service strings (``zoom-cli`` for meeting passwords, ``zoom-cli-auth``
here) to avoid any chance of overlap with a meeting that happens to be
named ``account_id``, ``client_id``, etc.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

import keyring
import keyring.errors

#: Keyring service identifier for OAuth credentials. Pinned by a test —
#: changing it orphans every existing user's saved credentials.
SERVICE_NAME = "zoom-cli-auth"

# Username slots inside the service. We use one keyring entry per field so
# we can read/delete each independently and so a user inspecting the
# Keychain sees three labelled entries rather than one opaque blob.
_ACCOUNT_ID_KEY = "s2s.account_id"
_CLIENT_ID_KEY = "s2s.client_id"
_CLIENT_SECRET_KEY = "s2s.client_secret"  # noqa: S105 - keyring slot name, not a password value


@dataclass(frozen=True)
class S2SCredentials:
    """The three values Zoom requires for Server-to-Server OAuth.

    See https://developers.zoom.us/docs/internal-apps/s2s-oauth/ — these
    are exchanged for an access token via the
    ``grant_type=account_credentials`` endpoint.
    """

    account_id: str
    client_id: str
    client_secret: str


def save_s2s_credentials(creds: S2SCredentials) -> None:
    """Persist all three S2S fields to the OS keyring under ``zoom-cli-auth``.

    Atomic semantics are best-effort: if the second or third write fails
    we leave whatever's already there. The caller can re-run ``zoom auth
    s2s set`` to retry. This matches how ``zoom save`` works for meetings.
    """
    keyring.set_password(SERVICE_NAME, _ACCOUNT_ID_KEY, creds.account_id)
    keyring.set_password(SERVICE_NAME, _CLIENT_ID_KEY, creds.client_id)
    keyring.set_password(SERVICE_NAME, _CLIENT_SECRET_KEY, creds.client_secret)


def load_s2s_credentials() -> S2SCredentials | None:
    """Return the stored credentials, or ``None`` if any field is missing.

    All three fields are required for the OAuth round-trip, so partial
    state is treated the same as no state. Callers that want to know
    *which* fields are missing should look at each key directly.

    Catches only the genuine "no backend" errors (matches the policy in
    ``zoom_cli.secrets``) — locked or misbehaving backends propagate so
    the user can see and resolve them rather than silently being treated
    as logged-out.
    """
    try:
        account_id = keyring.get_password(SERVICE_NAME, _ACCOUNT_ID_KEY)
        client_id = keyring.get_password(SERVICE_NAME, _CLIENT_ID_KEY)
        client_secret = keyring.get_password(SERVICE_NAME, _CLIENT_SECRET_KEY)
    except (keyring.errors.NoKeyringError, keyring.errors.InitError):
        return None

    if not (account_id and client_id and client_secret):
        return None

    return S2SCredentials(
        account_id=account_id,
        client_id=client_id,
        client_secret=client_secret,
    )


def clear_s2s_credentials() -> None:
    """Remove all three S2S keyring entries. Safe to call when none exist."""
    for key in (_ACCOUNT_ID_KEY, _CLIENT_ID_KEY, _CLIENT_SECRET_KEY):
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(SERVICE_NAME, key)


def has_s2s_credentials() -> bool:
    """Cheap "is the user logged in via S2S?" check, no return of secrets."""
    return load_s2s_credentials() is not None
