"""Tests for zoom_cli.commands — pure command implementations."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from zoom_cli import commands as commands_mod


def test_save_url_persists_payload(tmp_zoom_cli_home: Path) -> None:
    commands_mod._save_url("standup", "https://zoom.us/j/1", "")
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"standup": {"url": "https://zoom.us/j/1"}}


def test_save_url_includes_password_when_provided(tmp_zoom_cli_home: Path) -> None:
    commands_mod._save_url("standup", "https://zoom.us/j/1", "p@ss")
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"standup": {"url": "https://zoom.us/j/1", "password": "p@ss"}}


def test_save_id_password_persists_payload(tmp_zoom_cli_home: Path) -> None:
    commands_mod._save_id_password("standup", "1234567890", "secret")
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"standup": {"id": "1234567890", "password": "secret"}}


def test_save_id_password_omits_password_when_empty(tmp_zoom_cli_home: Path) -> None:
    commands_mod._save_id_password("standup", "1234567890", "")
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"standup": {"id": "1234567890"}}


def test_remove_deletes_entry(write_meetings, tmp_zoom_cli_home: Path) -> None:
    write_meetings({"a": {"id": "1"}, "b": {"id": "2"}})
    commands_mod._remove("a")
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
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


def test_launch_name_decodes_percent_encoded_password(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    """``parse_qs`` URL-decodes the password before we re-build the
    zoommtg URL, so a percent-encoded ``#`` round-trips correctly."""
    write_meetings({"team": {"url": "https://zoom.us/j/123?pwd=ab%23cd"}})
    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123&pwd=ab#cd"]]


def test_launch_name_decodes_space_in_password(
    write_meetings, captured_launches: list[list[str]]
) -> None:
    write_meetings({"team": {"url": "https://zoom.us/j/123?pwd=hello%20world"}})
    commands_mod._launch_name("team")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123&pwd=hello world"]]


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


def test_edit_overwrites_each_field_with_new_answer(
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_meetings({"team": {"url": "https://old.example/j/1", "password": "old"}})
    fake = _FakeQ(["https://new.example/j/2", "new"])
    monkeypatch.setattr(commands_mod.questionary, "text", fake)

    commands_mod._edit("team", "", "", "")

    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"team": {"url": "https://new.example/j/2", "password": "new"}}


def test_edit_allows_clearing_a_field_with_empty_string(
    write_meetings,
    tmp_zoom_cli_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: ``ask() or val`` silently restored the old value when the
    user submitted an empty string. The fix preserves the empty string and
    only treats ``None`` (Ctrl-C) as cancellation.
    """
    write_meetings({"team": {"url": "https://old.example/j/1", "password": "old"}})
    fake = _FakeQ(["https://kept.example/j/1", ""])  # second answer intentionally empty
    monkeypatch.setattr(commands_mod.questionary, "text", fake)

    commands_mod._edit("team", "", "", "")

    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"team": {"url": "https://kept.example/j/1", "password": ""}}


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
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
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
