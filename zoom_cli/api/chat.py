"""Zoom Team Chat API helpers (closes #19).

Reference: https://developers.zoom.us/docs/api/chat/

Endpoints covered:

  list_channels(client, *, user_id="me", page_size=300) -> Iterator[dict]
      → GET /chat/users/{user_id}/channels (paginated)

  send_message(client, *, message, to_channel=None, to_contact=None,
               user_id="me", reply_main_message_id=None) -> dict
      → POST /chat/users/{user_id}/messages

Same conventions as the meetings/users/recordings/phone modules: each
function maps 1:1 to a Zoom endpoint, percent-encodes path segments,
returns the parsed JSON envelope (or yields items via paginate()).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from zoom_cli.api.client import ApiClient
from zoom_cli.api.pagination import DEFAULT_PAGE_SIZE, paginate


def list_channels(
    client: ApiClient,
    *,
    user_id: str = "me",
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /chat/users/{user_id}/channels`` — yield the user's channels.

    Required scopes: ``chat_channel:read`` (self) or
    ``chat_channel:read:admin`` (other users).
    """
    return paginate(
        client,
        f"/chat/users/{quote(user_id, safe='')}/channels",
        item_key="channels",
        page_size=page_size,
    )


def send_message(
    client: ApiClient,
    *,
    message: str,
    to_channel: str | None = None,
    to_contact: str | None = None,
    user_id: str = "me",
    reply_main_message_id: str | None = None,
) -> dict[str, Any]:
    """``POST /chat/users/{user_id}/messages`` — send a chat message.

    Exactly one of ``to_channel`` (channel ID) or ``to_contact`` (email
    address) must be set; passing both or neither raises ``ValueError``.

    ``reply_main_message_id`` makes this a reply to a thread root; omit
    for a top-level message.

    Returns the new message's metadata (includes ``id`` for follow-ups).

    Required scopes: ``chat_message:write`` (self) or
    ``chat_message:write:admin`` (other users).
    """
    if (to_channel is None) == (to_contact is None):
        raise ValueError(
            "Exactly one of to_channel or to_contact must be set (got both or neither)."
        )

    payload: dict[str, Any] = {"message": message}
    if to_channel is not None:
        payload["to_channel"] = to_channel
    else:
        payload["to_contact"] = to_contact
    if reply_main_message_id is not None:
        payload["reply_main_message_id"] = reply_main_message_id

    return client.post(
        f"/chat/users/{quote(user_id, safe='')}/messages",
        json=payload,
    )
