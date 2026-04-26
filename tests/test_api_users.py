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
