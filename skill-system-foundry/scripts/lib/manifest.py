"""Manifest reading, conflict detection, and text-based append operations.

Provides functions to parse an existing ``manifest.yaml``, check for
name conflicts, append new component entries, and scaffold a minimal
empty manifest from the bundled template.
"""

import os

from .yaml_parser import parse_yaml_subset
from .constants import (
    DIR_SKILLS,
    DIR_ROLES,
    FILE_SKILL_MD,
    EXT_MARKDOWN,
)


def read_manifest(path: str) -> dict:
    """Read and parse a ``manifest.yaml`` file.

    Returns the parsed manifest as a dict.  Returns an empty dict
    when the file does not exist or is empty.
    """
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        return {}
    return parse_yaml_subset(text)


def has_skill_conflict(manifest: dict, name: str) -> bool:
    """Return True if *name* already exists under the ``skills:`` section."""
    skills = manifest.get("skills")
    if not isinstance(skills, dict):
        return False
    return name in skills


def has_role_conflict(manifest: dict, group: str, name: str) -> bool:
    """Return True if a role with *name* exists in *group* under ``roles:``."""
    roles = manifest.get("roles")
    if not isinstance(roles, dict):
        return False
    group_entries = roles.get(group)
    if not isinstance(group_entries, list):
        return False
    for entry in group_entries:
        if isinstance(entry, dict) and entry.get("name") == name:
            return True
    return False


def append_skill_entry(
    manifest_path: str,
    name: str,
    *,
    router: bool = False,
) -> None:
    """Append a skill entry to the ``skills:`` section of *manifest_path*.

    Uses text-based insertion since the YAML parser is read-only.
    The entry is appended after the last non-blank line in the
    ``skills:`` block.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        text = f.read()

    skill_type = "router" if router else "standalone"
    entry = (
        f"  {name}:\n"
        f"    canonical: {DIR_SKILLS}/{name}/{FILE_SKILL_MD}\n"
        f"    type: {skill_type}\n"
    )

    lines = text.split("\n")
    skills_idx = _find_section_index(lines, "skills:")
    if skills_idx is None:
        # No skills: section — append one at the end.
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\nskills:\n" + entry
    else:
        insert_pos = _find_section_end(lines, skills_idx)
        lines.insert(insert_pos, entry.rstrip("\n"))
        text = "\n".join(lines)

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(text)


def append_role_entry(
    manifest_path: str,
    group: str,
    name: str,
) -> None:
    """Append a role entry to the ``roles:`` section of *manifest_path*.

    Creates the group sub-key if it does not exist.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        text = f.read()

    entry_lines = (
        f"    - name: {name}\n"
        f"      path: {DIR_ROLES}/{group}/{name}{EXT_MARKDOWN}"
    )

    lines = text.split("\n")
    roles_idx = _find_section_index(lines, "roles:")

    if roles_idx is None:
        # No roles: section — append one at the end.
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\nroles:\n  {group}:\n{entry_lines}\n"
    else:
        # Look for existing group within roles section.
        group_idx = _find_group_index(lines, roles_idx, group)
        if group_idx is not None:
            insert_pos = _find_group_end(lines, group_idx)
            lines.insert(insert_pos, entry_lines)
            text = "\n".join(lines)
        else:
            # Group does not exist — append at end of roles section.
            insert_pos = _find_section_end(lines, roles_idx)
            group_block = f"  {group}:\n{entry_lines}"
            lines.insert(insert_pos, group_block)
            text = "\n".join(lines)

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(text)


def scaffold_empty_manifest(manifest_path: str) -> None:
    """Create a minimal empty manifest at *manifest_path*.

    Produces a clean manifest with empty ``skills:`` and ``roles:``
    sections, suitable for appending entries.
    """
    os.makedirs(os.path.dirname(manifest_path) or ".", exist_ok=True)
    content = (
        "# Skill System Manifest\n"
        "\n"
        "skills:\n"
        "\n"
        "roles:\n"
    )
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(content)


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------


def _find_section_index(lines: list[str], section: str) -> int | None:
    """Return the line index of a top-level *section* key, or None."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match only top-level keys (no leading whitespace).
        if stripped == section and (not line or not line[0].isspace()):
            return i
    return None


def _find_section_end(lines: list[str], section_idx: int) -> int:
    """Return the insert position after the last content line of a section.

    Walks forward from *section_idx* + 1 while lines are indented or
    blank, returning the position just after the last non-blank
    indented line.
    """
    last_content = section_idx
    i = section_idx + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue
        if line[0].isspace():
            last_content = i
            i += 1
        else:
            break
    return last_content + 1


def _find_group_index(
    lines: list[str], roles_idx: int, group: str,
) -> int | None:
    """Return the line index of a group key within the roles section."""
    target = f"  {group}:"
    i = roles_idx + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue
        if not line[0].isspace():
            break
        if line.rstrip() == target:
            return i
        i += 1
    return None


def _find_group_end(lines: list[str], group_idx: int) -> int:
    """Return the insert position after the last entry in a group."""
    last_content = group_idx
    i = group_idx + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue
        # Group entries are indented more than the group key (2 spaces).
        indent = len(line) - len(line.lstrip())
        group_indent = len(lines[group_idx]) - len(lines[group_idx].lstrip())
        if indent <= group_indent:
            break
        last_content = i
        i += 1
    return last_content + 1
