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


# ---- registrants depth-completion (post-#13 follow-up) --------------------


def test_list_registrants_default_status_pending_walks_pagination() -> None:
    """Zoom defaults the registrant list to pending; we mirror that.
    Pagination uses next_page_token like every other paginated endpoint."""
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"registrants": [{"id": "r-1"}, {"id": "r-2"}], "next_page_token": "tok-2"},
        {"registrants": [{"id": "r-3"}], "next_page_token": ""},
    ]

    result = list(meetings.list_registrants(fake_client, 123))

    assert result == [{"id": "r-1"}, {"id": "r-2"}, {"id": "r-3"}]
    first = fake_client.get.call_args_list[0]
    assert first[0][0] == "/meetings/123/registrants"
    assert first[1]["params"]["status"] == "pending"


def test_list_registrants_forwards_status_and_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"registrants": [], "next_page_token": ""}

    list(meetings.list_registrants(fake_client, "evil/../99", status="approved"))

    call = fake_client.get.call_args_list[0]
    assert "/.." not in call[0][0]
    assert "%2F" in call[0][0]
    assert call[1]["params"]["status"] == "approved"


@pytest.mark.parametrize("bad_status", ["bogus", "", "rejected"])
def test_list_registrants_rejects_unknown_status(bad_status: str) -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="status"):
        list(meetings.list_registrants(fake_client, 123, status=bad_status))


def test_add_registrant_posts_payload() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {
        "id": 12345,
        "registrant_id": "rid-abc",
        "join_url": "https://zoom.us/w/123?tk=xyz",
    }

    payload = {"email": "a@example.com", "first_name": "A"}
    result = meetings.add_registrant(fake_client, 123, payload)

    fake_client.post.assert_called_once_with("/meetings/123/registrants", json=payload)
    assert result["registrant_id"] == "rid-abc"


def test_add_registrant_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {}

    meetings.add_registrant(fake_client, "evil/../99", {"email": "a@b.c"})

    arg = fake_client.post.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_update_registrant_status_puts_action_and_list() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    meetings.update_registrant_status(
        fake_client, 123, action="approve", registrant_ids=["r-1", "r-2"]
    )

    fake_client.put.assert_called_once_with(
        "/meetings/123/registrants/status",
        json={"action": "approve", "registrants": [{"id": "r-1"}, {"id": "r-2"}]},
    )


@pytest.mark.parametrize("bad_action", ["bogus", "", "delete"])
def test_update_registrant_status_rejects_unknown_action(bad_action: str) -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="action"):
        meetings.update_registrant_status(
            fake_client, 123, action=bad_action, registrant_ids=["r-1"]
        )


def test_update_registrant_status_rejects_empty_id_list() -> None:
    """Sending an empty list to Zoom would be a no-op API call —
    refuse early so the caller learns about the typo before burning
    a request slot."""
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="at least one"):
        meetings.update_registrant_status(fake_client, 123, action="approve", registrant_ids=[])


def test_get_registration_questions_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"questions": [], "custom_questions": []}

    result = meetings.get_registration_questions(fake_client, 123)

    fake_client.get.assert_called_once_with("/meetings/123/registrants/questions")
    assert result == {"questions": [], "custom_questions": []}


def test_update_registration_questions_patches_with_payload() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    payload = {"questions": [{"field_name": "city", "required": True}]}
    meetings.update_registration_questions(fake_client, 123, payload)

    fake_client.patch.assert_called_once_with("/meetings/123/registrants/questions", json=payload)


def test_update_registration_questions_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    meetings.update_registration_questions(fake_client, "evil/../1", {"questions": []})
    arg = fake_client.patch.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_allowed_registrant_statuses_pinned() -> None:
    assert "pending" in meetings.ALLOWED_REGISTRANT_STATUSES
    assert "approved" in meetings.ALLOWED_REGISTRANT_STATUSES
    assert "denied" in meetings.ALLOWED_REGISTRANT_STATUSES


def test_allowed_registrant_actions_pinned() -> None:
    assert "approve" in meetings.ALLOWED_REGISTRANT_ACTIONS
    assert "deny" in meetings.ALLOWED_REGISTRANT_ACTIONS
    assert "cancel" in meetings.ALLOWED_REGISTRANT_ACTIONS


