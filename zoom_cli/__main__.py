import click
import questionary
from click_default_group import DefaultGroup

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
        name = questionary.text("Meeting name:").ask() or ""

    save_as_url: bool | None = None
    if not url and not id:
        choice = questionary.select(
            "Store as URL or Meeting ID/Password?",
            choices=["URL", "Meeting ID/Password"],
        ).ask()
        save_as_url = choice == "URL"

    if not url and save_as_url is True:
        url = questionary.text("Zoom URL:").ask() or ""

    if url and save_as_url is True and "pwd=" not in url:
        password = questionary.text("Meeting password:").ask() or ""

    if not id and save_as_url is False:
        id = questionary.text("Meeting ID:").ask() or ""
        password = questionary.text("Meeting password:").ask() or ""

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
        name = (
            questionary.select(
                "Meeting name:",
                choices=get_meeting_names(),
            ).ask()
            or ""
        )

    _edit(name, url, id, password)


@main.command(help="Delete meeting")
@click.argument("name", required=False)
def rm(name):
    if not name:
        name = (
            questionary.select(
                "Meeting name:",
                choices=get_meeting_names(),
            ).ask()
            or ""
        )

    _remove(name)


@main.command(help="List all saved meetings")
def ls():
    _ls()


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
