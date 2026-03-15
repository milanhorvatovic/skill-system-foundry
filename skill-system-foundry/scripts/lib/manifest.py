"""Manifest reading, conflict detection, and text-based append operations.

Provides functions to parse an existing ``manifest.yaml``, check for
name conflicts, append new component entries, and scaffold a minimal
empty manifest.
"""

import os

from .yaml_parser import parse_yaml_subset
from .constants import (
    DIR_SKILLS,
    DIR_ROLES,
    FILE_SKILL_MD,
    EXT_MARKDOWN,
)


class ManifestParseError(Exception):
    """Raised when a manifest file cannot be parsed."""


def read_manifest(path: str) -> dict:
    """Read and parse a ``manifest.yaml`` file.

    Returns the parsed manifest as a dict.  Returns an empty dict
    when the file does not exist or is empty.

    Raises:
        ManifestParseError: When the file exists but contains
            malformed YAML that cannot be parsed.
    """
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        return {}
    try:
        # Pre-parse guard: detect top-level list syntax that the parser
        # would coerce to an empty dict, which would hide malformed input.
        first_content = next(
            (
                ln.lstrip()
                for ln in text.splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")
            ),
            "",
        )
        if first_content.startswith("- "):
            raise ManifestParseError(
                f"Failed to parse {path}: top-level YAML must be a mapping"
            )
        manifest = parse_yaml_subset(text)
        if not isinstance(manifest, dict):
            raise ManifestParseError(
                f"Failed to parse {path}: top-level YAML must be a mapping"
            )
        skills = manifest.get("skills")
        if skills is not None and skills != "" and not isinstance(skills, dict):
            raise ManifestParseError(
                f"Failed to parse {path}: 'skills' must be a mapping"
            )
        roles = manifest.get("roles")
        if roles is not None and roles != "" and not isinstance(roles, dict):
            raise ManifestParseError(
                f"Failed to parse {path}: 'roles' must be a mapping"
            )
        return manifest
    except ValueError as exc:
        raise ManifestParseError(
            f"Failed to parse {path}: {exc}"
        ) from exc


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
        # No skills: section — insert before roles: to preserve
        # canonical section order (skills before roles).
        roles_idx = _find_section_index(lines, "roles:")
        if roles_idx is not None:
            entry_parts = ("skills:\n" + entry).rstrip("\n").split("\n")
            for j, part in enumerate(entry_parts):
                lines.insert(roles_idx + j, part)
            text = "\n".join(lines)
        else:
            # No roles: section either — append at the end.
            if text and not text.endswith("\n"):
                text += "\n"
            text += "\nskills:\n" + entry
    else:
        insert_pos = _find_section_end(lines, skills_idx)
        entry_parts = entry.rstrip("\n").split("\n")
        for j, part in enumerate(entry_parts):
            lines.insert(insert_pos + j, part)
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

    entry_block = (
        f"    - name: {name}\n"
        f"      path: {DIR_ROLES}/{group}/{name}{EXT_MARKDOWN}"
    )

    lines = text.split("\n")
    roles_idx = _find_section_index(lines, "roles:")

    if roles_idx is None:
        # No roles: section — append one at the end.
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\nroles:\n  {group}:\n{entry_block}\n"
    else:
        # Look for existing group within roles section.
        group_idx = _find_group_index(lines, roles_idx, group)
        if group_idx is not None:
            insert_pos = _find_group_end(lines, group_idx)
            entry_parts = entry_block.split("\n")
            for j, part in enumerate(entry_parts):
                lines.insert(insert_pos + j, part)
            text = "\n".join(lines)
        else:
            # Group does not exist — append at end of roles section.
            insert_pos = _find_section_end(lines, roles_idx)
            group_block = f"  {group}:\n{entry_block}"
            group_parts = group_block.split("\n")
            for j, part in enumerate(group_parts):
                lines.insert(insert_pos + j, part)
            text = "\n".join(lines)

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(text)


def update_manifest_for_skill(
    manifest_path: str,
    name: str,
    *,
    router: bool = False,
) -> tuple[bool, str | None, bool]:
    """Ensure *manifest_path* exists and append a skill entry.

    Returns ``(updated, warning, created_manifest)`` where *updated*
    is True when the manifest was modified, *warning* is a
    human-readable message when a conflict prevented the update, and
    *created_manifest* is True when a new manifest file was scaffolded.
    """
    created_manifest = False
    if not os.path.isfile(manifest_path):
        scaffold_empty_manifest(manifest_path)
        created_manifest = True

    try:
        manifest = read_manifest(manifest_path)
    except ManifestParseError as exc:
        warning = f"{exc} — skipping manifest update"
        return False, warning, created_manifest

    if has_skill_conflict(manifest, name):
        warning = (
            f"Skill '{name}' already exists in "
            f"{manifest_path} — skipping manifest update"
        )
        return False, warning, created_manifest

    append_skill_entry(manifest_path, name, router=router)
    return True, None, created_manifest


def update_manifest_for_role(
    manifest_path: str,
    group: str,
    name: str,
) -> tuple[bool, str | None, bool]:
    """Ensure *manifest_path* exists and append a role entry.

    Returns ``(updated, warning, created_manifest)`` where *updated*
    is True when the manifest was modified, *warning* is a
    human-readable message when a conflict prevented the update, and
    *created_manifest* is True when a new manifest file was scaffolded.
    """
    created_manifest = False
    if not os.path.isfile(manifest_path):
        scaffold_empty_manifest(manifest_path)
        created_manifest = True

    try:
        manifest = read_manifest(manifest_path)
    except ManifestParseError as exc:
        warning = f"{exc} — skipping manifest update"
        return False, warning, created_manifest

    if has_role_conflict(manifest, group, name):
        warning = (
            f"Role '{name}' in group '{group}' already exists in "
            f"{manifest_path} — skipping manifest update"
        )
        return False, warning, created_manifest

    append_role_entry(manifest_path, group, name)
    return True, None, created_manifest


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
        if stripped == section and not line[0:1].isspace():
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
    group_indent = len(lines[group_idx]) - len(lines[group_idx].lstrip())
    i = group_idx + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue
        # Group entries are indented more than the group key.
        indent = len(line) - len(line.lstrip())
        if indent <= group_indent:
            break
        last_content = i
        i += 1
    return last_content + 1
