#!/usr/bin/env python3
"""Report a skill's cross-file reference conformance under standard markdown semantics.

Usage:
    python scripts/reference_conformance_report.py <skill-path>
    python scripts/reference_conformance_report.py skill-system-foundry/ --json
    python scripts/reference_conformance_report.py skill-system-foundry/ --verbose

Computes per-skill metrics that quantify how well the skill's link
graph matches what a standard markdown reader sees.  See
``references/path-resolution.md`` for the rule the report is checking.

Metrics:

* ``total_links`` — total internal cross-file links across all ``.md``
  files in the skill (markdown links and backtick path mentions).
* ``resolves_under_standard_semantics`` — count of links that resolve
  to an existing file under file-relative resolution.
* ``broken_under_standard_semantics`` — count of links that do not.
* ``connected_components`` — count of connected components in the
  link graph reachable from ``SKILL.md`` and every ``capability.md``.
  A healthy skill has one component per scope (skill root, plus one
  per capability).
* ``files_unreachable_from_root`` — count of ``.md`` files under the
  skill that no root reaches.
* ``external_edges_per_capability`` — for each capability, the number
  of ``../``-prefixed edges into the shared skill root.  These are
  the edges a future capability-lift tool would mechanically rewrite.

A skill conforms when ``broken_under_standard_semantics == 0`` and
``files_unreachable_from_root == 0``.  Other fields are diagnostic.

The script is stdlib-only and reuses the body-reference patterns from
``configuration.yaml`` and the file-relative resolution semantics
already implemented in ``lib/reachability.py``.
"""

import argparse
import os
import sys

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.constants import (
    DIR_CAPABILITIES,
    EXT_MARKDOWN,
    FILE_CAPABILITY_MD,
    FILE_SKILL_MD,
    SEPARATOR_WIDTH,
)
from lib.frontmatter import strip_frontmatter_for_scan
from lib.reachability import extract_body_references
from lib.references import is_within_directory, strip_fragment
from lib.reporting import to_json_output


# ===================================================================
# File enumeration
# ===================================================================


def _enumerate_markdown_files(skill_root: str) -> list[str]:
    """Return absolute paths of every .md file under *skill_root*.

    Excludes ``scripts/`` and ``assets/`` — those trees are not part
    of the prose link graph the report measures.  ``SKILL.md`` and
    every file under ``references/``, ``capabilities/``, and
    ``shared/`` is included.
    """
    files: list[str] = []
    for root, dirs, names in os.walk(skill_root):
        rel_root = os.path.relpath(root, skill_root).replace(os.sep, "/")
        # Prune scripts/ and assets/ subtrees from the walk.
        top = rel_root.split("/", 1)[0] if rel_root != "." else ""
        if top in ("scripts", "assets"):
            dirs[:] = []
            continue
        for name in names:
            if name.endswith(EXT_MARKDOWN):
                files.append(os.path.abspath(os.path.join(root, name)))
    return sorted(files)


# ===================================================================
# Per-skill graph build
# ===================================================================


