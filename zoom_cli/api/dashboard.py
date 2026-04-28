"""Zoom Dashboard / Metrics API helpers (closes #21).

Reference: https://developers.zoom.us/docs/api/dashboards/

Requires Business+ plan on the Zoom account. Helpers return raw JSON
envelopes / yield items via the paginate() helper, like the other API
modules. Tier classification: all ``/metrics/*`` paths sit on Zoom's
HEAVY tier (40/s + 60,000/day) per the published rate-limit table.

Endpoints covered:

  list_meetings(client, *, type="past", from_, to, page_size=300)
      → GET /metrics/meetings (paginated)

  get_meeting(client, meeting_id) -> dict
      → GET /metrics/meetings/{meeting_id}

  list_meeting_participants(client, meeting_id, *, type="past",
                            page_size=300)
      → GET /metrics/meetings/{meeting_id}/participants (paginated)

  list_zoomrooms(client, *, page_size=300) -> Iterator[dict]
      → GET /metrics/zoomrooms (paginated)

  get_zoomroom(client, room_id) -> dict
      → GET /metrics/zoomrooms/{zoomroom_id}

``type`` controls live-vs-past selection on the metrics endpoints:
``past`` (default), ``live``, or ``pastOne``. Mirrors the Zoom enum.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from zoom_cli.api.client import ApiClient
from zoom_cli.api.pagination import DEFAULT_PAGE_SIZE, paginate

#: Allowed values for ``list_meetings(type=...)`` / ``list_meeting_participants``.
ALLOWED_MEETING_METRIC_TYPES: tuple[str, ...] = ("past", "live", "pastOne")


def list_meetings(
    client: ApiClient,
    *,
    type: str = "past",
    from_: str,
    to: str,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /metrics/meetings`` — paginated dashboard meetings list.

    ``from_`` and ``to`` are ISO-8601 dates and required by Zoom.
    ``type`` is one of :data:`ALLOWED_MEETING_METRIC_TYPES`. Required
    scopes: ``dashboard:read:list_meetings``.
    """
    if type not in ALLOWED_MEETING_METRIC_TYPES:
        raise ValueError(f"type must be one of {ALLOWED_MEETING_METRIC_TYPES!r}, got {type!r}")
    return paginate(
        client,
        "/metrics/meetings",
        item_key="meetings",
        params={"type": type, "from": from_, "to": to},
        page_size=page_size,
    )


def get_meeting(client: ApiClient, meeting_id: str | int) -> dict[str, Any]:
    """``GET /metrics/meetings/{meeting_id}`` — single meeting metrics.

    URL-encodes the path segment (Zoom UUIDs sometimes contain ``/``).
    Required scopes: ``dashboard:read:meeting``.
    """
    return client.get(f"/metrics/meetings/{quote(str(meeting_id), safe='')}")


def list_meeting_participants(
    client: ApiClient,
    meeting_id: str | int,
    *,
    type: str = "past",
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /metrics/meetings/{meeting_id}/participants`` — paginated.

    Required scopes: ``dashboard:read:meeting_participant``.
    """
    if type not in ALLOWED_MEETING_METRIC_TYPES:
        raise ValueError(f"type must be one of {ALLOWED_MEETING_METRIC_TYPES!r}, got {type!r}")
    return paginate(
        client,
        f"/metrics/meetings/{quote(str(meeting_id), safe='')}/participants",
        item_key="participants",
        params={"type": type},
        page_size=page_size,
    )


def list_zoomrooms(
    client: ApiClient,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /metrics/zoomrooms`` — paginated Zoom Rooms metrics list.

    Required scopes: ``dashboard:read:list_zoomrooms``.
    """
    return paginate(
        client,
        "/metrics/zoomrooms",
        item_key="zoom_rooms",
        page_size=page_size,
    )


def get_zoomroom(client: ApiClient, room_id: str) -> dict[str, Any]:
    """``GET /metrics/zoomrooms/{room_id}`` — single Zoom Room metrics.

    Required scopes: ``dashboard:read:zoomroom``.
    """
    return client.get(f"/metrics/zoomrooms/{quote(room_id, safe='')}")
