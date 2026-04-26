from __future__ import annotations

import json
import os
import subprocess

__version__ = "1.1.6"

ZOOM_CLI_DIR = os.path.expanduser("~/.zoom-cli")
SAVE_FILE_PATH = f"{ZOOM_CLI_DIR}/meetings.json"


# adopted from: https://stackoverflow.com/questions/8924173/how-do-i-print-bold-text-in-python
class ConsoleColor:
    PURPLE = "\033[95m"
    CYAN = "\033[96m"
    DARKCYAN = "\033[36m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"


def _ensure_storage() -> None:
    """Create the storage dir and empty meetings file on first use.

    Done lazily so tests can monkeypatch the paths before any storage call.
    """
    if not os.path.isdir(ZOOM_CLI_DIR):
        os.makedirs(ZOOM_CLI_DIR)
    if not os.path.exists(SAVE_FILE_PATH):
        with open(SAVE_FILE_PATH, "w") as file:
            file.write("{}")


def dict_to_json_string(data) -> str:
    def dumper(obj):
        try:
            return obj.toJSON()
        except AttributeError:
            return obj.__dict__

    return json.dumps(data, default=dumper, indent=2)


def get_meeting_file_contents() -> dict:
    try:
        with open(SAVE_FILE_PATH) as file:
            return json.loads(file.read())
    except (OSError, json.JSONDecodeError):
        return {}


def get_meeting_names() -> list[str]:
    return sorted(get_meeting_file_contents().keys())


def write_to_meeting_file(contents: dict) -> None:
    _ensure_storage()
    with open(SAVE_FILE_PATH, "w") as file:
        file.write(dict_to_json_string(contents))


def is_command_available(command: str) -> bool:
    """Return True if `command` is on PATH (or a shell builtin).

    Note: ``shell=True`` is required because ``command`` is a shell builtin and
    cannot be invoked directly. Tracked for hardening in
    https://github.com/jordan8037310/zoom-cli/issues (security/shell-injection epic).
    """
    result = subprocess.run(  # noqa: S602 - tracked, see docstring
        f"command -v {command}",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def launch_zoommtg_url(url: str, password: str = "") -> None:
    """Launch the Zoom desktop client for ``url``.

    Note: ``os.system`` with shell semantics is preserved here for behavior
    parity with the original implementation. Tracked for hardening in the
    security epic; the planned fix is ``subprocess.Popen`` with a list-form argv.
    """
    decorator = "?" if "?" not in url else "&"
    url_to_launch = f"{url}{decorator}pwd={password}" if password else url
    command = "open" if is_command_available("open") else "xdg-open"
    os.system(f'{command} "{url_to_launch}"')  # noqa: S605 - tracked, see docstring


def launch_zoommtg(id: str, password: str) -> None:
    url = "zoommtg://zoom.us/join?confno=" + id
    launch_zoommtg_url(url, password)
