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


def test_load_propagates_no_keyring_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Closes #41: a missing keyring backend is no longer silently flattened
    to ``None`` — that conflated "user has not run `zoom auth s2s set`" with
    a genuine environmental failure. Now the caller (the CLI) translates."""

    def boom(*_args, **_kwargs):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", boom)
    with pytest.raises(keyring.errors.NoKeyringError):
        auth.load_s2s_credentials()


def test_has_s2s_credentials_swallows_no_keyring_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``has_s2s_credentials`` is the probe-style helper used by ``zoom auth
    status``. It deliberately swallows backend-missing errors so a "check
    status" call doesn't blow up on a misconfigured machine."""

    def boom(*_args, **_kwargs):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", boom)
    assert auth.has_s2s_credentials() is False


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


@pytest.mark.parametrize("fail_on_call", [1, 2, 3])
def test_save_rolls_back_on_partial_failure(
    monkeypatch: pytest.MonkeyPatch, fail_on_call: int
) -> None:
    """Closes #45 / verifies #35 fix: a partial keyring failure must not leave
    a hybrid credential set in the keyring. The rollback restores prior state."""
    old = auth.S2SCredentials(account_id="old-acc", client_id="old-cid", client_secret="old-secret")
    auth.save_s2s_credentials(old)

    new = auth.S2SCredentials(account_id="new-acc", client_id="new-cid", client_secret="new-secret")

    real_set = keyring.set_password
    counter = {"calls": 0}

    def flaky_set(service: str, username: str, password: str) -> None:
        counter["calls"] += 1
        if counter["calls"] == fail_on_call:
            raise keyring.errors.KeyringError(f"simulated failure on call {fail_on_call}")
        real_set(service, username, password)

    monkeypatch.setattr(keyring, "set_password", flaky_set)
    with pytest.raises(keyring.errors.KeyringError):
        auth.save_s2s_credentials(new)

    # Rollback should have restored the prior state. Reads use the real
    # keyring backend (we patched set_password, not get_password).
    assert auth.load_s2s_credentials() == old


def test_save_rolls_back_to_empty_when_no_prior_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """If there were no prior credentials, rollback should leave the keyring
    empty rather than partially populated."""
    new = auth.S2SCredentials(account_id="new-acc", client_id="new-cid", client_secret="new-secret")

    real_set = keyring.set_password
    counter = {"calls": 0}

    def flaky_set(service: str, username: str, password: str) -> None:
        counter["calls"] += 1
        # Fail on the third (client_secret) write — first two succeed.
        if counter["calls"] == 3:
            raise keyring.errors.KeyringError("simulated")
        real_set(service, username, password)

    monkeypatch.setattr(keyring, "set_password", flaky_set)
    with pytest.raises(keyring.errors.KeyringError):
        auth.save_s2s_credentials(new)

    # No prior creds → rollback should delete what was written → load returns None.
    assert auth.load_s2s_credentials() is None


# ---- user OAuth credential storage (closes #12 storage layer) ----------


def _user_creds() -> auth.UserOAuthCredentials:
    return auth.UserOAuthCredentials(refresh_token="rt-1", client_id="cid-A")


def test_user_oauth_save_then_load_round_trips() -> None:
    creds = _user_creds()
    auth.save_user_oauth_credentials(creds)
    assert auth.load_user_oauth_credentials() == creds


def test_user_oauth_load_returns_none_when_nothing_saved() -> None:
    assert auth.load_user_oauth_credentials() is None
    assert auth.has_user_oauth_credentials() is False


def test_user_oauth_clear_removes_all_keys() -> None:
    auth.save_user_oauth_credentials(_user_creds())
    auth.clear_user_oauth_credentials()
    assert auth.load_user_oauth_credentials() is None
    for key in ("user.refresh_token", "user.client_id"):
        assert keyring.get_password(auth.SERVICE_NAME_USER, key) is None


def test_user_oauth_clear_is_idempotent() -> None:
    auth.clear_user_oauth_credentials()
    auth.clear_user_oauth_credentials()


def test_user_oauth_load_returns_none_when_only_partial() -> None:
    """Both keys are required; presence of just one means 'not configured'."""
    keyring.set_password(auth.SERVICE_NAME_USER, "user.refresh_token", "only-this")
    assert auth.load_user_oauth_credentials() is None


def test_user_oauth_has_swallows_no_keyring_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a, **_kw):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", boom)
    assert auth.has_user_oauth_credentials() is False


def test_user_oauth_load_propagates_no_keyring_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same #41 policy as S2S: load_* propagates so the CLI can show a
    distinct exit code; has_* swallows for probe-style use."""

    def boom(*_a, **_kw):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", boom)
    with pytest.raises(keyring.errors.NoKeyringError):
        auth.load_user_oauth_credentials()


@pytest.mark.parametrize("fail_on_call", [1, 2])
def test_user_oauth_save_rolls_back_on_partial_failure(
    monkeypatch: pytest.MonkeyPatch, fail_on_call: int
) -> None:
    """Same #35 transactional pattern as S2S save."""
    old = auth.UserOAuthCredentials(refresh_token="OLD-rt", client_id="OLD-cid")
    auth.save_user_oauth_credentials(old)

    new = auth.UserOAuthCredentials(refresh_token="NEW-rt", client_id="NEW-cid")
    real_set = keyring.set_password
    counter = {"calls": 0}

    def flaky(service, username, password):
        counter["calls"] += 1
        if counter["calls"] == fail_on_call:
            raise keyring.errors.KeyringError(f"sim fail call {fail_on_call}")
        real_set(service, username, password)

    monkeypatch.setattr(keyring, "set_password", flaky)
    with pytest.raises(keyring.errors.KeyringError):
        auth.save_user_oauth_credentials(new)

    # Old creds intact after rollback.
    assert auth.load_user_oauth_credentials() == old


def test_user_service_name_pinned() -> None:
    """Future rename would orphan every existing user's saved refresh."""
    assert auth.SERVICE_NAME_USER == "zoom-cli-user-auth"
