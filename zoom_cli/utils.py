from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
from urllib.parse import parse_qs, quote, urlsplit

__version__ = "1.1.6"

ZOOM_CLI_DIR = os.path.expanduser("~/.zoom-cli")
SAVE_FILE_PATH = f"{ZOOM_CLI_DIR}/meetings.json"

#: Allowlist of trusted Zoom hosts. We accept these and any subdomain
#: thereof (``us02web.zoom.us``, ``mydomain.zoom.us``, ``zoomgov.com``,
#: ``us02.zoomgov.com``). Anything else is refused at the launch layer
#: (closes #38). The list is intentionally short — Zoom only operates two
#: top-level domains for joining meetings.
TRUSTED_ZOOM_HOSTS: tuple[str, ...] = ("zoom.us", "zoomgov.com")


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
    """Write the meetings JSON atomically and durably.

    Strategy:
    1. Serialize the new content to a sibling tempfile (created via
       ``tempfile.mkstemp`` so the name is unpredictable and exclusive).
    2. ``flush()`` + ``os.fsync()`` the tempfile's fd so its contents reach
       the disk before we swap it into place.
    3. ``os.replace()`` it onto ``meetings.json``. The replace is atomic on
       POSIX and on Windows for same-filesystem replacements, so readers
       see either the old file or the new file — never a half-written one.
    4. ``os.fsync()`` the parent directory so the directory entry update
       (the rename) is also durable on POSIX. Skipped on platforms where
       opening a directory raises ``PermissionError`` (Windows).

    On any exception during the write, best-effort delete the tempfile so
    we don't leak it, then re-raise the original error. ``meetings.json``
    itself is never opened until the final replace, so a mid-write failure
    cannot corrupt it.
    """
    _ensure_storage()
    payload = dict_to_json_string(contents)
    dir_name = os.path.dirname(SAVE_FILE_PATH) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".meetings.", suffix=".tmp", dir=dir_name)
    try:
        with os.fdopen(fd, "w") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, SAVE_FILE_PATH)
    except Exception:
        # Best-effort cleanup; suppress errors so the original exception wins.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    # Durability: fsync the parent dir so the new dirent survives a crash
    # right after the rename. POSIX-only — Windows raises PermissionError
    # when you try to open a directory.
    with contextlib.suppress(OSError, PermissionError):
        dir_fd = os.open(dir_name, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def is_command_available(command: str) -> bool:
    """Return True if `command` is on PATH."""
    return shutil.which(command) is not None


class LauncherUnavailableError(RuntimeError):
    """Neither `open` nor `xdg-open` is available on PATH."""


class UntrustedHostError(ValueError):
    """The URL's host is not in the trusted Zoom domain allowlist (#38)."""


def is_trusted_zoom_host(host: str) -> bool:
    """Return True if ``host`` is on the Zoom allowlist or a subdomain thereof.

    Comparison is case-insensitive. Empty string returns False. Subdomain
    match requires the suffix to be a proper subdomain (``foo.zoom.us``
    matches; ``my-zoom.us-domain.com`` does NOT — the trailing ``.zoom.us``
    must be a domain boundary, not a substring).
    """
    if not host:
        return False
    normalized = host.lower()
    return any(
        normalized == trusted or normalized.endswith("." + trusted)
        for trusted in TRUSTED_ZOOM_HOSTS
    )


def looks_like_zoom_url(text: str) -> bool:
    """Return True if ``text`` parses to a URL on a trusted Zoom host.

    Used by the CLI to decide whether ``zoom <arg>`` should be treated as a
    URL or as a saved-meeting name. Accepts inputs with or without a scheme
    — ``zoom.us/j/123`` and ``https://zoom.us/j/123`` both return True.
    Strings without a Zoom host (``meeting-name``, ``https://evil.example/zoom.us/j/1``)
    return False.
    """
    candidate = text if "://" in text else f"https://{text}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False
    return is_trusted_zoom_host(parsed.hostname or "")


def launch_zoommtg_url(url: str, password: str = "") -> None:
    """Launch the Zoom desktop client for ``url``.

    Uses argv-list ``subprocess.run`` (not the shell) so that meeting URLs and
    passwords containing shell metacharacters (``"``, `` ` ``, ``$``, ``;``)
    cannot be interpreted as shell syntax (closes #4).

    Validates the URL host against :data:`TRUSTED_ZOOM_HOSTS` before
    launching; raises :class:`UntrustedHostError` for anything else
    (closes #38). The Zoom desktop client itself would likely reject a
    non-Zoom ``zoommtg://`` URL, but failing here gives the user a clear
    error rather than a silent no-op or a confusing client-side dialog.

    URL-encodes ``password`` when building the ``pwd=`` query parameter
    (closes #37); passwords containing ``&``, ``=``, ``#``, ``+`` etc. now
    round-trip correctly instead of corrupting the query string.
    """
    parsed = urlsplit(url)
    if not is_trusted_zoom_host(parsed.hostname or ""):
        raise UntrustedHostError(
            f"Refusing to launch URL with untrusted host: {parsed.hostname or url!r}"
        )

    if password:
        # quote(safe="") percent-encodes every character outside the
        # unreserved set (a-zA-Z0-9_.-~), which is exactly what we want
        # for a query-string value.
        decorator = "?" if "?" not in url else "&"
        url_to_launch = f"{url}{decorator}pwd={quote(password, safe='')}"
    else:
        url_to_launch = url

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
