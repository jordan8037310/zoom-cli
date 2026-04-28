"""Zoom Phone API helpers (closes #18).

Reference: https://developers.zoom.us/docs/api/phone/

Endpoints covered:

  list_phone_users(client, *, page_size=300) -> Iterator[dict]
      → GET /phone/users (paginated)

  get_phone_user(client, user_id) -> dict
      → GET /phone/users/{user_id}

  list_call_logs(client, *, user_id=None, from_=None, to=None,
                 page_size=300) -> Iterator[dict]
      → GET /phone/call_logs (account-wide if user_id is None)
      → GET /phone/users/{user_id}/call_logs (per-user when set)

  list_call_queues(client, *, page_size=300) -> Iterator[dict]
      → GET /phone/call_queues

  list_phone_recordings(client, *, user_id=None, from_=None, to=None,
                        page_size=300) -> Iterator[dict]
      → GET /phone/recordings (account-wide)
      → GET /phone/users/{user_id}/recordings (per-user)

Same conventions as the meetings/users/recordings modules: each function
maps 1:1 to a Zoom endpoint, percent-encodes path segments, returns the
parsed JSON envelope (or yields items via the paginate() helper for
list endpoints). Higher-level concerns (CLI flags, output format) live
in __main__.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from zoom_cli.api.client import ApiClient
from zoom_cli.api.pagination import DEFAULT_PAGE_SIZE, paginate


def list_phone_users(
    client: ApiClient,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /phone/users`` — yield phone-licensed users across all pages.

    Required scopes: ``phone:read:list_users``.
    """
    return paginate(
        client,
        "/phone/users",
        item_key="users",
        page_size=page_size,
    )


def get_phone_user(client: ApiClient, user_id: str) -> dict[str, Any]:
    """``GET /phone/users/{user_id}`` — single phone user's profile.

    ``user_id`` accepts a Zoom user ID or email address. Required scopes:
    ``phone:read:user``.
    """
    return client.get(f"/phone/users/{quote(user_id, safe='')}")


def list_call_logs(
    client: ApiClient,
    *,
    user_id: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """Yield call log entries.

    If ``user_id`` is ``None`` (default), uses the account-level endpoint
    ``/phone/call_logs``. If set, uses the per-user
    ``/phone/users/{user_id}/call_logs``.

    ``from_`` / ``to`` are ISO-8601 dates (YYYY-MM-DD); the server-side
    cap is 1 month per request — callers walking longer ranges should
    chunk in 30-day windows.

    Required scopes: ``phone:read:call_log:admin`` (account) or
    ``phone:read:call_log`` (per-user).
    """
    path = (
        f"/phone/users/{quote(user_id, safe='')}/call_logs"
        if user_id is not None
        else "/phone/call_logs"
    )
    params: dict[str, Any] = {}
    if from_ is not None:
        params["from"] = from_
    if to is not None:
        params["to"] = to
    return paginate(
        client,
        path,
        item_key="call_logs",
        params=params,
        page_size=page_size,
    )


def list_call_queues(
    client: ApiClient,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /phone/call_queues`` — yield call queues across all pages.

    Required scopes: ``phone:read:list_call_queues:admin``.
    """
    return paginate(
        client,
        "/phone/call_queues",
        item_key="call_queues",
        page_size=page_size,
    )


def get_phone_recording(client: ApiClient, recording_id: str) -> dict[str, Any]:
    """``GET /phone/recordings/{recording_id}`` — single recording metadata.

    Returns the recording's envelope including ``download_url``,
    ``file_extension``, ``duration``, etc. The CLI ``zoom phone
    recordings download`` chains this with
    :meth:`ApiClient.stream_download` to fetch the actual audio file.

    URL-encodes the path segment.

    Required scopes: ``phone:read:call_recording`` (or admin
    equivalent).
    """
    return client.get(f"/phone/recordings/{quote(recording_id, safe='')}")


def list_phone_recordings(
    client: ApiClient,
    *,
    user_id: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """Yield Zoom Phone call recordings.

    Account-wide when ``user_id`` is ``None``; per-user otherwise.

    Required scopes: ``phone:read:list_call_recordings:admin`` or
    ``phone:read:list_user_recordings``.
    """
    path = (
        f"/phone/users/{quote(user_id, safe='')}/recordings"
        if user_id is not None
        else "/phone/recordings"
    )
    params: dict[str, Any] = {}
    if from_ is not None:
        params["from"] = from_
    if to is not None:
        params["to"] = to
    return paginate(
        client,
        path,
        item_key="recordings",
        params=params,
        page_size=page_size,
    )
