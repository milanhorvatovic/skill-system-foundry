"""Component discovery: find skills and roles in a skill system."""

import os
from typing import NamedTuple

from .constants import (
    DIR_SKILLS, DIR_CAPABILITIES, DIR_ROLES,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, FILE_README, EXT_MARKDOWN,
)


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

    Returns one entry per immediate subdirectory.  Returns ``[]`` when
    *skills_dir* is missing.  This is the single source of truth for
    "what is a skill candidate"; both ``find_skill_dirs`` and
    ``find_router_audit_targets`` consume it.
    """
    if not os.path.isdir(skills_dir):
        return []
    candidates: list[_SkillCandidate] = []
    for entry in os.listdir(skills_dir):
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
            for cap in os.listdir(cap_dir):
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


def find_skill_root(system_root: str) -> dict[str, str] | None:
    """Return a synthetic registered-skill entry when SKILL.md sits at *system_root*.

    This complements ``find_skill_dirs`` for the *skill-root mode* —
    auditing a single skill directory (the foundry meta-skill or any
    integrator-built meta-skill) without first deploying it under a
    ``skills/`` tree.

    Used by rules that are intentionally meta-skill-aware (currently the
    router-table consistency rule).  Other per-skill rules continue to
    iterate ``find_skill_dirs`` only, because their pre-existing
    heuristics were not designed to scan meta-skill prose.
    """
    if not os.path.isfile(os.path.join(system_root, FILE_SKILL_MD)):
        return None
    # Compute name from the absolute path so callers passing "." still
    # get a real directory name, but keep ``path`` as the input shape so
    # it matches ``find_skill_dirs`` (which returns paths derived from
    # the caller's ``system_root``).
    return {
        "name": os.path.basename(os.path.abspath(system_root)),
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
    ``path``, ``type=registered``).  The skill-root entry (when
    present) cannot collide with a ``skills/`` candidate because the
    candidate iterator only walks ``<system_root>/skills/<entry>``,
    never ``<system_root>`` itself — so no dedup is needed.
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

    skill_root_entry = find_skill_root(system_root)
    if skill_root_entry is not None:
        targets.append(skill_root_entry)

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
