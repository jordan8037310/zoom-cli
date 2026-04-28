"""Tests for zoom_cli.api.dashboard — Dashboard / Metrics endpoint helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from zoom_cli.api import dashboard


def test_list_meetings_default_type_past() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(dashboard.list_meetings(fake_client, from_="2026-04-01", to="2026-04-30"))

    call = fake_client.get.call_args
    assert call[0][0] == "/metrics/meetings"
    assert call[1]["params"]["type"] == "past"
    assert call[1]["params"]["from"] == "2026-04-01"
    assert call[1]["params"]["to"] == "2026-04-30"


def test_list_meetings_forwards_type() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(dashboard.list_meetings(fake_client, type="live", from_="2026-04-01", to="2026-04-30"))

    assert fake_client.get.call_args[1]["params"]["type"] == "live"


def test_list_meetings_rejects_unknown_type() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="type"):
        list(
            dashboard.list_meetings(fake_client, type="bogus", from_="2026-04-01", to="2026-04-30")
        )


def test_list_meetings_walks_pagination_cursor() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"meetings": [{"id": 1}], "next_page_token": "tok-2"},
        {"meetings": [{"id": 2}, {"id": 3}], "next_page_token": ""},
    ]

    result = list(dashboard.list_meetings(fake_client, from_="2026-04-01", to="2026-04-30"))

    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_get_meeting_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"id": 12345}

    dashboard.get_meeting(fake_client, 12345)

    fake_client.get.assert_called_once_with("/metrics/meetings/12345")


def test_get_meeting_url_encodes_uuid_with_slashes() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    dashboard.get_meeting(fake_client, "uuid/with/slashes==")

    arg = fake_client.get.call_args[0][0]
    assert "uuid/with/slashes==" not in arg
    assert "%2F" in arg


def test_list_meeting_participants_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"participants": [], "next_page_token": ""}

    list(dashboard.list_meeting_participants(fake_client, "12345"))

    call = fake_client.get.call_args
    assert call[0][0] == "/metrics/meetings/12345/participants"
    assert call[1]["params"]["type"] == "past"


def test_list_meeting_participants_forwards_type() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"participants": [], "next_page_token": ""}

    list(dashboard.list_meeting_participants(fake_client, "12345", type="live"))

    assert fake_client.get.call_args[1]["params"]["type"] == "live"


def test_list_meeting_participants_rejects_unknown_type() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="type"):
        list(dashboard.list_meeting_participants(fake_client, "12345", type="bogus"))


def test_list_meeting_participants_url_encodes_meeting_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"participants": [], "next_page_token": ""}

    list(dashboard.list_meeting_participants(fake_client, "uuid/with/slashes=="))

    arg = fake_client.get.call_args[0][0]
    assert "uuid/with/slashes==" not in arg
    assert "%2F" in arg


def test_list_zoomrooms_paginates() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {
        "zoom_rooms": [{"id": "r1"}, {"id": "r2"}],
        "next_page_token": "",
    }

    result = list(dashboard.list_zoomrooms(fake_client))

    assert result == [{"id": "r1"}, {"id": "r2"}]
    assert fake_client.get.call_args[0][0] == "/metrics/zoomrooms"


def test_get_zoomroom_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"id": "r-1"}

    dashboard.get_zoomroom(fake_client, "r-1")

    fake_client.get.assert_called_once_with("/metrics/zoomrooms/r-1")


def test_get_zoomroom_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    dashboard.get_zoomroom(fake_client, "weird/id")

    assert fake_client.get.call_args[0][0] == "/metrics/zoomrooms/weird%2Fid"


def test_allowed_meeting_metric_types_pinned() -> None:
    assert dashboard.ALLOWED_MEETING_METRIC_TYPES == ("past", "live", "pastOne")
