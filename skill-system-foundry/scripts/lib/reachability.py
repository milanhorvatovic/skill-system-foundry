"""Per-skill reachability of the markdown reference graph.

Owns two primitives shared by ``stats.py`` (byte budget) and
``orphans.py`` (orphan-reference rule):

* :func:`extract_body_references` — clean reference paths extracted from
  a markdown body using the configured ``reference_patterns``.  Strips
  fenced code blocks, anchor fragments, and template placeholders.

* :func:`walk_reachable` — multi-root walk that returns the absolute
  paths of every file reachable from ``SKILL.md`` and every
  ``capabilities/*/capability.md`` via the body reference patterns.
  Used by the orphan-reference audit rule to determine which files
  under ``references/`` are dead weight.

Independent from ``lib/references.py`` (which walks the bundle/cross-
skill graph).  Independent from the ``--allow-nested-references`` flag
(that flag suppresses depth warnings during validation; reachability
is concerned only with whether a file is linked at all, never with
how deep the reference chain runs).
"""

import os
import re

from .constants import (
    DIR_CAPABILITIES,
    FILE_CAPABILITY_MD,
    FILE_SKILL_MD,
    LEVEL_INFO,
    LEVEL_WARN,
    PATH_RESOLUTION_RULE_NAME,
    RE_BACKTICK_REF,
    RE_MARKDOWN_LINK_REF,
)
from .frontmatter import strip_frontmatter_for_scan
from .references import is_drive_qualified, is_within_directory, strip_fragment
from .router_table import extract_capability_paths


# Pattern that strips fenced code blocks before reference scanning, so
# example links inside ``` are not treated as real references.
_RE_FENCED_BLOCK = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


# ===================================================================
# Reference extraction
# ===================================================================


def _is_capability_entry_path(ref_path: str) -> bool:
    """Return True when *ref_path* is a capability entry point.

    A capability entry point matches the canonical shape
    ``capabilities/<name>/capability.md`` exactly — three segments,
    leading directory ``capabilities``, trailing file
    ``capability.md``.  Nested capability resources like
    ``capabilities/<name>/references/foo.md`` do NOT match — those
    are legitimate intra-capability references that must stay in the
    load graph.
    """
    parts = ref_path.replace("\\", "/").split("/")
    return (
        len(parts) == 3
        and parts[0] == DIR_CAPABILITIES
        and parts[2] == FILE_CAPABILITY_MD
    )


