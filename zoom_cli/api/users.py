"""Zoom Users API helpers.

Reference: https://developers.zoom.us/docs/api/users/

This module is intentionally thin — each function maps to one Zoom
endpoint and returns the raw JSON envelope. We don't wrap responses in
typed dataclasses yet because:

1. The CLI surface is the only consumer right now and it just prints
   selected fields. Boxing into a dataclass adds no value at this stage.
2. A future codegen pass against the OpenAPI spec (issue #22) will
   produce proper types — handwriting them now would just be churn.

API shape:
    :func:`get_user` is the durable helper, taking a ``user_id`` (default
    ``"me"`` — the authenticated principal). :func:`get_me` is a thin
    alias kept for the CLI ``zoom users me`` command (closes #36 — Codex
    #14 flagged that hardcoding the implicit "me" principal would make
    later target-user commands awkward).

Out of scope here, deferred to issue #14:
- ``GET /users`` listing with pagination.
- ``--json`` flag for raw output.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from zoom_cli.api.client import ApiClient


def get_user(client: ApiClient, user_id: str = "me") -> dict[str, Any]:
    """``GET /users/{user_id}`` — return the requested user's profile.

    Pass ``user_id="me"`` (the default) for the authenticated principal,
    or a specific Zoom user ID / email. The path segment is percent-
    encoded so caller-supplied IDs cannot inject query/path metacharacters
    even if a future CLI threads user input straight through.

    Required scopes: ``user:read:user``.
    """
    return client.get(f"/users/{quote(user_id, safe='')}")


def get_me(client: ApiClient) -> dict[str, Any]:
    """``GET /users/me`` — alias for :func:`get_user` with ``user_id="me"``.

    Kept for the ``zoom users me`` CLI command and any external callers
    that imported it from PR #31. Prefer :func:`get_user` in new code.
    """
    return get_user(client, "me")
