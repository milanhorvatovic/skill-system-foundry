"""Token-budget measurement for a single skill.

Computes two byte-based proxies for a skill's context cost:

* ``discovery_bytes`` — the raw bytes of the ``SKILL.md`` YAML
  frontmatter block, inclusive of the two ``---`` fences.  This is what
  the harness reads at startup to decide whether the skill is relevant.

* ``load_bytes`` — the raw bytes of ``SKILL.md`` plus every in-scope
  referenced file reachable transitively from the entry point through
  the body reference patterns defined in ``configuration.yaml``.  Files
  under ``scripts/`` and ``assets/`` are excluded because they are not
  loaded into the model's context during skill use; only ``SKILL.md``,
  ``capabilities/.../capability.md``, and ``references/.../*`` count
  toward the load budget.

Bytes are not tokens.  Byte counts are not comparable across models or
tokenizers — they are a deterministic, on-disk signal for tracking the
relative cost of authoring decisions over time.  All counts are taken
from the raw on-disk UTF-8 bytes (CRLF preserved); a Windows checkout
of the same content will report higher than a POSIX checkout.
"""

import os
import re

from .constants import (
    DIR_ASSETS,
    DIR_CAPABILITIES,
    DIR_SCRIPTS,
    FILE_CAPABILITY_MD,
    FILE_SKILL_MD,
    LEVEL_FAIL,
    LEVEL_INFO,
    LEVEL_WARN,
    RE_BACKTICK_REF,
    RE_MARKDOWN_LINK_REF,
)
from .references import strip_fragment
from .router_table import (
    _parse_path_cell,
    _recover_segment,
    parse_router_table,
)


# Directory categories whose bytes are excluded from ``load_bytes``.
# Scripts execute outside the model's context window; assets are
# templates copied or rewritten by tooling, not loaded as instructions.
_EXCLUDED_LOAD_CATEGORIES = frozenset({DIR_SCRIPTS, DIR_ASSETS})

# Pattern that strips fenced code blocks before reference scanning, so
# example links inside ``` are not treated as real references.
_RE_FENCED_BLOCK = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


# ===================================================================
# File-level helpers
# ===================================================================


def read_bytes_count(filepath: str) -> int:
    """Return the raw on-disk byte count of *filepath*.

    Reads in binary mode so CRLF is preserved (a Windows checkout of
    the same file therefore reports a higher count than a POSIX
    checkout).  Raises ``OSError`` on read failure; callers convert
    that into a finding rather than letting it abort the run.
    """
    with open(filepath, "rb") as f:
        return len(f.read())


def discovery_bytes_for_skill_md(skill_md_path: str) -> int:
    """Return the byte count of the YAML frontmatter block.

    The block runs from the opening ``---`` line through the closing
    ``---`` line, inclusive of both fences and the newlines that
    terminate them.  Returns ``0`` when the file does not start with a
    ``---`` opener or has no closing ``---`` — those cases are
    surfaced as findings by ``compute_stats``.

    Counted from raw on-disk bytes (CRLF preserved).
    """
    with open(skill_md_path, "rb") as f:
        data = f.read()
    if not data.startswith(b"---"):
        return 0
    # Walk line by line to find the closing fence.  Track the byte
    # offset where the closing fence's terminator ends so the count
    # includes both fences and the newline that follows the closer.
    offset = 0
    line_index = 0
    while offset < len(data):
        newline = data.find(b"\n", offset)
        if newline == -1:
            line_end = len(data)
            line = data[offset:line_end]
            terminator_end = line_end
        else:
            line = data[offset:newline]
            terminator_end = newline + 1
        stripped = line.rstrip(b"\r")
        if line_index > 0 and stripped == b"---":
            return terminator_end
        if line_index == 0 and stripped != b"---":
            return 0
        offset = terminator_end
        line_index += 1
    return 0


# ===================================================================
# Reference extraction
# ===================================================================


