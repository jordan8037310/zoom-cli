import questionary

from zoom_cli.utils import (
    ConsoleColor,
    get_meeting_file_contents,
    launch_zoommtg,
    launch_zoommtg_url,
    write_to_meeting_file,
)


def _launch_url(url):
    try:
        url_to_launch = url[url.index("://") + 3 :] if "://" in url else url
        launch_zoommtg_url(f"zoommtg://{url_to_launch}")
    except Exception:
        print(ConsoleColor.BOLD + "Error:" + ConsoleColor.END, end=" ")
        print("Unable to launch given URL:  " + ConsoleColor.BOLD + url + ConsoleColor.END + ".")


def _launch_name(name):
    contents = get_meeting_file_contents()

    if name in contents:
        if "url" in contents[name]:
            url = contents[name]["url"]

            # Extract id from URL: between "/j/" and either "?" or end-of-string.
            id_start = url.index("/j/") + 3
            query_idx = url.index("?") if "?" in url else len(url)
            id = url[id_start:query_idx]
            password = ""

            if "pwd=" in url:
                pwd_start = url.index("pwd=") + 4
                pwd_end = url.index("&", pwd_start) if "&" in url[pwd_start:] else len(url)
                password = url[pwd_start:pwd_end]

            launch_zoommtg(id, contents[name].get("password", password))
        elif "id" in contents[name]:
            launch_zoommtg(contents[name]["id"], contents[name].get("password", ""))
        else:
            print(ConsoleColor.BOLD + "Error:" + ConsoleColor.END, end=" ")
            print(
                "No url or id found for meeting with title "
                + ConsoleColor.BOLD
                + name
                + ConsoleColor.END
                + "."
            )
    else:
        print(ConsoleColor.BOLD + "Error:" + ConsoleColor.END, end=" ")
        print(
            "Could not find meeting with title " + ConsoleColor.BOLD + name + ConsoleColor.END + "."
        )


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

    for key, val in contents[name].items():
        new_dict[key] = questionary.text(key, default=new_dict.get(key, val)).ask() or val

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
