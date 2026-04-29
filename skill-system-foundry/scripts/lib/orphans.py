"""Orphan-reference audit rule.

A file under a skill's ``references/`` directory (or under a nested
``capabilities/<name>/references/`` directory) is an *orphan* when no
``SKILL.md`` and no ``capability.md`` reach it via the configured body
reference patterns — directly or transitively.  Orphans are dead
weight: they add maintenance cost and confuse readers, but the
existing reference checks (which enforce only that *outgoing* links
resolve) cannot detect them.

This module exposes :func:`find_orphan_references`, which compares
every regular file under those directories against the visited set
returned by :func:`lib.reachability.walk_reachable` and emits one
``WARN`` finding per orphan that is not in ``allowed_orphans``.

The rule is independent of the ``--allow-nested-references`` flag:
that flag suppresses depth warnings for legitimately deep reference
chains, while this rule only asks whether a file is reachable at all.
A skill with deep references can still have orphans, and a skill with
shallow references can have none.

Hybrid keying for ``allowed_orphans``:

* Entries that begin with ``skills/`` are *audit-root-relative* —
  they target one specific skill in a deployed-system audit.
* All other entries are *skill-root-relative* and apply uniformly to
  every skill the audit walks (and to the single skill in skill-root
  mode).

Both forms are normalized to forward-slash POSIX form before
comparison so Windows checkouts and POSIX checkouts behave
identically.
"""

import os

from .constants import (
    DIR_CAPABILITIES,
    DIR_REFERENCES,
    DIR_SKILLS,
    LEVEL_WARN,
)
from .reachability import walk_reachable


# ===================================================================
# Candidate set
# ===================================================================


