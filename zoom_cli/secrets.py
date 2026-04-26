"""OS keyring-backed password storage for saved meetings.

Replaces the prior practice of writing meeting passwords as plaintext into
``~/.zoom-cli/meetings.json``. Each saved meeting's password lives under the
keyring service ``zoom-cli`` keyed by the meeting name.

Storage layout
--------------
- macOS: Keychain
- Linux: Secret Service (libsecret) / KWallet
- Windows: Credential Manager

The :data:`SERVICE_NAME` constant is the only thing other modules import.
Tests can swap the keyring backend with ``keyring.set_keyring(...)`` for
isolation; nothing in this module touches the real keyring at import time.
"""

from __future__ import annotations

import contextlib

import keyring
import keyring.errors

SERVICE_NAME = "zoom-cli"


def get_password(meeting_name: str) -> str | None:
    """Return the saved password for ``meeting_name`` or ``None`` if missing.

    Returns ``None`` (not the empty string) when the entry doesn't exist so
    callers can distinguish "not in keyring" from "saved as empty"; current
    callers don't rely on that distinction but future callers might.
    """
    try:
        return keyring.get_password(SERVICE_NAME, meeting_name)
    except keyring.errors.KeyringError:
        # Backend unavailable (e.g. no DBus on a headless Linux box). Treat
        # as "no stored password" so the CLI degrades gracefully — meetings
        # without a stored password just prompt or fail at launch.
        return None


def set_password(meeting_name: str, password: str) -> None:
    """Store ``password`` under ``meeting_name``.

    Empty strings are written through; callers that want "no password" should
    call :func:`delete_password` instead.
    """
    keyring.set_password(SERVICE_NAME, meeting_name, password)


def delete_password(meeting_name: str) -> None:
    """Remove the entry for ``meeting_name``. No-op if it doesn't exist."""
    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        keyring.delete_password(SERVICE_NAME, meeting_name)
