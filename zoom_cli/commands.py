import click
import questionary

from zoom_cli import secrets
from zoom_cli.utils import (
    ConsoleColor,
    LauncherUnavailableError,
    UntrustedHostError,
    get_meeting_file_contents,
    launch_zoommtg,
    launch_zoommtg_url,
    meeting_file_transaction,
    parse_meeting_url,
    strip_url_scheme,
)


def _resolve_password(name: str, entry: dict, url_password: str = "") -> str:
    """Pick the right password for a saved meeting.

    Resolution order:
    1. OS keyring (new entries land here as of #5).
    2. Plaintext ``password`` field in ``meetings.json`` (back-compat for
       entries saved before keyring migration).
    3. ``pwd=`` extracted from the saved URL.

    Empty strings count as a deliberate "no password" — only ``None`` from
    the keyring falls through to step 2.
    """
    keyring_pw = secrets.get_password(name)
    if keyring_pw is not None:
        return keyring_pw
    return entry.get("password", url_password)


def _print_error(message: str) -> None:
    print(ConsoleColor.BOLD + "Error:" + ConsoleColor.END, end=" ")
    print(message)


def _launch_url(url: str) -> None:
    """Launch a Zoom meeting from any URL by rewriting the scheme to ``zoommtg://``.

    Accepts URLs with or without an existing scheme. Only catches the
    expected user-facing error types so that genuine bugs propagate instead
    of being swallowed by a bare ``except``. ``UntrustedHostError`` is a
    defense-in-depth catch — the ``launch`` CLI command pre-validates the
    host, so this path normally only sees trusted URLs.
    """
    rebuilt = f"zoommtg://{strip_url_scheme(url)}"
    try:
        launch_zoommtg_url(rebuilt)
    except LauncherUnavailableError as exc:
        _print_error(str(exc))
    except UntrustedHostError as exc:
        _print_error(str(exc))


def _launch_name(name: str) -> None:
    contents = get_meeting_file_contents()

    if name not in contents:
        _print_error(
            "Could not find meeting with title " + ConsoleColor.BOLD + name + ConsoleColor.END + "."
        )
        return

    entry = contents[name]

    try:
        if "url" in entry:
            meeting_id, url_password = parse_meeting_url(entry["url"])
            password = _resolve_password(name, entry, url_password)

            if meeting_id is not None:
                launch_zoommtg(meeting_id, password)
                return

            # No /j/<id> path — likely a personal link (/s/<name>) or web-client URL.
            # Pass it through the zoommtg:// launcher so the desktop client
            # handles the resolution. We append the password only if the URL
            # does NOT already carry one, otherwise launch_zoommtg_url would
            # double-append `&pwd=...`.
            extra_pwd = "" if url_password else password
            launch_zoommtg_url(f"zoommtg://{strip_url_scheme(entry['url'])}", extra_pwd)
            return

        if "id" in entry:
            launch_zoommtg(entry["id"], _resolve_password(name, entry))
            return

        _print_error(
            "No url or id found for meeting with title "
            + ConsoleColor.BOLD
            + name
            + ConsoleColor.END
            + "."
        )
    except LauncherUnavailableError as exc:
        _print_error(str(exc))
    except UntrustedHostError as exc:
        _print_error(str(exc))


def _save_url(name, url, password):
    # Write the keyring BEFORE writing the JSON. If the keyring write fails
    # (e.g. backend unhealthy), the user's existing meetings.json is left
    # untouched — they don't end up with a meeting that has no usable
    # password anywhere. Codex review on #28 caught this ordering bug.
    if password:
        secrets.set_password(name, password)
    else:
        secrets.delete_password(name)

    # `meeting_file_transaction` takes the exclusive lock, yields the
    # current contents, and persists on exit (closes #39 — concurrent
    # invocations no longer overwrite each other's updates).
    with meeting_file_transaction() as contents:
        contents[name] = {"url": url}


def _save_id_password(name, id, password):
    if password:
        secrets.set_password(name, password)
    else:
        secrets.delete_password(name)

    with meeting_file_transaction() as contents:
        contents[name] = {"id": id}


def _edit(name, url, id, password):
    legacy_plaintext_password: str | None = None

    with meeting_file_transaction() as contents:
        new_dict: dict[str, str] = {}
        if url:
            new_dict["url"] = url
        if id:
            new_dict["id"] = id

        # For each existing non-secret field, re-prompt with the new value (if a
        # flag was passed) or the old value as the default. The user can clear a
        # field by submitting an empty string; only Ctrl-C aborts. Passwords are
        # NOT re-prompted here — they live in the keyring and are managed via
        # the explicit ``--password`` flag.
        for key, val in contents[name].items():
            if key == "password":
                # Legacy plaintext password from a pre-keyring entry. Capture it
                # so we can migrate it into the keyring below — never just drop
                # it (all three reviewers on #28 flagged the silent loss).
                legacy_plaintext_password = val
                continue
            answer = questionary.text(key, default=new_dict.get(key, val)).ask()
            if answer is None:
                raise click.Abort
            new_dict[key] = answer

        # Password handling — keyring is the source of truth.
        # Order matters: write keyring before rewriting JSON so a keyring-side
        # failure leaves the user's prior state intact.
        if password:
            # Explicit --password flag wins.
            secrets.set_password(name, password)
        elif legacy_plaintext_password is not None and secrets.get_password(name) is None:
            # Migrate legacy plaintext into the keyring on first edit. Only do
            # this if there's no existing keyring entry — never overwrite a
            # newer keyring value with stale legacy plaintext.
            secrets.set_password(name, legacy_plaintext_password)

        del contents[name]
        contents[name] = new_dict


def _remove(name):
    with meeting_file_transaction() as contents:
        del contents[name]
    secrets.delete_password(name)


def _ls():
    meetings = get_meeting_file_contents()

    for idx, (name, entries) in enumerate(meetings.items()):
        print(ConsoleColor.BOLD + name + ConsoleColor.END)
        if "url" in entries:
            print(ConsoleColor.BOLD + "    url: " + ConsoleColor.END + entries["url"])
        if "id" in entries:
            print(ConsoleColor.BOLD + "    id: " + ConsoleColor.END + entries["id"])
        # Passwords are masked. They live in the OS keyring (or, for
        # not-yet-migrated entries, plaintext in meetings.json).
        has_password = "password" in entries or secrets.get_password(name) is not None
        if has_password:
            print(ConsoleColor.BOLD + "    password: " + ConsoleColor.END + "********")

        if idx < len(meetings) - 1:
            print()
