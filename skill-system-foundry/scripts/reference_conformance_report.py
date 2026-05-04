#!/usr/bin/env python3
"""Report a skill's cross-file reference conformance under standard markdown semantics.

Usage:
    python scripts/reference_conformance_report.py <skill-path>
    python scripts/reference_conformance_report.py skill-system-foundry/ --json
    python scripts/reference_conformance_report.py skill-system-foundry/ --verbose

Computes per-skill metrics that quantify how well the skill's link
graph matches what a standard markdown reader sees.  See
``references/path-resolution.md`` for the rule the report is checking.

The scan covers every ``.md`` file under the skill *except* the
``scripts/`` and ``assets/`` subtrees — those are not part of the
prose link graph the report measures.  ``SKILL.md``, files under
``references/``, every ``capabilities/<name>/`` tree, and any
``shared/`` tree are all included.

Metrics:

* ``total_links`` — total internal cross-file links across the
  in-scope ``.md`` files (markdown links and backtick path mentions).
* ``resolves_under_standard_semantics`` — count of links that resolve
  to an existing file under file-relative resolution.
* ``broken_under_standard_semantics`` — count of links that do not.
* ``connected_components`` — count of weakly-connected components in
  the link graph reachable from ``SKILL.md`` and every ``capability.md``.
  A router skill in which ``SKILL.md`` links every capability typically
  reports ``1`` because the router edges merge all per-scope sub-graphs
  into a single component.  A larger value signals capability scopes
  that no router edge reaches — useful for detecting accidentally
  unrouted capabilities.
* ``files_unreachable_from_root`` — count of in-scope ``.md`` files
  under the skill that no root reaches.
* ``external_edges_per_capability`` — for each capability, the number
  of edges that escape the capability root and land in the shared
  skill root.  These are the edges a future capability-lift tool
  would mechanically rewrite.  ``../``-prefixed links that resolve
  back into the same capability (e.g. ``../capability.md`` from
  ``capabilities/<name>/references/foo.md``) are intra-scope and
  not counted.

A skill conforms when ``broken_under_standard_semantics == 0`` and
``files_unreachable_from_root == 0``.  Other fields are diagnostic.

This entry point is a thin wrapper over ``lib.conformance.compute_report``
— argument parsing, output formatting, and exit status only.  Any
caller that needs the metrics programmatically should import
``lib.conformance.compute_report`` directly.
"""

import argparse
import os
import sys

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.conformance import compute_report  # noqa: F401 — re-exported
from lib.constants import FILE_SKILL_MD, SEPARATOR_WIDTH
from lib.reporting import to_json_output


# ===================================================================
# Output
# ===================================================================


def print_human(report: dict, verbose: bool) -> None:
    """Print the report in human-readable form."""
    print("=" * SEPARATOR_WIDTH)
    print(f"Reference Conformance Report: {report['skill_root']}")
    print("=" * SEPARATOR_WIDTH)
    print(f"  Total internal links:           {report['total_links']}")
    print(
        f"  Resolves (standard markdown):    "
        f"{report['resolves_under_standard_semantics']}"
    )
    print(
        f"  Broken (standard markdown):      "
        f"{report['broken_under_standard_semantics']}"
    )
    by_scope = report.get("broken_under_standard_semantics_by_scope", {})
    if by_scope:
        print("    by source scope:")
        for scope, count in by_scope.items():
            print(f"      {scope:30s} {count:>4d}")
    print(f"  Connected components:            {report['connected_components']}")
    print(
        f"  Files unreachable from root:     "
        f"{report['files_unreachable_from_root']}"
    )
    if report["external_edges_per_capability"]:
        print("  External edges per capability:")
        for cap, count in report["external_edges_per_capability"].items():
            print(f"    {cap:30s} {count:>4d}")
    print("-" * SEPARATOR_WIDTH)
    if report["conforms"]:
        print("Conformance: PASS")
    else:
        print("Conformance: FAIL")
        if verbose and report["broken_links"]:
            print()
            print("Broken links:")
            for entry in report["broken_links"]:
                print(f"  {entry['source']} → {entry['target']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report a skill's cross-file reference conformance under "
            "standard markdown semantics (file-relative resolution)."
        ),
    )
    parser.add_argument(
        "skill_path",
        help="Path to the skill directory (containing SKILL.md).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the report as JSON for machine consumption.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="In human mode, list every broken-link source/target pair.",
    )
    args = parser.parse_args()

    skill_path = os.path.abspath(args.skill_path)
    if not os.path.isdir(skill_path):
        msg = f"error: '{args.skill_path}' is not a directory"
        if args.json:
            print(to_json_output({"tool": "reference_conformance_report", "error": msg}))
        else:
            print(msg, file=sys.stderr)
        return 2

    # Refuse to run on a directory that is not a skill root.  Without
    # this guard the walker scans whatever markdown the directory
    # happens to contain (top-level docs, .github/, examples/) and
    # reports broken links for paths that are simply outside any
    # skill — noise that masks real conformance issues.
    if not os.path.isfile(os.path.join(skill_path, FILE_SKILL_MD)):
        msg = (
            f"error: '{args.skill_path}' does not contain {FILE_SKILL_MD} "
            "— pass a skill directory (the directory containing SKILL.md)"
        )
        if args.json:
            print(to_json_output({
                "tool": "reference_conformance_report", "error": msg,
            }))
        else:
            print(msg, file=sys.stderr)
        return 2

    report = compute_report(skill_path)

    if args.json:
        payload = {"tool": "reference_conformance_report", **report}
        print(to_json_output(payload))
    else:
        print_human(report, args.verbose)

    # Exit non-zero on non-conformance so CI / scripts can gate on it.
    return 0 if report["conforms"] else 1


if __name__ == "__main__":
    sys.exit(main())
