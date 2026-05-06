#!/usr/bin/env python3
"""Report a skill's token-budget proxies (discovery + load bytes).

Usage:
    python scripts/stats.py <skill-path>
    python scripts/stats.py skill-system-foundry/
    python scripts/stats.py skill-system-foundry/ --json
    python scripts/stats.py skill-system-foundry/ --verbose

Two byte-based proxies are reported:

* ``discovery_bytes`` — the sum of every YAML frontmatter block the
  harness reads at discovery time: ``SKILL.md`` plus each
  ``capabilities/<name>/capability.md`` (when present).  Every
  discovery-relevant entry in ``files[]`` — ``SKILL.md`` and each
  visited capability entry — carries a per-row ``discovery_bytes``
  (``0`` when the file is silent on frontmatter) so consumers can
  reconstruct the breakdown without re-reading any files;
  non-discovery rows (capability-local references and shared
  references) omit the key entirely.  The human-readable report
  shows the breakdown directly when at least one capability
  declares frontmatter.

* ``load_bytes`` — SKILL.md plus every transitively reachable file
  under ``capabilities/`` or ``references/``, excluding ``scripts/``
  and ``assets/``.  That covers capability entry points
  (``capabilities/<name>/capability.md``), capability-local resources
  (``capabilities/<name>/references/<doc>.md``), and shared
  references (``references/<doc>.md``).  Excluded categories are
  not loaded into the model's context during skill use.

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
    to_posix,
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

    The discovery line collapses into a single ``Discovery: <N> B``
    when ``SKILL.md`` is the only contributor; when at least one
    capability declares frontmatter, the line becomes a
    ``Discovery: <N> B total`` header followed by an indented
    breakdown listing each contributor in alphabetical order.  This
    keeps legacy output unchanged for skills that have not adopted
    capability frontmatter.

    The breakdown always includes the ``SKILL.md`` row even when
    its own ``discovery_bytes`` is ``0`` (i.e. SKILL.md has no
    parseable frontmatter): the row is informative — it pairs with
    the standalone "no parseable frontmatter" WARN in
    ``result["errors"]`` to make the asymmetry explicit, and it
    keeps the breakdown's contributor set in sync with the rows
    that carry the ``discovery_bytes`` JSON key.
    """
    print(f"Skill: {result['skill']}")
    print(f"Metric: {result['metric']}")
    discovery_rows = [
        entry for entry in result["files"]
        if "discovery_bytes" in entry
    ]
    capability_contributors = [
        entry for entry in discovery_rows
        if entry["path"] != "SKILL.md" and entry["discovery_bytes"] > 0
    ]
    if capability_contributors:
        print(
            f"Discovery: {_format_bytes(result['discovery_bytes'])} total"
        )
        path_width = max(len(entry["path"]) for entry in discovery_rows)
        for entry in discovery_rows:
            print(
                f"  {entry['path']:<{path_width}}  "
                f"{_format_bytes(entry['discovery_bytes']):>10}"
            )
    else:
        print(f"Discovery: {_format_bytes(result['discovery_bytes'])}")
    print(
        f"Load:      {_format_bytes(result['load_bytes'])} "
        f"({len(result['files'])} files)"
    )
    # Surface the LF-normalized aggregates whenever they diverge from
    # the raw counts so a CRLF-checkout reader can see both numbers
    # without re-running the tool with --json.
    if (
        result.get("load_bytes_lf", result["load_bytes"])
        != result["load_bytes"]
        or result.get("discovery_bytes_lf", result["discovery_bytes"])
        != result["discovery_bytes"]
    ):
        print(
            f"Normalized (LF-only):  "
            f"discovery={_format_bytes(result['discovery_bytes_lf'])}  "
            f"load={_format_bytes(result['load_bytes_lf'])}"
        )
    print("-" * SEPARATOR_WIDTH)

    if result["files"]:
        # Right-align byte counts; left-align paths.  ``path_width`` is
        # the *minimum* column width: short paths get padded out to it,
        # but a path longer than 60 chars prints at its natural length
        # and pushes the byte-count column to the right on that line
        # only.  The 60-char ceiling on the padding bound keeps the
        # table readable on narrow terminals when a single very long
        # path would otherwise force every short row to be padded out
        # to match.
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
                "path": to_posix(os.path.abspath(skill_path)),
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
            "path": to_posix(os.path.abspath(skill_path)),
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
        # ``*_lf`` companions are emitted only when ``compute_stats``
        # produced them (i.e. line-ending detection is enabled in
        # configuration.yaml).  Consumers branch on key presence
        # rather than reading an equal-to-raw fallback that would
        # silently misrepresent CRLF checkouts.
        if "discovery_bytes_lf" in result:
            payload["discovery_bytes_lf"] = result["discovery_bytes_lf"]
        if "load_bytes_lf" in result:
            payload["load_bytes_lf"] = result["load_bytes_lf"]
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
