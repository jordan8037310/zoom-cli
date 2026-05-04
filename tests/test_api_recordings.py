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


# ---- depth-completion: recover + settings + registrants ----------------


def test_recover_recordings_puts_status_with_action_recover() -> None:
    """Recover all of a meeting's trashed recordings."""
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    recordings.recover_recordings(fake_client, 12345)

    fake_client.put.assert_called_once_with(
        "/meetings/12345/recordings/status", json={"action": "recover"}
    )


def test_recover_recordings_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}
    recordings.recover_recordings(fake_client, "evil/../1")
    arg = fake_client.put.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_recover_recording_file_puts_specific_path() -> None:
    """Recover one trashed file (not all)."""
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    recordings.recover_recording_file(fake_client, 12345, "rec-1")

    fake_client.put.assert_called_once_with(
        "/meetings/12345/recordings/rec-1/status", json={"action": "recover"}
    )


def test_recover_recording_file_url_encodes_both() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}
    recordings.recover_recording_file(fake_client, "m/../1", "r/../2")
    arg = fake_client.put.call_args[0][0]
    assert "/.." not in arg


def test_get_recording_settings_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {
        "share_recording": "publicly",
        "topic": "Daily Standup",
    }

    result = recordings.get_recording_settings(fake_client, 12345)

    fake_client.get.assert_called_once_with("/meetings/12345/recordings/settings")
    assert result["share_recording"] == "publicly"


def test_update_recording_settings_patches_with_payload() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    payload = {"share_recording": "internally", "viewer_download": False}
    recordings.update_recording_settings(fake_client, 12345, payload)

    fake_client.patch.assert_called_once_with("/meetings/12345/recordings/settings", json=payload)


def test_recording_settings_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}
    fake_client.patch.return_value = {}
    recordings.get_recording_settings(fake_client, "evil/../1")
    recordings.update_recording_settings(fake_client, "evil/../1", {})
    for arg in (
        fake_client.get.call_args[0][0],
        fake_client.patch.call_args[0][0],
    ):
        assert "/.." not in arg
        assert "%2F" in arg


def test_list_recording_registrants_default_status_pending_walks_pagination() -> None:
    """Same default-pending shape as meeting registrants."""
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"registrants": [{"id": "r-1"}, {"id": "r-2"}], "next_page_token": "t-2"},
        {"registrants": [{"id": "r-3"}], "next_page_token": ""},
    ]

    result = list(recordings.list_recording_registrants(fake_client, 12345))

    assert result == [{"id": "r-1"}, {"id": "r-2"}, {"id": "r-3"}]
    first = fake_client.get.call_args_list[0]
    assert first[0][0] == "/meetings/12345/recordings/registrants"
    assert first[1]["params"]["status"] == "pending"


@pytest.mark.parametrize("bad_status", ["bogus", "", "rejected"])
def test_list_recording_registrants_rejects_unknown_status(bad_status: str) -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="status"):
        list(recordings.list_recording_registrants(fake_client, 12345, status=bad_status))


def test_add_recording_registrant_posts_payload() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {
        "id": "r-1",
        "share_url": "https://zoom.us/rec/share/abc",
    }

    payload = {"email": "a@e.com", "first_name": "A"}
    result = recordings.add_recording_registrant(fake_client, 12345, payload)

    fake_client.post.assert_called_once_with("/meetings/12345/recordings/registrants", json=payload)
    assert result["share_url"].startswith("https://")


def test_update_recording_registrant_status_puts_action_and_list() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    recordings.update_recording_registrant_status(
        fake_client, 12345, action="approve", registrant_ids=["r-1", "r-2"]
    )

    fake_client.put.assert_called_once_with(
        "/meetings/12345/recordings/registrants/status",
        json={"action": "approve", "registrants": [{"id": "r-1"}, {"id": "r-2"}]},
    )


@pytest.mark.parametrize("bad_action", ["bogus", "", "cancel"])
def test_update_recording_registrant_status_rejects_unknown_action(bad_action: str) -> None:
    """Recording registrants only support approve/deny — no cancel like meetings."""
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="action"):
        recordings.update_recording_registrant_status(
            fake_client, 12345, action=bad_action, registrant_ids=["r-1"]
        )


def test_update_recording_registrant_status_rejects_empty_id_list() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="at least one"):
        recordings.update_recording_registrant_status(
            fake_client, 12345, action="approve", registrant_ids=[]
        )


def test_allowed_recording_registrant_statuses_pinned() -> None:
    assert "pending" in recordings.ALLOWED_REGISTRANT_STATUSES
    assert "approved" in recordings.ALLOWED_REGISTRANT_STATUSES
    assert "denied" in recordings.ALLOWED_REGISTRANT_STATUSES


def test_allowed_recording_registrant_actions_pinned() -> None:
    """Recording registrants only support approve/deny — no cancel."""
    assert "approve" in recordings.ALLOWED_REGISTRANT_ACTIONS
    assert "deny" in recordings.ALLOWED_REGISTRANT_ACTIONS
