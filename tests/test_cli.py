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
    runner: CliRunner, captured_launches: list[str], tmp_zoom_cli_home: Path
) -> None:
    result = runner.invoke(main, ["https://zoom.us/j/123"])
    assert result.exit_code == 0, result.output
    assert captured_launches == ['open "zoommtg://zoom.us/j/123"']


def test_default_launch_with_saved_name(
    runner: CliRunner,
    write_meetings,
    captured_launches: list[str],
) -> None:
    write_meetings({"team": {"id": "777"}})
    result = runner.invoke(main, ["team"])
    assert result.exit_code == 0, result.output
    assert captured_launches == ['open "zoommtg://zoom.us/join?confno=777"']
