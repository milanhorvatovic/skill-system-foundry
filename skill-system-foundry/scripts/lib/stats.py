"""Token-budget measurement for a single skill.

Computes two byte-based proxies for a skill's context cost:

* ``discovery_bytes`` — the raw bytes of the ``SKILL.md`` YAML
  frontmatter block, inclusive of the two ``---`` fences.  This is what
  the harness reads at startup to decide whether the skill is relevant.

* ``load_bytes`` — the raw bytes of ``SKILL.md`` plus every in-scope
  referenced file reachable transitively from the entry point through
  the body reference patterns defined in ``configuration.yaml``.
  Files under ``scripts/`` and ``assets/`` are excluded because they
  are not loaded into the model's context during skill use; everything
  else reachable under ``capabilities/`` or ``references/`` counts
  toward the load budget — that includes capability entry points
  (``capabilities/<name>/capability.md``), capability-local resources
  (``capabilities/<name>/references/<doc>.md``), and shared
  ``references/<doc>.md`` files.

Bytes are not tokens.  Byte counts are not comparable across models or
tokenizers — they are a deterministic, on-disk signal for tracking the
relative cost of authoring decisions over time.  All counts are taken
from the raw on-disk UTF-8 bytes (CRLF preserved); a Windows checkout
of the same content will report higher than a POSIX checkout.
"""

import os

from .constants import (
    DIR_ASSETS,
    DIR_SCRIPTS,
    FILE_SKILL_MD,
    LEVEL_FAIL,
    LEVEL_INFO,
    LEVEL_WARN,
)
from .frontmatter import load_frontmatter, strip_frontmatter_for_scan
from .reachability import extract_body_references
from .references import is_within_directory


# Directory categories whose bytes are excluded from ``load_bytes``.
# Scripts execute outside the model's context window; assets are
# templates copied or rewritten by tooling, not loaded as instructions.
_EXCLUDED_LOAD_CATEGORIES = frozenset({DIR_SCRIPTS, DIR_ASSETS})


# ===================================================================
# File-level helpers
# ===================================================================


def read_bytes_count(filepath: str) -> int:
    """Return the raw on-disk byte count of *filepath*.

    Uses ``os.path.getsize`` so the count is taken from the inode size
    without reading the file contents.  CRLF terminators are preserved
    in that count (a Windows checkout of the same file therefore
    reports a higher size than a POSIX checkout).  Raises ``OSError``
    on stat failure; callers convert that into a finding rather than
    letting it abort the run.
    """
    return os.path.getsize(filepath)


