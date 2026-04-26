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


def test_launch_zoommtg_url_no_password(captured_launches: list[list[str]]) -> None:
    utils_mod.launch_zoommtg_url("zoommtg://zoom.us/join?confno=1")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=1"]]


def test_launch_zoommtg_url_appends_password_with_amp(captured_launches: list[list[str]]) -> None:
    utils_mod.launch_zoommtg_url("zoommtg://zoom.us/join?confno=1", password="abc")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=1&pwd=abc"]]


def test_launch_zoommtg_url_appends_password_with_question_mark(
    captured_launches: list[list[str]],
) -> None:
    utils_mod.launch_zoommtg_url("zoommtg://zoom.us/foo", password="abc")
    assert captured_launches == [["open", "zoommtg://zoom.us/foo?pwd=abc"]]


def test_launch_zoommtg_builds_zoommtg_url(captured_launches: list[list[str]]) -> None:
    utils_mod.launch_zoommtg("123456789", "")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123456789"]]


def test_launch_zoommtg_includes_password(captured_launches: list[list[str]]) -> None:
    utils_mod.launch_zoommtg("123456789", "secret")
    assert captured_launches == [["open", "zoommtg://zoom.us/join?confno=123456789&pwd=secret"]]


def test_launch_zoommtg_url_falls_back_to_xdg_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """When `open` isn't on PATH, fall back to `xdg-open`."""
    launches: list[list[str]] = []
    import subprocess as _sp

    monkeypatch.setattr(
        utils_mod.shutil,
        "which",
        lambda cmd: "xdg-open" if cmd == "xdg-open" else None,
    )
    monkeypatch.setattr(
        utils_mod.subprocess,
        "run",
        lambda argv, **kw: (
            launches.append(list(argv))
            or _sp.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")
        ),
    )
    utils_mod.launch_zoommtg_url("zoommtg://zoom.us/join?confno=42")
    assert launches == [["xdg-open", "zoommtg://zoom.us/join?confno=42"]]


def test_launch_zoommtg_url_raises_when_no_launcher_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(utils_mod.shutil, "which", lambda _cmd: None)
    with pytest.raises(utils_mod.LauncherUnavailableError):
        utils_mod.launch_zoommtg_url("zoommtg://zoom.us/join?confno=1")


@pytest.mark.parametrize(
    "metacharacter_password",
    [
        '"; open evil.app; "',
        "$(rm -rf ~)",
        "`whoami`",
        '\\";echo pwn;#',
        "; rm -rf /; #",
    ],
)
def test_launch_zoommtg_url_does_not_shell_interpret_metacharacters(
    captured_launches: list[list[str]], metacharacter_password: str
) -> None:
    """Regression test for #4: shell metacharacters in user data must not be
    interpreted as shell syntax. Argv-list ``subprocess.run`` guarantees this.
    """
    utils_mod.launch_zoommtg("123", metacharacter_password)
    assert len(captured_launches) == 1
    argv = captured_launches[0]
    assert argv[0] == "open"
    # The metacharacters must arrive verbatim in argv[1] — never expanded.
    assert metacharacter_password in argv[1]


def test_console_color_constants_are_strings() -> None:
    for attr in ("PURPLE", "BOLD", "END"):
        assert isinstance(getattr(utils_mod.ConsoleColor, attr), str)


def test_is_command_available_finds_known_command() -> None:
    # `sh` is available on every CI runner we target (ubuntu, macos).
    assert utils_mod.is_command_available("sh") is True


def test_is_command_available_returns_false_for_garbage() -> None:
    assert utils_mod.is_command_available("definitely-not-a-real-command-zxcvbn") is False


# ---- parse_meeting_url ---------------------------------------------------


@pytest.mark.parametrize(
    "url,expected_id,expected_password",
    [
        # Standard meeting URLs
        ("https://zoom.us/j/123456789", "123456789", ""),
        ("https://zoom.us/j/123456789?pwd=abc", "123456789", "abc"),
        ("https://us02web.zoom.us/j/987654321?pwd=xyz", "987654321", "xyz"),
        # Subdomained / vanity hosts
        ("https://example.zoom.us/j/111?pwd=p", "111", "p"),
        # Trailing slash and extra path segments
        ("https://zoom.us/j/222/", "222", ""),
        ("https://zoom.us/j/333/extra-segment", "333", ""),
        # URL fragment shouldn't confuse parsing
        ("https://zoom.us/j/444?pwd=ok#frag", "444", "ok"),
        # Percent-encoded password decodes cleanly
        ("https://zoom.us/j/555?pwd=ab%23cd", "555", "ab#cd"),
        ("https://zoom.us/j/666?pwd=hello%20world", "666", "hello world"),
        # Multiple query params, pwd not first
        ("https://zoom.us/j/777?tk=abc&pwd=secret&other=1", "777", "secret"),
        # zoommtg:// scheme
        ("zoommtg://zoom.us/j/888?pwd=zz", "888", "zz"),
        # confno= query-param form (Zoom emits these for some click-to-join flows)
        ("https://zoom.us/join?confno=123456789", "123456789", ""),
        ("https://zoom.us/join?confno=987&pwd=secret", "987", "secret"),
        ("zoommtg://zoom.us/join?confno=42&pwd=abc", "42", "abc"),
        # Duplicate pwd= — first wins (attacker can't override by appending)
        ("https://zoom.us/j/100?pwd=legit&pwd=evil", "100", "legit"),
        # Unrecognized URL still extracts password for fallback launcher to use
        ("https://zoom.us/wc/123?pwd=fromurl", None, "fromurl"),
        # Personal link / web-client / unknown form -> meeting_id is None
        ("https://zoom.us/s/personal-link", None, ""),
        ("https://zoom.us/wc/123/join", None, ""),
        ("https://zoom.us/", None, ""),
        # Garbage
        ("not a url", None, ""),
        ("", None, ""),
    ],
)
def test_parse_meeting_url_extracts_id_and_password(
    url: str, expected_id: str | None, expected_password: str
) -> None:
    meeting_id, password = utils_mod.parse_meeting_url(url)
    assert meeting_id == expected_id
    assert password == expected_password


def test_strip_url_scheme_preserves_url_without_scheme() -> None:
    assert utils_mod.strip_url_scheme("zoom.us/j/1") == "zoom.us/j/1"


def test_strip_url_scheme_strips_https() -> None:
    assert utils_mod.strip_url_scheme("https://zoom.us/j/1?pwd=abc") == "zoom.us/j/1?pwd=abc"


def test_strip_url_scheme_strips_zoommtg() -> None:
    assert utils_mod.strip_url_scheme("zoommtg://zoom.us/j/2?pwd=xyz") == "zoom.us/j/2?pwd=xyz"