# ---- polls depth-completion (post-#13 follow-up) --------------------------


def test_list_polls_targets_meeting_path() -> None:
    """Polls list is a single GET (not paginated — Zoom returns the
    entire poll set inline) so we surface the raw envelope."""
    fake_client = MagicMock()
    fake_client.get.return_value = {
        "total_records": 1,
        "polls": [{"id": "p-1", "title": "Q1"}],
    }

    result = meetings.list_polls(fake_client, 123)

    fake_client.get.assert_called_once_with("/meetings/123/polls")
    assert result["polls"][0]["id"] == "p-1"


def test_list_polls_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"polls": []}

    meetings.list_polls(fake_client, "evil/../99")
    arg = fake_client.get.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_get_poll_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"id": "p-1", "title": "Q1"}

    result = meetings.get_poll(fake_client, 123, "p-1")

    fake_client.get.assert_called_once_with("/meetings/123/polls/p-1")
    assert result["id"] == "p-1"


def test_get_poll_url_encodes_both_segments() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    meetings.get_poll(fake_client, "m/../1", "p/../2")
    arg = fake_client.get.call_args[0][0]
    # Each segment has 2 slashes → 2*2 == 4 encoded chars total.
    assert arg.count("%2F") == 4
    assert "/.." not in arg


def test_create_poll_posts_payload() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {"id": "p-new", "title": "T"}

    payload = {
        "title": "T",
        "questions": [{"name": "Q1", "type": "single", "answers": ["A", "B"]}],
    }
    result = meetings.create_poll(fake_client, 123, payload)

    fake_client.post.assert_called_once_with("/meetings/123/polls", json=payload)
    assert result["id"] == "p-new"


def test_update_poll_puts_full_payload() -> None:
    """Per Zoom's spec the poll update is a PUT (full replace) — make
    that explicit in the helper rather than masquerading as PATCH."""
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    payload = {"title": "T2", "questions": []}
    meetings.update_poll(fake_client, 123, "p-1", payload)

    fake_client.put.assert_called_once_with("/meetings/123/polls/p-1", json=payload)


def test_update_poll_url_encodes_both_segments() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    meetings.update_poll(fake_client, "m/../1", "p/../2", {"title": ""})
    arg = fake_client.put.call_args[0][0]
    assert arg.count("%2F") == 4
    assert "/.." not in arg


def test_delete_poll_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    meetings.delete_poll(fake_client, 123, "p-1")

    fake_client.delete.assert_called_once_with("/meetings/123/polls/p-1")


def test_delete_poll_url_encodes_both_segments() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    meetings.delete_poll(fake_client, "m/../1", "p/../2")
    arg = fake_client.delete.call_args[0][0]
    assert arg.count("%2F") == 4
    assert "/.." not in arg


def test_list_past_poll_results_targets_past_meetings_endpoint() -> None:
    """Past-meeting poll RESULTS live under /past_meetings (not /meetings) —
    different namespace, identical resource shape."""
    fake_client = MagicMock()
    fake_client.get.return_value = {
        "id": 123,
        "questions": [{"name": "Q1", "question_details": []}],
    }

    result = meetings.list_past_poll_results(fake_client, 123)

    fake_client.get.assert_called_once_with("/past_meetings/123/polls")
    assert "questions" in result


# ---- livestream depth-completion (post-#13 follow-up) -------------------


def test_get_livestream_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {
        "stream_url": "rtmp://example.com/live",
        "stream_key": "x",
        "page_url": "https://example.com/watch",
    }

    result = meetings.get_livestream(fake_client, 123)

    fake_client.get.assert_called_once_with("/meetings/123/livestream")
    assert result["stream_url"] == "rtmp://example.com/live"


def test_get_livestream_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    meetings.get_livestream(fake_client, "evil/../99")
    arg = fake_client.get.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_update_livestream_patches_with_payload() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    payload = {
        "stream_url": "rtmp://example.com/live",
        "stream_key": "k",
        "page_url": "https://example.com/watch",
    }
    meetings.update_livestream(fake_client, 123, payload)

    fake_client.patch.assert_called_once_with("/meetings/123/livestream", json=payload)


