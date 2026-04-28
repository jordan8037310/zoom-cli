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
