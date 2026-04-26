import click
import httpx
import questionary
from click_default_group import DefaultGroup

from zoom_cli import auth
from zoom_cli.api import oauth
from zoom_cli.commands import (
    _edit,
    _launch_name,
    _launch_url,
    _ls,
    _remove,
    _save_id_password,
    _save_url,
)
from zoom_cli.utils import __version__, get_meeting_names


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


@click.group(cls=DefaultGroup, default="launch", default_if_no_args=True)
@click.version_option(__version__)
def main():
    pass


@main.command(help="Launch meeting [url or saved meeting name]")
@click.argument("url_or_name")
def launch(url_or_name):
    if "://" in url_or_name or "zoom.us" in url_or_name:
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


@s2s.command("set", help="Save Server-to-Server OAuth credentials to the OS keyring.")
@click.option("--account-id", default="", help="Zoom Account ID")
@click.option("--client-id", default="", help="Server-to-Server OAuth Client ID")
@click.option("--client-secret", default="", help="Server-to-Server OAuth Client Secret")
def s2s_set(account_id, client_id, client_secret):
    if not account_id:
        account_id = _ask_or_abort(questionary.text("Account ID:"))
    if not client_id:
        client_id = _ask_or_abort(questionary.text("Client ID:"))
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
    if auth.has_s2s_credentials():
        click.echo("Server-to-Server OAuth: configured")
    else:
        click.echo("Server-to-Server OAuth: not configured")
        click.echo("Run `zoom auth s2s set` to configure.")


@auth_cmd.command(help="Clear all stored API authentication credentials.")
def logout():
    auth.clear_s2s_credentials()
    click.echo("Cleared Server-to-Server OAuth credentials.")


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
