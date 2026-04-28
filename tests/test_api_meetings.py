"""Tests for zoom_cli.api.meetings — Meetings endpoint helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from zoom_cli.api import meetings


def test_get_meeting_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"id": 123, "topic": "Daily standup"}

    result = meetings.get_meeting(fake_client, 123)

    fake_client.get.assert_called_once_with("/meetings/123")
    assert result == {"id": 123, "topic": "Daily standup"}


def test_get_meeting_accepts_string_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    meetings.get_meeting(fake_client, "98765")

    fake_client.get.assert_called_once_with("/meetings/98765")


def test_get_meeting_url_encodes_special_chars() -> None:
    """Defense-in-depth: even if a future caller passes untrusted input,
    path metacharacters can't break out of the segment."""
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    meetings.get_meeting(fake_client, "evil/../admin?x=1")

    arg = fake_client.get.call_args[0][0]
    assert "/.." not in arg
    assert "?" not in arg
    assert "%2F" in arg


def test_list_meetings_default_user_is_me() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(meetings.list_meetings(fake_client))

    fake_client.get.assert_called_once_with(
        "/users/me/meetings",
        params={"type": "scheduled", "page_size": 300, "next_page_token": ""},
    )


def test_list_meetings_walks_pagination_cursor() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"meetings": [{"id": 1}, {"id": 2}], "next_page_token": "tok-2"},
        {"meetings": [{"id": 3}], "next_page_token": ""},
    ]

    result = list(meetings.list_meetings(fake_client))

    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert fake_client.get.call_count == 2


def test_list_meetings_forwards_user_id_and_type() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(meetings.list_meetings(fake_client, user_id="user-42", meeting_type="upcoming"))

    call = fake_client.get.call_args_list[0]
    assert call[0][0] == "/users/user-42/meetings"
    assert call[1]["params"]["type"] == "upcoming"


def test_list_meetings_url_encodes_user_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(meetings.list_meetings(fake_client, user_id="alice@example.com"))

    call_path = fake_client.get.call_args_list[0][0][0]
    assert call_path == "/users/alice%40example.com/meetings"


@pytest.mark.parametrize("bad_type", ["bogus", "", "deleted", "scheduled "])
def test_list_meetings_rejects_unknown_type(bad_type: str) -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="meeting_type"):
        list(meetings.list_meetings(fake_client, meeting_type=bad_type))


def test_allowed_list_types_constant_pinned() -> None:
    """Future renames would silently change CLI behaviour — pin the set."""
    assert "scheduled" in meetings.ALLOWED_LIST_TYPES
    assert "live" in meetings.ALLOWED_LIST_TYPES
    assert "upcoming" in meetings.ALLOWED_LIST_TYPES
    assert "previous_meetings" in meetings.ALLOWED_LIST_TYPES


# ---- write surface (closes #13 write piece) -----------------------------


def test_create_meeting_posts_to_user_endpoint() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {"id": 999, "join_url": "https://zoom.us/j/999"}

    payload = {"topic": "T", "type": 2, "duration": 30}
    result = meetings.create_meeting(fake_client, payload)

    fake_client.post.assert_called_once_with("/users/me/meetings", json=payload)
    assert result == {"id": 999, "join_url": "https://zoom.us/j/999"}


def test_create_meeting_url_encodes_user_id() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {}

    meetings.create_meeting(fake_client, {"topic": "T"}, user_id="alice@example.com")

    assert fake_client.post.call_args[0][0] == "/users/alice%40example.com/meetings"


def test_update_meeting_patches_meeting_path() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    meetings.update_meeting(fake_client, 123, {"topic": "New title"})

    fake_client.patch.assert_called_once_with("/meetings/123", json={"topic": "New title"})


def test_update_meeting_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    meetings.update_meeting(fake_client, "evil/../admin", {})

    arg = fake_client.patch.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_delete_meeting_uses_DELETE_with_default_silent_params() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    meetings.delete_meeting(fake_client, 123)

    fake_client.delete.assert_called_once_with(
        "/meetings/123",
        params={
            "schedule_for_reminder": "false",
            "cancel_meeting_reminder": "false",
        },
    )


def test_delete_meeting_forwards_notify_flags() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    meetings.delete_meeting(
        fake_client, 123, schedule_for_reminder=True, cancel_meeting_reminder=True
    )

    params = fake_client.delete.call_args[1]["params"]
    assert params["schedule_for_reminder"] == "true"
    assert params["cancel_meeting_reminder"] == "true"


def test_end_meeting_puts_status_with_action_end() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    meetings.end_meeting(fake_client, 123)

    fake_client.put.assert_called_once_with("/meetings/123/status", json={"action": "end"})


def test_end_meeting_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    meetings.end_meeting(fake_client, "evil/../admin")

    arg = fake_client.put.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg
