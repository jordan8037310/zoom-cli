"""Pagination helper for Zoom REST endpoints.

Most Zoom list endpoints return a payload shaped like::

    {
      "page_size": 30,
      "next_page_token": "abc...",
      "users": [ {...}, {...}, ... ]
    }

An empty ``next_page_token`` means "no more pages." :func:`paginate` walks
the cursor for you and yields each item across all pages, so callers can
write straightforward generator pipelines instead of pagination boilerplate.

Closes #16 (partial) — the per-tier token-bucket rate limiter is a
follow-up; this module is the pagination half of that issue.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from zoom_cli.api.client import ApiClient

#: Default items per page. Zoom caps vary per endpoint (commonly 300, some
#: are 100 or 30); pass a lower ``page_size`` for endpoints with smaller
#: caps. Higher values minimize round-trips when the caller iterates the
#: full result.
DEFAULT_PAGE_SIZE = 300


def paginate(
    client: ApiClient,
    path: str,
    *,
    item_key: str,
    params: dict[str, Any] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """Yield each item from a paginated Zoom endpoint across all pages.

    Args:
        client: Authenticated :class:`~zoom_cli.api.client.ApiClient`.
        path: Endpoint path (relative to the API base — e.g. ``"/users"``).
        item_key: The key in each response that holds the page's items
            (``"users"`` for ``/users``, ``"meetings"`` for ``/meetings``,
            etc.). Required because Zoom uses different keys per endpoint.
        params: Base query parameters merged into every page request.
        page_size: Items per page. See :data:`DEFAULT_PAGE_SIZE`.

    Yields:
        Each item dict, in the order Zoom returns them. The generator
        terminates when the server returns an empty ``next_page_token``.

    Each request goes through :meth:`ApiClient.request`, so 401 token
    refresh and 429 / Retry-After backoff happen transparently. A
    :class:`~zoom_cli.api.client.ZoomApiError` from any single page
    propagates immediately and stops iteration.

    The generator is lazy — pages are fetched on demand as the caller
    consumes items. Materialise into a list with ``list(paginate(...))``
    if you need all results before processing.
    """
    page_params = dict(params or {})
    page_params["page_size"] = page_size
    next_page_token = ""

    while True:
        page_params["next_page_token"] = next_page_token
        page = client.get(path, params=page_params)
        # `.get(item_key, [])` rather than `[item_key]` — empty pages
        # (zero items) return either an empty list or the key omitted
        # entirely depending on endpoint. Both are valid "no items here."
        yield from page.get(item_key, [])
        next_page_token = page.get("next_page_token", "") or ""
        if not next_page_token:
            return
