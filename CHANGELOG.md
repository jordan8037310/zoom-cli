# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> Bootstrap PR: [#25](https://github.com/jordan8037310/zoom-cli/pull/25) — closes #4, #7, #8 and partially addresses #9, #10.
> Codex review follow-ups (PR #32): closes #34, #35, #36, #37, #38, #39, #40, #41, #42, #43, #44, #45, #46, #47.
> CC security setup (PR #33): adds `.claude/settings.json`, `SECURITY.md`, `LOCAL-SECURITY.md`, `TASKS.md`, and three FACET developer skills.
> Rate-limit + pagination (this branch): closes #16 (partial — per-tier token bucket deferred). 429/Retry-After backoff with jitter; `paginate()` generator helper; `users.list_users()` as the first paginated endpoint.

### Added (issue #16)
- New `zoom_cli/api/pagination.py` with `paginate(client, path, *, item_key, params, page_size)` generator. Walks Zoom's `next_page_token` cursor, yielding each item across all pages. Lazy — pages are fetched on demand.
- `zoom_cli/api/users.py::list_users(client, *, status, page_size)` — first consumer of `paginate`. Yields user records across the `/users` endpoint; default `page_size=300` matches Zoom's per-endpoint cap.
- `MAX_429_RETRIES` (3), `MAX_RETRY_DELAY_SECONDS` (60), `JITTER_RANGE` (0.2) constants exposed by `zoom_cli/api/client.py`.

### Changed (issue #16)
- `ApiClient.request` now retries 429 responses up to `MAX_429_RETRIES` times. Honours `Retry-After` (delta-seconds or HTTP-date per RFC 7231); falls back to exponential backoff (`2^attempt`) when the header is missing. Always caps any single sleep at `MAX_RETRY_DELAY_SECONDS` and applies ±20% jitter so cooperating processes don't thunder back together.
- After `MAX_429_RETRIES` exhaustion, the 429 propagates as `ZoomApiError` so callers can decide what to do (skip, alert, defer).

### Deferred (issue #16 follow-up)
- Per-tier token-bucket rate limiting (Light 80/s, Medium 60/s, Heavy 40/s + 60k/day, Resource-intensive 20/s + 60k/day). Best done after more endpoints land so the per-endpoint tier mapping isn't speculative.

### Security (Codex review follow-ups)
- **#34 (High)** — `zoom auth s2s set` no longer accepts `--client-secret` as a CLI flag. Values in argv landed in shell history and were visible via `ps`/proc to other users on the host. New contract: `ZOOM_CLIENT_SECRET` env var or masked `questionary.password()` prompt only. `--account-id` and `--client-id` still accept flags (public-ish identifiers) and pick up `ZOOM_ACCOUNT_ID` / `ZOOM_CLIENT_ID` env vars.
- **#35 (High)** — `save_s2s_credentials` is now best-effort transactional: snapshot existing values, write new ones, restore the snapshot on any partial failure. Closes the "mixed credential set" failure mode where a partial keyring write left the user authenticating with one new field and two old ones, silently.
- **#37 (Medium)** — Meeting passwords are URL-encoded when appended to the `zoommtg://` query string. Passwords containing `&`, `=`, `#`, `+` etc. now round-trip cleanly instead of corrupting the URL semantics.
- **#38 (Medium)** — Trusted-host allowlist (`zoom.us`, `zoomgov.com`, and proper subdomains thereof) replaces the substring `"zoom.us" in url_or_name` check. Deceptive inputs like `https://evil.example/zoom.us/j/1` and `https://my-zoom.us-domain.com/j/1` are now rejected at the launch layer.
- **#40 (Low)** — `~/.zoom-cli/` is created with `0o700` and `meetings.json` with `0o600`. Existing files/dirs are tightened on touch if owned by the current user and group/world-readable. Initial file creation uses `O_CREAT|O_EXCL` to avoid the umask TOCTOU window.

### Security (CC onboarding setup)
- **Claude Code permission rules** (`.claude/settings.json`) — three-tier deny / allow / default-ask model. Denies `zoom auth s2s set/test`, `zoom users me` and all other endpoint subcommands, keyring access against `zoom-cli` / `zoom-cli-auth` services, direct `curl`/`wget` against `api.zoom.us`, and `~/.zoom-cli/**` reads — so AI assistants cannot consume real Zoom credentials during development. Allow-list covers read-only git/lint/test/CI inspection commands; everything else defaults to ask.
- **`SECURITY.md`** — project threat model, data classification, attack surface, mitigations, and AI development guardrails.
- **`LOCAL-SECURITY.md`** — risk register for installed skills, plugins, and MCP servers (currently no project-scoped MCPs).
- **`TASKS.md`** — onboarding follow-ups (security tooling evaluation, schema versioning, disclosure channel).
- **`.gitignore`** — fixed `.claude/` blanket-ignore so shared `.claude/settings.json` and `.claude/skills/` are tracked while `.claude/settings.local.json` and `.claude/CLAUDE.local.md` remain local-only. Added defense-in-depth `.env` ignores.
- **FACET developer skills** copied into `.claude/skills/`: `env-safe.md`, `mcp-security.md`, `codebase-introspection.md`.

### Fixed (Codex review follow-ups)
- **#39 (Medium)** — `meetings.json` mutations now hold an exclusive POSIX file lock (`fcntl.flock` against `meetings.json.lock`). Prevents lost updates when concurrent `zoom save`/`edit`/`rm` invocations interleave. New `meeting_file_transaction()` context manager wraps read + lock + persist.
- **#41 (Medium)** — `load_s2s_credentials()` no longer flattens `NoKeyringError`/`InitError` to `None`. The CLI now distinguishes "user has not configured S2S yet" (exit 1) from "this machine has no keyring backend at all" (exit 2). `has_s2s_credentials()` keeps the silent-False semantics for the probe-style `zoom auth status` command.
- **#42 (Medium)** — Both `fetch_access_token` and `ApiClient.request` wrap the success-path `response.json()` so a non-JSON 2xx body (corporate proxy returning HTML, captive portal) surfaces as `ZoomAuthError`/`ZoomApiError` instead of leaking raw `ValueError` to callers. Includes the response's `content-type` in the error message for triage.
- **#43 (Medium)** — New `_translate_keyring_errors` decorator in `__main__.py` applied to `s2s set`, `s2s test`, `logout`, `users me`. Splits errors three ways: `NoKeyringError`/`InitError` → exit 2 with "backend not available", other `KeyringError` → exit 3 with "may be locked", anything else propagates. No more raw Python tracebacks on a locked Keychain.
- **#47 (High, partial)** — `AccessToken.is_expired` now treats a token as expired when within `EXPIRY_SKEW_SECONDS` (60s) of its absolute expiry, preventing the race where a request lands after Zoom rotated the token. `ApiClient.request` catches a 401 once, force-refreshes the cached token, and retries the request — covers token rotation / scope-change cases. A second 401 propagates as `ZoomApiError` so we never loop. 429 / Retry-After / token-bucket / pagination remain deferred to issue #16.

### Changed (Codex review follow-ups)
- **#36 (Medium)** — `zoom_cli/api/users.py` now exposes `get_user(client, user_id="me")` as the durable boundary for the Users API. `get_me(client)` is kept as a thin alias for backward compatibility with PR #31's CLI code. The path segment is percent-encoded so caller-supplied IDs cannot inject path/query metacharacters.

### Tests added (Codex review follow-ups)
- **#44 (Medium)** — Parametrized round-trip test over delimiter-heavy passwords (`&`, `=`, `#`, `+`, `?`, space, `%`, quote, backslash). Pin for the #37 fix.
- **#45 (Medium)** — Parametrized test (`fail_on_call=1,2,3`) for the #35 rollback path; asserts the prior credential set survives a partial keyring failure. Plus a no-prior-state variant that asserts the rollback deletes what was written.
- **#46 (Low)** — Tests for HTML, empty, and garbage 2xx bodies on both OAuth and Users endpoints. Pin for the #42 fix.
- Lock-serialization test for #39 (two threads, one delayed; both meetings present after).
- Permissions tests for #40 (fresh dir is 0o700, fresh file is 0o600, existing permissive permissions are tightened on touch).
- 401 retry tests for #47 (single retry on 401, no retry on 403, no infinite loop on persistent 401).

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
