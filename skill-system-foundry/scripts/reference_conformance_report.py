#!/usr/bin/env python3
"""Report a skill's cross-file reference conformance under standard markdown semantics.

Usage:
    python scripts/reference_conformance_report.py <skill-path>
    python scripts/reference_conformance_report.py skill-system-foundry/ --json
    python scripts/reference_conformance_report.py skill-system-foundry/ --verbose

Computes per-skill metrics that quantify how well the skill's link
graph matches what a standard markdown reader sees.  See
``references/path-resolution.md`` for the rule the report is checking.

The scan covers ``SKILL.md`` plus every ``.md`` file under the
skill's ``references/``, ``capabilities/<name>/``, and ``shared/``
subtrees — that is the load graph the agent harness walks during
skill use.  ``scripts/`` and ``assets/`` subtrees are excluded at
any depth (capability-local trees too) because they are not part
of the prose link graph the report measures.  Top-level ``.md``
files at the skill root other than ``SKILL.md`` (``README.md``,
``CHANGELOG.md``, ``LICENSE.md``) are package metadata, not load-
graph nodes — the agent harness never loads them — so they are
excluded as well.  Without that exclusion, a README that links
outward to capabilities but receives no inbound link from any
entry root would surface as ``unreachable`` under the directed
reachability rule and fail the conformance gate, even though it
is genuinely external to the load surface.

Metrics:

* ``total_links`` — total internal cross-file links across the
  in-scope ``.md`` files (markdown links and backtick path mentions).
* ``resolves_under_standard_semantics`` — count of links that resolve
  to an existing file under file-relative resolution.
* ``broken_under_standard_semantics`` — count of links that do not.
* ``connected_components`` — count of weakly-connected components in
  the in-scope link graph.  Counts every cluster of mutually-linked
  ``.md`` files, including orphan subgraphs that no entry root
  reaches.  A router skill in which ``SKILL.md`` links every
  capability typically reports ``1`` because the router edges merge
  all per-scope sub-graphs into a single component.  A larger value
  signals either capability scopes that no router edge reaches *or*
  orphan clusters of files that no root reaches — both are useful
  drift signals.  ``files_unreachable_from_root`` is the companion
  metric that distinguishes the two cases (orphan clusters
  contribute to both, unrouted-but-router-linked subgraphs only
  inflate this count).
* ``files_unreachable_from_root`` — count of in-scope ``.md`` files
  under the skill that no entry root reaches.
* ``external_edges_per_capability`` — for each capability, the number
  of edges that escape the capability root and land in the shared
  skill root.  These are the edges a future capability-lift tool
  would mechanically rewrite.  ``../``-prefixed links that resolve
  back into the same capability (e.g. ``../capability.md`` from
  ``capabilities/<name>/references/foo.md``) are intra-scope and
  not counted.

* ``unrouted_capabilities`` — names of capabilities whose
  ``capability.md`` path is not listed in ``SKILL.md``'s
  router-shaped markdown table.  No link-graph walk is involved:
  the router table is the structured surface the agent harness
  reads to dispatch, so router-table membership is the
  authoritative dispatchability signal.  A capability that
  ``SKILL.md`` mentions only in prose (or in inline-code, or as a
  link to an asset) is *unrouted* — the harness has no way to
  know it should reach that capability.

A skill conforms when ``broken_under_standard_semantics == 0``,
``files_unreachable_from_root == 0``, ``unrouted_capabilities == []``,
and ``unreadable_files == []``.  ``connected_components`` stays
diagnostic — useful for distinguishing orphan clusters from
incomplete-router cases when investigating a failure, but the gate
proper reads the four signals above.

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
    if report.get("unrouted_capabilities"):
        print("  Unrouted capabilities:")
        for cap in report["unrouted_capabilities"]:
            print(f"    {cap}")
    print("-" * SEPARATOR_WIDTH)
    if report["conforms"]:
        print("Conformance: PASS")
    else:
        print("Conformance: FAIL")
        # Always surface unrouted capabilities on failure — they are
        # the most common drift case after the gate change, and the
        # gate fails on this signal even when broken/unreachable
        # counts are zero.  CI runs the human form (``--verbose``),
        # so a maintainer needs the actionable capability name in
        # the failure output without having to re-run with
        # ``--json``.
        if report.get("unrouted_capabilities"):
            print()
            print(
                "Unrouted capabilities "
                "(not listed in SKILL.md router table):"
            )
            for cap in report["unrouted_capabilities"]:
                print(f"  {cap}")
        # Surface unreadable files unconditionally on failure for
        # the same reason as unrouted capabilities — the gate fails
        # on this signal independently of broken/unreachable counts,
        # and a maintainer needs the actionable file path in the
        # human output without re-running with ``--json``.
        if report.get("unreadable_files"):
            print()
            print(
                "Unreadable markdown files "
                "(I/O or UTF-8 decode error — links not parsed):"
            )
            for path in report["unreadable_files"]:
                print(f"  {path}")
        if verbose and report["broken_links"]:
            print()
            print("Broken links:")
            for entry in report["broken_links"]:
                print(f"  {entry['source']} → {entry['target']}")


def main() -> int:
    # Fast-path: no arguments at all → print module docstring as the
    # usage hint and exit non-zero.  Matches the convention used by
    # validate_skill.py, bundle.py, scaffold.py — keeps the CLI UX
    # uniform across foundry entry points and ensures the module
    # docstring serves as the actual usage message a user sees when
    # they invoke the script with no arguments.
    if len(sys.argv) == 1:
        print(__doc__)
        return 1

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
