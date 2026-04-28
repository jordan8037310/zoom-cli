"""Tests for zoom_cli.commands — pure command implementations."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from zoom_cli import commands as commands_mod


def test_save_url_persists_payload(tmp_zoom_cli_home: Path) -> None:
    commands_mod._save_url("standup", "https://zoom.us/j/1", "")
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"standup": {"url": "https://zoom.us/j/1"}}


def test_save_url_includes_password_when_provided(tmp_zoom_cli_home: Path) -> None:
    """Password goes to the OS keyring, not into meetings.json."""
    from zoom_cli import secrets

    commands_mod._save_url("standup", "https://zoom.us/j/1", "p@ss")

    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"standup": {"url": "https://zoom.us/j/1"}}
    assert secrets.get_password("standup") == "p@ss"


def test_save_id_password_persists_payload(tmp_zoom_cli_home: Path) -> None:
    from zoom_cli import secrets

    commands_mod._save_id_password("standup", "1234567890", "secret")

    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"standup": {"id": "1234567890"}}
    assert secrets.get_password("standup") == "secret"


def test_save_id_password_omits_password_when_empty(tmp_zoom_cli_home: Path) -> None:
    commands_mod._save_id_password("standup", "1234567890", "")
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"standup": {"id": "1234567890"}}


def test_remove_deletes_entry(write_meetings, tmp_zoom_cli_home: Path) -> None:
    write_meetings({"a": {"id": "1"}, "b": {"id": "2"}})
    commands_mod._remove("a")
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"b": {"id": "2"}}


def test_remove_raises_for_unknown(tmp_zoom_cli_home: Path) -> None:
    with pytest.raises(KeyError):
        commands_mod._remove("missing")


def test_ls_prints_each_meeting(write_meetings, capsys: pytest.CaptureFixture[str]) -> None:
    write_meetings({"daily": {"url": "https://zoom.us/j/1", "password": "p"}})
    commands_mod._ls()
    captured = capsys.readouterr().out
    assert "daily" in captured
    assert "url:" in captured
    assert "https://zoom.us/j/1" in captured
    assert "password:" in captured


def test_ls_prints_separator_between_meetings(
    write_meetings, capsys: pytest.CaptureFixture[str]
) -> None:
    write_meetings({"a": {"id": "1"}, "b": {"id": "2"}})
    commands_mod._ls()
    captured = capsys.readouterr().out
    assert captured.count("\n\n") >= 1


def test_launch_url_strips_scheme_and_calls_launcher(
    captured_launches: list[list[str]],
) -> None:
    commands_mod._launch_url("https://zoom.us/j/123")
    assert captured_launches == [["open", "zoommtg://zoom.us/j/123"]]


def test_launch_url_handles_url_without_scheme(captured_launches: list[list[str]]) -> None:
    commands_mod._launch_url("zoom.us/j/456")
    assert captured_launches == [["open", "zoommtg://zoom.us/j/456"]]


def test_launch_url_does_not_swallow_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #6 — bare ``except Exception`` previously hid bugs.

    Genuine bugs in the launcher must propagate; only the launcher's
    own ``LauncherUnavailableError`` is treated as a recoverable user error.
    """

    def boom(*_args, **_kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(commands_mod, "launch_zoommtg_url", boom)

    with pytest.raises(RuntimeError, match="unexpected"):
        commands_mod._launch_url("https://zoom.us/j/1")


def test_launch_url_reports_launcher_unavailable_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from zoom_cli import utils as utils_mod

    def boom(*_args, **_kwargs):
        raise utils_mod.LauncherUnavailableError("no launcher")

    monkeypatch.setattr(commands_mod, "launch_zoommtg_url", boom)

    commands_mod._launch_url("https://zoom.us/j/1")
    out = capsys.readouterr().out
    assert "Error:" in out
    assert "no launcher" in out


def test_launch_name_uses_saved_url(write_meetings, captured_launches: list[list[str]]) -> None:
    write_meetings({"team": {"url": "https://zoom.us/j/123?pwd=abc"}})
    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123&pwd=abc"]]


def test_launch_name_uses_explicit_password_field(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    write_meetings({"team": {"url": "https://zoom.us/j/123", "password": "xyz"}})
    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123&pwd=xyz"]]


def test_launch_name_falls_back_to_id(write_meetings, captured_launches: list[list[str]]) -> None:
    write_meetings({"team": {"id": "987", "password": "p"}})
    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=987&pwd=p"]]


def test_launch_name_unknown_meeting_prints_error(
    write_meetings, capsys: pytest.CaptureFixture[str], captured_launches: list[list[str]]
) -> None:
    write_meetings({})
    commands_mod._launch_name("ghost")
    assert captured_launches == []
    assert "Could not find meeting" in capsys.readouterr().out


def test_launch_name_meeting_without_url_or_id(
    write_meetings, capsys: pytest.CaptureFixture[str], captured_launches: list[list[str]]
) -> None:
    write_meetings({"empty": {}})
    commands_mod._launch_name("empty")
    assert captured_launches == []
    assert "No url or id found" in capsys.readouterr().out


# ---- _launch_name URL-parsing edge cases (issue #6) ----------------------


def test_launch_name_personal_link_falls_back_to_url_launch(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """Regression for #6: ``/s/personal-name`` URLs previously crashed
    because slice-based parsing called ``url.index('/j/')``. Now they fall
    back to launching the URL through the zoommtg scheme."""
    write_meetings({"personal": {"url": "https://zoom.us/s/my-personal-link"}})
    commands_mod._launch_name("personal")
    assert captured_launches == [["open", "zoommtg://zoom.us/s/my-personal-link"]]


def test_launch_name_web_client_url_falls_back(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    write_meetings({"webclient": {"url": "https://zoom.us/wc/123/join?pwd=abc"}})
    commands_mod._launch_name("webclient")
    assert captured_launches == [["open", "zoommtg://zoom.us/wc/123/join?pwd=abc"]]


def test_launch_name_round_trips_percent_encoded_password(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """``parse_qs`` URL-decodes the password from the saved URL, then the
    launcher re-encodes it when building the zoommtg URL (closes #37). The
    decoded round-trip must yield the original byte-for-byte."""
    from urllib.parse import parse_qs, urlsplit

    write_meetings({"team": {"url": "https://zoom.us/j/123?pwd=ab%23cd"}})
    commands_mod._launch_name("team")
    assert len(captured_launches) == 1
    argv = captured_launches[0]
    assert argv[0] == "open"
    pwd_values = parse_qs(urlsplit(argv[1]).query).get("pwd", [])
    assert pwd_values == ["ab#cd"]


def test_launch_name_round_trips_space_in_password(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    from urllib.parse import parse_qs, urlsplit

    write_meetings({"team": {"url": "https://zoom.us/j/123?pwd=hello%20world"}})
    commands_mod._launch_name("team")
    assert len(captured_launches) == 1
    pwd_values = parse_qs(urlsplit(captured_launches[0][1]).query).get("pwd", [])
    assert pwd_values == ["hello world"]


def test_launch_name_picks_pwd_when_other_query_params_present(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """Earlier slice-based code broke on multiple ``&`` params if ``pwd``
    wasn't the first one. parse_qs handles arbitrary order."""
    write_meetings({"team": {"url": "https://zoom.us/j/123?tk=tracking&pwd=secret&other=1"}})
    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123&pwd=secret"]]


def test_launch_name_handles_url_with_fragment(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    write_meetings({"team": {"url": "https://zoom.us/j/123?pwd=abc#section"}})
    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123&pwd=abc"]]


def test_launch_name_explicit_password_field_overrides_url_password(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """When an entry has both a URL with ``pwd=`` and an explicit
    ``password`` field, the explicit field wins (preserves prior behavior)."""
    write_meetings({"team": {"url": "https://zoom.us/j/123?pwd=fromurl", "password": "explicit"}})
    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123&pwd=explicit"]]


# ---- Keyring integration (issue #5) -------------------------------------


def test_launch_name_uses_keyring_password_when_available(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """Keyring is the source of truth — wins over plaintext in JSON."""
    from zoom_cli import secrets

    write_meetings({"team": {"id": "555"}})
    secrets.set_password("team", "from-keyring")

    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=555&pwd=from-keyring"]]


def test_launch_name_keyring_wins_over_legacy_json_password(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """Back-compat ladder: if both a keyring entry and a legacy JSON
    password exist, the keyring wins. Pre-keyring JSON entries continue
    to work; once a user re-saves, they migrate."""
    from zoom_cli import secrets

    write_meetings({"team": {"id": "555", "password": "legacy-json"}})
    secrets.set_password("team", "from-keyring")

    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=555&pwd=from-keyring"]]


def test_launch_name_falls_back_to_legacy_json_password(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """No keyring entry → fall back to plaintext JSON password (back-compat)."""
    write_meetings({"team": {"id": "555", "password": "legacy-only"}})

    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=555&pwd=legacy-only"]]


def test_launch_name_empty_keyring_password_overrides_url_pwd(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """Superpowers review on PR #28: if the user explicitly stored an
    empty-string password in the keyring (a deliberate "no password"),
    that empty value must beat the URL's ``pwd=`` rather than falling
    through to it."""
    from zoom_cli import secrets

    write_meetings({"team": {"url": "https://zoom.us/j/123?pwd=fromurl"}})
    secrets.set_password("team", "")  # explicit empty

    commands_mod._launch_name("team")
    # Empty keyring password wins → no &pwd= appended.
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123"]]


def test_save_url_with_no_password_clears_keyring(tmp_zoom_cli_home) -> None:
    """`_save_url(name, url, "")` must clear any pre-existing keyring entry —
    otherwise re-saving a meeting "without a password" would silently keep
    the old one."""
    from zoom_cli import secrets

    secrets.set_password("standup", "stale")
    commands_mod._save_url("standup", "https://zoom.us/j/1", "")

    assert secrets.get_password("standup") is None


def test_save_url_keyring_failure_leaves_json_untouched(
    tmp_zoom_cli_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex regression for PR #28: save must write keyring BEFORE JSON.
    If the keyring write fails, the prior on-disk state is preserved."""
    from zoom_cli import secrets

    # Seed: existing meeting with a known JSON contents (v1 envelope from #24).
    (tmp_zoom_cli_home / "meetings.json").write_text(
        '{"schema_version": 1, "meetings": {"standup": {"url": "https://old.example/j/1"}}}'
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("keyring backend exploded")

    monkeypatch.setattr(secrets, "set_password", boom)

    with pytest.raises(RuntimeError, match="keyring backend exploded"):
        commands_mod._save_url("standup", "https://NEW.example/j/2", "newpw")

    # JSON must be unchanged — the rewrite never happened.
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"standup": {"url": "https://old.example/j/1"}}


def test_remove_deletes_keyring_entry(write_meetings, tmp_zoom_cli_home) -> None:
    """`zoom rm` must take the keyring entry with it — leaving an orphan
    keyring entry under a freed name is a leak."""
    from zoom_cli import secrets

    write_meetings({"team": {"id": "1"}})
    secrets.set_password("team", "p")

    commands_mod._remove("team")

    assert secrets.get_password("team") is None


def test_ls_masks_keyring_password(write_meetings, capsys: pytest.CaptureFixture[str]) -> None:
    from zoom_cli import secrets

    write_meetings({"team": {"id": "1"}})
    secrets.set_password("team", "very-secret")

    commands_mod._ls()
    out = capsys.readouterr().out
    assert "very-secret" not in out, "real password leaked into ls output"
    assert "********" in out
    assert "password:" in out


def test_ls_masks_legacy_json_password(write_meetings, capsys: pytest.CaptureFixture[str]) -> None:
    """Legacy plaintext-in-JSON passwords must also be masked, even though
    the storage path is the back-compat one."""
    write_meetings({"team": {"id": "1", "password": "legacy"}})

    commands_mod._ls()
    out = capsys.readouterr().out
    assert "legacy" not in out, "legacy plaintext password leaked into ls output"
    assert "********" in out


# -------------------------------------------------------------------------


def test_launch_name_personal_link_with_explicit_password_passes_password(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """Regression for review feedback on #6: when a personal-link/non-/j/
    URL has an explicit ``password`` field saved, the URL fallback path
    must pass it to the launcher so the meeting joins without a manual
    re-entry."""
    write_meetings({"personal": {"url": "https://zoom.us/s/my-link", "password": "explicit"}})
    commands_mod._launch_name("personal")
    assert captured_launches == [["open", "zoommtg://zoom.us/s/my-link?pwd=explicit"]]


def test_launch_name_personal_link_with_url_pwd_does_not_double_append(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """If the URL already has ``pwd=``, we must not append it again — that
    would corrupt the URL. The URL passes through verbatim through the
    zoommtg launcher."""
    write_meetings({"personal": {"url": "https://zoom.us/s/my-link?pwd=fromurl"}})
    commands_mod._launch_name("personal")
    assert captured_launches == [["open", "zoommtg://zoom.us/s/my-link?pwd=fromurl"]]


def test_launch_name_empty_string_password_is_respected_not_replaced(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """Regression for superpowers review on #6: an entry with
    ``password: ""`` (intentional clear via ``zoom edit``) must keep the
    empty value, not silently fall back to the URL's pwd= parameter.
    Presence-check, not truthy-check."""
    write_meetings({"team": {"url": "https://zoom.us/j/123?pwd=fromurl", "password": ""}})
    commands_mod._launch_name("team")
    # Empty explicit password wins over URL pwd=. launch_zoommtg with
    # password="" produces the URL with no &pwd= suffix.
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123"]]


def test_launch_name_handles_confno_query_param_url(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """Regression for codex review on #6: URLs of the form
    ``?confno=<id>`` should now be recognized as meeting URLs and
    re-emitted through the canonical zoommtg:// scheme."""
    write_meetings({"team": {"url": "https://zoom.us/join?confno=123456789&pwd=p"}})
    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123456789&pwd=p"]]


def test_launch_name_propagates_launcher_unavailable_as_error_message(
    write_meetings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from zoom_cli import utils as utils_mod

    write_meetings({"team": {"id": "1"}})
    monkeypatch.setattr(utils_mod.shutil, "which", lambda _cmd: None)

    commands_mod._launch_name("team")
    out = capsys.readouterr().out
    assert "Error:" in out
    assert "Neither" in out  # message from LauncherUnavailableError


# ---- _edit ---------------------------------------------------------------


class _FakeQ:
    """Fake questionary chainable: ``questionary.text(...).ask()`` returns a fixed value."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, message, default=""):  # questionary.text(message, default=...)
        self._last = (message, default)
        return self

    def ask(self):
        self.calls.append(self._last)
        if not self._answers:
            raise AssertionError(f"_FakeQ ran out of answers; last call was {self._last!r}")
        return self._answers.pop(0)


def test_edit_overwrites_url_with_new_answer(
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_edit` no longer prompts for password (it's in the keyring); the URL
    field is still re-prompted."""
    write_meetings({"team": {"url": "https://old.example/j/1"}})
    fake = _FakeQ(["https://new.example/j/2"])
    monkeypatch.setattr(commands_mod.questionary, "text", fake)

    commands_mod._edit("team", "", "", "")

    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"team": {"url": "https://new.example/j/2"}}


def test_edit_with_password_flag_writes_to_keyring(
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing ``--password`` (positional ``password`` arg here) updates the
    keyring entry; nothing about the password leaks back into meetings.json."""
    from zoom_cli import secrets

    write_meetings({"team": {"url": "https://old.example/j/1"}})
    secrets.set_password("team", "old-pw")
    fake = _FakeQ(["https://new.example/j/2"])
    monkeypatch.setattr(commands_mod.questionary, "text", fake)

    commands_mod._edit("team", "", "", "new-pw")

    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"team": {"url": "https://new.example/j/2"}}
    assert secrets.get_password("team") == "new-pw"


def test_edit_migrates_legacy_plaintext_password_into_keyring(
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-keyring entry has ``password`` in JSON. `_edit` must:
    1. NOT re-prompt (would expose plaintext via ``default=...``).
    2. Migrate the value into the keyring before dropping it from JSON.

    Regression for all three reviewers on PR #28 — earlier behavior
    silently destroyed the legacy plaintext on any edit."""
    from zoom_cli import secrets

    write_meetings({"team": {"url": "https://old.example/j/1", "password": "legacy"}})
    assert secrets.get_password("team") is None  # nothing in keyring yet
    fake = _FakeQ(["https://kept.example/j/1"])  # only the URL is prompted
    monkeypatch.setattr(commands_mod.questionary, "text", fake)

    commands_mod._edit("team", "", "", "")

    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    # Legacy password field is gone from JSON — but the value is in the keyring.
    assert on_disk == {"team": {"url": "https://kept.example/j/1"}}
    assert secrets.get_password("team") == "legacy"


def test_edit_legacy_password_migration_does_not_overwrite_existing_keyring(
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a keyring entry already exists, the (stale) legacy JSON password
    must NOT overwrite it. The keyring is authoritative."""
    from zoom_cli import secrets

    write_meetings({"team": {"url": "https://old.example/j/1", "password": "stale-legacy"}})
    secrets.set_password("team", "fresh-keyring")
    fake = _FakeQ(["https://kept.example/j/1"])
    monkeypatch.setattr(commands_mod.questionary, "text", fake)

    commands_mod._edit("team", "", "", "")

    assert secrets.get_password("team") == "fresh-keyring"


def test_edit_aborts_cleanly_on_ctrl_c(
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_meetings({"team": {"url": "https://old.example/j/1"}})
    fake = _FakeQ([None])
    monkeypatch.setattr(commands_mod.questionary, "text", fake)

    with pytest.raises(click.Abort):
        commands_mod._edit("team", "", "", "")

    # Original entry must be untouched.
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())["meetings"]
    assert on_disk == {"team": {"url": "https://old.example/j/1"}}


def test_edit_uses_flag_value_as_default(
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When --url is passed, the prompt for `url` should use the flag value as
    its default rather than the saved value."""
    write_meetings({"team": {"url": "https://old.example/j/1"}})
    fake = _FakeQ(["https://flag.example/j/2"])
    monkeypatch.setattr(commands_mod.questionary, "text", fake)

    commands_mod._edit("team", "https://flag.example/j/2", "", "")

    assert fake.calls[0][1] == "https://flag.example/j/2"