def extract_body_references(content: str) -> list[str]:
    """Return cleaned reference paths from a markdown body.

    Applies the body ``reference_patterns`` from ``configuration.yaml``
    (markdown-link and backtick forms) after stripping fenced code
    blocks, then augments the result with capability paths recovered
    from a SKILL.md router table — those paths are bare cells, not
    markdown links, so the body regexes alone would miss them.

    Anchor fragments, queries, and title suffixes are stripped via
    :func:`strip_fragment`.  Template placeholders (containing ``<``
    or ``>``) are dropped.  Order is preserved as the body presents
    them, with duplicates removed on first sight.  Router-table
    capability paths follow whatever links were found in prose.
    """
    stripped = _RE_FENCED_BLOCK.sub("", content)
    raw_refs: list[str] = []
    raw_refs.extend(RE_MARKDOWN_LINK_REF.findall(stripped))
    raw_refs.extend(RE_BACKTICK_REF.findall(stripped))
    raw_refs.extend(_router_table_capability_paths(content))

    seen: set[str] = set()
    cleaned: list[str] = []
    for ref in raw_refs:
        if "<" in ref or ">" in ref:
            continue
        clean = strip_fragment(ref)
        if not clean:
            continue
        if clean in seen:
            continue
        seen.add(clean)
        cleaned.append(clean)
    return cleaned


def _router_table_capability_paths(content: str) -> list[str]:
    """Return ``capabilities/<name>/capability.md`` paths from a router table.

    Returns an empty list when *content* contains no router table or
    when none of its rows have a recoverable canonical path cell.
    Decoration recovery (backticks, ``[text](url)`` wrappers, leading
    ``./``, trailing ``#fragment``) is applied so authors can decorate
    table cells without their capabilities disappearing from the load
    graph.
    """
    parsed = parse_router_table(content)
    if parsed is None:
        return []
    rows, _findings = parsed
    paths: list[str] = []
    for _capability, _trigger, path_cell in rows:
        # Try strict parse first, then the decoration-stripping
        # recovery used by the router-table audit.
        name = _parse_path_cell(path_cell.strip())
        if name is None:
            name = _recover_segment(path_cell)
        if name is None:
            continue
        paths.append(
            f"{DIR_CAPABILITIES}/{name}/{FILE_CAPABILITY_MD}"
        )
    return paths


def category_of(rel_path: str) -> str:
    """Return the top-level directory of a skill-root-relative path.

    Returns the entry-file basename for top-level files (e.g.
    ``"SKILL.md"``) and the leading directory name for files inside a
    subdirectory (e.g. ``"capabilities"``, ``"references"``).
    """
    parts = rel_path.replace("\\", "/").split("/", 1)
    return parts[0]


def is_excluded_from_load(rel_path: str) -> bool:
    """Return True when a path's bytes should not contribute to load."""
    return category_of(rel_path) in _EXCLUDED_LOAD_CATEGORIES


# ===================================================================
# Stats computation
# ===================================================================


def _to_skill_root_relative(filepath: str, skill_root: str) -> str:
    """Return a POSIX path relative to *skill_root* for display."""
    rel = os.path.relpath(filepath, skill_root)
    return rel.replace(os.sep, "/")


