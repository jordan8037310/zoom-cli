# Zoom CLI — Comparative Analysis vs. Public Zoom REST API

_Last updated: 2026-04-25_

This document compares the current `zoom-cli` (a local meeting bookmark + `zoommtg://` URL-scheme launcher) against the public Zoom REST API surface, calls out gaps, and proposes a phased roadmap. It is research-only; no source code was modified.

## 1. Current CLI in one paragraph

`zoom-cli` is a small Python 3 Click app (`zoom_cli/__main__.py`) backed by a single JSON file at `~/.zoom-cli/meetings.json` (`zoom_cli/utils.py`). Subcommands `launch`, `save`, `edit`, `rm`, `ls` (and the implicit default `launch`) let a user persist a meeting under a name and re-open it via `zoommtg://zoom.us/join?confno=...&pwd=...` shelled out through `os.system("open ...")` (`zoom_cli/commands.py:_launch_url`, `_launch_name`). There is **zero** integration with `api.zoom.us` — no auth, no HTTP client, no scopes, no pagination, no webhooks.

## 2. Public Zoom API surface (2026)

Base URL: `https://api.zoom.us/v2/`. All references below are HTTP method + path under `/v2`. Sourced from the Zoom Developer Docs API Reference: https://developers.zoom.us/docs/api/ and the OpenAPI v2 spec at https://github.com/zoom/api/blob/master/openapi.v2.json.

### 2.1 Meetings — https://developers.zoom.us/docs/api/meetings/
- `GET    /users/{userId}/meetings` — list a user's scheduled meetings
- `POST   /users/{userId}/meetings` — create a meeting (use `me` for self)
- `GET    /meetings/{meetingId}` — get a meeting
- `PATCH  /meetings/{meetingId}` — update a meeting
- `DELETE /meetings/{meetingId}` — delete a meeting
- `PUT    /meetings/{meetingId}/status` — end a live meeting
- `GET    /past_meetings/{meetingId}` — get details of a past meeting instance
- `GET    /past_meetings/{meetingId}/participants` — past meeting participants
- `GET    /meetings/{meetingId}/registrants` / `POST .../registrants` — list/add registrants
- `PUT    /meetings/{meetingId}/registrants/status` — approve/deny registrants
- `GET    /meetings/{meetingId}/polls` / `POST .../polls` — meeting polls
- `GET    /meetings/{meetingId}/invitation` — invitation text
- `PATCH  /meetings/{meetingId}/livestream` / `PATCH .../livestream/status` — live streaming
- `GET    /meetings/{meetingId}/jointoken/local_recording` — join token for local recording

### 2.2 Webinars — https://developers.zoom.us/docs/api/webinars/
- `GET  /users/{userId}/webinars` / `POST /users/{userId}/webinars`
- `GET  /webinars/{webinarId}` / `PATCH` / `DELETE`
- `PUT  /webinars/{webinarId}/status` — end webinar
- `GET  /webinars/{webinarId}/registrants` / `POST` / `PUT .../status`
- `GET  /webinars/{webinarId}/panelists` / `POST` / `DELETE .../panelists/{panelistId}`
- `GET  /webinars/{webinarId}/polls` / `POST .../polls`
- `GET  /webinars/{webinarId}/tracking_sources`
- `GET  /past_webinars/{webinarId}/absentees`
- `GET  /past_webinars/{webinarId}/qa`

### 2.3 Users — https://developers.zoom.us/docs/api/users/
- `GET    /users` — list users (`status=active|inactive|pending`)
- `POST   /users` — create user (action: `create|autoCreate|custCreate|ssoCreate`)
- `GET    /users/{userId}` — get user
- `PATCH  /users/{userId}` — update user
- `DELETE /users/{userId}?action=disassociate|delete` — unlink or delete
- `GET    /users/{userId}/settings` / `PATCH .../settings`
- `GET    /users/{userId}/token` — get user-level access token
- `PUT    /users/{userId}/email` — change email
- `PUT    /users/{userId}/status` — activate/deactivate
- `POST   /users/{userId}/assistants` / `DELETE .../assistants/{assistantId}`

