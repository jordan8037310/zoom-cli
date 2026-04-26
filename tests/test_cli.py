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


def test_auth_s2s_set_with_flags_persists_to_keyring(runner: CliRunner) -> None:
    from zoom_cli import auth

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
            "csecret-3",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "saved" in result.output.lower()

    loaded = auth.load_s2s_credentials()
    assert loaded is not None
    assert loaded.account_id == "acc-1"
    assert loaded.client_id == "cid-2"
    assert loaded.client_secret == "csecret-3"


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
        [
            "auth",
            "s2s",
            "set",
            "--account-id",
            "a",
            "--client-id",
            "b",
            "--client-secret",
            secret,
        ],
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