def _list_reference_files(skill_root: str) -> list[str]:
    """Return absolute paths of every file under references/ trees.

    Walks two locations:

    * ``<skill_root>/references/**`` (the skill's shared references)
    * ``<skill_root>/capabilities/*/references/**`` (per-capability
      references)

    All file types are returned — ``.md``, images, YAML snippets, and
    any other extension — because a non-markdown file consumes disk
    space and review attention just as a stale ``.md`` does.

    Symbolic links are followed; broken or directory-pointing entries
    are skipped silently.  Hidden files (names starting with ``.``)
    are excluded so noise like editor swap files or ``.DS_Store`` does
    not surface as an orphan finding.
    """
    candidates: list[str] = []
    locations: list[str] = []

    top_refs = os.path.join(skill_root, DIR_REFERENCES)
    if os.path.isdir(top_refs):
        locations.append(top_refs)

    cap_dir = os.path.join(skill_root, DIR_CAPABILITIES)
    if os.path.isdir(cap_dir):
        for name in sorted(os.listdir(cap_dir)):
            cap_refs = os.path.join(cap_dir, name, DIR_REFERENCES)
            if os.path.isdir(cap_refs):
                locations.append(cap_refs)

    for location in locations:
        for root, dirs, files in os.walk(location, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for filename in sorted(files):
                if filename.startswith("."):
                    continue
                filepath = os.path.join(root, filename)
                if not os.path.isfile(filepath):
                    continue
                candidates.append(os.path.abspath(filepath))

    return candidates


# ===================================================================
# Allowed-orphans matching
# ===================================================================


def _normalize_path(path: str) -> str:
    """Return *path* in forward-slash form with no leading ``./``."""
    cleaned = path.replace("\\", "/").strip()
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _build_allowed_set(
    allowed_orphans: tuple[str, ...] | list[str],
    skill_root: str,
    audit_root: str | None,
) -> set[str]:
    """Resolve every ``allowed_orphans`` entry into an absolute path.

    Entries that begin with ``skills/`` are audit-root-relative; they
    are joined to *audit_root* when one was supplied and otherwise
    skipped (skill-root mode has no audit root that contains the
    ``skills/`` segment).  All other entries are skill-root-relative
    and are joined to *skill_root*.  Returned paths are normalized
    via :func:`os.path.normcase` + :func:`os.path.normpath` so the
    comparison works on case-insensitive filesystems.
    """
    resolved: set[str] = set()
    for entry in allowed_orphans:
        norm = _normalize_path(entry)
        if not norm:
            continue
        if norm.startswith(f"{DIR_SKILLS}/"):
            if audit_root is None:
                continue
            base = audit_root
        else:
            base = skill_root
        abs_path = os.path.normpath(os.path.join(base, norm))
        resolved.add(os.path.normcase(abs_path))
    return resolved


# ===================================================================
# Public API
# ===================================================================


def find_orphan_references(
    skill_root: str,
    allowed_orphans: tuple[str, ...] | list[str],
    *,
    audit_root: str | None = None,
    skill_audit_prefix: str | None = None,
) -> list[str]:
    """Return WARN finding strings for every orphan in *skill_root*.

    Parameters
    ----------
    skill_root:
        Absolute path to the skill being audited (the directory
        containing ``SKILL.md``).
    allowed_orphans:
        Iterable of opt-out entries from ``configuration.yaml``.  The
        hybrid keying described in this module's docstring is applied.
    audit_root:
        Absolute path to the audit root in deployed-system mode (the
        directory that contains ``skills/``).  Required for matching
        ``skills/...``-prefixed allow-list entries.  In skill-root
        mode, callers may pass *skill_root* itself or ``None``;
        ``skills/...`` entries simply do not match anything in that
        case (they have nothing to disambiguate).
    skill_audit_prefix:
        Optional display prefix used when formatting findings (e.g.
        ``skills/foo`` for system-root mode, the skill basename for
        skill-root mode).  Defaults to the skill directory's basename
        so a CLI consumer always sees a stable label.

    Returns
    -------
    list[str]
        One ``WARN``-prefixed finding per unreferenced file that is
        not opted out via *allowed_orphans*.  Order is deterministic
        (alphabetical by skill-root-relative path).  An empty list
        means the skill has no orphans (or none beyond those allowed).
    """
    skill_root = os.path.abspath(skill_root)
    if skill_audit_prefix is None:
        skill_audit_prefix = os.path.basename(skill_root.rstrip(os.sep))

    candidates = _list_reference_files(skill_root)
    visited, walk_warnings = walk_reachable(skill_root)
    visited_norm = {os.path.normcase(p) for p in visited}

    resolved_audit_root = (
        os.path.abspath(audit_root) if audit_root is not None else None
    )
    allowed = _build_allowed_set(
        allowed_orphans, skill_root, resolved_audit_root,
    )

    findings: list[str] = []
    # Surface reachability-walk diagnostics with the skill prefix so
    # audit consumers see *why* a target file might appear orphan
    # (e.g., a malformed link in some upstream file caused the walk
    # to stop short).  validate_skill emits its own broken-reference
    # findings via validate_skill_references, so these duplicate
    # nothing in skill-validation runs but add real diagnostic value
    # when audit_skill_system runs the rule on its own.
    for warning in walk_warnings:
        findings.append(
            f"{warning[: warning.find(':')]}: {skill_audit_prefix} "
            f"{warning[warning.find(':') + 2 :]}"
        )

    if not candidates:
        return findings

    orphans: list[tuple[str, str]] = []
    for candidate in candidates:
        candidate_norm = os.path.normcase(candidate)
        if candidate_norm in visited_norm:
            continue
        if candidate_norm in allowed:
            continue
        rel = os.path.relpath(candidate, skill_root).replace(os.sep, "/")
        orphans.append((rel, candidate))

    orphans.sort(key=lambda item: item[0])
    for rel, _ in orphans:
        findings.append(
            f"{LEVEL_WARN}: {skill_audit_prefix}/{rel} is unreferenced — "
            f"link it from a SKILL.md or capability.md, delete it, or add "
            f"it to 'orphan_references.allowed_orphans' in "
            f"configuration.yaml"
        )

    return findings
