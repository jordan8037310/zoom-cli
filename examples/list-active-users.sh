#!/usr/bin/env bash
# List all active Zoom users in the account, sorted by email.
#
# `zoom users list` emits TSV with a header row, designed to pipe through
# the standard text tools (cut/awk/sort/column/etc.).
#
# Requires: `zoom auth s2s set` to have run first (or set ZOOM_ACCOUNT_ID +
# ZOOM_CLIENT_ID + ZOOM_CLIENT_SECRET environment variables).

set -euo pipefail

# Skip the header row, then grab the email column (field 2) and sort.
zoom users list --status active \
    | tail -n +2 \
    | cut -f2 \
    | sort -u