def discovery_bytes_of(markdown_path: str) -> int:
    """Return the byte count of a markdown file's YAML frontmatter block.

    The block runs from the opening ``---`` line through the closing
    ``---`` line, inclusive of both fences and the newlines that
    terminate them.  Returns ``0`` when the file does not start with a
    ``---`` opener or has no closing ``---`` — those cases are
    surfaced as findings by ``compute_stats``.

    Counted from raw on-disk bytes (CRLF preserved).  Reads in UTF-8
    text mode with ``newline=""`` so carriage returns are not
    swallowed by universal-newline translation, then re-encodes to
    bytes for the byte-oriented scanner.  The text mode keeps the
    ``encoding="utf-8"`` convention without losing the CRLF byte cost
    that Windows checkouts genuinely pay at discovery time.

    Deliberately walks the bytes rather than reusing
    ``frontmatter.split_frontmatter`` — the parser normalizes CRLF to
    LF before splitting, which would also lose those carriage returns.
    The two implementations are kept in sync by the
    ``DiscoveryBoundaryAgreementTests`` assertion in test_stats.py.
    """
    with open(markdown_path, "r", encoding="utf-8", newline="") as f:
        data = f.read().encode("utf-8")
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
#
# ``extract_body_references`` is provided by ``lib.reachability`` and
# imported above.  It is the single source of truth for body reference
# extraction; both the byte-budget metric (this module) and the
# orphan-reference audit consume it.


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
    # Wrap both entry-file reads in try/except so a permission error or
    # invalid UTF-8 surfaces as a structured FAIL instead of a
    # traceback through the CLI.
    try:
        frontmatter, _body, _scalar_findings = load_frontmatter(skill_md)
    except (OSError, UnicodeError) as exc:
        result["errors"].append(
            f"{LEVEL_FAIL}: [foundry] cannot read {FILE_SKILL_MD} "
            f"({exc.__class__.__name__}: {exc})"
        )
        return result
    if frontmatter and "_parse_error" in frontmatter:
        # The skill is not discoverable as-is — surface the parse error
        # so consumers don't read the metric as a clean signal.  Stats
        # continues anyway so the load graph (which doesn't depend on
        # the parsed frontmatter) is still useful for debugging.
        result["errors"].append(
            f"{LEVEL_WARN}: [foundry] {FILE_SKILL_MD} frontmatter has a "
            f"parse error ({frontmatter['_parse_error']}); the skill "
            f"is not discoverable as-is — fix the frontmatter before "
            f"trusting these numbers"
        )
    elif frontmatter and frontmatter.get("name"):
        result["skill"] = str(frontmatter["name"])

    try:
        discovery_count = discovery_bytes_of(skill_md)
    except (OSError, UnicodeError) as exc:
        result["errors"].append(
            f"{LEVEL_FAIL}: [foundry] cannot scan {FILE_SKILL_MD} "
            f"frontmatter ({exc.__class__.__name__}: {exc})"
        )
        return result
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
        # Decline at the boundary for excluded categories — scripts and
        # assets are not loaded into the model context, so reading
        # their bytes only to drop the row later wastes I/O.
        if is_excluded_from_load(rel):
            return
        if filepath in visited:
            if parent_rel is not None:
                visited[filepath]["parents"].add(parent_rel)
            return

        try:
            byte_count = read_bytes_count(filepath)
        except OSError as exc:
            result["errors"].append(
                f"{LEVEL_WARN}: [foundry] cannot read '{rel}' "
                f"({exc.__class__.__name__}: {exc}) — excluded from "
                f"load_bytes"
            )
            return

        # For markdown files, attempt the UTF-8 decode BEFORE
        # recording in ``visited`` so that an undecodable file is
        # excluded from ``files[]`` and ``load_bytes`` rather than
        # being counted with a trailing WARN.  Non-markdown files
        # (within the load-budget categories) record only their
        # byte count — there is no body to walk.
        is_markdown = filepath.lower().endswith(".md")
        content: str | None = None
        if is_markdown:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeError) as exc:
                result["errors"].append(
                    f"{LEVEL_WARN}: [foundry] cannot decode '{rel}' as "
                    f"UTF-8 ({exc.__class__.__name__}: {exc}) — "
                    f"excluded from load_bytes"
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

        # Non-markdown: byte count recorded, nothing to walk further.
        if content is None:
            return

        # Strip the YAML frontmatter block before reference extraction
        # so metadata strings (e.g. ``description: see references/foo.md``)
        # are not mistaken for live load edges.  The body regex is
        # otherwise applied to the entire file, including the
        # frontmatter, which would inflate ``load_bytes`` whenever a
        # frontmatter scalar happens to contain a path-shaped string.
        body_only = strip_frontmatter_for_scan(content)
        is_entry = filepath == os.path.abspath(skill_md)
        for ref in extract_body_references(
            body_only, include_router_table=is_entry,
        ):
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

            # Decline at the gate for excluded categories.  A missing
            # scripts/foo.py or assets/template.md must not emit a
            # broken-ref WARN, since those categories are silently
            # excluded from load_bytes anyway — the existence check
            # below would fire a false-positive warning on every
            # missing helper script that the entry happens to mention.
            if is_excluded_from_load(ref_norm):
                continue

            # External / cross-skill references resolve outside the
            # skill root; report once and skip — they are not part of
            # this skill's load budget.  Use is_within_directory rather
            # than a lexical relpath check so symlinks pointing outside
            # the skill are correctly classified.
            if not is_within_directory(ref_abs, skill_path):
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

    # Build the sorted file list and total load_bytes.  ``visited``
    # already excludes scripts/assets thanks to the early-return in
    # ``_visit``, so this loop is an unconditional aggregator.
    entries: list[dict] = []
    load_total = 0
    for state in visited.values():
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
