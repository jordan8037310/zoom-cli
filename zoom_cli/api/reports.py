"""Zoom Reports API helpers (closes #20).

Reference: https://developers.zoom.us/docs/api/reports/

Endpoints covered:

  get_daily(client, *, year=None, month=None) -> dict
      → GET /report/daily (single page; returns the whole month)

  list_meetings_report(client, *, user_id=None, from_, to,
                       meeting_type=None, page_size=300) -> Iterator[dict]
      → GET /report/users/{user_id}/meetings (paginated; per-user)
      OR GET /report/meetings (paginated; account-wide when user_id is None)

  list_meeting_participants(client, meeting_id, *, page_size=300) -> Iterator[dict]
      → GET /report/meetings/{meeting_id}/participants (paginated)

  list_operation_logs(client, *, from_, to, category_type=None,
                      page_size=300) -> Iterator[dict]
      → GET /report/operationlogs (paginated)

All Reports endpoints sit on Zoom's HEAVY rate-limit tier (40/s,
60,000/day) — see :mod:`zoom_cli.api.rate_limit` for the classification.
``from_``/``to`` are ISO-8601 dates (Zoom's parameter name is just
``from`` but Python reserves it).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from zoom_cli.api.client import ApiClient
from zoom_cli.api.pagination import DEFAULT_PAGE_SIZE, paginate


def get_daily(
    client: ApiClient,
    *,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    """``GET /report/daily`` — daily account usage for one month.

    Default (no year/month) returns the current month per Zoom's API
    default. Pass ``year``/``month`` for a specific historical month.
    Not paginated — Zoom returns the whole month in one envelope.

    Required scopes: ``report:read:admin``.
    """
    params: dict[str, Any] = {}
    if year is not None:
        params["year"] = year
    if month is not None:
        params["month"] = month
    return client.get("/report/daily", params=params or None)


def list_meetings_report(
    client: ApiClient,
    *,
    user_id: str | None = None,
    from_: str,
    to: str,
    meeting_type: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """Yield meeting report entries.

    If ``user_id`` is set, hits the per-user endpoint
    ``/report/users/{user_id}/meetings``; otherwise the account-wide
    ``/report/meetings``.

    ``from_`` and ``to`` are ISO-8601 dates and **required** by Zoom.
    ``meeting_type`` filters server-side (e.g. ``past``, ``pastOne``,
    ``pastJoined``); omit to include all.

    Required scopes: ``report:read:admin``.
    """
    path = (
        f"/report/users/{quote(user_id, safe='')}/meetings"
        if user_id is not None
        else "/report/meetings"
    )
    params: dict[str, Any] = {"from": from_, "to": to}
    if meeting_type is not None:
        params["type"] = meeting_type
    return paginate(
        client,
        path,
        item_key="meetings",
        params=params,
        page_size=page_size,
    )


def list_meeting_participants(
    client: ApiClient,
    meeting_id: str | int,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /report/meetings/{meeting_id}/participants`` — paginated.

    The ``meeting_id`` is the meeting's UUID **or** numeric ID. Zoom
    treats both interchangeably here. URL-encoded so a UUID containing
    ``/`` (Zoom UUIDs sometimes do) doesn't break the path.

    Required scopes: ``report:read:admin``.
    """
    return paginate(
        client,
        f"/report/meetings/{quote(str(meeting_id), safe='')}/participants",
        item_key="participants",
        page_size=page_size,
    )


def list_operation_logs(
    client: ApiClient,
    *,
    from_: str,
    to: str,
    category_type: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /report/operationlogs`` — paginated admin operation log.

    ``from_`` / ``to`` are ISO-8601 dates and required.
    ``category_type`` filters by Zoom's category enum (``user``,
    ``account``, ``billing``, ``zoom_rooms``, etc.); omit for all.

    Required scopes: ``report:read:admin``.
    """
    params: dict[str, Any] = {"from": from_, "to": to}
    if category_type is not None:
        params["category_type"] = category_type
    return paginate(
        client,
        "/report/operationlogs",
        item_key="operation_logs",
        params=params,
        page_size=page_size,
    )
