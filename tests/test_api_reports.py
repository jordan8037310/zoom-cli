"""Tests for zoom_cli.api.reports — Reports endpoint helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from zoom_cli.api import reports


def test_get_daily_default_no_params() -> None:
    """No year/month → empty params (Zoom returns the current month)."""
    fake_client = MagicMock()
    fake_client.get.return_value = {"dates": []}

    reports.get_daily(fake_client)

    fake_client.get.assert_called_once_with("/report/daily", params=None)


def test_get_daily_forwards_year_month() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    reports.get_daily(fake_client, year=2026, month=4)

    fake_client.get.assert_called_once_with("/report/daily", params={"year": 2026, "month": 4})


def test_list_meetings_report_account_wide_when_no_user_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(reports.list_meetings_report(fake_client, from_="2026-04-01", to="2026-04-30"))

    call = fake_client.get.call_args
    assert call[0][0] == "/report/meetings"
    assert call[1]["params"]["from"] == "2026-04-01"
    assert call[1]["params"]["to"] == "2026-04-30"


def test_list_meetings_report_per_user_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(
        reports.list_meetings_report(
            fake_client, user_id="alice@example.com", from_="2026-04-01", to="2026-04-30"
        )
    )

    assert fake_client.get.call_args[0][0] == "/report/users/alice%40example.com/meetings"


def test_list_meetings_report_forwards_meeting_type() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(
        reports.list_meetings_report(
            fake_client,
            from_="2026-04-01",
            to="2026-04-30",
            meeting_type="past",
        )
    )

    assert fake_client.get.call_args[1]["params"]["type"] == "past"


def test_list_meetings_report_omits_type_when_none() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"meetings": [], "next_page_token": ""}

    list(reports.list_meetings_report(fake_client, from_="2026-04-01", to="2026-04-30"))

    assert "type" not in fake_client.get.call_args[1]["params"]


def test_list_meetings_report_walks_pagination_cursor() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"meetings": [{"id": 1}, {"id": 2}], "next_page_token": "tok-2"},
        {"meetings": [{"id": 3}], "next_page_token": ""},
    ]

    result = list(reports.list_meetings_report(fake_client, from_="2026-04-01", to="2026-04-30"))

    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_list_meeting_participants_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"participants": [], "next_page_token": ""}

    list(reports.list_meeting_participants(fake_client, "12345"))

    assert fake_client.get.call_args[0][0] == "/report/meetings/12345/participants"


def test_list_meeting_participants_url_encodes_meeting_id() -> None:
    """Zoom UUIDs sometimes contain `/` which would break the path; verify
    they're percent-encoded."""
    fake_client = MagicMock()
    fake_client.get.return_value = {"participants": [], "next_page_token": ""}

    list(reports.list_meeting_participants(fake_client, "uuid/with/slashes=="))

    arg = fake_client.get.call_args[0][0]
    assert "uuid/with/slashes==" not in arg
    assert "%2F" in arg


def test_list_operation_logs_required_dates_forwarded() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"operation_logs": [], "next_page_token": ""}

    list(reports.list_operation_logs(fake_client, from_="2026-04-01", to="2026-04-30"))

    call = fake_client.get.call_args
    assert call[0][0] == "/report/operationlogs"
    assert call[1]["params"]["from"] == "2026-04-01"
    assert call[1]["params"]["to"] == "2026-04-30"


def test_list_operation_logs_forwards_category_type() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"operation_logs": [], "next_page_token": ""}

    list(
        reports.list_operation_logs(
            fake_client, from_="2026-04-01", to="2026-04-30", category_type="user"
        )
    )

    assert fake_client.get.call_args[1]["params"]["category_type"] == "user"


def test_list_operation_logs_omits_category_when_none() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"operation_logs": [], "next_page_token": ""}

    list(reports.list_operation_logs(fake_client, from_="2026-04-01", to="2026-04-30"))

    assert "category_type" not in fake_client.get.call_args[1]["params"]
