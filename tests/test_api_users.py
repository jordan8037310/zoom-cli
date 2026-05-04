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


# ---- depth-completion: status + password + email + token + permissions --


def test_update_user_status_activate_puts_action() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    users.update_user_status(fake_client, "u-1", action="activate")

    fake_client.put.assert_called_once_with("/users/u-1/status", json={"action": "activate"})


def test_update_user_status_deactivate_puts_action() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    users.update_user_status(fake_client, "u-1", action="deactivate")

    fake_client.put.assert_called_once_with("/users/u-1/status", json={"action": "deactivate"})


@pytest.mark.parametrize("bad_action", ["bogus", "", "delete", "ACTIVATE"])
def test_update_user_status_rejects_unknown_action(bad_action: str) -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="action"):
        users.update_user_status(fake_client, "u-1", action=bad_action)


def test_update_user_status_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}
    users.update_user_status(fake_client, "evil/../1", action="activate")
    arg = fake_client.put.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_allowed_status_actions_pinned() -> None:
    assert "activate" in users.ALLOWED_STATUS_ACTIONS
    assert "deactivate" in users.ALLOWED_STATUS_ACTIONS


def test_update_user_password_puts_password_field() -> None:
    """Password reset — Zoom expects ``{password: "..."}``. The helper
    accepts it in cleartext (the CLI prompts via getpass; the secret
    never reaches argv)."""
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    users.update_user_password(fake_client, "u-1", new_password="hunter2hunter2")

    fake_client.put.assert_called_once_with(
        "/users/u-1/password", json={"password": "hunter2hunter2"}
    )


def test_update_user_password_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}
    users.update_user_password(fake_client, "evil/../1", new_password="x12345678")
    arg = fake_client.put.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_update_user_email_puts_email_field() -> None:
    """Email change triggers a Zoom confirmation flow — the new address
    isn't active until the user clicks the confirmation link."""
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    users.update_user_email(fake_client, "u-1", new_email="new@example.com")

    fake_client.put.assert_called_once_with("/users/u-1/email", json={"email": "new@example.com"})


def test_update_user_email_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}
    users.update_user_email(fake_client, "evil/../1", new_email="x@e.com")
    arg = fake_client.put.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_get_user_token_default_zak() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"token": "abc.def.ghi"}

    result = users.get_user_token(fake_client, "u-1")

    fake_client.get.assert_called_once_with("/users/u-1/token", params={"type": "zak"})
    assert result["token"] == "abc.def.ghi"


def test_get_user_token_forwards_type() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"token": "x"}

    users.get_user_token(fake_client, "u-1", token_type="token")

    fake_client.get.assert_called_once_with("/users/u-1/token", params={"type": "token"})


@pytest.mark.parametrize("bad_type", ["bogus", "", "ZAK", "z a k"])
def test_get_user_token_rejects_unknown_type(bad_type: str) -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="token_type"):
        users.get_user_token(fake_client, "u-1", token_type=bad_type)


def test_allowed_user_token_types_pinned() -> None:
    """Pinned set — Zoom currently supports zak / token / zpk for
    user-level token requests."""
    assert "zak" in users.ALLOWED_USER_TOKEN_TYPES
    assert "token" in users.ALLOWED_USER_TOKEN_TYPES
    assert "zpk" in users.ALLOWED_USER_TOKEN_TYPES


def test_get_user_permissions_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {
        "permissions": ["AccountSettingPermission", "MeetingPermission"]
    }

    result = users.get_user_permissions(fake_client, "u-1")

    fake_client.get.assert_called_once_with("/users/u-1/permissions")
    assert "MeetingPermission" in result["permissions"]


def test_get_user_permissions_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}
    users.get_user_permissions(fake_client, "evil/../1")
    arg = fake_client.get.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


# ---- depth-completion: schedulers + assistants + presence --------------


def test_list_schedulers_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"schedulers": [{"id": "s-1", "email": "a@e.com"}]}

    result = users.list_schedulers(fake_client, "u-1")

    fake_client.get.assert_called_once_with("/users/u-1/schedulers")
    assert result["schedulers"][0]["email"] == "a@e.com"


def test_list_schedulers_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {}
    users.list_schedulers(fake_client, "evil/../1")
    arg = fake_client.get.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_delete_scheduler_targets_specific_path() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_scheduler(fake_client, "u-1", "s-1")

    fake_client.delete.assert_called_once_with("/users/u-1/schedulers/s-1")


def test_delete_scheduler_url_encodes_both_segments() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}
    users.delete_scheduler(fake_client, "u/../1", "s/../1")
    arg = fake_client.delete.call_args[0][0]
    assert arg.count("%2F") == 4
    assert "/.." not in arg


def test_delete_all_schedulers_targets_collection_path() -> None:
    """Bulk delete: same path as list, just DELETE."""
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_all_schedulers(fake_client, "u-1")

    fake_client.delete.assert_called_once_with("/users/u-1/schedulers")


