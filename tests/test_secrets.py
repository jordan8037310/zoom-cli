"""Tests for zoom_cli.secrets — the OS keyring facade."""

from __future__ import annotations

import keyring
import keyring.errors
import pytest
from zoom_cli import secrets


def test_set_then_get_round_trips() -> None:
    secrets.set_password("daily", "p@ss")
    assert secrets.get_password("daily") == "p@ss"


def test_get_returns_none_for_unknown_meeting() -> None:
    assert secrets.get_password("never-seen") is None


def test_delete_removes_entry() -> None:
    secrets.set_password("temp", "x")
    secrets.delete_password("temp")
    assert secrets.get_password("temp") is None


def test_delete_is_noop_when_entry_absent() -> None:
    # Must not raise.
    secrets.delete_password("never-existed")


def test_set_password_with_empty_string_is_stored() -> None:
    """Caller wants 'no password' → use delete_password. set_password('')
    intentionally writes through; this test just pins that contract."""
    secrets.set_password("empty", "")
    assert secrets.get_password("empty") == ""


def test_get_password_returns_none_when_no_keyring_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Headless Linux boxes without DBus raise NoKeyringError. We treat that
    as 'no stored password' so the CLI degrades gracefully."""

    def boom(*_args, **_kwargs):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", boom)
    assert secrets.get_password("anything") is None


def test_get_password_returns_none_on_init_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """InitError is the other 'no backend' case we degrade gracefully on."""

    def boom(*_args, **_kwargs):
        raise keyring.errors.InitError("backend init failed")

    monkeypatch.setattr(keyring, "get_password", boom)
    assert secrets.get_password("anything") is None


def test_get_password_does_not_swallow_locked_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for python-review on PR #28: a locked-keyring or other
    KeyringError MUST propagate. Silently returning None would launch
    meetings with no password — wrong-launch silently."""

    def boom(*_args, **_kwargs):
        raise keyring.errors.KeyringError("locked or other failure")

    monkeypatch.setattr(keyring, "get_password", boom)
    with pytest.raises(keyring.errors.KeyringError):
        secrets.get_password("anything")


def test_service_name_constant_is_zoom_cli() -> None:
    """Pin the service name so a future rename doesn't silently orphan
    every existing user's stored passwords."""
    assert secrets.SERVICE_NAME == "zoom-cli"
