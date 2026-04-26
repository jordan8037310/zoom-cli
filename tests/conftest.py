"""Shared pytest fixtures.

These fixtures isolate every test from the user's real ``~/.zoom-cli`` directory
and from launching real subprocesses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_zoom_cli_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ZOOM_CLI_DIR / SAVE_FILE_PATH at every reachable import site.

    Both ``zoom_cli.utils`` and any module that imported the constants by name
    (e.g. ``from .utils import SAVE_FILE_PATH``) need patching, so we update both.
    """
    home = tmp_path / ".zoom-cli"
    home.mkdir()
    save_file = home / "meetings.json"
    save_file.write_text("{}")

    import zoom_cli.utils as utils_mod

    monkeypatch.setattr(utils_mod, "ZOOM_CLI_DIR", str(home))
    monkeypatch.setattr(utils_mod, "SAVE_FILE_PATH", str(save_file))
    return home


@pytest.fixture
def captured_launches(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture every URL that would have been launched without invoking the OS."""
    launches: list[str] = []

    import zoom_cli.utils as utils_mod

    def fake_os_system(cmd: str) -> int:
        launches.append(cmd)
        return 0

    monkeypatch.setattr(utils_mod.os, "system", fake_os_system)
    monkeypatch.setattr(utils_mod, "is_command_available", lambda _cmd: True)
    return launches


def _write_meetings(save_file: Path, payload: dict) -> None:
    save_file.write_text(json.dumps(payload, indent=2))


@pytest.fixture
def write_meetings(tmp_zoom_cli_home: Path):
    save_file = tmp_zoom_cli_home / "meetings.json"

    def _write(payload: dict) -> None:
        _write_meetings(save_file, payload)

    return _write