### 2.4 Cloud Recordings
- `GET    /users/{userId}/recordings` — list a user's cloud recordings
- `GET    /meetings/{meetingId}/recordings` — get recordings for a meeting
- `DELETE /meetings/{meetingId}/recordings` — delete all
- `DELETE /meetings/{meetingId}/recordings/{recordingId}` — delete one
- `PUT    /meetings/{meetingId}/recordings/status` — recover trash
- `GET    /meetings/{meetingId}/recordings/settings` / `PATCH ...`
- `GET    /meetings/{meetingId}/recordings/registrants` / `POST ...`
- `GET    /accounts/{accountId}/recordings` — account-level list

### 2.5 Reports — https://developers.zoom.us/docs/api/
- `GET /report/daily` — daily account usage
- `GET /report/users` — active/inactive host report
- `GET /report/users/{userId}/meetings` — past meetings hosted by a user
- `GET /report/meetings/{meetingId}` — meeting summary
- `GET /report/meetings/{meetingId}/participants`
- `GET /report/meetings/{meetingId}/polls`
- `GET /report/webinars/{webinarId}/participants`
- `GET /report/cloud_recording` — cloud-recording usage
- `GET /report/telephone` — telephony usage
- `GET /report/operationlogs` — admin audit log

### 2.6 Dashboards (Business+ plan)
- `GET /metrics/meetings` / `GET /metrics/meetings/{meetingId}`
- `GET /metrics/meetings/{meetingId}/participants` / `.../qos`
- `GET /metrics/webinars` / `.../{webinarId}/participants`
- `GET /metrics/zoomrooms` / `.../{zoomRoomId}`
- `GET /metrics/crc` — CRC port usage
- `GET /metrics/im` — IM activity
- `GET /metrics/issues/zoomrooms`
- `GET /metrics/client/feedback`

### 2.7 Team Chat — https://developers.zoom.us/docs/api/rest/reference/chat/methods/
- `GET    /chat/users/{userId}/channels` / `POST ...`
- `GET    /chat/channels/{channelId}` / `PATCH` / `DELETE`
- `GET    /chat/channels/{channelId}/members` / `POST` / `DELETE`
- `GET    /chat/users/{userId}/messages` — list messages (channel or DM via query)
- `POST   /chat/users/me/messages` — send message
- `PUT    /chat/users/me/messages/{messageId}` / `DELETE ...`
- `POST   /chat/users/me/messages/{messageId}/emoji_reactions`
- `GET    /chat/users/me/messages/{messageId}/files`

### 2.8 Phone — https://developers.zoom.us/docs/api/phone/
- `GET    /phone/users` / `GET /phone/users/{userId}` / `PATCH ...`
- `GET    /phone/call_logs` (account) / `GET /phone/users/{userId}/call_logs`
- `GET    /phone/call_history` — modern call history view
- `GET    /phone/recordings` / `GET /phone/users/{userId}/recordings`
- `GET    /phone/voicemails` / `GET /phone/users/{userId}/voice_mails`
- `GET    /phone/sites` / `POST` / `PATCH /phone/sites/{siteId}`
- `GET    /phone/call_queues` / `POST` / `PATCH /phone/call_queues/{callQueueId}`
- `POST   /phone/call_queues/{callQueueId}/members` / `DELETE .../members/{memberId}`
- `GET    /phone/auto_receptionists` / `PATCH ...`
- `GET    /phone/numbers` / `GET .../numbers/{numberId}`
- `GET    /phone/common_areas` / `POST` / `PATCH`

### 2.9 Zoom Rooms
- `GET    /rooms` / `POST /rooms` / `PATCH /rooms/{roomId}` / `DELETE /rooms/{roomId}`
- `GET    /rooms/locations` / `POST` / `PATCH /rooms/locations/{locationId}`
- `GET    /rooms/{roomId}/devices`
- `GET    /rooms/account_settings` / `PATCH ...`
- `PATCH  /rooms/{roomId}/events` — start/end/leave/invite

### 2.10 Contact Center — https://developers.zoom.us/docs/api/contact-center/
- `GET  /contact_center/users` / `POST` / `PATCH /contact_center/users/{userId}`
- `GET  /contact_center/queues` / `POST` / `PATCH`
- `GET  /contact_center/flows` / `POST` / `PATCH`
- `GET  /contact_center/engagements` / `GET /contact_center/engagements/{engagementId}`
- `GET  /contact_center/recordings`
- `GET  /contact_center/dispositions`

### 2.11 Devices
- `GET    /devices` / `POST /devices`
- `GET    /devices/{deviceId}` / `PATCH` / `DELETE`
- `POST   /devices/{deviceId}/zpa/assignment`

