"""Shared pytest fixtures.

These fixtures isolate every test from the user's real ``~/.zoom-cli`` directory,
the user's real OS keyring, and from launching real subprocesses.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import keyring
import keyring.backend
import pytest


class _InMemoryKeyring(keyring.backend.KeyringBackend):
    """Tiny in-memory keyring backend for tests; isolates from the real OS keyring."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            import keyring.errors

            raise keyring.errors.PasswordDeleteError(f"{service}:{username} not set")
        del self._store[(service, username)]


@pytest.fixture(autouse=True)
def isolated_keyring() -> _InMemoryKeyring:
    """Replace the real OS keyring with an in-memory one for every test.

    Autouse so no test can accidentally read or write the developer's real
    keychain. Returns the backend instance so individual tests can pre-seed
    it if needed.
    """
    backend = _InMemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(previous)


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
def captured_launches(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture every argv that would have been launched without invoking the OS.

    Each element is the argv list (e.g. ``["open", "zoommtg://..."]``).
    """
    launches: list[list[str]] = []

    import zoom_cli.utils as utils_mod

    def fake_run(argv, **kwargs):
        launches.append(list(argv))
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(utils_mod.subprocess, "run", fake_run)
    # Make shutil.which echo back known launchers so tests can assert on simple argv.
    monkeypatch.setattr(
        utils_mod.shutil,
        "which",
        lambda cmd: cmd if cmd in {"open", "xdg-open"} else None,
    )
    return launches


def _write_meetings(save_file: Path, payload: dict) -> None:
    save_file.write_text(json.dumps(payload, indent=2))


@pytest.fixture
def write_meetings(tmp_zoom_cli_home: Path):
    save_file = tmp_zoom_cli_home / "meetings.json"

    def _write(payload: dict) -> None:
        _write_meetings(save_file, payload)

    return _write
