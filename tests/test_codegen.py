"""Tests for scripts/codegen.py — Pydantic v2 model generator wrapper.

The actual code generation is delegated to ``datamodel-code-generator``
(installed only via the optional ``[codegen]`` extra). These tests cover
the wrapper's argv construction, error paths, and the CLI surface;
they don't shell out to the real generator (which would require the
extra installed in CI and a real OpenAPI spec on disk).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

#: Repo root (computed from this test file's path).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CODEGEN_PATH = _REPO_ROOT / "scripts" / "codegen.py"


def _load_codegen():
    """Import scripts/codegen.py as a module despite it living outside the
    package. Cached on the test session via sys.modules."""
    if "codegen_script" in sys.modules:
        return sys.modules["codegen_script"]
    spec = importlib.util.spec_from_file_location("codegen_script", _CODEGEN_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["codegen_script"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- argv construction (pure) -----------------------------------------


def test_build_argv_includes_pinned_flags(tmp_path: Path) -> None:
    """The flag set is the project's policy on generated output: Pydantic
    v2, double quotes, standard collections, py3.10+ syntax, etc. Pin
    them so a future flag drift shows up in review."""
    codegen = _load_codegen()
    spec = tmp_path / "openapi.json"
    out = tmp_path / "_generated"

    argv = codegen._build_argv(spec, out)

    assert argv[0] == "datamodel-codegen"
    # Pinned flags — order doesn't matter for the assertion but inclusion does.
    flag_set = set(argv)
    assert "--input" in flag_set
    assert str(spec) in argv
    assert "--output" in flag_set
    assert str(out) in argv
    assert "--input-file-type" in flag_set
    assert "openapi" in argv
    assert "--output-model-type" in flag_set
    assert "pydantic_v2.BaseModel" in argv
    assert "--use-double-quotes" in flag_set
    assert "--use-standard-collections" in flag_set
    assert "--use-union-operator" in flag_set
    assert "--target-python-version" in flag_set
    assert "3.10" in argv


# ---- main() surface ---------------------------------------------------


def test_main_errors_when_spec_missing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    codegen = _load_codegen()
    missing = tmp_path / "nope.json"

    rc = codegen.main([str(missing)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "spec file not found" in captured.err


def test_main_errors_when_codegen_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """If `datamodel-codegen` isn't on PATH, the wrapper must point the
    user at the right pip install command — not produce a cryptic
    'command not found' from subprocess."""
    codegen = _load_codegen()
    spec = tmp_path / "openapi.json"
    spec.write_text("{}")

    monkeypatch.setattr(codegen.shutil, "which", lambda _cmd: None)

    rc = codegen.main([str(spec), "--output-dir", str(tmp_path / "out")])

    assert rc == 2
    err = capsys.readouterr().err
    assert "datamodel-codegen" in err
    assert "pip install -e '.[codegen]'" in err


def test_main_dry_run_prints_command_without_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--dry-run is the safe way to inspect what would be invoked,
    without needing the generator installed at all (path-on-PATH check
    is bypassed by --dry-run)."""
    codegen = _load_codegen()
    spec = tmp_path / "openapi.json"
    spec.write_text("{}")

    # Pretend the generator IS available — --dry-run shouldn't shell out.
    monkeypatch.setattr(codegen.shutil, "which", lambda _cmd: "/usr/local/bin/datamodel-codegen")

    ran = {"n": 0}

    def fake_run(*_a, **_kw):
        ran["n"] += 1
        raise AssertionError("subprocess.run must not be called for --dry-run")

    monkeypatch.setattr(codegen.subprocess, "run", fake_run)

    rc = codegen.main([str(spec), "--output-dir", str(tmp_path / "out"), "--dry-run"])
    assert rc == 0
    assert ran["n"] == 0
    out = capsys.readouterr().out
    assert "Would run:" in out
    assert "datamodel-codegen" in out