### 2.12 Tracking Fields
- `GET    /tracking_fields` / `POST`
- `GET    /tracking_fields/{fieldId}` / `PATCH` / `DELETE`

### 2.13 Groups
- `GET    /groups` / `POST` / `GET /groups/{groupId}` / `PATCH` / `DELETE`
- `GET    /groups/{groupId}/members` / `POST` / `DELETE .../members/{memberId}`
- `GET    /groups/{groupId}/settings` / `PATCH ...`

### 2.14 Roles
- `GET    /roles` / `POST` / `GET /roles/{roleId}` / `PATCH` / `DELETE`
- `GET    /roles/{roleId}/members` / `POST` / `DELETE .../members/{memberId}`

### 2.15 Billing
- `GET /accounts/{accountId}/billing` / `PATCH ...`
- `GET /accounts/{accountId}/plans` / `POST` / `PATCH` / `DELETE`
- `GET /accounts/{accountId}/billing/invoices` / `GET .../invoices/{invoiceId}`

### 2.16 SIP Connected Audio
- `GET    /sip_trunk/numbers` / `POST /sip_trunk/numbers` / `DELETE .../numbers/{numberId}`
- `GET    /accounts/{accountId}/sip_trunk/trunks` / `POST` / `DELETE`
- `GET    /sip_trunk/callout_countries`

### 2.17 TSP (Telephony Service Provider)
- `GET    /tsp` / `PATCH /tsp`
- `GET    /users/{userId}/tsp` / `POST` / `PATCH /users/{userId}/tsp/{tspId}`
- `PATCH  /users/{userId}/tsp/settings`

## 3. Auth in 2026

- **JWT app type is fully sunset** (no new apps after 2023-06-01; existing apps disabled 2023-09-01). See https://developers.zoom.us/changelog/platform/jwt-app-type-deprecation/. Do not build on it.
- **Server-to-Server OAuth (S2S OAuth)** is the recommended flow for headless tooling like a CLI run by an admin. See https://developers.zoom.us/docs/internal-apps/s2s-oauth/.
  - Token endpoint: `POST https://zoom.us/oauth/token?grant_type=account_credentials&account_id={ACCOUNT_ID}`
  - Auth: HTTP Basic with `client_id:client_secret`
  - Token TTL: 1 hour; cache and refresh on demand. Reference: https://github.com/zoom/server-to-server-oauth-token
  - Credentials: `ACCOUNT_ID`, `CLIENT_ID`, `CLIENT_SECRET` (from a Server-to-Server OAuth app in the Zoom Marketplace).
- **OAuth 2.0 (user-level / 3-legged)** for end-user CLI flows (developer/personal use without admin rights). See https://developers.zoom.us/docs/integrations/oauth/. Standard authorization-code flow at `https://zoom.us/oauth/authorize` and `POST /oauth/token`. Use PKCE; persist refresh tokens encrypted (e.g., OS keyring).
- **Most relevant scopes for a CLI** (granular S2S scopes follow the `noun:verb[:admin]` pattern):
  - Meetings: `meeting:read:meeting`, `meeting:write:meeting`, `meeting:update:meeting`, `meeting:delete:meeting`, `meeting:read:list_meetings`
  - Users: `user:read:user`, `user:read:list_users`, `user:write:user`, `user:read:settings`
  - Recordings: `cloud_recording:read:recording`, `cloud_recording:read:list_user_recordings`, `cloud_recording:delete:recording`
  - Reports: `report:read:list_meeting_participants`, `report:read:user`
  - Dashboards: `dashboard:read:list_meetings`, `dashboard:read:meeting`
  - Webinars: `webinar:read:webinar`, `webinar:write:webinar`
  - Phone: `phone:read:list_call_logs`, `phone:read:list_users`
  - Chat: `chat_message:write:user_message`, `chat_channel:read:list_user_channels`

## 4. Notable API behaviors a CLI must handle

