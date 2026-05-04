"""Zoom Meetings API helpers.

Reference: https://developers.zoom.us/docs/api/meetings/

Mirrors the structure of :mod:`zoom_cli.api.users`:

- :func:`get_meeting` / :func:`list_meetings` — read surface.
- :func:`create_meeting` / :func:`update_meeting` /
  :func:`delete_meeting` / :func:`end_meeting` — write surface.

Each function maps 1:1 to a Zoom endpoint and returns the parsed JSON
envelope (or ``{}`` for 204 No Content responses). Higher-level concerns
(confirmation prompts, --dry-run, --yes) live in the CLI layer in
``__main__.py``; the API layer is intentionally side-effect-only.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from zoom_cli.api.client import ApiClient
from zoom_cli.api.pagination import DEFAULT_PAGE_SIZE, paginate

#: Allowed values for ``list_meetings(meeting_type=...)``.
#: Mirrors Zoom's ``type`` query param. The server also accepts
#: ``previous_meetings`` (snake_case) — kept for callers that already use
#: it. ``upcoming_meetings`` is Zoom's newer alias for ``upcoming``.
ALLOWED_LIST_TYPES: tuple[str, ...] = (
    "scheduled",
    "live",
    "upcoming",
    "upcoming_meetings",
    "previous_meetings",
)


def get_meeting(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /meetings/{meeting_id}`` — return one meeting's details.

    ``meeting_id`` accepts either an int (numeric Zoom meeting ID) or a
    str. The path segment is percent-encoded so caller-supplied IDs
    cannot inject path/query metacharacters even if a future CLI threads
    user input straight through.

    Required scopes: ``meeting:read:meeting`` (or any scope that
    includes it).
    """
    return client.get(f"/meetings/{quote(str(meeting_id), safe='')}")


def create_meeting(
    client: ApiClient, payload: dict[str, Any], *, user_id: str = "me"
) -> dict[str, Any]:
    """``POST /users/{user_id}/meetings`` — schedule a new meeting.

    ``payload`` is the full Zoom create-meeting body (``topic``, ``type``,
    ``start_time``, etc.). The CLI ``zoom meetings create`` builds this
    from individual flags; programmatic callers can pass any subset Zoom
    accepts. Returns the created meeting's full detail object (Zoom
    responds with the new resource, including ``id`` and ``join_url``).

    Required scopes: ``meeting:write:meeting`` (or admin equivalent for
    creating on another user's behalf).
    """
    return client.post(f"/users/{quote(user_id, safe='')}/meetings", json=payload)


def update_meeting(
    client: ApiClient, meeting_id: str | int, payload: dict[str, Any]
) -> dict[str, Any]:
    """``PATCH /meetings/{meeting_id}`` — partial update.

    ``payload`` should contain only the fields being changed; Zoom's
    PATCH semantics leave omitted fields untouched. Returns ``{}`` (Zoom
    responds with ``204 No Content``).

    Required scopes: ``meeting:write:meeting``.
    """
    return client.patch(f"/meetings/{quote(str(meeting_id), safe='')}", json=payload)


def delete_meeting(
    client: ApiClient,
    meeting_id: str | int,
    *,
    schedule_for_reminder: bool = False,
    cancel_meeting_reminder: bool = False,
) -> dict[str, Any]:
    """``DELETE /meetings/{meeting_id}`` — remove the meeting.

    ``schedule_for_reminder``: send the host a reminder email about the
    deletion. ``cancel_meeting_reminder``: send registrants a cancellation
    notice. Both default ``False`` (silent delete) so scripted use is
    quiet by default.

    Returns ``{}`` (Zoom responds with ``204 No Content``).

    Required scopes: ``meeting:write:meeting``.
    """
    return client.delete(
        f"/meetings/{quote(str(meeting_id), safe='')}",
        params={
            "schedule_for_reminder": "true" if schedule_for_reminder else "false",
            "cancel_meeting_reminder": "true" if cancel_meeting_reminder else "false",
        },
    )


