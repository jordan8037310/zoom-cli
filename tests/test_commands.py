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
