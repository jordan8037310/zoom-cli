"""Tests for zoom_cli.api.recordings — Cloud Recording endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from zoom_cli.api import recordings


def test_get_recordings_targets_meeting_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"recording_files": []}

    recordings.get_recordings(fake_client, 12345)

    fake_client.get.assert_called_once_with("/meetings/12345/recordings")


def test_get_recordings_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    recordings.get_recordings(fake_client, "evil/../admin")

    arg = fake_client.get.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_list_recordings_default_user_me_no_date_filters() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(recordings.list_recordings(fake_client))

    call = fake_client.get.call_args
    assert call[0][0] == "/users/me/recordings"
    # No `from`/`to` should be in params (apart from page_size + next_page_token).
    params = call[1]["params"]
    assert "from" not in params
    assert "to" not in params


def test_list_recordings_forwards_date_filters() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(
        recordings.list_recordings(
            fake_client, user_id="alice@example.com", from_="2026-04-01", to="2026-04-30"
        )
    )

    call = fake_client.get.call_args
    assert call[0][0] == "/users/alice%40example.com/recordings"
    assert call[1]["params"]["from"] == "2026-04-01"
    assert call[1]["params"]["to"] == "2026-04-30"


def test_list_recordings_walks_pagination_cursor() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"meetings": [{"id": 1}, {"id": 2}], "next_page_token": "tok-2"},
        {"meetings": [{"id": 3}], "next_page_token": ""},
    ]

    result = list(recordings.list_recordings(fake_client))

    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert fake_client.get.call_count == 2


def test_delete_recordings_default_action_is_trash() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    recordings.delete_recordings(fake_client, 12345)

    fake_client.delete.assert_called_once_with(
        "/meetings/12345/recordings", params={"action": "trash"}
    )


def test_delete_recordings_permanent() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    recordings.delete_recordings(fake_client, 12345, action="delete")

    assert fake_client.delete.call_args[1]["params"]["action"] == "delete"


def test_delete_recordings_rejects_unknown_action() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="action"):
        recordings.delete_recordings(fake_client, 12345, action="bogus")


def test_delete_recording_file_targets_file_path() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    recordings.delete_recording_file(fake_client, 12345, "rec-abc")

    fake_client.delete.assert_called_once_with(
        "/meetings/12345/recordings/rec-abc", params={"action": "trash"}
    )


def test_delete_recording_file_url_encodes_recording_id() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    recordings.delete_recording_file(fake_client, 12345, "rec/../bad")

    arg = fake_client.delete.call_args[0][0]
    assert "/recordings/rec%2F" in arg


def test_delete_recording_file_rejects_unknown_action() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="action"):
        recordings.delete_recording_file(fake_client, 12345, "rec", action="bogus")


def test_allowed_delete_actions_pinned() -> None:
    assert recordings.ALLOWED_DELETE_ACTIONS == ("trash", "delete")
