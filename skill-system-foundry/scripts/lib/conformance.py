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
from .references import is_drive_qualified, is_within_directory, strip_fragment


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

    Excludes ``scripts/`` and ``assets/`` at *any* depth — those
    trees are not part of the prose link graph the report measures.
    A capability with a markdown template under
    ``capabilities/<name>/assets/`` would otherwise be added to the
    conformance graph and could be flagged ``unreachable`` even
    though the report's contract excludes assets and scripts from
    its scope.  ``SKILL.md`` and every file under ``references/``,
    ``capabilities/<name>/``, ``capabilities/<name>/references/``,
    and ``shared/`` is included.
    """
    files: list[str] = []
    for root, dirs, names in os.walk(skill_root):
        rel_root = os.path.relpath(root, skill_root).replace(os.sep, "/")
        # Prune scripts/ and assets/ subtrees at any scope depth —
        # check every component, not just the first, so capability-
        # local trees are excluded too.
        rel_parts = [] if rel_root == "." else rel_root.split("/")
        if any(part in ("scripts", "assets") for part in rel_parts):
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
            # Skip absolute or drive-qualified paths — both are spec
            # violations, not in-scope conformance candidates.
            # ``is_drive_qualified`` (lib/references) catches the
            # Windows ``C:foo.md`` form that ``os.path.isabs`` misses
            # on every platform; using ``os.path.splitdrive`` would
            # only catch it on Windows because ``os.path`` is
            # host-dependent.  Without the cross-platform check
            # ``os.path.join`` would treat the path as drive-rooted
            # and distort the broken/resolved tally on Windows.
            if (
                not normalized
                or os.path.isabs(normalized)
                or is_drive_qualified(normalized)
            ):
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
            # The metric counts capability links whose resolved target
            # lands *in the shared skill root* (outside the
            # capabilities/ tree entirely).  Three kinds of capability
            # links are excluded:
            #
            # - Intra-capability links (``../capability.md`` from a
            #   capability-local reference file) stay inside the
            #   capability scope and need no rewriting at lift time.
            # - Cross-capability links (``capabilities/<other>/...``)
            #   are an architecture concern — after lift, the sibling
            #   capability is gone, so the link cannot be mechanically
            #   inlined.  ``audit_skill_system``'s capability-isolation
            #   rule catches these from a different angle.
            # - Broken targets (file does not exist) are not
            #   lift-rewriteable content; they're already in
            #   ``broken_links`` and would double-count here while
            #   overstating the lift-cost surface area.
            if scope_kind == "capability" and os.path.isfile(ref_abs):
                cap_dir = os.path.join(skill_root, DIR_CAPABILITIES)
                # Must escape the entire capabilities/ tree to count —
                # this excludes both the source capability and any
                # sibling capability, leaving only true shared-root
                # targets (references/, assets/, scripts/, ...).
                if not is_within_directory(ref_abs, cap_dir):
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

    The graph is restricted to the in-scope ``.md`` set: ``edges.keys()``
    holds every enumerated markdown file (the conformance scan
    excludes ``scripts/`` and ``assets/``).  Targets outside that set
    — non-markdown files like ``scripts/foo.py`` and out-of-scope
    markdown like ``scripts/notes.md`` — are valid links but not
    nodes for the component / unreachable analysis.  Without this
    restriction ``files_unreachable_from_root`` would inflate with
    every non-markdown target a markdown file links to, and the
    metric would no longer match its documented ``in-scope .md
    files`` definition.

    Builds an undirected reachability index from the directed edges
    (filtered against ``edges.keys()`` so cross-set targets do not
    pollute it), then walks each root's component.  In-scope files
    not reached by any root walk are unreachable.
    """
    in_scope = set(edges.keys())

    # Undirected adjacency for component detection — only edges
    # between in-scope nodes count.  ``edges`` may contain targets
    # outside the in-scope set (non-md or excluded subtrees); those
    # are skipped here so they neither inflate the unreachable count
    # nor alter component shape.
    adj: dict[str, set[str]] = {n: set() for n in in_scope}
    for src, targets in edges.items():
        for tgt in targets:
            if tgt in in_scope:
                adj[src].add(tgt)
                adj[tgt].add(src)

    visited: set[str] = set()
    component_count = 0
    # First pass: walk each entry root's component.  Roots are the
    # canonical entry points (SKILL.md + every capability.md), so a
    # router skill in which SKILL.md links every capability merges
    # all per-scope subgraphs into a single component here.
    for root in roots:
        if root in visited or root not in adj:
            continue
        stack = [root]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(adj[node] - visited)
        component_count += 1

    # Second pass: every still-unvisited in-scope node belongs to an
    # *orphan* component — a connected subgraph that no entry root
    # reaches.  The metric is documented as the count of
    # weakly-connected components in the in-scope link graph, so the
    # report must surface these too; otherwise an isolated cluster
    # of orphan markdown files would only contribute to
    # ``files_unreachable_from_root`` while ``connected_components``
    # silently underreports the drift.
    unreachable_nodes = in_scope - visited
    for node in unreachable_nodes:
        if node in visited:
            continue
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            stack.extend(adj[cur] - visited)
        component_count += 1

    return component_count, len(unreachable_nodes)


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


