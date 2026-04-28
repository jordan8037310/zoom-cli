"""Zoom Cloud Recordings API helpers.

Reference: https://developers.zoom.us/docs/api/cloud-recording/

Endpoints covered:

  list_recordings(client, *, user_id="me", from_=None, to=None,
                  page_size=DEFAULT_PAGE_SIZE)
      → GET /users/{user_id}/recordings (paginated)

  get_recordings(client, meeting_id)
      → GET /meetings/{meeting_id}/recordings

  delete_recordings(client, meeting_id, *, action="trash")
      → DELETE /meetings/{meeting_id}/recordings

  delete_recording_file(client, meeting_id, recording_id, *, action="trash")
      → DELETE /meetings/{meeting_id}/recordings/{recording_id}

Downloads use :meth:`zoom_cli.api.client.ApiClient.stream_download`
directly — the download URL on the recording_file object isn't a normal
JSON endpoint.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from zoom_cli.api.client import ApiClient
from zoom_cli.api.pagination import DEFAULT_PAGE_SIZE, paginate

#: Allowed values for ``delete_recordings(..., action=...)``. ``trash``
#: (default) moves the recording to Zoom's trash (recoverable for 30
#: days); ``delete`` is a permanent, immediate delete.
ALLOWED_DELETE_ACTIONS: tuple[str, ...] = ("trash", "delete")


def get_recordings(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /meetings/{meeting_id}/recordings`` — return all recording
    files for a single meeting.

    The returned envelope contains the meeting's metadata plus a
    ``recording_files`` array (each entry has ``id``, ``file_type``,
    ``file_extension``, ``file_size``, ``download_url``,
    ``recording_type``).

    Required scopes: ``recording:read:recording`` (or any scope that
    includes it).
    """
    return client.get(f"/meetings/{quote(str(meeting_id), safe='')}/recordings")


def list_recordings(
    client: ApiClient,
    *,
    user_id: str = "me",
    from_: str | None = None,
    to: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /users/{user_id}/recordings`` — yield recorded meetings
    across all pages.

    Args:
        client: Authenticated :class:`ApiClient`.
        user_id: Whose recordings to list. Default ``"me"``.
        from_: ISO date (YYYY-MM-DD) lower bound on meeting start.
            Zoom's parameter name is just ``from``, but Python reserves
            that, so the kwarg is ``from_``.
        to: ISO date upper bound on meeting start.
        page_size: Items per page; see
            :data:`~zoom_cli.api.pagination.DEFAULT_PAGE_SIZE`.

    Yields:
        One meeting dict per recorded meeting (each contains a
        ``recording_files`` array with the actual files).

    Required scopes: ``recording:read:list_user_recordings``.
    """
    params: dict[str, Any] = {}
    if from_ is not None:
        params["from"] = from_
    if to is not None:
        params["to"] = to
    return paginate(
        client,
        f"/users/{quote(user_id, safe='')}/recordings",
        item_key="meetings",
        params=params,
        page_size=page_size,
    )


def delete_recordings(
    client: ApiClient,
    meeting_id: str | int,
    *,
    action: str = "trash",
) -> dict[str, Any]:
    """``DELETE /meetings/{meeting_id}/recordings`` — delete ALL
    recordings for a meeting.

    ``action="trash"`` (default) is recoverable; ``action="delete"`` is
    permanent. Returns ``{}`` (Zoom responds with ``204 No Content``).

    Required scopes: ``recording:write:recording``.
    """
    if action not in ALLOWED_DELETE_ACTIONS:
        raise ValueError(f"action must be one of {ALLOWED_DELETE_ACTIONS!r}, got {action!r}")
    return client.delete(
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings",
        params={"action": action},
    )


def delete_recording_file(
    client: ApiClient,
    meeting_id: str | int,
    recording_id: str,
    *,
    action: str = "trash",
) -> dict[str, Any]:
    """``DELETE /meetings/{meeting_id}/recordings/{recording_id}`` —
    delete a single recording file (one entry of the recording_files
    array).

    Same ``action`` semantics as :func:`delete_recordings`.

    Required scopes: ``recording:write:recording``.
    """
    if action not in ALLOWED_DELETE_ACTIONS:
        raise ValueError(f"action must be one of {ALLOWED_DELETE_ACTIONS!r}, got {action!r}")
    return client.delete(
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings/"
        f"{quote(str(recording_id), safe='')}",
        params={"action": action},
    )