def test_main_propagates_subprocess_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A non-zero exit from datamodel-codegen propagates as the wrapper's
    own exit code so CI can detect failure."""
    codegen = _load_codegen()
    spec = tmp_path / "openapi.json"
    spec.write_text("{}")

    monkeypatch.setattr(codegen.shutil, "which", lambda _cmd: "/usr/local/bin/datamodel-codegen")

    class FakeResult:
        returncode = 17

    monkeypatch.setattr(codegen.subprocess, "run", lambda *_a, **_kw: FakeResult())

    rc = codegen.main([str(spec), "--output-dir", str(tmp_path / "out")])

    assert rc == 17
    assert "exited with status 17" in capsys.readouterr().err


def test_main_creates_output_dir_if_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Output dir is created automatically — saves users a `mkdir -p`."""
    codegen = _load_codegen()
    spec = tmp_path / "openapi.json"
    spec.write_text("{}")
    out_dir = tmp_path / "deeply" / "nested" / "out"

    monkeypatch.setattr(codegen.shutil, "which", lambda _cmd: "/path/to/datamodel-codegen")

    class FakeResult:
        returncode = 0

    monkeypatch.setattr(codegen.subprocess, "run", lambda *_a, **_kw: FakeResult())

    rc = codegen.main([str(spec), "--output-dir", str(out_dir)])

    assert rc == 0
    assert out_dir.is_dir()


# ---- module-level surface -------------------------------------------


def test_default_output_dir_pinned() -> None:
    """A move would silently break collaborators' git status / .gitignore."""
    codegen = _load_codegen()
    assert Path("zoom_cli/api/_generated") == codegen.DEFAULT_OUTPUT_DIR


# ---- --from-url mode ----------------------------------------------------


def test_main_requires_spec_or_url(capsys: pytest.CaptureFixture) -> None:
    """argparse mutually-exclusive required group enforces this."""
    codegen = _load_codegen()
    with pytest.raises(SystemExit) as excinfo:
        codegen.main([])  # neither positional spec nor --from-url
    assert excinfo.value.code == 2  # argparse error exit
    err = capsys.readouterr().err
    assert "required" in err.lower() or "one of" in err.lower()


def test_main_rejects_both_spec_and_url(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Mutually exclusive — passing both should error."""
    codegen = _load_codegen()
    spec = tmp_path / "spec.json"
    spec.write_text("{}")
    with pytest.raises(SystemExit) as excinfo:
        codegen.main([str(spec), "--from-url", "https://example.com/spec.json"])
    assert excinfo.value.code == 2


def test_main_from_url_fetches_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--from-url calls _fetch_spec_to_tempfile and feeds the result to
    the codegen invocation."""
    codegen = _load_codegen()

    fetched_url = {"url": None}
    fake_path = tmp_path / "fetched.json"
    fake_path.write_text("{}")

    def fake_fetch(url: str) -> Path:
        fetched_url["url"] = url
        return fake_path

    monkeypatch.setattr(codegen, "_fetch_spec_to_tempfile", fake_fetch)

    captured_cmd: list = []

    def fake_run(cmd, check=False):
        captured_cmd.extend(cmd)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(codegen.shutil, "which", lambda _cmd: "/path/datamodel-codegen")
    monkeypatch.setattr(codegen.subprocess, "run", fake_run)

    rc = codegen.main(
        [
            "--from-url",
            "https://developers.zoom.us/openapi-spec/api.json",
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    assert fetched_url["url"] == "https://developers.zoom.us/openapi-spec/api.json"
    # The fetched tempfile path should appear in the codegen invocation.
    assert str(fake_path) in captured_cmd
    out = capsys.readouterr().out
    assert "Fetched spec from" in out


def test_main_from_url_propagates_fetch_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Network failure during fetch → exit 1 with a clear message."""
    codegen = _load_codegen()

    def boom(_url: str) -> Path:
        raise RuntimeError("simulated DNS failure")

    monkeypatch.setattr(codegen, "_fetch_spec_to_tempfile", boom)
    rc = codegen.main(
        [
            "--from-url",
            "https://example.com/spec.json",
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "failed to fetch spec" in err
    assert "simulated DNS failure" in err


def test_fetch_spec_to_tempfile_writes_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end smoke of the helper using httpx.MockTransport.

    The helper does ``import httpx`` lazily inside, so patching
    ``httpx.Client`` on the real httpx module is what the function
    picks up at call time.
    """
    import httpx

    codegen = _load_codegen()

    body = b'{"openapi":"3.0.0","info":{"title":"Test"}}'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    real_client = httpx.Client

    class _Mocked(real_client):
        def __init__(self, *_a, **_kw):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", _Mocked)

    path = codegen._fetch_spec_to_tempfile("https://example.com/spec.json")
    try:
        assert path.read_bytes() == body
    finally:
        path.unlink()
