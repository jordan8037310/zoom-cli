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

    Catches only the "no backend available" errors (``NoKeyringError``,
    ``InitError``) so the CLI degrades gracefully on a headless Linux box
    with no DBus. Locked-keyring errors and other failures are intentionally
    NOT caught here — those mean the backend is present but refused, and a
    silent fall-through would launch meetings with the wrong (or no)
    password. The caller sees the exception and can decide what to do.
    """
    try:
        return keyring.get_password(SERVICE_NAME, meeting_name)
    except (keyring.errors.NoKeyringError, keyring.errors.InitError):
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
