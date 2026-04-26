import click
import questionary

from zoom_cli.utils import (
    ConsoleColor,
    LauncherUnavailableError,
    get_meeting_file_contents,
    launch_zoommtg,
    launch_zoommtg_url,
    parse_meeting_url,
    strip_url_scheme,
    write_to_meeting_file,
)


def _print_error(message: str) -> None:
    print(ConsoleColor.BOLD + "Error:" + ConsoleColor.END, end=" ")
    print(message)


def _launch_url(url: str) -> None:
    """Launch a Zoom meeting from any URL by rewriting the scheme to ``zoommtg://``.

    Accepts URLs with or without an existing scheme. Only catches
    ``LauncherUnavailableError`` so that genuine bugs propagate instead of
    being swallowed by a bare ``except``.
    """
    rebuilt = f"zoommtg://{strip_url_scheme(url)}"
    try:
        launch_zoommtg_url(rebuilt)
    except LauncherUnavailableError as exc:
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
            # Presence-check via dict.get: a deliberately empty saved password
            # ({"password": ""}) returns "" — meaning "no password" — rather
            # than falling back to url_password. Preserves the contract from
            # PR #25 where `_edit` lets users intentionally clear a field.
            password = entry.get("password", url_password)

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
            launch_zoommtg(entry["id"], entry.get("password", ""))
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


def _save_url(name, url, password):
    contents = get_meeting_file_contents()
    contents[name] = {"url": url}
    if password:
        contents[name]["password"] = password
    write_to_meeting_file(contents)


def _save_id_password(name, id, password):
    contents = get_meeting_file_contents()
    contents[name] = {"id": id}
    if password:
        contents[name]["password"] = password
    write_to_meeting_file(contents)


def _edit(name, url, id, password):
    contents = get_meeting_file_contents()
    new_dict: dict[str, str] = {}

    if url:
        new_dict["url"] = url
    if id:
        new_dict["id"] = id
    if password:
        new_dict["password"] = password

    # For each existing field, re-prompt with the new value (if a flag was
    # passed) or the old value as the default. The user can intentionally
    # clear a field by submitting an empty string; only Ctrl-C aborts.
    for key, val in contents[name].items():
        answer = questionary.text(key, default=new_dict.get(key, val)).ask()
        if answer is None:
            raise click.Abort
        new_dict[key] = answer

    del contents[name]
    contents[name] = new_dict
    write_to_meeting_file(contents)


def _remove(name):
    contents = get_meeting_file_contents()
    del contents[name]
    write_to_meeting_file(contents)


def _ls():
    meetings = get_meeting_file_contents()

    for idx, (name, entries) in enumerate(meetings.items()):
        print(ConsoleColor.BOLD + name + ConsoleColor.END)
        if "url" in entries:
            print(ConsoleColor.BOLD + "    url: " + ConsoleColor.END + entries["url"])
        if "id" in entries:
            print(ConsoleColor.BOLD + "    id: " + ConsoleColor.END + entries["id"])
        if "password" in entries:
            print(ConsoleColor.BOLD + "    password: " + ConsoleColor.END + entries["password"])

        if idx < len(meetings) - 1:
            print()
