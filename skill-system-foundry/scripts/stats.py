#!/usr/bin/env python3
"""Report a skill's token-budget proxies (discovery + load bytes).

Usage:
    python scripts/stats.py <skill-path>
    python scripts/stats.py skill-system-foundry/
    python scripts/stats.py skill-system-foundry/ --json
    python scripts/stats.py skill-system-foundry/ --verbose

Two byte-based proxies are reported:

* ``discovery_bytes`` — the SKILL.md YAML frontmatter block (between
  and including the ``---`` fences).  This is what the harness reads
  at startup to decide whether to surface the skill.

* ``load_bytes`` — SKILL.md plus every transitively reachable
  ``capabilities/**/capability.md`` and ``references/**/*`` file.
  ``scripts/`` and ``assets/`` are excluded — they are not loaded into
  the model's context during skill use.

Bytes are not tokens.  Counts are not comparable across models or
tokenizers — they are a deterministic on-disk signal for tracking the
relative cost of authoring decisions over time.  Counts are taken
from raw on-disk UTF-8 bytes (CRLF preserved); a Windows checkout of
the same content reports a higher count than a POSIX checkout.
"""

import argparse
import os
import sys

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.constants import SEPARATOR_WIDTH
from lib.reporting import (
    categorize_errors,
    categorize_errors_for_json,
    print_error_line,
    print_summary,
    to_json_output,
)
from lib.stats import compute_stats


def _format_bytes(value: int) -> str:
    """Render *value* with thousands separators for the human table."""
    return f"{value:,} B"


def _print_human(result: dict, verbose: bool) -> None:
    """Print the default human-readable report.

    Two sections: a header (skill name + totals) and a per-file table
    sorted alphabetically.  Findings — when present — print after the
    table in the same format the other entry points use.  ``verbose``
    expands the ``reachable_from`` column to show every parent rather
    than just the first one.
    """
    print(f"Skill: {result['skill']}")
    print(f"Metric: {result['metric']}")
    print(f"Discovery: {_format_bytes(result['discovery_bytes'])}")
    print(
        f"Load:      {_format_bytes(result['load_bytes'])} "
        f"({len(result['files'])} files)"
    )
    print("-" * SEPARATOR_WIDTH)

    if result["files"]:
        # Right-align byte counts; left-align paths.  The path column
        # widens to fit the longest entry, capped at 60 chars to keep
        # the line readable on narrow terminals.
        max_path_width = max(len(entry["path"]) for entry in result["files"])
        path_width = min(max_path_width, 60)
        for entry in result["files"]:
            parents = entry["reachable_from"]
            if not parents:
                arrow = ""
            elif verbose or len(parents) == 1:
                arrow = "  ← " + ", ".join(parents)
            else:
                arrow = (
                    f"  ← {parents[0]} (+{len(parents) - 1} more)"
                )
            print(
                f"{entry['path']:<{path_width}}  "
                f"{_format_bytes(entry['bytes']):>10}{arrow}"
            )

    if result["errors"]:
        print("-" * SEPARATOR_WIDTH)
        for error in result["errors"]:
            print_error_line(error)
        fails, warns, infos = categorize_errors(result["errors"])
        print("-" * SEPARATOR_WIDTH)
        print_summary(fails, warns, infos)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report token-budget proxies (discovery + load bytes) for "
            "a single skill.  Bytes are not tokens — they are a "
            "deterministic on-disk signal, not a tokenizer-accurate "
            "estimate.  CRLF is preserved in the count, so Windows "
            "checkouts report higher than POSIX checkouts of the "
            "same content."
        ),
        epilog=(
            "Examples:\n"
            "  python scripts/stats.py skill-system-foundry/\n"
            "  python scripts/stats.py skill-system-foundry/ --json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "skill_path",
        help="Path to the skill directory (must contain SKILL.md).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Expand the reachable_from column to list every parent "
            "rather than just the first."
        ),
    )
    return parser


def main() -> None:
    _json_mode = "--json" in sys.argv

    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(1)

    parser = _build_parser()

    def _json_aware_error(message: str) -> None:
        if _json_mode:
            print(to_json_output({
                "tool": "stats",
                "success": False,
                "error": message,
            }))
            sys.exit(1)
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)

    parser.error = _json_aware_error  # type: ignore[assignment]

    args = parser.parse_args()
    skill_path: str = args.skill_path
    json_output: bool = args.json_output
    verbose: bool = args.verbose

    if not os.path.isdir(skill_path):
        if json_output:
            print(to_json_output({
                "tool": "stats",
                "path": os.path.abspath(skill_path),
                "success": False,
                "error": f"'{skill_path}' is not a directory",
            }))
        else:
            print(f"Error: '{skill_path}' is not a directory")
        sys.exit(1)

    result = compute_stats(skill_path)
    fails, warns, infos = categorize_errors(result["errors"])

    if json_output:
        payload = {
            "tool": "stats",
            "path": os.path.abspath(skill_path),
            "success": len(fails) == 0,
            "skill": result["skill"],
            "metric": result["metric"],
            "discovery_bytes": result["discovery_bytes"],
            "load_bytes": result["load_bytes"],
            "files": result["files"],
            "summary": {
                "failures": len(fails),
                "warnings": len(warns),
                "info": len(infos),
                "files": len(result["files"]),
            },
            "errors": categorize_errors_for_json(result["errors"]),
        }
        print(to_json_output(payload))
        sys.exit(1 if fails else 0)

    # Early-exit human path: a FAIL means SKILL.md is missing.
    if fails and not result["files"]:
        for error in result["errors"]:
            print_error_line(error)
        sys.exit(1)

    _print_human(result, verbose)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
