from __future__ import annotations

import json
import os
import shutil
import subprocess
from urllib.parse import parse_qs, urlsplit

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
    """Return True if `command` is on PATH."""
    return shutil.which(command) is not None


class LauncherUnavailableError(RuntimeError):
    """Neither `open` nor `xdg-open` is available on PATH."""


def launch_zoommtg_url(url: str, password: str = "") -> None:
    """Launch the Zoom desktop client for ``url``.

    Uses argv-list ``subprocess.run`` (not the shell) so that meeting URLs and
    passwords containing shell metacharacters (``"``, `` ` ``, ``$``, ``;``)
    cannot be interpreted as shell syntax. Closes #4.
    """
    decorator = "?" if "?" not in url else "&"
    url_to_launch = f"{url}{decorator}pwd={password}" if password else url
    cmd = shutil.which("open") or shutil.which("xdg-open")
    if cmd is None:
        raise LauncherUnavailableError(
            "Neither `open` nor `xdg-open` was found on PATH; cannot launch Zoom."
        )
    # Argv-list form (no shell) — `cmd` comes from shutil.which (literal
    # "open"/"xdg-open") and `url_to_launch` is passed as an argv arg, never
    # interpreted as shell syntax. S603 is a generic subprocess warning.
    subprocess.run([cmd, url_to_launch], check=False)  # noqa: S603


def launch_zoommtg(id: str, password: str) -> None:
    url = "zoommtg://zoom.us/join?confno=" + id
    launch_zoommtg_url(url, password)


def parse_meeting_url(url: str) -> tuple[str | None, str]:
    """Extract ``(meeting_id, password)`` from a Zoom meeting URL.

    Recognizes:

    - ``/j/<id>`` — the standard meeting URL form.
    - ``?confno=<id>`` query parameter — Zoom's older click-to-join form,
      sometimes still emitted (and the same form the ``zoommtg://`` scheme
      uses internally).

    Personal links (``/s/<name>``), web-client links (``/wc/<id>``), and
    unrecognized formats return ``(None, password_if_any)`` so callers can
    fall back to launching the URL as-is. Note: even for unrecognized
    formats the ``pwd=`` parameter is still extracted, so a caller routing
    a ``/wc/...?pwd=abc`` through the fallback launcher knows to add the
    password if the URL doesn't already contain one.

    The ``pwd=`` query parameter is URL-decoded by ``parse_qs``, so
    percent-encoded passwords (e.g. ``pwd=ab%23cd``) round-trip cleanly.
    If multiple ``pwd=`` parameters are present (malicious or buggy), the
    **first** value wins; an attacker cannot override a legitimate first
    value by appending ``&pwd=evil``.
    """
    parsed = urlsplit(url)
    path_segments = [seg for seg in parsed.path.split("/") if seg]
    query = parse_qs(parsed.query)

    meeting_id: str | None = None
    if len(path_segments) >= 2 and path_segments[0] == "j":
        meeting_id = path_segments[1]
    else:
        confno_values = query.get("confno", [])
        if confno_values:
            meeting_id = confno_values[0]

    password = query.get("pwd", [""])[0]
    return meeting_id, password


def strip_url_scheme(url: str) -> str:
    """Return ``url`` with any leading ``scheme://`` removed."""
    return url.split("://", 1)[1] if "://" in url else url
