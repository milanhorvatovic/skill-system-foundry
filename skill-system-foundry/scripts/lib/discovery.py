"""Component discovery: find skills and roles in a skill system."""

import glob
import os
from typing import NamedTuple

from .constants import (
    DIR_SKILLS, DIR_CAPABILITIES, DIR_ROLES,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, FILE_README, EXT_MARKDOWN,
)
from .frontmatter import load_frontmatter


class _SkillCandidate(NamedTuple):
    """One immediate subdirectory of a ``skills/`` tree.

    ``has_skill_md`` and ``has_capabilities`` flag which halves of the
    router contract are present on disk.
    """
    name: str
    path: str
    has_skill_md: bool
    has_capabilities: bool


def _iter_skill_candidates(skills_dir: str) -> list[_SkillCandidate]:
    """One pass over ``<skills_dir>/<entry>``.

    Returns one entry per immediate subdirectory, sorted by name so
    findings emitted by downstream rules (notably the router-table
    audit, which produces per-row findings) stay stable across
    platforms — ``os.listdir`` order is filesystem-defined and
    differs between APFS, ext4, and NTFS.  Returns ``[]`` when
    *skills_dir* is missing.  This is the single source of truth for
    "what is a skill candidate"; both ``find_skill_dirs`` and
    ``find_router_audit_targets`` consume it.
    """
    if not os.path.isdir(skills_dir):
        return []
    candidates: list[_SkillCandidate] = []
    for entry in sorted(os.listdir(skills_dir)):
        entry_path = os.path.join(skills_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        candidates.append(_SkillCandidate(
            name=entry,
            path=entry_path,
            has_skill_md=os.path.isfile(
                os.path.join(entry_path, FILE_SKILL_MD)
            ),
            has_capabilities=os.path.isdir(
                os.path.join(entry_path, DIR_CAPABILITIES)
            ),
        ))
    return candidates


def find_skill_dirs(system_root: str) -> list[dict[str, str]]:
    """Find all skill and capability directories.

    Registered skills contain SKILL.md; capabilities contain capability.md.
    Walks ``<system_root>/skills/<name>/`` — the deployed-system layout.
    """
    skills: list[dict[str, str]] = []
    skills_dir = os.path.join(system_root, DIR_SKILLS)
    for cand in _iter_skill_candidates(skills_dir):
        if cand.has_skill_md:
            skills.append(
                {"name": cand.name, "path": cand.path, "type": "registered"}
            )

        if cand.has_capabilities:
            cap_dir = os.path.join(cand.path, DIR_CAPABILITIES)
            # ``os.listdir`` order is filesystem-defined and differs
            # between APFS, ext4, and NTFS — sort so downstream audit
            # output (and any caller iterating the returned list) is
            # deterministic, matching the skill-candidate sort above.
            for cap in sorted(os.listdir(cap_dir)):
                cap_path = os.path.join(cap_dir, cap)
                cap_skill = os.path.join(cap_path, FILE_CAPABILITY_MD)
                if os.path.isdir(cap_path) and os.path.exists(cap_skill):
                    skills.append(
                        {
                            "name": cap,
                            "path": cap_path,
                            "type": "capability",
                            "parent": cand.name,
                        }
                    )

    return skills


def top_level_skill_entry(system_root: str) -> dict[str, str] | None:
    """Return a synthetic registered-skill entry when SKILL.md sits at *system_root*.

    Complements ``find_skill_dirs`` for the *skill-root mode* — auditing
    a single skill directory (the foundry meta-skill or any
    integrator-built meta-skill) without first deploying it under a
    ``skills/`` tree.  Consumed by audit rules that fire in both
    skill-root and deployed-system modes
    (``find_router_audit_targets``, the aggregation rule).

    The returned ``name`` prefers the SKILL.md frontmatter ``name`` so
    findings are prefixed with the canonical skill name even when the
    audit runs from a worktree or renamed directory (e.g.,
    ``worktrees/feature-foo/``).  Falls back to the absolute-path
    basename when the frontmatter is unreadable, missing, or has no
    ``name`` field, so the prefix degrades gracefully rather than
    blocking the audit.
    """
    skill_md = os.path.join(system_root, FILE_SKILL_MD)
    if not os.path.isfile(skill_md):
        return None
    name = os.path.basename(os.path.abspath(system_root))
    try:
        fm, _, _ = load_frontmatter(skill_md)
    except OSError:
        fm = None
    if fm is not None and "_parse_error" not in fm:
        fm_name = fm.get("name")
        if isinstance(fm_name, str) and fm_name.strip():
            name = fm_name.strip()
    return {
        "name": name,
        "path": system_root,
        "type": "registered",
    }


def find_router_audit_targets(system_root: str) -> list[dict[str, str]]:
    """Return every directory the router-table rule should audit.

    A directory is a router-audit target when it has at least one half
    of the router contract — ``SKILL.md`` exists at the top, or
    ``capabilities/`` exists on disk.  Directories with neither
    (typically empty placeholders) are dropped.

    Sources:

    1. Subdirectories of ``<system_root>/skills/`` that have
       ``SKILL.md`` and/or ``capabilities/``.  This subsumes both
       registered skills (caught by the ``SKILL.md`` half) and orphan
       capability-only directories (caught by the ``capabilities/``
       half) in a single pass.
    2. The skill-root entry — included whenever
       ``<system_root>/SKILL.md`` exists (skill-root mode for
       meta-skills).

    ``audit_router_table`` itself decides whether the rule actually
    applies to each target — a registered skill without
    ``capabilities/`` and without a router table simply returns ``[]``.

    Returned entries match the ``find_skill_dirs`` shape (``name``,
    ``path``, ``type=registered``).  Appending the skill-root entry
    (when present) cannot duplicate a ``skills/`` candidate's
    ``path`` because the candidate iterator only walks
    ``<system_root>/skills/<entry>``, never ``<system_root>``
    itself — so no path-level dedup is needed and the same directory
    is never audited twice.  Names may still overlap (e.g., a
    top-level SKILL.md whose frontmatter ``name`` is ``alpha`` next
    to a ``skills/alpha/`` candidate); each target is audited
    independently because ``path`` is the dispatch key, but the
    finding prefix derived from ``name`` will be ambiguous in that
    pathological case.  Integrators are expected to keep the
    meta-skill's frontmatter name distinct from any deployed skill
    under ``skills/``.
    """
    skills_dir = os.path.join(system_root, DIR_SKILLS)
    targets: list[dict[str, str]] = []

    for cand in _iter_skill_candidates(skills_dir):
        if not (cand.has_skill_md or cand.has_capabilities):
            continue
        targets.append({
            "name": cand.name,
            "path": cand.path,
            "type": "registered",
        })

    skill_root_entry = top_level_skill_entry(system_root)
    if skill_root_entry is not None:
        targets.append(skill_root_entry)
    elif os.path.isdir(os.path.join(system_root, DIR_CAPABILITIES)):
        # SKILL.md is missing but capabilities/ sits at the top —
        # the canonical "broken meta-skill" shape (entry point
        # deleted, on-disk tree left behind).  Without this branch
        # the audit only emits the generic partial-audit WARN; with
        # it, audit_router_table fires the specific
        # ``capabilities/ exists but SKILL.md is missing`` FAIL.
        # Fall back to the basename for the finding prefix because
        # there is no SKILL.md frontmatter to canonicalize.
        targets.append({
            "name": os.path.basename(os.path.abspath(system_root)),
            "path": system_root,
            "type": "registered",
        })

    return targets


def find_roles(system_root: str) -> list[dict[str, str]]:
    """Find all role files."""
    roles = []
    roles_dir = os.path.join(system_root, DIR_ROLES)
    if not os.path.isdir(roles_dir):
        return roles

    for group in os.listdir(roles_dir):
        group_path = os.path.join(roles_dir, group)
        if not os.path.isdir(group_path):
            continue
        for role_file in os.listdir(group_path):
            if role_file.endswith(EXT_MARKDOWN) and role_file != FILE_README:
                roles.append(
                    {
                        "name": role_file[:-3],
                        "path": os.path.join(group_path, role_file),
                        "group": group,
                    }
                )

    return roles


def check_line_count(filepath: str) -> int:
    """Return line count of a file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def read_file(filepath: str) -> str:
    """Read file content."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


class CapabilityRecord(NamedTuple):
    """Discovered ``capability.md`` payload — frontmatter dict (or
    ``None`` for unreadable files / files without frontmatter) plus
    the plain-scalar divergence findings emitted during YAML parsing.

    The pair is stored together so consumers that need both
    (the audit's per-capability loop) and consumers that need only
    the frontmatter (validation rules) can share one discovery pass.
    """
    frontmatter: dict | None
    scalar_findings: list[str]


def load_capability_data(skill_root: str) -> dict[str, CapabilityRecord]:
    """Load every ``capabilities/**/capability.md`` payload once.

    Returns a mapping from absolute path to :class:`CapabilityRecord`.
    Parse errors are kept as a frontmatter dict carrying
    ``_parse_error`` so callers can decide whether to skip or surface
    them — matches the contract of :func:`load_frontmatter`.

    Single discovery pass: ``aggregate_capability_allowed_tools``,
    ``validate_tool_coherence``, the skill-only-fields walk in
    ``validate_skill.py``, and the audit's per-capability loop all
    consume from one dict instead of re-reading the same file
    multiple times.  Callers that hold a ``capability_data`` dict
    pass it through to keep I/O O(1) per file even as new rules
    land on the same data.
    """
    result: dict[str, CapabilityRecord] = {}
    capability_glob = os.path.join(
        skill_root, DIR_CAPABILITIES, "**", FILE_CAPABILITY_MD,
    )
    for path in sorted(glob.glob(capability_glob, recursive=True)):
        abs_path = os.path.abspath(path)
        try:
            fm, _, scalar_findings = load_frontmatter(path)
        except (OSError, UnicodeDecodeError) as exc:
            # Surface I/O failures as a parse-error record so callers
            # (audit capability-isolation, validate_skill skill-only
            # walk) can emit a FAIL through the existing
            # ``_parse_error`` branch instead of silently skipping the
            # file or crashing later when the body is read elsewhere.
            result[abs_path] = CapabilityRecord(
                {"_parse_error": f"unreadable: {exc}"}, [],
            )
            continue
        result[abs_path] = CapabilityRecord(fm, scalar_findings)
    return result
