#!/usr/bin/env bash
# Download every recording from the last 7 days into ./recordings/.
#
# Walks `zoom recordings list` (paginated) for the date range, then
# invokes `zoom recordings download` per meeting. Each download is
# atomic (sibling tempfile + os.replace) so a network drop never
# leaves a half-written file at the destination.
#
# Requires: `zoom auth s2s set` to have run first.

set -euo pipefail

OUT_DIR="${1:-./recordings}"
mkdir -p "$OUT_DIR"

# 7 days ago in YYYY-MM-DD format. macOS `date` and GNU `date` differ;
# Python is more portable for date math.
SINCE="$(python3 -c 'from datetime import date, timedelta; print(date.today() - timedelta(days=7))')"

echo "Downloading recordings since $SINCE into $OUT_DIR ..."

# `zoom recordings list` outputs TSV: uuid, meeting_id, topic, start_time, file_count
# Skip the header, skip rows with file_count = 0.
zoom recordings list --from "$SINCE" \
    | tail -n +2 \
    | awk -F$'\t' '$5 != "0" {print $2}' \
    | while read -r meeting_id; do
        echo "→ meeting $meeting_id"
        zoom recordings download "$meeting_id" --out-dir "$OUT_DIR"
    done

echo "Done."
