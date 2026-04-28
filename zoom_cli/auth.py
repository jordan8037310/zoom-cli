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


_ALL_KEYS = (_ACCOUNT_ID_KEY, _CLIENT_ID_KEY, _CLIENT_SECRET_KEY)


def save_s2s_credentials(creds: S2SCredentials) -> None:
    """Persist all three S2S fields to the OS keyring under ``zoom-cli-auth``.

    Best-effort transactional: snapshot the existing values first, then write
    the three new ones in order. If any write raises, restore the snapshot
    so the user is left with the prior credential set rather than a hybrid
    of new + old fields. ``load_s2s_credentials`` would otherwise return a
    full-looking tuple composed of mismatched values, leading the user to
    authenticate with the wrong account/client combination silently.
    Closes #35.
    """
    snapshot = {key: keyring.get_password(SERVICE_NAME, key) for key in _ALL_KEYS}
    written: list[str] = []
    try:
        for key, value in (
            (_ACCOUNT_ID_KEY, creds.account_id),
            (_CLIENT_ID_KEY, creds.client_id),
            (_CLIENT_SECRET_KEY, creds.client_secret),
        ):
            keyring.set_password(SERVICE_NAME, key, value)
            written.append(key)
    except Exception:
        for key in written:
            previous = snapshot[key]
            with contextlib.suppress(Exception):
                if previous is None:
                    keyring.delete_password(SERVICE_NAME, key)
                else:
                    keyring.set_password(SERVICE_NAME, key, previous)
        raise


def load_s2s_credentials() -> S2SCredentials | None:
    """Return the stored credentials, or ``None`` if any field is missing.

    All three fields are required for the OAuth round-trip, so partial
    state is treated the same as no state. Callers that want to know
    *which* fields are missing should look at each key directly.

    Behavior change in #41: ``NoKeyringError`` and ``InitError`` now
    propagate rather than being silently flattened to ``None``. The two
    states ("user has not configured S2S yet" vs "this machine has no
    keyring backend at all") need different remediation paths and the
    CLI surfaces them with different exit codes. Locked or otherwise
    misbehaving backends already propagated; this just makes the
    backend-missing case behave the same way for consistency.
    """
    account_id = keyring.get_password(SERVICE_NAME, _ACCOUNT_ID_KEY)
    client_id = keyring.get_password(SERVICE_NAME, _CLIENT_ID_KEY)
    client_secret = keyring.get_password(SERVICE_NAME, _CLIENT_SECRET_KEY)

    if not (account_id and client_id and client_secret):
        return None

    return S2SCredentials(
        account_id=account_id,
        client_id=client_id,
        client_secret=client_secret,
    )


def clear_s2s_credentials() -> None:
    """Remove all three S2S keyring entries. Safe to call when none exist."""
    for key in _ALL_KEYS:
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(SERVICE_NAME, key)


def has_s2s_credentials() -> bool:
    """Cheap "is the user logged in via S2S?" check, no return of secrets.

    Returns ``False`` if the backend is unavailable (rather than raising)
    so the CLI ``status`` command can give a friendlier message; callers
    that need to distinguish "no backend" from "no creds" should use
    :func:`load_s2s_credentials` directly.
    """
    try:
        return load_s2s_credentials() is not None
    except (keyring.errors.NoKeyringError, keyring.errors.InitError):
        return False


# ---- User OAuth (PKCE) credential storage (closes #12 storage layer) ----
#
# Distinct service name from S2S so a `zoom auth logout` can clear one
# without touching the other. We persist:
#   - refresh_token: long-lived (~14 days, rotated on each refresh)
#   - client_id: needed to re-do the refresh; not secret on its own but
#     still per-installation, so we store it alongside.
# access_token is in-memory only — Zoom rotates it every hour and the
# refresh path is cheap.

#: Keyring service identifier for user-OAuth credentials.
SERVICE_NAME_USER = "zoom-cli-user-auth"

_USER_REFRESH_KEY = "user.refresh_token"
_USER_CLIENT_ID_KEY = "user.client_id"

_USER_ALL_KEYS = (_USER_REFRESH_KEY, _USER_CLIENT_ID_KEY)


@dataclass(frozen=True)
class UserOAuthCredentials:
    """Persisted half of a user-OAuth session.

    The access_token isn't in here — it's short-lived and lives in
    memory only.
    """

    refresh_token: str
    client_id: str


def save_user_oauth_credentials(creds: UserOAuthCredentials) -> None:
    """Persist user-OAuth refresh + client_id to the OS keyring.

    Best-effort transactional, mirroring :func:`save_s2s_credentials`
    (closes #35 pattern): snapshot existing values, write new ones,
    restore the snapshot on any partial failure.
    """
    snapshot = {key: keyring.get_password(SERVICE_NAME_USER, key) for key in _USER_ALL_KEYS}
    written: list[str] = []
    try:
        for key, value in (
            (_USER_REFRESH_KEY, creds.refresh_token),
            (_USER_CLIENT_ID_KEY, creds.client_id),
        ):
            keyring.set_password(SERVICE_NAME_USER, key, value)
            written.append(key)
    except Exception:
        for key in written:
            previous = snapshot[key]
            with contextlib.suppress(Exception):
                if previous is None:
                    keyring.delete_password(SERVICE_NAME_USER, key)
                else:
                    keyring.set_password(SERVICE_NAME_USER, key, previous)
        raise


def load_user_oauth_credentials() -> UserOAuthCredentials | None:
    """Return persisted user-OAuth credentials, or ``None`` if absent.

    Same NoKeyringError-propagates semantics as :func:`load_s2s_credentials`
    (closes #41): the CLI distinguishes "user has not run `zoom auth login`"
    from "this machine has no keyring backend at all".
    """
    refresh = keyring.get_password(SERVICE_NAME_USER, _USER_REFRESH_KEY)
    client_id = keyring.get_password(SERVICE_NAME_USER, _USER_CLIENT_ID_KEY)
    if not (refresh and client_id):
        return None
    return UserOAuthCredentials(refresh_token=refresh, client_id=client_id)


def clear_user_oauth_credentials() -> None:
    """Remove all user-OAuth keyring entries. Safe to call when none exist."""
    for key in _USER_ALL_KEYS:
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(SERVICE_NAME_USER, key)


def has_user_oauth_credentials() -> bool:
    """Cheap "is a user-OAuth session configured?" check.

    Same probe-style semantics as :func:`has_s2s_credentials` — swallows
    backend-missing errors so ``zoom auth status`` doesn't crash on a
    misconfigured machine.
    """
    try:
        return load_user_oauth_credentials() is not None
    except (keyring.errors.NoKeyringError, keyring.errors.InitError):
        return False
