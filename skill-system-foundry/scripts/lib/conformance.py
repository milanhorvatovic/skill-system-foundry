"""Per-skill reference conformance under standard markdown semantics.

Computes the metrics surfaced by ``reference_conformance_report.py``
— total links, file-relative resolution counts, broken links grouped
by source scope, weakly-connected components, files unreachable from
the canonical entry-point roots, and per-capability external-edge
counts.

The implementation lives here (not in the entry point) so the
validator, the audit, and any future tool can share the same metric
shape and per-link classification without re-implementing the graph
walk.  See ``references/path-resolution.md`` for the rule the
metrics quantify.
"""

import os

from .constants import (
    DIR_CAPABILITIES,
    EXT_MARKDOWN,
    FILE_CAPABILITY_MD,
    FILE_SKILL_MD,
)
from .frontmatter import strip_frontmatter_for_scan
from .reachability import extract_body_references
from .references import is_within_directory, strip_fragment


# ===================================================================
# Scope helpers
# ===================================================================


def _file_scope(rel_path: str) -> tuple[str, str]:
    """Return ``(scope_kind, scope_name)`` for a skill-root-relative path."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == DIR_CAPABILITIES:
        return ("capability", parts[1])
    return ("skill", "")


def _scope_label(scope_kind: str, scope_name: str) -> str:
    """Return the per-scope label used in the conformance report's
    ``broken_under_standard_semantics_by_scope`` map."""
    if scope_kind == "capability":
        return f"capability:{scope_name}"
    return scope_kind


def _read(filepath: str) -> str | None:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeError):
        return None


# ===================================================================
# File enumeration
# ===================================================================


def enumerate_markdown_files(skill_root: str) -> list[str]:
    """Return absolute paths of every in-scope ``.md`` file under *skill_root*.

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
# Graph build
# ===================================================================


def _build_graph(
    skill_root: str, md_files: list[str],
) -> tuple[
    dict[str, list[str]],
    int,
    int,
    int,
    list[tuple[str, str]],
    dict[str, int],
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
                       refs whose resolved path escapes the capability
                       root and lands in the shared skill root (the
                       canonical external-reference form per
                       references/path-resolution.md).
        broken_by_scope — ``scope_label → count`` of broken links,
                       grouped by the *source* scope (``"skill"`` or
                       ``"capability:<name>"``).  Missing scopes have
                       no entry.
    """
    edges: dict[str, list[str]] = {f: [] for f in md_files}
    total_links = 0
    resolved = 0
    broken = 0
    broken_rows: list[tuple[str, str]] = []
    external_per_capability: dict[str, int] = {}
    broken_by_scope: dict[str, int] = {}

    skill_md_abs = os.path.abspath(os.path.join(skill_root, FILE_SKILL_MD))

    for filepath in md_files:
        content = _read(filepath)
        if content is None:
            continue
        body = strip_frontmatter_for_scan(content)
        rel = os.path.relpath(filepath, skill_root).replace(os.sep, "/")
        scope_kind, scope_name = _file_scope(rel)
        scope_label = _scope_label(scope_kind, scope_name)
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
                broken_by_scope[scope_label] = (
                    broken_by_scope.get(scope_label, 0) + 1
                )

            # External edges — the lift tool's rewrite candidates.
            # An external edge is one that *escapes the capability root*,
            # not just any ``../``-prefixed link.  A capability-local
            # reference under ``capabilities/<name>/references/foo.md``
            # legitimately uses ``../capability.md`` to reach its own
            # entry; that edge stays within the capability scope and
            # does not need rewriting at lift time.  Filter on the
            # resolved path's containment in the capability directory
            # instead of on the literal prefix.
            if scope_kind == "capability":
                cap_root = os.path.join(
                    skill_root, DIR_CAPABILITIES, scope_name,
                )
                if not is_within_directory(ref_abs, cap_root):
                    external_per_capability[scope_name] = (
                        external_per_capability.get(scope_name, 0) + 1
                    )

    return (
        edges,
        total_links,
        resolved,
        broken,
        broken_rows,
        external_per_capability,
        broken_by_scope,
    )


# ===================================================================
# Component analysis
# ===================================================================


def _connected_components(
    edges: dict[str, list[str]], roots: list[str],
) -> tuple[int, int]:
    """Return ``(component_count, files_unreachable_from_root)``.

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
    human-readable formatter and the ``--json`` output of
    ``reference_conformance_report.py``.
    """
    skill_root = os.path.abspath(skill_root)
    md_files = enumerate_markdown_files(skill_root)
    (
        edges,
        total_links,
        resolved,
        broken,
        broken_rows,
        ext_per_cap,
        broken_by_scope,
    ) = _build_graph(skill_root, md_files)
    roots = _list_roots(skill_root)
    component_count, unreachable_count = _connected_components(edges, roots)

    return {
        "skill_root": skill_root,
        "total_links": total_links,
        "resolves_under_standard_semantics": resolved,
        "broken_under_standard_semantics": broken,
        "broken_under_standard_semantics_by_scope": dict(
            sorted(broken_by_scope.items())
        ),
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
