# Security

Threat model and security posture for `zoom-cli`. See also `LOCAL-SECURITY.md` for tool/MCP risk assessment, and `.claude/settings.json` for enforced permission rules.

## Application Type

`zoom-cli` is a Python 3.10+ command-line tool with two operational modes:

1. **Local launcher mode (legacy)** — stores meeting bookmarks in `~/.zoom-cli/meetings.json` and launches the macOS Zoom app via the `zoommtg://` URL scheme. Originated from upstream `tmonfre/zoom-cli`.
2. **Zoom REST API mode (in progress)** — Server-to-Server OAuth (`zoom auth s2s`) and downstream API calls (`zoom users me`, future meetings/recordings/etc.). Credentials live in the OS keyring under service names `zoom-cli` (meeting passwords) and `zoom-cli-auth` (OAuth client_id + client_secret).

## Authentication & Authorization

| Surface | Mechanism | Storage | Notes |
|---------|-----------|---------|-------|
| Meeting passwords | User-supplied at `zoom save` / `zoom edit` | OS keyring, service `zoom-cli` | Migrated from plaintext JSON in PR #28 (closes #5). Legacy plaintext entries are auto-migrated on first `_edit` touch. |
| Server-to-Server OAuth | Account ID + Client ID + Client Secret | OS keyring, service `zoom-cli-auth` | Set via `zoom auth s2s set`; secret prompt is masked. Tested via `zoom auth s2s test` (PR #30 / closes #11). |
| API access tokens | OAuth bearer, 1-hour TTL | In-memory only (`AccessToken` dataclass with `is_expired`) | Never persisted. Refreshed on demand by `ApiClient`. |
| User OAuth + PKCE | Planned | TBD | Tracked in issue #12. |

## Data Classification

| Data | Sensitivity | Where it lives |
|------|-------------|----------------|
| Zoom meeting URLs | Low — shareable links | `~/.zoom-cli/meetings.json` |
| Meeting passwords | **High** | OS keyring (`zoom-cli` service); legacy plaintext entries may still exist in `meetings.json` for un-touched bookmarks |
| OAuth client secret | **Critical** | OS keyring (`zoom-cli-auth` service) |
| Bearer tokens | **Critical** | Process memory only |
| Zoom user PII (email, name, role) | High | Returned by `zoom users me` and similar API calls; printed to terminal but not persisted |

## Attack Surface

### Untrusted input paths

- **Saved JSON file** — `~/.zoom-cli/meetings.json` is user-writable; treat all fields as untrusted when read back. URL parsing in `_launch_url` uses `urllib.parse` with typed exceptions (PR #26 / closes #6).
- **Interactive prompts** — questionary input must be treated as untrusted; the launcher historically used `os.system(...)` (shell semantics) and was switched to argv-list `subprocess.run` in PR #25 review feedback.
- **Zoom API responses** — JSON envelope `{code, message}` is parsed; non-2xx raises `ZoomApiError` with the parsed envelope, never blindly executed.

### Known historical issues (now mitigated)

| Issue | Mitigation | PR |
|-------|-----------|----|
| `os.system` shell injection on launcher | Switched to argv-list `subprocess.run` | #25 |
| Plaintext meeting passwords in JSON | Migrated to OS keyring | #28 (#5) |
| Bare `except Exception` swallowing URL errors | Replaced with typed `urllib.parse` exceptions | #26 (#6) |
| Non-atomic JSON writes (corruption risk on crash) | tempfile + fsync + os.replace + parent-dir fsync | #27 (partial #24) |
| `zoom rm` immediate deletion without confirmation | `--dry-run` + `--yes`; interactive prompt confirms | #27 (partial #24) |

### Open / deferred issues

- **Schema versioning of `meetings.json`** — partial #24, not yet implemented.
- **User OAuth (PKCE)** — issue #12.
- **Rate-limit-aware HTTP client + pagination** — issue #16.
- **Webhook receiver HMAC verification** — issue #17 (not started).

## Mitigations

- **OS keyring** for all secrets (Keychain on macOS, libsecret on Linux, Credential Manager on Windows). Service names are pinned by tests so a future rename cannot silently orphan stored credentials.
- **In-memory tokens only** — bearer tokens never touch disk.
- **Atomic file writes** — `write_to_meeting_file` uses tempfile + fsync + `os.replace` + parent-dir fsync (POSIX) so a crash mid-write cannot corrupt the saved file.
- **Typed exceptions** — `ZoomAuthError`, `ZoomApiError`, and `httpx.HTTPError` are distinct so users know whether to debug credentials, the API call, or connectivity.
- **Test isolation** — every secret-touching test runs against an autouse `_InMemoryKeyring` backend; every HTTP test uses `httpx.MockTransport`. Production code is exercised end-to-end with zero socket I/O and zero Keychain writes.

## Security Testing

| Tool | Scope | Where it runs |
|------|-------|---------------|
| ruff | Lint + format | `ruff check .` / `ruff format --check .` (CI: GitHub Actions) |
| mypy | Type checking | `mypy` (CI) |
| pytest | Unit + integration | 160+ tests across Python 3.10–3.13 × Ubuntu+macOS (CI) |
| Service-name pinning | Regression guard against keyring service rename | `tests/test_secrets.py`, `tests/test_auth.py` |
| `httpx.MockTransport` | OAuth + API calls without sockets | `tests/test_auth.py`, `tests/test_api_client.py`, `tests/test_api_users.py` |

## Reporting

Security issues should be filed as GitHub issues on `jordan8037310/zoom-cli` with the `security` label. For sensitive disclosures, contact the repo owner directly before opening a public issue.

## AI development guardrails

When AI assistants (Claude Code, Codex) work on this project, the following rules apply (enforced by `.claude/settings.json`):

- **No live Zoom API calls during development.** Deny rules block `zoom auth s2s set/test`, `zoom users me`, and any other endpoint subcommand. All testing uses `httpx.MockTransport`.
- **No keyring access for `zoom-cli` / `zoom-cli-auth` services.** Deny rules block `keyring get/set` and macOS `security find-generic-password` against those service names.
- **No `.env` reads.** Defense-in-depth — project does not currently use `.env`, but baseline deny rules guard against future addition.
- **No force-push, hard reset, or history rewrite** without explicit operator approval.