def test_update_livestream_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    meetings.update_livestream(fake_client, "evil/../99", {})
    arg = fake_client.patch.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_update_livestream_status_starts_with_action_and_settings() -> None:
    """Start variant — Zoom requires the broadcast settings sub-object."""
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    meetings.update_livestream_status(
        fake_client,
        123,
        action="start",
        settings={"active_speaker_name": True, "display_name": "Webinar live"},
    )

    fake_client.patch.assert_called_once_with(
        "/meetings/123/livestream/status",
        json={
            "action": "start",
            "settings": {
                "active_speaker_name": True,
                "display_name": "Webinar live",
            },
        },
    )


def test_update_livestream_status_stops_without_settings() -> None:
    """Stop variant — settings sub-object is omitted (Zoom doesn't need
    it for shutdown)."""
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    meetings.update_livestream_status(fake_client, 123, action="stop")

    fake_client.patch.assert_called_once_with(
        "/meetings/123/livestream/status", json={"action": "stop"}
    )


@pytest.mark.parametrize("bad_action", ["bogus", "", "pause"])
def test_update_livestream_status_rejects_unknown_action(bad_action: str) -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="action"):
        meetings.update_livestream_status(fake_client, 123, action=bad_action)


def test_update_livestream_status_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    meetings.update_livestream_status(fake_client, "evil/../99", action="stop")
    arg = fake_client.patch.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_allowed_livestream_actions_pinned() -> None:
    assert "start" in meetings.ALLOWED_LIVESTREAM_ACTIONS
    assert "stop" in meetings.ALLOWED_LIVESTREAM_ACTIONS


# ---- past instances + invitation + past-meeting summary/participants ----


def test_get_invitation_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"invitation": "Hi! You're invited to..."}

    result = meetings.get_invitation(fake_client, 123)

    fake_client.get.assert_called_once_with("/meetings/123/invitation")
    assert "invitation" in result


def test_get_invitation_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}
    meetings.get_invitation(fake_client, "evil/../99")
    arg = fake_client.get.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_list_past_instances_targets_past_meetings_endpoint() -> None:
    """Past instances list lives under /past_meetings (not /meetings) —
    same namespace as past_poll_results."""
    fake_client = MagicMock()
    fake_client.get.return_value = {
        "meetings": [{"uuid": "u-1", "start_time": "2026-04-29T15:00:00Z"}]
    }

    result = meetings.list_past_instances(fake_client, 123)

    fake_client.get.assert_called_once_with("/past_meetings/123/instances")
    assert result["meetings"][0]["uuid"] == "u-1"


def test_get_past_meeting_targets_past_meetings_endpoint() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"id": 123, "topic": "Daily standup"}

    result = meetings.get_past_meeting(fake_client, 123)

    fake_client.get.assert_called_once_with("/past_meetings/123")
    assert result["topic"] == "Daily standup"


def test_get_past_meeting_url_encodes_uuid() -> None:
    """UUIDs (the more typical past-meeting key) often contain slashes
    that Zoom expects double-encoded — but we're conservative and just
    single-encode (Zoom accepts both)."""
    fake_client = MagicMock()
    fake_client.get.return_value = {}
    meetings.get_past_meeting(fake_client, "evil/../99")
    arg = fake_client.get.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_list_past_participants_walks_pagination() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"participants": [{"id": "p-1"}, {"id": "p-2"}], "next_page_token": "tok-2"},
        {"participants": [{"id": "p-3"}], "next_page_token": ""},
    ]

    result = list(meetings.list_past_participants(fake_client, 123))

    assert result == [{"id": "p-1"}, {"id": "p-2"}, {"id": "p-3"}]
    first = fake_client.get.call_args_list[0]
    assert first[0][0] == "/past_meetings/123/participants"


def test_list_past_participants_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"participants": [], "next_page_token": ""}
    list(meetings.list_past_participants(fake_client, "evil/../99"))
    call_path = fake_client.get.call_args_list[0][0][0]
    assert "/.." not in call_path
    assert "%2F" in call_path


