# Zoom CLI

[![CI](https://github.com/jordan8037310/zoom-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/jordan8037310/zoom-cli/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`zoom` is a command line tool that lets you store, access, and launch Zoom meetings on the fly. Written in Python, available via Homebrew.

> **Heads up — fork in flight.** This fork (`jordan8037310/zoom-cli`) is being modernized and expanded toward Zoom REST API integration. See [`docs/comparative-analysis.md`](docs/comparative-analysis.md) for the maturity assessment and roadmap, and [`CHANGELOG.md`](CHANGELOG.md) for changes. Upstream is [`tmonfre/zoom-cli`](https://github.com/tmonfre/zoom-cli).

## Installation Instructions

### Mac/Linux Users

1. Download and install Homebrew: [https://brew.sh](https://brew.sh).
2. `brew tap tmonfre/homebrew-tmonfre`
3. `brew install zoom`
4. (Only if zoom cask is also installed) `brew link zoom`

### PC Users

This package is currently not yet available on Scoop. Please follow the [developer instructions](#developer-instructions) below in the meantime.

## Usage

Below are the available commands. If an option/flag listed below is omitted, you will be prompted to enter its value.

### Launch Meetings

- `zoom [url]` to launch any meeting on the fly.
- `zoom [name]` to launch a saved meeting by name.

### Save Meetings

- `zoom save` to save a new meeting
  - `-n, --name` meeting name
  - `--id` meeting ID
  - `--password` meeting password (optional)
  - `--url` meeting URL (optional, must provide this or `--id`)

- `zoom edit` to edit a stored meeting
  - `-n, --name` meeting name (optional)
  - `--id` meeting ID (optional)
  - `--password` meeting password (optional)
  - `--url` meeting URL (optional)

- `zoom rm [name]` to delete a stored meeting

- `zoom ls` to see all stored meetings

## Developer Instructions

Interested in contributing? Follow the steps below to install the project locally. Open a pull request and reference the related issue (`Closes #N`).

1. Ensure you have **Python 3.10+** installed.
2. Clone this repository.
3. Create a virtual environment and install in editable mode with dev extras:

    ```shell
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e '.[dev]'
    ```

4. Run the test suite, lint, and type-check:

    ```shell
    pytest                # tests + coverage
    ruff check .          # lint
    ruff format --check . # formatting
    mypy                  # type check
    ```

5. Run the CLI directly: `python -m zoom_cli` or `./cli.py`.
6. Build a distributable binary with PyInstaller (optional, for releases):

    ```shell
    pip install -e '.[build]'
    ./build.sh
    ```

    A binary named `zoom` will be generated in `dist/`. The script also generates `dist/zoom.tar.gz` and prints its SHA-256 hash for the Homebrew formula.

## Project layout

```
zoom_cli/        # package — CLI entrypoint, commands, storage helpers
tests/           # pytest suite (utils, commands, CLI surface)
docs/            # design notes & comparative analysis
.github/         # CI workflow
cli.py           # PyInstaller entrypoint shim
```

See [`CLAUDE.md`](CLAUDE.md) for AI-assistant project conventions and [`CHANGELOG.md`](CHANGELOG.md) for the running release notes.
