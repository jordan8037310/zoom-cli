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
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"standup": {"url": "https://zoom.us/j/1"}}


def test_save_id_password_via_flags(runner: CliRunner, tmp_zoom_cli_home: Path) -> None:
    """Password lands in keyring, not in meetings.json."""
    from zoom_cli import secrets

    result = runner.invoke(
        main,
        ["save", "-n", "standup", "--id", "1234567890", "-p", "pw"],
    )
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
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
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"standup": {"url": "https://zoom.us/j/1?pwd=abc"}}


def test_rm_with_argument_no_prompt(
    runner: CliRunner, write_meetings, tmp_zoom_cli_home: Path
) -> None:
    """Regression: `zoom rm <name>` with a positional name must NOT prompt
    for confirmation — that would break existing scripts and aliases."""
    write_meetings({"a": {"id": "1"}, "b": {"id": "2"}})
    result = runner.invoke(main, ["rm", "a"])
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"b": {"id": "2"}}


def test_rm_dry_run_does_not_modify_file(
    runner: CliRunner, write_meetings, tmp_zoom_cli_home: Path
) -> None:
    write_meetings({"a": {"id": "1"}, "b": {"id": "2"}})
    result = runner.invoke(main, ["rm", "a", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert "a" in result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
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

    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
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
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
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
    """S2S configured + user-OAuth not configured. The output now reports
    both surfaces (closes #12 status integration), so we just assert the
    S2S half is shown as configured."""
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))
    result = runner.invoke(main, ["auth", "status"])
    assert result.exit_code == 0, result.output
    assert "Server-to-Server OAuth: configured" in result.output


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
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
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
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
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


# ---- #13 (write): zoom meetings create / update / delete / end -----------


def _patch_meetings_module(monkeypatch: pytest.MonkeyPatch, **funcs):
    """Helper: patch zoom_cli.api.meetings functions and OAuth fetch."""
    import zoom_cli.__main__ as main_mod

    for name, fn in funcs.items():
        monkeypatch.setattr(main_mod.meetings, name, fn)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )


def _save_creds():
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))


# create


def test_meetings_create_requires_topic(runner: CliRunner) -> None:
    result = runner.invoke(main, ["meetings", "create"])
    assert result.exit_code != 0
    assert "topic" in result.output.lower() or "missing" in result.output.lower()


