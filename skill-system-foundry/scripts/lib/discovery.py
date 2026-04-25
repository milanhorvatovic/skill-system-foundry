"""Component discovery: find skills and roles in a skill system."""

import os

from .constants import (
    DIR_SKILLS, DIR_CAPABILITIES, DIR_ROLES,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, FILE_README, EXT_MARKDOWN,
)


def find_skill_dirs(system_root: str) -> list[dict[str, str]]:
    """Find all skill and capability directories.

    Registered skills contain SKILL.md; capabilities contain capability.md.
    Walks ``<system_root>/skills/<name>/`` — the deployed-system layout.
    """
    skills = []
    skills_dir = os.path.join(system_root, DIR_SKILLS)
    if not os.path.isdir(skills_dir):
        return skills

    for domain in os.listdir(skills_dir):
        domain_path = os.path.join(skills_dir, domain)
        if not os.path.isdir(domain_path):
            continue

        skill_md = os.path.join(domain_path, FILE_SKILL_MD)
        if os.path.exists(skill_md):
            skills.append(
                {"name": domain, "path": domain_path, "type": "registered"}
            )

        # Check for capabilities
        cap_dir = os.path.join(domain_path, DIR_CAPABILITIES)
        if os.path.isdir(cap_dir):
            for cap in os.listdir(cap_dir):
                cap_path = os.path.join(cap_dir, cap)
                cap_skill = os.path.join(cap_path, FILE_CAPABILITY_MD)
                if os.path.isdir(cap_path) and os.path.exists(cap_skill):
                    skills.append(
                        {
                            "name": cap,
                            "path": cap_path,
                            "type": "capability",
                            "parent": domain,
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
    skill_root_abs = os.path.abspath(system_root)
    return {
        "name": os.path.basename(skill_root_abs),
        "path": skill_root_abs,
        "type": "registered",
    }


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