def end_meeting(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``PUT /meetings/{meeting_id}/status`` with ``action=end`` — kick
    all participants and end an in-progress meeting.

    Returns ``{}`` (Zoom responds with ``204 No Content``). The CLI
    requires explicit confirmation before calling this — kicking
    participants mid-meeting is disruptive enough that ``--yes`` is the
    only way to skip the prompt.

    Required scopes: ``meeting:write:meeting``.
    """
    return client.put(
        f"/meetings/{quote(str(meeting_id), safe='')}/status",
        json={"action": "end"},
    )


def list_meetings(
    client: ApiClient,
    *,
    user_id: str = "me",
    meeting_type: str = "scheduled",
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /users/{user_id}/meetings`` — yield meetings across all pages.

    Args:
        client: Authenticated :class:`ApiClient`.
        user_id: Whose meetings to list. Default ``"me"`` (the
            authenticated principal). Pass a Zoom user ID or email for
            any other user the caller has scope to see.
        meeting_type: Zoom's ``type`` filter; one of
            :data:`ALLOWED_LIST_TYPES`. Default ``"scheduled"``.
        page_size: Items per page; see
            :data:`~zoom_cli.api.pagination.DEFAULT_PAGE_SIZE`. The
            ``/users/{userId}/meetings`` endpoint accepts up to 300.

    Yields:
        One meeting dict per record. Lazy — additional pages are fetched
        only as the caller iterates.

    Required scopes: ``meeting:read:list_meetings`` (or finer-grained
    equivalent for the listed user).
    """
    if meeting_type not in ALLOWED_LIST_TYPES:
        raise ValueError(
            f"meeting_type must be one of {ALLOWED_LIST_TYPES!r}, got {meeting_type!r}"
        )
    return paginate(
        client,
        f"/users/{quote(user_id, safe='')}/meetings",
        item_key="meetings",
        params={"type": meeting_type},
        page_size=page_size,
    )


# ---- registrants surface (Zoom Webinars-style registration on regular --
# meetings; required when the meeting is set to ``registration_type``) ----

#: Allowed values for ``list_registrants(status=...)``. Mirrors Zoom's
#: registrant_status filter. Default ``"pending"`` matches Zoom's own
#: default — the bucket most callers care about (admins approving sign-ups).
ALLOWED_REGISTRANT_STATUSES: tuple[str, ...] = ("pending", "approved", "denied")

#: Allowed values for ``update_registrant_status(action=...)``.
#: ``approve`` / ``deny`` move a registrant in or out of the attendee
#: list; ``cancel`` revokes a previously-approved registration (Zoom
#: emails the cancellation if the meeting has notifications enabled).
ALLOWED_REGISTRANT_ACTIONS: tuple[str, ...] = ("approve", "deny", "cancel")


def list_registrants(
    client: ApiClient,
    meeting_id: str | int,
    *,
    status: str = "pending",
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /meetings/{meeting_id}/registrants`` — yield registrants.

    Args:
        client: Authenticated :class:`ApiClient`.
        meeting_id: Numeric Zoom meeting ID.
        status: One of :data:`ALLOWED_REGISTRANT_STATUSES`. Default
            ``"pending"`` (Zoom's own default — the approval queue).
        page_size: Items per page; see
            :data:`~zoom_cli.api.pagination.DEFAULT_PAGE_SIZE`.

    Yields:
        One registrant dict per record.

    Required scopes: ``meeting:read:meeting`` (or finer-grained
    ``meeting:read:list_registrants``).
    """
    if status not in ALLOWED_REGISTRANT_STATUSES:
        raise ValueError(f"status must be one of {ALLOWED_REGISTRANT_STATUSES!r}, got {status!r}")
    return paginate(
        client,
        f"/meetings/{quote(str(meeting_id), safe='')}/registrants",
        item_key="registrants",
        params={"status": status},
        page_size=page_size,
    )


def add_registrant(
    client: ApiClient, meeting_id: str | int, payload: dict[str, Any]
) -> dict[str, Any]:
    """``POST /meetings/{meeting_id}/registrants`` — register an attendee.

    ``payload`` must contain at minimum ``email`` and ``first_name``;
    Zoom accepts the full registration form (``last_name``, ``address``,
    ``city``, ``country``, ``phone``, ``industry``, custom_questions, …).

    Returns Zoom's response object including ``registrant_id``,
    ``join_url`` (with the registration token baked in), and the
    deduced ``id``. The CLI surfaces ``join_url`` since that's the
    actionable thing to send to the attendee.

    Required scopes: ``meeting:write:registrant``.
    """
    return client.post(f"/meetings/{quote(str(meeting_id), safe='')}/registrants", json=payload)


def update_registrant_status(
    client: ApiClient,
    meeting_id: str | int,
    *,
    action: str,
    registrant_ids: list[str],
) -> dict[str, Any]:
    """``PUT /meetings/{meeting_id}/registrants/status`` — bulk-update.

    Args:
        client: Authenticated :class:`ApiClient`.
        meeting_id: Numeric Zoom meeting ID.
        action: One of :data:`ALLOWED_REGISTRANT_ACTIONS`.
        registrant_ids: Zoom registrant IDs (the ``id`` field, not the
            registrant's email). Must be non-empty.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Refusing an empty ``registrant_ids`` here turns a silent no-op into
    a fast local error — easier to debug than "the API call returned
    success but nothing changed."

    Required scopes: ``meeting:write:registrant``.
    """
    if action not in ALLOWED_REGISTRANT_ACTIONS:
        raise ValueError(f"action must be one of {ALLOWED_REGISTRANT_ACTIONS!r}, got {action!r}")
    if not registrant_ids:
        raise ValueError("registrant_ids must contain at least one ID")
    return client.put(
        f"/meetings/{quote(str(meeting_id), safe='')}/registrants/status",
        json={"action": action, "registrants": [{"id": rid} for rid in registrant_ids]},
    )


def get_registration_questions(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /meetings/{meeting_id}/registrants/questions`` — fetch the
    registration form schema (standard + custom questions).

    Returns the full questions envelope so the caller can round-trip it
    through ``update_registration_questions`` after editing.

    Required scopes: ``meeting:read:meeting``.
    """
    return client.get(f"/meetings/{quote(str(meeting_id), safe='')}/registrants/questions")


def update_registration_questions(
    client: ApiClient, meeting_id: str | int, payload: dict[str, Any]
) -> dict[str, Any]:
    """``PATCH /meetings/{meeting_id}/registrants/questions`` — replace
    the registration form's questions.

    Note: Zoom's "PATCH" here is closer to a PUT — the ``questions``
    array is replaced wholesale, not merged. Round-trip through
    ``get_registration_questions`` to pick up the existing shape, edit,
    then submit.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``meeting:write:meeting``.
    """
    return client.patch(
        f"/meetings/{quote(str(meeting_id), safe='')}/registrants/questions",
        json=payload,
    )


# ---- polls surface (in-meeting Q&A; structured single-/multi-/matching --
# question shapes — payload is complex enough that the CLI is JSON-only) --


def list_polls(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /meetings/{meeting_id}/polls`` — return the poll envelope.

    Not paginated: Zoom returns the full poll set inline (typically a
    handful of polls per meeting). The caller gets back the raw envelope
    so the ``total_records`` field is available for downstream display.

    Required scopes: ``meeting:read:meeting``.
    """
    return client.get(f"/meetings/{quote(str(meeting_id), safe='')}/polls")


def get_poll(client: ApiClient, meeting_id: str | int, poll_id: str) -> dict[str, Any]:
    """``GET /meetings/{meeting_id}/polls/{poll_id}`` — one poll's detail.

    Required scopes: ``meeting:read:meeting``.
    """
    return client.get(
        f"/meetings/{quote(str(meeting_id), safe='')}/polls/{quote(poll_id, safe='')}"
    )


def create_poll(
    client: ApiClient, meeting_id: str | int, payload: dict[str, Any]
) -> dict[str, Any]:
    """``POST /meetings/{meeting_id}/polls`` — add a poll.

    ``payload`` is the full Zoom poll body (``title``, ``poll_type``,
    ``anonymous``, and a ``questions`` array of question dicts with
    nested ``answers`` / ``right_answers`` / ``answer_required``).

    Returns the created poll's full detail object.

    Required scopes: ``meeting:write:meeting``.
    """
    return client.post(f"/meetings/{quote(str(meeting_id), safe='')}/polls", json=payload)


def update_poll(
    client: ApiClient,
    meeting_id: str | int,
    poll_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """``PUT /meetings/{meeting_id}/polls/{poll_id}`` — full replace.

    Note Zoom's poll update is a PUT (full replace), not a PATCH —
    omitted fields are dropped. Round-trip via :func:`get_poll` first
    to pick up the existing shape, edit, then submit.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``meeting:write:meeting``.
    """
    return client.put(
        f"/meetings/{quote(str(meeting_id), safe='')}/polls/{quote(poll_id, safe='')}",
        json=payload,
    )


def delete_poll(client: ApiClient, meeting_id: str | int, poll_id: str) -> dict[str, Any]:
    """``DELETE /meetings/{meeting_id}/polls/{poll_id}`` — remove a poll.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``meeting:write:meeting``.
    """
    return client.delete(
        f"/meetings/{quote(str(meeting_id), safe='')}/polls/{quote(poll_id, safe='')}"
    )


def list_past_poll_results(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /past_meetings/{meeting_id}/polls`` — poll RESULTS (not
    config) for a meeting that has already ended.

    Different namespace from the live polls endpoints: results live
    under ``/past_meetings``, not ``/meetings``. Same resource shape
    (questions with per-answer breakdowns).

    Required scopes: ``meeting:read:meeting``.
    """
    return client.get(f"/past_meetings/{quote(str(meeting_id), safe='')}/polls")


# ---- livestream surface (RTMP livestream config + start/stop) ----------

#: Allowed values for ``update_livestream_status(action=...)``. Zoom only
#: supports ``start`` / ``stop`` here; pause/resume aren't real actions
#: at this endpoint despite the broadcast UI suggesting otherwise.
ALLOWED_LIVESTREAM_ACTIONS: tuple[str, ...] = ("start", "stop")


def get_livestream(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /meetings/{meeting_id}/livestream`` — fetch RTMP config.

    Returns ``{stream_url, stream_key, page_url, ...}`` as Zoom holds
    them. The ``stream_key`` field is sensitive (anyone with it can push
    video to the destination); the CLI surfaces it but reminds the
    caller to redact when sharing.

    Required scopes: ``meeting:read:meeting``.
    """
    return client.get(f"/meetings/{quote(str(meeting_id), safe='')}/livestream")


def update_livestream(
    client: ApiClient, meeting_id: str | int, payload: dict[str, Any]
) -> dict[str, Any]:
    """``PATCH /meetings/{meeting_id}/livestream`` — set RTMP config.

    ``payload`` should contain ``stream_url``, ``stream_key``, and
    ``page_url``. Zoom's PATCH leaves omitted fields untouched.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``meeting:write:meeting``.
    """
    return client.patch(f"/meetings/{quote(str(meeting_id), safe='')}/livestream", json=payload)


def update_livestream_status(
    client: ApiClient,
    meeting_id: str | int,
    *,
    action: str,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``PATCH /meetings/{meeting_id}/livestream/status`` — start or stop.

    Args:
        client: Authenticated :class:`ApiClient`.
        meeting_id: Numeric Zoom meeting ID.
        action: One of :data:`ALLOWED_LIVESTREAM_ACTIONS`.
        settings: Broadcast settings (display_name, active_speaker_name,
            …). Required for ``action="start"``; ignored / omitted for
            ``action="stop"``.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``meeting:update:livestream`` (or admin equivalent).
    """
    if action not in ALLOWED_LIVESTREAM_ACTIONS:
        raise ValueError(f"action must be one of {ALLOWED_LIVESTREAM_ACTIONS!r}, got {action!r}")
    body: dict[str, Any] = {"action": action}
    if settings is not None:
        body["settings"] = settings
    return client.patch(f"/meetings/{quote(str(meeting_id), safe='')}/livestream/status", json=body)


# ---- past instances + invitation + past-meeting summary/participants + --
# ---- recover (soft-deleted) ---------------------------------------------


def get_invitation(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /meetings/{meeting_id}/invitation`` — fetch the canonical
    email invitation text for a meeting.

    Returns ``{invitation: str}``. Useful for "give me the email body to
    paste into Outlook" workflows.

    Required scopes: ``meeting:read:meeting``.
    """
    return client.get(f"/meetings/{quote(str(meeting_id), safe='')}/invitation")


def list_past_instances(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /past_meetings/{meeting_id}/instances`` — list past
    occurrences of a recurring meeting.

    Not paginated: Zoom returns the full instance list inline. Each
    instance includes a ``uuid`` and ``start_time`` — the uuid is the
    handle for ``get_past_meeting`` and ``list_past_participants``.

    Required scopes: ``meeting:read:meeting``.
    """
    return client.get(f"/past_meetings/{quote(str(meeting_id), safe='')}/instances")


def get_past_meeting(client: ApiClient, meeting_id_or_uuid: str | int) -> dict[str, Any]:
    """``GET /past_meetings/{meeting_id}`` — summary for a meeting that
    already ended.

    The path segment accepts either the numeric meeting ID or a meeting
    instance UUID (from ``list_past_instances``). For UUIDs that contain
    ``/`` Zoom requires double-encoding; we single-encode here and let
    callers double-encode upstream if needed (the conservative default).

    Required scopes: ``meeting:read:meeting``.
    """
    return client.get(f"/past_meetings/{quote(str(meeting_id_or_uuid), safe='')}")


def list_past_participants(
    client: ApiClient,
    meeting_id_or_uuid: str | int,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /past_meetings/{meeting_id}/participants`` — yield
    participants who joined a past meeting.

    Same UUID/ID semantics as :func:`get_past_meeting`. Paginated via
    ``next_page_token`` like every other paginated endpoint here.

    Required scopes: ``meeting:read:meeting`` (or
    ``dashboard:read:list_meeting_participants`` for the live dashboard
    equivalent).
    """
    return paginate(
        client,
        f"/past_meetings/{quote(str(meeting_id_or_uuid), safe='')}/participants",
        item_key="participants",
        params={},
        page_size=page_size,
    )


def recover_meeting(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``PUT /meetings/{meeting_id}/status`` with ``action=recover`` —
    restore a soft-deleted meeting.

    Counterpart to :func:`end_meeting` (action=end) and a recovery path
    for :func:`delete_meeting` (which soft-deletes by default; Zoom keeps
    the meeting recoverable for a window).

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``meeting:write:meeting``.
    """
    return client.put(
        f"/meetings/{quote(str(meeting_id), safe='')}/status",
        json={"action": "recover"},
    )
