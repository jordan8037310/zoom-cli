"""Tests for zoom_cli.auth — S2S OAuth credential storage."""

from __future__ import annotations

import keyring
import keyring.errors
import pytest
from zoom_cli import auth


def _sample_creds() -> auth.S2SCredentials:
    return auth.S2SCredentials(
        account_id="acc-123",
        client_id="cid-456",
        client_secret="csecret-789",
    )


def test_save_then_load_round_trips() -> None:
    creds = _sample_creds()
    auth.save_s2s_credentials(creds)
    loaded = auth.load_s2s_credentials()
    assert loaded == creds


def test_load_returns_none_when_nothing_saved() -> None:
    assert auth.load_s2s_credentials() is None
    assert auth.has_s2s_credentials() is False


def test_load_returns_none_when_only_partial_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """If only some of the three fields are present, treat as not-configured.
    All three are required for the OAuth round-trip."""
    keyring.set_password(auth.SERVICE_NAME, "s2s.account_id", "only-this-one")
    assert auth.load_s2s_credentials() is None


def test_clear_removes_all_three_keys() -> None:
    auth.save_s2s_credentials(_sample_creds())
    auth.clear_s2s_credentials()
    assert auth.load_s2s_credentials() is None
    # Each individual key must also be gone.
    for key in ("s2s.account_id", "s2s.client_id", "s2s.client_secret"):
        assert keyring.get_password(auth.SERVICE_NAME, key) is None


def test_clear_is_idempotent() -> None:
    # Must not raise when nothing's there to clear.
    auth.clear_s2s_credentials()
    auth.clear_s2s_credentials()


def test_has_s2s_credentials_true_when_all_present() -> None:
    auth.save_s2s_credentials(_sample_creds())
    assert auth.has_s2s_credentials() is True


def test_load_returns_none_on_no_keyring_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", boom)
    assert auth.load_s2s_credentials() is None


def test_load_does_not_swallow_locked_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same precedent as zoom_cli.secrets — locked keyring must propagate
    rather than silently report 'not configured', because the latter would
    let `zoom auth s2s test` decide we have no creds and fall over with
    an unhelpful message."""

    def boom(*_args, **_kwargs):
        raise keyring.errors.KeyringError("locked")

    monkeypatch.setattr(keyring, "get_password", boom)
    with pytest.raises(keyring.errors.KeyringError):
        auth.load_s2s_credentials()


def test_service_name_constant_is_pinned() -> None:
    """A future rename would orphan every existing user's saved credentials."""
    assert auth.SERVICE_NAME == "zoom-cli-auth"
