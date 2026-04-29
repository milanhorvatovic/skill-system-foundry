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
    LEVEL_INFO,
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

    Symbolic-link handling is intentionally asymmetric:

    * Symlinks to regular files inside ``references/`` are included
      as candidates (``os.path.isfile`` follows the link).
    * Symlinks to directories are NOT descended (``os.walk`` is
      called with ``followlinks=False``) — author per-directory
      resources via real directories instead.
    * Broken links and links pointing at non-files are skipped
      silently (``os.path.isfile`` returns False).

    Hidden files and hidden directories are scanned the same as any
    other entry: a stale ``references/.notes.md`` or a stale file
    under ``references/.draft/`` consumes bundle bytes and review
    attention just like a visible orphan, and the rule's documented
    surface is "every file under ``references/``".  Genuinely
    transient noise (``.DS_Store``, editor swap files) is best
    handled at the source — ``.gitignore`` keeps it out of the
    checkout, or ``orphan_references.allowed_orphans`` opts the
    specific path out for cases that must remain in the tree.
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
            dirs[:] = sorted(dirs)
            for filename in sorted(files):
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
    surface_walk_warnings: bool = True,
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
    surface_walk_warnings:
        When True (the default), reachability-walk diagnostics
        (broken / out-of-skill / unreadable references encountered
        during the walk) are emitted as findings prefixed with the
        skill label.  ``audit_skill_system`` wants this — it does not
        otherwise validate intra-skill references, so the walk's view
        is the only signal of *why* a target file appears orphan.
        ``validate_skill`` callers should pass ``False`` because
        ``validate_skill_references`` already emits equivalent
        broken-reference findings against the same graph; surfacing
        them again would double the WARN count for every broken
        intra-skill link.

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
    if surface_walk_warnings:
        for warning in walk_warnings:
            level, _, rest = warning.partition(": ")
            findings.append(f"{level}: {skill_audit_prefix} {rest}")

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


# ===================================================================
# Stale allow-list detection
# ===================================================================


def find_unresolved_allowed_orphans(
    allowed_orphans: tuple[str, ...] | list[str],
    skill_roots: list[str],
    audit_root: str | None,
) -> list[str]:
    """Return INFO findings for ``allowed_orphans`` entries that don't resolve.

    An entry is *unresolved* when it does not point at an existing
    regular file under any of the audited skill roots (or under
    *audit_root* for ``skills/...``-prefixed entries).  Without this
    surface, allow-list entries silently rot when the referenced file
    is renamed, moved, or removed — and a real orphan that the entry
    was meant to suppress would re-appear unnoticed once a future
    rename collides with the stale path.

    Hybrid keying matches the rule's runtime semantics:

    * ``skills/<name>/...``  — checked against *audit_root* only.
      When *audit_root* is ``None`` (skill-root mode), the entry is
      *not applicable* in this audit — it would target a deployed
      system layout — so it is silently skipped here rather than
      flagged.  Re-running the same config in system-root mode
      against a deployed system would still apply the entry, so
      "skipped" is the right outcome.
    * Any other entry — checked against every entry in *skill_roots*.
      The entry is unresolved only when *no* skill root resolves it
      to an existing file.

    Returns one INFO-level finding per unresolved entry, deterministic
    in input order.  Empty *allowed_orphans* trivially returns ``[]``.
    A fully-empty audit (no skill roots and no audit root — partial
    distribution-repo mode) also returns ``[]`` so allow-list entries
    are not falsely flagged as stale just because the run cannot reach
    any skill; the partial-audit WARN already signals the limitation.
    """
    findings: list[str] = []
    if not skill_roots and audit_root is None:
        return findings
    resolved_audit_root = (
        os.path.abspath(audit_root) if audit_root is not None else None
    )
    abs_skill_roots = [os.path.abspath(p) for p in skill_roots]
    for entry in allowed_orphans:
        norm = _normalize_path(entry)
        if not norm:
            continue
        if norm.startswith(f"{DIR_SKILLS}/"):
            if resolved_audit_root is None:
                continue
            candidate = os.path.normpath(
                os.path.join(resolved_audit_root, norm)
            )
            if os.path.isfile(candidate):
                continue
        else:
            matched = False
            for skill_root in abs_skill_roots:
                candidate = os.path.normpath(os.path.join(skill_root, norm))
                if os.path.isfile(candidate):
                    matched = True
                    break
            if matched:
                continue
        findings.append(
            f"{LEVEL_INFO}: orphan_references.allowed_orphans entry "
            f"'{entry}' does not resolve to an existing file under the "
            f"audited skills — remove it from configuration.yaml or "
            f"update the path"
        )
    return findings
