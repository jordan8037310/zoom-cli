"""Zoom Users API helpers.

Reference: https://developers.zoom.us/docs/api/users/

This module is intentionally thin — each function maps to one Zoom
endpoint and returns the raw JSON envelope. We don't wrap responses in
typed dataclasses yet because:

1. The CLI surface is the only consumer right now and it just prints
   selected fields. Boxing into a dataclass adds no value at this stage.
2. A future codegen pass against the OpenAPI spec (issue #22) will
   produce proper types — handwriting them now would just be churn.

API shape:
    :func:`get_user` is the durable helper, taking a ``user_id`` (default
    ``"me"`` — the authenticated principal). :func:`get_me` is a thin
    alias kept for the CLI ``zoom users me`` command (closes #36 — Codex
    #14 flagged that hardcoding the implicit "me" principal would make
    later target-user commands awkward).

    :func:`list_users` paginates across the ``GET /users`` endpoint via
    :func:`zoom_cli.api.pagination.paginate` (closes #16 first consumer).

Still deferred to issue #14:
- ``zoom users create`` / ``delete`` / ``settings`` CLI commands.
- ``--json`` flag for raw output.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from zoom_cli.api.client import ApiClient
from zoom_cli.api.pagination import DEFAULT_PAGE_SIZE, paginate


def get_user(client: ApiClient, user_id: str = "me") -> dict[str, Any]:
    """``GET /users/{user_id}`` — return the requested user's profile.

    Pass ``user_id="me"`` (the default) for the authenticated principal,
    or a specific Zoom user ID / email. The path segment is percent-
    encoded so caller-supplied IDs cannot inject query/path metacharacters
    even if a future CLI threads user input straight through.

    Required scopes: ``user:read:user``.
    """
    return client.get(f"/users/{quote(user_id, safe='')}")


def get_me(client: ApiClient) -> dict[str, Any]:
    """``GET /users/me`` — alias for :func:`get_user` with ``user_id="me"``.

    Kept for the ``zoom users me`` CLI command and any external callers
    that imported it from PR #31. Prefer :func:`get_user` in new code.
    """
    return get_user(client, "me")


#: Allowed values for ``zoom users create --action``. Mirrors Zoom's
#: ``action`` field on POST /users. ``create`` (default) sends an
#: invite; ``autoCreate`` provisions with a password; ``custCreate``
#: is for custom-auth managed users; ``ssoCreate`` is for SSO-managed
#: users.
ALLOWED_CREATE_ACTIONS: tuple[str, ...] = (
    "create",
    "autoCreate",
    "custCreate",
    "ssoCreate",
)

#: Allowed values for ``zoom users delete --action``. ``disassociate``
#: removes the user from this account but keeps their data and Zoom
#: identity. ``delete`` permanently removes them.
ALLOWED_DELETE_ACTIONS: tuple[str, ...] = ("disassociate", "delete")


def create_user(
    client: ApiClient,
    user_info: dict[str, Any],
    *,
    action: str = "create",
) -> dict[str, Any]:
    """``POST /users`` — create a user.

    Zoom expects ``{"action": "...", "user_info": {...}}``; this helper
    builds that envelope so callers can pass a flat ``user_info`` dict.

    Required scopes: ``user:write:admin``.
    """
    if action not in ALLOWED_CREATE_ACTIONS:
        raise ValueError(f"action must be one of {ALLOWED_CREATE_ACTIONS!r}, got {action!r}")
    return client.post("/users", json={"action": action, "user_info": user_info})


def delete_user(
    client: ApiClient,
    user_id: str,
    *,
    action: str = "disassociate",
    transfer_email: str | None = None,
    transfer_meeting: bool = False,
    transfer_recording: bool = False,
    transfer_webinar: bool = False,
) -> dict[str, Any]:
    """``DELETE /users/{user_id}`` — remove a user from the account.

    Args:
        action: ``disassociate`` (default; remove from account, keep
            user identity) or ``delete`` (permanent, irreversible).
        transfer_email: If set, transfer the user's content to this
            other user's account before deletion.
        transfer_meeting / transfer_recording / transfer_webinar:
            Which content kinds to transfer. Only meaningful when
            ``transfer_email`` is set; ignored otherwise.

    Returns ``{}`` (Zoom responds with ``204 No Content``).

    Required scopes: ``user:write:admin``.
    """
    if action not in ALLOWED_DELETE_ACTIONS:
        raise ValueError(f"action must be one of {ALLOWED_DELETE_ACTIONS!r}, got {action!r}")
    params: dict[str, Any] = {"action": action}
    if transfer_email:
        params["transfer_email"] = transfer_email
        params["transfer_meeting"] = "true" if transfer_meeting else "false"
        params["transfer_recording"] = "true" if transfer_recording else "false"
        params["transfer_webinar"] = "true" if transfer_webinar else "false"
    return client.delete(f"/users/{quote(user_id, safe='')}", params=params)


def get_user_settings(client: ApiClient, user_id: str = "me") -> dict[str, Any]:
    """``GET /users/{user_id}/settings`` — return the user's settings.

    The settings payload has ~50 fields across nested categories
    (``feature``, ``in_meeting``, ``email_notification``, etc.). The CLI
    dumps the JSON; round-trip mutate via :func:`update_user_settings`
    after editing the dump.

    Required scopes: ``user:read:settings`` or ``user:read:admin``.
    """
    return client.get(f"/users/{quote(user_id, safe='')}/settings")


def update_user_settings(
    client: ApiClient, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """``PATCH /users/{user_id}/settings`` — partial-update settings.

    ``payload`` is the (sub-)dict to merge — Zoom's PATCH semantics
    leave omitted fields untouched. Typical workflow:

        # 1. Dump current settings to a JSON file
        zoom users settings get me > settings.json
        # 2. Edit settings.json
        # 3. PATCH back
        zoom users settings update me --from-json settings.json

    Returns ``{}`` (Zoom responds with ``204 No Content``).

    Required scopes: ``user:write:settings`` or ``user:write:admin``.
    """
    return client.patch(f"/users/{quote(user_id, safe='')}/settings", json=payload)


def list_users(
    client: ApiClient,
    *,
    status: str = "active",
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """``GET /users`` — yield every user record across all pages.

    Args:
        client: Authenticated :class:`ApiClient`.
        status: Account user status filter (``active``, ``inactive``,
            ``pending``). Default matches Zoom's UI default.
        page_size: Items per page; see :data:`DEFAULT_PAGE_SIZE`. The
            ``/users`` endpoint accepts up to 300.

    Yields:
        One user dict per record. Lazy — additional pages are fetched
        only as the caller iterates.

    Required scopes: ``user:read:list_users:admin`` (or finer-grained
    equivalent for the listed account).
    """
    return paginate(
        client,
        "/users",
        item_key="users",
        params={"status": status},
        page_size=page_size,
    )


# ---- depth-completion: status + password + email + token + permissions --

#: Allowed values for ``update_user_status(action=...)``. Zoom's
#: PUT /users/<id>/status accepts only these two verbs.
ALLOWED_STATUS_ACTIONS: tuple[str, ...] = ("activate", "deactivate")

#: Allowed values for ``get_user_token(token_type=...)``. Zoom's
#: ``type`` query param at /users/<id>/token accepts:
#: - zak: start-meeting token (most common)
#: - token: SDK / web embed token
#: - zpk: host-presence token (legacy)
ALLOWED_USER_TOKEN_TYPES: tuple[str, ...] = ("zak", "token", "zpk")


def update_user_status(client: ApiClient, user_id: str, *, action: str) -> dict[str, Any]:
    """``PUT /users/{user_id}/status`` — activate or deactivate a user.

    Args:
        client: Authenticated :class:`ApiClient`.
        user_id: Zoom user ID or email.
        action: One of :data:`ALLOWED_STATUS_ACTIONS`.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``user:write:user:admin`` or admin equivalent.
    """
    if action not in ALLOWED_STATUS_ACTIONS:
        raise ValueError(f"action must be one of {ALLOWED_STATUS_ACTIONS!r}, got {action!r}")
    return client.put(f"/users/{quote(user_id, safe='')}/status", json={"action": action})


def update_user_password(client: ApiClient, user_id: str, *, new_password: str) -> dict[str, Any]:
    """``PUT /users/{user_id}/password`` — set a new password.

    The CLI should accept ``new_password`` via getpass (interactive
    masked prompt) — never as a flag (would leak through argv / shell
    history). The helper takes cleartext because it needs to put it on
    the wire.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``user:write:password:admin`` or admin equivalent.
    """
    return client.put(
        f"/users/{quote(user_id, safe='')}/password",
        json={"password": new_password},
    )


def update_user_email(client: ApiClient, user_id: str, *, new_email: str) -> dict[str, Any]:
    """``PUT /users/{user_id}/email`` — initiate an email change.

    Zoom sends the new address a confirmation link; the change isn't
    active until they click. Returns ``{}`` (Zoom responds with 204 No
    Content) — no indication of confirmation success here.

    Required scopes: ``user:write:email:admin`` or admin equivalent.
    """
    return client.put(f"/users/{quote(user_id, safe='')}/email", json={"email": new_email})


def get_user_token(
    client: ApiClient,
    user_id: str,
    *,
    token_type: str = "zak",  # noqa: S107 — "zak" is Zoom's enum value, not a credential
) -> dict[str, Any]:
    """``GET /users/{user_id}/token`` — fetch a user-level token.

    Args:
        client: Authenticated :class:`ApiClient`.
        user_id: Zoom user ID or email.
        token_type: One of :data:`ALLOWED_USER_TOKEN_TYPES`. Default
            ``"zak"`` (start-meeting token).

    Returns ``{token: str}``. The value is sensitive — anyone with a
    ``zak`` can start the user's meetings as them.

    Required scopes: ``user:read:token:admin``.
    """
    if token_type not in ALLOWED_USER_TOKEN_TYPES:
        raise ValueError(
            f"token_type must be one of {ALLOWED_USER_TOKEN_TYPES!r}, got {token_type!r}"
        )
    return client.get(f"/users/{quote(user_id, safe='')}/token", params={"type": token_type})


def get_user_permissions(client: ApiClient, user_id: str) -> dict[str, Any]:
    """``GET /users/{user_id}/permissions`` — list the user's assigned
    role + permission set.

    Returns ``{permissions: [str]}`` plus role metadata. Useful for
    "what can this user do?" audits.

    Required scopes: ``user:read:permission:admin``.
    """
    return client.get(f"/users/{quote(user_id, safe='')}/permissions")


# ---- depth-completion: schedulers + assistants + presence --------------

#: Allowed values for ``set_presence(status=...)``. Mirrors Zoom's
#: chat presence-status enum. Case-sensitive and exact (``DND`` is NOT
#: an alias — Zoom uses ``Do_Not_Disturb``).
ALLOWED_PRESENCE_STATUSES: tuple[str, ...] = (
    "Available",
    "Away",
    "Do_Not_Disturb",
    "In_Calendar_Event",
    "Presenting",
    "In_A_Zoom_Meeting",
    "On_A_Call",
)


def list_schedulers(client: ApiClient, user_id: str) -> dict[str, Any]:
    """``GET /users/{user_id}/schedulers`` — list users authorized to
    schedule meetings on behalf of this user.

    Returns ``{schedulers: [{id, email}, ...]}``.

    Required scopes: ``user:read:user``.
    """
    return client.get(f"/users/{quote(user_id, safe='')}/schedulers")


def delete_scheduler(client: ApiClient, user_id: str, scheduler_id: str) -> dict[str, Any]:
    """``DELETE /users/{user_id}/schedulers/{scheduler_id}`` — revoke
    one scheduler's permission.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``user:write:scheduler:admin``.
    """
    return client.delete(
        f"/users/{quote(user_id, safe='')}/schedulers/{quote(scheduler_id, safe='')}"
    )


def delete_all_schedulers(client: ApiClient, user_id: str) -> dict[str, Any]:
    """``DELETE /users/{user_id}/schedulers`` — revoke all schedulers
    in one call. Same path as :func:`list_schedulers`, just DELETE.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``user:write:scheduler:admin``.
    """
    return client.delete(f"/users/{quote(user_id, safe='')}/schedulers")


def add_assistants(client: ApiClient, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """``POST /users/{user_id}/assistants`` — assign assistants who
    can manage meetings on behalf of this user.

    ``payload`` is ``{assistants: [{id?, email}, ...]}``. Identifying
    by email is the common case; ``id`` is for already-known Zoom user
    IDs.

    Returns Zoom's response with comma-separated assistant IDs and
    assignment timestamp.

    Required scopes: ``user:write:assistant:admin``.
    """
    return client.post(f"/users/{quote(user_id, safe='')}/assistants", json=payload)


def delete_assistant(client: ApiClient, user_id: str, assistant_id: str) -> dict[str, Any]:
    """``DELETE /users/{user_id}/assistants/{assistant_id}`` — revoke
    one assistant.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``user:write:assistant:admin``.
    """
    return client.delete(
        f"/users/{quote(user_id, safe='')}/assistants/{quote(assistant_id, safe='')}"
    )


def delete_all_assistants(client: ApiClient, user_id: str) -> dict[str, Any]:
    """``DELETE /users/{user_id}/assistants`` — revoke all assistants
    in one call. Same path as :func:`add_assistants`, just DELETE.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``user:write:assistant:admin``.
    """
    return client.delete(f"/users/{quote(user_id, safe='')}/assistants")


def get_presence(client: ApiClient, user_id: str) -> dict[str, Any]:
    """``GET /users/{user_id}/presence_status`` — fetch the user's
    current chat presence status.

    Returns ``{status: str}`` where status is one of
    :data:`ALLOWED_PRESENCE_STATUSES`.

    Required scopes: ``user:read:user`` or chat-specific equivalent.
    """
    return client.get(f"/users/{quote(user_id, safe='')}/presence_status")


def set_presence(client: ApiClient, user_id: str, *, status: str) -> dict[str, Any]:
    """``PUT /users/{user_id}/presence_status`` — set presence status.

    Args:
        client: Authenticated :class:`ApiClient`.
        user_id: Zoom user ID. Setting on others requires admin scope;
            self-set works with the user's own OAuth.
        status: One of :data:`ALLOWED_PRESENCE_STATUSES`.

    Returns ``{}`` (Zoom responds with 204 No Content).

    Required scopes: ``user:write:presence_status:admin`` or
    ``user:write:presence_status`` (self).
    """
    if status not in ALLOWED_PRESENCE_STATUSES:
        raise ValueError(f"status must be one of {ALLOWED_PRESENCE_STATUSES!r}, got {status!r}")
    return client.put(
        f"/users/{quote(user_id, safe='')}/presence_status",
        json={"status": status},
    )