def compute_stats(skill_path: str) -> dict:
    """Compute byte-based stats for the skill rooted at *skill_path*.

    Returns a dict with keys::

        {
            "skill":           str,           # skill name (frontmatter or dir basename)
            "metric":          "bytes",
            "discovery_bytes": int,
            "load_bytes":      int,
            "files":           list[dict],    # sorted by relative POSIX path
            "errors":          list[str],     # FAIL/WARN/INFO finding strings
        }

    Each ``files`` entry has the shape::

        {
            "path":            str,                 # relative to skill root, POSIX
            "bytes":           int,
            "reachable_from":  list[str],           # parents, sorted alphabetically
        }

    The traversal:

    * Starts at ``SKILL.md`` and follows body reference patterns.
    * Filters out scripts/assets from ``load_bytes`` and from the
      reported file list — they are not loaded into the model context.
    * Visits each file at most once; duplicate references accumulate
      additional parents in ``reachable_from`` and naturally short-
      circuit cycles (a back-edge to an already-visited file just
      records the extra parent and stops recursing).
    * Produces a WARN when a referenced file is missing or unreadable
      and continues from any other parents.
    * Produces an INFO when a reference resolves outside the skill
      directory (cross-skill or shared-system reference) — those files
      are not counted toward ``load_bytes``.

    A FAIL is returned only when ``SKILL.md`` itself is missing; the
    caller treats that as an early exit via the ``errors`` list (no
    metrics are computed).  Every other condition is recoverable.
    """
    skill_path = os.path.abspath(skill_path)
    skill_md = os.path.join(skill_path, FILE_SKILL_MD)

    result: dict = {
        "skill": os.path.basename(skill_path.rstrip(os.sep)),
        "metric": "bytes",
        "discovery_bytes": 0,
        "load_bytes": 0,
        "files": [],
        "errors": [],
    }

    if not os.path.isfile(skill_md):
        result["errors"].append(
            f"{LEVEL_FAIL}: [foundry] No {FILE_SKILL_MD} found in {skill_path}"
        )
        return result

    # Best-effort skill-name resolution from frontmatter; falls back to
    # the directory basename when frontmatter is absent or malformed.
    # Importing lazily avoids a circular dependency through constants.
    from .frontmatter import load_frontmatter

    frontmatter, _body, _scalar_findings = load_frontmatter(skill_md)
    if frontmatter and "_parse_error" not in frontmatter and frontmatter.get("name"):
        result["skill"] = str(frontmatter["name"])

    discovery_count = discovery_bytes_for_skill_md(skill_md)
    if discovery_count == 0:
        result["errors"].append(
            f"{LEVEL_WARN}: [foundry] {FILE_SKILL_MD} has no parseable "
            f"frontmatter block; discovery_bytes recorded as 0"
        )
    result["discovery_bytes"] = discovery_count

    # ``visited`` keys are absolute paths; values capture per-file
    # state (relative path, byte count, parent set).  Reading happens
    # once per file regardless of how many parents reach it.
    visited: dict[str, dict] = {}

    def _visit(filepath: str, parent_rel: str | None) -> None:
        filepath = os.path.abspath(filepath)
        rel = _to_skill_root_relative(filepath, skill_path)
        if filepath in visited:
            if parent_rel is not None:
                visited[filepath]["parents"].add(parent_rel)
            return

        try:
            byte_count = read_bytes_count(filepath)
        except OSError as exc:
            result["errors"].append(
                f"{LEVEL_WARN}: [foundry] cannot read '{rel}' "
                f"({exc.__class__.__name__}: {exc})"
            )
            return

        parents: set[str] = set()
        if parent_rel is not None:
            parents.add(parent_rel)
        visited[filepath] = {
            "path": rel,
            "bytes": byte_count,
            "parents": parents,
        }

        # Only markdown bodies carry references in the patterns we use.
        if not filepath.lower().endswith(".md"):
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeError) as exc:
            result["errors"].append(
                f"{LEVEL_WARN}: [foundry] cannot decode '{rel}' as UTF-8 "
                f"for reference scanning ({exc.__class__.__name__}: {exc})"
            )
            return

        for ref in extract_body_references(content):
            if os.path.isabs(ref):
                result["errors"].append(
                    f"{LEVEL_WARN}: [foundry] absolute reference '{ref}' "
                    f"in '{rel}' skipped — references must be relative"
                )
                continue
            ref_norm = ref.replace("\\", "/")
            if ".." in ref_norm.split("/"):
                result["errors"].append(
                    f"{LEVEL_WARN}: [foundry] reference '{ref}' in '{rel}' "
                    f"uses parent traversal — skipped from stats"
                )
                continue

            ref_abs = os.path.normpath(os.path.join(skill_path, ref_norm))
            ref_rel = _to_skill_root_relative(ref_abs, skill_path)

            # External / cross-skill references resolve outside the
            # skill root; report once and skip — they are not part of
            # this skill's load budget.
            if ref_rel.startswith(".."):
                result["errors"].append(
                    f"{LEVEL_INFO}: [foundry] reference '{ref}' in '{rel}' "
                    f"resolves outside the skill directory — excluded "
                    f"from load_bytes"
                )
                continue

            if not os.path.exists(ref_abs):
                result["errors"].append(
                    f"{LEVEL_WARN}: [foundry] reference '{ref}' in '{rel}' "
                    f"does not exist — excluded from load_bytes"
                )
                continue
            if not os.path.isfile(ref_abs):
                result["errors"].append(
                    f"{LEVEL_WARN}: [foundry] reference '{ref}' in '{rel}' "
                    f"is not a regular file — excluded from load_bytes"
                )
                continue

            _visit(ref_abs, rel)

    _visit(skill_md, None)

    # Build the sorted file list and total load_bytes, filtering out
    # categories that don't contribute to the model's context.
    entries: list[dict] = []
    load_total = 0
    for state in visited.values():
        if is_excluded_from_load(state["path"]):
            continue
        entries.append({
            "path": state["path"],
            "bytes": state["bytes"],
            "reachable_from": sorted(state["parents"]),
        })
        load_total += state["bytes"]

    entries.sort(key=lambda entry: entry["path"])
    result["files"] = entries
    result["load_bytes"] = load_total
    return result
