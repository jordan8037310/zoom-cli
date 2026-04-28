# Zoom CLI

[![CI](https://github.com/jordan8037310/zoom-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/jordan8037310/zoom-cli/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`zoom` is a command-line tool for Zoom — two modes in one binary:

| Mode | What it does | Auth |
|---|---|---|
| **Local launcher** (offline) | Save meetings as named bookmarks; launch the Zoom desktop client via `zoommtg://` | None |
| **Zoom REST API** | List/get/create/update/delete users, meetings, recordings; download recordings | Server-to-Server OAuth or User OAuth (PKCE) |

Both modes ship in the same `zoom` binary and share the same configuration directory (`~/.zoom-cli/`). You can use one or both.

> **Fork in flight.** `jordan8037310/zoom-cli` is being modernized and expanded toward Zoom REST API integration. See [`CHANGELOG.md`](CHANGELOG.md) for the running notes and [`docs/comparative-analysis.md`](docs/comparative-analysis.md) for the maturity / roadmap. Upstream is [`tmonfre/zoom-cli`](https://github.com/tmonfre/zoom-cli).

## Quick start

### Local launcher mode

```bash
# Save a meeting
zoom save -n standup --url 'https://zoom.us/j/123456789?pwd=secret'

# Launch it later
zoom standup

# Or launch any URL on the fly
zoom 'https://zoom.us/j/123456789?pwd=secret'

# List saved meetings (passwords masked)
zoom ls

# Delete a saved meeting
zoom rm standup
```

Saved meetings live in `~/.zoom-cli/meetings.json` (just metadata). Passwords go into the OS keyring (Keychain on macOS, libsecret on Linux, Credential Manager on Windows) — never plaintext on disk for new entries.

### Zoom REST API mode

```bash
# Configure Server-to-Server OAuth credentials (creates a Zoom marketplace app first)
zoom auth s2s set --account-id AAA --client-id BBB
# Client secret is read from ZOOM_CLIENT_SECRET env var or prompted (never accepted as a flag)

# Verify
zoom auth s2s test

# Read your own profile
zoom users me

# List users (paginated, TSV output)
zoom users list

# List your scheduled meetings
zoom meetings list

# Download a meeting's recordings
zoom recordings download 12345 --out-dir ./recordings
```

For users without admin marketplace access, `zoom auth login --client-id <id>` runs a 3-legged OAuth flow with PKCE instead.

## Installation

### macOS / Linux (via PyPI)

```bash
pip install zoom-cli           # (planned — not yet on PyPI)
# Or directly from GitHub:
pip install git+https://github.com/jordan8037310/zoom-cli.git
```

### macOS / Linux (legacy Homebrew, upstream)

The upstream `tmonfre/zoom-cli` Homebrew tap installs the local-launcher portion only:

```bash
brew tap tmonfre/homebrew-tmonfre
brew install zoom
```

This fork's REST API surface is **not** available through that tap yet. Use `pip install` until a fresh formula publishes.

### Windows

Currently no installer; use the [developer instructions](#developer-instructions) below.

## CLI reference

Every command supports `--help`. Full surface as of latest:

### Local launcher

```
zoom <name>                          # launch saved meeting
zoom <url>                           # launch URL (only Zoom domains accepted)
zoom save -n NAME [--url URL | --id ID] [-p PASSWORD]
zoom edit  [-n NAME] [--url URL] [--id ID] [-p PASSWORD]
zoom rm    [NAME] [--yes] [--dry-run]
zoom ls                              # list saved (passwords masked)
```

URL safety: `zoom <url>` only accepts hosts on the Zoom allowlist (`zoom.us`, `*.zoom.us`, `zoomgov.com`, `*.zoomgov.com`). Look-alike hosts like `my-zoom.us-domain.com` are refused at the launcher.

### Authentication

```
zoom auth s2s set [--account-id ID] [--client-id ID]
                                # client secret: ZOOM_CLIENT_SECRET env var or masked prompt
zoom auth s2s test              # exchange creds for an access token
zoom auth login --client-id ID [--port N] [--timeout S] [--no-browser]
                                # 3-legged user OAuth + PKCE (#12)
zoom auth status                # show which surfaces are configured
zoom auth logout                # clear all stored credentials
```

### Users API

```
zoom users me                                  # current user profile
zoom users get <user-id-or-email>              # any user's profile
zoom users list [--status active|inactive|pending] [--page-size N]
zoom users create --email E --type {1,2,3} [--first-name] [--last-name] [...] [--action ...]
zoom users delete <user-id> [--action disassociate|delete] [--transfer-email ...] [--yes] [--dry-run]
zoom users settings get [user-id]              # JSON dump
```

### Meetings API

```
zoom meetings list [--user-id me] [--type scheduled|live|upcoming|...] [--page-size N]
zoom meetings get <meeting-id>
zoom meetings create --topic T [--type N] [--start-time ISO] [--duration MIN] [--password P] [...]
zoom meetings update <meeting-id> [--topic] [--start-time] [--duration] [...]
zoom meetings delete <meeting-id> [--yes] [--dry-run] [--notify-host] [--notify-registrants]
zoom meetings end    <meeting-id> [--yes]      # kicks all participants
```

### Recordings API

```
zoom recordings list [--user-id me] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--page-size N]
zoom recordings get <meeting-id>               # JSON dump for jq pipelines
zoom recordings download <meeting-id> [--out-dir DIR] [--file-type MP4 ...]
                                              # streamed atomic write per file
zoom recordings delete <meeting-id> [--file-id ID] [--action trash|delete] [--yes] [--dry-run]
```

## Codegen (optional, dev tool)

For developers who want statically-typed Pydantic v2 models instead of `dict[str, Any]`, [`scripts/codegen.py`](scripts/codegen.py) wraps `datamodel-code-generator` against Zoom's published OpenAPI spec.

```bash
# Install the codegen extra (only needed when running the script)
pip install -e '.[codegen]'

# Fetch Zoom's OpenAPI spec (URL changes occasionally — see Zoom developer docs)
curl -o /tmp/zoom-openapi.json https://developers.zoom.us/openapi-spec/...

# Run the generator (or `--dry-run` to inspect the invocation first)
python scripts/codegen.py /tmp/zoom-openapi.json
```

The generated models land in `zoom_cli/api/_generated/` and are gitignored by default. Existing helpers (`users.py`, `meetings.py`, `recordings.py`) still return raw dicts; migrating each to typed return shapes is opt-in per endpoint.

## Examples

See [`examples/`](examples/) for runnable scripts:

- [`examples/list-active-users.sh`](examples/list-active-users.sh) — TSV pipeline for `zoom users list` (cut/awk/sort).
- [`examples/download-recent-recordings.sh`](examples/download-recent-recordings.sh) — list-then-download for the last week.
- [`examples/batch-meetings-with-rate-limit.py`](examples/batch-meetings-with-rate-limit.py) — programmatic Python use of `ApiClient` with the per-tier rate limiter.

## Configuration

| Path | What it stores |
|---|---|
| `~/.zoom-cli/meetings.json` | Local launcher bookmarks (URL or meeting ID + name; passwords masked into the keyring on save). Atomic writes; schema-versioned. |
| OS keyring service `zoom-cli` | Per-meeting passwords (one entry per saved meeting). |
| OS keyring service `zoom-cli-auth` | Server-to-Server OAuth credentials (account_id, client_id, client_secret). |
| OS keyring service `zoom-cli-user-auth` | User OAuth refresh token + client_id (PKCE flow). |
| In-memory only | API access tokens (1-hour bearer; re-minted on demand). |

Environment variables (all optional):

- `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` — alternative inputs for `zoom auth s2s set` (the secret is **never** accepted as a CLI flag).
- `ZOOM_USER_CLIENT_ID` — alternative input for `zoom auth login`.

## Security

For the full threat model, see [`SECURITY.md`](SECURITY.md). Highlights:

- All secrets live in the OS keyring; nothing sensitive on disk.
- URLs go through a domain allowlist before launch — deceptive look-alikes refused.
- All `meetings.json` writes are atomic (tempfile + fsync + `os.replace` + parent-dir fsync) and use a POSIX `fcntl.flock` to serialize concurrent CLI invocations.
- File mode `0o600` for `meetings.json`, `0o700` for `~/.zoom-cli/`. Existing permissive perms are tightened on touch.
- API client retries 401 once with a force-refresh and 429 up to three times with `Retry-After` + jitter. Optional opt-in per-tier token-bucket limiter for batch jobs.
- AI assistants working on this project are denied (via `.claude/settings.json`) every endpoint command, keyring access against the `zoom-cli*` services, and direct `curl` against `api.zoom.us`. See [`LOCAL-SECURITY.md`](LOCAL-SECURITY.md).

## Developer instructions

Interested in contributing? See [`CLAUDE.md`](CLAUDE.md) for the project conventions and [`TASKS.md`](TASKS.md) for the open backlog.

```bash
# 1. Python 3.10+
python3 -m venv .venv
source .venv/bin/activate

# 2. Editable install with dev extras
pip install -e '.[dev]'

# 3. Quality gate
ruff check .          # lint
ruff format --check . # formatting
mypy                  # type check
pytest                # 429+ tests across the matrix

# 4. Run the CLI directly
python -m zoom_cli --help

# 5. (Optional) build a PyInstaller binary for releases
pip install -e '.[build]'
./build.sh             # produces dist/zoom + dist/zoom.tar.gz
```

CI runs the same gate on Python 3.10–3.13 × Ubuntu + macOS for every PR.

### Branch + PR conventions

- Branches: `feat/<topic>`, `fix/<topic>`, `chore/<topic>`, `docs/<topic>`, `refactor/<topic>`.
- Commits: conventional-style (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- One issue → one PR. Reference the issue in the PR body (`Closes #N`).
- Update [`CHANGELOG.md`](CHANGELOG.md) under `[Unreleased]` for any user-visible change.

## Project layout

```
zoom_cli/
  __main__.py          # Click CLI entrypoint
  commands.py          # Local-launcher commands
  utils.py             # Storage, ANSI helpers, launch helpers, schema versioning
  auth.py              # OS keyring storage for S2S + user OAuth credentials
  secrets.py           # Per-meeting password storage (keyring)
  api/
    client.py          # ApiClient (bearer auth, 401/429 retry, optional rate limiter)
    oauth.py           # S2S token exchange
    user_oauth.py      # 3-legged PKCE flow
    pagination.py      # paginate() generator helper
    rate_limit.py      # per-tier token bucket + daily counter
    users.py           # /users helpers
    meetings.py        # /meetings helpers
    recordings.py      # /meetings/<id>/recordings helpers
tests/                 # pytest suite (429+ tests across the API + CLI surface)
examples/              # runnable example scripts
docs/                  # design notes & comparative analysis
.github/workflows/     # CI
.claude/               # FACET CC settings (AI-assistant guardrails)
```

## Links

- [`CHANGELOG.md`](CHANGELOG.md) — release notes
- [`SECURITY.md`](SECURITY.md) — threat model
- [`LOCAL-SECURITY.md`](LOCAL-SECURITY.md) — AI/MCP/skill risk register
- [`CLAUDE.md`](CLAUDE.md) — AI-assistant project conventions
- [`TASKS.md`](TASKS.md) — open backlog
- [Zoom REST API docs](https://developers.zoom.us/docs/api/)
- [Zoom rate limits](https://developers.zoom.us/docs/api/rate-limits/)
