"""Tests for zoom_cli.api.users — Users endpoint helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

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
