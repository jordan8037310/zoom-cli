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

### Added (PR [#31](https://github.com/jordan8037310/zoom-cli/pull/31) — partial #14, first downstream API call)
- New authenticated `ApiClient` class (`zoom_cli/api/client.py`): wraps `httpx.Client`, injects `Authorization: Bearer <token>` on every request, caches the access token in-memory until expiry, raises `ZoomApiError` (with `status_code` + Zoom's `code` field) on non-2xx responses.
- New `zoom_cli/api/users.py::get_me` helper for `GET /users/me`.
- New `zoom users me` CLI subcommand: prints the authenticated user's display_name, email, id, account_id, type, and status. Distinguishes `ZoomAuthError` (HTTP 401 from token endpoint), `ZoomApiError` (HTTP error from the Users API), and `httpx.HTTPError` (network/TLS failure) so users know whether to debug creds, scopes, or connectivity.
- API base URL `https://api.zoom.us/v2` pinned by a test.

### Added (PR [#30](https://github.com/jordan8037310/zoom-cli/pull/30) — closes #11)
- New `zoom auth s2s test` command exchanges saved Server-to-Server OAuth credentials for an access token and reports back ("OK" with token-expiry minutes and granted scopes, or a typed error message). Distinguishes "credentials rejected" (HTTP status from Zoom) from "couldn't reach api.zoom.us" (network/TLS failure) so the user knows where to look.
- New `zoom_cli/api/` subpackage seeding the REST API client surface. First module: `oauth.py` with `AccessToken` dataclass (with `is_expired` property), `ZoomAuthError` exception (carrying status_code + error_code + reason), and `fetch_access_token(creds)` against `https://zoom.us/oauth/token` using HTTP Basic auth.
- `httpx>=0.27,<1` added as runtime dependency. Tests use `httpx.MockTransport` so the production code is exercised end-to-end without ever opening a socket.

### Added (PR [#29](https://github.com/jordan8037310/zoom-cli/pull/29) — partial #11, phase-2 entry)
- New `zoom auth` subcommand group: foundation for Zoom REST API authentication.
  - `zoom auth s2s set` saves Server-to-Server OAuth credentials (account_id, client_id, client_secret) to the OS keyring under service `zoom-cli-auth`.
  - `zoom auth status` reports whether S2S is configured.
  - `zoom auth logout` clears all stored API credentials.
  - Client Secret prompt is masked (uses `questionary.password`) so it isn't echoed to the terminal.
- New `zoom_cli/auth.py` module with `S2SCredentials` dataclass + storage helpers (`save_s2s_credentials`, `load_s2s_credentials`, `clear_s2s_credentials`, `has_s2s_credentials`).
- Scoped to credential storage only — actual token exchange against `https://zoom.us/oauth/token` and `zoom auth s2s test` follow in a separate PR (keeps this PR small and reviewable).

### Security (PR [#28](https://github.com/jordan8037310/zoom-cli/pull/28) — closes #5)
- New meeting passwords now go to the OS keyring (Keychain on macOS, libsecret/Secret-Service on Linux, Credential Manager on Windows) under service `zoom-cli` keyed by meeting name — they no longer land in plaintext in `~/.zoom-cli/meetings.json`.
- `zoom ls` masks passwords as `********` regardless of where they came from. Even legacy plaintext-in-JSON passwords are now hidden in the listing.
- `zoom rm <name>` deletes the matching keyring entry alongside the JSON entry, so freed names don't leave orphan secrets.
- `zoom edit` no longer re-prompts for the `password` field (which would have shown the current value as a default — leaking it on screen). Use `--password` to update.
- Back-compat: `_launch_name` reads the keyring first, then falls back to plaintext-in-JSON. Existing users keep working without action; any subsequent `zoom save` migrates that meeting's password to the keyring.
- Auto-migration of existing plaintext passwords (one-shot scan + redaction with a `version` field) is intentionally **not** done in this PR; it'll come as a separate, opt-in step.

### Changed (PR [#27](https://github.com/jordan8037310/zoom-cli/pull/27) — partial #24)
- `write_to_meeting_file` now writes atomically: serialize to a sibling tempfile, `fsync`, then `os.replace` onto `meetings.json`. A crash or kill mid-write can no longer corrupt the file — readers see either the old or the new version, never a partial JSON.
- `zoom rm` gains `--dry-run` (preview) and `--yes`/`-y` (skip confirmation) flags.
- When a meeting name is **picked interactively** by `zoom rm`, a confirmation prompt now fires before deletion (the new safety net catches miss-clicks). `zoom rm <name>` with a positional argument still deletes immediately — no behavior change for scripts/aliases.
- Schema versioning and `--dry-run` on future API `delete` commands deferred to a follow-up PR.

### Changed (PR [#26](https://github.com/jordan8037310/zoom-cli/pull/26) — closes #6)
- `_launch_name` URL parsing now uses `urllib.parse.urlsplit` + `parse_qs` instead of brittle `str.index`/`min(..., float("inf"))` slicing. Personal links (`/s/<name>`), web-client URLs (`/wc/...`), URLs with fragments, and URLs with `pwd=` not as the first query parameter all work now where they previously crashed with `ValueError`.
- `_launch_name` correctly URL-decodes percent-encoded passwords (`pwd=hello%20world` → `hello world`).
- `_launch_name` falls back to launching the URL directly through the `zoommtg://` scheme when the URL is not in the standard `/j/<id>` form.
- `_launch_url` no longer swallows unexpected exceptions with a bare `except Exception`. Only the launcher's own `LauncherUnavailableError` produces a friendly error message; other exceptions propagate so genuine bugs are visible.
- New `parse_meeting_url(url)` and `strip_url_scheme(url)` helpers in `zoom_cli.utils`.

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
