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