def test_recover_meeting_puts_status_with_action_recover() -> None:
    """Recovering a soft-deleted meeting — separate verb from end_meeting
    even though both PUT to /meetings/<id>/status."""
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    meetings.recover_meeting(fake_client, 123)

    fake_client.put.assert_called_once_with("/meetings/123/status", json={"action": "recover"})


def test_recover_meeting_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}
    meetings.recover_meeting(fake_client, "evil/../99")
    arg = fake_client.put.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


# ---- survey + token + batch register + in-meeting controls -------------


def test_get_survey_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"questions": [{"name": "Q1"}]}

    result = meetings.get_survey(fake_client, 123)

    fake_client.get.assert_called_once_with("/meetings/123/survey")
    assert result["questions"][0]["name"] == "Q1"


def test_update_survey_patches_with_payload() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    payload = {"questions": [{"name": "Rating", "type": "single"}], "show_in_browser": True}
    meetings.update_survey(fake_client, 123, payload)

    fake_client.patch.assert_called_once_with("/meetings/123/survey", json=payload)


def test_delete_survey_uses_delete() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    meetings.delete_survey(fake_client, 123)

    fake_client.delete.assert_called_once_with("/meetings/123/survey")


def test_survey_url_encodes_id() -> None:
    """Cross-cutting: all three survey verbs encode their path segment."""
    fake_client = MagicMock()
    fake_client.get.return_value = {}
    fake_client.patch.return_value = {}
    fake_client.delete.return_value = {}

    meetings.get_survey(fake_client, "evil/../1")
    meetings.update_survey(fake_client, "evil/../1", {})
    meetings.delete_survey(fake_client, "evil/../1")

    for call in (
        fake_client.get.call_args[0][0],
        fake_client.patch.call_args[0][0],
        fake_client.delete.call_args[0][0],
    ):
        assert "/.." not in call
        assert "%2F" in call


def test_get_token_default_type_is_zak() -> None:
    """Zoom defaults the token endpoint to ZAK (the most common: needed
    to start a meeting on someone's behalf). Keep that as our default."""
    fake_client = MagicMock()
    fake_client.get.return_value = {"token": "abc.def.ghi"}

    result = meetings.get_token(fake_client, 123)

    fake_client.get.assert_called_once_with("/meetings/123/token", params={"type": "zak"})
    assert result["token"] == "abc.def.ghi"


def test_get_token_forwards_type_filter() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"token": "x"}

    meetings.get_token(fake_client, 123, token_type="zpk")

    fake_client.get.assert_called_once_with("/meetings/123/token", params={"type": "zpk"})


@pytest.mark.parametrize("bad_type", ["bogus", "", "ZAK", "z a k"])
def test_get_token_rejects_unknown_type(bad_type: str) -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="token_type"):
        meetings.get_token(fake_client, 123, token_type=bad_type)


def test_allowed_token_types_pinned() -> None:
    assert "zak" in meetings.ALLOWED_TOKEN_TYPES


def test_batch_register_posts_payload() -> None:
    """Bulk registration: payload contains an array of registrants under
    the ``registrants`` key. Returns Zoom's bulk response with one
    join_url per accepted entry."""
    fake_client = MagicMock()
    fake_client.post.return_value = {
        "registrants": [{"email": "a@e.com", "join_url": "https://zoom.us/w/1?tk=A"}]
    }

    payload = {
        "auto_approve": True,
        "registrants_confirmation_email": False,
        "registrants": [{"email": "a@e.com", "first_name": "A"}],
    }
    result = meetings.batch_register(fake_client, 123, payload)

    fake_client.post.assert_called_once_with("/meetings/123/batch_registrants", json=payload)
    assert result["registrants"][0]["email"] == "a@e.com"


def test_in_meeting_control_patches_live_meetings_path() -> None:
    """In-meeting control sits under /live_meetings (NOT /meetings) —
    distinct namespace, action verbs like 'invite' / 'mute_participants'."""
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    payload = {"method": "invite", "params": {"contacts": [{"email": "a@e.com"}]}}
    meetings.in_meeting_control(fake_client, 123, payload)

    fake_client.patch.assert_called_once_with("/live_meetings/123/events", json=payload)


def test_in_meeting_control_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    meetings.in_meeting_control(fake_client, "evil/../1", {})
    arg = fake_client.patch.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg
