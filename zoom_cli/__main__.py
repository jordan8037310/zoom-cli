import functools
import os

import click
import httpx
import keyring.errors
import questionary
from click_default_group import DefaultGroup

from zoom_cli import auth
from zoom_cli.api import (
    chat,
    dashboard,
    meetings,
    oauth,
    phone,
    recordings,
    reports,
    user_oauth,
    users,
    webhook,
)
from zoom_cli.api.client import ApiClient, ZoomApiError
from zoom_cli.commands import (
    _edit,
    _launch_name,
    _launch_url,
    _ls,
    _remove,
    _save_id_password,
    _save_url,
)
from zoom_cli.utils import __version__, get_meeting_names, looks_like_zoom_url


def _ask_or_abort(question):
    """Run a questionary question; abort cleanly if the user cancels (Ctrl-C).

    questionary's ``.ask()`` returns ``None`` on cancellation. Letting that
    propagate as ``""`` was a regression from the PyInquirer version (which
    raised KeyboardInterrupt) — empty strings silently fell through into the
    next prompt or into a downstream KeyError. Here we map ``None`` to
    ``click.Abort`` so the user sees a clean exit.
    """
    answer = question.ask()
    if answer is None:
        raise click.Abort
    return answer


# ---- error translation -----------------------------------------------------
#
# Closes #41 / #43: keyring failures should surface as actionable CLI
# errors, not Python tracebacks. We split the error space three ways so the
# user knows what to do:
#
#   - NoKeyringError / InitError → no backend at all (exit 2).
#     Action: install/configure a keyring backend.
#   - Other KeyringError → backend present but refused (exit 3).
#     Action: unlock the keychain.
#   - Anything else → propagates normally.
#
# Decorator order in command stacks: place ``@_translate_keyring_errors``
# closest to ``def`` so it wraps the bare function. Click options decorate
# the wrapper next, then ``@s2s.command`` registers the wrapped command.


def _translate_keyring_errors(func):
    """Map keyring exceptions to friendly CLI exits with distinct codes."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (keyring.errors.NoKeyringError, keyring.errors.InitError) as exc:
            click.echo(
                f"OS keyring backend not available: {exc}\n"
                "Install or configure a keyring backend before retrying.",
                err=True,
            )
            raise click.exceptions.Exit(code=2) from exc
        except keyring.errors.KeyringError as exc:
            click.echo(
                f"OS keyring error (the backend may be locked): {exc}\n"
                "Unlock your keychain and retry.",
                err=True,
            )
            raise click.exceptions.Exit(code=3) from exc

    return wrapper


@click.group(cls=DefaultGroup, default="launch", default_if_no_args=True)
@click.version_option(__version__)
def main():
    pass


@main.command(help="Launch meeting [url or saved meeting name]")
@click.argument("url_or_name")
def launch(url_or_name):
    # Distinguish URL from saved-meeting-name by checking the host, not by
    # substring match against "zoom.us" — the substring trick mis-routed
    # deceptive inputs like "https://evil.example/zoom.us/j/1". Closes #38.
    has_scheme = "://" in url_or_name
    if has_scheme and not looks_like_zoom_url(url_or_name):
        click.echo(f"Refusing to launch URL with untrusted host: {url_or_name}", err=True)
        raise click.exceptions.Exit(code=1)
    if has_scheme or looks_like_zoom_url(url_or_name):
        _launch_url(url_or_name)
    else:
        _launch_name(url_or_name)


@main.command(help="Save meeting")
@click.option("--name", "-n", default="", help="Meeting name")
@click.option("--url", default="", help="Zoom URL (must provide this or meeting ID/password)")
@click.option("--id", default="", help="Zoom meeting ID")
@click.option("--password", "-p", default="", help="Zoom password")
def save(name, url, id, password):
    if not name:
        name = _ask_or_abort(questionary.text("Meeting name:"))

    save_as_url: bool | None = None
    if not url and not id:
        choice = _ask_or_abort(
            questionary.select(
                "Store as URL or Meeting ID/Password?",
                choices=["URL", "Meeting ID/Password"],
            )
        )
        save_as_url = choice == "URL"

    if not url and save_as_url is True:
        url = _ask_or_abort(questionary.text("Zoom URL:"))

    if url and save_as_url is True and "pwd=" not in url:
        password = _ask_or_abort(questionary.text("Meeting password:"))

    if not id and save_as_url is False:
        id = _ask_or_abort(questionary.text("Meeting ID:"))
        password = _ask_or_abort(questionary.text("Meeting password:"))

    if name and url:
        _save_url(name, url, password)
    elif name and id:
        _save_id_password(name, id, password)


@main.command(help="Edit meeting")
@click.option("--name", "-n", default="", help="Meeting name")
@click.option("--url", default="", help="Zoom URL (must provide this or meeting ID/password)")
@click.option("--id", default="", help="Zoom meeting ID")
@click.option("--password", "-p", default="", help="Zoom password")
def edit(name, url, id, password):
    if not name:
        choices = get_meeting_names()
        if not choices:
            click.echo("No saved meetings to edit.")
            return
        name = _ask_or_abort(questionary.select("Meeting name:", choices=choices))

    _edit(name, url, id, password)


@main.command(help="Delete meeting")
@click.argument("name", required=False)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be deleted without modifying meetings.json.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt that fires when the name is picked interactively.",
)
def rm(name, dry_run, yes):
    name_was_picked_interactively = not name
    if name_was_picked_interactively:
        choices = get_meeting_names()
        if not choices:
            click.echo("No saved meetings to remove.")
            return
        name = _ask_or_abort(questionary.select("Meeting name:", choices=choices))

    if dry_run:
        click.echo(f"[dry-run] Would remove meeting: {name}")
        return

    # Only confirm if the name came from the interactive selector — a positional
    # `zoom rm <name>` is already a deliberate choice, and adding a prompt would
    # break existing scripts and aliases.
    needs_confirm = name_was_picked_interactively and not yes
    if needs_confirm and not click.confirm(f"Remove meeting '{name}'?", default=False):
        click.echo("Aborted.")
        return

    _remove(name)


@main.command(help="List all saved meetings")
def ls():
    _ls()


# ---- API authentication ---------------------------------------------------


@main.group("auth", help="Manage Zoom API authentication.")
def auth_cmd():
    """Top-level group for ``zoom auth ...``.

    Function name has the ``_cmd`` suffix to avoid shadowing the ``auth``
    module imported above; Click registers it under the bare name ``auth``.
    """


@auth_cmd.group("s2s", help="Server-to-Server OAuth credential management.")
def s2s():
    """Group for ``zoom auth s2s ...``."""


@s2s.command(
    "set",
    help=(
        "Save Server-to-Server OAuth credentials to the OS keyring. "
        "The client secret is read from the ZOOM_CLIENT_SECRET env var or, "
        "if unset, prompted interactively (masked). It is intentionally NOT "
        "accepted as a command-line flag (closes #34)."
    ),
)
@click.option("--account-id", default="", envvar="ZOOM_ACCOUNT_ID", help="Zoom Account ID")
@click.option(
    "--client-id",
    default="",
    envvar="ZOOM_CLIENT_ID",
    help="Server-to-Server OAuth Client ID",
)
@_translate_keyring_errors
def s2s_set(account_id, client_id):
    if not account_id:
        account_id = _ask_or_abort(questionary.text("Account ID:"))
    if not client_id:
        client_id = _ask_or_abort(questionary.text("Client ID:"))

    # Client secret is intentionally NOT a CLI flag — values in argv land in
    # shell history and are visible via `ps`/proc to other users on the host
    # for the lifetime of the command. Accept via masked prompt or the
    # ZOOM_CLIENT_SECRET env var only. Closes #34.
    client_secret = os.environ.get("ZOOM_CLIENT_SECRET", "")
    if not client_secret:
        # questionary.password() masks the input on screen. The default
        # text() prompt would echo the secret to the terminal.
        client_secret = _ask_or_abort(questionary.password("Client Secret:"))

    auth.save_s2s_credentials(
        auth.S2SCredentials(
            account_id=account_id,
            client_id=client_id,
            client_secret=client_secret,
        )
    )
    click.echo("Server-to-Server OAuth credentials saved.")


@s2s.command(
    "test",
    help="Verify saved Server-to-Server OAuth credentials by exchanging them for a token.",
)
@_translate_keyring_errors
def s2s_test():
    creds = auth.load_s2s_credentials()
    if creds is None:
        click.echo("No Server-to-Server OAuth credentials saved. Run `zoom auth s2s set` first.")
        raise click.exceptions.Exit(code=1)

    try:
        token = oauth.fetch_access_token(creds)
    except oauth.ZoomAuthError as exc:
        message = str(exc) or "(no message)"
        if exc.status_code is not None:
            click.echo(f"Authentication failed (HTTP {exc.status_code}): {message}")
        else:
            click.echo(f"Authentication failed: {message}")
        raise click.exceptions.Exit(code=1) from exc
    except httpx.HTTPError as exc:
        # Network / TLS / timeout — the request never got an HTTP response
        # we can interpret. Distinguish from auth failures so the user
        # knows whether to check creds or check connectivity.
        click.echo(f"Could not reach Zoom OAuth endpoint: {exc}")
        raise click.exceptions.Exit(code=1) from exc

    minutes = max(int((token.expires_at - _now()).total_seconds() // 60), 0)
    click.echo(f"OK — Server-to-Server OAuth credentials valid (token expires in {minutes}m).")
    if token.scopes:
        click.echo(f"Scopes: {' '.join(token.scopes)}")


def _now():
    """Indirection for ``datetime.now`` so tests can monkeypatch it cleanly."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


@auth_cmd.command(help="Show which authentication mode is configured.")
def status():
    """``status`` deliberately does NOT use ``@_translate_keyring_errors``.

    ``has_*_credentials`` swallow backend-missing errors themselves and
    report "not configured", which is the right UX for a probe-style
    command — you don't want a 'check status' to crash the script. Users
    debugging a missing backend should run ``zoom auth s2s test`` (which
    surfaces the backend error).

    Reports both auth surfaces — S2S (account-wide) and User OAuth
    (per-developer, closes #12).
    """
    if auth.has_s2s_credentials():
        click.echo("Server-to-Server OAuth: configured")
    else:
        click.echo("Server-to-Server OAuth: not configured")
        click.echo("  Run `zoom auth s2s set` to configure.")

    if auth.has_user_oauth_credentials():
        click.echo("User OAuth (PKCE): configured")
    else:
        click.echo("User OAuth (PKCE): not configured")
        click.echo("  Run `zoom auth login --client-id <id>` to configure.")


@auth_cmd.command(help="Clear ALL stored API authentication credentials (S2S + user OAuth).")
@_translate_keyring_errors
def logout():
    auth.clear_s2s_credentials()
    auth.clear_user_oauth_credentials()
    click.echo("Cleared Server-to-Server OAuth credentials.")
    click.echo("Cleared User OAuth credentials.")


