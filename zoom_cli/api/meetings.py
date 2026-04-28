"""Zoom Meetings API helpers.

Reference: https://developers.zoom.us/docs/api/meetings/

Mirrors the structure of :mod:`zoom_cli.api.users`:

- :func:`get_meeting` is the durable single-meeting helper, paralleling
  :func:`zoom_cli.api.users.get_user`.
- :func:`list_meetings` paginates ``GET /users/<user_id>/meetings`` via
  the helper from :mod:`zoom_cli.api.pagination`.

The write surface (``create``, ``update``, ``delete``, ``end``) is a
follow-up — it needs confirmation-flow design (mirror ``zoom rm``) before
the CLI surface can land safely.
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
