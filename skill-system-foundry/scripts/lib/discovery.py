"""Component discovery: find skills and roles in a skill system."""

import os

from .constants import (
    DIR_SKILLS, DIR_CAPABILITIES, DIR_ROLES,
    FILE_SKILL_MD, FILE_README, EXT_MARKDOWN,
)


def find_skill_dirs(system_root):
    """Find all skill directories (those containing SKILL.md)."""
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
                cap_skill = os.path.join(cap_path, FILE_SKILL_MD)
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


def find_roles(system_root):
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


def check_line_count(filepath):
    """Return line count of a file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def read_file(filepath):
    """Read file content."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()
