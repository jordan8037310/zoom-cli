"""Tests for zoom_cli.api.pagination — paginate() generator helper."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from zoom_cli.api import oauth
from zoom_cli.api import pagination as pagination_mod
from zoom_cli.api.client import ApiClient
from zoom_cli.auth import S2SCredentials


def _creds() -> S2SCredentials:
    return S2SCredentials(account_id="acc", client_id="cid", client_secret="csec")


def _fresh_token() -> oauth.AccessToken:
    return oauth.AccessToken(
        value="tok",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes=("user:read:list_users:admin",),
    )


def _api(handler, monkeypatch: pytest.MonkeyPatch) -> tuple[ApiClient, httpx.Client]:
    monkeypatch.setattr(oauth, "fetch_access_token", lambda *_a, **_k: _fresh_token())
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return ApiClient(_creds(), http_client=http), http


def test_paginate_single_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """A response with empty next_page_token terminates after one fetch."""
    requests_seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "page_size": 300,
                "next_page_token": "",
                "users": [{"id": "u1"}, {"id": "u2"}],
            },
        )

    api, http = _api(handler, monkeypatch)
    with http:
        items = list(pagination_mod.paginate(api, "/users", item_key="users"))
    assert items == [{"id": "u1"}, {"id": "u2"}]
    assert len(requests_seen) == 1
    # First request must omit next_page_token (or send empty).
    assert requests_seen[0].get("next_page_token", "") == ""


def test_paginate_multi_page_walks_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three pages: each request carries the prior page's next_page_token,
    and the generator yields items in order across all pages."""
    pages = [
        {"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": "tok-page-2"},
        {"users": [{"id": "u3"}], "next_page_token": "tok-page-3"},
        {"users": [{"id": "u4"}, {"id": "u5"}], "next_page_token": ""},
    ]
    seen_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_tokens.append(request.url.params.get("next_page_token", ""))
        return httpx.Response(200, json=pages[len(seen_tokens) - 1])

    api, http = _api(handler, monkeypatch)
    with http:
        items = list(pagination_mod.paginate(api, "/users", item_key="users"))

    assert items == [{"id": "u1"}, {"id": "u2"}, {"id": "u3"}, {"id": "u4"}, {"id": "u5"}]
    # First request: empty token. Subsequent: cursor from prior response.
    assert seen_tokens == ["", "tok-page-2", "tok-page-3"]


def test_paginate_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"users": [], "next_page_token": ""})

    api, http = _api(handler, monkeypatch)
    with http:
        items = list(pagination_mod.paginate(api, "/users", item_key="users"))
    assert items == []


def test_paginate_handles_omitted_item_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Some endpoints omit the item key entirely on an empty page."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"next_page_token": ""})

    api, http = _api(handler, monkeypatch)
    with http:
        items = list(pagination_mod.paginate(api, "/users", item_key="users"))
    assert items == []


def test_paginate_passes_page_size_and_user_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(dict(request.url.params))
        return httpx.Response(200, json={"users": [], "next_page_token": ""})

    api, http = _api(handler, monkeypatch)
    with http:
        list(
            pagination_mod.paginate(
                api,
                "/users",
                item_key="users",
                params={"status": "active", "role_id": "admin"},
                page_size=100,
            )
        )

    assert captured[0]["status"] == "active"
    assert captured[0]["role_id"] == "admin"
    assert captured[0]["page_size"] == "100"


def test_paginate_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The generator must not pre-fetch; pulling one item should fetch one
    page, not the entire dataset."""
    pages = [
        {"users": [{"id": "u1"}], "next_page_token": "tok-2"},
        {"users": [{"id": "u2"}], "next_page_token": ""},
    ]
    fetch_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        n = fetch_count["n"]
        fetch_count["n"] += 1
        return httpx.Response(200, json=pages[n])

    api, http = _api(handler, monkeypatch)
    with http:
        gen = pagination_mod.paginate(api, "/users", item_key="users")
        first = next(gen)
        # After yielding one item, only the first page should have been fetched.
        assert fetch_count["n"] == 1
        assert first == {"id": "u1"}
        # Drain the rest.
        rest = list(gen)
        assert rest == [{"id": "u2"}]
        assert fetch_count["n"] == 2