def test_meetings_create_builds_payload_and_prints_result(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_create(_client, payload, *, user_id):
        captured["payload"] = payload
        captured["user_id"] = user_id
        return {
            "id": 555,
            "topic": payload.get("topic"),
            "type": payload.get("type"),
            "join_url": "https://zoom.us/j/555",
        }

    _patch_meetings_module(monkeypatch, create_meeting=fake_create)

    result = runner.invoke(
        main,
        [
            "meetings",
            "create",
            "--topic",
            "Standup",
            "--type",
            "2",
            "--start-time",
            "2026-04-29T15:00:00Z",
            "--duration",
            "30",
            "--password",
            "abc",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "me"
    assert captured["payload"] == {
        "topic": "Standup",
        "type": 2,
        "start_time": "2026-04-29T15:00:00Z",
        "duration": 30,
        "password": "abc",
    }
    assert "555" in result.output
    assert "Standup" in result.output


# update


def test_meetings_update_rejects_no_fields(runner: CliRunner) -> None:
    _save_creds()
    result = runner.invoke(main, ["meetings", "update", "12345"])
    assert result.exit_code == 1
    assert "Nothing to update" in result.output


def test_meetings_update_sends_only_provided_fields(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_update(_client, meeting_id, payload):
        captured["meeting_id"] = meeting_id
        captured["payload"] = payload
        return {}

    _patch_meetings_module(monkeypatch, update_meeting=fake_update)

    result = runner.invoke(
        main,
        ["meetings", "update", "12345", "--topic", "New title", "--duration", "45"],
    )
    assert result.exit_code == 0, result.output
    assert captured["meeting_id"] == "12345"
    assert captured["payload"] == {"topic": "New title", "duration": 45}
    assert "Updated meeting 12345" in result.output


# create / update --from-json (settings + recurrence escape hatch)


def test_meetings_create_from_json_sends_full_payload(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """--from-json is the escape hatch for the full create-meeting body
    (settings sub-object + recurrence) that the per-field flags don't
    expose. The JSON content goes through verbatim."""
    _save_creds()
    json_file = tmp_path / "meeting.json"
    json_file.write_text(
        '{"topic": "Weekly", "type": 8, "recurrence": {"type": 2, "repeat_interval": 1}, '
        '"settings": {"join_before_host": true, "waiting_room": false}}'
    )

    captured = {}

    def fake_create(_client, payload, *, user_id):
        captured["payload"] = payload
        captured["user_id"] = user_id
        return {"id": 999, "topic": payload.get("topic"), "join_url": "https://zoom.us/j/999"}

    _patch_meetings_module(monkeypatch, create_meeting=fake_create)
    result = runner.invoke(main, ["meetings", "create", "--from-json", str(json_file)])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "me"
    assert captured["payload"] == {
        "topic": "Weekly",
        "type": 8,
        "recurrence": {"type": 2, "repeat_interval": 1},
        "settings": {"join_before_host": True, "waiting_room": False},
    }


def test_meetings_create_from_json_mutually_exclusive_with_field_flags(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "meeting.json"
    json_file.write_text('{"topic": "x"}')

    _patch_meetings_module(monkeypatch, create_meeting=lambda *_a, **_k: {})
    result = runner.invoke(
        main,
        ["meetings", "create", "--from-json", str(json_file), "--topic", "Other"],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_meetings_create_from_json_rejects_invalid_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "meeting.json"
    json_file.write_text("not valid {{{")

    _patch_meetings_module(monkeypatch, create_meeting=lambda *_a, **_k: {})
    result = runner.invoke(main, ["meetings", "create", "--from-json", str(json_file)])
    assert result.exit_code == 1
    assert "Invalid JSON" in result.output


def test_meetings_create_from_json_rejects_non_dict(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "meeting.json"
    json_file.write_text('["not", "a", "dict"]')

    _patch_meetings_module(monkeypatch, create_meeting=lambda *_a, **_k: {})
    result = runner.invoke(main, ["meetings", "create", "--from-json", str(json_file)])
    assert result.exit_code == 1
    assert "must be a JSON object" in result.output


def test_meetings_update_from_json_sends_full_payload(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """--from-json on update lets you PATCH the settings sub-object that
    per-field flags can't reach."""
    _save_creds()
    json_file = tmp_path / "patch.json"
    json_file.write_text('{"settings": {"join_before_host": false}}')

    captured = {}

    def fake_update(_client, meeting_id, payload):
        captured["meeting_id"] = meeting_id
        captured["payload"] = payload

    _patch_meetings_module(monkeypatch, update_meeting=fake_update)
    result = runner.invoke(main, ["meetings", "update", "12345", "--from-json", str(json_file)])
    assert result.exit_code == 0, result.output
    assert captured["meeting_id"] == "12345"
    assert captured["payload"] == {"settings": {"join_before_host": False}}


def test_meetings_update_from_json_mutually_exclusive_with_field_flags(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "patch.json"
    json_file.write_text('{"topic": "x"}')

    _patch_meetings_module(monkeypatch, update_meeting=lambda *_a, **_k: None)
    result = runner.invoke(
        main,
        ["meetings", "update", "12345", "--from-json", str(json_file), "--topic", "Other"],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


# delete


def test_meetings_delete_dry_run_does_not_call_api(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    called = {"n": 0}

    def fake_delete(*_a, **_k):
        called["n"] += 1
        return {}

    _patch_meetings_module(monkeypatch, delete_meeting=fake_delete)

    result = runner.invoke(main, ["meetings", "delete", "12345", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert "12345" in result.output
    assert called["n"] == 0


def test_meetings_delete_confirms_before_deleting(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --yes, the user must type 'y' to confirm."""
    _save_creds()
    called = {"n": 0}

    def fake_delete(*_a, **_k):
        called["n"] += 1
        return {}

    _patch_meetings_module(monkeypatch, delete_meeting=fake_delete)

    # Decline the prompt.
    result = runner.invoke(main, ["meetings", "delete", "12345"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_meetings_delete_yes_skips_confirmation(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_delete(_client, meeting_id, *, schedule_for_reminder, cancel_meeting_reminder):
        captured["meeting_id"] = meeting_id
        captured["schedule_for_reminder"] = schedule_for_reminder
        captured["cancel_meeting_reminder"] = cancel_meeting_reminder
        return {}

    _patch_meetings_module(monkeypatch, delete_meeting=fake_delete)

    result = runner.invoke(main, ["meetings", "delete", "12345", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["meeting_id"] == "12345"
    assert captured["schedule_for_reminder"] is False
    assert captured["cancel_meeting_reminder"] is False
    assert "Deleted meeting 12345" in result.output


def test_meetings_delete_forwards_notify_flags(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_delete(_client, meeting_id, *, schedule_for_reminder, cancel_meeting_reminder):
        captured["schedule_for_reminder"] = schedule_for_reminder
        captured["cancel_meeting_reminder"] = cancel_meeting_reminder
        return {}

    _patch_meetings_module(monkeypatch, delete_meeting=fake_delete)

    result = runner.invoke(
        main,
        [
            "meetings",
            "delete",
            "12345",
            "--yes",
            "--notify-host",
            "--notify-registrants",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["schedule_for_reminder"] is True
    assert captured["cancel_meeting_reminder"] is True


# end


def test_meetings_end_confirms_before_ending(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    called = {"n": 0}

    def fake_end(*_a, **_k):
        called["n"] += 1
        return {}

    _patch_meetings_module(monkeypatch, end_meeting=fake_end)

    result = runner.invoke(main, ["meetings", "end", "12345"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert "kicks all participants" in result.output
    assert called["n"] == 0


def test_meetings_end_yes_skips_confirmation(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_end(_client, meeting_id):
        captured["meeting_id"] = meeting_id
        return {}

    _patch_meetings_module(monkeypatch, end_meeting=fake_end)

    result = runner.invoke(main, ["meetings", "end", "12345", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["meeting_id"] == "12345"
    assert "Ended meeting 12345" in result.output


# ---- meeting registrants (depth-completion follow-up to #13) ------------


def test_meetings_registrants_list_prints_tsv(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, meeting_id, *, status, page_size):
        assert meeting_id == "12345"
        assert status == "pending"
        return iter(
            [
                {
                    "id": "r-1",
                    "email": "a@e.com",
                    "first_name": "A",
                    "last_name": "Z",
                    "status": "pending",
                },
                {
                    "id": "r-2",
                    "email": "b@e.com",
                    "first_name": "B",
                    "last_name": "Y",
                    "status": "pending",
                },
            ]
        )

    _patch_meetings_module(monkeypatch, list_registrants=fake_list)
    result = runner.invoke(main, ["meetings", "registrants", "list", "12345"])
    assert result.exit_code == 0, result.output
    assert "id\temail\tfirst_name\tlast_name\tstatus" in result.output
    assert "r-1\ta@e.com\tA\tZ\tpending" in result.output
    assert "r-2\tb@e.com\tB\tY\tpending" in result.output


def test_meetings_registrants_list_forwards_status(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_list(_client, _meeting_id, *, status, page_size):
        captured["status"] = status
        return iter([])

    _patch_meetings_module(monkeypatch, list_registrants=fake_list)
    result = runner.invoke(
        main, ["meetings", "registrants", "list", "12345", "--status", "approved"]
    )
    assert result.exit_code == 0, result.output
    assert captured["status"] == "approved"


def test_meetings_registrants_add_field_flags_build_payload(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_add(_client, meeting_id, payload):
        captured["meeting_id"] = meeting_id
        captured["payload"] = payload
        return {"registrant_id": "rid-1", "join_url": "https://zoom.us/w/12345?tk=xyz"}

    _patch_meetings_module(monkeypatch, add_registrant=fake_add)
    result = runner.invoke(
        main,
        [
            "meetings",
            "registrants",
            "add",
            "12345",
            "--email",
            "a@e.com",
            "--first-name",
            "A",
            "--last-name",
            "Z",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["meeting_id"] == "12345"
    assert captured["payload"] == {
        "email": "a@e.com",
        "first_name": "A",
        "last_name": "Z",
    }
    assert "rid-1" in result.output
    assert "https://zoom.us/w/12345?tk=xyz" in result.output


def test_meetings_registrants_add_requires_email_and_first_name(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    _patch_meetings_module(monkeypatch, add_registrant=lambda *_a, **_k: {})
    result = runner.invoke(main, ["meetings", "registrants", "add", "12345", "--email", "a@e.com"])
    assert result.exit_code == 1
    assert "--email" in result.output and "--first-name" in result.output


def test_meetings_registrants_add_from_json_sends_full_payload(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "reg.json"
    json_file.write_text(
        '{"email": "a@e.com", "first_name": "A", "custom_questions": '
        '[{"title": "Company", "value": "Acme"}]}'
    )
    captured: dict[str, object] = {}

    def fake_add(_client, _meeting_id, payload):
        captured["payload"] = payload
        return {"registrant_id": "rid-2"}

    _patch_meetings_module(monkeypatch, add_registrant=fake_add)
    result = runner.invoke(
        main,
        ["meetings", "registrants", "add", "12345", "--from-json", str(json_file)],
    )
    assert result.exit_code == 0, result.output
    assert captured["payload"] == {
        "email": "a@e.com",
        "first_name": "A",
        "custom_questions": [{"title": "Company", "value": "Acme"}],
    }


def test_meetings_registrants_add_from_json_mutually_exclusive(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "reg.json"
    json_file.write_text('{"email": "a@e.com", "first_name": "A"}')
    _patch_meetings_module(monkeypatch, add_registrant=lambda *_a, **_k: {})
    result = runner.invoke(
        main,
        [
            "meetings",
            "registrants",
            "add",
            "12345",
            "--from-json",
            str(json_file),
            "--email",
            "b@e.com",
        ],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


@pytest.mark.parametrize(
    "subcmd,expected_action,past",
    [
        ("approve", "approve", "Approved"),
        ("deny", "deny", "Denied"),
        ("cancel", "cancel", "Cancelled"),
    ],
)
def test_meetings_registrants_status_actions_send_correct_action(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    subcmd: str,
    expected_action: str,
    past: str,
) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_update(_client, meeting_id, *, action, registrant_ids):
        captured["meeting_id"] = meeting_id
        captured["action"] = action
        captured["registrant_ids"] = list(registrant_ids)
        return {}

    _patch_meetings_module(monkeypatch, update_registrant_status=fake_update)
    result = runner.invoke(
        main,
        [
            "meetings",
            "registrants",
            subcmd,
            "12345",
            "--registrant",
            "r-1",
            "--registrant",
            "r-2",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["action"] == expected_action
    assert captured["registrant_ids"] == ["r-1", "r-2"]
    assert past in result.output


def test_meetings_registrants_approve_confirms_before_acting(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --yes, an explicit 'n' aborts and the API is not called."""
    _save_creds()
    called = {"n": 0}

    def fake_update(*_a, **_k):
        called["n"] += 1
        return {}

    _patch_meetings_module(monkeypatch, update_registrant_status=fake_update)
    result = runner.invoke(
        main,
        [
            "meetings",
            "registrants",
            "approve",
            "12345",
            "--registrant",
            "r-1",
        ],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_meetings_registrants_questions_get_prints_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    payload = {
        "questions": [{"field_name": "city", "required": True}],
        "custom_questions": [],
    }

    def fake_get(_client, meeting_id):
        assert meeting_id == "12345"
        return payload

    _patch_meetings_module(monkeypatch, get_registration_questions=fake_get)
    result = runner.invoke(main, ["meetings", "registrants", "questions", "get", "12345"])
    assert result.exit_code == 0, result.output
    # Parses back as JSON cleanly — the round-trip property the help text promises.
    import json as _json

    parsed = _json.loads(result.output)
    assert parsed == payload


def test_meetings_registrants_questions_update_yes_calls_patch(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "q.json"
    json_file.write_text('{"questions": [{"field_name": "country", "required": false}]}')
    captured: dict[str, object] = {}

    def fake_update(_client, meeting_id, payload):
        captured["meeting_id"] = meeting_id
        captured["payload"] = payload

    _patch_meetings_module(monkeypatch, update_registration_questions=fake_update)
    result = runner.invoke(
        main,
        [
            "meetings",
            "registrants",
            "questions",
            "update",
            "12345",
            "--from-json",
            str(json_file),
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["payload"] == {"questions": [{"field_name": "country", "required": False}]}


# ---- meeting polls (depth-completion follow-up to #13) -----------------


def test_meetings_polls_list_prints_tsv(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()

    def fake_list(_client, meeting_id):
        assert meeting_id == "12345"
        return {
            "total_records": 2,
            "polls": [
                {"id": "p-1", "title": "Q1", "status": "started", "anonymous": False},
                {"id": "p-2", "title": "Q2", "status": "ended", "anonymous": True},
            ],
        }

    _patch_meetings_module(monkeypatch, list_polls=fake_list)
    result = runner.invoke(main, ["meetings", "polls", "list", "12345"])
    assert result.exit_code == 0, result.output
    assert "id\ttitle\tstatus\tanonymous" in result.output
    assert "p-1\tQ1\tstarted\tFalse" in result.output
    assert "p-2\tQ2\tended\tTrue" in result.output


def test_meetings_polls_get_prints_json(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    payload = {"id": "p-1", "title": "Q1", "questions": []}

    def fake_get(_client, meeting_id, poll_id):
        assert (meeting_id, poll_id) == ("12345", "p-1")
        return payload

    _patch_meetings_module(monkeypatch, get_poll=fake_get)
    result = runner.invoke(main, ["meetings", "polls", "get", "12345", "p-1"])
    assert result.exit_code == 0, result.output
    import json as _json

    assert _json.loads(result.output) == payload


def test_meetings_polls_create_sends_payload(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "poll.json"
    json_file.write_text(
        '{"title": "T", "questions": [{"name": "Q1", "type": "single", "answers": ["A", "B"]}]}'
    )
    captured: dict[str, object] = {}

    def fake_create(_client, meeting_id, payload):
        captured["meeting_id"] = meeting_id
        captured["payload"] = payload
        return {"id": "p-new", "title": "T"}

    _patch_meetings_module(monkeypatch, create_poll=fake_create)
    result = runner.invoke(
        main,
        ["meetings", "polls", "create", "12345", "--from-json", str(json_file)],
    )
    assert result.exit_code == 0, result.output
    assert captured["meeting_id"] == "12345"
    assert captured["payload"]["title"] == "T"
    assert "Created poll" in result.output
    assert "p-new" in result.output


def test_meetings_polls_create_rejects_invalid_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "poll.json"
    json_file.write_text("not valid json {{{")
    _patch_meetings_module(monkeypatch, create_poll=lambda *_a, **_k: {})
    result = runner.invoke(
        main, ["meetings", "polls", "create", "12345", "--from-json", str(json_file)]
    )
    assert result.exit_code == 1
    assert "Invalid JSON" in result.output


def test_meetings_polls_update_yes_skips_confirm(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "poll.json"
    json_file.write_text('{"title": "T2", "questions": []}')
    captured: dict[str, object] = {}

    def fake_update(_client, meeting_id, poll_id, payload):
        captured["meeting_id"] = meeting_id
        captured["poll_id"] = poll_id
        captured["payload"] = payload

    _patch_meetings_module(monkeypatch, update_poll=fake_update)
    result = runner.invoke(
        main,
        [
            "meetings",
            "polls",
            "update",
            "12345",
            "p-1",
            "--from-json",
            str(json_file),
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["poll_id"] == "p-1"
    assert "Updated poll" in result.output


def test_meetings_polls_update_confirms_and_aborts(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Without --yes, an explicit 'n' aborts and the API is not called."""
    _save_creds()
    json_file = tmp_path / "poll.json"
    json_file.write_text('{"title": "T2", "questions": []}')
    called = {"n": 0}

    def fake_update(*_a, **_k):
        called["n"] += 1

    _patch_meetings_module(monkeypatch, update_poll=fake_update)
    result = runner.invoke(
        main,
        ["meetings", "polls", "update", "12345", "p-1", "--from-json", str(json_file)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_meetings_polls_delete_yes_calls_api(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_delete(_client, meeting_id, poll_id):
        captured["meeting_id"] = meeting_id
        captured["poll_id"] = poll_id

    _patch_meetings_module(monkeypatch, delete_poll=fake_delete)
    result = runner.invoke(main, ["meetings", "polls", "delete", "12345", "p-1", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured == {"meeting_id": "12345", "poll_id": "p-1"}
    assert "Deleted poll p-1" in result.output


def test_meetings_polls_delete_confirms_and_aborts(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    called = {"n": 0}

    def fake_delete(*_a, **_k):
        called["n"] += 1

    _patch_meetings_module(monkeypatch, delete_poll=fake_delete)
    result = runner.invoke(main, ["meetings", "polls", "delete", "12345", "p-1"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_meetings_polls_results_prints_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past-meeting poll results — different namespace, JSON output."""
    _save_creds()
    payload = {
        "id": 12345,
        "questions": [{"name": "Q1", "question_details": [{"answer": "A", "count": 3}]}],
    }

    def fake_results(_client, meeting_id):
        assert meeting_id == "12345"
        return payload

    _patch_meetings_module(monkeypatch, list_past_poll_results=fake_results)
    result = runner.invoke(main, ["meetings", "polls", "results", "12345"])
    assert result.exit_code == 0, result.output
    import json as _json

    assert _json.loads(result.output) == payload


# ---- meeting livestream (depth-completion follow-up to #13) ------------


def test_meetings_livestream_get_prints_fields(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_get(_client, meeting_id):
        assert meeting_id == "12345"
        return {
            "stream_url": "rtmp://example.com/live",
            "stream_key": "secretkey",
            "page_url": "https://example.com/watch",
        }

    _patch_meetings_module(monkeypatch, get_livestream=fake_get)
    result = runner.invoke(main, ["meetings", "livestream", "get", "12345"])
    assert result.exit_code == 0, result.output
    assert "stream_url: rtmp://example.com/live" in result.output
    assert "stream_key: secretkey" in result.output
    assert "page_url: https://example.com/watch" in result.output


def test_meetings_livestream_update_field_flags_build_payload(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_update(_client, meeting_id, payload):
        captured["meeting_id"] = meeting_id
        captured["payload"] = payload

    _patch_meetings_module(monkeypatch, update_livestream=fake_update)
    result = runner.invoke(
        main,
        [
            "meetings",
            "livestream",
            "update",
            "12345",
            "--stream-url",
            "rtmp://example.com/live",
            "--stream-key",
            "k",
            "--page-url",
            "https://example.com/watch",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["meeting_id"] == "12345"
    assert captured["payload"] == {
        "stream_url": "rtmp://example.com/live",
        "stream_key": "k",
        "page_url": "https://example.com/watch",
    }


def test_meetings_livestream_update_rejects_no_fields(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    _patch_meetings_module(monkeypatch, update_livestream=lambda *_a, **_k: None)
    result = runner.invoke(main, ["meetings", "livestream", "update", "12345"])
    assert result.exit_code == 1
    assert "Nothing to update" in result.output


def test_meetings_livestream_update_from_json_mutually_exclusive(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "ls.json"
    json_file.write_text('{"stream_url": "rtmp://a"}')
    _patch_meetings_module(monkeypatch, update_livestream=lambda *_a, **_k: None)
    result = runner.invoke(
        main,
        [
            "meetings",
            "livestream",
            "update",
            "12345",
            "--from-json",
            str(json_file),
            "--stream-url",
            "rtmp://other",
        ],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_meetings_livestream_start_yes_sends_action_and_settings(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_status(_client, meeting_id, *, action, settings):
        captured["meeting_id"] = meeting_id
        captured["action"] = action
        captured["settings"] = settings

    _patch_meetings_module(monkeypatch, update_livestream_status=fake_status)
    result = runner.invoke(
        main,
        [
            "meetings",
            "livestream",
            "start",
            "12345",
            "--display-name",
            "Webinar Live",
            "--active-speaker-name",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["action"] == "start"
    assert captured["settings"] == {
        "display_name": "Webinar Live",
        "active_speaker_name": True,
    }
    assert "Started livestream" in result.output


def test_meetings_livestream_start_with_no_settings_passes_none(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No settings flags → API helper receives ``settings=None`` so it
    omits the sub-object entirely (Zoom accepts a bare action=start)."""
    _save_creds()
    captured: dict[str, object] = {}

    def fake_status(_client, _mid, *, action, settings):
        captured["action"] = action
        captured["settings"] = settings

    _patch_meetings_module(monkeypatch, update_livestream_status=fake_status)
    result = runner.invoke(main, ["meetings", "livestream", "start", "12345", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["action"] == "start"
    assert captured["settings"] is None


def test_meetings_livestream_start_confirms_and_aborts(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    called = {"n": 0}

    def fake_status(*_a, **_k):
        called["n"] += 1

    _patch_meetings_module(monkeypatch, update_livestream_status=fake_status)
    result = runner.invoke(main, ["meetings", "livestream", "start", "12345"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_meetings_livestream_stop_yes_sends_action_stop(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_status(_client, meeting_id, *, action, settings=None):
        captured["meeting_id"] = meeting_id
        captured["action"] = action
        captured["settings"] = settings

    _patch_meetings_module(monkeypatch, update_livestream_status=fake_status)
    result = runner.invoke(main, ["meetings", "livestream", "stop", "12345", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["action"] == "stop"
    # `stop` doesn't pass settings at all, so the stub default kicks in.
    assert captured["settings"] is None
    assert "Stopped livestream" in result.output


def test_meetings_livestream_stop_confirms_and_aborts(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    called = {"n": 0}

    def fake_status(*_a, **_k):
        called["n"] += 1

    _patch_meetings_module(monkeypatch, update_livestream_status=fake_status)
    result = runner.invoke(main, ["meetings", "livestream", "stop", "12345"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


# ---- past instances + invitation + recover (depth-completion) ----------


def test_meetings_invitation_prints_text(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_inv(_client, meeting_id):
        assert meeting_id == "12345"
        return {"invitation": "Hi! Join my Zoom meeting at https://zoom.us/j/12345"}

    _patch_meetings_module(monkeypatch, get_invitation=fake_inv)
    result = runner.invoke(main, ["meetings", "invitation", "12345"])
    assert result.exit_code == 0, result.output
    assert "Hi! Join my Zoom meeting at https://zoom.us/j/12345" in result.output


def test_meetings_recover_yes_calls_api(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_recover(_client, meeting_id):
        captured["meeting_id"] = meeting_id

    _patch_meetings_module(monkeypatch, recover_meeting=fake_recover)
    result = runner.invoke(main, ["meetings", "recover", "12345", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["meeting_id"] == "12345"
    assert "Recovered meeting 12345" in result.output


def test_meetings_recover_confirms_and_aborts(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    called = {"n": 0}

    def fake_recover(*_a, **_k):
        called["n"] += 1

    _patch_meetings_module(monkeypatch, recover_meeting=fake_recover)
    result = runner.invoke(main, ["meetings", "recover", "12345"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_meetings_past_instances_prints_tsv(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_inst(_client, meeting_id):
        assert meeting_id == "12345"
        return {
            "meetings": [
                {"uuid": "u-1", "start_time": "2026-04-29T15:00:00Z"},
                {"uuid": "u-2", "start_time": "2026-04-30T15:00:00Z"},
            ]
        }

    _patch_meetings_module(monkeypatch, list_past_instances=fake_inst)
    result = runner.invoke(main, ["meetings", "past", "instances", "12345"])
    assert result.exit_code == 0, result.output
    assert "uuid\tstart_time" in result.output
    assert "u-1\t2026-04-29T15:00:00Z" in result.output
    assert "u-2\t2026-04-30T15:00:00Z" in result.output


def test_meetings_past_get_prints_summary(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_get(_client, mid):
        assert mid == "u-1"
        return {
            "uuid": "u-1",
            "id": 12345,
            "topic": "Daily standup",
            "start_time": "2026-04-29T15:00:00Z",
            "duration": 30,
            "user_name": "Alice",
        }

    _patch_meetings_module(monkeypatch, get_past_meeting=fake_get)
    result = runner.invoke(main, ["meetings", "past", "get", "u-1"])
    assert result.exit_code == 0, result.output
    assert "uuid: u-1" in result.output
    assert "topic: Daily standup" in result.output
    assert "duration: 30" in result.output


def test_meetings_past_participants_prints_tsv(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, mid, *, page_size):
        assert mid == "u-1"
        return iter(
            [
                {
                    "id": "p-1",
                    "name": "Alice",
                    "user_email": "a@e.com",
                    "join_time": "T1",
                    "leave_time": "T2",
                },
                {
                    "id": "p-2",
                    "name": "Bob",
                    "user_email": "b@e.com",
                    "join_time": "T3",
                    "leave_time": "T4",
                },
            ]
        )

    _patch_meetings_module(monkeypatch, list_past_participants=fake_list)
    result = runner.invoke(main, ["meetings", "past", "participants", "u-1"])
    assert result.exit_code == 0, result.output
    assert "id\tname\tuser_email\tjoin_time\tleave_time" in result.output
    assert "p-1\tAlice\ta@e.com\tT1\tT2" in result.output
    assert "p-2\tBob\tb@e.com\tT3\tT4" in result.output


# ---- survey + token + batch register + control (depth-completion) ------


def test_meetings_survey_get_prints_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    payload = {"questions": [{"name": "Rating", "type": "single"}]}

    def fake_get(_client, mid):
        assert mid == "12345"
        return payload

    _patch_meetings_module(monkeypatch, get_survey=fake_get)
    result = runner.invoke(main, ["meetings", "survey", "get", "12345"])
    assert result.exit_code == 0, result.output
    import json as _json

    assert _json.loads(result.output) == payload


def test_meetings_survey_update_yes_calls_patch(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "s.json"
    json_file.write_text('{"questions": [{"name": "Rating"}], "show_in_browser": true}')
    captured: dict[str, object] = {}

    def fake_update(_client, mid, payload):
        captured["mid"] = mid
        captured["payload"] = payload

    _patch_meetings_module(monkeypatch, update_survey=fake_update)
    result = runner.invoke(
        main,
        ["meetings", "survey", "update", "12345", "--from-json", str(json_file), "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert captured["mid"] == "12345"
    assert captured["payload"] == {
        "questions": [{"name": "Rating"}],
        "show_in_browser": True,
    }
    assert "Updated survey" in result.output


def test_meetings_survey_update_confirms_and_aborts(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "s.json"
    json_file.write_text("{}")
    called = {"n": 0}
    _patch_meetings_module(
        monkeypatch, update_survey=lambda *_a, **_k: called.__setitem__("n", called["n"] + 1)
    )
    result = runner.invoke(
        main,
        ["meetings", "survey", "update", "12345", "--from-json", str(json_file)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_meetings_survey_delete_yes_calls_api(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_delete(_client, mid):
        captured["mid"] = mid

    _patch_meetings_module(monkeypatch, delete_survey=fake_delete)
    result = runner.invoke(main, ["meetings", "survey", "delete", "12345", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["mid"] == "12345"
    assert "Deleted survey" in result.output


def test_meetings_token_default_zak(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_token(_client, mid, *, token_type):
        captured["mid"] = mid
        captured["type"] = token_type
        return {"token": "abc.def.ghi"}

    _patch_meetings_module(monkeypatch, get_token=fake_token)
    result = runner.invoke(main, ["meetings", "token", "12345"])
    assert result.exit_code == 0, result.output
    assert captured["type"] == "zak"
    assert "abc.def.ghi" in result.output


def test_meetings_token_forwards_type(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_token(_client, _mid, *, token_type):
        captured["type"] = token_type
        return {"token": "x"}

    _patch_meetings_module(monkeypatch, get_token=fake_token)
    result = runner.invoke(main, ["meetings", "token", "12345", "--type", "zpk"])
    assert result.exit_code == 0, result.output
    assert captured["type"] == "zpk"


def test_meetings_registrants_batch_sends_payload(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "batch.json"
    json_file.write_text(
        '{"auto_approve": true, "registrants": ['
        '{"email": "a@e.com", "first_name": "A"}, '
        '{"email": "b@e.com", "first_name": "B"}]}'
    )
    captured: dict[str, object] = {}

    def fake_batch(_client, mid, payload):
        captured["mid"] = mid
        captured["payload"] = payload
        return {
            "registrants": [
                {"email": "a@e.com", "join_url": "https://zoom.us/w/12345?tk=A"},
                {"email": "b@e.com", "join_url": "https://zoom.us/w/12345?tk=B"},
            ]
        }

    _patch_meetings_module(monkeypatch, batch_register=fake_batch)
    result = runner.invoke(
        main,
        [
            "meetings",
            "registrants",
            "batch",
            "12345",
            "--from-json",
            str(json_file),
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["mid"] == "12345"
    assert len(captured["payload"]["registrants"]) == 2  # type: ignore[index]
    assert "Registered 2 attendee(s)" in result.output


def test_meetings_control_yes_sends_payload(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "ctrl.json"
    json_file.write_text('{"method": "invite", "params": {"contacts": [{"email": "a@e.com"}]}}')
    captured: dict[str, object] = {}

    def fake_ctrl(_client, mid, payload):
        captured["mid"] = mid
        captured["payload"] = payload

    _patch_meetings_module(monkeypatch, in_meeting_control=fake_ctrl)
    result = runner.invoke(
        main,
        ["meetings", "control", "12345", "--from-json", str(json_file), "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert captured["mid"] == "12345"
    assert captured["payload"]["method"] == "invite"  # type: ignore[index]
    assert "Sent in-meeting control 'invite'" in result.output


def test_meetings_control_confirms_and_aborts(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "ctrl.json"
    json_file.write_text('{"method": "mute_participants", "params": {}}')
    called = {"n": 0}
    _patch_meetings_module(
        monkeypatch,
        in_meeting_control=lambda *_a, **_k: called.__setitem__("n", called["n"] + 1),
    )
    result = runner.invoke(
        main,
        ["meetings", "control", "12345", "--from-json", str(json_file)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert "mute_participants" in result.output  # confirmation surfaced the verb
    assert called["n"] == 0


# ---- #14 (write): zoom users create / delete / settings get -------------


def _patch_users_module(monkeypatch: pytest.MonkeyPatch, **funcs):
    import zoom_cli.__main__ as main_mod

    for name, fn in funcs.items():
        monkeypatch.setattr(main_mod.users, name, fn)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )


# create


def test_users_create_requires_email_and_type(runner: CliRunner) -> None:
    """--email and --type are required."""
    result = runner.invoke(main, ["users", "create"])
    assert result.exit_code != 0
    result = runner.invoke(main, ["users", "create", "--email", "x@y"])
    assert result.exit_code != 0
    result = runner.invoke(main, ["users", "create", "--type", "1"])
    assert result.exit_code != 0


def test_users_create_builds_user_info_and_prints_result(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_create(_client, user_info, *, action):
        captured["user_info"] = user_info
        captured["action"] = action
        return {
            "id": "new-1",
            "email": user_info["email"],
            "type": user_info["type"],
            "status": "pending",
            "display_name": user_info.get("display_name", ""),
        }

    _patch_users_module(monkeypatch, create_user=fake_create)

    result = runner.invoke(
        main,
        [
            "users",
            "create",
            "--email",
            "alice@example.com",
            "--type",
            "2",
            "--first-name",
            "Alice",
            "--last-name",
            "Example",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["action"] == "create"
    assert captured["user_info"] == {
        "email": "alice@example.com",
        "type": 2,
        "first_name": "Alice",
        "last_name": "Example",
    }
    assert "alice@example.com" in result.output


def test_users_create_forwards_action(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured = {}

    def fake_create(_client, user_info, *, action):
        captured["action"] = action
        return {"id": "x", "email": user_info["email"]}

    _patch_users_module(monkeypatch, create_user=fake_create)
    result = runner.invoke(
        main,
        ["users", "create", "--email", "x@y", "--type", "1", "--action", "autoCreate"],
    )
    assert result.exit_code == 0, result.output
    assert captured["action"] == "autoCreate"


def test_users_create_rejects_invalid_type(runner: CliRunner) -> None:
    """click.IntRange caps at 1..3."""
    _save_creds()
    result = runner.invoke(main, ["users", "create", "--email", "x@y", "--type", "9"])
    assert result.exit_code != 0


# delete


def test_users_delete_dry_run_does_not_call_api(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    called = {"n": 0}

    def fake_delete(*_a, **_k):
        called["n"] += 1

    _patch_users_module(monkeypatch, delete_user=fake_delete)
    result = runner.invoke(main, ["users", "delete", "u-1", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert "disassociate" in result.output  # default action shown
    assert called["n"] == 0


def test_users_delete_dry_run_shows_transfer_block(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    _patch_users_module(monkeypatch, delete_user=lambda *_a, **_k: None)
    result = runner.invoke(
        main,
        [
            "users",
            "delete",
            "u-1",
            "--dry-run",
            "--transfer-email",
            "boss@example.com",
            "--transfer-meetings",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "boss@example.com" in result.output
    assert "meetings=True" in result.output


def test_users_delete_default_action_confirms_disassociate(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --action, prompt phrasing should say 'Disassociate'."""
    _save_creds()
    called = {"n": 0}

    def fake_delete(*_a, **_k):
        called["n"] += 1

    _patch_users_module(monkeypatch, delete_user=fake_delete)
    # Decline.
    result = runner.invoke(main, ["users", "delete", "u-1"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Disassociate" in result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_users_delete_action_delete_uses_louder_prompt(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--action delete should warn 'cannot be undone'."""
    _save_creds()
    _patch_users_module(monkeypatch, delete_user=lambda *_a, **_k: None)
    result = runner.invoke(main, ["users", "delete", "u-1", "--action", "delete"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Permanently delete" in result.output
    assert "cannot be undone" in result.output


def test_users_delete_yes_skips_confirmation(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_delete(
        _client,
        user_id,
        *,
        action,
        transfer_email,
        transfer_meeting,
        transfer_recording,
        transfer_webinar,
    ):
        captured.update(
            {
                "user_id": user_id,
                "action": action,
                "transfer_email": transfer_email,
                "transfer_meeting": transfer_meeting,
            }
        )

    _patch_users_module(monkeypatch, delete_user=fake_delete)
    result = runner.invoke(main, ["users", "delete", "u-1", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "u-1"
    assert captured["action"] == "disassociate"
    assert captured["transfer_email"] is None
    assert captured["transfer_meeting"] is False
    assert "Disassociated user u-1" in result.output


def test_users_delete_action_delete_message(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    _patch_users_module(monkeypatch, delete_user=lambda *_a, **_k: None)
    result = runner.invoke(main, ["users", "delete", "u-1", "--action", "delete", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Deleted user u-1" in result.output


def test_users_delete_forwards_transfer_flags(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_delete(
        _client,
        user_id,
        *,
        action,
        transfer_email,
        transfer_meeting,
        transfer_recording,
        transfer_webinar,
    ):
        captured.update(
            {
                "transfer_email": transfer_email,
                "transfer_meeting": transfer_meeting,
                "transfer_recording": transfer_recording,
                "transfer_webinar": transfer_webinar,
            }
        )

    _patch_users_module(monkeypatch, delete_user=fake_delete)
    result = runner.invoke(
        main,
        [
            "users",
            "delete",
            "u-1",
            "--yes",
            "--transfer-email",
            "boss@example.com",
            "--transfer-meetings",
            "--transfer-recordings",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["transfer_email"] == "boss@example.com"
    assert captured["transfer_meeting"] is True
    assert captured["transfer_recording"] is True
    assert captured["transfer_webinar"] is False


# settings get


def test_users_settings_get_default_me(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured = {}

    def fake_get_settings(_client, user_id):
        captured["user_id"] = user_id
        return {"feature": {"meeting_capacity": 100}, "in_meeting": {"chat": True}}

    _patch_users_module(monkeypatch, get_user_settings=fake_get_settings)
    result = runner.invoke(main, ["users", "settings", "get"])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "me"
    # Output is JSON.
    import json as _json

    parsed = _json.loads(result.output)
    assert parsed == {"feature": {"meeting_capacity": 100}, "in_meeting": {"chat": True}}


def test_users_settings_get_specific_user(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_get_settings(_client, user_id):
        captured["user_id"] = user_id
        return {}

    _patch_users_module(monkeypatch, get_user_settings=fake_get_settings)
    result = runner.invoke(main, ["users", "settings", "get", "u-42"])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "u-42"


# ---- #15: zoom recordings list / get / download / delete ----------------


def _patch_recordings_module(monkeypatch: pytest.MonkeyPatch, **funcs):
    import zoom_cli.__main__ as main_mod

    for name, fn in funcs.items():
        monkeypatch.setattr(main_mod.recordings, name, fn)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )


# list


def test_recordings_list_bails_when_no_credentials(runner: CliRunner) -> None:
    result = runner.invoke(main, ["recordings", "list"])
    assert result.exit_code == 1
    assert "No Server-to-Server" in result.output


def test_recordings_list_prints_tab_separated_with_header(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_list_recordings(_client, *, user_id, from_, to, page_size):
        captured.update({"user_id": user_id, "from_": from_, "to": to, "page_size": page_size})
        return iter(
            [
                {
                    "uuid": "uuid-1",
                    "id": 11,
                    "topic": "M1",
                    "start_time": "2026-04-28T10:00:00Z",
                    "recording_files": [{"id": "f1"}, {"id": "f2"}],
                },
                {
                    "uuid": "uuid-2",
                    "id": 22,
                    "topic": "M2",
                    "start_time": "2026-04-29T11:00:00Z",
                    "recording_files": [],
                },
            ]
        )

    _patch_recordings_module(monkeypatch, list_recordings=fake_list_recordings)

    result = runner.invoke(main, ["recordings", "list"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "uuid\tmeeting_id\ttopic\tstart_time\tfile_count"
    assert lines[1] == "uuid-1\t11\tM1\t2026-04-28T10:00:00Z\t2"
    assert lines[2] == "uuid-2\t22\tM2\t2026-04-29T11:00:00Z\t0"

    assert captured["user_id"] == "me"
    assert captured["from_"] is None
    assert captured["to"] is None
    assert captured["page_size"] == 300


def test_recordings_list_forwards_date_filters(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_list_recordings(_client, *, user_id, from_, to, page_size):
        captured.update({"from_": from_, "to": to})
        return iter([])

    _patch_recordings_module(monkeypatch, list_recordings=fake_list_recordings)
    result = runner.invoke(
        main,
        ["recordings", "list", "--from", "2026-04-01", "--to", "2026-04-30"],
    )
    assert result.exit_code == 0, result.output
    assert captured["from_"] == "2026-04-01"
    assert captured["to"] == "2026-04-30"


# get


def test_recordings_get_prints_json(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()

    def fake_get_recordings(_client, meeting_id):
        return {"id": meeting_id, "recording_files": [{"id": "f1", "file_type": "MP4"}]}

    _patch_recordings_module(monkeypatch, get_recordings=fake_get_recordings)
    result = runner.invoke(main, ["recordings", "get", "12345"])
    assert result.exit_code == 0, result.output
    import json as _json

    parsed = _json.loads(result.output)
    assert parsed["id"] == "12345"
    assert parsed["recording_files"][0]["file_type"] == "MP4"


# download


def test_recordings_download_writes_each_file(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()

    def fake_get(_client, meeting_id):
        return {
            "recording_files": [
                {
                    "id": "f1",
                    "file_type": "MP4",
                    "file_extension": "MP4",
                    "recording_type": "shared_screen_with_speaker_view",
                    "download_url": "https://files.zoom.us/rec/f1",
                },
                {
                    "id": "f2",
                    "file_type": "M4A",
                    "file_extension": "M4A",
                    "recording_type": "audio_only",
                    "download_url": "https://files.zoom.us/rec/f2",
                },
            ]
        }

    written = []

    def fake_stream(self, url, dest):
        # Mirror stream_download: write something and return bytes.
        with open(dest, "wb") as f:
            f.write(b"data-for:" + url.encode())
        written.append((url, dest))
        return 99

    _patch_recordings_module(monkeypatch, get_recordings=fake_get)
    monkeypatch.setattr("zoom_cli.api.client.ApiClient.stream_download", fake_stream)

    out_dir = tmp_path / "downloads"
    result = runner.invoke(main, ["recordings", "download", "12345", "--out-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert len(written) == 2
    # Filename convention: <meeting_id>-<recording_type>.<ext>
    paths = sorted(p for _u, p in written)
    assert paths[0].endswith("12345-audio_only.m4a")
    assert paths[1].endswith("12345-shared_screen_with_speaker_view.mp4")


def test_recordings_download_filter_by_file_type(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()

    def fake_get(_client, _meeting_id):
        return {
            "recording_files": [
                {
                    "id": "f1",
                    "file_type": "MP4",
                    "file_extension": "MP4",
                    "recording_type": "x",
                    "download_url": "https://x",
                },
                {
                    "id": "f2",
                    "file_type": "CHAT",
                    "file_extension": "TXT",
                    "recording_type": "y",
                    "download_url": "https://y",
                },
            ]
        }

    written: list = []

    def fake_stream(self, url, dest):
        with open(dest, "wb") as f:
            f.write(b"x")
        written.append(url)
        return 1

    _patch_recordings_module(monkeypatch, get_recordings=fake_get)
    monkeypatch.setattr("zoom_cli.api.client.ApiClient.stream_download", fake_stream)

    result = runner.invoke(
        main,
        [
            "recordings",
            "download",
            "12345",
            "--out-dir",
            str(tmp_path),
            "--file-type",
            "MP4",
        ],
    )
    assert result.exit_code == 0, result.output
    assert written == ["https://x"]


def test_recordings_download_handles_no_files(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    _patch_recordings_module(monkeypatch, get_recordings=lambda _c, _id: {"recording_files": []})
    result = runner.invoke(main, ["recordings", "download", "12345", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "No recording files" in result.output


# delete


def test_recordings_delete_dry_run_no_api_call(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    called = {"n": 0}

    def fake_delete(*_a, **_k):
        called["n"] += 1

    _patch_recordings_module(monkeypatch, delete_recordings=fake_delete)
    result = runner.invoke(main, ["recordings", "delete", "12345", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert called["n"] == 0


def test_recordings_delete_default_trash_confirm(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    _patch_recordings_module(monkeypatch, delete_recordings=lambda *_a, **_k: None)
    result = runner.invoke(main, ["recordings", "delete", "12345"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Move" in result.output and "trash" in result.output
    assert "Aborted" in result.output


def test_recordings_delete_action_delete_louder_prompt(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    _patch_recordings_module(monkeypatch, delete_recordings=lambda *_a, **_k: None)
    result = runner.invoke(
        main, ["recordings", "delete", "12345", "--action", "delete"], input="n\n"
    )
    assert result.exit_code == 0, result.output
    assert "Permanently delete" in result.output
    assert "cannot be undone" in result.output


def test_recordings_delete_yes_skips_confirmation(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_delete(_client, meeting_id, *, action):
        captured.update({"meeting_id": meeting_id, "action": action})

    _patch_recordings_module(monkeypatch, delete_recordings=fake_delete)
    result = runner.invoke(main, ["recordings", "delete", "12345", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured == {"meeting_id": "12345", "action": "trash"}
    assert "Trashed" in result.output


def test_recordings_delete_single_file_with_file_id(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_delete_file(_client, meeting_id, recording_id, *, action):
        captured.update({"meeting_id": meeting_id, "recording_id": recording_id, "action": action})

    # Patch the single-file delete; the bulk delete should NOT be called.
    bulk_called = {"n": 0}
    _patch_recordings_module(
        monkeypatch,
        delete_recording_file=fake_delete_file,
        delete_recordings=lambda *_a, **_k: bulk_called.__setitem__("n", bulk_called["n"] + 1),
    )

    result = runner.invoke(main, ["recordings", "delete", "12345", "--file-id", "rec-abc", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured == {"meeting_id": "12345", "recording_id": "rec-abc", "action": "trash"}
    assert bulk_called["n"] == 0


# ---- #12: zoom auth login (PKCE) ----------------------------------------


def test_auth_login_requires_client_id(runner: CliRunner) -> None:
    """--client-id has no default — must come from flag or env."""
    result = runner.invoke(main, ["auth", "login"])
    assert result.exit_code != 0
    # Either the env-var path also must be empty, or click reports missing.
    assert "client-id" in result.output.lower() or "missing" in result.output.lower()


def test_auth_login_persists_refresh_token_to_keyring(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stub run_pkce_flow to return tokens directly; assert refresh +
    client_id land in the keyring."""
    from datetime import datetime, timedelta, timezone

    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth
    from zoom_cli.api.user_oauth import UserOAuthTokens

    fake_tokens = UserOAuthTokens(
        access_token="acc-123",
        refresh_token="ref-XYZ",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes=("user:read", "meeting:read"),
    )

    captured = {}

    def fake_flow(client_id, **kwargs):
        captured["client_id"] = client_id
        captured["kwargs"] = kwargs
        return fake_tokens

    monkeypatch.setattr(main_mod.user_oauth, "run_pkce_flow", fake_flow)

    result = runner.invoke(main, ["auth", "login", "--client-id", "MY-CID", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert captured["client_id"] == "MY-CID"
    # Browser was suppressed.
    browser = captured["kwargs"]["browser"]
    assert callable(browser)
    assert browser("https://example.com") is False  # the no-op no-browser

    saved = auth.load_user_oauth_credentials()
    assert saved is not None
    assert saved.refresh_token == "ref-XYZ"
    assert saved.client_id == "MY-CID"

    assert "Logged in" in result.output
    assert "ref-XYZ" not in result.output  # never echo the secret


def test_auth_login_reports_oauth_error_distinctly(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli.api.user_oauth import ZoomUserAuthError

    def fake_flow(*_a, **_kw):
        raise ZoomUserAuthError("Code expired", status_code=400, error_code="invalid_grant")

    monkeypatch.setattr(main_mod.user_oauth, "run_pkce_flow", fake_flow)

    result = runner.invoke(main, ["auth", "login", "--client-id", "MY-CID", "--no-browser"])
    assert result.exit_code == 1
    assert "OAuth failed" in result.output
    assert "Code expired" in result.output


def test_auth_login_reports_timeout_distinctly(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod

    def fake_flow(*_a, **_kw):
        raise TimeoutError("user took too long")

    monkeypatch.setattr(main_mod.user_oauth, "run_pkce_flow", fake_flow)
    result = runner.invoke(main, ["auth", "login", "--client-id", "MY-CID", "--no-browser"])
    assert result.exit_code == 1
    assert "Timed out" in result.output


def test_auth_status_reports_both_surfaces(runner: CliRunner) -> None:
    """Both S2S configured + user OAuth configured."""
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))
    auth.save_user_oauth_credentials(
        auth.UserOAuthCredentials(refresh_token="rt", client_id="cid-X")
    )
    result = runner.invoke(main, ["auth", "status"])
    assert result.exit_code == 0, result.output
    assert "Server-to-Server OAuth: configured" in result.output
    assert "User OAuth (PKCE): configured" in result.output


def test_auth_status_reports_user_oauth_unconfigured_separately(runner: CliRunner) -> None:
    """S2S configured + user OAuth NOT configured → shows the user-side
    'not configured' line so users know how to add it."""
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))
    result = runner.invoke(main, ["auth", "status"])
    assert "Server-to-Server OAuth: configured" in result.output
    assert "User OAuth (PKCE): not configured" in result.output


def test_auth_logout_clears_both_stores(runner: CliRunner) -> None:
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))
    auth.save_user_oauth_credentials(auth.UserOAuthCredentials(refresh_token="rt", client_id="cid"))
    assert auth.has_s2s_credentials() is True
    assert auth.has_user_oauth_credentials() is True

    result = runner.invoke(main, ["auth", "logout"])
    assert result.exit_code == 0, result.output
    assert "Cleared Server-to-Server OAuth" in result.output
    assert "Cleared User OAuth" in result.output

    assert auth.has_s2s_credentials() is False
    assert auth.has_user_oauth_credentials() is False


# ---- #18: zoom phone CLI ------------------------------------------------


def _patch_phone_module(monkeypatch: pytest.MonkeyPatch, **funcs):
    import zoom_cli.__main__ as main_mod

    for name, fn in funcs.items():
        monkeypatch.setattr(main_mod.phone, name, fn)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )


def test_phone_users_list_prints_tab_separated(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, *, page_size):
        return iter(
            [
                {
                    "id": "u1",
                    "email": "alice@example.com",
                    "extension_number": "100",
                    "status": "activate",
                },
                {
                    "id": "u2",
                    "email": "bob@example.com",
                    "extension_number": "101",
                    "status": "deactivate",
                },
            ]
        )

    _patch_phone_module(monkeypatch, list_phone_users=fake_list)
    result = runner.invoke(main, ["phone", "users", "list"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "id\temail\textension_number\tstatus"
    assert lines[1] == "u1\talice@example.com\t100\tactivate"


def test_phone_users_get_prints_json(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()

    def fake_get(_client, user_id):
        return {"id": user_id, "email": "x@y", "extension_number": "200"}

    _patch_phone_module(monkeypatch, get_phone_user=fake_get)
    result = runner.invoke(main, ["phone", "users", "get", "u-X"])
    assert result.exit_code == 0, result.output
    import json as _json

    parsed = _json.loads(result.output)
    assert parsed["id"] == "u-X"


def test_phone_call_logs_list_forwards_filters(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_list(_client, *, user_id, from_, to, page_size):
        captured.update({"user_id": user_id, "from_": from_, "to": to})
        return iter([])

    _patch_phone_module(monkeypatch, list_call_logs=fake_list)
    result = runner.invoke(
        main,
        [
            "phone",
            "call-logs",
            "list",
            "--user-id",
            "u-X",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured == {"user_id": "u-X", "from_": "2026-04-01", "to": "2026-04-30"}


def test_phone_queues_list_prints_tab_separated(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, *, page_size):
        return iter(
            [
                {"id": "q1", "name": "Sales", "extension_number": "200", "site": {"name": "HQ"}},
            ]
        )

    _patch_phone_module(monkeypatch, list_call_queues=fake_list)
    result = runner.invoke(main, ["phone", "queues", "list"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "id\tname\textension_number\tsite_name"
    assert lines[1] == "q1\tSales\t200\tHQ"


def test_phone_recordings_list_forwards_filters(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_list(_client, *, user_id, from_, to, page_size):
        captured.update({"user_id": user_id, "from_": from_, "to": to})
        return iter([])

    _patch_phone_module(monkeypatch, list_phone_recordings=fake_list)
    result = runner.invoke(
        main,
        [
            "phone",
            "recordings",
            "list",
            "--user-id",
            "u-X",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured == {"user_id": "u-X", "from_": "2026-04-01", "to": "2026-04-30"}


# ---- #19: zoom chat CLI -------------------------------------------------


def _patch_chat_module(monkeypatch: pytest.MonkeyPatch, **funcs):
    import zoom_cli.__main__ as main_mod

    for name, fn in funcs.items():
        monkeypatch.setattr(main_mod.chat, name, fn)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )


def test_chat_channels_list_prints_tab_separated(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, *, user_id, page_size):
        return iter(
            [
                {"id": "c1", "name": "general", "type": 2},
                {"id": "c2", "name": "engineering", "type": 1},
            ]
        )

    _patch_chat_module(monkeypatch, list_channels=fake_list)

    result = runner.invoke(main, ["chat", "channels", "list"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "id\tname\ttype"
    assert lines[1] == "c1\tgeneral\t2"
    assert lines[2] == "c2\tengineering\t1"


def test_chat_channels_list_forwards_user_id(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_list(_client, *, user_id, page_size):
        captured["user_id"] = user_id
        return iter([])

    _patch_chat_module(monkeypatch, list_channels=fake_list)
    result = runner.invoke(main, ["chat", "channels", "list", "--user-id", "alice@example.com"])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "alice@example.com"


def test_chat_messages_send_to_channel(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured = {}

    def fake_send(_client, *, message, to_channel, to_contact, user_id, reply_main_message_id):
        captured.update(
            {
                "message": message,
                "to_channel": to_channel,
                "to_contact": to_contact,
                "user_id": user_id,
                "reply_main_message_id": reply_main_message_id,
            }
        )
        return {"id": "msg-NEW"}

    _patch_chat_module(monkeypatch, send_message=fake_send)
    result = runner.invoke(
        main,
        ["chat", "messages", "send", "--message", "hello world", "--to-channel", "ch-1"],
    )
    assert result.exit_code == 0, result.output
    assert captured["message"] == "hello world"
    assert captured["to_channel"] == "ch-1"
    assert captured["to_contact"] is None
    assert captured["reply_main_message_id"] is None
    assert "msg-NEW" in result.output


def test_chat_messages_send_to_contact(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured = {}

    def fake_send(_client, *, message, to_channel, to_contact, user_id, reply_main_message_id):
        captured["to_contact"] = to_contact
        return {"id": "msg-2"}

    _patch_chat_module(monkeypatch, send_message=fake_send)
    result = runner.invoke(
        main,
        ["chat", "messages", "send", "--message", "x", "--to-contact", "bob@example.com"],
    )
    assert result.exit_code == 0, result.output
    assert captured["to_contact"] == "bob@example.com"


def test_chat_messages_send_rejects_both_targets(runner: CliRunner) -> None:
    _save_creds()
    result = runner.invoke(
        main,
        [
            "chat",
            "messages",
            "send",
            "--message",
            "x",
            "--to-channel",
            "ch-1",
            "--to-contact",
            "bob@example.com",
        ],
    )
    assert result.exit_code == 1
    assert "Pass exactly one" in result.output


def test_chat_messages_send_rejects_neither_target(runner: CliRunner) -> None:
    _save_creds()
    result = runner.invoke(main, ["chat", "messages", "send", "--message", "x"])
    assert result.exit_code == 1
    assert "Pass exactly one" in result.output


def test_chat_messages_send_forwards_reply_id(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_send(_client, *, message, to_channel, to_contact, user_id, reply_main_message_id):
        captured["reply_main_message_id"] = reply_main_message_id
        return {"id": "reply-1"}

    _patch_chat_module(monkeypatch, send_message=fake_send)
    result = runner.invoke(
        main,
        [
            "chat",
            "messages",
            "send",
            "--message",
            "x",
            "--to-channel",
            "ch-1",
            "--reply-to",
            "PARENT-MSG-ID",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["reply_main_message_id"] == "PARENT-MSG-ID"


# ---- #20: zoom reports CLI ---------------------------------------------


def _patch_reports_module(monkeypatch: pytest.MonkeyPatch, **funcs):
    import zoom_cli.__main__ as main_mod

    for name, fn in funcs.items():
        monkeypatch.setattr(main_mod.reports, name, fn)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )


def test_reports_daily_prints_json(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured = {}

    def fake_get(_client, *, year, month):
        captured.update({"year": year, "month": month})
        return {"year": "2026", "month": "04", "dates": []}

    _patch_reports_module(monkeypatch, get_daily=fake_get)
    result = runner.invoke(main, ["reports", "daily", "--year", "2026", "--month", "4"])
    assert result.exit_code == 0, result.output
    assert captured == {"year": 2026, "month": 4}
    import json as _json

    parsed = _json.loads(result.output)
    assert parsed["year"] == "2026"


def test_reports_daily_default_omits_year_month(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_get(_client, *, year, month):
        captured.update({"year": year, "month": month})
        return {}

    _patch_reports_module(monkeypatch, get_daily=fake_get)
    result = runner.invoke(main, ["reports", "daily"])
    assert result.exit_code == 0, result.output
    assert captured == {"year": None, "month": None}


def test_reports_meetings_list_requires_dates(runner: CliRunner) -> None:
    _save_creds()
    result = runner.invoke(main, ["reports", "meetings", "list"])
    assert result.exit_code != 0
    assert "from" in result.output.lower() or "missing" in result.output.lower()


def test_reports_meetings_list_prints_tab_separated(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, *, user_id, from_, to, meeting_type, page_size):
        return iter(
            [
                {
                    "uuid": "u-1",
                    "id": 11,
                    "topic": "Standup",
                    "user_email": "alice@example.com",
                    "start_time": "2026-04-28T10:00:00Z",
                    "duration": 30,
                    "participants_count": 5,
                },
            ]
        )

    _patch_reports_module(monkeypatch, list_meetings_report=fake_list)
    result = runner.invoke(
        main,
        [
            "reports",
            "meetings",
            "list",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
        ],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "uuid\tid\ttopic\tuser_email\tstart_time\tduration\tparticipants_count"
    assert lines[1] == "u-1\t11\tStandup\talice@example.com\t2026-04-28T10:00:00Z\t30\t5"


def test_reports_meetings_list_forwards_filters(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_list(_client, *, user_id, from_, to, meeting_type, page_size):
        captured.update(
            {"user_id": user_id, "from_": from_, "to": to, "meeting_type": meeting_type}
        )
        return iter([])

    _patch_reports_module(monkeypatch, list_meetings_report=fake_list)
    result = runner.invoke(
        main,
        [
            "reports",
            "meetings",
            "list",
            "--user-id",
            "u-X",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
            "--type",
            "past",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured == {
        "user_id": "u-X",
        "from_": "2026-04-01",
        "to": "2026-04-30",
        "meeting_type": "past",
    }


def test_reports_meetings_list_rejects_invalid_type(runner: CliRunner) -> None:
    _save_creds()
    result = runner.invoke(
        main,
        [
            "reports",
            "meetings",
            "list",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
            "--type",
            "garbage",
        ],
    )
    assert result.exit_code != 0


def test_reports_meetings_participants_prints_tab_separated(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, meeting_id, *, page_size):
        return iter(
            [
                {
                    "id": "p-1",
                    "name": "Alice",
                    "user_email": "alice@example.com",
                    "join_time": "2026-04-28T10:00:00Z",
                    "leave_time": "2026-04-28T10:30:00Z",
                    "duration": 1800,
                },
            ]
        )

    _patch_reports_module(monkeypatch, list_meeting_participants=fake_list)
    result = runner.invoke(main, ["reports", "meetings", "participants", "12345"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "id\tname\tuser_email\tjoin_time\tleave_time\tduration"
    assert lines[1] == (
        "p-1\tAlice\talice@example.com\t2026-04-28T10:00:00Z\t2026-04-28T10:30:00Z\t1800"
    )


def test_reports_operationlogs_list_forwards_filters(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_list(_client, *, from_, to, category_type, page_size):
        captured.update({"from_": from_, "to": to, "category_type": category_type})
        return iter([])

    _patch_reports_module(monkeypatch, list_operation_logs=fake_list)
    result = runner.invoke(
        main,
        [
            "reports",
            "operationlogs",
            "list",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
            "--category-type",
            "user",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured == {
        "from_": "2026-04-01",
        "to": "2026-04-30",
        "category_type": "user",
    }


# ---- #21: zoom dashboard CLI -------------------------------------------


def _patch_dashboard_module(monkeypatch: pytest.MonkeyPatch, **funcs):
    import zoom_cli.__main__ as main_mod

    for name, fn in funcs.items():
        monkeypatch.setattr(main_mod.dashboard, name, fn)
    monkeypatch.setattr(
        main_mod.oauth, "fetch_access_token", lambda *_a, **_k: _fake_access_token()
    )


def test_dashboard_meetings_list_requires_dates(runner: CliRunner) -> None:
    _save_creds()
    result = runner.invoke(main, ["dashboard", "meetings", "list"])
    assert result.exit_code != 0


def test_dashboard_meetings_list_prints_tab_separated(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, *, type, from_, to, page_size):
        return iter(
            [
                {
                    "uuid": "u-1",
                    "id": 11,
                    "topic": "T",
                    "host": "alice@example.com",
                    "participants": 5,
                    "duration": 30,
                    "start_time": "2026-04-28T10:00:00Z",
                },
            ]
        )

    _patch_dashboard_module(monkeypatch, list_meetings=fake_list)
    result = runner.invoke(
        main,
        [
            "dashboard",
            "meetings",
            "list",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
        ],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "uuid\tid\ttopic\thost\tparticipants\tduration\tstart_time"
    assert lines[1] == "u-1\t11\tT\talice@example.com\t5\t30\t2026-04-28T10:00:00Z"


def test_dashboard_meetings_list_forwards_type(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    captured = {}

    def fake_list(_client, *, type, from_, to, page_size):
        captured["type"] = type
        return iter([])

    _patch_dashboard_module(monkeypatch, list_meetings=fake_list)
    result = runner.invoke(
        main,
        [
            "dashboard",
            "meetings",
            "list",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
            "--type",
            "live",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["type"] == "live"


def test_dashboard_meetings_list_rejects_invalid_type(runner: CliRunner) -> None:
    _save_creds()
    result = runner.invoke(
        main,
        [
            "dashboard",
            "meetings",
            "list",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
            "--type",
            "garbage",
        ],
    )
    assert result.exit_code != 0


def test_dashboard_meetings_get_prints_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_get(_client, meeting_id):
        return {"id": meeting_id, "topic": "M", "duration": 45}

    _patch_dashboard_module(monkeypatch, get_meeting=fake_get)
    result = runner.invoke(main, ["dashboard", "meetings", "get", "12345"])
    assert result.exit_code == 0, result.output
    import json as _json

    parsed = _json.loads(result.output)
    assert parsed["id"] == "12345"


def test_dashboard_meetings_participants_prints_tab_separated(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, meeting_id, *, type, page_size):
        return iter(
            [
                {
                    "id": "p-1",
                    "user_id": "u-1",
                    "user_name": "Alice",
                    "join_time": "2026-04-28T10:00:00Z",
                    "leave_time": "2026-04-28T10:30:00Z",
                    "duration": 1800,
                },
            ]
        )

    _patch_dashboard_module(monkeypatch, list_meeting_participants=fake_list)
    result = runner.invoke(main, ["dashboard", "meetings", "participants", "12345"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "id\tuser_id\tuser_name\tjoin_time\tleave_time\tduration"
    assert lines[1] == ("p-1\tu-1\tAlice\t2026-04-28T10:00:00Z\t2026-04-28T10:30:00Z\t1800")


def test_dashboard_zoomrooms_list_prints_tab_separated(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_list(_client, *, page_size):
        return iter(
            [
                {
                    "id": "r-1",
                    "room_name": "Conference A",
                    "status": "Available",
                    "device_ip": "192.168.1.10",
                    "last_start_time": "2026-04-28T08:00:00Z",
                },
            ]
        )

    _patch_dashboard_module(monkeypatch, list_zoomrooms=fake_list)
    result = runner.invoke(main, ["dashboard", "zoomrooms", "list"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[0] == "id\troom_name\tstatus\tdevice_ip\tlast_start_time"
    assert lines[1] == ("r-1\tConference A\tAvailable\t192.168.1.10\t2026-04-28T08:00:00Z")


def test_dashboard_zoomrooms_get_prints_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_get(_client, room_id):
        return {"id": room_id, "room_name": "Conference A", "status": "Available"}

    _patch_dashboard_module(monkeypatch, get_zoomroom=fake_get)
    result = runner.invoke(main, ["dashboard", "zoomrooms", "get", "r-1"])
    assert result.exit_code == 0, result.output
    import json as _json

    parsed = _json.loads(result.output)
    assert parsed["id"] == "r-1"


# ---- _load_creds_or_exit + _build_api_client (user-OAuth integration) ---


def test_load_creds_prefers_user_oauth_when_both_configured(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When both auth surfaces are configured, user-OAuth wins. This is
    the developer-friendly default — `zoom auth login` is the personal
    flow, S2S is the org flow."""
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))
    auth.save_user_oauth_credentials(
        auth.UserOAuthCredentials(refresh_token="user-rt", client_id="user-cid")
    )

    captured = {"creds_type": None}

    # `zoom users me` is the simplest path that exercises _load_creds_or_exit.
    def fake_get_me(_client):
        return {"id": "u-1", "email": "x@y", "display_name": "X"}

    def fake_build(creds):
        captured["creds_type"] = type(creds).__name__
        # Return a fake client context manager — the test only cares which
        # creds were chosen.
        from contextlib import nullcontext

        return nullcontext(enter_result=object())

    monkeypatch.setattr(main_mod.users, "get_me", fake_get_me)
    monkeypatch.setattr(main_mod, "_build_api_client", fake_build)

    result = runner.invoke(main, ["users", "me"])
    assert result.exit_code == 0, result.output
    assert captured["creds_type"] == "UserOAuthCredentials"


def test_load_creds_falls_back_to_s2s_when_only_s2s_configured(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    auth.save_s2s_credentials(auth.S2SCredentials(account_id="a", client_id="b", client_secret="c"))

    captured = {"creds_type": None}

    def fake_get_me(_client):
        return {"id": "u-1", "email": "x@y"}

    def fake_build(creds):
        captured["creds_type"] = type(creds).__name__
        from contextlib import nullcontext

        return nullcontext(enter_result=object())

    monkeypatch.setattr(main_mod.users, "get_me", fake_get_me)
    monkeypatch.setattr(main_mod, "_build_api_client", fake_build)

    result = runner.invoke(main, ["users", "me"])
    assert result.exit_code == 0, result.output
    assert captured["creds_type"] == "S2SCredentials"


def test_load_creds_friendly_message_when_neither_configured(runner: CliRunner) -> None:
    """No auth configured at all → mention BOTH setup paths."""
    result = runner.invoke(main, ["users", "me"])
    assert result.exit_code == 1
    assert "zoom auth s2s set" in result.output
    assert "zoom auth login" in result.output


def test_build_api_client_wires_rotation_callback_for_user_oauth() -> None:
    """_build_api_client should pass on_user_token_rotated for user-OAuth
    creds so rotated refresh tokens get persisted."""
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    user_creds = auth.UserOAuthCredentials(refresh_token="rt", client_id="cid")
    client = main_mod._build_api_client(user_creds)
    try:
        # The callback should be auth.save_user_oauth_credentials.
        assert client._on_user_token_rotated is auth.save_user_oauth_credentials
    finally:
        client.close()


def test_build_api_client_no_callback_for_s2s() -> None:
    """S2S doesn't have rotation; on_user_token_rotated should stay None."""
    import zoom_cli.__main__ as main_mod
    from zoom_cli import auth

    s2s = auth.S2SCredentials(account_id="a", client_id="b", client_secret="c")
    client = main_mod._build_api_client(s2s)
    try:
        assert client._on_user_token_rotated is None
    finally:
        client.close()


# ---- phone recordings download (#18 follow-up) -------------------------


def test_phone_recordings_download_writes_file(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Streams the recording to disk via stream_download. Filename
    convention: <recording_id>.<file_extension>."""
    _save_creds()

    def fake_get(_client, recording_id):
        return {
            "id": recording_id,
            "download_url": "https://files.zoom.us/rec/abc",
            "file_extension": "MP3",
            "duration": 120,
        }

    written: list = []

    def fake_stream(self, url, dest):
        with open(dest, "wb") as f:
            f.write(b"fake audio")
        written.append((url, dest))
        return 10

    _patch_phone_module(monkeypatch, get_phone_recording=fake_get)
    monkeypatch.setattr("zoom_cli.api.client.ApiClient.stream_download", fake_stream)

    out_dir = tmp_path / "downloads"
    result = runner.invoke(
        main, ["phone", "recordings", "download", "rec-1", "--out-dir", str(out_dir)]
    )
    assert result.exit_code == 0, result.output
    assert len(written) == 1
    url, dest = written[0]
    assert url == "https://files.zoom.us/rec/abc"
    assert dest.endswith("rec-1.mp3")
    assert "Downloaded" in result.output


def test_phone_recordings_download_errors_on_missing_url(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Recording without download_url (deleted / trashed) → exit 1 with
    a clear message; nothing written to disk."""
    _save_creds()

    def fake_get(_client, recording_id):
        # No download_url field — recording is trashed.
        return {"id": recording_id, "file_extension": "MP3"}

    _patch_phone_module(monkeypatch, get_phone_recording=fake_get)

    result = runner.invoke(
        main, ["phone", "recordings", "download", "rec-1", "--out-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "No download_url" in result.output
    # Nothing written.
    assert list(tmp_path.iterdir()) == []


def test_phone_recordings_download_defaults_extension_when_missing(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()

    def fake_get(_client, recording_id):
        # Some recordings don't include file_extension; default to mp3.
        return {"id": recording_id, "download_url": "https://x"}

    written: list = []

    def fake_stream(self, _url, dest):
        with open(dest, "wb") as f:
            f.write(b"x")
        written.append(dest)
        return 1

    _patch_phone_module(monkeypatch, get_phone_recording=fake_get)
    monkeypatch.setattr("zoom_cli.api.client.ApiClient.stream_download", fake_stream)

    result = runner.invoke(
        main, ["phone", "recordings", "download", "rec-X", "--out-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert written[0].endswith("rec-X.mp3")


# ---- users settings update --from-json -----------------------------------


def test_users_settings_update_requires_from_json(runner: CliRunner) -> None:
    _save_creds()
    result = runner.invoke(main, ["users", "settings", "update", "u-1"])
    assert result.exit_code != 0
    assert "from-json" in result.output.lower() or "missing" in result.output.lower()


def test_users_settings_update_dry_run_prints_payload_no_api(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "settings.json"
    json_file.write_text('{"in_meeting": {"chat": false}}')

    called = {"n": 0}

    def fake_update(*_a, **_k):
        called["n"] += 1

    _patch_users_module(monkeypatch, update_user_settings=fake_update)
    result = runner.invoke(
        main,
        [
            "users",
            "settings",
            "update",
            "u-1",
            "--from-json",
            str(json_file),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert "in_meeting" in result.output
    assert called["n"] == 0


def test_users_settings_update_yes_skips_confirmation(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "settings.json"
    json_file.write_text('{"in_meeting": {"chat": false}}')

    captured = {}

    def fake_update(_client, user_id, payload):
        captured.update({"user_id": user_id, "payload": payload})

    _patch_users_module(monkeypatch, update_user_settings=fake_update)
    result = runner.invoke(
        main,
        [
            "users",
            "settings",
            "update",
            "u-1",
            "--from-json",
            str(json_file),
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "u-1"
    assert captured["payload"] == {"in_meeting": {"chat": False}}
    assert "Updated settings for user u-1" in result.output


def test_users_settings_update_confirms_and_aborts(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Without --yes, an explicit 'n' aborts and the API is not called."""
    _save_creds()
    json_file = tmp_path / "settings.json"
    json_file.write_text('{"feature": {"meeting_capacity": 100}}')

    called = {"n": 0}

    def fake_update(*_a, **_k):
        called["n"] += 1

    _patch_users_module(monkeypatch, update_user_settings=fake_update)
    result = runner.invoke(
        main,
        ["users", "settings", "update", "u-1", "--from-json", str(json_file)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert "feature" in result.output  # confirmation surfaced top-level key
    assert called["n"] == 0


def test_users_settings_update_rejects_invalid_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _save_creds()
    json_file = tmp_path / "settings.json"
    json_file.write_text("not valid json {{{")

    _patch_users_module(monkeypatch, update_user_settings=lambda *_a, **_k: None)
    result = runner.invoke(
        main,
        [
            "users",
            "settings",
            "update",
            "u-1",
            "--from-json",
            str(json_file),
            "--yes",
        ],
    )
    assert result.exit_code == 1
    assert "Invalid JSON" in result.output


def test_users_settings_update_rejects_non_dict_payload(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """--from-json must contain a JSON object; arrays / scalars are
    rejected (Zoom's PATCH expects a dict)."""
    _save_creds()
    json_file = tmp_path / "settings.json"
    json_file.write_text('["not", "a", "dict"]')

    _patch_users_module(monkeypatch, update_user_settings=lambda *_a, **_k: None)
    result = runner.invoke(
        main,
        [
            "users",
            "settings",
            "update",
            "u-1",
            "--from-json",
            str(json_file),
            "--yes",
        ],
    )
    assert result.exit_code == 1
    assert "must be a JSON object" in result.output


def test_users_settings_update_default_user_me(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Positional user_id defaults to 'me'."""
    _save_creds()
    json_file = tmp_path / "settings.json"
    json_file.write_text('{"feature": {}}')

    captured = {}

    def fake_update(_client, user_id, payload):
        captured["user_id"] = user_id

    _patch_users_module(monkeypatch, update_user_settings=fake_update)
    result = runner.invoke(
        main, ["users", "settings", "update", "--from-json", str(json_file), "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "me"


# ---- users depth-completion: status / password / email / token / perms --


@pytest.mark.parametrize(
    "subcmd,expected_action,past",
    [
        ("activate", "activate", "Activated"),
        ("deactivate", "deactivate", "Deactivated"),
    ],
)
def test_users_status_actions_send_correct_action(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    subcmd: str,
    expected_action: str,
    past: str,
) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_status(_client, user_id, *, action):
        captured["user_id"] = user_id
        captured["action"] = action

    _patch_users_module(monkeypatch, update_user_status=fake_status)
    result = runner.invoke(main, ["users", subcmd, "u-1", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "u-1"
    assert captured["action"] == expected_action
    assert past in result.output


def test_users_activate_confirms_and_aborts(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()
    called = {"n": 0}

    def fake_status(*_a, **_k):
        called["n"] += 1

    _patch_users_module(monkeypatch, update_user_status=fake_status)
    result = runner.invoke(main, ["users", "activate", "u-1"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_users_password_prompts_via_getpass(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Password is read via getpass.getpass — never via argv. We patch
    getpass to return a known value and confirm the helper sees it."""
    import getpass

    _save_creds()
    captured: dict[str, object] = {}
    pw_responses = iter(["hunter2hunter2", "hunter2hunter2"])

    def fake_getpass(_prompt):
        return next(pw_responses)

    monkeypatch.setattr(getpass, "getpass", fake_getpass)

    def fake_password(_client, user_id, *, new_password):
        captured["user_id"] = user_id
        captured["new_password"] = new_password

    _patch_users_module(monkeypatch, update_user_password=fake_password)
    result = runner.invoke(main, ["users", "password", "u-1", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "u-1"
    assert captured["new_password"] == "hunter2hunter2"
    assert "Reset password for user u-1" in result.output


def test_users_password_rejects_mismatched_confirmation(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the confirm-prompt doesn't match the first prompt, abort
    without calling the API."""
    import getpass

    _save_creds()
    pw_responses = iter(["one", "two"])
    monkeypatch.setattr(getpass, "getpass", lambda _p: next(pw_responses))

    called = {"n": 0}
    _patch_users_module(
        monkeypatch,
        update_user_password=lambda *_a, **_k: called.__setitem__("n", called["n"] + 1),
    )
    result = runner.invoke(main, ["users", "password", "u-1", "--yes"])
    assert result.exit_code == 1
    assert "do not match" in result.output
    assert called["n"] == 0


def test_users_password_rejects_empty(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    import getpass

    _save_creds()
    monkeypatch.setattr(getpass, "getpass", lambda _p: "")
    called = {"n": 0}
    _patch_users_module(
        monkeypatch,
        update_user_password=lambda *_a, **_k: called.__setitem__("n", called["n"] + 1),
    )
    result = runner.invoke(main, ["users", "password", "u-1", "--yes"])
    assert result.exit_code == 1
    assert "Empty password" in result.output
    assert called["n"] == 0


def test_users_email_yes_calls_api(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_email(_client, user_id, *, new_email):
        captured["user_id"] = user_id
        captured["new_email"] = new_email

    _patch_users_module(monkeypatch, update_user_email=fake_email)
    result = runner.invoke(main, ["users", "email", "u-1", "new@example.com", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured["user_id"] == "u-1"
    assert captured["new_email"] == "new@example.com"
    assert "Email change initiated" in result.output


def test_users_email_confirms_and_surfaces_target_address(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirmation message must surface the target email so the user
    sees what's about to be changed."""
    _save_creds()
    called = {"n": 0}
    _patch_users_module(
        monkeypatch,
        update_user_email=lambda *_a, **_k: called.__setitem__("n", called["n"] + 1),
    )
    result = runner.invoke(main, ["users", "email", "u-1", "new@example.com"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "new@example.com" in result.output
    assert "Aborted" in result.output
    assert called["n"] == 0


def test_users_token_default_zak(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_token(_client, user_id, *, token_type):
        captured["user_id"] = user_id
        captured["token_type"] = token_type
        return {"token": "abc.def.ghi"}

    _patch_users_module(monkeypatch, get_user_token=fake_token)
    result = runner.invoke(main, ["users", "token", "u-1"])
    assert result.exit_code == 0, result.output
    assert captured["token_type"] == "zak"
    assert "abc.def.ghi" in result.output


def test_users_token_forwards_type(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_creds()
    captured: dict[str, object] = {}

    def fake_token(_client, _uid, *, token_type):
        captured["type"] = token_type
        return {"token": "x"}

    _patch_users_module(monkeypatch, get_user_token=fake_token)
    result = runner.invoke(main, ["users", "token", "u-1", "--type", "token"])
    assert result.exit_code == 0, result.output
    assert captured["type"] == "token"


def test_users_permissions_prints_one_per_line(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_creds()

    def fake_perm(_client, user_id):
        assert user_id == "u-1"
        return {"permissions": ["AccountSettingPermission", "MeetingPermission"]}

    _patch_users_module(monkeypatch, get_user_permissions=fake_perm)
    result = runner.invoke(main, ["users", "permissions", "u-1"])
    assert result.exit_code == 0, result.output
    assert "AccountSettingPermission" in result.output
    assert "MeetingPermission" in result.output