def extract_body_references(
    content: str,
    *,
    include_router_table: bool = False,
    filter_capability_entries: bool = True,
) -> list[str]:
    """Return cleaned reference paths from a markdown body.

    Applies the body ``reference_patterns`` from ``configuration.yaml``
    (markdown-link and backtick forms) after stripping fenced code
    blocks.  When *include_router_table* is True, the result is also
    augmented with capability paths recovered from a router table in
    *content* — those paths are bare cells, not markdown links, so the
    body regexes alone would miss them.  Only the SKILL.md entry point
    legitimately carries a router table, so callers pass
    ``include_router_table=True`` only for that file.

    Anchor fragments, queries, and title suffixes are stripped via
    :func:`strip_fragment`.  Template placeholders (containing ``<``
    or ``>``) are dropped.  Order is preserved as the body presents
    them, with duplicates removed on first sight.  Router-table
    capability paths follow whatever links were found in prose.

    *filter_capability_entries* (default True) drops references that
    point at a capability entry point (``capabilities/<name>/capability.md``)
    when ``include_router_table`` is False.  The reachability walker
    needs that filter — capability entry points are entry-point-only
    edges, never followed transitively from a non-entry body.  Other
    consumers (e.g. ``validate_skill._check_references``) need to
    *validate* references to capability entry points, so they pass
    ``filter_capability_entries=False`` to keep those paths in scope.
    """
    stripped = _RE_FENCED_BLOCK.sub("", content)
    raw_refs: list[str] = []
    raw_refs.extend(RE_MARKDOWN_LINK_REF.findall(stripped))
    raw_refs.extend(RE_BACKTICK_REF.findall(stripped))
    if include_router_table:
        raw_refs.extend(extract_capability_paths(content))
    elif filter_capability_entries:
        # Capability *entry-point* paths are entry-point-only edges.
        # A non-entry body that references ``capabilities/<name>/capability.md``
        # is either a documentation example or an architecture violation
        # (capabilities don't reference each other — see
        # audit_skill_system).  Either way, do not treat it as a live
        # load edge.  Nested capability resources like
        # ``capabilities/<name>/references/foo.md`` remain legitimate
        # — those are skill-root-relative links from within a
        # capability into its own local references and must stay in
        # the load graph.
        #
        # Apply ``strip_fragment`` before the shape check so anchored
        # links (``capabilities/foo/capability.md#section``) and
        # query-suffixed links are recognized as entry-point paths
        # too — they would otherwise survive this filter and be
        # followed during traversal as a live edge.
        raw_refs = [
            r for r in raw_refs
            if not _is_capability_entry_path(strip_fragment(r))
        ]

    seen: set[str] = set()
    cleaned: list[str] = []
    for ref in raw_refs:
        # Drop template placeholders (``<name>``, ``<...>``).
        if "<" in ref or ">" in ref:
            continue
        # ``strip_fragment`` removes anchors (``#section``), query
        # strings (``?v=2``), and markdown link title annotations
        # (``foo.md "Title"``) — running it before the glob check
        # is essential because ``?`` is also a glob metacharacter
        # but most often appears in a link as a query separator
        # *after* the filename extension.  Checking glob metachars
        # only on the path portion lets normal query-suffixed links
        # like ``guide.md?v=2`` reach the resolver while still
        # filtering out true glob mentions like
        # ``capabilities/**/*.md`` and ``references/[abc].md``
        # whose metachars sit *inside* the filesystem path.
        clean = strip_fragment(ref)
        if not clean:
            continue
        if any(c in clean for c in "*?[]{}"):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        cleaned.append(clean)
    return cleaned


# ===================================================================
# Multi-root reachability walk
# ===================================================================


def _list_capability_entries(skill_root: str) -> list[str]:
    """Return absolute paths of every existing capability.md under *skill_root*.

    Walks ``<skill_root>/capabilities/*/capability.md`` only.  Nested
    capability resources are reached transitively from the entry, not
    enumerated as roots.
    """
    cap_dir = os.path.join(skill_root, DIR_CAPABILITIES)
    if not os.path.isdir(cap_dir):
        return []
    entries: list[str] = []
    for name in sorted(os.listdir(cap_dir)):
        cap_md = os.path.join(cap_dir, name, FILE_CAPABILITY_MD)
        if os.path.isfile(cap_md):
            entries.append(os.path.abspath(cap_md))
    return entries


