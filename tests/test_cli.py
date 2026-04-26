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
    result = runner.invoke(
        main,
        ["save", "-n", "standup", "--id", "1234567890", "-p", "pw"],
    )
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"standup": {"id": "1234567890", "password": "pw"}}


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
    write_meetings({"a": {"id": "1"}, "b": {"id": "2"}})
    result = runner.invoke(main, ["rm", "a"])
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == {"b": {"id": "2"}}


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
