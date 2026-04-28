"""Tests for zoom_cli.api.phone — Zoom Phone endpoint helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from zoom_cli.api import phone


def test_list_phone_users_paginates_users_endpoint() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": "tok-2"},
        {"users": [{"id": "u3"}], "next_page_token": ""},
    ]

    result = list(phone.list_phone_users(fake_client))

    assert result == [{"id": "u1"}, {"id": "u2"}, {"id": "u3"}]
    assert fake_client.get.call_count == 2
    assert fake_client.get.call_args_list[0][0][0] == "/phone/users"


def test_get_phone_user_targets_user_path_and_url_encodes() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"id": "u-1"}

    phone.get_phone_user(fake_client, "alice@example.com")

    assert fake_client.get.call_args[0][0] == "/phone/users/alice%40example.com"


def test_list_call_logs_account_wide_when_no_user_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"call_logs": [], "next_page_token": ""}

    list(phone.list_call_logs(fake_client))

    assert fake_client.get.call_args[0][0] == "/phone/call_logs"


def test_list_call_logs_per_user_when_user_id_set() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"call_logs": [], "next_page_token": ""}

    list(phone.list_call_logs(fake_client, user_id="u-42"))

    assert fake_client.get.call_args[0][0] == "/phone/users/u-42/call_logs"


def test_list_call_logs_forwards_date_filters() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"call_logs": [], "next_page_token": ""}

    list(phone.list_call_logs(fake_client, from_="2026-04-01", to="2026-04-30"))

    params = fake_client.get.call_args[1]["params"]
    assert params["from"] == "2026-04-01"
    assert params["to"] == "2026-04-30"


def test_list_call_logs_omits_date_filters_when_unset() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"call_logs": [], "next_page_token": ""}

    list(phone.list_call_logs(fake_client))

    params = fake_client.get.call_args[1]["params"]
    assert "from" not in params
    assert "to" not in params


def test_list_call_logs_walks_pagination_cursor() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"call_logs": [{"id": "c1"}], "next_page_token": "tok-2"},
        {"call_logs": [{"id": "c2"}, {"id": "c3"}], "next_page_token": ""},
    ]

    result = list(phone.list_call_logs(fake_client))

    assert result == [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]
    assert fake_client.get.call_count == 2


def test_list_call_queues_paginates() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {
        "call_queues": [{"id": "q1"}, {"id": "q2"}],
        "next_page_token": "",
    }

    result = list(phone.list_call_queues(fake_client))

    assert result == [{"id": "q1"}, {"id": "q2"}]
    assert fake_client.get.call_args[0][0] == "/phone/call_queues"


def test_list_phone_recordings_account_wide_when_no_user_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"recordings": [], "next_page_token": ""}

    list(phone.list_phone_recordings(fake_client))

    assert fake_client.get.call_args[0][0] == "/phone/recordings"


def test_list_phone_recordings_per_user_when_user_id_set() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"recordings": [], "next_page_token": ""}

    list(phone.list_phone_recordings(fake_client, user_id="u-7"))

    assert fake_client.get.call_args[0][0] == "/phone/users/u-7/recordings"


def test_list_phone_recordings_forwards_date_filters() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"recordings": [], "next_page_token": ""}

    list(phone.list_phone_recordings(fake_client, from_="2026-04-01", to="2026-04-30"))

    params = fake_client.get.call_args[1]["params"]
    assert params["from"] == "2026-04-01"
    assert params["to"] == "2026-04-30"
