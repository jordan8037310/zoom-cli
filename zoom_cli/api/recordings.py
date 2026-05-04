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


# ---- depth-completion: recover + settings + registrants ----------------

#: Allowed values for ``list_recording_registrants(status=...)``.
#: Same shape as meeting registrants — pending is the default (the bucket
#: admins approve from).
ALLOWED_REGISTRANT_STATUSES: tuple[str, ...] = ("pending", "approved", "denied")

#: Allowed values for ``update_recording_registrant_status(action=...)``.
#: Note: recording registrants do NOT support ``cancel`` (unlike meeting
#: registrants — Zoom's recording-share approval flow is just yes/no).
ALLOWED_REGISTRANT_ACTIONS: tuple[str, ...] = ("approve", "deny")


def recover_recordings(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``PUT /meetings/{meeting_id}/recordings/status`` with
    ``action=recover`` — restore all of a meeting's trashed recordings.

    Counterpart to :func:`delete_recordings` with ``action="trash"``
    (Zoom keeps trashed recordings recoverable for 30 days).

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``recording:write:recording``.
    """
    return client.put(
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings/status",
        json={"action": "recover"},
    )


def recover_recording_file(
    client: ApiClient,
    meeting_id: str | int,
    recording_id: str,
) -> dict[str, Any]:
    """``PUT /meetings/{meeting_id}/recordings/{recording_id}/status``
    with ``action=recover`` — restore one trashed recording file.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``recording:write:recording``.
    """
    return client.put(
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings/"
        f"{quote(str(recording_id), safe='')}/status",
        json={"action": "recover"},
    )


def get_recording_settings(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /meetings/{meeting_id}/recordings/settings`` — fetch
    recording sharing/permission settings.

    Returns the settings envelope (share_recording, viewer_download,
    on_demand, password, recording_authentication, etc.).

    Required scopes: ``recording:read:recording``.
    """
    return client.get(f"/meetings/{quote(str(meeting_id), safe='')}/recordings/settings")


def update_recording_settings(
    client: ApiClient, meeting_id: str | int, payload: dict[str, Any]
) -> dict[str, Any]:
    """``PATCH /meetings/{meeting_id}/recordings/settings`` — partial
    update to recording sharing/permission settings.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``recording:write:recording``.
    """
    return client.patch(
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings/settings",
        json=payload,
    )


def list_recording_registrants(
    client: ApiClient,
    meeting_id: str | int,
    *,
    status: str = "pending",
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /meetings/{meeting_id}/recordings/registrants`` — yield
    registrants who requested access to the on-demand recording.

    Args:
        client: Authenticated :class:`ApiClient`.
        meeting_id: Numeric Zoom meeting ID.
        status: One of :data:`ALLOWED_REGISTRANT_STATUSES`. Default
            ``"pending"``.
        page_size: Items per page.

    Required scopes: ``recording:read:recording``.
    """
    if status not in ALLOWED_REGISTRANT_STATUSES:
        raise ValueError(f"status must be one of {ALLOWED_REGISTRANT_STATUSES!r}, got {status!r}")
    return paginate(
        client,
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings/registrants",
        item_key="registrants",
        params={"status": status},
        page_size=page_size,
    )


def add_recording_registrant(
    client: ApiClient,
    meeting_id: str | int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """``POST /meetings/{meeting_id}/recordings/registrants`` — register
    a viewer for the on-demand recording.

    Returns Zoom's response with the registrant id and ``share_url`` —
    the actionable thing to send to the viewer.

    Required scopes: ``recording:write:recording``.
    """
    return client.post(
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings/registrants",
        json=payload,
    )


def update_recording_registrant_status(
    client: ApiClient,
    meeting_id: str | int,
    *,
    action: str,
    registrant_ids: list[str],
) -> dict[str, Any]:
    """``PUT /meetings/{meeting_id}/recordings/registrants/status`` —
    bulk-update registrant approval status.

    Args:
        client: Authenticated :class:`ApiClient`.
        meeting_id: Numeric Zoom meeting ID.
        action: One of :data:`ALLOWED_REGISTRANT_ACTIONS`. Recording
            registrants only support approve/deny — no cancel verb.
        registrant_ids: Zoom registrant IDs (must be non-empty).

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``recording:write:recording``.
    """
    if action not in ALLOWED_REGISTRANT_ACTIONS:
        raise ValueError(f"action must be one of {ALLOWED_REGISTRANT_ACTIONS!r}, got {action!r}")
    if not registrant_ids:
        raise ValueError("registrant_ids must contain at least one ID")
    return client.put(
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings/registrants/status",
        json={
            "action": action,
            "registrants": [{"id": rid} for rid in registrant_ids],
        },
    )


# ---- depth-completion: analytics + registrant questions + archive ------


def get_analytics_summary(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /past_meetings/{meeting_id}/recordings/analytics_summary`` —
    aggregated viewer metrics (view count, average watch time, etc.) for
    a past meeting's recording.

    Lives under /past_meetings (not /meetings) — Zoom's namespace
    convention for after-the-fact data. Requires Business+ Zoom plan.

    Required scopes: ``recording:read:recording``.
    """
    return client.get(
        f"/past_meetings/{quote(str(meeting_id), safe='')}/recordings/analytics_summary"
    )


def get_analytics_details(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /past_meetings/{meeting_id}/recordings/analytics_details`` —
    per-viewer breakdown of who watched, when, and for how long.

    Same Business+ requirement as :func:`get_analytics_summary`.

    Required scopes: ``recording:read:recording``.
    """
    return client.get(
        f"/past_meetings/{quote(str(meeting_id), safe='')}/recordings/analytics_details"
    )


def get_recording_registration_questions(
    client: ApiClient, meeting_id: str | int
) -> dict[str, Any]:
    """``GET /meetings/{meeting_id}/recordings/registrants/questions`` —
    fetch the recording-registration form schema (standard + custom).

    Returns the full questions envelope so the caller can round-trip it
    through :func:`update_recording_registration_questions`.

    Required scopes: ``recording:read:recording``.
    """
    return client.get(
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings/registrants/questions"
    )


def update_recording_registration_questions(
    client: ApiClient, meeting_id: str | int, payload: dict[str, Any]
) -> dict[str, Any]:
    """``PATCH /meetings/{meeting_id}/recordings/registrants/questions``
    — replace the recording-registration form's questions.

    Same wholesale-replace semantics as the meetings registrants
    questions endpoint — round-trip via the get first.

    Required scopes: ``recording:write:recording``.
    """
    return client.patch(
        f"/meetings/{quote(str(meeting_id), safe='')}/recordings/registrants/questions",
        json=payload,
    )


def list_archive_files(
    client: ApiClient,
    *,
    from_: str | None = None,
    to: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /archive_files`` — yield archive files (Business+ archiving
    feature) across all pages.

    Args:
        client: Authenticated :class:`ApiClient`.
        from_: ISO date (YYYY-MM-DD) lower bound on archive date.
        to: ISO date upper bound.
        page_size: Items per page; see :data:`DEFAULT_PAGE_SIZE`.

    Yields:
        One archive_file dict per record.

    Required scopes: ``recording:read:archive_file:admin``.
    """
    params: dict[str, Any] = {}
    if from_ is not None:
        params["from"] = from_
    if to is not None:
        params["to"] = to
    return paginate(
        client,
        "/archive_files",
        item_key="archive_files",
        params=params,
        page_size=page_size,
    )


def get_archive_file(client: ApiClient, file_id: str) -> dict[str, Any]:
    """``GET /archive_files/{file_id}`` — fetch one archive file's
    metadata + per-format download URLs.

    Required scopes: ``recording:read:archive_file:admin``.
    """
    return client.get(f"/archive_files/{quote(file_id, safe='')}")


def delete_archive_file(client: ApiClient, file_id: str) -> dict[str, Any]:
    """``DELETE /archive_files/{file_id}`` — permanently remove an
    archive file. No trash/recover step here (unlike standard
    recordings).

    Required scopes: ``recording:write:archive_file:admin``.
    """
    return client.delete(f"/archive_files/{quote(file_id, safe='')}")
