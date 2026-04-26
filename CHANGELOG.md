# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Modern `pyproject.toml` packaging (PEP 621) with `dev` and `build` extras.
- GitHub Actions CI: ruff lint, mypy, pytest with coverage on Python 3.10–3.13 across Ubuntu and macOS.
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

### Security
- Documented existing `os.system`/`shell=True` usage and plain-text password storage as known issues; tracked for follow-up PRs.

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