def _list_capability_entries(skill_root: str) -> list[tuple[str, str]]:
    """Return ``(name, abs_path)`` for every capability entry."""
    entries: list[tuple[str, str]] = []
    cap_dir = os.path.join(skill_root, DIR_CAPABILITIES)
    if os.path.isdir(cap_dir):
        for name in sorted(os.listdir(cap_dir)):
            cap_md = os.path.join(cap_dir, name, FILE_CAPABILITY_MD)
            if os.path.isfile(cap_md):
                entries.append((name, os.path.abspath(cap_md)))
    return entries


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

    # Unrouted-capability check: every capability.md must be
    # reachable from SKILL.md via the forward (directed) edge chain.
    # The undirected component count alone misses the case where a
    # capability and SKILL.md both link the same shared reference —
    # the shared edge would merge them into one component even
    # though the router table never names the capability.  A directed
    # walk from SKILL.md only follows edges *out* of each node, so a
    # shared-resource sink cannot smuggle the capability into the
    # closure.
    # Routing check uses *direct* edges out of SKILL.md only — not
    # the transitive forward closure.  A capability is "routed"
    # exactly when SKILL.md links it directly through the router
    # table: if capability A is routed and links to capability B,
    # the transitive closure would include B even though SKILL.md
    # never named it, masking the architecture violation that
    # cross-capability references represent.  ``set(edges[skill_md])``
    # is the set of router-table targets only; intersecting with the
    # capability list gives the routed set, and the difference is
    # the unrouted list.
    skill_md_abs = os.path.abspath(os.path.join(skill_root, FILE_SKILL_MD))
    direct_router_targets = (
        set(edges.get(skill_md_abs, ()))
        if os.path.isfile(skill_md_abs)
        else set()
    )
    unrouted_capabilities = sorted(
        name for name, cap_md in _list_capability_entries(skill_root)
        if cap_md not in direct_router_targets
    )

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
        # Names of capabilities not directly reachable from SKILL.md
        # via the router-table forward edge chain.  Distinct from
        # ``files_unreachable_from_root`` (which uses an undirected
        # walk that treats every capability.md as its own root) and
        # from ``connected_components`` (which an undirected shared-
        # reference edge can artificially merge).  This list is the
        # authoritative router-completeness signal.
        "unrouted_capabilities": unrouted_capabilities,
        # Conforms requires three independent signals:
        #
        # - ``broken == 0`` — every captured link resolves to a real
        #   in-scope file under file-relative semantics.
        # - ``unreachable_count == 0`` — no in-scope ``.md`` file is
        #   stranded with no path from any entry root.
        # - ``unrouted_capabilities == []`` — every capability is
        #   directly reachable from SKILL.md.  This catches the
        #   incomplete-router case the undirected component metric
        #   misses (a shared-reference edge can artificially merge
        #   an unrouted capability into the SKILL.md component).
        #
        # ``connected_components`` stays diagnostic — it is useful
        # for distinguishing orphan clusters from missing-router
        # cases when investigating a failure, but the gate proper
        # reads the three boolean signals above.
        "conforms": (
            broken == 0
            and unreachable_count == 0
            and not unrouted_capabilities
        ),
    }
