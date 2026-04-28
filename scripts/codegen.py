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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Pydantic v2 models from a Zoom OpenAPI spec.",
    )
    parser.add_argument(
        "spec",
        type=Path,
        help="Path to a local Zoom OpenAPI 3 spec (JSON or YAML).",
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

    if not args.spec.exists():
        print(f"error: spec file not found: {args.spec}", file=sys.stderr)
        return 1

    if shutil.which("datamodel-codegen") is None:
        print(
            "error: `datamodel-codegen` not on PATH. Install with:\n  pip install -e '.[codegen]'",
            file=sys.stderr,
        )
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cmd = _build_argv(args.spec, args.output_dir)

    if args.dry_run:
        print("Would run:", " ".join(cmd))
        return 0

    print(f"Generating Pydantic models from {args.spec} -> {args.output_dir} ...")
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