- **Rate limits** (https://developers.zoom.us/docs/api/rate-limits/): four tiers per endpoint:
  - Light: ~80 req/s
  - Medium: ~60 req/s
  - Heavy: ~40 req/s, ~60k/day cap
  - Resource-intensive: ~20 req/s, ~60k/day cap
  Handle `429 Too Many Requests` with exponential backoff using the `Retry-After` header, and respect `X-RateLimit-*` response headers. Caps are per-account and tier classification is per endpoint — see the rate-limits page for the per-endpoint table.
- **Pagination**: cursor-style via `next_page_token`; pass `page_size` (default 30, max usually 300; some endpoints cap at 100). The first page request may not include the token. Iterate until `next_page_token` is empty. A small set of endpoints still uses page-number pagination (`page_number` / `page_count`).
- **Webhook verification** (https://developers.zoom.us/docs/api/webhooks/, https://github.com/zoom/webhook-sample):
  - Headers: `x-zm-request-timestamp`, `x-zm-signature` (format `v0={hex_hmac}`)
  - Construct `message = "v0:{timestamp}:{raw_body}"` and HMAC-SHA256 with the **Webhook Secret Token** (not the OAuth client secret); compare in constant time
  - Reject if `now - timestamp > 5 minutes` (replay window)
  - On endpoint validation, Zoom sends `event: "endpoint.url_validation"` with a `plainToken`; respond with `{plainToken, encryptedToken: hmac_sha256_hex(secret, plainToken)}`
- **OpenAPI spec**: maintained at https://github.com/zoom/api/blob/master/openapi.v2.json — usable for client generation (`openapi-python-client`, `datamodel-codegen`, etc.). The spec lags the live docs by days/weeks; treat it as advisory.
- **Idempotency**: Zoom does not honor `Idempotency-Key`. Build retries around safe verbs only.
- **Errors**: structured JSON `{code, message}`. Common codes: `124` (invalid token), `1010` (user not found), `3001` (meeting not found), `200` family (validation).

## 5. Existing Python SDKs / CLIs (one-liners)

- **prschmid/zoomus** (https://github.com/prschmid/zoomus, ~260 stars): the most popular community wrapper; supports OAuth 2.0 incl. S2S since the JWT removal; coverage is broad but uneven (Meetings/Users/Webinars/Recordings strong; Phone/Contact Center thin); maintenance is intermittent. _Take_: usable as a dependency or reference, not as a turnkey CLI.
- **pyzoom** (https://pypi.org/project/pyzoom/): smaller wrapper with built-in OAuth callback web server; OAuth-only since 2023; narrower endpoint coverage focused on meetings/users. _Take_: nice ergonomics for personal user-OAuth flows.
- **rootalley/py-zoom-api** (https://github.com/rootalley/py-zoom-api): unofficial, lightly maintained, classic JWT-era examples; not recommended for new work.
- **zoom-meeting-sdk / zoom-developer-sdk / PyZoomMeetingSDK** (https://pypi.org/project/zoom-meeting-sdk/): Python bindings for the **Meeting SDK** (Linux, native — for bot/in-meeting audio capture), not the REST API. Out of scope for a meeting-management CLI but relevant if the project ever grows into recording bots.
- **No official Zoom-published CLI** exists; Zoom ships sample utilities (`zoom/server-to-server-oauth-token`, `zoom/server-to-server-oauth-starter-api`, `zoom/webhook-sample`) but these are starter snippets, not products.

## 6. Maturity assessment of the current CLI

Scale: 1 = nonexistent, 5 = production-grade.

| Dimension | Score | Justification |
|---|---:|---|
| API coverage | 1 | No REST integration whatsoever; only `zoommtg://` deep-link. |
| Auth | 1 | No OAuth, no token storage; passwords stored in plaintext JSON at `~/.zoom-cli/meetings.json` (`utils.py:write_to_meeting_file`). |
| Testing | 1 | Repo contains no `tests/` directory and no test config in `setup.py`/`requirements.txt`. |
| Packaging | 2 | `setup.py` is functional with a `zoom_cli` console-script entry point, but classifies as Python 2 & 3, has no `python_requires`, no `pyproject.toml`, no extras, and `requirements.txt` includes build tooling (`pyinstaller`, `altgraph`, `macholib`) mixed with runtime deps. |
| Security | 1 | `os.system('open "{}"')` interpolates a user-controlled URL into a shell string (`utils.py:launch_zoommtg_url`); plaintext password storage; bare `except:` swallows errors (`commands.py:_launch_url`, `utils.py:get_meeting_file_contents`); meeting-file write is non-atomic. |
| UX | 3 | Click-based subcommands, sensible defaults via `DefaultGroup`, interactive prompts via PyInquirer. Decent for the small scope. |
| Observability | 1 | No logging; ad-hoc `print` with ANSI escapes; no `--verbose` / `--quiet`; no structured errors. |
| Docs | 2 | README documents the local launch workflow; no API docs, no man page, no examples directory. |
| CI/CD | 1 | No `.github/workflows`, no lint, no release automation; only a `build.sh`. |

Overall maturity: **1.6 / 5** — fine as a personal launcher, far from API-CLI ready.

## 7. Capability gap matrix

| Zoom API area | Current support | Priority | Notes |
|---|---|:---:|---|
| Local `zoommtg://` launcher | Full | — | Keep as a non-API mode. |
| Auth (S2S OAuth + user OAuth) | None | P0 | Foundation; nothing else lights up without it. |
| Meetings CRUD | None | P0 | Most-requested CLI use case (schedule, list, end, delete). |
| Users (list/get/me/settings) | None | P0 | Needed for `me` resolution, multi-user S2S admin flows. |
| Cloud Recordings (list/get/download/delete) | None | P1 | High admin value; large blob downloads need streaming + resume. |
| Reports (past meetings, participants) | None | P1 | Common admin/analytics ask; Heavy tier — needs throttling. |
| Dashboards | None | P2 | Business+ plans only; useful for SREs. |
| Webinars | None | P2 | Big surface; only relevant if user has Webinar license. |
| Phone (call logs, users, queues) | None | P2 | Big revenue surface for orgs on Zoom Phone. |
| Team Chat (channels/messages) | None | P2 | Useful "send message to channel" command. |
| Zoom Rooms | None | P3 | Niche; admin tooling. |
| Contact Center | None | P3 | Specialized; only for CCaaS customers. |
| Devices | None | P3 | Admin-only. |
| Tracking Fields | None | P3 | Convenience for org policies. |
| Groups & Roles | None | P3 | Admin IAM. |
| Billing | None | P3 | Rarely useful from a CLI. |
| SIP Connected Audio | None | P3 | Niche. |
| TSP | None | P3 | Niche. |
| Webhooks (verify + serve) | None | P2 | Optional `zoom webhook serve` to receive/verify locally. |
| Pagination + rate-limit handling | None | P0 | Cross-cutting; required by every list endpoint. |
| OpenAPI-driven typed client | None | P1 | Reduces hand-written boilerplate and drift. |

## 8. Recommended roadmap

### Phase 1 — Hardening of the existing local launcher (no API)
Goal: make today's product safe, testable, and Python-3.10+ ready before adding any HTTP surface.

1. Drop Python 2 classifiers; set `python_requires=">=3.10"`; migrate to `pyproject.toml` (PEP 621) with `setuptools` or `hatchling` backend; split `requirements.txt` into runtime vs. dev/build (`[project.optional-dependencies]`).
2. Replace `os.system('{} "{}"'.format(cmd, url))` with `subprocess.run([cmd, url], check=False)` to remove shell-injection surface (`utils.py:launch_zoommtg_url`, `:is_command_available`).
3. Replace **PyInquirer** (unmaintained, last release 2020, depends on `prompt_toolkit==1.0.14`) with `questionary` or native `click.prompt`. PyInquirer is a known blocker for modern Python.
4. Stop persisting plaintext passwords. Move credentials behind the OS keyring (`keyring` library, Keychain on macOS, libsecret on Linux, Credential Manager on Windows). Keep `meetings.json` for non-secret bookmark metadata only; bump schema version.
5. Replace bare `except:` with typed exceptions (`commands.py:_launch_url`, `utils.py:get_meeting_file_contents`); add `logging` with a `--verbose/-v` flag; remove ad-hoc ANSI color class in favor of `click.style`/`rich`.
6. Atomic file writes: write to `meetings.json.tmp` then `os.replace` to avoid corruption on Ctrl-C.
7. Input validation on URL parsing: prefer `urllib.parse.urlparse` over `str.index("/j/")` slicing — fixes a class of bugs and avoids `IndexError`/`ValueError` masquerading as "could not launch."
8. Add `pytest` + `pytest-cov`; target ≥80% coverage on `commands.py` and `utils.py`. Add `mypy --strict`, `ruff` (lint+format), `pre-commit`.
9. GitHub Actions: matrix on Python 3.10–3.13, macOS + Linux + Windows, jobs for lint/type/test, plus a release job that publishes to PyPI on tag.
10. Ship a real CHANGELOG and a versioning policy (SemVer); move version source-of-truth to a single place (e.g., `zoom_cli/__init__.py:__version__`).

### Phase 2 — Server-to-Server OAuth + first API surface (Meetings, Users, Recordings)
Goal: turn `zoom-cli` into a real Zoom API client without abandoning the local launcher.

1. New top-level subcommand group `zoom api ...` that lives alongside `launch/save/edit/rm/ls`. The non-API local launcher stays the default.
2. Auth subsystem:
   - `zoom auth login` — runs the user-OAuth authorization-code flow with PKCE; persists `refresh_token` in the OS keyring.
   - `zoom auth s2s` — stores `ACCOUNT_ID/CLIENT_ID/CLIENT_SECRET` in the keyring for headless use.
   - `zoom auth status` / `zoom auth logout`.
   - Internal token cache with `exp - 60s` skew; transparent refresh; honor `WWW-Authenticate` on 401.
3. HTTP client: `httpx` (sync + async), shared `Client` with timeouts, `Retry-After` aware retry middleware, pluggable rate-limit limiter (per-tier token bucket).
4. Pagination helper: `paginate(client, path, params)` yielding objects; default `page_size=300`; respect `next_page_token`.
5. Feature subcommands (each with `--json` / `--table` / `--yaml` output):
   - `zoom meetings list [--user me|<id>] [--type scheduled|live|upcoming]` → `GET /users/{userId}/meetings`
   - `zoom meetings get <id>` → `GET /meetings/{meetingId}`
   - `zoom meetings create --topic ... --start ... --duration ... [--password ...]` → `POST /users/me/meetings`
   - `zoom meetings update <id> [--topic ...]` → `PATCH /meetings/{meetingId}`
   - `zoom meetings delete <id>` → `DELETE /meetings/{meetingId}`
   - `zoom meetings end <id>` → `PUT /meetings/{meetingId}/status` `{action:"end"}`
   - `zoom meetings invite <id>` → `GET /meetings/{meetingId}/invitation`
   - `zoom users list [--status ...]` / `zoom users get <id|me>` / `zoom users create ...` / `zoom users delete <id>`
   - `zoom recordings list [--user me|<id>] [--from ... --to ...]` → `GET /users/{userId}/recordings`
   - `zoom recordings get <meetingId>` → `GET /meetings/{meetingId}/recordings`
   - `zoom recordings download <meetingId> [--out DIR]` — streams `download_url` with auth, supports `--resume`
6. Bridge: `zoom save --from-api <meetingId>` to persist an API-discovered meeting into the local store, and `zoom launch <meetingId-or-saved-name>` falls back to API lookup if no local match.
7. Telemetry/observability: `--log-format=json`, `--log-level`, optional `ZOOM_CLI_HTTP_DEBUG=1` to dump redacted request/response.

### Phase 3 — Webinars, Phone, Chat, Reports, Dashboards
Each behind opt-in scopes; users add only what their account supports.

1. `zoom webinars` — list/create/update/delete + registrants/panelists/polls.
2. `zoom phone calls list [--from --to]` → `GET /phone/call_logs`; `zoom phone users list`; `zoom phone queues list`; `zoom phone recordings download <id>`.
3. `zoom chat send --channel <name|id> --text "..."` → `POST /chat/users/me/messages`; `zoom chat channels list`.
4. `zoom reports daily --from --to`, `zoom reports meetings <id>`, `zoom reports participants <id>`, `zoom reports operationlogs --from --to`.
5. `zoom dashboard meetings [--type live|past]`, `zoom dashboard zoomrooms`.
6. `zoom webhook serve --port 8080 --secret-env ZOOM_WEBHOOK_SECRET` — local FastAPI/Starlette receiver that verifies the `x-zm-signature`/`x-zm-request-timestamp` headers (HMAC-SHA256 of `v0:{ts}:{body}`) and handles the `endpoint.url_validation` challenge; logs events to stdout. Useful for local dev tunneled via `cloudflared`/`ngrok`.
7. Generated typed models: pull `openapi.v2.json` at build time and codegen Pydantic v2 models with `datamodel-code-generator`; pin a SHA so drift is intentional.

## 9. Security & correctness findings already visible in the code

1. **Shell-string command construction** in `zoom_cli/utils.py:launch_zoommtg_url`:
   ```
   os.system('{} "{}"'.format(command, url_to_launch))
   ```
   Any `"` or `$` in a saved URL/password is interpolated into the shell. The CLI accepts arbitrary user input via `save --url` and the interactive prompt, then later passes it through `os.system`. Replace with `subprocess.run([command, url_to_launch], check=False)` (no `shell=True`).
2. **Plaintext password storage** in `~/.zoom-cli/meetings.json` (`utils.py:write_to_meeting_file`, `commands.py:_save_url`/`_save_id_password`). File mode is the umask default — readable by any process running as the user. Move secrets to the OS keyring.
3. **Bare `except:`** masks real errors and aids `KeyboardInterrupt` resistance bugs:
   - `commands.py:_launch_url` — silently turns a malformed URL into "Unable to launch given URL."
   - `utils.py:get_meeting_file_contents` — turns any read or JSON error into "no meetings," silently corrupting state on a partial write.
   - `utils.py:dict_to_json_string.dumper` — catches everything during serialization.
   Catch concrete exceptions (`OSError`, `json.JSONDecodeError`, `ValueError`).
4. **PyInquirer is unmaintained** (last release 2020) and pins `prompt_toolkit==1.0.14`, blocking modern `prompt_toolkit` and Python 3.12+ on some platforms. Migrate to `questionary` (modern fork) or `click.prompt`.
5. **Fragile URL parsing** in `commands.py:_launch_name`:
   ```
   id = url[url.index("/j/")+3:min(len(url), url.index("?") if "?" in url else float("inf"))]
   ```
   Will raise `ValueError` if `/j/` is absent (caught only by the outer bare `except` if any), and mishandles fragments, multiple query params, percent-encoded passwords, and `https://*.zoom.us/s/` (personal-link) URLs. Use `urllib.parse.urlparse` + `parse_qs`.
6. **No input validation** on `id`/`password` in `save`. Meeting IDs should be 9–11 digits; passwords have known character-class constraints when going via `zoommtg://` (special chars need URL-encoding via `urllib.parse.quote`).
7. **Non-atomic write** in `utils.py:write_to_meeting_file` — Ctrl-C mid-write leaves a truncated JSON, then the bare `except` in `get_meeting_file_contents` silently returns `{}`, effectively erasing the user's bookmarks.
8. **Mixed runtime + build deps** in `requirements.txt` (`pyinstaller`, `altgraph`, `macholib`); these are pinned by `setup.py` as `install_requires`, forcing every user install to pull build tooling.
9. **Python 2 classifier** in `setup.py` is misleading: PyInquirer + f-strings and modern syntax mean only Python 3 actually works. Remove and add `python_requires=">=3.10"`.
10. **`__version__` duplicated** across `zoom_cli/utils.py` and any future packaging metadata; consolidate or read from package metadata via `importlib.metadata.version`.
11. **`is_command_available` shells out** with `shell=True` and a format-string. Replace with `shutil.which("open")`.
12. **No `--dry-run`** for destructive commands (`rm`, future API `delete`).

## 10. Sources

- Zoom Developer API Reference — https://developers.zoom.us/docs/api/
- Meetings APIs — https://developers.zoom.us/docs/api/meetings/
- Webinars Plus & Events API — https://developers.zoom.us/docs/api/rest/zoom-events-api/
- Users APIs — https://developers.zoom.us/docs/api/users/
- Phone APIs — https://developers.zoom.us/docs/api/phone/
- Chat API methods — https://developers.zoom.us/docs/api/rest/reference/chat/methods/
- Contact Center APIs — https://developers.zoom.us/docs/api/contact-center/
- Rate limits — https://developers.zoom.us/docs/api/rate-limits/
- Using webhooks — https://developers.zoom.us/docs/api/webhooks/
- Server-to-Server OAuth — https://developers.zoom.us/docs/internal-apps/s2s-oauth/
- OAuth 2.0 (user-level) — https://developers.zoom.us/docs/integrations/oauth/
- JWT app type deprecation — https://developers.zoom.us/changelog/platform/jwt-app-type-deprecation/
- Zoom OpenAPI v2 spec — https://github.com/zoom/api/blob/master/openapi.v2.json
- S2S OAuth token utility — https://github.com/zoom/server-to-server-oauth-token
- Webhook sample — https://github.com/zoom/webhook-sample
- prschmid/zoomus — https://github.com/prschmid/zoomus
- pyzoom — https://pypi.org/project/pyzoom/
- zoom-meeting-sdk — https://pypi.org/project/zoom-meeting-sdk/
