"""Zoom Users API helpers.

Reference: https://developers.zoom.us/docs/api/users/

This module is intentionally thin — each function maps to one Zoom
endpoint and returns the raw JSON envelope. We don't wrap responses in
typed dataclasses yet because:

1. The CLI surface is the only consumer right now and it just prints
   selected fields. Boxing into a dataclass adds no value at this stage.
2. A future codegen pass against the OpenAPI spec (issue #22) will
   produce proper types — handwriting them now would just be churn.
"""

from __future__ import annotations

from typing import Any

from zoom_cli.api.client import ApiClient


def get_me(client: ApiClient) -> dict[str, Any]:
    """``GET /users/me`` — return the authenticated user's profile.

    Required scopes: ``user:read:user`` (or any scope that includes it).
    """
    return client.get("/users/me")