@auth_cmd.command(
    "login",
    help=(
        "Authenticate as a Zoom user via OAuth 2.0 + PKCE (3-legged flow). "
        "Opens the browser; captures the redirect on a loopback port; "
        "exchanges the auth code for a refresh_token (stored in OS keyring)."
    ),
)
@click.option(
    "--client-id",
    required=True,
    envvar="ZOOM_USER_CLIENT_ID",
    help="OAuth Client ID for a user-managed (not S2S) app. Picks up ZOOM_USER_CLIENT_ID env var.",
)
@click.option(
    "--port",
    type=click.IntRange(0, 65535),
    default=0,
    show_default=True,
    help="Loopback port for the OAuth redirect. 0 = pick an ephemeral port.",
)
@click.option(
    "--timeout",
    type=click.IntRange(10, 1800),
    default=300,
    show_default=True,
    help="Seconds to wait for the browser callback.",
)
@click.option(
    "--no-browser",
    is_flag=True,
    default=False,
    help="Don't try to open a browser; just print the auth URL for manual paste.",
)
@_translate_keyring_errors
def auth_login(client_id, port, timeout, no_browser):
    """Closes #12. Refresh token persists across CLI invocations; access
    token (1-hour lifetime) lives only in memory and is re-minted via
    refresh as needed."""

    def _no_browser(_url):
        # webbrowser.open returns bool; mimic that.
        return False

    browser = _no_browser if no_browser else None

    def _print_url(url):
        click.echo(f"Open this URL in a browser to authorize:\n  {url}")

    try:
        tokens = user_oauth.run_pkce_flow(
            client_id,
            port=port,
            browser=browser,
            timeout=float(timeout),
            on_url=_print_url,
        )
    except user_oauth.ZoomUserAuthError as exc:
        click.echo(f"OAuth failed: {exc}", err=True)
        raise click.exceptions.Exit(code=1) from exc
    except TimeoutError as exc:
        click.echo(f"Timed out waiting for browser callback: {exc}", err=True)
        raise click.exceptions.Exit(code=1) from exc
    except httpx.HTTPError as exc:
        click.echo(f"Could not reach Zoom OAuth endpoint: {exc}", err=True)
        raise click.exceptions.Exit(code=1) from exc

    auth.save_user_oauth_credentials(
        auth.UserOAuthCredentials(
            refresh_token=tokens.refresh_token,
            client_id=client_id,
        )
    )
    minutes = max(int((tokens.expires_at - _now()).total_seconds() // 60), 0)
    click.echo(f"Logged in. Refresh token saved to keyring; access token expires in {minutes}m.")
    if tokens.scopes:
        click.echo(f"Scopes: {' '.join(tokens.scopes)}")


# ---- Zoom Users REST API -------------------------------------------------


@main.group("users", help="Zoom Users API (https://developers.zoom.us/docs/api/users/).")
def users_cmd():
    """Group for ``zoom users ...``."""


# Fields printed by `zoom users me` and `zoom users get`. The full Zoom
# user payload has many dozen fields; users who want all of them can pipe
# the underlying call through `jq` once we add `--json` (separate issue).
_USER_PROFILE_FIELDS = ("display_name", "email", "id", "account_id", "type", "status")


def _print_user_profile(profile: dict) -> None:
    """Print the well-known subset of a Zoom user payload, one field per line."""
    for field in _USER_PROFILE_FIELDS:
        if field in profile:
            click.echo(f"{field}: {profile[field]}")


def _load_creds_or_exit():
    """Load credentials for an API call; preferring user-OAuth when configured.

    Resolution order (newer auth surfaces win):
      1. User-OAuth (``zoom auth login`` / PKCE) — preferred when set.
      2. S2S OAuth (``zoom auth s2s set``) — the original flow.
      3. Neither → exit 1 with a friendly message pointing at both
         setup commands.

    Backward compat: if a CLI command tests for the legacy "No Server-
    to-Server OAuth credentials saved" message, it'll still match for
    the no-creds-at-all case (the message starts with that line).
    """
    user_creds = auth.load_user_oauth_credentials()
    if user_creds is not None:
        return user_creds
    s2s_creds = auth.load_s2s_credentials()
    if s2s_creds is not None:
        return s2s_creds
    click.echo(
        "No Server-to-Server OAuth credentials saved. Run one of:\n"
        "  zoom auth s2s set                       # Server-to-Server OAuth\n"
        "  zoom auth login --client-id ID          # 3-legged user OAuth"
    )
    raise click.exceptions.Exit(code=1)


def _build_api_client(creds):
    """Construct an ``ApiClient`` with the right callbacks for the cred type.

    For user-OAuth credentials, every refresh rotates the persisted
    refresh_token (Zoom invalidates the old one immediately), so we pass
    a callback that writes the new value back to the keyring
    transactionally (mirrors the #35 rollback pattern) — without it,
    the next CLI invocation would have a dead refresh_token.
    """
    if isinstance(creds, auth.UserOAuthCredentials):
        return ApiClient(
            creds,
            on_user_token_rotated=auth.save_user_oauth_credentials,
        )
    return ApiClient(creds)


def _exit_on_api_error(exc: Exception) -> None:
    """Print a typed message for Zoom API / network errors, then exit 1.

    Centralises the three-way error handling that every API CLI command
    needs: ``ZoomAuthError`` (HTTP from token endpoint), ``ZoomApiError``
    (HTTP from the API endpoint), ``httpx.HTTPError`` (network / TLS /
    timeout). Callers should ``raise`` the result so type checkers and
    readers see the control flow.
    """
    if isinstance(exc, oauth.ZoomAuthError):
        click.echo(f"Authentication failed (HTTP {exc.status_code}): {exc}")
    elif isinstance(exc, ZoomApiError):
        click.echo(f"Zoom API error (HTTP {exc.status_code}): {exc}")
    elif isinstance(exc, httpx.HTTPError):
        click.echo(f"Could not reach Zoom API: {exc}")
    else:
        # Should never happen — caller filters before delegating.
        raise exc
    raise click.exceptions.Exit(code=1) from exc


@users_cmd.command("me", help="Print the authenticated user's profile (GET /users/me).")
@_translate_keyring_errors
def users_me():
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            profile = users.get_me(client)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    _print_user_profile(profile)


@users_cmd.command("get", help="Print a specific user's profile (GET /users/<user-id>).")
@click.argument("user_id")
@_translate_keyring_errors
def users_get(user_id):
    """``user_id`` is either a Zoom user ID or an email address. Closes #14
    (read-only piece) — write commands (create/delete/settings) are a
    follow-up that needs separate confirmation-flow design."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            profile = users.get_user(client, user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    _print_user_profile(profile)


@users_cmd.command("list", help="List users in the account (paginates GET /users).")
@click.option(
    "--status",
    type=click.Choice(["active", "inactive", "pending"]),
    default="active",
    show_default=True,
    help="Filter by Zoom user status.",
)
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
    help="Items per page request (Zoom caps `/users` at 300).",
)
@_translate_keyring_errors
def users_list(status, page_size):
    """Output is tab-separated (id\\temail\\ttype\\tstatus) so it pipes into
    ``cut``/``awk``/``column``. Pagination is handled transparently;
    multi-page accounts may take a few seconds.

    Closes #14 (read-only piece) — uses the ``paginate()`` helper from
    PR #48 / issue #16."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("user_id\temail\ttype\tstatus")
            for user in users.list_users(client, status=status, page_size=page_size):
                click.echo(
                    f"{user.get('id', '')}\t"
                    f"{user.get('email', '')}\t"
                    f"{user.get('type', '')}\t"
                    f"{user.get('status', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


# ---- Zoom Meetings REST API ---------------------------------------------


@main.group(
    "meetings",
    help="Zoom Meetings API (https://developers.zoom.us/docs/api/meetings/).",
)
def meetings_cmd():
    """Group for ``zoom meetings ...``."""


# Fields printed by ``zoom meetings get``. Same one-per-line shape as
# ``zoom users me`` for visual consistency.
_MEETING_DETAIL_FIELDS = (
    "id",
    "topic",
    "type",
    "status",
    "start_time",
    "duration",
    "timezone",
    "host_email",
    "join_url",
)


def _print_meeting_detail(meeting: dict) -> None:
    for field in _MEETING_DETAIL_FIELDS:
        if field in meeting:
            click.echo(f"{field}: {meeting[field]}")


@meetings_cmd.command("get", help="Print one meeting's details (GET /meetings/<meeting-id>).")
@click.argument("meeting_id")
@_translate_keyring_errors
def meetings_get(meeting_id):
    """``meeting_id`` is the numeric Zoom meeting ID. Closes #13 (read-only
    piece) — write commands (create / update / delete / end) are a follow-up
    that needs separate confirmation-flow design."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meeting = meetings.get_meeting(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    _print_meeting_detail(meeting)


@meetings_cmd.command(
    "list", help="List meetings for a user (paginates GET /users/<user-id>/meetings)."
)
@click.option(
    "--user-id",
    default="me",
    show_default=True,
    help="Whose meetings to list. Default 'me' (the authenticated user).",
)
@click.option(
    "--type",
    "meeting_type",
    type=click.Choice(list(meetings.ALLOWED_LIST_TYPES)),
    default="scheduled",
    show_default=True,
    help="Zoom's `type` filter.",
)
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
    help="Items per page request (Zoom caps `/users/{userId}/meetings` at 300).",
)
@_translate_keyring_errors
def meetings_list(user_id, meeting_type, page_size):
    """Output is tab-separated (id\\ttopic\\ttype\\tstart_time\\tduration) so
    it pipes into cut/awk/column. Pagination is handled transparently
    (PR #48 / #16). Closes #13 (read-only piece)."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\ttopic\ttype\tstart_time\tduration")
            for meeting in meetings.list_meetings(
                client,
                user_id=user_id,
                meeting_type=meeting_type,
                page_size=page_size,
            ):
                click.echo(
                    f"{meeting.get('id', '')}\t"
                    f"{meeting.get('topic', '')}\t"
                    f"{meeting.get('type', '')}\t"
                    f"{meeting.get('start_time', '')}\t"
                    f"{meeting.get('duration', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


# ---- Zoom Users — write commands + settings ----------------------------
#
# Closes #14 (write piece). Confirmation flow:
#   - `delete <id>` always prompts unless --yes (deleting a user is high-
#     blast-radius — affects their meetings, recordings, scheduled
#     invitees). Permanent (`--action delete`) wording is louder than
#     disassociate.
#   - `settings get` is read-only; `settings update` is deferred to
#     follow-up because the field surface is too big to flag-map cleanly.


@users_cmd.command("create", help="Create a user (POST /users).")
@click.option("--email", required=True, help="The new user's email address.")
@click.option(
    "--type",
    "user_type",
    type=click.IntRange(1, 3),
    required=True,
    help="1=Basic, 2=Licensed, 3=On-prem.",
)
@click.option("--first-name", help="Given name.")
@click.option("--last-name", help="Family name.")
@click.option("--display-name", help="Display name; defaults to first+last.")
@click.option(
    "--password",
    help="Initial password; only honoured with --action autoCreate.",
)
@click.option(
    "--action",
    type=click.Choice(list(users.ALLOWED_CREATE_ACTIONS)),
    default="create",
    show_default=True,
    help=(
        "create: invite by email; autoCreate: provision with password; "
        "custCreate: custom-auth managed; ssoCreate: SSO-managed."
    ),
)
@_translate_keyring_errors
def users_create(email, user_type, first_name, last_name, display_name, password, action):
    user_info: dict = {"email": email, "type": user_type}
    if first_name is not None:
        user_info["first_name"] = first_name
    if last_name is not None:
        user_info["last_name"] = last_name
    if display_name is not None:
        user_info["display_name"] = display_name
    if password is not None:
        user_info["password"] = password

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            created = users.create_user(client, user_info, action=action)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    _print_user_profile(created)


@users_cmd.command("delete", help="Delete or disassociate a user (DELETE /users/<user-id>).")
@click.argument("user_id")
@click.option(
    "--action",
    type=click.Choice(list(users.ALLOWED_DELETE_ACTIONS)),
    default="disassociate",
    show_default=True,
    help=(
        "disassociate: remove from this account but keep the user's "
        "Zoom identity; delete: permanent, irreversible."
    ),
)
@click.option(
    "--transfer-email",
    help=(
        "Transfer the user's content to this email before deletion "
        "(meetings/recordings/webinars per the --transfer-* flags below)."
    ),
)
@click.option(
    "--transfer-meetings",
    is_flag=True,
    default=False,
    help="Transfer scheduled meetings (only with --transfer-email).",
)
@click.option(
    "--transfer-recordings",
    is_flag=True,
    default=False,
    help="Transfer cloud recordings (only with --transfer-email).",
)
@click.option(
    "--transfer-webinars",
    is_flag=True,
    default=False,
    help="Transfer scheduled webinars (only with --transfer-email).",
)
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip the confirmation prompt.")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would happen without calling the API.",
)
@_translate_keyring_errors
def users_delete(
    user_id,
    action,
    transfer_email,
    transfer_meetings,
    transfer_recordings,
    transfer_webinars,
    yes,
    dry_run,
):
    """Always confirms unless --yes — deleting a user has high blast
    radius (affects their meetings, recordings, and any invitees)."""
    if dry_run:
        click.echo(f"[dry-run] Would {action} user {user_id}")
        if transfer_email:
            click.echo(
                f"[dry-run] transfer to {transfer_email}: "
                f"meetings={transfer_meetings} "
                f"recordings={transfer_recordings} "
                f"webinars={transfer_webinars}"
            )
        return

    if not yes:
        if action == "delete":
            prompt = f"Permanently delete user {user_id}? This cannot be undone."
        else:
            prompt = f"Disassociate user {user_id} from this account?"
        if not click.confirm(prompt, default=False):
            click.echo("Aborted.")
            return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            users.delete_user(
                client,
                user_id,
                action=action,
                transfer_email=transfer_email,
                transfer_meeting=transfer_meetings,
                transfer_recording=transfer_recordings,
                transfer_webinar=transfer_webinars,
            )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    verb = "Deleted" if action == "delete" else "Disassociated"
    click.echo(f"{verb} user {user_id}.")


@users_cmd.group("settings", help="Read or update a user's account settings.")
def users_settings_cmd():
    """Group for ``zoom users settings ...``.

    Two-step round trip for mass updates:

      zoom users settings get me > settings.json   # dump
      # edit settings.json
      zoom users settings update me --from-json settings.json   # patch back

    Per-field flags aren't exposed (~50 fields across nested
    categories); the round-trip flow is more practical and avoids the
    coverage / staleness problem of mirroring Zoom's full schema."""


@users_settings_cmd.command(
    "get",
    help="Print a user's settings as JSON (GET /users/<user-id>/settings).",
)
@click.argument("user_id", default="me", required=False)
@_translate_keyring_errors
def users_settings_get(user_id):
    """Default user is ``me``. Output is the raw JSON payload from
    Zoom — pipe through ``jq`` for readable output or to extract
    specific fields."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            settings = users.get_user_settings(client, user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(settings, indent=2, sort_keys=True))


@users_settings_cmd.command(
    "update",
    help="PATCH a user's settings from a JSON file (PATCH /users/<user-id>/settings).",
)
@click.argument("user_id", default="me", required=False)
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    required=True,
    help=(
        "Path to a JSON file containing the (sub-)payload to PATCH. "
        "Use '-' for stdin. Typical workflow: pipe `zoom users settings "
        "get me` through `jq`, edit, then PATCH back."
    ),
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the parsed payload without calling the API.",
)
@_translate_keyring_errors
def users_settings_update(user_id, from_json, yes, dry_run):
    """Zoom PATCH semantics: omitted keys are left untouched, so passing
    a partial dict only changes the keys you include. Always confirms
    unless ``--yes`` (settings changes can be invasive — disabling
    waiting rooms, screen sharing, etc. has security implications)."""
    import json as _json

    try:
        payload = _json.load(from_json)
    except _json.JSONDecodeError as exc:
        click.echo(f"Invalid JSON in --from-json input: {exc}", err=True)
        raise click.exceptions.Exit(code=1) from exc

    if not isinstance(payload, dict):
        click.echo(
            f"--from-json input must be a JSON object (dict), got {type(payload).__name__}.",
            err=True,
        )
        raise click.exceptions.Exit(code=1)

    if dry_run:
        click.echo(f"[dry-run] Would PATCH /users/{user_id}/settings with:")
        click.echo(_json.dumps(payload, indent=2, sort_keys=True))
        return

    if not yes:
        # Surface the top-level keys being changed so the user knows
        # what they're agreeing to without having to scroll the body.
        keys = ", ".join(sorted(payload.keys())) or "(empty)"
        if not click.confirm(
            f"Update settings for user {user_id}? Top-level keys: {keys}",
            default=False,
        ):
            click.echo("Aborted.")
            return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            users.update_user_settings(client, user_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Updated settings for user {user_id}.")


# ---- Users depth-completion: status + password + email + token + perms --


def _user_status_action(action: str, action_past: str):
    """Build one of the ``activate`` / ``deactivate`` subcommands.

    Same factory pattern as the registrant status verbs — extract the
    shared confirmation + dispatch shape so the per-verb body is empty."""

    @users_cmd.command(
        action,
        help=f"{action.capitalize()} a user (PUT /users/<user-id>/status, action={action}).",
    )
    @click.argument("user_id")
    @click.option(
        "--yes",
        "-y",
        is_flag=True,
        default=False,
        help="Skip the confirmation prompt.",
    )
    @_translate_keyring_errors
    def _cmd(user_id, yes):
        if not yes and not click.confirm(f"{action.capitalize()} user {user_id}?", default=False):
            click.echo("Aborted.")
            return
        creds = _load_creds_or_exit()
        try:
            with _build_api_client(creds) as client:
                users.update_user_status(client, user_id, action=action)
        except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
            _exit_on_api_error(exc)
        click.echo(f"{action_past} user {user_id}.")

    _cmd.__name__ = f"users_{action}"
    return _cmd


_users_activate = _user_status_action("activate", "Activated")
_users_deactivate = _user_status_action("deactivate", "Deactivated")


@users_cmd.command(
    "password",
    help="Reset a user's password (PUT /users/<user-id>/password). Prompts via getpass — never accepted as a flag.",
)
@click.argument("user_id")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def users_password(user_id, yes):
    """Password is read from a masked prompt (getpass) — never via argv,
    never via env var. Confirms the change before sending."""
    import getpass

    new_password = getpass.getpass(f"New password for {user_id}: ")
    if not new_password:
        click.echo("Empty password — aborted.", err=True)
        raise click.exceptions.Exit(code=1)
    confirm_password = getpass.getpass("Confirm new password: ")
    if confirm_password != new_password:
        click.echo("Passwords do not match — aborted.", err=True)
        raise click.exceptions.Exit(code=1)

    if not yes and not click.confirm(f"Reset password for user {user_id}?", default=False):
        click.echo("Aborted.")
        return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            users.update_user_password(client, user_id, new_password=new_password)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Reset password for user {user_id}.")


@users_cmd.command(
    "email",
    help="Change a user's email (PUT /users/<user-id>/email; sends Zoom confirmation link).",
)
@click.argument("user_id")
@click.argument("new_email")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def users_email(user_id, new_email, yes):
    """Zoom sends the new address a confirmation link — the change isn't
    active until the user clicks. Confirms by default since it triggers
    user-visible email."""
    if not yes and not click.confirm(
        f"Change email for user {user_id} to {new_email}? "
        f"(Zoom will send a confirmation link to {new_email})",
        default=False,
    ):
        click.echo("Aborted.")
        return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            users.update_user_email(client, user_id, new_email=new_email)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Email change initiated for user {user_id} -> {new_email}.")


@users_cmd.command(
    "token",
    help="Get a user-level token (GET /users/<user-id>/token; sensitive).",
)
@click.argument("user_id")
@click.option(
    "--type",
    "token_type",
    type=click.Choice(list(users.ALLOWED_USER_TOKEN_TYPES)),
    default="zak",
    show_default=True,
    help="Token type. Default zak (start-meeting on the user's behalf).",
)
@_translate_keyring_errors
def users_token(user_id, token_type):
    """Output is the raw token string. Sensitive — anyone with a zak can
    start the user's meetings as them. Don't paste into chat / tickets."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = users.get_user_token(client, user_id, token_type=token_type)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(data.get("token", ""))


@users_cmd.command(
    "permissions",
    help="List a user's role + assigned permissions (GET /users/<user-id>/permissions).",
)
@click.argument("user_id")
@_translate_keyring_errors
def users_permissions(user_id):
    """One permission per line. The set is what the user can DO — useful
    for "why can't this person create a meeting on behalf of X?" audits."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = users.get_user_permissions(client, user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    for perm in data.get("permissions", []):
        click.echo(perm)


# ---- Users depth-completion: schedulers + assistants + presence --------


@users_cmd.group(
    "schedulers",
    help="Manage users authorized to schedule meetings on this user's behalf.",
)
def users_schedulers_cmd():
    """Group for ``zoom users schedulers ...``."""


@users_schedulers_cmd.command(
    "list", help="List schedulers for a user (GET /users/<user-id>/schedulers)."
)
@click.argument("user_id")
@_translate_keyring_errors
def users_schedulers_list(user_id):
    """TSV output (id\\temail)."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = users.list_schedulers(client, user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo("id\temail")
    for s in data.get("schedulers", []):
        click.echo(f"{s.get('id', '')}\t{s.get('email', '')}")


@users_schedulers_cmd.command(
    "delete",
    help=(
        "Revoke a scheduler (DELETE /users/<user-id>/schedulers/<scheduler-id>); "
        "omit the scheduler id with --all to revoke all schedulers."
    ),
)
@click.argument("user_id")
@click.argument("scheduler_id", required=False)
@click.option(
    "--all",
    "all_schedulers",
    is_flag=True,
    default=False,
    help="Revoke ALL schedulers (DELETE /users/<user-id>/schedulers).",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def users_schedulers_delete(user_id, scheduler_id, all_schedulers, yes):
    if all_schedulers and scheduler_id:
        click.echo("--all is mutually exclusive with a scheduler-id argument.", err=True)
        raise click.exceptions.Exit(code=1)
    if not all_schedulers and not scheduler_id:
        click.echo(
            "Pass either a scheduler-id or --all to delete all schedulers.",
            err=True,
        )
        raise click.exceptions.Exit(code=1)

    if all_schedulers:
        prompt = f"Revoke ALL schedulers for user {user_id}?"
    else:
        prompt = f"Revoke scheduler {scheduler_id} for user {user_id}?"
    if not yes and not click.confirm(prompt, default=False):
        click.echo("Aborted.")
        return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            if all_schedulers:
                users.delete_all_schedulers(client, user_id)
                click.echo(f"Revoked all schedulers for user {user_id}.")
            else:
                users.delete_scheduler(client, user_id, scheduler_id)
                click.echo(f"Revoked scheduler {scheduler_id} for user {user_id}.")
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@users_cmd.group(
    "assistants",
    help="Manage assistants who can manage meetings on this user's behalf.",
)
def users_assistants_cmd():
    """Group for ``zoom users assistants ...``."""


@users_assistants_cmd.command(
    "add",
    help="Assign assistants (POST /users/<user-id>/assistants).",
)
@click.argument("user_id")
@click.option(
    "--email",
    multiple=True,
    help="Assistant email. Repeat for multiple.",
)
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    default=None,
    help="Read the full assistants payload from a JSON file (or '-' for stdin).",
)
@_translate_keyring_errors
def users_assistants_add(user_id, email, from_json):
    """Two payload-construction modes:
    1. ``--email a@e.com --email b@e.com`` builds the assistants array from emails.
    2. ``--from-json FILE`` accepts the full body (also lets you pass IDs).
    Mutually exclusive."""
    if from_json is not None:
        if email:
            click.echo("--from-json is mutually exclusive with --email.", err=True)
            raise click.exceptions.Exit(code=1)
        payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    else:
        if not email:
            click.echo(
                "Pass at least one --email, or --from-json with a full body.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = {"assistants": [{"email": e} for e in email]}

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            result = users.add_assistants(client, user_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Added assistants. ids: {result.get('ids', '')}")


@users_assistants_cmd.command(
    "delete",
    help=(
        "Revoke an assistant (DELETE /users/<user-id>/assistants/<assistant-id>); "
        "use --all to revoke all assistants."
    ),
)
@click.argument("user_id")
@click.argument("assistant_id", required=False)
@click.option(
    "--all",
    "all_assistants",
    is_flag=True,
    default=False,
    help="Revoke ALL assistants (DELETE /users/<user-id>/assistants).",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def users_assistants_delete(user_id, assistant_id, all_assistants, yes):
    if all_assistants and assistant_id:
        click.echo("--all is mutually exclusive with an assistant-id argument.", err=True)
        raise click.exceptions.Exit(code=1)
    if not all_assistants and not assistant_id:
        click.echo(
            "Pass either an assistant-id or --all to delete all assistants.",
            err=True,
        )
        raise click.exceptions.Exit(code=1)

    if all_assistants:
        prompt = f"Revoke ALL assistants for user {user_id}?"
    else:
        prompt = f"Revoke assistant {assistant_id} for user {user_id}?"
    if not yes and not click.confirm(prompt, default=False):
        click.echo("Aborted.")
        return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            if all_assistants:
                users.delete_all_assistants(client, user_id)
                click.echo(f"Revoked all assistants for user {user_id}.")
            else:
                users.delete_assistant(client, user_id, assistant_id)
                click.echo(f"Revoked assistant {assistant_id} for user {user_id}.")
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@users_cmd.group(
    "presence",
    help="Read or set the user's chat presence status.",
)
def users_presence_cmd():
    """Group for ``zoom users presence ...``."""


@users_presence_cmd.command(
    "get", help="Print the user's current presence (GET /users/<user-id>/presence_status)."
)
@click.argument("user_id")
@_translate_keyring_errors
def users_presence_get(user_id):
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = users.get_presence(client, user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(data.get("status", ""))


@users_presence_cmd.command(
    "set",
    help="Set the user's presence (PUT /users/<user-id>/presence_status).",
)
@click.argument("user_id")
@click.argument("status", type=click.Choice(list(users.ALLOWED_PRESENCE_STATUSES)))
@_translate_keyring_errors
def users_presence_set(user_id, status):
    """Status is case-sensitive — Zoom uses Available / Away /
    Do_Not_Disturb / In_Calendar_Event / Presenting / In_A_Zoom_Meeting /
    On_A_Call."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            users.set_presence(client, user_id, status=status)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Set presence for user {user_id} -> {status}.")


# ---- Users depth-completion: update + sso-revoke + virtual-backgrounds --


@users_cmd.command(
    "update",
    help="Update a user's profile (PATCH /users/<user-id>).",
)
@click.argument("user_id")
@click.option("--first-name", help="New first name.")
@click.option("--last-name", help="New last name.")
@click.option(
    "--type",
    "user_type",
    type=click.IntRange(1, 3),
    help="1=Basic, 2=Licensed, 3=On-prem.",
)
@click.option("--language", help="Locale (e.g. en-US).")
@click.option("--dept", help="Department.")
@click.option("--vanity-name", help="Vanity URL prefix (Pro+).")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    default=None,
    help="Read full user-update body from JSON. Mutually exclusive with the per-field flags.",
)
@_translate_keyring_errors
def users_update(user_id, first_name, last_name, user_type, language, dept, vanity_name, from_json):
    """Two payload-construction modes (mirrors the rest of the CLI):

    1. Per-field flags — at least one must be passed.
    2. ``--from-json FILE`` — full Zoom PATCH body."""
    field_flags = (first_name, last_name, user_type, language, dept, vanity_name)
    any_field_flag = any(f is not None for f in field_flags)

    if from_json is not None:
        if any_field_flag:
            click.echo(
                "--from-json is mutually exclusive with the per-field flags.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    else:
        payload = {}
        if first_name is not None:
            payload["first_name"] = first_name
        if last_name is not None:
            payload["last_name"] = last_name
        if user_type is not None:
            payload["type"] = user_type
        if language is not None:
            payload["language"] = language
        if dept is not None:
            payload["dept"] = dept
        if vanity_name is not None:
            payload["vanity_name"] = vanity_name
        if not payload:
            click.echo(
                "Nothing to update — pass at least one --field, or --from-json.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            users.update_user(client, user_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Updated user {user_id}.")


@users_cmd.command(
    "revoke-sso",
    help="Invalidate the user's active SSO sessions (PUT /users/<user-id>/sso_token).",
)
@click.argument("user_id")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def users_revoke_sso(user_id, yes):
    """Forces re-auth on the user's next access. Confirms by default
    since this is a user-visible disruption."""
    if not yes and not click.confirm(
        f"Revoke all SSO sessions for user {user_id}?",
        default=False,
    ):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            users.revoke_sso_token(client, user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Revoked SSO sessions for user {user_id}.")


@users_cmd.group(
    "virtual-backgrounds",
    help="Manage a user's uploaded virtual backgrounds.",
)
def users_vb_cmd():
    """Group for ``zoom users virtual-backgrounds ...``."""


@users_vb_cmd.command(
    "list",
    help="List a user's virtual backgrounds (paginates GET /users/<user-id>/settings/virtual_backgrounds).",
)
@click.argument("user_id")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
    help="Items per page request.",
)
@_translate_keyring_errors
def users_vb_list(user_id, page_size):
    """TSV output (id\\tname\\ttype\\tsize\\tis_default)."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\tname\ttype\tsize\tis_default")
            for vb in users.list_virtual_backgrounds(client, user_id, page_size=page_size):
                click.echo(
                    f"{vb.get('id', '')}\t"
                    f"{vb.get('name', '')}\t"
                    f"{vb.get('type', '')}\t"
                    f"{vb.get('size', '')}\t"
                    f"{vb.get('is_default', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@users_vb_cmd.command(
    "delete",
    help="Delete one or more virtual backgrounds by file ID.",
)
@click.argument("user_id")
@click.option(
    "--id",
    "ids",
    multiple=True,
    required=True,
    help="VB file ID. Repeat for bulk delete.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def users_vb_delete(user_id, ids, yes):
    id_list = list(ids)
    if not yes and not click.confirm(
        f"Delete {len(id_list)} virtual background(s) for user {user_id}?",
        default=False,
    ):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            users.delete_virtual_backgrounds(client, user_id, ids=id_list)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Deleted {len(id_list)} virtual background(s) for user {user_id}.")


# ---- Zoom Meetings — write commands -------------------------------------
#
# Closes #13 (write piece). Confirmation-flow design mirrors `zoom rm`:
#   - positional id with no prompt = scripted use OK
#   - `--yes` / `-y` skips any confirmation
#   - `--dry-run` (delete only) shows what would happen without acting
#   - `end` always requires confirmation unless `--yes` — kicking live
#     participants is disruptive and there's no recovery


def _build_meeting_payload(
    *,
    topic: str | None,
    meeting_type: int | None,
    start_time: str | None,
    duration: int | None,
    timezone: str | None,
    password: str | None,
    agenda: str | None,
) -> dict:
    """Drop None-valued fields so we don't clobber defaults on PATCH or
    send junk on POST."""
    payload: dict = {}
    if topic is not None:
        payload["topic"] = topic
    if meeting_type is not None:
        payload["type"] = meeting_type
    if start_time is not None:
        payload["start_time"] = start_time
    if duration is not None:
        payload["duration"] = duration
    if timezone is not None:
        payload["timezone"] = timezone
    if password is not None:
        payload["password"] = password
    if agenda is not None:
        payload["agenda"] = agenda
    return payload


def _load_json_payload_or_exit(file_handle, *, label: str) -> dict:
    """Parse a JSON object from a file/stdin handle; exit 1 with a clear
    message on parse failure or non-dict top-level. Used by both
    ``meetings create --from-json`` and ``meetings update --from-json``."""
    import json as _json

    try:
        payload = _json.load(file_handle)
    except _json.JSONDecodeError as exc:
        click.echo(f"Invalid JSON in {label}: {exc}", err=True)
        raise click.exceptions.Exit(code=1) from exc
    if not isinstance(payload, dict):
        click.echo(
            f"{label} must be a JSON object (dict), got {type(payload).__name__}.",
            err=True,
        )
        raise click.exceptions.Exit(code=1)
    return payload


@meetings_cmd.command("create", help="Schedule a new meeting (POST /users/<user-id>/meetings).")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    default=None,
    help=(
        "Read the full create-meeting body from a JSON file (or '-' for "
        "stdin). Mutually exclusive with --topic / --type / etc. Use "
        "this for meetings that need recurrence or settings sub-objects "
        "the per-field flags don't expose."
    ),
)
@click.option("--topic", help="Meeting topic / title (required unless --from-json).")
@click.option(
    "--type",
    "meeting_type",
    type=click.IntRange(1, 8),
    default=None,
    help="1=instant, 2=scheduled (default), 3=recurring no-fixed-time, 8=recurring fixed-time.",
)
@click.option("--start-time", help="ISO 8601 (required for type 2 / 8). e.g. 2026-04-29T15:00:00Z")
@click.option(
    "--duration",
    type=click.IntRange(1, 1440),
    default=None,
    help="Minutes (default 60 when not using --from-json).",
)
@click.option("--timezone", "tz", help="IANA tz, e.g. America/New_York.")
@click.option("--password", help="Meeting password. If omitted Zoom auto-generates one.")
@click.option("--agenda", help="Optional agenda body.")
@click.option(
    "--user-id",
    default="me",
    show_default=True,
    help="Whose calendar to create on. Default 'me'.",
)
@_translate_keyring_errors
def meetings_create(
    from_json, topic, meeting_type, start_time, duration, tz, password, agenda, user_id
):
    """Two payload-construction modes:

    1. **Per-field flags** (default) — build the simple-meeting payload
       from ``--topic`` / ``--type`` / etc. ``--topic`` is required.

    2. **--from-json FILE** — pass the full Zoom create-meeting body
       (including ``settings`` and ``recurrence`` sub-objects) as JSON.
       Mutually exclusive with the field flags.
    """
    field_flags = (topic, meeting_type, start_time, duration, tz, password, agenda)
    any_field_flag = any(f is not None for f in field_flags)

    if from_json is not None:
        if any_field_flag:
            click.echo(
                "--from-json is mutually exclusive with --topic / --type / "
                "--start-time / --duration / --timezone / --password / --agenda.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    else:
        if not topic:
            click.echo(
                "Either --topic (with the field flags) or --from-json is required.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = _build_meeting_payload(
            topic=topic,
            meeting_type=meeting_type if meeting_type is not None else 2,
            start_time=start_time,
            duration=duration if duration is not None else 60,
            timezone=tz,
            password=password,
            agenda=agenda,
        )
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            created = meetings.create_meeting(client, payload, user_id=user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    _print_meeting_detail(created)


@meetings_cmd.command("update", help="Update an existing meeting (PATCH /meetings/<meeting-id>).")
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    default=None,
    help=(
        "Read the full update body from a JSON file (or '-' for stdin). "
        "Mutually exclusive with the per-field flags. Use this for "
        "settings / recurrence updates the field flags don't expose."
    ),
)
@click.option("--topic", help="New topic.")
@click.option(
    "--type",
    "meeting_type",
    type=click.IntRange(1, 8),
    help="Change meeting type.",
)
@click.option("--start-time", help="ISO 8601.")
@click.option("--duration", type=click.IntRange(1, 1440), help="Minutes.")
@click.option("--timezone", "tz", help="IANA tz.")
@click.option("--password", help="New password.")
@click.option("--agenda", help="New agenda body.")
@_translate_keyring_errors
def meetings_update(
    meeting_id, from_json, topic, meeting_type, start_time, duration, tz, password, agenda
):
    """Two payload-construction modes (same as ``meetings create``):

    1. **Per-field flags** — partial update; only flags you pass are
       sent. Errors out if no fields were provided.

    2. **--from-json FILE** — full PATCH body. Useful for settings
       sub-object updates that the field flags can't express.
    """
    field_flags = (topic, meeting_type, start_time, duration, tz, password, agenda)
    any_field_flag = any(f is not None for f in field_flags)

    if from_json is not None:
        if any_field_flag:
            click.echo(
                "--from-json is mutually exclusive with --topic / --type / "
                "--start-time / --duration / --timezone / --password / --agenda.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    else:
        payload = _build_meeting_payload(
            topic=topic,
            meeting_type=meeting_type,
            start_time=start_time,
            duration=duration,
            timezone=tz,
            password=password,
            agenda=agenda,
        )
        if not payload:
            click.echo("Nothing to update — pass at least one --field.", err=True)
            raise click.exceptions.Exit(code=1)
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.update_meeting(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Updated meeting {meeting_id}.")


@meetings_cmd.command("delete", help="Delete a meeting (DELETE /meetings/<meeting-id>).")
@click.argument("meeting_id")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be deleted without calling the API.",
)
@click.option(
    "--notify-host",
    is_flag=True,
    default=False,
    help="Send the host an email reminder of the deletion (Zoom default is silent).",
)
@click.option(
    "--notify-registrants",
    is_flag=True,
    default=False,
    help="Send registrants a cancellation notice.",
)
@_translate_keyring_errors
def meetings_delete(meeting_id, yes, dry_run, notify_host, notify_registrants):
    """Mirrors the `zoom rm` confirmation-flow pattern: positional id +
    interactive confirm unless --yes; --dry-run for a no-op preview."""
    if dry_run:
        click.echo(f"[dry-run] Would delete meeting {meeting_id}")
        if notify_host or notify_registrants:
            click.echo(
                f"[dry-run] notify_host={notify_host} notify_registrants={notify_registrants}"
            )
        return

    if not yes and not click.confirm(f"Delete meeting {meeting_id}?", default=False):
        click.echo("Aborted.")
        return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.delete_meeting(
                client,
                meeting_id,
                schedule_for_reminder=notify_host,
                cancel_meeting_reminder=notify_registrants,
            )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Deleted meeting {meeting_id}.")


@meetings_cmd.command(
    "end",
    help="End an in-progress meeting (PUT /meetings/<meeting-id>/status, action=end).",
)
@click.argument("meeting_id")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_end(meeting_id, yes):
    """Kicking live participants is disruptive and irreversible — always
    confirm unless --yes."""
    if not yes and not click.confirm(
        f"End meeting {meeting_id}? This kicks all participants.", default=False
    ):
        click.echo("Aborted.")
        return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.end_meeting(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Ended meeting {meeting_id}.")


# ---- Meeting registrants (depth-completion follow-up to #13) -----------


@meetings_cmd.group(
    "registrants",
    help="Manage attendee registrations on a meeting (requires meeting registration enabled).",
)
def meetings_registrants_cmd():
    """Group for ``zoom meetings registrants ...``."""


@meetings_registrants_cmd.command(
    "list",
    help="List registrants for a meeting (paginates GET /meetings/<id>/registrants).",
)
@click.argument("meeting_id")
@click.option(
    "--status",
    type=click.Choice(list(meetings.ALLOWED_REGISTRANT_STATUSES)),
    default="pending",
    show_default=True,
    help="Filter by registration status.",
)
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
    help="Items per page request.",
)
@_translate_keyring_errors
def meetings_registrants_list(meeting_id, status, page_size):
    """Output is tab-separated (id\\temail\\tfirst_name\\tlast_name\\tstatus)."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\temail\tfirst_name\tlast_name\tstatus")
            for r in meetings.list_registrants(
                client, meeting_id, status=status, page_size=page_size
            ):
                click.echo(
                    f"{r.get('id', '')}\t"
                    f"{r.get('email', '')}\t"
                    f"{r.get('first_name', '')}\t"
                    f"{r.get('last_name', '')}\t"
                    f"{r.get('status', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@meetings_registrants_cmd.command(
    "add",
    help="Register an attendee on a meeting (POST /meetings/<id>/registrants).",
)
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    default=None,
    help=(
        "Read the full registration body from a JSON file (or '-' for stdin). "
        "Use this for custom_questions and the long form fields the per-field "
        "flags don't expose. Mutually exclusive with --email / --first-name / --last-name."
    ),
)
@click.option("--email", help="Registrant email (required unless --from-json).")
@click.option("--first-name", help="Registrant first name (required unless --from-json).")
@click.option("--last-name", help="Registrant last name (optional).")
@_translate_keyring_errors
def meetings_registrants_add(meeting_id, from_json, email, first_name, last_name):
    """Two payload-construction modes (mirrors meetings create / users settings update):

    1. Per-field flags — ``--email`` and ``--first-name`` required.
    2. ``--from-json FILE`` — full Zoom registration body.
    """
    field_flags = (email, first_name, last_name)
    any_field_flag = any(f is not None for f in field_flags)

    if from_json is not None:
        if any_field_flag:
            click.echo(
                "--from-json is mutually exclusive with --email / --first-name / --last-name.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    else:
        if not email or not first_name:
            click.echo(
                "Either (--email AND --first-name) or --from-json is required.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = {"email": email, "first_name": first_name}
        if last_name:
            payload["last_name"] = last_name

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            result = meetings.add_registrant(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Registered. id: {result.get('registrant_id', result.get('id', ''))}")
    if "join_url" in result:
        click.echo(f"join_url: {result['join_url']}")


def _registrant_status_action(action: str, action_past: str):
    """Build one of the ``approve`` / ``deny`` / ``cancel`` subcommands.

    Factored out because the three commands differ only in the verb,
    confirmation copy, and action token sent to Zoom — extracting the
    shared shape keeps the three command bodies one-liners.
    """

    @meetings_registrants_cmd.command(
        action,
        help=f"{action.capitalize()} one or more registrants (PUT /meetings/<id>/registrants/status).",
    )
    @click.argument("meeting_id")
    @click.option(
        "--registrant",
        "registrant_ids",
        multiple=True,
        required=True,
        help="Registrant ID. Repeat for bulk action.",
    )
    @click.option(
        "--yes",
        "-y",
        is_flag=True,
        default=False,
        help="Skip the confirmation prompt.",
    )
    @_translate_keyring_errors
    def _cmd(meeting_id, registrant_ids, yes):
        ids = list(registrant_ids)
        if not yes and not click.confirm(
            f"{action.capitalize()} {len(ids)} registrant(s) on meeting {meeting_id}?",
            default=False,
        ):
            click.echo("Aborted.")
            return
        creds = _load_creds_or_exit()
        try:
            with _build_api_client(creds) as client:
                meetings.update_registrant_status(
                    client, meeting_id, action=action, registrant_ids=ids
                )
        except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
            _exit_on_api_error(exc)
        click.echo(f"{action_past} {len(ids)} registrant(s) on meeting {meeting_id}.")

    _cmd.__name__ = f"meetings_registrants_{action}"
    return _cmd


_meetings_registrants_approve = _registrant_status_action("approve", "Approved")
_meetings_registrants_deny = _registrant_status_action("deny", "Denied")
_meetings_registrants_cancel = _registrant_status_action("cancel", "Cancelled")


@meetings_registrants_cmd.group(
    "questions",
    help="Manage the registration form (custom questions) for a meeting.",
)
def meetings_registrants_questions_cmd():
    """Group for ``zoom meetings registrants questions ...``."""


@meetings_registrants_questions_cmd.command(
    "get",
    help="Print the registration form's questions as JSON (GET .../registrants/questions).",
)
@click.argument("meeting_id")
@_translate_keyring_errors
def meetings_registrants_questions_get(meeting_id):
    """Output is the raw JSON envelope so it round-trips cleanly through
    ``... questions update --from-json -``."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.get_registration_questions(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(data, indent=2))


@meetings_registrants_questions_cmd.command(
    "update",
    help="Replace the registration form's questions (PATCH .../registrants/questions).",
)
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    required=True,
    help="Read the full questions payload from a JSON file (or '-' for stdin).",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_registrants_questions_update(meeting_id, from_json, yes):
    """Zoom replaces the questions array wholesale, not merge — round-trip
    via ``questions get`` first to pick up the existing shape, then edit."""
    payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    if not yes and not click.confirm(
        f"Replace registration questions on meeting {meeting_id}?",
        default=False,
    ):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.update_registration_questions(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Updated registration questions for meeting {meeting_id}.")


# ---- Meeting polls (depth-completion follow-up to #13) -----------------
#
# Poll payloads are nested (questions[]/answers[]/right_answers[]/
# answer_required) so create/update are JSON-only. The list/get/delete
# commands keep the simple shape from the rest of the CLI.


@meetings_cmd.group("polls", help="Manage in-meeting polls.")
def meetings_polls_cmd():
    """Group for ``zoom meetings polls ...``."""


@meetings_polls_cmd.command("list", help="List polls on a meeting (GET /meetings/<id>/polls).")
@click.argument("meeting_id")
@_translate_keyring_errors
def meetings_polls_list(meeting_id):
    """TSV output (id\\ttitle\\tstatus\\tanonymous)."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.list_polls(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo("id\ttitle\tstatus\tanonymous")
    for p in data.get("polls", []):
        click.echo(
            f"{p.get('id', '')}\t"
            f"{p.get('title', '')}\t"
            f"{p.get('status', '')}\t"
            f"{p.get('anonymous', '')}"
        )


@meetings_polls_cmd.command(
    "get", help="Print one poll's full detail as JSON (GET /meetings/<id>/polls/<poll-id>)."
)
@click.argument("meeting_id")
@click.argument("poll_id")
@_translate_keyring_errors
def meetings_polls_get(meeting_id, poll_id):
    """Output is raw JSON so it round-trips into ``polls update --from-json``."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.get_poll(client, meeting_id, poll_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(data, indent=2))


@meetings_polls_cmd.command("create", help="Add a poll to a meeting (POST /meetings/<id>/polls).")
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    required=True,
    help=(
        "Read the full poll body from a JSON file (or '-' for stdin). "
        "Polls are nested enough (questions/answers/right_answers/"
        "answer_required) that per-field flags would be unusable — "
        "JSON-only by design."
    ),
)
@_translate_keyring_errors
def meetings_polls_create(meeting_id, from_json):
    """Returns the created poll's id and title on success."""
    payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            result = meetings.create_poll(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Created poll. id: {result.get('id', '')}, title: {result.get('title', '')}")


@meetings_polls_cmd.command(
    "update",
    help="Replace a poll wholesale (PUT /meetings/<id>/polls/<poll-id>).",
)
@click.argument("meeting_id")
@click.argument("poll_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    required=True,
    help="Read the full poll body from a JSON file (or '-' for stdin).",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_polls_update(meeting_id, poll_id, from_json, yes):
    """Zoom's poll update is a PUT — full replace, NOT a merge. Round-trip
    via ``polls get`` first to pick up the existing shape."""
    payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    if not yes and not click.confirm(
        f"Replace poll {poll_id} on meeting {meeting_id}? (omitted fields will be dropped)",
        default=False,
    ):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.update_poll(client, meeting_id, poll_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Updated poll {poll_id} on meeting {meeting_id}.")


@meetings_polls_cmd.command(
    "delete",
    help="Delete a poll (DELETE /meetings/<id>/polls/<poll-id>).",
)
@click.argument("meeting_id")
@click.argument("poll_id")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_polls_delete(meeting_id, poll_id, yes):
    if not yes and not click.confirm(
        f"Delete poll {poll_id} from meeting {meeting_id}?", default=False
    ):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.delete_poll(client, meeting_id, poll_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Deleted poll {poll_id} from meeting {meeting_id}.")


@meetings_polls_cmd.command(
    "results",
    help="Print poll RESULTS for a past meeting (GET /past_meetings/<id>/polls).",
)
@click.argument("meeting_id")
@_translate_keyring_errors
def meetings_polls_results(meeting_id):
    """Different namespace from the live polls endpoints — results live
    under /past_meetings, not /meetings. Output is raw JSON because the
    per-question result breakdowns nest deeper than TSV can express."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.list_past_poll_results(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(data, indent=2))


# ---- Meeting livestream (depth-completion follow-up to #13) ------------


@meetings_cmd.group("livestream", help="Configure and start/stop a meeting's RTMP livestream.")
def meetings_livestream_cmd():
    """Group for ``zoom meetings livestream ...``."""


@meetings_livestream_cmd.command(
    "get", help="Print livestream config (GET /meetings/<id>/livestream)."
)
@click.argument("meeting_id")
@_translate_keyring_errors
def meetings_livestream_get(meeting_id):
    """Output is one-per-line. ``stream_key`` is the secret half — anyone
    with it can push video to the destination, so redact when sharing."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.get_livestream(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    for field in ("stream_url", "stream_key", "page_url", "resolution"):
        if field in data:
            click.echo(f"{field}: {data[field]}")


@meetings_livestream_cmd.command(
    "update",
    help="Set livestream config (PATCH /meetings/<id>/livestream).",
)
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    default=None,
    help=(
        "Read the full livestream body from a JSON file (or '-' for "
        "stdin). Mutually exclusive with --stream-url / --stream-key / "
        "--page-url."
    ),
)
@click.option("--stream-url", help="RTMP destination URL (e.g. rtmp://example.com/live).")
@click.option("--stream-key", help="RTMP stream key (sensitive — pass via env or stdin).")
@click.option("--page-url", help="Public viewer page (HTTPS).")
@_translate_keyring_errors
def meetings_livestream_update(meeting_id, from_json, stream_url, stream_key, page_url):
    """Two payload-construction modes (mirrors the rest of the CLI):

    1. Per-field flags — at least one of the three must be passed.
    2. ``--from-json FILE`` — full Zoom livestream body.
    """
    field_flags = (stream_url, stream_key, page_url)
    any_field_flag = any(f is not None for f in field_flags)

    if from_json is not None:
        if any_field_flag:
            click.echo(
                "--from-json is mutually exclusive with --stream-url / --stream-key / --page-url.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    else:
        payload = {}
        if stream_url is not None:
            payload["stream_url"] = stream_url
        if stream_key is not None:
            payload["stream_key"] = stream_key
        if page_url is not None:
            payload["page_url"] = page_url
        if not payload:
            click.echo(
                "Nothing to update — pass at least one of --stream-url / "
                "--stream-key / --page-url, or use --from-json.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.update_livestream(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Updated livestream config for meeting {meeting_id}.")


@meetings_livestream_cmd.command(
    "start",
    help="Start the livestream (PATCH /meetings/<id>/livestream/status, action=start).",
)
@click.argument("meeting_id")
@click.option(
    "--display-name",
    help="Banner overlay shown on the stream.",
)
@click.option(
    "--active-speaker-name/--no-active-speaker-name",
    "active_speaker_name",
    default=None,
    help="Show the active speaker's name on the stream.",
)
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    default=None,
    help=(
        "Read the broadcast settings sub-object from JSON. Mutually "
        "exclusive with --display-name / --active-speaker-name."
    ),
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_livestream_start(meeting_id, display_name, active_speaker_name, from_json, yes):
    """Starting the livestream pushes the meeting to the configured RTMP
    destination — visible to anyone with the page URL. Confirms by
    default."""
    field_flags = (display_name, active_speaker_name)
    any_field_flag = any(f is not None for f in field_flags)

    if from_json is not None:
        if any_field_flag:
            click.echo(
                "--from-json is mutually exclusive with --display-name / --active-speaker-name.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        settings = _load_json_payload_or_exit(from_json, label="--from-json input")
    else:
        settings = {}
        if display_name is not None:
            settings["display_name"] = display_name
        if active_speaker_name is not None:
            settings["active_speaker_name"] = active_speaker_name

    if not yes and not click.confirm(f"Start livestream on meeting {meeting_id}?", default=False):
        click.echo("Aborted.")
        return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.update_livestream_status(
                client, meeting_id, action="start", settings=settings or None
            )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Started livestream on meeting {meeting_id}.")


@meetings_livestream_cmd.command(
    "stop",
    help="Stop the livestream (PATCH /meetings/<id>/livestream/status, action=stop).",
)
@click.argument("meeting_id")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_livestream_stop(meeting_id, yes):
    if not yes and not click.confirm(f"Stop livestream on meeting {meeting_id}?", default=False):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.update_livestream_status(client, meeting_id, action="stop")
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Stopped livestream on meeting {meeting_id}.")


# ---- Past instances + invitation + past-meeting summary/participants + --
# ---- recover (depth-completion follow-up to #13) ------------------------


@meetings_cmd.command(
    "invitation", help="Print the invitation text (GET /meetings/<id>/invitation)."
)
@click.argument("meeting_id")
@_translate_keyring_errors
def meetings_invitation(meeting_id):
    """Output is the raw email invitation text Zoom builds for the
    meeting — paste-ready into any email client."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.get_invitation(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(data.get("invitation", ""))


@meetings_cmd.command(
    "recover",
    help="Restore a soft-deleted meeting (PUT /meetings/<id>/status, action=recover).",
)
@click.argument("meeting_id")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_recover(meeting_id, yes):
    """Counterpart to ``meetings delete`` — Zoom keeps deleted meetings
    recoverable for a window. Confirms by default since this changes
    soft-deleted state to active."""
    if not yes and not click.confirm(f"Recover (un-delete) meeting {meeting_id}?", default=False):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.recover_meeting(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Recovered meeting {meeting_id}.")


@meetings_cmd.group("past", help="Read endpoints for meetings that have already ended.")
def meetings_past_cmd():
    """Group for ``zoom meetings past ...``."""


@meetings_past_cmd.command(
    "instances",
    help="List past occurrences of a recurring meeting (GET /past_meetings/<id>/instances).",
)
@click.argument("meeting_id")
@_translate_keyring_errors
def meetings_past_instances(meeting_id):
    """TSV output (uuid\\tstart_time). The uuid is the handle for
    ``meetings past get`` and ``meetings past participants``."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.list_past_instances(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo("uuid\tstart_time")
    for inst in data.get("meetings", []):
        click.echo(f"{inst.get('uuid', '')}\t{inst.get('start_time', '')}")


@meetings_past_cmd.command(
    "get",
    help="Print past-meeting summary (GET /past_meetings/<id-or-uuid>).",
)
@click.argument("meeting_id_or_uuid")
@_translate_keyring_errors
def meetings_past_get(meeting_id_or_uuid):
    """``meeting_id_or_uuid`` accepts either the numeric meeting ID or a
    meeting instance UUID (from ``meetings past instances``). Output is
    one-per-line, same shape as ``meetings get``."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.get_past_meeting(client, meeting_id_or_uuid)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    for field in ("uuid", "id", "topic", "type", "start_time", "end_time", "duration", "user_name"):
        if field in data:
            click.echo(f"{field}: {data[field]}")


@meetings_past_cmd.command(
    "participants",
    help="List participants who joined a past meeting (paginates GET /past_meetings/<id-or-uuid>/participants).",
)
@click.argument("meeting_id_or_uuid")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
    help="Items per page request.",
)
@_translate_keyring_errors
def meetings_past_participants(meeting_id_or_uuid, page_size):
    """TSV output (id\\tname\\tuser_email\\tjoin_time\\tleave_time)."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\tname\tuser_email\tjoin_time\tleave_time")
            for p in meetings.list_past_participants(
                client, meeting_id_or_uuid, page_size=page_size
            ):
                click.echo(
                    f"{p.get('id', '')}\t"
                    f"{p.get('name', '')}\t"
                    f"{p.get('user_email', '')}\t"
                    f"{p.get('join_time', '')}\t"
                    f"{p.get('leave_time', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


# ---- Survey + token + batch register + in-meeting controls -------------


@meetings_cmd.group("survey", help="Manage the post-meeting survey shown to attendees.")
def meetings_survey_cmd():
    """Group for ``zoom meetings survey ...``."""


@meetings_survey_cmd.command(
    "get", help="Print the survey config as JSON (GET /meetings/<id>/survey)."
)
@click.argument("meeting_id")
@_translate_keyring_errors
def meetings_survey_get(meeting_id):
    """JSON output so it round-trips into ``survey update --from-json``."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.get_survey(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(data, indent=2))


@meetings_survey_cmd.command(
    "update",
    help="Replace the survey config (PATCH /meetings/<id>/survey).",
)
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    required=True,
    help="Read the survey body from a JSON file (or '-' for stdin).",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_survey_update(meeting_id, from_json, yes):
    """Surveys nest deep (questions[]/custom_survey/show_in_browser/
    third_party_survey) — JSON-only by design. Round-trip via
    ``survey get`` first."""
    payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    if not yes and not click.confirm(f"Replace survey on meeting {meeting_id}?", default=False):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.update_survey(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Updated survey for meeting {meeting_id}.")


@meetings_survey_cmd.command("delete", help="Remove the survey (DELETE /meetings/<id>/survey).")
@click.argument("meeting_id")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_survey_delete(meeting_id, yes):
    if not yes and not click.confirm(f"Delete survey on meeting {meeting_id}?", default=False):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.delete_survey(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Deleted survey from meeting {meeting_id}.")


@meetings_cmd.command(
    "token",
    help="Get the start-meeting token (GET /meetings/<id>/token; sensitive).",
)
@click.argument("meeting_id")
@click.option(
    "--type",
    "token_type",
    type=click.Choice(list(meetings.ALLOWED_TOKEN_TYPES)),
    default="zak",
    show_default=True,
    help="Token type. Default zak (start-meeting).",
)
@_translate_keyring_errors
def meetings_token(meeting_id, token_type):
    """Output is the raw token string. Sensitive — anyone with this
    can start the meeting as the host. Don't paste into chat / tickets."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = meetings.get_token(client, meeting_id, token_type=token_type)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(data.get("token", ""))


@meetings_registrants_cmd.command(
    "batch",
    help="Bulk-register up to 30 attendees (POST /meetings/<id>/batch_registrants).",
)
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    required=True,
    help=(
        "JSON file (or '-' for stdin) containing the bulk registration body. "
        "Required shape: {registrants: [{email, first_name, ...}, ...], "
        "auto_approve?, registrants_confirmation_email?}."
    ),
)
@_translate_keyring_errors
def meetings_registrants_batch(meeting_id, from_json):
    """Returns one accepted entry per registrant with the per-attendee
    join_url. Useful for "register the whole team in one shot" flows."""
    import json as _json

    payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            result = meetings.batch_register(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    accepted = result.get("registrants", [])
    click.echo(f"Registered {len(accepted)} attendee(s).")
    click.echo(_json.dumps(result, indent=2))


@meetings_cmd.command(
    "control",
    help="Send an in-meeting control event (PATCH /live_meetings/<id>/events).",
)
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    required=True,
    help=(
        "JSON file (or '-' for stdin) with {method, params}. Examples: "
        '{"method": "invite", "params": {"contacts": [{"email": "a@e.com"}]}} '
        'or {"method": "mute_participants", "params": {}}.'
    ),
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def meetings_control(meeting_id, from_json, yes):
    """Lives in the /live_meetings namespace (NOT /meetings). Confirms by
    default since these actions affect a meeting in progress (mute /
    invite / etc. are user-visible)."""
    payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    method = payload.get("method", "<unknown>")
    if not yes and not click.confirm(
        f"Send in-meeting control '{method}' to meeting {meeting_id}?", default=False
    ):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            meetings.in_meeting_control(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Sent in-meeting control '{method}' to meeting {meeting_id}.")


# ---- Zoom Cloud Recordings ----------------------------------------------
#
# Closes #15. Same confirmation-flow design as `meetings delete`:
#   - delete always confirms unless --yes
#   - --action delete (permanent) gets a louder prompt than the default
#     trash (recoverable for 30 days)
#   - --dry-run for previews
#
# `download` is read-only on Zoom's side (just fetches files) so no
# confirmation needed. By default it writes one file per recording asset
# into --out-dir; --file-type filters to just MP4, M4A, etc.


@main.group(
    "recordings",
    help="Zoom Cloud Recordings API (https://developers.zoom.us/docs/api/cloud-recording/).",
)
def recordings_cmd():
    """Group for ``zoom recordings ...``."""


@recordings_cmd.command("list", help="List recorded meetings (paginated).")
@click.option(
    "--user-id",
    default="me",
    show_default=True,
    help="Whose recordings to list. Default 'me'.",
)
@click.option(
    "--from",
    "from_",
    metavar="YYYY-MM-DD",
    help="Lower bound on meeting start (ISO date).",
)
@click.option("--to", metavar="YYYY-MM-DD", help="Upper bound on meeting start (ISO date).")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
    help="Items per page request.",
)
@_translate_keyring_errors
def recordings_list(user_id, from_, to, page_size):
    """Output is tab-separated (uuid\\tmeeting_id\\ttopic\\tstart_time\\tfile_count)
    so it pipes into cut/awk/column."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("uuid\tmeeting_id\ttopic\tstart_time\tfile_count")
            for meeting in recordings.list_recordings(
                client,
                user_id=user_id,
                from_=from_,
                to=to,
                page_size=page_size,
            ):
                click.echo(
                    f"{meeting.get('uuid', '')}\t"
                    f"{meeting.get('id', '')}\t"
                    f"{meeting.get('topic', '')}\t"
                    f"{meeting.get('start_time', '')}\t"
                    f"{len(meeting.get('recording_files', []))}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@recordings_cmd.command(
    "get",
    help="Print a meeting's recording metadata as JSON (GET /meetings/<id>/recordings).",
)
@click.argument("meeting_id")
@_translate_keyring_errors
def recordings_get(meeting_id):
    """Output is the raw JSON envelope (sort_keys for diff-friendly).
    Pipe through `jq` to extract download URLs or filter by file_type."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            envelope = recordings.get_recordings(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(envelope, indent=2, sort_keys=True))


@recordings_cmd.command(
    "download",
    help="Download recording files for a meeting to disk.",
)
@click.argument("meeting_id")
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, writable=True, resolve_path=True),
    default=".",
    show_default=True,
    help="Directory to write files into. Created automatically if missing.",
)
@click.option(
    "--file-type",
    multiple=True,
    metavar="TYPE",
    help=(
        "Filter by file_type (MP4, M4A, CHAT, TRANSCRIPT, TIMELINE, CC, CSV). "
        "May be repeated to include multiple types. Omit to download all."
    ),
)
@_translate_keyring_errors
def recordings_download(meeting_id, out_dir, file_type):
    """Streams each file to disk via tempfile + os.replace, so a network
    drop mid-download leaves no half-written file at the target path.

    Filename convention: <meeting_id>-<recording_type>.<file_extension>.
    Conflicts (same recording_type appearing twice) are disambiguated by
    appending the recording_id."""
    import os
    import pathlib

    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    type_filter = {t.upper() for t in file_type} if file_type else None

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            envelope = recordings.get_recordings(client, meeting_id)
            files = envelope.get("recording_files", []) or []
            if type_filter is not None:
                files = [f for f in files if (f.get("file_type") or "").upper() in type_filter]
            if not files:
                click.echo(f"No recording files for meeting {meeting_id}.")
                return

            seen_names: set[str] = set()
            for f in files:
                ext = (f.get("file_extension") or "bin").lower()
                rtype = (f.get("recording_type") or f.get("file_type") or "file").lower()
                base = f"{meeting_id}-{rtype}.{ext}"
                if base in seen_names:
                    base = f"{meeting_id}-{rtype}-{f.get('id', '')}.{ext}"
                seen_names.add(base)
                dest = os.path.join(out_dir, base)
                url = f.get("download_url")
                if not url:
                    click.echo(f"Skipping {base} — no download_url in payload.", err=True)
                    continue
                bytes_written = client.stream_download(url, dest)
                click.echo(f"Downloaded {dest} ({bytes_written} bytes)")
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@recordings_cmd.command(
    "delete",
    help="Delete a meeting's recordings (DELETE /meetings/<id>/recordings).",
)
@click.argument("meeting_id")
@click.option(
    "--file-id",
    help="Delete a single recording file. Omit to delete ALL files for the meeting.",
)
@click.option(
    "--action",
    type=click.Choice(list(recordings.ALLOWED_DELETE_ACTIONS)),
    default="trash",
    show_default=True,
    help=(
        "trash: move to Zoom's trash (recoverable for 30 days); delete: permanent, irreversible."
    ),
)
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip the confirmation prompt.")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would happen without calling the API.",
)
@_translate_keyring_errors
def recordings_delete(meeting_id, file_id, action, yes, dry_run):
    """Always confirms unless --yes. The prompt is louder for
    `--action delete` (permanent) than for the default trash."""
    target = (
        f"recording file {file_id} of meeting {meeting_id}"
        if file_id
        else f"all recordings for meeting {meeting_id}"
    )
    if dry_run:
        click.echo(f"[dry-run] Would {action} {target}.")
        return

    if not yes:
        if action == "delete":
            prompt = f"Permanently delete {target}? This cannot be undone."
        else:
            prompt = f"Move {target} to trash? (Recoverable for 30 days.)"
        if not click.confirm(prompt, default=False):
            click.echo("Aborted.")
            return

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            if file_id:
                recordings.delete_recording_file(client, meeting_id, file_id, action=action)
            else:
                recordings.delete_recordings(client, meeting_id, action=action)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    verb = "Deleted" if action == "delete" else "Trashed"
    click.echo(f"{verb} {target}.")


# ---- Recordings depth-completion: recover + settings + registrants -----


@recordings_cmd.command(
    "recover",
    help="Restore trashed recordings (PUT /meetings/<id>/recordings[/<file-id>]/status, action=recover).",
)
@click.argument("meeting_id")
@click.option(
    "--file-id",
    "file_id",
    default=None,
    help="Recover only this specific recording file. If omitted, all of the meeting's trashed recordings are recovered.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def recordings_recover(meeting_id, file_id, yes):
    """Counterpart to ``recordings delete`` (which trashes by default).
    Trashed recordings stay recoverable for 30 days."""
    target = (
        f"recording {file_id} in meeting {meeting_id}"
        if file_id
        else f"all trashed recordings in meeting {meeting_id}"
    )
    if not yes and not click.confirm(f"Recover {target}?", default=False):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            if file_id:
                recordings.recover_recording_file(client, meeting_id, file_id)
            else:
                recordings.recover_recordings(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Recovered {target}.")


@recordings_cmd.group(
    "settings",
    help="Read or update a meeting's recording sharing/permission settings.",
)
def recordings_settings_cmd():
    """Group for ``zoom recordings settings ...``."""


@recordings_settings_cmd.command(
    "get",
    help="Print recording settings as JSON (GET /meetings/<id>/recordings/settings).",
)
@click.argument("meeting_id")
@_translate_keyring_errors
def recordings_settings_get(meeting_id):
    """JSON output so it round-trips into ``settings update --from-json``."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = recordings.get_recording_settings(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(data, indent=2))


@recordings_settings_cmd.command(
    "update",
    help="Update recording settings (PATCH /meetings/<id>/recordings/settings).",
)
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    required=True,
    help="Read the settings body from JSON (or '-' for stdin).",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def recordings_settings_update(meeting_id, from_json, yes):
    """Recording settings nest deep (share_recording / viewer_download /
    on_demand / password / authentication / etc.) — JSON-only by design.
    Round-trip via ``settings get`` first."""
    payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    if not yes and not click.confirm(
        f"Update recording settings on meeting {meeting_id}?",
        default=False,
    ):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            recordings.update_recording_settings(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Updated recording settings for meeting {meeting_id}.")


@recordings_cmd.group(
    "registrants",
    help="Manage on-demand recording viewer registrants.",
)
def recordings_registrants_cmd():
    """Group for ``zoom recordings registrants ...``."""


@recordings_registrants_cmd.command(
    "list",
    help="List on-demand recording registrants (paginates GET /meetings/<id>/recordings/registrants).",
)
@click.argument("meeting_id")
@click.option(
    "--status",
    type=click.Choice(list(recordings.ALLOWED_REGISTRANT_STATUSES)),
    default="pending",
    show_default=True,
    help="Filter by registration status.",
)
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
    help="Items per page request.",
)
@_translate_keyring_errors
def recordings_registrants_list(meeting_id, status, page_size):
    """TSV output (id\\temail\\tfirst_name\\tlast_name\\tstatus)."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\temail\tfirst_name\tlast_name\tstatus")
            for r in recordings.list_recording_registrants(
                client, meeting_id, status=status, page_size=page_size
            ):
                click.echo(
                    f"{r.get('id', '')}\t"
                    f"{r.get('email', '')}\t"
                    f"{r.get('first_name', '')}\t"
                    f"{r.get('last_name', '')}\t"
                    f"{r.get('status', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@recordings_registrants_cmd.command(
    "add",
    help="Register a viewer for an on-demand recording (POST /meetings/<id>/recordings/registrants).",
)
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    default=None,
    help="Read the full registration body from JSON (or '-' for stdin). Mutually exclusive with --email / --first-name / --last-name.",
)
@click.option("--email", help="Registrant email (required unless --from-json).")
@click.option("--first-name", help="Registrant first name (required unless --from-json).")
@click.option("--last-name", help="Registrant last name (optional).")
@_translate_keyring_errors
def recordings_registrants_add(meeting_id, from_json, email, first_name, last_name):
    """Same two-mode payload pattern as meetings registrants add."""
    field_flags = (email, first_name, last_name)
    any_field_flag = any(f is not None for f in field_flags)

    if from_json is not None:
        if any_field_flag:
            click.echo(
                "--from-json is mutually exclusive with --email / --first-name / --last-name.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    else:
        if not email or not first_name:
            click.echo(
                "Either (--email AND --first-name) or --from-json is required.",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        payload = {"email": email, "first_name": first_name}
        if last_name:
            payload["last_name"] = last_name

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            result = recordings.add_recording_registrant(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Registered. id: {result.get('id', '')}")
    if "share_url" in result:
        click.echo(f"share_url: {result['share_url']}")


def _recording_registrant_status_action(action: str, action_past: str):
    """Build one of the ``approve`` / ``deny`` subcommands. Recording
    registrants don't have ``cancel`` (unlike meeting registrants)."""

    @recordings_registrants_cmd.command(
        action,
        help=f"{action.capitalize()} one or more recording registrants.",
    )
    @click.argument("meeting_id")
    @click.option(
        "--registrant",
        "registrant_ids",
        multiple=True,
        required=True,
        help="Registrant ID. Repeat for bulk action.",
    )
    @click.option(
        "--yes",
        "-y",
        is_flag=True,
        default=False,
        help="Skip the confirmation prompt.",
    )
    @_translate_keyring_errors
    def _cmd(meeting_id, registrant_ids, yes):
        ids = list(registrant_ids)
        if not yes and not click.confirm(
            f"{action.capitalize()} {len(ids)} recording registrant(s) on meeting {meeting_id}?",
            default=False,
        ):
            click.echo("Aborted.")
            return
        creds = _load_creds_or_exit()
        try:
            with _build_api_client(creds) as client:
                recordings.update_recording_registrant_status(
                    client, meeting_id, action=action, registrant_ids=ids
                )
        except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
            _exit_on_api_error(exc)
        click.echo(f"{action_past} {len(ids)} recording registrant(s) on meeting {meeting_id}.")

    _cmd.__name__ = f"recordings_registrants_{action}"
    return _cmd


_recordings_registrants_approve = _recording_registrant_status_action("approve", "Approved")
_recordings_registrants_deny = _recording_registrant_status_action("deny", "Denied")


# ---- Recordings depth-completion: analytics + reg questions + archive --


@recordings_cmd.group(
    "analytics",
    help="Recording viewer analytics for a past meeting (Business+ plan).",
)
def recordings_analytics_cmd():
    """Group for ``zoom recordings analytics ...``."""


@recordings_analytics_cmd.command(
    "summary",
    help="Aggregated viewer metrics (GET /past_meetings/<id>/recordings/analytics_summary).",
)
@click.argument("meeting_id")
@_translate_keyring_errors
def recordings_analytics_summary(meeting_id):
    """JSON output. The summary contains aggregated stats (view_count,
    unique_viewer_count, average_watch_time, etc.)."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = recordings.get_analytics_summary(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(data, indent=2))


@recordings_analytics_cmd.command(
    "details",
    help="Per-viewer breakdown (GET /past_meetings/<id>/recordings/analytics_details).",
)
@click.argument("meeting_id")
@_translate_keyring_errors
def recordings_analytics_details(meeting_id):
    """JSON output. The details list nests per-viewer (who watched,
    when, how long) — too irregular for TSV."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = recordings.get_analytics_details(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(data, indent=2))


@recordings_registrants_cmd.group(
    "questions",
    help="Manage the recording registration form (custom questions).",
)
def recordings_registrants_questions_cmd():
    """Group for ``zoom recordings registrants questions ...``."""


@recordings_registrants_questions_cmd.command(
    "get",
    help="Print the registration form's questions as JSON.",
)
@click.argument("meeting_id")
@_translate_keyring_errors
def recordings_registrants_questions_get(meeting_id):
    """Output is raw JSON so it round-trips into ``... questions update --from-json``."""
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = recordings.get_recording_registration_questions(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(data, indent=2))


@recordings_registrants_questions_cmd.command(
    "update",
    help="Replace the registration form's questions (PATCH .../registrants/questions).",
)
@click.argument("meeting_id")
@click.option(
    "--from-json",
    "from_json",
    type=click.File("r", encoding="utf-8"),
    required=True,
    help="Read the full questions payload from JSON (or '-' for stdin).",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def recordings_registrants_questions_update(meeting_id, from_json, yes):
    """Wholesale-replace semantics — round-trip via ``questions get`` first."""
    payload = _load_json_payload_or_exit(from_json, label="--from-json input")
    if not yes and not click.confirm(
        f"Replace recording registration questions on meeting {meeting_id}?",
        default=False,
    ):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            recordings.update_recording_registration_questions(client, meeting_id, payload)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Updated recording registration questions for meeting {meeting_id}.")


@recordings_cmd.group(
    "archive",
    help="Manage archive files (Business+ archiving feature).",
)
def recordings_archive_cmd():
    """Group for ``zoom recordings archive ...``."""


@recordings_archive_cmd.command(
    "list",
    help="List archive files (paginates GET /archive_files).",
)
@click.option(
    "--from",
    "from_",
    help="ISO date (YYYY-MM-DD) lower bound on archive date.",
)
@click.option(
    "--to",
    help="ISO date (YYYY-MM-DD) upper bound on archive date.",
)
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
    help="Items per page request.",
)
@_translate_keyring_errors
def recordings_archive_list(from_, to, page_size):
    """TSV output (id\\tmeeting_id\\ttopic\\tarchive_date)."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\tmeeting_id\ttopic\tarchive_date")
            for af in recordings.list_archive_files(
                client, from_=from_, to=to, page_size=page_size
            ):
                click.echo(
                    f"{af.get('id', '')}\t"
                    f"{af.get('meeting_id', '')}\t"
                    f"{af.get('topic', '')}\t"
                    f"{af.get('archive_date', af.get('start_time', ''))}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@recordings_archive_cmd.command(
    "get",
    help="Print an archive file's metadata + per-format download URLs as JSON (GET /archive_files/<file-id>).",
)
@click.argument("file_id")
@_translate_keyring_errors
def recordings_archive_get(file_id):
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            data = recordings.get_archive_file(client, file_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(data, indent=2))


@recordings_archive_cmd.command(
    "delete",
    help="Permanently delete an archive file (DELETE /archive_files/<file-id>).",
)
@click.argument("file_id")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@_translate_keyring_errors
def recordings_archive_delete(file_id, yes):
    """No trash/recover step here — unlike standard recordings, archive
    file deletion is permanent. Confirms by default; `--yes` to skip."""
    if not yes and not click.confirm(
        f"Permanently delete archive file {file_id}? (no recover step)",
        default=False,
    ):
        click.echo("Aborted.")
        return
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            recordings.delete_archive_file(client, file_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Deleted archive file {file_id}.")


# ---- Zoom Dashboard / Metrics ------------------------------------------


@main.group(
    "dashboard",
    help=(
        "Zoom Dashboard / Metrics API (Business+ plans only). "
        "https://developers.zoom.us/docs/api/dashboards/"
    ),
)
def dashboard_cmd():
    """Group for ``zoom dashboard ...``. All endpoints sit on the HEAVY
    rate-limit tier (40/s + 60k/day)."""


@dashboard_cmd.group("meetings", help="Dashboard meeting metrics.")
def dashboard_meetings_cmd():
    pass


@dashboard_meetings_cmd.command("list", help="List meetings with metrics (paginated).")
@click.option(
    "--type",
    "type_",
    type=click.Choice(list(dashboard.ALLOWED_MEETING_METRIC_TYPES)),
    default="past",
    show_default=True,
)
@click.option("--from", "from_", required=True, metavar="YYYY-MM-DD")
@click.option("--to", required=True, metavar="YYYY-MM-DD")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def dashboard_meetings_list(type_, from_, to, page_size):
    """TSV: uuid\\tid\\ttopic\\thost\\tparticipants\\tduration\\tstart_time."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("uuid\tid\ttopic\thost\tparticipants\tduration\tstart_time")
            for m in dashboard.list_meetings(
                client,
                type=type_,
                from_=from_,
                to=to,
                page_size=page_size,
            ):
                click.echo(
                    f"{m.get('uuid', '')}\t"
                    f"{m.get('id', '')}\t"
                    f"{m.get('topic', '')}\t"
                    f"{m.get('host', '')}\t"
                    f"{m.get('participants', '')}\t"
                    f"{m.get('duration', '')}\t"
                    f"{m.get('start_time', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@dashboard_meetings_cmd.command("get", help="Print one meeting's dashboard metrics (JSON).")
@click.argument("meeting_id")
@_translate_keyring_errors
def dashboard_meetings_get(meeting_id):
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            envelope = dashboard.get_meeting(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(envelope, indent=2, sort_keys=True))


@dashboard_meetings_cmd.command(
    "participants",
    help="List participant metrics for one meeting (paginated).",
)
@click.argument("meeting_id")
@click.option(
    "--type",
    "type_",
    type=click.Choice(list(dashboard.ALLOWED_MEETING_METRIC_TYPES)),
    default="past",
    show_default=True,
)
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def dashboard_meetings_participants(meeting_id, type_, page_size):
    """TSV: id\\tuser_id\\tuser_name\\tjoin_time\\tleave_time\\tduration."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\tuser_id\tuser_name\tjoin_time\tleave_time\tduration")
            for p in dashboard.list_meeting_participants(
                client, meeting_id, type=type_, page_size=page_size
            ):
                click.echo(
                    f"{p.get('id', '')}\t"
                    f"{p.get('user_id', '')}\t"
                    f"{p.get('user_name', '')}\t"
                    f"{p.get('join_time', '')}\t"
                    f"{p.get('leave_time', '')}\t"
                    f"{p.get('duration', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@dashboard_cmd.group("zoomrooms", help="Zoom Rooms dashboard metrics.")
def dashboard_zoomrooms_cmd():
    pass


@dashboard_zoomrooms_cmd.command("list", help="List Zoom Rooms with metrics (paginated).")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def dashboard_zoomrooms_list(page_size):
    """TSV: id\\troom_name\\tstatus\\tdevice_ip\\tlast_start_time."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\troom_name\tstatus\tdevice_ip\tlast_start_time")
            for r in dashboard.list_zoomrooms(client, page_size=page_size):
                click.echo(
                    f"{r.get('id', '')}\t"
                    f"{r.get('room_name', '')}\t"
                    f"{r.get('status', '')}\t"
                    f"{r.get('device_ip', '')}\t"
                    f"{r.get('last_start_time', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@dashboard_zoomrooms_cmd.command(
    "get",
    help="Print one Zoom Room's dashboard metrics (JSON).",
)
@click.argument("room_id")
@_translate_keyring_errors
def dashboard_zoomrooms_get(room_id):
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            envelope = dashboard.get_zoomroom(client, room_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(envelope, indent=2, sort_keys=True))


# ---- Zoom Reports ------------------------------------------------------


@main.group(
    "reports",
    help="Zoom Reports API (https://developers.zoom.us/docs/api/reports/).",
)
def reports_cmd():
    """Group for ``zoom reports ...``. All Reports endpoints sit on the
    HEAVY rate-limit tier (40/s + 60k/day) — pass ``RateLimiter()`` to
    ``ApiClient`` for batch use to stay under the daily cap."""


@reports_cmd.command("daily", help="Daily account usage report (JSON dump).")
@click.option("--year", type=click.IntRange(2010, 2100), help="Year (default: current).")
@click.option(
    "--month",
    type=click.IntRange(1, 12),
    help="Month (default: current). Both --year and --month omitted = current month.",
)
@_translate_keyring_errors
def reports_daily(year, month):
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            envelope = reports.get_daily(client, year=year, month=month)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(envelope, indent=2, sort_keys=True))


@reports_cmd.group("meetings", help="Meeting-level reports.")
def reports_meetings_cmd():
    pass


@reports_meetings_cmd.command(
    "list",
    help="List meeting report entries (paginated).",
)
@click.option(
    "--user-id",
    default=None,
    help="Limit to one user. Omit for account-wide.",
)
@click.option("--from", "from_", required=True, metavar="YYYY-MM-DD")
@click.option("--to", required=True, metavar="YYYY-MM-DD")
@click.option(
    "--type",
    "meeting_type",
    type=click.Choice(["past", "pastOne", "pastJoined"]),
    help="Filter by meeting type.",
)
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def reports_meetings_list(user_id, from_, to, meeting_type, page_size):
    """TSV: uuid\\tid\\ttopic\\tuser_email\\tstart_time\\tduration\\tparticipants_count."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("uuid\tid\ttopic\tuser_email\tstart_time\tduration\tparticipants_count")
            for m in reports.list_meetings_report(
                client,
                user_id=user_id,
                from_=from_,
                to=to,
                meeting_type=meeting_type,
                page_size=page_size,
            ):
                click.echo(
                    f"{m.get('uuid', '')}\t"
                    f"{m.get('id', '')}\t"
                    f"{m.get('topic', '')}\t"
                    f"{m.get('user_email', '')}\t"
                    f"{m.get('start_time', '')}\t"
                    f"{m.get('duration', '')}\t"
                    f"{m.get('participants_count', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@reports_meetings_cmd.command(
    "participants",
    help="List participants for one meeting (paginated).",
)
@click.argument("meeting_id")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def reports_meetings_participants(meeting_id, page_size):
    """TSV: id\\tname\\tuser_email\\tjoin_time\\tleave_time\\tduration."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\tname\tuser_email\tjoin_time\tleave_time\tduration")
            for p in reports.list_meeting_participants(client, meeting_id, page_size=page_size):
                click.echo(
                    f"{p.get('id', '')}\t"
                    f"{p.get('name', '')}\t"
                    f"{p.get('user_email', '')}\t"
                    f"{p.get('join_time', '')}\t"
                    f"{p.get('leave_time', '')}\t"
                    f"{p.get('duration', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@reports_cmd.group("operationlogs", help="Admin operation logs.")
def reports_operationlogs_cmd():
    pass


@reports_operationlogs_cmd.command("list", help="List admin operation logs (paginated).")
@click.option("--from", "from_", required=True, metavar="YYYY-MM-DD")
@click.option("--to", required=True, metavar="YYYY-MM-DD")
@click.option(
    "--category-type",
    help="Filter by category (user, account, billing, zoom_rooms, ...).",
)
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def reports_operationlogs_list(from_, to, category_type, page_size):
    """TSV: time\\toperator\\tcategory_type\\taction\\toperation_detail."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("time\toperator\tcategory_type\taction\toperation_detail")
            for entry in reports.list_operation_logs(
                client,
                from_=from_,
                to=to,
                category_type=category_type,
                page_size=page_size,
            ):
                click.echo(
                    f"{entry.get('time', '')}\t"
                    f"{entry.get('operator', '')}\t"
                    f"{entry.get('category_type', '')}\t"
                    f"{entry.get('action', '')}\t"
                    f"{entry.get('operation_detail', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


# ---- Zoom Team Chat ----------------------------------------------------


@main.group(
    "chat",
    help="Zoom Team Chat API (https://developers.zoom.us/docs/api/chat/).",
)
def chat_cmd():
    """Group for ``zoom chat ...``."""


@chat_cmd.group("channels", help="Zoom chat channels.")
def chat_channels_cmd():
    pass


@chat_channels_cmd.command("list", help="List a user's chat channels (paginated).")
@click.option(
    "--user-id",
    default="me",
    show_default=True,
    help="Whose channels to list. Default 'me'.",
)
@click.option(
    "--page-size",
    type=click.IntRange(1, 50),
    default=50,
    show_default=True,
    help="Items per page (Zoom caps /chat/users/<id>/channels at 50).",
)
@_translate_keyring_errors
def chat_channels_list(user_id, page_size):
    """TSV: id\\tname\\ttype\\tchannel_settings.posting_permissions."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\tname\ttype")
            for ch in chat.list_channels(client, user_id=user_id, page_size=page_size):
                click.echo(f"{ch.get('id', '')}\t{ch.get('name', '')}\t{ch.get('type', '')}")
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@chat_cmd.group("messages", help="Zoom chat messages.")
def chat_messages_cmd():
    pass


@chat_messages_cmd.command("send", help="Send a chat message to a channel or contact.")
@click.option("--message", "message_text", required=True, help="Message body (text).")
@click.option("--to-channel", help="Target channel ID (mutually exclusive with --to-contact).")
@click.option(
    "--to-contact",
    help="Target contact email (mutually exclusive with --to-channel).",
)
@click.option(
    "--user-id",
    default="me",
    show_default=True,
    help="Sender. Default 'me' (the authenticated user).",
)
@click.option(
    "--reply-to",
    "reply_main_message_id",
    help="Make this a thread reply to the given main message ID.",
)
@_translate_keyring_errors
def chat_messages_send(message_text, to_channel, to_contact, user_id, reply_main_message_id):
    """Exactly one of --to-channel or --to-contact must be set. Prints
    the new message ID on success."""
    if (to_channel is None) == (to_contact is None):
        click.echo(
            "Pass exactly one of --to-channel or --to-contact (got both or neither).",
            err=True,
        )
        raise click.exceptions.Exit(code=1)

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            result = chat.send_message(
                client,
                message=message_text,
                to_channel=to_channel,
                to_contact=to_contact,
                user_id=user_id,
                reply_main_message_id=reply_main_message_id,
            )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    msg_id = result.get("id", "")
    click.echo(f"Sent message {msg_id}.")


# ---- Zoom Phone --------------------------------------------------------


@main.group(
    "phone",
    help="Zoom Phone API (https://developers.zoom.us/docs/api/phone/).",
)
def phone_cmd():
    """Group for ``zoom phone ...``."""


@phone_cmd.group("users", help="Zoom Phone users.")
def phone_users_cmd():
    pass


@phone_users_cmd.command("list", help="List phone-licensed users (paginated).")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def phone_users_list(page_size):
    """TSV: id\\temail\\textension_number\\tstatus."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\temail\textension_number\tstatus")
            for u in phone.list_phone_users(client, page_size=page_size):
                click.echo(
                    f"{u.get('id', '')}\t"
                    f"{u.get('email', '')}\t"
                    f"{u.get('extension_number', '')}\t"
                    f"{u.get('status', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@phone_users_cmd.command("get", help="Print a phone user's profile (JSON).")
@click.argument("user_id")
@_translate_keyring_errors
def phone_users_get(user_id):
    import json as _json

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            profile = phone.get_phone_user(client, user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(profile, indent=2, sort_keys=True))


@phone_cmd.group("call-logs", help="Zoom Phone call logs.")
def phone_call_logs_cmd():
    pass


@phone_call_logs_cmd.command("list", help="List call log entries (paginated).")
@click.option(
    "--user-id",
    default=None,
    help="Limit to one user's call logs. Omit for account-wide.",
)
@click.option("--from", "from_", metavar="YYYY-MM-DD", help="Lower bound on date.")
@click.option("--to", metavar="YYYY-MM-DD", help="Upper bound on date.")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def phone_call_logs_list(user_id, from_, to, page_size):
    """TSV: id\\tdirection\\tcaller_number\\tcallee_number\\tstart_time\\tduration."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\tdirection\tcaller_number\tcallee_number\tstart_time\tduration")
            for entry in phone.list_call_logs(
                client,
                user_id=user_id,
                from_=from_,
                to=to,
                page_size=page_size,
            ):
                click.echo(
                    f"{entry.get('id', '')}\t"
                    f"{entry.get('direction', '')}\t"
                    f"{entry.get('caller_number', '')}\t"
                    f"{entry.get('callee_number', '')}\t"
                    f"{entry.get('start_time', '')}\t"
                    f"{entry.get('duration', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@phone_cmd.group("queues", help="Zoom Phone call queues.")
def phone_queues_cmd():
    pass


@phone_queues_cmd.command("list", help="List call queues (paginated).")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def phone_queues_list(page_size):
    """TSV: id\\tname\\textension_number\\tsite_name."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\tname\textension_number\tsite_name")
            for q in phone.list_call_queues(client, page_size=page_size):
                click.echo(
                    f"{q.get('id', '')}\t"
                    f"{q.get('name', '')}\t"
                    f"{q.get('extension_number', '')}\t"
                    f"{q.get('site', {}).get('name', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@phone_cmd.group("recordings", help="Zoom Phone call recordings.")
def phone_recordings_cmd():
    pass


@phone_recordings_cmd.command(
    "download",
    help="Download a single phone call recording to disk.",
)
@click.argument("recording_id")
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, writable=True, resolve_path=True),
    default=".",
    show_default=True,
    help="Directory to write the file into. Created automatically if missing.",
)
@_translate_keyring_errors
def phone_recordings_download(recording_id, out_dir):
    """Fetches the recording's metadata to learn the download_url, then
    streams it to disk via the same atomic tempfile + os.replace path
    used by `zoom recordings download`. Filename convention:
    ``<recording_id>.<file_extension>``."""
    import os
    import pathlib

    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)

    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            rec = phone.get_phone_recording(client, recording_id)
            url = rec.get("download_url")
            if not url:
                click.echo(
                    f"No download_url for recording {recording_id} "
                    "(may already be deleted or trashed).",
                    err=True,
                )
                raise click.exceptions.Exit(code=1)
            ext = (rec.get("file_extension") or "mp3").lower()
            dest = os.path.join(out_dir, f"{recording_id}.{ext}")
            bytes_written = client.stream_download(url, dest)
            click.echo(f"Downloaded {dest} ({bytes_written} bytes)")
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


@phone_recordings_cmd.command("list", help="List phone call recordings (paginated).")
@click.option(
    "--user-id",
    default=None,
    help="Limit to one user. Omit for account-wide.",
)
@click.option("--from", "from_", metavar="YYYY-MM-DD")
@click.option("--to", metavar="YYYY-MM-DD")
@click.option(
    "--page-size",
    type=click.IntRange(1, 300),
    default=300,
    show_default=True,
)
@_translate_keyring_errors
def phone_recordings_list(user_id, from_, to, page_size):
    """TSV: id\\tcaller_number\\tcallee_number\\tdate_time\\tduration."""
    creds = _load_creds_or_exit()
    try:
        with _build_api_client(creds) as client:
            click.echo("id\tcaller_number\tcallee_number\tdate_time\tduration")
            for r in phone.list_phone_recordings(
                client,
                user_id=user_id,
                from_=from_,
                to=to,
                page_size=page_size,
            ):
                click.echo(
                    f"{r.get('id', '')}\t"
                    f"{r.get('caller_number', '')}\t"
                    f"{r.get('callee_number', '')}\t"
                    f"{r.get('date_time', '')}\t"
                    f"{r.get('duration', '')}"
                )
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)


# ---- Zoom Webhooks ------------------------------------------------------


@main.group(
    "webhook",
    help="Local HMAC-verified Zoom webhook receiver (closes #17).",
)
def webhook_cmd():
    """Group for ``zoom webhook ...``."""


@webhook_cmd.command(
    "serve",
    help=(
        "Run a local HTTP server that receives + verifies Zoom webhooks. "
        "Use with ngrok or similar to expose to the internet during dev."
    ),
)
@click.option(
    "--secret-token",
    envvar="ZOOM_WEBHOOK_SECRET",
    required=True,
    help=(
        "The webhook secret token from the Zoom Marketplace app's "
        "Feature -> Event Subscriptions tab. Picks up "
        "ZOOM_WEBHOOK_SECRET env var."
    ),
)
@click.option(
    "--bind",
    default="127.0.0.1",
    show_default=True,
    help="Address to bind. Default 127.0.0.1 (loopback only).",
)
@click.option(
    "--port",
    type=click.IntRange(1, 65535),
    default=8000,
    show_default=True,
    help="Port to listen on.",
)
def webhook_serve(secret_token, bind, port):
    """Streams verified events to stdout as one-line JSON; rejected
    deliveries get a 401 + a stderr line. Ctrl-C exits cleanly. Closes
    #17."""
    webhook.run_webhook_server(secret_token, bind=bind, port=port)


if __name__ == "__main__":
    main()


#############################
##  zoom [url]
##  zoom [name]
##  zoom save -n [name] --url [url]
##  zoom save -n [name] --id [id] -p [password]
##  zoom ls
##  zoom rm [name]
##  zoom edit [name] (can provide options for url, id, and password. Will prompt for everything missing)
#############################
