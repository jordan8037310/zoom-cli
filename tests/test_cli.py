"""End-to-end tests for the Click CLI surface (no interactive prompts)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from zoom_cli import __version__
from zoom_cli.__main__ import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class _FakeQ:
    """Stand-in for ``questionary.text``/``questionary.select`` in CLI tests.

    Each call to ``.ask()`` consumes one queued answer; ``None`` simulates Ctrl-C.
    """

    def __init__(self, answers):
        self._answers = list(answers)

    def __call__(self, *args, **kwargs):
        return self

    def ask(self):
        if not self._answers:
            raise AssertionError("_FakeQ ran out of answers")
        return self._answers.pop(0)


def test_version(runner: CliRunner) -> None:
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


def test_ls_empty(runner: CliRunner, tmp_zoom_cli_home: Path) -> None:
    result = runner.invoke(main, ["ls"])
    assert result.exit_code == 0, result.output
    assert result.output == ""


def test_ls_with_data(runner: CliRunner, write_meetings) -> None:
    write_meetings({"daily": {"id": "1", "password": "p"}})
    result = runner.invoke(main, ["ls"])
    assert result.exit_code == 0, result.output
    assert "daily" in result.output


def test_save_url_via_flags(runner: CliRunner, tmp_zoom_cli_home: Path) -> None:
    result = runner.invoke(
        main,
        ["save", "-n", "standup", "--url", "https://zoom.us/j/1"],
    )
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"standup": {"url": "https://zoom.us/j/1"}}


def test_save_id_password_via_flags(runner: CliRunner, tmp_zoom_cli_home: Path) -> None:
    """Password lands in keyring, not in meetings.json."""
    from zoom_cli import secrets

    result = runner.invoke(
        main,
        ["save", "-n", "standup", "--id", "1234567890", "-p", "pw"],
    )
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"standup": {"id": "1234567890"}}
    assert secrets.get_password("standup") == "pw"


def test_save_url_does_not_prompt_for_password_when_pwd_in_url(
    runner: CliRunner, tmp_zoom_cli_home: Path
) -> None:
    result = runner.invoke(
        main,
        ["save", "-n", "standup", "--url", "https://zoom.us/j/1?pwd=abc"],
    )
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"standup": {"url": "https://zoom.us/j/1?pwd=abc"}}


def test_rm_with_argument_no_prompt(
    runner: CliRunner, write_meetings, tmp_zoom_cli_home: Path
) -> None:
    """Regression: `zoom rm <name>` with a positional name must NOT prompt
    for confirmation — that would break existing scripts and aliases."""
    write_meetings({"a": {"id": "1"}, "b": {"id": "2"}})
    result = runner.invoke(main, ["rm", "a"])
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"b": {"id": "2"}}


def test_rm_dry_run_does_not_modify_file(
    runner: CliRunner, write_meetings, tmp_zoom_cli_home: Path
) -> None:
    write_meetings({"a": {"id": "1"}, "b": {"id": "2"}})
    result = runner.invoke(main, ["rm", "a", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert "a" in result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"a": {"id": "1"}, "b": {"id": "2"}}


def test_rm_interactive_dry_run_does_not_confirm_or_delete(
    runner: CliRunner,
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`zoom rm --dry-run` (no positional name): pick from list, print the
    preview, return without firing the confirmation prompt."""
    import zoom_cli.__main__ as main_mod

    write_meetings({"alpha": {"id": "1"}, "beta": {"id": "2"}})
    monkeypatch.setattr(main_mod.questionary, "select", _FakeQ(["alpha"]))

    result = runner.invoke(main, ["rm", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert "alpha" in result.output
    assert "Remove meeting" not in result.output  # confirm prompt did NOT fire

    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"alpha": {"id": "1"}, "beta": {"id": "2"}}


def test_rm_interactive_confirms_before_deleting(
    runner: CliRunner,
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the name is picked interactively (no positional arg), a
    confirmation prompt must fire. Answering 'n' must abort."""
    import zoom_cli.__main__ as main_mod

    write_meetings({"a": {"id": "1"}})
    monkeypatch.setattr(main_mod.questionary, "select", _FakeQ(["a"]))

    # Click's prompt reads from stdin; feed 'n\n' to decline.
    result = runner.invoke(main, ["rm"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    # Meeting still present.
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert "a" in on_disk


# ---- zoom auth subcommand group (issue #11) -----------------------------


def test_auth_status_when_not_configured(runner: CliRunner) -> None:
    result = runner.invoke(main, ["auth", "status"])
    assert result.exit_code == 0, result.output
    assert "not configured" in result.output


def test_auth_s2s_set_with_env_secret_persists_to_keyring(runner: CliRunner) -> None:
    from zoom_cli import auth

    result = runner.invoke(
        main,
        ["auth", "s2s", "set", "--account-id", "acc-1", "--client-id", "cid-2"],
        env={"ZOOM_CLIENT_SECRET": "csecret-3"},
    )
    assert result.exit_code == 0, result.output
    assert "saved" in result.output.lower()

    loaded = auth.load_s2s_credentials()
    assert loaded is not None
    assert loaded.account_id == "acc-1"
    assert loaded.client_id == "cid-2"
    assert loaded.client_secret == "csecret-3"


def test_auth_s2s_set_rejects_client_secret_flag(runner: CliRunner) -> None:
    """Closes #34: --client-secret must NOT exist as a CLI flag, since values
    in argv land in shell history and are visible via process inspection."""
    result = runner.invoke(
        main,
        [
            "auth",
            "s2s",
            "set",
            "--account-id",
            "acc-1",
            "--client-id",
            "cid-2",
            "--client-secret",
            "should-be-rejected",
        ],
    )
    assert result.exit_code != 0
    # Click prints "No such option" or similar on unknown flags.
    assert "no such option" in result.output.lower() or "unrecognized" in result.output.lower()


def test_auth_s2s_set_reads_account_and_client_id_from_env(runner: CliRunner) -> None:
    """All three identifiers can come from env vars (only client_secret is
    forbidden from the flag path; account_id and client_id are public-ish
    identifiers but env support keeps scripted use ergonomic)."""
    from zoom_cli import auth

    result = runner.invoke(
        main,
        ["auth", "s2s", "set"],
        env={
            "ZOOM_ACCOUNT_ID": "env-acc",
            "ZOOM_CLIENT_ID": "env-cid",
            "ZOOM_CLIENT_SECRET": "env-secret",
        },
    )
    assert result.exit_code == 0, result.output

    loaded = auth.load_s2s_credentials()
    assert loaded is not None
    assert loaded.account_id == "env-acc"
    assert loaded.client_id == "env-cid"
    assert loaded.client_secret == "env-secret"


def test_auth_status_when_configured(runner: CliRunner) -> None:
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))
    result = runner.invoke(main, ["auth", "status"])
    assert result.exit_code == 0, result.output
    assert "configured" in result.output
    assert "not configured" not in result.output


def test_auth_logout_clears_keyring(runner: CliRunner) -> None:
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))
    assert auth.has_s2s_credentials() is True

    result = runner.invoke(main, ["auth", "logout"])
    assert result.exit_code == 0, result.output
    assert "Cleared" in result.output

    assert auth.has_s2s_credentials() is False


def test_auth_s2s_set_does_not_echo_secret_in_output(runner: CliRunner) -> None:
    """Regression: the success message must not echo the secret."""
    secret = "very-secret-do-not-leak-12345"
    result = runner.invoke(
        main,
        ["auth", "s2s", "set", "--account-id", "a", "--client-id", "b"],
        env={"ZOOM_CLIENT_SECRET": secret},
    )
    assert result.exit_code == 0, result.output
    assert secret not in result.output


# ---- zoom users me (PR #31) ----------------------------------------------


def test_users_me_bails_when_no_credentials_saved(runner: CliRunner) -> None:
    result = runner.invoke(main, ["users", "me"])
    assert result.exit_code == 1
    assert "No Server-to-Server" in result.output


def test_users_me_prints_well_known_fields(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    fake_profile = {
        "id": "user-abc",
        "account_id": "acc-xyz",
        "email": "alice@example.com",
        "display_name": "Alice Example",
        "type": 2,
        "status": "active",
        # Some fields we don't expect to print:
        "phone_number": "+1-555-0100",
        "language": "en-US",
    }

    def fake_get_me(_client):
        return fake_profile

    monkeypatch.setattr(main_mod.users, "get_me", fake_get_me)
    # Stub out the OAuth round-trip — ApiClient is created but never exchanges tokens
    # because get_me is replaced wholesale.
    monkeypatch.setattr(
        main_mod.oauth,
        "fetch_access_token",
        lambda *_a, **_k: _fake_access_token(),
    )

    result = runner.invoke(main, ["users", "me"])
    assert result.exit_code == 0, result.output
    assert "alice@example.com" in result.output
    assert "Alice Example" in result.output
    assert "user-abc" in result.output
    assert "acc-xyz" in result.output
    # We don't print every field — phone_number shouldn't appear
    assert "phone_number" not in result.output


def test_users_me_reports_zoom_api_error_distinctly(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth
    from zoom_cli.api.client import ZoomApiError

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    def boom(_client):
        raise ZoomApiError("Something broke", status_code=500, code=9999)

    monkeypatch.setattr(main_mod.users, "get_me", boom)
    monkeypatch.setattr(
        main_mod.oauth,
        "fetch_access_token",
        lambda *_a, **_k: _fake_access_token(),
    )

    result = runner.invoke(main, ["users", "me"])
    assert result.exit_code == 1
    assert "500" in result.output
    assert "Something broke" in result.output


def _fake_access_token():
    from datetime import datetime, timedelta, timezone

    from zoom_cli.api import oauth

    return oauth.AccessToken(
        value="tok",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=3600),
        scopes=("user:read:user",),
    )


# ---- zoom auth s2s test (issue #11 part 2) -------------------------------


def test_auth_s2s_test_bails_when_no_credentials_saved(runner: CliRunner) -> None:
    """`zoom auth s2s test` with nothing configured: print a helpful
    message and exit non-zero so scripts can detect the unconfigured state."""
    result = runner.invoke(main, ["auth", "s2s", "test"])
    assert result.exit_code == 1
    assert "No Server-to-Server" in result.output
    assert "zoom auth s2s set" in result.output


def test_auth_s2s_test_success_prints_ok_and_scopes(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timedelta, timezone

    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth
    from zoom_cli.api import oauth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    fake_token_value = "very-secret-do-not-leak-bearer-12345"
    fake_token = oauth.AccessToken(
        value=fake_token_value,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=3600),
        scopes=("user:read:user", "meeting:read:meeting"),
    )
    monkeypatch.setattr(main_mod.oauth, "fetch_access_token", lambda *_a, **_k: fake_token)

    result = runner.invoke(main, ["auth", "s2s", "test"])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output
    assert "user:read:user" in result.output
    assert "meeting:read:meeting" in result.output
    # The bearer token value itself must never reach stdout.
    assert fake_token_value not in result.output


def test_auth_s2s_test_reports_zoom_auth_error(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth
    from zoom_cli.api import oauth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    def boom(*_a, **_k):
        raise oauth.ZoomAuthError(
            "Invalid client_id or client_secret", status_code=401, error_code="invalid_client"
        )

    monkeypatch.setattr(main_mod.oauth, "fetch_access_token", boom)

    result = runner.invoke(main, ["auth", "s2s", "test"])
    assert result.exit_code == 1
    assert "401" in result.output
    assert "Invalid client_id" in result.output


def test_auth_s2s_test_reports_network_error_distinctly(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinguish 'creds rejected' from 'couldn't reach Zoom' — the user
    needs to know which one to debug."""
    import httpx
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    def boom(*_a, **_k):
        raise httpx.ConnectError("DNS failed")

    monkeypatch.setattr(main_mod.oauth, "fetch_access_token", boom)

    result = runner.invoke(main, ["auth", "s2s", "test"])
    assert result.exit_code == 1
    assert "Could not reach" in result.output
    assert "DNS failed" in result.output


def test_auth_s2s_set_aborts_on_ctrl_c_at_account_prompt(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation at any prompt must not write partial state."""
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    monkeypatch.setattr(main_mod.questionary, "text", _FakeQ([None]))

    result = runner.invoke(main, ["auth", "s2s", "set"])
    assert result.exit_code != 0
    assert auth.has_s2s_credentials() is False


def test_rm_interactive_with_yes_flag_skips_confirmation(
    runner: CliRunner,
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zoom_cli.__main__ as main_mod

    write_meetings({"a": {"id": "1"}})
    monkeypatch.setattr(main_mod.questionary, "select", _FakeQ(["a"]))

    result = runner.invoke(main, ["rm", "--yes"])
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert "a" not in on_disk


def test_default_launch_with_url_argument(
    runner: CliRunner, captured_launches: list[list[str]], tmp_zoom_cli_home: Path
) -> None:
    result = runner.invoke(main, ["https://zoom.us/j/123"])
    assert result.exit_code == 0, result.output
    assert captured_launches == [["open", "zoommtg://zoom.us/j/123"]]


def test_default_launch_with_saved_name(
    runner: CliRunner,
    write_meetings,
    captured_launches: list[list[str]],
) -> None:
    write_meetings({"team": {"id": "777"}})
    result = runner.invoke(main, ["team"])
    assert result.exit_code == 0, result.output
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=777"]]


# ---- Ctrl-C handling (regression — None from questionary.ask()) -----------


def test_save_ctrl_c_on_name_aborts_cleanly(
    runner: CliRunner,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl-C on the name prompt: must exit non-zero, write nothing."""
    import zoom_cli.__main__ as main_mod

    monkeypatch.setattr(main_mod.questionary, "text", _FakeQ([None]))
    monkeypatch.setattr(main_mod.questionary, "select", _FakeQ([None]))

    result = runner.invoke(main, ["save"])
    assert result.exit_code != 0
    assert (tmp_zoom_cli_home / "meetings.json").read_text() == "{}"


def test_save_ctrl_c_on_url_select_does_not_fall_through_to_id_branch(
    runner: CliRunner,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: ``None == "URL"`` evaluated to False, silently routing the
    user into the ID/password branch instead of aborting."""
    import zoom_cli.__main__ as main_mod

    # Name prompt resolves; URL/ID select returns None (Ctrl-C).
    monkeypatch.setattr(main_mod.questionary, "text", _FakeQ(["myname"]))
    monkeypatch.setattr(main_mod.questionary, "select", _FakeQ([None]))

    result = runner.invoke(main, ["save"])
    assert result.exit_code != 0
    assert (tmp_zoom_cli_home / "meetings.json").read_text() == "{}"


def test_rm_ctrl_c_on_name_select_does_not_crash(
    runner: CliRunner,
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: ``name = "" or None`` reached ``del contents[""]`` and
    raised KeyError. Must abort cleanly instead."""
    import zoom_cli.__main__ as main_mod

    write_meetings({"a": {"id": "1"}, "b": {"id": "2"}})
    monkeypatch.setattr(main_mod.questionary, "select", _FakeQ([None]))

    result = runner.invoke(main, ["rm"])
    assert result.exit_code != 0
    # Existing meetings still present.
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert "a" in on_disk and "b" in on_disk


def test_edit_ctrl_c_on_name_select_does_not_crash(
    runner: CliRunner,
    write_meetings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zoom_cli.__main__ as main_mod

    write_meetings({"a": {"id": "1"}})
    monkeypatch.setattr(main_mod.questionary, "select", _FakeQ([None]))

    result = runner.invoke(main, ["edit"])
    assert result.exit_code != 0


def test_rm_with_empty_store_short_circuits(
    runner: CliRunner,
    tmp_zoom_cli_home: Path,
) -> None:
    """No saved meetings → short-circuit with a friendly message instead of
    presenting a select with an empty choice list."""
    result = runner.invoke(main, ["rm"])
    assert result.exit_code == 0
    assert "No saved meetings" in result.output


def test_edit_with_empty_store_short_circuits(
    runner: CliRunner,
    tmp_zoom_cli_home: Path,
) -> None:
    result = runner.invoke(main, ["edit"])
    assert result.exit_code == 0
    assert "No saved meetings" in result.output


# ---- launch command (#38 untrusted-host refusal) -------------------------


def test_launch_refuses_url_with_untrusted_scheme_host(
    runner: CliRunner, captured_launches: list[list[str]]
) -> None:
    """Closes #38: an explicit scheme + non-Zoom host must be refused at the
    CLI layer with a clear error and exit code != 0. Never reaches the
    launcher subprocess."""
    result = runner.invoke(main, ["https://evil.example/zoom.us/j/123"])
    assert result.exit_code != 0
    assert "untrusted host" in result.output.lower()
    assert captured_launches == []


def test_launch_refuses_substring_lookalike(
    runner: CliRunner, captured_launches: list[list[str]]
) -> None:
    """``my-zoom.us-domain.com`` contains the literal substring ``zoom.us``
    but is not a Zoom subdomain. Old substring-based routing accepted it."""
    result = runner.invoke(main, ["https://my-zoom.us-domain.com/j/123"])
    assert result.exit_code != 0
    assert "untrusted host" in result.output.lower()
    assert captured_launches == []


def test_launch_accepts_zoom_subdomain(
    runner: CliRunner, captured_launches: list[list[str]]
) -> None:
    result = runner.invoke(main, ["https://us02web.zoom.us/j/123"])
    assert result.exit_code == 0, result.output
    assert len(captured_launches) == 1
    assert captured_launches[0][1].startswith("zoommtg://us02web.zoom.us/")


def test_launch_accepts_bare_zoom_url_no_scheme(
    runner: CliRunner, captured_launches: list[list[str]]
) -> None:
    result = runner.invoke(main, ["zoom.us/j/123"])
    assert result.exit_code == 0, result.output
    assert len(captured_launches) == 1


def test_launch_routes_non_url_to_saved_meeting_lookup(
    runner: CliRunner, write_meetings, captured_launches: list[list[str]]
) -> None:
    """A bare argument that doesn't parse as a Zoom URL routes to the
    saved-meeting branch (the existing behaviour for `zoom <name>`)."""
    write_meetings({"daily": {"id": "999"}})
    result = runner.invoke(main, ["daily"])
    assert result.exit_code == 0, result.output
    assert len(captured_launches) == 1
    assert "confno=999" in captured_launches[0][1]


# ---- #41 / #43: keyring error translation at CLI boundary ----------------


def _force_keyring_error(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Patch every keyring entry point used by the CLI to raise ``exc``."""
    import keyring

    def boom(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(keyring, "get_password", boom)
    monkeypatch.setattr(keyring, "set_password", boom)
    monkeypatch.setattr(keyring, "delete_password", boom)


def test_s2s_test_translates_no_keyring_to_distinct_exit_code(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closes #41: 'no backend' must give exit 2 with a backend-specific
    message, distinct from the 'not configured' exit 1."""
    import keyring.errors

    _force_keyring_error(monkeypatch, keyring.errors.NoKeyringError("no backend"))
    result = runner.invoke(main, ["auth", "s2s", "test"])
    assert result.exit_code == 2
    assert "keyring backend not available" in result.output.lower()


def test_s2s_test_translates_locked_keyring_to_friendly_error(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closes #43: a generic KeyringError (e.g. locked Keychain) gives a
    friendly message and exit code 3 — not a Python traceback."""
    import keyring.errors

    _force_keyring_error(monkeypatch, keyring.errors.KeyringError("locked"))
    result = runner.invoke(main, ["auth", "s2s", "test"])
    assert result.exit_code == 3
    assert "may be locked" in result.output.lower()
    # No traceback noise.
    assert "Traceback" not in result.output


def test_users_me_translates_keyring_errors(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`zoom users me` must not surface raw KeyringError on a locked
    keychain — it goes through the same translation as auth commands."""
    import keyring.errors

    _force_keyring_error(monkeypatch, keyring.errors.KeyringError("locked"))
    result = runner.invoke(main, ["users", "me"])
    assert result.exit_code == 3
    assert "Traceback" not in result.output


def test_logout_translates_keyring_errors(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import keyring.errors

    _force_keyring_error(monkeypatch, keyring.errors.NoKeyringError("no backend"))
    result = runner.invoke(main, ["auth", "logout"])
    assert result.exit_code == 2
    assert "keyring backend not available" in result.output.lower()


def test_status_swallows_no_backend_and_reports_not_configured(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``zoom auth status`` is a probe-style command — it should not exit
    non-zero just because the backend is missing. The friendly 'not
    configured' message is enough; users debugging a real backend issue
    use ``zoom auth s2s test``."""
    import keyring.errors

    _force_keyring_error(monkeypatch, keyring.errors.NoKeyringError("no backend"))
    result = runner.invoke(main, ["auth", "status"])
    assert result.exit_code == 0
    assert "not configured" in result.output


def test_s2s_set_translates_keyring_save_error(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the keyring write itself fails (locked backend), the user gets a
    friendly error, not a raw exception trace."""
    import keyring
    import keyring.errors

    # `save` reads existing values first (snapshot) — those reads succeed
    # on the in-memory backend. The first set_password fails.
    real_set = keyring.set_password

    def boom(service, username, password):
        raise keyring.errors.KeyringError("locked")

    monkeypatch.setattr(keyring, "set_password", boom)
    result = runner.invoke(
        main,
        ["auth", "s2s", "set", "--account-id", "a", "--client-id", "b"],
        env={"ZOOM_CLIENT_SECRET": "c"},
    )
    assert result.exit_code == 3
    assert "may be locked" in result.output.lower()
    # Restore for fixture teardown.
    monkeypatch.setattr(keyring, "set_password", real_set)


# ---- #14: zoom users get / list CLI ------------------------------------


def test_users_get_bails_when_no_credentials(runner: CliRunner) -> None:
    result = runner.invoke(main, ["users", "get", "u-123"])
    assert result.exit_code == 1
    assert "No Server-to-Server" in result.output


def test_users_get_prints_well_known_fields(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    captured = {}

    def fake_get_user(_client, user_id):
        captured["user_id"] = user_id
        return {
            "id": "u-target",
            "email": "bob@example.com",
            "display_name": "Bob Example",
            "type": 1,
            "status": "active",
        }

    monkeypatch.setattr(main_mod.users, "get_user", fake_get_user)
    monkeypatch.setattr(
        main_mod.oauth,
        "fetch_access_token",
        lambda *_a, **_k: _fake_access_token(),
    )

    result = runner.invoke(main, ["users", "get", "u-target"])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "u-target"
    assert "bob@example.com" in result.output
    assert "Bob Example" in result.output


def test_users_get_passes_email_through_unmodified(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zoom accepts an email as `user_id` for `GET /users/<email>`."""
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    captured = {}

    def fake_get_user(_client, user_id):
        captured["user_id"] = user_id
        return {"id": "u-1", "email": "alice@example.com"}

    monkeypatch.setattr(main_mod.users, "get_user", fake_get_user)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )

    result = runner.invoke(main, ["users", "get", "alice@example.com"])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "alice@example.com"


def test_users_list_bails_when_no_credentials(runner: CliRunner) -> None:
    result = runner.invoke(main, ["users", "list"])
    assert result.exit_code == 1
    assert "No Server-to-Server" in result.output


def test_users_list_prints_tab_separated_with_header(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    captured = {}

    def fake_list_users(_client, *, status, page_size):
        captured["status"] = status
        captured["page_size"] = page_size
        return iter(
            [
                {"id": "u-1", "email": "alice@example.com", "type": 1, "status": "active"},
                {"id": "u-2", "email": "bob@example.com", "type": 2, "status": "active"},
            ]
        )

    monkeypatch.setattr(main_mod.users, "list_users", fake_list_users)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )

    result = runner.invoke(main, ["users", "list"])
    assert result.exit_code == 0, result.output

    lines = result.output.strip().split("\n")
    assert lines[0] == "user_id\temail\ttype\tstatus"
    assert lines[1] == "u-1\talice@example.com\t1\tactive"
    assert lines[2] == "u-2\tbob@example.com\t2\tactive"

    # Default filter values flow through.
    assert captured["status"] == "active"
    assert captured["page_size"] == 300


def test_users_list_forwards_status_and_page_size(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    captured = {}

    def fake_list_users(_client, *, status, page_size):
        captured["status"] = status
        captured["page_size"] = page_size
        return iter([])

    monkeypatch.setattr(main_mod.users, "list_users", fake_list_users)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )

    result = runner.invoke(main, ["users", "list", "--status", "pending", "--page-size", "50"])
    assert result.exit_code == 0, result.output
    assert captured["status"] == "pending"
    assert captured["page_size"] == 50


def test_users_list_rejects_invalid_status(runner: CliRunner) -> None:
    """click.Choice should reject anything outside active/inactive/pending."""
    result = runner.invoke(main, ["users", "list", "--status", "garbage"])
    assert result.exit_code != 0
    assert "garbage" in result.output.lower() or "invalid" in result.output.lower()


def test_users_list_rejects_oversize_page(runner: CliRunner) -> None:
    """click.IntRange should cap at 300 (Zoom's per-endpoint maximum)."""
    result = runner.invoke(main, ["users", "list", "--page-size", "5000"])
    assert result.exit_code != 0


# ---- #13 (read-only): zoom meetings get / list CLI ----------------------


def test_meetings_get_bails_when_no_credentials(runner: CliRunner) -> None:
    result = runner.invoke(main, ["meetings", "get", "12345"])
    assert result.exit_code == 1
    assert "No Server-to-Server" in result.output


def test_meetings_get_prints_well_known_fields(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    captured = {}

    def fake_get_meeting(_client, meeting_id):
        captured["meeting_id"] = meeting_id
        return {
            "id": 12345,
            "topic": "Daily standup",
            "type": 2,
            "status": "started",
            "start_time": "2026-04-28T15:00:00Z",
            "duration": 30,
            "timezone": "UTC",
            "host_email": "alice@example.com",
            "join_url": "https://zoom.us/j/12345",
            # Fields we don't print:
            "agenda": "🚀 launch",
            "settings": {"approval_type": 0},
        }

    monkeypatch.setattr(main_mod.meetings, "get_meeting", fake_get_meeting)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )

    result = runner.invoke(main, ["meetings", "get", "12345"])
    assert result.exit_code == 0, result.output
    assert captured["meeting_id"] == "12345"
    assert "Daily standup" in result.output
    assert "alice@example.com" in result.output
    assert "agenda" not in result.output  # not in the printed subset
    assert "settings" not in result.output


def test_meetings_list_bails_when_no_credentials(runner: CliRunner) -> None:
    result = runner.invoke(main, ["meetings", "list"])
    assert result.exit_code == 1
    assert "No Server-to-Server" in result.output


def test_meetings_list_prints_tab_separated_with_header(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    captured = {}

    def fake_list_meetings(_client, *, user_id, meeting_type, page_size):
        captured["user_id"] = user_id
        captured["meeting_type"] = meeting_type
        captured["page_size"] = page_size
        return iter(
            [
                {
                    "id": 11,
                    "topic": "M1",
                    "type": 2,
                    "start_time": "2026-04-28T10:00:00Z",
                    "duration": 30,
                },
                {
                    "id": 22,
                    "topic": "M2",
                    "type": 8,
                    "start_time": "2026-04-29T11:00:00Z",
                    "duration": 60,
                },
            ]
        )

    monkeypatch.setattr(main_mod.meetings, "list_meetings", fake_list_meetings)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )

    result = runner.invoke(main, ["meetings", "list"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "id\ttopic\ttype\tstart_time\tduration"
    assert lines[1] == "11\tM1\t2\t2026-04-28T10:00:00Z\t30"
    assert lines[2] == "22\tM2\t8\t2026-04-29T11:00:00Z\t60"

    # Defaults flow through.
    assert captured["user_id"] == "me"
    assert captured["meeting_type"] == "scheduled"
    assert captured["page_size"] == 300


def test_meetings_list_forwards_user_id_type_page_size(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    captured = {}

    def fake_list_meetings(_client, *, user_id, meeting_type, page_size):
        captured.update({"user_id": user_id, "meeting_type": meeting_type, "page_size": page_size})
        return iter([])

    monkeypatch.setattr(main_mod.meetings, "list_meetings", fake_list_meetings)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )

    result = runner.invoke(
        main,
        [
            "meetings",
            "list",
            "--user-id",
            "alice@example.com",
            "--type",
            "live",
            "--page-size",
            "50",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "alice@example.com"
    assert captured["meeting_type"] == "live"
    assert captured["page_size"] == 50


def test_meetings_list_rejects_unknown_type(runner: CliRunner) -> None:
    result = runner.invoke(main, ["meetings", "list", "--type", "garbage"])
    assert result.exit_code != 0


def test_meetings_list_rejects_oversize_page(runner: CliRunner) -> None:
    result = runner.invoke(main, ["meetings", "list", "--page-size", "5000"])
    assert result.exit_code != 0