def test_add_assistants_posts_payload() -> None:
    """Assistant assignment — payload contains an array of
    ``{id?, email}`` dicts. Identifying by email is the common case."""
    fake_client = MagicMock()
    fake_client.post.return_value = {
        "ids": "a-1,a-2",
        "add_at": "2026-04-30T12:00:00Z",
    }

    payload = {"assistants": [{"email": "alice@e.com"}, {"email": "bob@e.com"}]}
    result = users.add_assistants(fake_client, "u-1", payload)

    fake_client.post.assert_called_once_with("/users/u-1/assistants", json=payload)
    assert result["ids"] == "a-1,a-2"


def test_delete_assistant_targets_specific_path() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_assistant(fake_client, "u-1", "a-1")

    fake_client.delete.assert_called_once_with("/users/u-1/assistants/a-1")


def test_delete_all_assistants_targets_collection_path() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_all_assistants(fake_client, "u-1")

    fake_client.delete.assert_called_once_with("/users/u-1/assistants")


def test_get_presence_targets_correct_path() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"status": "Available"}

    result = users.get_presence(fake_client, "u-1")

    fake_client.get.assert_called_once_with("/users/u-1/presence_status")
    assert result["status"] == "Available"


def test_set_presence_puts_status_with_action() -> None:
    """PUT body is {status: <state>}; Zoom's API quirk."""
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    users.set_presence(fake_client, "u-1", status="Do_Not_Disturb")

    fake_client.put.assert_called_once_with(
        "/users/u-1/presence_status", json={"status": "Do_Not_Disturb"}
    )


@pytest.mark.parametrize("bad_status", ["bogus", "", "available", "DND"])
def test_set_presence_rejects_unknown_status(bad_status: str) -> None:
    """Pinned set — case-sensitive and exact (Zoom uses Available /
    Away / Do_Not_Disturb / In_Calendar_Event etc.)."""
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="status"):
        users.set_presence(fake_client, "u-1", status=bad_status)


def test_allowed_presence_statuses_pinned() -> None:
    assert "Available" in users.ALLOWED_PRESENCE_STATUSES
    assert "Away" in users.ALLOWED_PRESENCE_STATUSES
    assert "Do_Not_Disturb" in users.ALLOWED_PRESENCE_STATUSES


# ---- depth-completion: update_user + SSO revoke + virtual backgrounds --


def test_update_user_patches_user_path() -> None:
    """PATCH /users/<id> — partial update on the user profile."""
    fake_client = MagicMock()
    fake_client.patch.return_value = {}

    payload = {"first_name": "Alice", "last_name": "Smith", "language": "en-US"}
    users.update_user(fake_client, "u-1", payload)

    fake_client.patch.assert_called_once_with("/users/u-1", json=payload)


def test_update_user_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.patch.return_value = {}
    users.update_user(fake_client, "evil/../1", {})
    arg = fake_client.patch.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_revoke_sso_token_targets_correct_path() -> None:
    """PUT /users/<id>/sso_token — invalidates all active SSO sessions."""
    fake_client = MagicMock()
    fake_client.put.return_value = {}

    users.revoke_sso_token(fake_client, "u-1")

    fake_client.put.assert_called_once_with("/users/u-1/sso_token")


def test_revoke_sso_token_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.put.return_value = {}
    users.revoke_sso_token(fake_client, "evil/../1")
    arg = fake_client.put.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg


def test_list_virtual_backgrounds_walks_pagination() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        {"files": [{"id": "vb-1"}, {"id": "vb-2"}], "next_page_token": "tok-2"},
        {"files": [{"id": "vb-3"}], "next_page_token": ""},
    ]

    result = list(users.list_virtual_backgrounds(fake_client, "u-1"))

    assert result == [{"id": "vb-1"}, {"id": "vb-2"}, {"id": "vb-3"}]
    first = fake_client.get.call_args_list[0]
    assert first[0][0] == "/users/u-1/settings/virtual_backgrounds"


def test_list_virtual_backgrounds_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = {"files": [], "next_page_token": ""}
    list(users.list_virtual_backgrounds(fake_client, "evil/../1"))
    call_path = fake_client.get.call_args_list[0][0][0]
    assert "/.." not in call_path
    assert "%2F" in call_path


def test_delete_virtual_backgrounds_passes_ids_csv_param() -> None:
    """Zoom takes a comma-separated `ids` query param — the helper builds it."""
    fake_client = MagicMock()
    fake_client.delete.return_value = {}

    users.delete_virtual_backgrounds(fake_client, "u-1", ids=["vb-1", "vb-2"])

    fake_client.delete.assert_called_once_with(
        "/users/u-1/settings/virtual_backgrounds",
        params={"ids": "vb-1,vb-2"},
    )


def test_delete_virtual_backgrounds_rejects_empty_ids() -> None:
    fake_client = MagicMock()
    with pytest.raises(ValueError, match="at least one"):
        users.delete_virtual_backgrounds(fake_client, "u-1", ids=[])


def test_delete_virtual_backgrounds_url_encodes_id() -> None:
    fake_client = MagicMock()
    fake_client.delete.return_value = {}
    users.delete_virtual_backgrounds(fake_client, "evil/../1", ids=["vb-1"])
    arg = fake_client.delete.call_args[0][0]
    assert "/.." not in arg
    assert "%2F" in arg