def walk_reachable(
    skill_root: str,
) -> tuple[set[str], list[str]]:
    """Walk the per-skill reference graph from canonical entry points.

    Roots are ``SKILL.md`` and every existing
    ``capabilities/*/capability.md`` under *skill_root*.  From each
    root, body reference patterns are applied to the post-frontmatter,
    post-fence content; resolved paths are added to the visited set
    and recursively walked when they are markdown files.

    Returns ``(visited, warnings)``:

    * ``visited`` — absolute paths of every file the walk reached.
      Includes the roots themselves.  Non-markdown files appear in
      the set but are not recursed into (the body reference patterns
      target markdown content).
    * ``warnings`` — list of pre-formatted finding strings (``WARN:`` /
      ``INFO:``) for broken or out-of-skill references encountered
      during the walk.  The walk continues past every recoverable
      condition so the caller always receives a complete visited set.

    Refs are resolved **file-relative** — every link is interpreted
    from the directory containing the file the link lives in, using
    standard markdown semantics.  See ``references/path-resolution.md``
    for the canonical rule, the per-scope behavior (skill root vs
    capability root), and the external-reference syntax
    (``../../<dir>/<file>``).

    Parent-traversal segments (``..``) are legal — they are how a
    capability body reaches into the shared skill root.  The walker
    follows the resolved path unchanged; the ``is_within_directory``
    check below is the only boundary that matters.

    Refs that resolve outside *skill_root* are recorded as ``INFO``
    and skipped — they are by definition out of scope for an
    intra-skill orphan check.  Refs that do not resolve to a regular
    file are recorded as ``WARN``.  Absolute paths are recorded as
    ``WARN`` (tagged ``[path-resolution]``) and skipped —
    ``audit_skill_system`` does not otherwise validate intra-skill
    reference syntax, so silent skip would let absolute forms go
    entirely unreported when the audit runs without ``validate_skill``.
    File-read failures during the walk are tagged
    ``[foundry reachability]`` (an operational concern, not a
    path-resolution rule violation).  Callers that already run
    ``validate_skill`` on the same tree (e.g. ``validate_skill``
    itself, which invokes ``find_orphan_references`` after its own
    reference check) suppress these via
    ``surface_walk_warnings=False`` to avoid double counting.
    """
    skill_root = os.path.abspath(skill_root)
    visited: set[str] = set()
    warnings: list[str] = []
    skill_md = os.path.join(skill_root, FILE_SKILL_MD)

    def _to_rel(filepath: str) -> str:
        return os.path.relpath(filepath, skill_root).replace(os.sep, "/")

    def _visit(filepath: str) -> None:
        filepath = os.path.abspath(filepath)
        if filepath in visited:
            return
        visited.add(filepath)

        # Only markdown content is walked further; non-markdown files
        # are recorded as visited (so they are not flagged orphans
        # when reachable) but their bytes are not parsed.
        if not filepath.lower().endswith(".md"):
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeError) as exc:
            rel = _to_rel(filepath)
            warnings.append(
                f"{LEVEL_WARN}: [foundry reachability] cannot read '{rel}' "
                f"({exc.__class__.__name__}: {exc}) — reachability walk "
                f"skipped its references"
            )
            return

        body_only = strip_frontmatter_for_scan(content)
        is_entry = filepath == os.path.abspath(skill_md)
        rel = _to_rel(filepath)
        source_dir = os.path.dirname(filepath)

        for ref in extract_body_references(
            body_only, include_router_table=is_entry,
        ):
            # Reject absolute and drive-qualified paths.
            # ``is_drive_qualified`` (lib/references) provides
            # platform-independent detection of the Windows
            # drive-relative form (``C:foo.md``) that
            # ``os.path.isabs`` misses on every platform; using
            # ``os.path.splitdrive`` would only catch it on Windows
            # because ``os.path`` is host-dependent.  Without the
            # check ``os.path.join`` would treat the path as drive-
            # rooted on Windows and let the reference escape the
            # skill walk.
            if os.path.isabs(ref) or is_drive_qualified(ref):
                warnings.append(
                    f"{LEVEL_WARN}: [{PATH_RESOLUTION_RULE_NAME}] "
                    f"reference '{ref}' in '{rel}' is absolute or "
                    f"drive-qualified — reachability walk skipped it"
                )
                continue
            ref_norm = ref.replace("\\", "/")

            # File-relative resolution per ``path-resolution.md``.
            # Parent-traversal segments are legal — they are the
            # canonical way for a capability body to reach into the
            # shared skill root (``../../references/foo.md``).  The
            # ``is_within_directory`` check below catches paths that
            # escape the skill root entirely.
            ref_abs = os.path.normpath(os.path.join(source_dir, ref_norm))

            if not is_within_directory(ref_abs, skill_root):
                warnings.append(
                    f"{LEVEL_INFO}: [{PATH_RESOLUTION_RULE_NAME}] "
                    f"reference '{ref}' in '{rel}' resolves outside the "
                    f"skill directory — excluded from reachability"
                )
                continue

            if not os.path.exists(ref_abs):
                warnings.append(
                    f"{LEVEL_WARN}: [{PATH_RESOLUTION_RULE_NAME}] "
                    f"reference '{ref}' in '{rel}' does not exist — "
                    f"reachability walk skipped it"
                )
                continue
            if not os.path.isfile(ref_abs):
                warnings.append(
                    f"{LEVEL_WARN}: [{PATH_RESOLUTION_RULE_NAME}] "
                    f"reference '{ref}' in '{rel}' is not a regular "
                    f"file — reachability walk skipped it"
                )
                continue

            _visit(ref_abs)

    if os.path.isfile(skill_md):
        _visit(skill_md)
    for cap_md in _list_capability_entries(skill_root):
        _visit(cap_md)

    return visited, warnings
