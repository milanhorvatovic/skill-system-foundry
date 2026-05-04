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
from .router_table import extract_capability_paths


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

    Top-level package metadata files at the skill root other than
    ``SKILL.md`` (e.g., ``README.md``, ``CHANGELOG.md``,
    ``LICENSE.md``) are package documentation, not link-graph
    nodes — the agent harness never loads them as part of the
    skill's context.  Excluding them keeps the directed-reachability
    metric focused on the actual load graph: a README that links
    outward to capabilities but receives no inbound link from any
    entry root would otherwise surface as ``unreachable`` and fail
    the conformance gate, even though it is genuinely external to
    the load surface.
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
            if not name.endswith(EXT_MARKDOWN):
                continue
            # At the skill root, only ``SKILL.md`` is in scope.
            # Other top-level ``.md`` files are package metadata.
            if rel_root == "." and name != FILE_SKILL_MD:
                continue
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
    list[str],
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
        unreadable_rels — skill-root-relative paths of every in-scope
                       markdown file the I/O layer could not read or
                       UTF-8 decode.  These cannot contribute links
                       to the graph, so a silent skip would let an
                       unreadable entry root or reference file pass
                       the conformance gate by accident.  The
                       conformance predicate gates on this list.
    """
    edges: dict[str, list[str]] = {f: [] for f in md_files}
    total_links = 0
    resolved = 0
    broken = 0
    broken_rows: list[tuple[str, str]] = []
    external_per_capability: dict[str, int] = {}
    broken_by_scope: dict[str, int] = {}
    unreadable_rels: list[str] = []

    skill_md_abs = os.path.abspath(os.path.join(skill_root, FILE_SKILL_MD))

    for filepath in md_files:
        content = _read(filepath)
        if content is None:
            # An in-scope markdown file the harness cannot read or
            # decode contributes no links to the graph.  Surfacing
            # it here means the conformance gate fails loudly
            # instead of silently passing on a tree where an entry
            # root or a reachable reference is unreadable.
            unreadable_rels.append(
                os.path.relpath(filepath, skill_root).replace(os.sep, "/")
            )
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
            # Conformance counts every literal link occurrence so
            # ``total_links``, ``resolves_under_standard_semantics``,
            # and ``broken_under_standard_semantics`` reflect link
            # counts rather than unique-target counts.  Two anchored
            # links to the same file (``guide.md#a``, ``guide.md#b``)
            # normalize to the same cleaned path, but each is a
            # separate authored link the report is meant to tally.
            dedupe=False,
        ):
            normalized = strip_fragment(ref)
            if not normalized:
                continue
            # Absolute and drive-qualified paths are spec violations.
            # The body-reference regex now captures both shapes (a
            # leading-``/`` POSIX absolute alternative and a single-
            # letter drive-qualified alternative — see
            # ``configuration.yaml`` ``markdown_link``), so the
            # conformance gate counts them as broken rather than
            # silently dropping them.  ``is_drive_qualified``
            # (lib/references) catches the Windows ``C:foo.md`` form
            # that ``os.path.isabs`` misses on every platform; using
            # ``os.path.splitdrive`` would only catch it on Windows
            # because ``os.path`` is host-dependent.  ``os.path.join``
            # would also treat the path as drive-rooted on Windows,
            # so this branch must run before resolution to avoid
            # distorting the resolved/broken tally.
            if os.path.isabs(normalized) or is_drive_qualified(normalized):
                total_links += 1
                broken += 1
                broken_rows.append((rel, ref))
                broken_by_scope[scope_label] = (
                    broken_by_scope.get(scope_label, 0) + 1
                )
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
        sorted(unreadable_rels),
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

    Reachability and component count use *different* adjacency views
    of the same edge set:

    * **Reachability** is computed from the directed ``src → tgt``
      edges only.  An agent following links from an entry root can
      only traverse links written *outward* from a file; a back-link
      from an otherwise orphan reference to ``SKILL.md`` does not
      make that reference discoverable.  Using undirected adjacency
      here would silently mark such orphans reachable, falsely
      passing the conformance gate.
    * **Components** are weakly connected — that is the documented
      metric, so the helper builds an undirected adjacency for the
      component pass.  The undirected view legitimately merges two
      subgraphs that share a back-edge, since the metric is meant
      to surface clusters of files that have any reference relation
      to each other.

    Targets outside the in-scope set are filtered out of both views.
    """
    in_scope = set(edges.keys())

    # Directed adjacency — outward edges only, used to walk what an
    # agent can reach from an entry root.  Filter to in-scope targets
    # so cross-set links (e.g. to ``scripts/foo.py``) do not appear
    # as reachable nodes.
    directed_adj: dict[str, set[str]] = {n: set() for n in in_scope}
    for src, targets in edges.items():
        for tgt in targets:
            if tgt in in_scope:
                directed_adj[src].add(tgt)

    # Undirected adjacency — built from the same filtered edges, used
    # for the weakly-connected-component pass.
    undirected_adj: dict[str, set[str]] = {n: set() for n in in_scope}
    for src, targets in directed_adj.items():
        for tgt in targets:
            undirected_adj[src].add(tgt)
            undirected_adj[tgt].add(src)

    # Reachability pass: walk each root following directed edges
    # outward.  An in-scope file not reached by any root is
    # unreachable, even if it links *back* to an entry root.
    reached: set[str] = set()
    for root in roots:
        if root not in directed_adj or root in reached:
            continue
        stack = [root]
        while stack:
            node = stack.pop()
            if node in reached:
                continue
            reached.add(node)
            stack.extend(directed_adj[node] - reached)
    unreachable_count = len(in_scope - reached)

    # Component pass: walk weakly-connected components on the
    # undirected adjacency.  Visit every in-scope node so isolated
    # clusters with no entry root still contribute a component.
    visited: set[str] = set()
    component_count = 0
    for node in in_scope:
        if node in visited:
            continue
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            stack.extend(undirected_adj[cur] - visited)
        component_count += 1

    return component_count, unreachable_count


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

    Programmatic callers (the docstring of
    ``reference_conformance_report`` recommends importing this
    function directly) get a dict with ``conforms: false`` and a
    ``missing_skill_md: true`` flag when *skill_root* has no
    ``SKILL.md``.  Without this guard a non-skill directory would
    silently report ``conforms: true`` because there are no files
    to enumerate, no links to break, and no roots to walk — a
    false PASS the CLI catches via its own ``[skill_path]/SKILL.md``
    existence check but library callers do not.
    """
    skill_root = os.path.abspath(skill_root)
    skill_md_abs = os.path.abspath(os.path.join(skill_root, FILE_SKILL_MD))
    if not os.path.isfile(skill_md_abs):
        return {
            "skill_root": skill_root,
            "missing_skill_md": True,
            "total_links": 0,
            "resolves_under_standard_semantics": 0,
            "broken_under_standard_semantics": 0,
            "broken_under_standard_semantics_by_scope": {},
            "broken_links": [],
            "connected_components": 0,
            "files_unreachable_from_root": 0,
            "external_edges_per_capability": {},
            "unrouted_capabilities": [],
            "unreadable_files": [],
            "conforms": False,
        }
    md_files = enumerate_markdown_files(skill_root)
    (
        edges,
        total_links,
        resolved,
        broken,
        broken_rows,
        ext_per_cap,
        broken_by_scope,
        unreadable_rels,
    ) = _build_graph(skill_root, md_files)
    roots = _list_roots(skill_root)
    component_count, unreachable_count = _connected_components(edges, roots)

    # Unrouted-capability check: a capability is *routed* iff its
    # path appears in SKILL.md's router-shaped markdown table.  No
    # link-graph walk is involved — the router table is the
    # structured surface the agent harness reads to dispatch, so
    # router-table membership is the authoritative dispatchability
    # signal.  Other forms of link from SKILL.md (prose paragraph
    # references, capability paths quoted in inline-code, links to
    # the capability's own README/asset) all fail to count as
    # routing because the harness does not consult them.
    #
    # ``extract_capability_paths`` (router_table.py) is the parser
    # for the canonical ``Capability | Trigger | Path`` table.  It
    # returns just the path cells (with the same decoration-stripping
    # recovery the audit uses), so the routed set is exactly the
    # cells that the harness would dispatch through.
    skill_md_abs = os.path.abspath(os.path.join(skill_root, FILE_SKILL_MD))
    router_table_paths: set[str] = set()
    if os.path.isfile(skill_md_abs):
        try:
            with open(skill_md_abs, "r", encoding="utf-8") as fh:
                skill_content = fh.read()
        except (OSError, UnicodeError):
            skill_content = ""
        skill_body = strip_frontmatter_for_scan(skill_content)
        for cell in extract_capability_paths(skill_body):
            router_table_paths.add(
                os.path.normpath(os.path.join(skill_root, cell))
            )
    unrouted_capabilities = sorted(
        name for name, cap_md in _list_capability_entries(skill_root)
        if cap_md not in router_table_paths
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
        # Names of capabilities whose ``capability.md`` path is not
        # listed in SKILL.md's router-shaped markdown table.
        # Distinct from ``files_unreachable_from_root`` (a directed
        # ``src → tgt`` walk from each canonical entry root) and
        # from ``connected_components`` (an undirected shared-
        # reference edge can artificially merge two scopes).  This
        # list is the authoritative router-completeness signal — it
        # does not consult the link graph at all, only the router
        # table.
        "unrouted_capabilities": unrouted_capabilities,
        # Skill-root-relative paths of every in-scope markdown file
        # the I/O layer could not read or UTF-8 decode.  The graph
        # build silently dropped these before, which let an
        # unreadable entry root or reference file pass the
        # conformance gate accidentally — the report would observe
        # ``broken == 0`` and ``unreachable_count == 0`` even though
        # the file's links were never parsed.  Surfacing the list
        # here and gating ``conforms`` on it makes the failure
        # mode loud.
        "unreadable_files": list(unreadable_rels),
        # Conforms requires four independent signals:
        #
        # - ``broken == 0`` — every captured link resolves to a real
        #   in-scope file under file-relative semantics.
        # - ``unreachable_count == 0`` — no in-scope ``.md`` file is
        #   stranded with no path from any entry root.
        # - ``unrouted_capabilities == []`` — every capability is
        #   listed in SKILL.md's router table.  This catches the
        #   incomplete-router case the link-graph metrics miss (a
        #   shared-reference edge or a prose link can artificially
        #   make a capability look connected to SKILL.md even when
        #   the router table never names it).
        # - ``unreadable_files == []`` — every in-scope ``.md`` file
        #   parsed successfully.  An unreadable file contributes no
        #   links to the graph, so without this gate the report
        #   could observe zero broken links on a tree where a
        #   file's body was never inspected.
        #
        # ``connected_components`` stays diagnostic — it is useful
        # for distinguishing orphan clusters from missing-router
        # cases when investigating a failure, but the gate proper
        # reads the four boolean signals above.
        "conforms": (
            broken == 0
            and unreachable_count == 0
            and not unrouted_capabilities
            and not unreadable_rels
        ),
    }
