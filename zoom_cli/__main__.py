import functools
import os

import click
import httpx
import keyring.errors
import questionary
from click_default_group import DefaultGroup

from zoom_cli import auth
from zoom_cli.api import meetings, oauth, recordings, user_oauth, users, webhook
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
    """Load S2S creds, exit cleanly with a friendly message if not configured."""
    creds = auth.load_s2s_credentials()
    if creds is None:
        click.echo("No Server-to-Server OAuth credentials saved. Run `zoom auth s2s set` first.")
        raise click.exceptions.Exit(code=1)
    return creds


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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
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
    """Group for ``zoom users settings ...``. Currently only ``get`` is
    implemented; ``update`` (PATCH /users/<id>/settings) is deferred to
    a follow-up — the settings payload has ~50 fields and needs design
    work to map to flags coherently."""


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
        with ApiClient(creds) as client:
            settings = users.get_user_settings(client, user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(_json.dumps(settings, indent=2, sort_keys=True))


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


@meetings_cmd.command("create", help="Schedule a new meeting (POST /users/<user-id>/meetings).")
@click.option("--topic", required=True, help="Meeting topic / title.")
@click.option(
    "--type",
    "meeting_type",
    type=click.IntRange(1, 8),
    default=2,
    show_default=True,
    help="1=instant, 2=scheduled, 3=recurring no-fixed-time, 8=recurring fixed-time.",
)
@click.option("--start-time", help="ISO 8601 (required for type 2 / 8). e.g. 2026-04-29T15:00:00Z")
@click.option(
    "--duration",
    type=click.IntRange(1, 1440),
    default=60,
    show_default=True,
    help="Minutes.",
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
def meetings_create(topic, meeting_type, start_time, duration, tz, password, agenda, user_id):
    """Closes #13 (write piece). Settings (massive sub-object) and
    recurrence (also complex sub-object) are out of scope for this PR —
    use the JSON API directly for those until a follow-up adds flags."""
    payload = _build_meeting_payload(
        topic=topic,
        meeting_type=meeting_type,
        start_time=start_time,
        duration=duration,
        timezone=tz,
        password=password,
        agenda=agenda,
    )
    creds = _load_creds_or_exit()
    try:
        with ApiClient(creds) as client:
            created = meetings.create_meeting(client, payload, user_id=user_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    _print_meeting_detail(created)


@meetings_cmd.command("update", help="Update an existing meeting (PATCH /meetings/<meeting-id>).")
@click.argument("meeting_id")
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
def meetings_update(meeting_id, topic, meeting_type, start_time, duration, tz, password, agenda):
    """Partial update — only flags you pass are sent. Zoom leaves omitted
    fields untouched (PATCH semantics)."""
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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
            meetings.end_meeting(client, meeting_id)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    click.echo(f"Ended meeting {meeting_id}.")


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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
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
        with ApiClient(creds) as client:
            if file_id:
                recordings.delete_recording_file(client, meeting_id, file_id, action=action)
            else:
                recordings.delete_recordings(client, meeting_id, action=action)
    except (oauth.ZoomAuthError, ZoomApiError, httpx.HTTPError) as exc:
        _exit_on_api_error(exc)
    verb = "Deleted" if action == "delete" else "Trashed"
    click.echo(f"{verb} {target}.")


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
