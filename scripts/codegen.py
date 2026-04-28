#!/usr/bin/env python3
"""Generate Pydantic v2 models from a Zoom OpenAPI v2 spec (closes #22).

Wraps ``datamodel-code-generator`` with the flags this project wants.
The actual codegen is delegated — this script's job is to:

  1. Make the invocation reproducible (same flags every time, pinned in
     code rather than in a developer's shell history).
  2. Produce output in the project's preferred shape:
     - Pydantic v2 (not v1) — ``--output-model-type pydantic_v2.BaseModel``
     - One file per tag (e.g. ``users.py``, ``meetings.py``) so the
     generated tree mirrors ``zoom_cli/api/`` itself.
     - ``from __future__ import annotations`` everywhere — keeps
     forward refs trivial without a string-quote dance.
  3. Drop into ``zoom_cli/api/_generated/`` (gitignored by default —
     teams that want to commit the generated tree can opt in).

The Zoom OpenAPI spec lives at <https://developers.zoom.us/openapi-spec/>.
This script accepts a local path; it does not bundle the spec because
it's large (~1.5 MB) and changes frequently — keep it as a fetch-on-
demand workflow rather than a build artefact.

Optional install: ``pip install -e '.[codegen]'`` (adds
``datamodel-code-generator``).

Usage:

    # 1. Fetch the spec (one-time or periodic):
    curl -o /tmp/zoom-openapi.json https://developers.zoom.us/openapi-spec/...

    # 2. Run the generator:
    python scripts/codegen.py /tmp/zoom-openapi.json

    # 3. Review the diff in zoom_cli/api/_generated/ and decide what to
    #    commit (if anything — the generated tree is gitignored by default).

What this script does NOT do (deferred to follow-ups):
  - Bundle the spec in the repo (large, fast-moving, not the right place).
  - Wire generated models into existing helpers (``users.py`` etc. still
    return raw ``dict[str, Any]``). Migration is opt-in per endpoint.
  - Provide pre-generated models. Each developer runs the script.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

#: Default output directory, relative to the repo root.
DEFAULT_OUTPUT_DIR = Path("zoom_cli/api/_generated")


def _build_argv(spec_path: Path, output_dir: Path) -> list[str]:
    """Construct the datamodel-codegen argv. Pulled out for testability."""
    return [
        "datamodel-codegen",
        "--input",
        str(spec_path),
        "--input-file-type",
        "openapi",
        "--output",
        str(output_dir),
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--use-double-quotes",
        "--use-standard-collections",
        "--use-union-operator",
        "--use-schema-description",
        "--use-field-description",
        "--field-constraints",
        "--target-python-version",
        "3.10",
        "--enum-field-as-literal",
        "all",
    ]


def _fetch_spec_to_tempfile(url: str) -> Path:
    """Fetch ``url`` over HTTPS via httpx (already a runtime dep) and write
    to a tempfile under ``$TMPDIR``. Returns the tempfile path; the
    caller owns cleanup (we don't unlink — the spec is small enough to
    leak harmlessly and useful to inspect on failure).

    Pulled out for testability. We don't reuse the project's ApiClient
    because the OpenAPI spec is hosted on a public HTTP endpoint with
    no authentication, and ApiClient would inject a bearer token.
    """
    import tempfile

    import httpx

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        body = response.content

    fd, path = tempfile.mkstemp(prefix="zoom-openapi.", suffix=".json")
    with open(fd, "wb") as f:
        f.write(body)
    return Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Pydantic v2 models from a Zoom OpenAPI spec.",
    )
    # `spec` and `--from-url` are mutually exclusive: exactly one must
    # be provided. argparse handles the required+exclusive contract.
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "spec",
        nargs="?",
        type=Path,
        default=None,
        help="Path to a local Zoom OpenAPI 3 spec (JSON or YAML).",
    )
    source.add_argument(
        "--from-url",
        dest="from_url",
        metavar="URL",
        help=(
            "Fetch the spec from a URL (HTTPS) and run codegen on it. "
            "Saves a `curl` step; the fetched spec is left in $TMPDIR "
            "for inspection."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Where to write generated models (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the datamodel-codegen invocation without running it.",
    )
    args = parser.parse_args(argv)

    # Resolve the input source.
    if args.from_url is not None:
        try:
            spec_path = _fetch_spec_to_tempfile(args.from_url)
        except Exception as exc:
            print(f"error: failed to fetch spec from {args.from_url}: {exc}", file=sys.stderr)
            return 1
        print(f"Fetched spec from {args.from_url} -> {spec_path}")
    else:
        spec_path = args.spec
        if not spec_path.exists():
            print(f"error: spec file not found: {spec_path}", file=sys.stderr)
            return 1

    if shutil.which("datamodel-codegen") is None:
        print(
            "error: `datamodel-codegen` not on PATH. Install with:\n  pip install -e '.[codegen]'",
            file=sys.stderr,
        )
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cmd = _build_argv(spec_path, args.output_dir)

    if args.dry_run:
        print("Would run:", " ".join(cmd))
        return 0

    print(f"Generating Pydantic models from {spec_path} -> {args.output_dir} ...")
    # The argv here is constructed from a literal command name +
    # explicit flags + caller-controlled paths; safe from shell injection
    # (no shell, list-form argv).
    result = subprocess.run(cmd, check=False)  # noqa: S603
    if result.returncode != 0:
        print(
            f"datamodel-codegen exited with status {result.returncode}",
            file=sys.stderr,
        )
        return result.returncode
    print("Done. Review the diff with `git status zoom_cli/api/_generated/`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
