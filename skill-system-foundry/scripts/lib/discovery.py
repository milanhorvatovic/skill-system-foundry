"""Component discovery: find skills and roles in a skill system."""

import os

from .constants import (
    DIR_SKILLS, DIR_CAPABILITIES, DIR_ROLES,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, FILE_README, EXT_MARKDOWN,
)


def _collect_capabilities(
    skill_path: str, parent_name: str,
) -> list[dict[str, str]]:
    """Walk ``<skill_path>/capabilities/*`` and return capability entries."""
    entries: list[dict[str, str]] = []
    cap_dir = os.path.join(skill_path, DIR_CAPABILITIES)
    if not os.path.isdir(cap_dir):
        return entries
    for cap in os.listdir(cap_dir):
        cap_path = os.path.join(cap_dir, cap)
        cap_skill = os.path.join(cap_path, FILE_CAPABILITY_MD)
        if os.path.isdir(cap_path) and os.path.exists(cap_skill):
            entries.append(
                {
                    "name": cap,
                    "path": cap_path,
                    "type": "capability",
                    "parent": parent_name,
                }
            )
    return entries


def find_skill_dirs(system_root: str) -> list[dict[str, str]]:
    """Find all skill and capability directories.

    Registered skills contain SKILL.md; capabilities contain capability.md.

    Two discovery modes are supported:

    * **System-root mode** — ``<system_root>/skills/<name>/SKILL.md`` is
      walked.  This is the deployed-system layout.
    * **Skill-root mode** — when ``<system_root>/SKILL.md`` exists, the
      system root itself is registered as a skill.  This lets the audit
      run against a single skill directory (e.g., the foundry meta-skill
      or any integrator-built meta-skill) without first deploying it
      under a ``skills/`` tree.

    Both modes can apply at the same time and their results are
    concatenated.
    """
    skills: list[dict[str, str]] = []

    # Skill-root mode: system_root itself is a skill.
    top_level_skill = os.path.join(system_root, FILE_SKILL_MD)
    if os.path.isfile(top_level_skill):
        skill_root_abs = os.path.abspath(system_root)
        name = os.path.basename(skill_root_abs)
        skills.append(
            {"name": name, "path": skill_root_abs, "type": "registered"}
        )
        skills.extend(_collect_capabilities(skill_root_abs, name))

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

        skills.extend(_collect_capabilities(domain_path, domain))

    return skills


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
