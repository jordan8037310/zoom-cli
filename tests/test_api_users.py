"""Tests for zoom_cli.api.users — Users endpoint helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from zoom_cli.api import users


def test_get_me_calls_users_me_endpoint() -> None:
    """Pin the path so a typo doesn't silently target the wrong endpoint."""
    fake_client = MagicMock()
    fake_client.get.return_value = {"id": "u-1", "email": "x@y"}

    result = users.get_me(fake_client)

    fake_client.get.assert_called_once_with("/users/me")
    assert result == {"id": "u-1", "email": "x@y"}


# ---- #36: durable get_user(user_id) abstraction --------------------------


def test_get_user_default_targets_me() -> None:
    """Closes #36: ``get_user`` with no args is the same as ``get_me``."""
    fake_client = MagicMock()
    fake_client.get.return_value = {"id": "u-me"}

    users.get_user(fake_client)

    fake_client.get.assert_called_once_with("/users/me")


def test_get_user_targets_specific_user_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"id": "u-42"}

    users.get_user(fake_client, "u-42")

    fake_client.get.assert_called_once_with("/users/u-42")


def test_get_user_url_encodes_user_id_with_special_chars() -> None:
    """A user_id containing ``/``, ``?``, ``#`` etc. must be percent-encoded
    so it can't break out of the path segment. Defense-in-depth — current
    callers don't pass untrusted input but a future CLI might."""
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    users.get_user(fake_client, "evil/../admin?x=1")

    # `/` and `?` must be percent-encoded (`%2F` and `%3F`).
    call_arg = fake_client.get.call_args[0][0]
    assert "/.." not in call_arg
    assert "?" not in call_arg
    assert "%2F" in call_arg
    assert "%3F" in call_arg


def test_get_me_is_alias_for_get_user_me() -> None:
    """The CLI's ``zoom users me`` command imports get_me; ensure the alias
    keeps producing the same call shape (closes #36 backward compatibility)."""
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    users.get_me(fake_client)

    fake_client.get.assert_called_once_with("/users/me")


# ---- #16: list_users via paginate ---------------------------------------


def test_list_users_yields_across_pages() -> None:
    """list_users walks the next_page_token cursor end-to-end."""
    pages = [
        {"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": "tok-2"},
        {"users": [{"id": "u3"}], "next_page_token": ""},
    ]
    fake_client = MagicMock()
    fake_client.get.side_effect = pages

    result = list(users.list_users(fake_client))

    assert result == [{"id": "u1"}, {"id": "u2"}, {"id": "u3"}]
    # Two GETs, both to /users with status=active.
    assert fake_client.get.call_count == 2
    first_call_args = fake_client.get.call_args_list[0]
    assert first_call_args[0][0] == "/users"
    assert first_call_args[1]["params"]["status"] == "active"
    assert first_call_args[1]["params"]["page_size"] == 300


def test_list_users_passes_status_filter() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"users": [], "next_page_token": ""}

    list(users.list_users(fake_client, status="pending"))

    params = fake_client.get.call_args_list[0][1]["params"]
    assert params["status"] == "pending"


# ---- write surface (closes #14 write piece) -----------------------------


def test_create_user_wraps_payload_with_action_and_user_info() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {"id": "new-user", "email": "alice@example.com"}

    result = users.create_user(fake_client, {"email": "alice@example.com", "type": 2})

    fake_client.post.assert_called_once_with(
        "/users",
        json={"action": "create", "user_info": {"email": "alice@example.com", "type": 2}},
    )
    assert result == {"id": "new-user", "email": "alice@example.com"}


def test_create_user_forwards_action() -> None:
    fake_client = MagicMock()
    fake_client.post.return_value = {}

    users.create_user(fake_client, {"email": "x@y", "type": 1}, action="autoCreate")

    body = fake_client.post.call_args[1]["json"]
    assert body["action"] == "autoCreate"


def test_create_user_rejects_unknown_action() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="action"):
        users.create_user(fake_client, {"email": "x@y", "type": 1}, action="bogus")


def test_delete_user_default_disassociates() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_user(fake_client, "u-123")

    fake_client.delete.assert_called_once_with("/users/u-123", params={"action": "disassociate"})


def test_delete_user_permanent_action() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_user(fake_client, "u-123", action="delete")

    assert fake_client.delete.call_args[1]["params"]["action"] == "delete"


def test_delete_user_rejects_unknown_action() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="action"):
        users.delete_user(fake_client, "u-1", action="bogus")


def test_delete_user_attaches_transfer_params_when_email_set() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_user(
        fake_client,
        "u-leaving",
        transfer_email="successor@example.com",
        transfer_meeting=True,
        transfer_recording=False,
        transfer_webinar=True,
    )

    params = fake_client.delete.call_args[1]["params"]
    assert params["transfer_email"] == "successor@example.com"
    assert params["transfer_meeting"] == "true"
    assert params["transfer_recording"] == "false"
    assert params["transfer_webinar"] == "true"


def test_delete_user_omits_transfer_params_without_email() -> None:
    """Transfer flags are no-ops without --transfer-email; don't send them."""
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_user(fake_client, "u-123", transfer_meeting=True)

    params = fake_client.delete.call_args[1]["params"]
    assert "transfer_email" not in params
    assert "transfer_meeting" not in params


def test_delete_user_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_user(fake_client, "alice@example.com")

    arg = fake_client.delete.call_args[0][0]
    assert arg == "/users/alice%40example.com"


def test_get_user_settings_default_me() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"feature": {}, "in_meeting": {}}

    users.get_user_settings(fake_client)

    fake_client.get.assert_called_once_with("/users/me/settings")


def test_get_user_settings_specific_user() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    users.get_user_settings(fake_client, "u-42")

    fake_client.get.assert_called_once_with("/users/u-42/settings")


def test_get_user_settings_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}

    users.get_user_settings(fake_client, "alice@example.com")

    assert fake_client.get.call_args[0][0] == "/users/alice%40example.com/settings"


def test_allowed_create_actions_pinned() -> None:
    assert "create" in users.ALLOWED_CREATE_ACTIONS
    assert "autoCreate" in users.ALLOWED_CREATE_ACTIONS
    assert "custCreate" in users.ALLOWED_CREATE_ACTIONS
    assert "ssoCreate" in users.ALLOWED_CREATE_ACTIONS


def test_allowed_delete_actions_pinned() -> None:
    assert users.ALLOWED_DELETE_ACTIONS == ("disassociate", "delete")


# ---- update_user_settings (PATCH partial) -------------------------------


def test_update_user_settings_patches_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    users.update_user_settings(fake_client, "u-1", {"in_meeting": {"chat": False}})

    fake_client.patch.assert_called_once_with(
        "/users/u-1/settings", json={"in_meeting": {"chat": False}}
    )


def test_update_user_settings_url_encodes_user_id() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    users.update_user_settings(fake_client, "alice@example.com", {"x": 1})

    arg = fake_client.patch.call_args[0][0]
    assert arg == "/users/alice%40example.com/settings"


def test_update_user_settings_passes_payload_through() -> None:
    """Payload is forwarded as-is — no validation, no field-coverage
    requirement (the CLI dumps then re-PATCHes, which is the typical
    workflow)."""
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    payload = {
        "feature": {"meeting_capacity": 100},
        "in_meeting": {"chat": True, "private_chat": False},
        "email_notification": {"jbh_reminder": True},
    }
    users.update_user_settings(fake_client, "me", payload)

    assert fake_client.patch.call_args[1]["json"] == payload
