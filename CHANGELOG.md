# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> Bootstrap PR: [#25](https://github.com/jordan8037310/zoom-cli/pull/25) — closes #4, #7, #8 and partially addresses #9, #10.

### Added
- Modern `pyproject.toml` packaging (PEP 621) with `dev` and `build` extras.
- GitHub Actions CI: ruff lint, mypy, pytest with coverage on Python 3.10–3.13 across Ubuntu and macOS. CI fires on every PR regardless of base branch (so stacked PRs are covered).
- Initial `pytest` test suite covering `zoom_cli.utils` and `zoom_cli.commands`.
- Project-level `CLAUDE.md` with developer workflow and conventions.
- Project-level `CHANGELOG.md` (this file).
- `upstream` git remote pointing at `tmonfre/zoom-cli` for syncing.

### Changed
- Replaced unmaintained `PyInquirer` with `questionary` (active fork; `prompt_toolkit` 3.x compatible). Restores compatibility with Python 3.10+.
- Bumped `click` floor to `>=8.1` and `click-default-group` to `>=1.2.4`.
- Minimum Python version is now 3.10.

### Removed
- `setup.py` and `requirements.txt` (superseded by `pyproject.toml`).

### Fixed
- Ctrl-C no longer falls through as an empty string in `save`/`edit`/`rm`. Cancellation now raises `click.Abort` cleanly instead of silently routing into the wrong branch (`save`) or crashing with `KeyError: ''` (`edit`/`rm`).
- `_edit` no longer silently restores the old value when a user submits an empty string; only Ctrl-C aborts. (Reported by codex review on PR #25.)
- `edit`/`rm` short-circuit with a friendly message when no saved meetings exist, instead of presenting an empty selection.

### Security
- Replaced `os.system` shell interpolation in `launch_zoommtg_url` with argv-list `subprocess.run`; meeting URLs and passwords containing shell metacharacters (`"`, `` ` ``, `$`, `;`) can no longer be interpreted as shell syntax. Closes #4.
- Replaced `subprocess.run(..., shell=True)` in `is_command_available` with `shutil.which`. The previous shell call was only ever invoked with literal command names, but `shutil.which` is the idiomatic, no-shell spelling.
- Documented plain-text password storage as a known issue; tracked in #5 for a follow-up PR (OS keyring migration).

## [1.1.6] - 2024-03-03

### Fixed
- Bug launching meetings via URL (#7).

## [1.1.5] - 2024

### Fixed
- Bug storing meeting URL with name (#5).

## [1.1.4] - 2022

### Changed
- Build script generates a tarball with a SHA-256 hash for Homebrew deployment.
- Removed `--onefile` option from PyInstaller build.

### Added
- `is_command_available` check before launching `open`/`xdg-open`.

## [1.1.3] and earlier

See git history for details prior to the introduction of this changelog.

[Unreleased]: https://github.com/jordan8037310/zoom-cli/compare/v1.1.6...HEAD
[1.1.6]: https://github.com/jordan8037310/zoom-cli/releases/tag/v1.1.6
[1.1.5]: https://github.com/jordan8037310/zoom-cli/releases/tag/v1.1.5
[1.1.4]: https://github.com/jordan8037310/zoom-cli/releases/tag/v1.1.4
