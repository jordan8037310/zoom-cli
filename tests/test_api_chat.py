"""Tests for zoom_cli.api.chat — Team Chat endpoint helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from zoom_cli.api import chat


def test_list_channels_default_user_me() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"channels": [], "next_page_token": ""}

    list(chat.list_channels(fake_client))

    assert fake_client.get.call_args[0][0] == "/chat/users/me/channels"


def test_list_channels_specific_user_url_encoded() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"channels": [], "next_page_token": ""}

    list(chat.list_channels(fake_client, user_id="alice@example.com"))

    assert fake_client.get.call_args[0][0] == "/chat/users/alice%40example.com/channels"


def test_list_channels_walks_pagination_cursor() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"channels": [{"id": "c1"}], "next_page_token": "tok-2"},
        {"channels": [{"id": "c2"}, {"id": "c3"}], "next_page_token": ""},
    ]

    result = list(chat.list_channels(fake_client))

    assert result == [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]


def test_send_message_to_channel_builds_payload() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {"id": "msg-123"}

    result = chat.send_message(fake_client, message="hello", to_channel="ch-1")

    fake_client.post.assert_called_once_with(
        "/chat/users/me/messages",
        json={"message": "hello", "to_channel": "ch-1"},
    )
    assert result == {"id": "msg-123"}


def test_send_message_to_contact_builds_payload() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {"id": "msg-456"}

    chat.send_message(fake_client, message="hi", to_contact="bob@example.com")

    body = fake_client.post.call_args[1]["json"]
    assert body == {"message": "hi", "to_contact": "bob@example.com"}


def test_send_message_includes_reply_id_when_set() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {}

    chat.send_message(
        fake_client,
        message="reply",
        to_channel="ch-1",
        reply_main_message_id="parent-msg-id",
    )

    body = fake_client.post.call_args[1]["json"]
    assert body["reply_main_message_id"] == "parent-msg-id"


def test_send_message_omits_reply_id_when_none() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {}

    chat.send_message(fake_client, message="x", to_channel="ch-1")

    body = fake_client.post.call_args[1]["json"]
    assert "reply_main_message_id" not in body


def test_send_message_url_encodes_user_id() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {}

    chat.send_message(fake_client, message="x", to_channel="ch-1", user_id="alice@example.com")

    assert fake_client.post.call_args[0][0] == "/chat/users/alice%40example.com/messages"


def test_send_message_rejects_both_targets() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="Exactly one"):
        chat.send_message(
            fake_client,
            message="x",
            to_channel="ch-1",
            to_contact="bob@example.com",
        )


def test_send_message_rejects_neither_target() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="Exactly one"):
        chat.send_message(fake_client, message="x")
