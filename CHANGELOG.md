# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> Bootstrap PR: [#25](https://github.com/jordan8037310/zoom-cli/pull/25) — closes #4, #7, #8 and partially addresses #9, #10.
> Codex review follow-ups (PR #32): closes #34, #35, #36, #37, #38, #39, #40, #41, #42, #43, #44, #45, #46, #47.
> CC security setup (PR #33): adds `.claude/settings.json`, `SECURITY.md`, `LOCAL-SECURITY.md`, `TASKS.md`, and three FACET developer skills.
> Rate-limit + pagination (PR #48): closes #16 (partial — per-tier token bucket tracked at #49). 429/Retry-After backoff with jitter; `paginate()` generator helper; `users.list_users()` as the first paginated endpoint.
> Users CLI surface (PR #50): closes #14 (read-only piece). New `zoom users list` and `zoom users get <user-id>` commands.
> Meetings CLI surface (PR #51): closes #13 (read-only piece). New `zoom meetings list` and `zoom meetings get <meeting-id>` commands; `zoom_cli/api/meetings.py` mirrors the structure of `users.py`.
> Meetings write surface (PR #52): closes #13 (write piece). New `zoom meetings create / update / delete / end` commands. `ApiClient` gains `post`/`patch`/`put`/`delete` convenience wrappers.
> Users write surface (PR #53): closes #14 (write + settings-read piece). New `zoom users create / delete / settings get` commands.
> Recordings surface (PR #54): closes #15. New `zoom recordings list / get / download / delete` commands; `zoom_cli/api/recordings.py`; `ApiClient.stream_download` for atomic streamed downloads.
> User OAuth + PKCE (PR #55): closes #12. New `zoom auth login` 3-legged OAuth flow with loopback callback; `zoom_cli/api/user_oauth.py`; refresh-token storage in keyring service `zoom-cli-user-auth`; extended `auth status` and `auth logout` to cover both surfaces.
> Schema versioning (PR #56): closes #24 (final piece). `meetings.json` now wraps the meetings dict in a `{schema_version, meetings}` envelope; legacy v0 (pre-#24) files read transparently and migrate on first write.
> Per-tier rate limiting (PR #57): closes #49 (follow-up to #16's partial close). `zoom_cli/api/rate_limit.py` with token-bucket + daily counter + endpoint→tier classification; opt-in via `ApiClient(creds, rate_limiter=RateLimiter())`.
> Documentation rewrite (PR #58): closes #23. README rewritten around the two-mode reality (local launcher + REST API), full CLI reference, configuration table, security overview; new `examples/` directory with three runnable scripts.
> Codegen tooling (PR #59): closes #22. New `scripts/codegen.py` wraps `datamodel-code-generator` for Pydantic v2 model generation from Zoom's OpenAPI spec. Optional `[codegen]` extra; output gitignored by default.
> Webhook receiver (PR #60): closes #17. New `zoom webhook serve` command + `zoom_cli/api/webhook.py` with constant-time HMAC verification and the endpoint.url_validation handshake.
> Zoom Phone API (PR #61): closes #18 (read-only piece). New `zoom phone users / call-logs / queues / recordings list/get` commands; `zoom_cli/api/phone.py`; tier mappings extended for `/phone/*` endpoints.
> Zoom Team Chat API (PR #62): closes #19. New `zoom chat channels list` and `zoom chat messages send` commands; `zoom_cli/api/chat.py`.
> Zoom Reports API (PR #63): closes #20. New `zoom reports daily / meetings list / meetings participants / operationlogs list` commands; `zoom_cli/api/reports.py`; tier mappings extended for `/report/*` (HEAVY tier).
> Zoom Dashboard API (PR #64): closes #21. New `zoom dashboard meetings list / get / participants` and `zoom dashboard zoomrooms list / get` commands; `zoom_cli/api/dashboard.py`; tier mappings extended for `/metrics/*` (HEAVY tier). Requires Business+ Zoom plan.
> ApiClient user-OAuth integration (PR #65): completes the user-OAuth story from #12. `ApiClient` now accepts either `S2SCredentials` or `UserOAuthCredentials`; the CLI prefers user-OAuth when both are configured.
> Webhook timestamp-skew enforcement (PR #66): closes the deferred replay-protection piece from #17. `MAX_TIMESTAMP_SKEW_SECONDS = 300` is now actually enforced — old / future-dated deliveries are rejected with 401 even if the signature verifies.
> Phone call recording downloads (PR #67): closes the deferred download piece from #18. New `zoom phone recordings download <recording-id>` chains `get_phone_recording` (for the URL) with `ApiClient.stream_download` (atomic write).
> PyPI release workflow (PR #68): closes the PyPI half of #10. New `.github/workflows/release.yml` builds + publishes on tag push via PyPI Trusted Publishing (OIDC, no token in secrets).
> Users settings update (PR #69): closes the deferred settings-update piece from #14. New `zoom users settings update [user-id] --from-json FILE` rounds out the get → edit → PATCH workflow.
> Codegen `--from-url` (this branch): scripts/codegen.py can now fetch the OpenAPI spec directly instead of requiring a separate `curl` step.
> Meetings create/update `--from-json` (this branch): `zoom meetings create` and `zoom meetings update` now accept a `--from-json FILE` (or `-` for stdin) payload-construction mode. Mutually exclusive with the per-field flags. Use this for `recurrence` and `settings` sub-objects that the field flags don't expose.
> Meeting registrants surface (PR #72): full registrant management — list / add / approve / deny / cancel / questions get / questions update — under `zoom meetings registrants`. First entry in the depth-first push to bring Meetings from ~15% → ~80% of Zoom's documented surface.
> Meeting polls surface (PR #73): list / get / create / update / delete plus past-meeting `results` — under `zoom meetings polls`. Second iteration of the depth-first push.
> Meeting livestream surface (PR #74): get / update RTMP config + start/stop the livestream — under `zoom meetings livestream`. Third iteration of the depth-first push.
> Past instances + invitation + recover (PR #75): `zoom meetings invitation`, `zoom meetings recover`, and a new `zoom meetings past` subgroup with `instances / get / participants`. Fourth iteration of the depth-first push.
> Survey + token + batch register + in-meeting controls (PR #76): `zoom meetings survey [get/update/delete]`, `zoom meetings token`, `zoom meetings registrants batch`, `zoom meetings control`. Fifth iteration of the depth-first push — closes Meetings to ~80% of Zoom's documented surface.
> Users status + password + email + token + permissions (PR #77): `zoom users [activate|deactivate|password|email|token|permissions]`. First iteration of the Users depth-first push (~25% → target ~80%).
> Users schedulers + assistants + presence (PR #78): `zoom users schedulers [list|delete]`, `zoom users assistants [add|delete]`, `zoom users presence [get|set]`. Second iteration of the Users depth-first push.
> Recordings recover + settings + registrants (this branch): `zoom recordings recover`, `zoom recordings settings [get|update]`, `zoom recordings registrants [list|add|approve|deny]`. First iteration of the Recordings depth-first push (~25% → target ~80%).

### Added (post-#15 depth-completion: recover + settings + registrants)
- `zoom recordings recover <meeting-id> [--file-id ID]` — restore trashed recordings (whole meeting or one specific file). Counterpart to `recordings delete` (which trashes by default; recoverable for 30 days). Confirms by default; `--yes` to skip.
- `zoom recordings settings get <meeting-id>` — print recording sharing/permission settings as JSON.
- `zoom recordings settings update <meeting-id> --from-json FILE` — JSON-only because settings nest deep (share_recording / viewer_download / on_demand / password / authentication / etc.). Confirms by default.
- `zoom recordings registrants list <meeting-id> [--status pending|approved|denied]` — paginated TSV of on-demand recording viewer registrations.
- `zoom recordings registrants add <meeting-id>` — register a viewer (per-field flags OR `--from-json`; mutually exclusive). Returns the per-viewer `share_url`.
- `zoom recordings registrants approve|deny <meeting-id> --registrant ID [--registrant ID ...]` — bulk status change. Note: recording registrants only support approve/deny — no `cancel` (unlike meeting registrants). Confirms by default.
- New API helpers: `recordings.recover_recordings`, `recordings.recover_recording_file`, `recordings.get_recording_settings`, `recordings.update_recording_settings`, `recordings.list_recording_registrants` (paginated), `recordings.add_recording_registrant`, `recordings.update_recording_registrant_status`. New pinned-tuple constants `recordings.ALLOWED_REGISTRANT_STATUSES` and `recordings.ALLOWED_REGISTRANT_ACTIONS = ("approve", "deny")`.

### Added (post-#14 depth-completion: schedulers + assistants + presence)
- `zoom users schedulers list <user-id>` — TSV (id / email) of users authorized to schedule meetings on this user's behalf.
- `zoom users schedulers delete <user-id> <scheduler-id|--all>` — revoke one or all. Confirms by default; `--yes` to skip. Mutually-exclusive arg/flag validation.
- `zoom users assistants add <user-id> --email E [--email E ...]` — assign assistants by email. `--from-json FILE` accepts the full body (with IDs) and is mutually exclusive with `--email`.
- `zoom users assistants delete <user-id> <assistant-id|--all>` — revoke one or all. Confirms by default; `--yes` to skip.
- `zoom users presence get <user-id>` — print current chat presence status.
- `zoom users presence set <user-id> <STATUS>` — set presence. STATUS is case-sensitive (Available / Away / Do_Not_Disturb / In_Calendar_Event / Presenting / In_A_Zoom_Meeting / On_A_Call); validated by Click's Choice.
- New API helpers: `users.list_schedulers`, `users.delete_scheduler`, `users.delete_all_schedulers`, `users.add_assistants`, `users.delete_assistant`, `users.delete_all_assistants`, `users.get_presence`, `users.set_presence` (status validated against `ALLOWED_PRESENCE_STATUSES`).

### Added (post-#14 depth-completion: status + password + email + token + permissions)
- `zoom users activate|deactivate <user-id>` — toggle account status. Confirms by default; `--yes` to skip. Same factory pattern as the meeting registrant status verbs.
- `zoom users password <user-id>` — reset password. Reads via `getpass.getpass` — never via argv, never via env var. Asks for confirmation (matches the new vs confirm prompt) before sending. Empty / mismatched passwords abort with exit 1.
- `zoom users email <user-id> <new-email>` — initiate email change. Zoom sends a confirmation link to the new address; the change isn't active until the user clicks. Confirmation prompt surfaces the target email so the operator sees what's about to change.
- `zoom users token <user-id> [--type zak|token|zpk]` — fetch user-level token. Sensitive — anyone with a `zak` can start the user's meetings as them. Flagged in help text + docstring.
- `zoom users permissions <user-id>` — list assigned role + permissions; one-per-line.
- New API helpers: `users.update_user_status` (action validated against `ALLOWED_STATUS_ACTIONS = ("activate", "deactivate")`), `users.update_user_password`, `users.update_user_email`, `users.get_user_token` (validated against `ALLOWED_USER_TOKEN_TYPES = ("zak", "token", "zpk")`), `users.get_user_permissions`.

### Added (post-#13 depth-completion: survey + token + batch + control)
- `zoom meetings survey get|update|delete <meeting-id>` — manage the post-meeting survey shown to attendees. `update --from-json FILE` (JSON-only because surveys nest deep). All mutating verbs confirm by default; `--yes` to skip.
- `zoom meetings token <meeting-id> [--type zak|zpk]` — fetch the start-meeting token (sensitive — anyone with it can start the meeting as the host). Default `zak` mirrors Zoom's own default.
- `zoom meetings registrants batch <meeting-id> --from-json FILE` — bulk-register up to 30 attendees in one call. Returns Zoom's per-attendee join_url array.
- `zoom meetings control <meeting-id> --from-json FILE` — send an in-meeting control event (invite, mute_participants, etc.). Lives in the `/live_meetings` namespace (NOT `/meetings`) — different scopes apply. Confirms by default since these affect a meeting in progress.
- New API helpers: `meetings.get_survey`, `meetings.update_survey`, `meetings.delete_survey`, `meetings.get_token` (validated against `ALLOWED_TOKEN_TYPES = ("zak", "zpk")`), `meetings.batch_register`, `meetings.in_meeting_control`.

### Added (post-#13 depth-completion: past instances + invitation + recover)
- `zoom meetings invitation <meeting-id>` — print the canonical email invitation text Zoom builds for the meeting.
- `zoom meetings recover <meeting-id>` — un-delete a soft-deleted meeting (counterpart to `meetings delete`). Confirms by default; `--yes` to skip.
- `zoom meetings past instances <meeting-id>` — list past occurrences of a recurring meeting (TSV: uuid / start_time).
- `zoom meetings past get <meeting-id-or-uuid>` — past-meeting summary (one-per-line; same shape as `meetings get`).
- `zoom meetings past participants <meeting-id-or-uuid>` — paginated TSV list of attendees who joined a past meeting.
- New API helpers: `meetings.get_invitation`, `meetings.list_past_instances`, `meetings.get_past_meeting`, `meetings.list_past_participants` (paginated), `meetings.recover_meeting`.

### Added (post-#13 depth-completion: livestream)
- `zoom meetings livestream get <meeting-id>` — print RTMP config (stream_url / stream_key / page_url / resolution) one-per-line.
- `zoom meetings livestream update <meeting-id> [--stream-url URL] [--stream-key K] [--page-url URL]` — partial PATCH; rejects empty payload. `--from-json FILE` accepts the full body and is mutually exclusive with the per-field flags.
- `zoom meetings livestream start <meeting-id> [--display-name N] [--active-speaker-name/--no-active-speaker-name] [--from-json FILE]` — confirms by default; `--yes` to skip. Builds the broadcast settings sub-object from flags or accepts the full sub-object as JSON.
- `zoom meetings livestream stop <meeting-id>` — confirms by default; `--yes` to skip. Sends `action=stop` with no settings sub-object.
- New API helpers: `meetings.get_livestream`, `meetings.update_livestream`, `meetings.update_livestream_status` (action validated against `ALLOWED_LIVESTREAM_ACTIONS = ("start", "stop")`).

### Added (post-#13 depth-completion: polls)
- `zoom meetings polls list <meeting-id>` — TSV output (id / title / status / anonymous).
- `zoom meetings polls get <meeting-id> <poll-id>` — raw JSON output (round-trips into `polls update --from-json`).
- `zoom meetings polls create <meeting-id> --from-json FILE` — JSON-only because polls nest deep (questions / answers / right_answers / answer_required) and per-field flags would be unusable.
- `zoom meetings polls update <meeting-id> <poll-id> --from-json FILE` — full PUT replace per Zoom's spec (NOT a merge); confirms by default since omitted fields are dropped.
- `zoom meetings polls delete <meeting-id> <poll-id>` — confirms by default; `--yes` to skip.
- `zoom meetings polls results <meeting-id>` — past-meeting poll results from a different namespace (`/past_meetings/<id>/polls`); JSON output.
- New API helpers: `meetings.list_polls`, `meetings.get_poll`, `meetings.create_poll`, `meetings.update_poll` (PUT semantics), `meetings.delete_poll`, `meetings.list_past_poll_results`.

### Added (post-#13 depth-completion: registrants)
- `zoom meetings registrants list <meeting-id> [--status pending|approved|denied]` — paginated TSV output (id / email / first_name / last_name / status). Default status `pending` mirrors Zoom's own default (the approval queue admins care about).
- `zoom meetings registrants add <meeting-id> --email E --first-name F [--last-name L]` — register an attendee. `--from-json FILE` accepts the full Zoom registration body (custom_questions, address, industry, …); mutually exclusive with the per-field flags.
- `zoom meetings registrants approve|deny|cancel <meeting-id> --registrant ID [--registrant ID ...]` — bulk status change. `--yes` skips the confirmation prompt; otherwise the CLI confirms before mutating.
- `zoom meetings registrants questions get <meeting-id>` — print the registration form's questions as JSON (round-trips cleanly into `questions update`).
- `zoom meetings registrants questions update <meeting-id> --from-json FILE` — replace the registration questions array. Confirms by default; `--yes` to skip.
- New API helpers: `meetings.list_registrants` (paginated), `meetings.add_registrant`, `meetings.update_registrant_status`, `meetings.get_registration_questions`, `meetings.update_registration_questions`. Pinned-tuple constants `ALLOWED_REGISTRANT_STATUSES` and `ALLOWED_REGISTRANT_ACTIONS` mirror the CLI choices.

### Added (post-#13 follow-up)
- `zoom meetings create --from-json FILE` — bypass the per-field flags and POST a full Zoom create-meeting body (settings + recurrence). Validates the file contains a JSON object; rejects scalar / array payloads. Mutually exclusive with `--topic / --type / --start-time / --duration / --timezone / --password / --agenda` (exit 1 with a clear error if both are passed).
- `zoom meetings update <meeting-id> --from-json FILE` — same escape hatch for PATCH. The "nothing to update" guard still applies to the field-flags path; `--from-json` lets the caller send whatever Zoom accepts.

### Changed (post-#22 follow-up)
- `scripts/codegen.py` accepts `--from-url URL` as an alternative to the positional spec path. Mutually exclusive — exactly one source must be provided. Fetches via `httpx` (already a runtime dep, public unauthenticated endpoint), writes to `$TMPDIR/zoom-openapi.*.json`, then runs the existing codegen flow on that tempfile. Failure during fetch surfaces as exit 1 with the underlying error.
- README "Codegen" section updated with the one-step workflow.

### Added (post-#14 follow-up)
- `users.update_user_settings(client, user_id, payload)` — `PATCH /users/<user-id>/settings`. Zoom's PATCH semantics leave omitted fields untouched, so callers can pass any subset.
- `zoom users settings update [user-id] --from-json FILE [--yes] [--dry-run]` — CLI completes the round trip:

  ```bash
  zoom users settings get me > settings.json   # dump
  # edit settings.json
  zoom users settings update me --from-json settings.json   # PATCH back
  ```

  Validates that `--from-json` parses as a JSON object (rejects arrays / scalars). Always confirms unless `--yes` (settings changes can disable security features like waiting rooms / private chat); the prompt surfaces top-level keys being changed so the user sees the scope without scrolling. `--dry-run` previews the parsed payload without calling the API. `--from-json -` reads from stdin, so `... | zoom users settings update --from-json -` works.
- `rate_limit.ENDPOINT_TIERS` adds `PATCH /users/<id>/settings` → `Tier.MEDIUM` (write); the GET stays LIGHT.

### Why round-trip instead of per-field flags
The settings payload has ~50 fields across nested categories (`feature`, `in_meeting`, `email_notification`, `recording`, etc.). Mirroring all of them as flags would be a sprawling surface that drifts whenever Zoom adds a field. The dump-edit-PATCH flow scales to whatever Zoom adds without code changes.

### Added (issue #10, PyPI half)
- `.github/workflows/release.yml` — three-stage workflow:
  1. Build sdist + wheel via `python -m build`.
  2. Verify by installing the wheel into a fresh interpreter and importing `zoom_cli`.
  3. Publish to PyPI via the official `pypa/gh-action-pypi-publish@release/v1` action using **Trusted Publishing (OIDC)** — no `PYPI_API_TOKEN` secret needed.
- Triggers on `git push` to a `v*` tag, **and** on manual `workflow_dispatch` (with a `dry_run` checkbox that skips the upload step — handy for verifying the build before the first real release).
- README "Releases" section documents the one-time PyPI Trusted Publisher setup.

### One-time setup (action required to actually publish)
The workflow lands inert. To activate publishes, on PyPI:
1. Create the `zoom-cli` project (or claim it).
2. PyPI → project Settings → Publishing → Add Trusted Publisher with `Owner=jordan8037310`, `Repo=zoom-cli`, `Workflow=release.yml`, `Environment=pypi`.
3. Tag a release: `git tag vX.Y.Z && git push --tags`.

### Added (post-#18 follow-up)
- `phone.get_phone_recording(client, recording_id)` — `GET /phone/recordings/<id>`. Returns the single recording's metadata including `download_url` and `file_extension`. URL-encodes the path segment.
- `zoom phone recordings download <recording-id> [--out-dir DIR]` — fetches the metadata, then streams the audio file to disk via `ApiClient.stream_download` (atomic tempfile + os.replace from PR #54). Filename convention: `<recording_id>.<file_extension>`. Errors with exit 1 + clear message if the recording has no `download_url` (deleted/trashed).
- `rate_limit.ENDPOINT_TIERS` adds `GET /phone/recordings/<id>` → `Tier.LIGHT` (single-resource read; the listing stays MEDIUM).

### Added (post-#17 follow-up)
- `webhook.is_timestamp_within_skew(timestamp_str, *, max_skew_seconds, now_ms)` — pure helper. Symmetric ±300s default window (rejects old replays AND future-dated spoofs); malformed / missing timestamps return False. Injectable `now_ms` for tests; defaults to `time.time() * 1000`.
- `_make_handler(..., now_ms=None, max_skew_seconds=300)` — handler accepts injectable clock + skew so tests can pin time and bypass the wall clock.
- Webhook handler now runs the timestamp-skew check **before** the signature check (parse failures and ancient timestamps are cheaper to reject than HMAC). All three rejection paths emit a stderr line for debugging.

### Why this matters (security)
Signature alone proves a `(body, timestamp)` pair was signed by someone with the secret — it does **not** prove the delivery is recent. Without timestamp enforcement, an attacker who captured an old signed delivery could replay it indefinitely. The ±300s window matches Zoom's documented tolerance.

### Added (post-#12 follow-up)
- `ApiClient(credentials, ..., on_user_token_rotated=...)` — `credentials` now accepts either `S2SCredentials` or `UserOAuthCredentials`. For user-OAuth, every refresh rotates the persisted refresh_token (Zoom invalidates the old one immediately), and the optional callback fires with the new credentials so the caller can persist them.
- `_load_creds_or_exit()` (CLI) — resolves user-OAuth first, falls back to S2S, then exits with a friendly two-path message if neither is set.
- `_build_api_client(creds)` (CLI) — wires `on_user_token_rotated=auth.save_user_oauth_credentials` automatically for user-OAuth credentials so rotated refresh tokens persist transactionally (mirrors the #35 pattern).
- All 32 `ApiClient(creds)` call sites in `__main__.py` switched to `_build_api_client(creds)` so every API command (users, meetings, recordings, phone, chat, reports, dashboard) works with either auth surface.

### Net effect
After `zoom auth login --client-id ID`, every existing API command (`zoom users me`, `zoom meetings list`, etc.) Just Works with the user-OAuth refresh token. No more "user OAuth is configured but nothing uses it" gap.

### Added (issue #21)
- `zoom_cli/api/dashboard.py` — `list_meetings(client, *, type, from_, to)`, `get_meeting(client, meeting_id)`, `list_meeting_participants(client, meeting_id, *, type)`, `list_zoomrooms(client)`, `get_zoomroom(client, room_id)`. `type` validated against `ALLOWED_MEETING_METRIC_TYPES = ("past", "live", "pastOne")`. URL-encodes meeting_id and room_id.
- CLI:
  - `zoom dashboard meetings list --from --to [--type past|live|pastOne] [--page-size]` — TSV per meeting.
  - `zoom dashboard meetings get <meeting-id>` — JSON dump.
  - `zoom dashboard meetings participants <meeting-id> [--type] [--page-size]` — TSV per participant.
  - `zoom dashboard zoomrooms list [--page-size]` — TSV per room.
  - `zoom dashboard zoomrooms get <room-id>` — JSON dump.
- `rate_limit.ENDPOINT_TIERS` extended with `/metrics/.*` → `Tier.HEAVY` (matches Zoom's published table). Tests cover every endpoint plus an unmapped wildcard.

### Added (issue #20)
- `zoom_cli/api/reports.py` — `get_daily(client, *, year, month)`, `list_meetings_report(client, *, user_id, from_, to, meeting_type, page_size)`, `list_meeting_participants(client, meeting_id, *, page_size)`, `list_operation_logs(client, *, from_, to, category_type, page_size)`. All paginated except `get_daily` (Zoom returns the whole month). URL-encodes `meeting_id` (Zoom UUIDs sometimes contain `/` so this is needed for correctness, not just defense).
- CLI:
  - `zoom reports daily [--year] [--month]` — JSON dump.
  - `zoom reports meetings list --from --to [--user-id] [--type past|pastOne|pastJoined] [--page-size]` — TSV per meeting.
  - `zoom reports meetings participants <meeting-id> [--page-size]` — TSV per participant.
  - `zoom reports operationlogs list --from --to [--category-type] [--page-size]` — TSV per log entry.
- `rate_limit.ENDPOINT_TIERS` now classifies all `/report/*` paths as `Tier.HEAVY` (40/s + 60,000/day cap). Tests pin every endpoint plus a wildcard fallback so an unmapped reports path still ends up HEAVY rather than the MEDIUM default.

### Note
Reports are heavyweight — pass `RateLimiter()` to `ApiClient` for batch use to stay under the 60k/day cap; the `DailyCapExhaustedError` from PR #57 surfaces when you'd otherwise be silently blocked.

### Added (issue #19)
- `zoom_cli/api/chat.py` — `list_channels(client, *, user_id="me", page_size=50)` paginates `GET /chat/users/<id>/channels` (Zoom caps this at 50 not 300); `send_message(client, *, message, to_channel | to_contact, user_id, reply_main_message_id)` posts to `/chat/users/<id>/messages` and validates that exactly one of `to_channel` / `to_contact` is set.
- CLI:
  - `zoom chat channels list [--user-id me] [--page-size N]` — TSV: id\\tname\\ttype.
  - `zoom chat messages send --message TEXT [--to-channel ID | --to-contact EMAIL] [--user-id me] [--reply-to MSG_ID]` — refuses to run if both or neither target is set.
- `rate_limit.ENDPOINT_TIERS` extended for `GET /chat/users/<id>/channels` and `POST /chat/users/<id>/messages` → both MEDIUM. Tests pin both.

### Added (issue #18)
- `zoom_cli/api/phone.py` — `list_phone_users`, `get_phone_user`, `list_call_logs` (account-wide or per-user), `list_call_queues`, `list_phone_recordings` (account-wide or per-user). All paginated via the helper from PR #48; date-filter forwarding for `--from`/`--to` where applicable.
- CLI subgroups under `zoom phone`:
  - `zoom phone users list [--page-size]` (TSV: id\\temail\\textension_number\\tstatus)
  - `zoom phone users get <user-id>` (JSON dump)
  - `zoom phone call-logs list [--user-id] [--from] [--to] [--page-size]` (TSV: id\\tdirection\\tcaller_number\\tcallee_number\\tstart_time\\tduration)
  - `zoom phone queues list [--page-size]` (TSV: id\\tname\\textension_number\\tsite_name)
  - `zoom phone recordings list [--user-id] [--from] [--to] [--page-size]` (TSV: id\\tcaller_number\\tcallee_number\\tdate_time\\tduration)
- `rate_limit.ENDPOINT_TIERS` extended with `/phone/users`, `/phone/users/{id}`, `/phone/users/{id}/call_logs`, `/phone/users/{id}/recordings`, `/phone/call_logs`, `/phone/call_queues`, `/phone/recordings` — single-resource user lookup is LIGHT, everything else MEDIUM.

### Added (issue #17)
- `zoom_cli/api/webhook.py` — pure crypto helpers: `compute_signature(secret_token, timestamp, body)` returns Zoom's `v0=<64-hex>` format; `verify_signature(...)` does constant-time `hmac.compare_digest`; `compute_url_validation_response(secret_token, plain_token)` builds the handshake response. `_make_handler(secret_token, *, sink)` builds a `BaseHTTPRequestHandler` subclass that recognises `endpoint.url_validation` (unsigned by Zoom — special handshake), verifies signed events, rejects tampering with 401 + stderr line, and dumps verified events to the `sink` callable.
- `zoom webhook serve --secret-token TOKEN [--bind 127.0.0.1] [--port 8000]` CLI command. Picks up `ZOOM_WEBHOOK_SECRET` env var. Default `--bind 127.0.0.1` (loopback only) — use `ngrok http 8000` or similar to expose during development.
- README "Webhooks" section in the CLI reference.

### Out of scope (deferred)
- Persistent storage / replay of received events. Stdout is the sink; pipe through `jq`/`tee`/etc. for ad-hoc storage.
- Timestamp-skew rejection (replay protection beyond signature). The `MAX_TIMESTAMP_SKEW_SECONDS = 300` constant is pinned for a follow-up that wires it into the verification path.
- TLS termination — use `ngrok` or another reverse proxy for HTTPS.

### Added (issue #22)
- `scripts/codegen.py` — reproducible wrapper around `datamodel-code-generator` with the project's preferred flag set pinned in code (Pydantic v2, double quotes, standard collections, py3.10+ syntax, enum-as-literal). Supports `--dry-run` for safe inspection, errors with an actionable message if `datamodel-codegen` isn't installed, propagates non-zero exit codes.
- New `[codegen]` optional dependency extra: `pip install -e '.[codegen]'` adds `datamodel-code-generator>=0.25,<1`. Kept out of `[dev]` so contributors who don't need codegen don't pull the heavy dep.
- New `zoom_cli/api/_generated/` placeholder directory (with `.gitkeep`); contents gitignored by default so the generated tree doesn't bloat git history. Teams that want to commit it can remove the `.gitignore` entry.
- README "Codegen (optional, dev tool)" section documenting the workflow.

### Deferred (issue #22 follow-up)
- Bundling the spec in the repo (large, fast-moving — fetch-on-demand is the right model).
- Wiring generated models into existing helpers (`users.py` etc. still return `dict[str, Any]`). Migration is opt-in per endpoint; can land as separate PRs once a developer needs typed access.
- Pre-generating models for the endpoints currently in use. Each developer runs the script.

### Documentation (issue #23)
- **README rewrite** — restructured around the two operational modes (local launcher + Zoom REST API), each with its own quick-start. New "CLI reference" section enumerates every command. New "Configuration" table maps each storage location (`~/.zoom-cli/`, four keyring services, in-memory) to what it holds. Security section links to `SECURITY.md` / `LOCAL-SECURITY.md` and summarises the highlights. Project-layout block updated for the new `api/` modules.
- **`examples/`** (new) — three runnable scripts:
  - `list-active-users.sh` — TSV pipeline: `zoom users list` → `cut`/`sort -u`.
  - `download-recent-recordings.sh` — list-then-download for the last 7 days; uses `awk` to filter the TSV, calls `zoom recordings download` per meeting.
  - `batch-meetings-with-rate-limit.py` — programmatic Python use of `ApiClient` with the per-tier `RateLimiter` for batch automation.

### Added (issue #49)
- `zoom_cli/api/rate_limit.py` — `Tier` enum (LIGHT/MEDIUM/HEAVY/RESOURCE_INTENSIVE) and `TIER_LIMITS` table pinned by tests against Zoom's published caps (80/60/40/20 per-second; HEAVY + RESOURCE_INTENSIVE additionally cap at 60,000/day). `TokenBucket` and `DailyCounter` primitives take injectable `clock` / `sleep` / `day_clock` for deterministic tests. `RateLimiter` composes the per-tier buckets and daily counters; `acquire(method, path)` blocks (or raises `DailyCapExhaustedError`) and returns the classified tier.
- `tier_for(method, path)` — pinned regex table maps the endpoints currently in use; unmapped paths fall back to `Tier.MEDIUM`. Strips a leading `/v1`/`/v2`/etc. version prefix so callers can pass either relative or full paths.
- `ApiClient` gains `rate_limiter: RateLimiter | None = None` constructor arg. Default `None` = no proactive limiting (existing behaviour unchanged; the 429/Retry-After backoff from #16 still catches reactive throttling). Pass an instance for batch / long-running automation:

  ```python
  from zoom_cli.api.rate_limit import RateLimiter
  client = ApiClient(creds, rate_limiter=RateLimiter())
  ```

### Added (issue #24, schema versioning piece)
- `zoom_cli/utils.py` — `SCHEMA_VERSION = 1` constant; new `UnknownSchemaVersionError` for files written by a newer CLI; new `_detect_envelope()` helper that handles both v0 (flat dict at root) and v1 (wrapped envelope).
- `write_to_meeting_file` now emits `{schema_version: 1, meetings: {...}}`. Atomic-write semantics from PR #27 are unchanged.
- `get_meeting_file_contents` transparently reads both formats — pure read does NOT migrate the file (no surprise modifications). The first `zoom save`/`edit`/`rm` after a CLI upgrade migrates v0 → v1 opportunistically.
- A v1 file written by a future `schema_version > 1` CLI raises `UnknownSchemaVersionError` with a clear "Upgrade zoom-cli to read it" message — fail-loud rather than silently dropping fields the future version added.
- A corrupt envelope (`meetings` not a dict) returns empty rather than crashing — fail-soft so the user can re-save.
- `tests/conftest.py` `write_meetings` fixture now writes the v1 envelope to match what the CLI itself produces.

### Added (issue #12)
- `zoom_cli/api/user_oauth.py` — PKCE primitives (`_pkce_pair`, `_random_state`), `build_authorize_url`, `exchange_code_for_tokens`, `refresh_user_tokens`, end-to-end `run_pkce_flow` with loopback HTTP server + browser launch + state-mismatch CSRF check + 5-minute timeout.
- `zoom_cli.auth.UserOAuthCredentials` (refresh_token + client_id) plus `save_user_oauth_credentials` / `load_user_oauth_credentials` / `clear_user_oauth_credentials` / `has_user_oauth_credentials`. Best-effort transactional save (mirrors #35 pattern); load propagates `NoKeyringError` (#41 pattern). Stored under service `zoom-cli-user-auth`, distinct from `zoom-cli-auth` (S2S) so `zoom auth logout` can clear one without touching the other.
- `zoom auth login --client-id <id> [--port N] [--timeout S] [--no-browser]` CLI command. Picks up `ZOOM_USER_CLIENT_ID` env var. Prints the auth URL before launching the browser so headless / SSH sessions can paste it. `--no-browser` skips the launch (useful when the URL just needs to be shared).

### Changed (issue #12)
- `zoom auth status` now reports both surfaces (S2S and User OAuth) with separate "configured / not configured" lines plus the right "run X to configure" hint for each.
- `zoom auth logout` clears both stores (S2S and User OAuth) and reports both clears.

### Added (issue #15)
- `zoom recordings list [--user-id me] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--page-size N]` — paginates `GET /users/<user-id>/recordings`. TSV output: `uuid\tmeeting_id\ttopic\tstart_time\tfile_count`.
- `zoom recordings get <meeting-id>` — `GET /meetings/<meeting-id>/recordings`. Pretty-printed JSON for piping through `jq`.
- `zoom recordings download <meeting-id> [--out-dir DIR] [--file-type TYPE ...]` — fetches the meeting's recording metadata, then streams each file to disk via the new `ApiClient.stream_download`. Atomic per-file writes (sibling tempfile + `os.replace`) so a network drop never leaves half a file at the destination. `--file-type` is repeatable to filter to MP4/M4A/CHAT/etc. Filename convention: `<meeting_id>-<recording_type>.<ext>` (collision-disambiguated by recording_id).
- `zoom recordings delete <meeting-id> [--file-id ID] [--action trash|delete] [--yes] [--dry-run]` — `DELETE /meetings/<id>/recordings` (or `/recordings/<file-id>` if `--file-id`). Always confirms unless `--yes`; louder prompt for `--action delete` (permanent) than the default `trash` (recoverable for 30 days).
- API helpers: `recordings.list_recordings / get_recordings / delete_recordings / delete_recording_file`. `ALLOWED_DELETE_ACTIONS` constant pinned by tests.
- `ApiClient.stream_download(url, dest_path)` — bearer-authenticated streamed GET with atomic tempfile-then-replace write semantics. Single-shot 401 retry with force-refresh (same policy as `request`); 429 on Zoom's download host is uncommon enough that it's deferred to issue #49.

### Added (issue #14, write piece)
- `zoom users create --email ... --type N [--first-name ...] [--last-name ...] [--display-name ...] [--password ...] [--action create|autoCreate|custCreate|ssoCreate]` — `POST /users`. Builds Zoom's `{action, user_info}` envelope from flat flags.
- `zoom users delete <user-id> [--action disassociate|delete] [--transfer-email ...] [--transfer-meetings] [--transfer-recordings] [--transfer-webinars] [--yes] [--dry-run]` — `DELETE /users/<user-id>`. Always confirms unless `--yes` (deleting a user has high blast radius); the prompt phrasing is louder for `--action delete` ("Permanently delete ... cannot be undone") than for the default disassociate.
- `zoom users settings get [user-id]` — `GET /users/<user-id>/settings`. Default user is `me`. Output is the raw JSON payload, pretty-printed; pipe through `jq` for filtering.
- API helpers: `users.create_user(client, user_info, *, action="create")`, `users.delete_user(client, user_id, *, action, transfer_*)`, `users.get_user_settings(client, user_id="me")`. Constants `ALLOWED_CREATE_ACTIONS` and `ALLOWED_DELETE_ACTIONS` pinned by tests.

### Deferred (issue #14 follow-up)
- `zoom users settings update` — the settings payload has ~50 fields across nested categories; needs design before exposing as flags. Use `ApiClient.patch` directly until then.

### Added (issue #13, write piece)
- `zoom meetings create --topic ... [--type] [--start-time] [--duration] [--timezone] [--password] [--agenda] [--user-id me]` — `POST /users/<user-id>/meetings`. Topic is required; everything else is optional. Recurrence + settings sub-objects are out of scope here (use the API directly until a follow-up adds flags).
- `zoom meetings update <meeting-id> [--topic ...] [...]` — `PATCH /meetings/<id>`. Partial update; only flags you pass are sent. Errors out with exit 1 if no fields were provided.
- `zoom meetings delete <meeting-id> [--yes] [--dry-run] [--notify-host] [--notify-registrants]` — `DELETE /meetings/<id>`. Confirmation-flow mirrors `zoom rm` (positional id is scripted-friendly; `--yes` skips confirm; `--dry-run` previews without calling the API; notification flags default to silent delete).
- `zoom meetings end <meeting-id> [--yes]` — `PUT /meetings/<id>/status` with `action=end`. **Always** confirms unless `--yes` because kicking live participants is irreversible.
- `ApiClient.post(...)`, `.patch(...)`, `.put(...)`, `.delete(...)` convenience wrappers (the underlying `request()` already supported all methods; the wrappers just save callers from typing the method string).
- `meetings.create_meeting`, `update_meeting`, `delete_meeting`, `end_meeting` API helpers.

### Added (issue #14, read-only)
- New `zoom users list` CLI command — paginates `GET /users` via the helper from PR #48. Tab-separated output (`user_id\temail\ttype\tstatus`) with a header line; pipes cleanly into `cut`/`awk`/`column`. `--status active|inactive|pending` (default `active`) and `--page-size` (1–300, default 300) flags.
- New `zoom users get <user-id>` CLI command — `GET /users/<user-id>`. Accepts a Zoom user ID or email address. Same field-per-line output format as `zoom users me`.
- Refactored `__main__.py`: extracted `_print_user_profile`, `_load_creds_or_exit`, and `_exit_on_api_error` helpers so the three users commands share their boilerplate. The original `zoom users me` behaviour is unchanged.

### Deferred (issue #14 follow-up)
- `zoom users create` / `delete` / `settings` (write commands). Each needs separate confirmation-flow design (e.g. `--yes` for delete, scope warnings for create) so they're better as a separate PR.



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
