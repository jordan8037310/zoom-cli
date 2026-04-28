#!/usr/bin/env python3
"""Programmatic batch use of the Zoom API client with proactive rate limiting.

Use case: a long-running script that touches many users / meetings and
wants to stay well under Zoom's per-account per-tier limits without
relying solely on reactive 429 backoff.

The CLI itself doesn't enable the rate limiter by default (it's
opt-in via the constructor) — this script shows how to wire it up.

Requires: `zoom auth s2s set` to have run first (or for the script to
be invoked with ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET
in the environment if zoom-cli is configured to read them).
"""

from __future__ import annotations

import sys

from zoom_cli import auth
from zoom_cli.api.client import ApiClient
from zoom_cli.api.rate_limit import RateLimiter
from zoom_cli.api.users import list_users


def main() -> int:
    creds = auth.load_s2s_credentials()
    if creds is None:
        print(
            "No Server-to-Server OAuth credentials saved. Run `zoom auth s2s set` first.",
            file=sys.stderr,
        )
        return 1

    # The limiter throttles to Zoom's published per-tier caps (80/60/40/20
    # per second; HEAVY + RESOURCE_INTENSIVE additionally cap at 60k/day).
    # `ApiClient` will block (or raise DailyCapExhaustedError) before
    # sending if a bucket is empty.
    rate_limiter = RateLimiter()

    with ApiClient(creds, rate_limiter=rate_limiter) as client:
        # `list_users` paginates transparently; each page request goes
        # through the limiter. For a large account this safely walks
        # thousands of users at the MEDIUM tier (60/s).
        for user in list_users(client, status="active"):
            # Replace this with the real per-user work — list their
            # meetings, fetch settings, etc. Each subsequent call
            # also goes through the limiter automatically.
            print(f"{user.get('id', '')}\t{user.get('email', '')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
