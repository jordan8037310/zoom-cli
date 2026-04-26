"""Tests for zoom_cli.utils — pure storage + launch helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from zoom_cli import utils as utils_mod


def test_dict_to_json_string_round_trips() -> None:
    payload = {"a": 1, "b": {"c": [1, 2, 3]}}
    serialized = utils_mod.dict_to_json_string(payload)
    assert json.loads(serialized) == payload


def test_get_meeting_file_contents_empty(tmp_zoom_cli_home: Path) -> None:
    assert utils_mod.get_meeting_file_contents() == {}


def test_get_meeting_file_contents_returns_data(write_meetings) -> None:
    write_meetings({"daily": {"url": "https://zoom.us/j/123"}})
    assert utils_mod.get_meeting_file_contents() == {"daily": {"url": "https://zoom.us/j/123"}}


def test_get_meeting_file_contents_handles_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "nope.json"
    monkeypatch.setattr(utils_mod, "SAVE_FILE_PATH", str(missing))
    assert utils_mod.get_meeting_file_contents() == {}


def test_get_meeting_names_sorted(write_meetings) -> None:
    write_meetings({"zeta": {}, "alpha": {}, "mike": {}})
    assert utils_mod.get_meeting_names() == ["alpha", "mike", "zeta"]


def test_write_to_meeting_file_round_trips(tmp_zoom_cli_home: Path) -> None:
    payload = {"team": {"id": "999", "password": "secret"}}
    utils_mod.write_to_meeting_file(payload)
    on_disk = json.loads((tmp_zoom_cli_home / "meetings.json").read_text())
    assert on_disk == payload


def test_launch_zoommtg_url_no_password(captured_launches: list[str]) -> None:
    utils_mod.launch_zoommtg_url("zoommtg://zoom.us/join?confno=1")
    assert captured_launches == ['open "zoommtg://zoom.us/join?confno=1"']


def test_launch_zoommtg_url_appends_password_with_amp(captured_launches: list[str]) -> None:
    utils_mod.launch_zoommtg_url("zoommtg://zoom.us/join?confno=1", password="abc")
    assert captured_launches == ['open "zoommtg://zoom.us/join?confno=1&pwd=abc"']


def test_launch_zoommtg_url_appends_password_with_question_mark(
    captured_launches: list[str],
) -> None:
    utils_mod.launch_zoommtg_url("zoommtg://zoom.us/foo", password="abc")
    assert captured_launches == ['open "zoommtg://zoom.us/foo?pwd=abc"']


def test_launch_zoommtg_builds_zoommtg_url(captured_launches: list[str]) -> None:
    utils_mod.launch_zoommtg("123456789", "")
    assert captured_launches == ['open "zoommtg://zoom.us/join?confno=123456789"']


def test_launch_zoommtg_includes_password(captured_launches: list[str]) -> None:
    utils_mod.launch_zoommtg("123456789", "secret")
    assert captured_launches == ['open "zoommtg://zoom.us/join?confno=123456789&pwd=secret"']


def test_launch_zoommtg_url_falls_back_to_xdg_open(monkeypatch: pytest.MonkeyPatch) -> None:
    launches: list[str] = []
    monkeypatch.setattr(utils_mod, "is_command_available", lambda cmd: cmd == "xdg-open")
    monkeypatch.setattr(utils_mod.os, "system", lambda c: launches.append(c) or 0)
    utils_mod.launch_zoommtg_url("zoommtg://zoom.us/join?confno=42")
    assert launches == ['xdg-open "zoommtg://zoom.us/join?confno=42"']


def test_console_color_constants_are_strings() -> None:
    for attr in ("PURPLE", "BOLD", "END"):
        assert isinstance(getattr(utils_mod.ConsoleColor, attr), str)


def test_is_command_available_finds_known_command() -> None:
    # `sh` is available on every CI runner we target (ubuntu, macos).
    assert utils_mod.is_command_available("sh") is True


def test_is_command_available_returns_false_for_garbage() -> None:
    assert utils_mod.is_command_available("definitely-not-a-real-command-zxcvbn") is False