def _file_scope(rel_path: str) -> tuple[str, str]:
    """Return ``(scope_kind, scope_name)`` for a skill-root-relative path."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == DIR_CAPABILITIES:
        return ("capability", parts[1])
    return ("skill", "")


def _read(filepath: str) -> str | None:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeError):
        return None


def _build_graph(
    skill_root: str, md_files: list[str],
) -> tuple[
    dict[str, list[str]],
    int,
    int,
    int,
    list[tuple[str, str]],
    dict[str, int],
]:
    """Build the link graph and tally per-link conformance.

    Returns:
        edges        — adjacency map: source_abs → list of target_abs.
        total_links  — number of (source, ref) pairs extracted.
        resolved     — number of links that land on existing files
                       under file-relative resolution.
        broken       — total_links - resolved (out-of-skill links
                       are excluded from both counts).
        broken_rows  — list of (source_rel, ref_text) for the broken
                       set, used for the verbose report and the JSON
                       payload.
        external_per_capability — ``capability_name → count`` for
                       refs whose path starts with ``..`` and resolves
                       to a file under the skill root (the canonical
                       external-reference form per
                       references/path-resolution.md).
    """
    edges: dict[str, list[str]] = {f: [] for f in md_files}
    total_links = 0
    resolved = 0
    broken = 0
    broken_rows: list[tuple[str, str]] = []
    external_per_capability: dict[str, int] = {}

    skill_md_abs = os.path.abspath(os.path.join(skill_root, FILE_SKILL_MD))

    for filepath in md_files:
        content = _read(filepath)
        if content is None:
            continue
        body = strip_frontmatter_for_scan(content)
        rel = os.path.relpath(filepath, skill_root).replace(os.sep, "/")
        scope_kind, scope_name = _file_scope(rel)
        is_entry = filepath == skill_md_abs
        source_dir = os.path.dirname(filepath)

        for ref in extract_body_references(
            body,
            include_router_table=is_entry,
            filter_capability_entries=False,
        ):
            normalized = strip_fragment(ref)
            if not normalized or os.path.isabs(normalized):
                continue
            ref_abs = os.path.normpath(os.path.join(source_dir, normalized))

            if not is_within_directory(ref_abs, skill_root):
                continue  # Out-of-skill — excluded from in-scope tally.

            total_links += 1
            if os.path.isfile(ref_abs):
                resolved += 1
                edges[filepath].append(os.path.abspath(ref_abs))
            else:
                broken += 1
                broken_rows.append((rel, ref))

            # Track external edges (the lift tool's rewrite candidates).
            ref_norm = normalized.replace("\\", "/")
            if scope_kind == "capability" and ref_norm.startswith("../"):
                external_per_capability[scope_name] = (
                    external_per_capability.get(scope_name, 0) + 1
                )

    return edges, total_links, resolved, broken, broken_rows, external_per_capability


# ===================================================================
# Component analysis
# ===================================================================


def _connected_components(
    edges: dict[str, list[str]], roots: list[str],
) -> tuple[int, int]:
    """Return (component_count, files_unreachable_from_root).

    Builds an undirected reachability index from the directed edges,
    then walks each root's component.  Files not reached by any root
    walk are unreachable.
    """
    nodes = set(edges.keys())
    for src, targets in edges.items():
        for tgt in targets:
            nodes.add(tgt)

    # Undirected adjacency for component detection.
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for src, targets in edges.items():
        for tgt in targets:
            if tgt in adj:  # only edges between known .md files
                adj[src].add(tgt)
                adj[tgt].add(src)

    visited: set[str] = set()
    component_count = 0
    for root in roots:
        if root in visited or root not in adj:
            continue
        # BFS the component from this root.
        stack = [root]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(adj[node] - visited)
        component_count += 1

    unreachable = nodes - visited
    return component_count, len(unreachable)


def _list_roots(skill_root: str) -> list[str]:
    """Return absolute paths of canonical entry points in *skill_root*."""
    roots: list[str] = []
    skill_md = os.path.join(skill_root, FILE_SKILL_MD)
    if os.path.isfile(skill_md):
        roots.append(os.path.abspath(skill_md))
    cap_dir = os.path.join(skill_root, DIR_CAPABILITIES)
    if os.path.isdir(cap_dir):
        for name in sorted(os.listdir(cap_dir)):
            cap_md = os.path.join(cap_dir, name, FILE_CAPABILITY_MD)
            if os.path.isfile(cap_md):
                roots.append(os.path.abspath(cap_md))
    return roots


# ===================================================================
# Public entry point
# ===================================================================


def compute_report(skill_root: str) -> dict:
    """Compute the conformance report for *skill_root*.

    The returned dict is the canonical shape consumed by both the
    human-readable formatter and the ``--json`` output.
    """
    skill_root = os.path.abspath(skill_root)
    md_files = _enumerate_markdown_files(skill_root)
    edges, total_links, resolved, broken, broken_rows, ext_per_cap = (
        _build_graph(skill_root, md_files)
    )
    roots = _list_roots(skill_root)
    component_count, unreachable_count = _connected_components(edges, roots)

    return {
        "skill_root": skill_root,
        "total_links": total_links,
        "resolves_under_standard_semantics": resolved,
        "broken_under_standard_semantics": broken,
        "broken_links": [
            {"source": src, "target": tgt} for src, tgt in broken_rows
        ],
        "connected_components": component_count,
        "files_unreachable_from_root": unreachable_count,
        "external_edges_per_capability": dict(
            sorted(ext_per_cap.items())
        ),
        "conforms": broken == 0 and unreachable_count == 0,
    }


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
