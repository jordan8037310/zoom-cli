# CLAUDE.md — zoom-cli

Project-level guidance for AI assistants working on this repository. The user's global preferences in `~/CLAUDE.md` also apply.

## What this project is

A Python CLI (`zoom`) that originally just stored meeting bookmarks locally and launched the macOS Zoom app via the `zoommtg://` URL scheme. The fork at `jordan8037310/zoom-cli` is being expanded toward broader Zoom REST API integration while keeping the local launcher as a non-API mode.

Upstream lives at `tmonfre/zoom-cli` and is tracked via the `upstream` git remote. Improvements that are not jordan-specific are candidates for upstream PRs.

## Stack

- Python 3.10+ (matrix tests through 3.13)
- Click + click-default-group for CLI parsing
- questionary for interactive prompts (replaced unmaintained PyInquirer)
- pytest + pytest-cov for testing
- ruff for linting and formatting
- mypy for type checking
- GitHub Actions for CI
- PyInstaller for distributable binary builds (legacy path preserved)

## Layout

```
zoom_cli/
  __init__.py     # version + first-run dir/file creation
  __main__.py     # Click CLI entrypoint
  commands.py     # Pure command implementations
  utils.py        # Storage, ANSI helpers, launch helpers
cli.py            # Thin entrypoint shim used by PyInstaller
tests/            # pytest suite
docs/             # comparative analysis, design notes
.github/workflows # CI
```

## Dev workflow

Set up:
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Common commands:
```bash
ruff check .             # lint
ruff format .            # format
mypy                     # typecheck
pytest                   # test
pytest --cov=zoom_cli    # test + coverage
```

## Branch and PR conventions

- Branches: `feat/<topic>`, `fix/<topic>`, `chore/<topic>`, `docs/<topic>`, `refactor/<topic>`.
- Commits: conventional-style (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- One issue → one PR. Reference the issue in the PR body (`Closes #N`).
- Commit early and often (per global CLAUDE.md).
- Update `CHANGELOG.md` under `[Unreleased]` for any user-visible change.

## Code-review automation

When opening a PR, run automated review using:
- `superpowers:requesting-code-review`
- `codex:rescue` (delegate review to Codex for an independent perspective)
- `fullstack-dev-skills:code-reviewer` (for inline issue triage)

## Testing rules

- Never write to the user's real `~/.zoom-cli/`. Always monkeypatch `ZOOM_CLI_DIR` and `SAVE_FILE_PATH` in tests, or use the `tmp_zoom_cli_home` fixture from `tests/conftest.py`.
- Never invoke real `os.system`/`subprocess`. Patch the launcher.
- Tests must not require an interactive TTY — questionary prompts are mocked.

## Security guardrails

- The current launcher uses `os.system(...)` with a `shell=True` semantic. Treat any URL/ID/password coming from an interactive prompt or saved file as untrusted; future PRs will switch to `subprocess.Popen` with a list-form `argv`.
- `meetings.json` stores meeting passwords in plaintext at `~/.zoom-cli/meetings.json`. This is a known issue tracked in GitHub Issues; do not introduce new plaintext-secret storage paths without a tracking issue.
