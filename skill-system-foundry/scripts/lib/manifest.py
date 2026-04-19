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
    LEVEL_FAIL,
)

__all__ = [
    "ManifestParseError",
    "read_manifest",
    "has_skill_conflict",
    "has_role_conflict",
    "append_skill_entry",
    "append_role_entry",
    "update_manifest_for_skill",
    "update_manifest_for_role",
    "scaffold_empty_manifest",
    "has_emit_corruption",
]


class ManifestParseError(Exception):
    """Raised when a manifest file cannot be parsed."""


# Sentinel used by append helpers to mark post-write structural
# corruption so ``update_manifest_for_*`` can distinguish emit
# failure from pre-existing plain-scalar divergences that also
# carry a FAIL level.
_EMIT_CORRUPTION_MARKER = "manifest emit produced unparseable YAML"


def read_manifest(path: str, findings: list[str] | None = None) -> dict:
    """Read and parse a ``manifest.yaml`` file.

    Returns the parsed manifest as a dict.  Returns an empty dict
    when the file does not exist or is empty.

    If *findings* is a list, plain-scalar divergence findings
    produced by the YAML subset parser are appended to it on the
    successful parse path.  Structural failures raise
    ``ManifestParseError`` without touching *findings*.

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
    # When the caller asks for findings, collect them into a local list
    # and only extend the caller-provided list on the success path so
    # structural failures never mutate it.  When findings is None,
    # avoid allocating and skip plain-scalar checks entirely.
    local_findings: list[str] | None = [] if findings is not None else None
    try:
        # Collect all top-level content lines for validation
        top_level_lines = [
            ln.lstrip()
            for ln in text.splitlines()
            if ln.strip()
            and not ln.lstrip().startswith("#")
            and not ln[0:1].isspace()  # Top-level only (no leading whitespace)
        ]

        # Pre-parse guard: detect top-level list syntax that the parser
        # would coerce to an empty dict, which would hide malformed input.
        if any(ln.startswith("- ") for ln in top_level_lines):
            raise ManifestParseError(
                f"Failed to parse {path}: top-level YAML must be a mapping"
            )

        manifest = parse_yaml_subset(text, local_findings)
        if not isinstance(manifest, dict):
            raise ManifestParseError(
                f"Failed to parse {path}: top-level YAML must be a mapping"
            )

        # Reject malformed manifests that parse to empty dict despite having content
        if manifest == {} and top_level_lines:
            raise ManifestParseError(
                f"Failed to parse {path}: malformed YAML content"
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
        # Validate each role group value is a list so that append
        # operations don't silently corrupt incompatible structures.
        if isinstance(roles, dict):
            for group_name, group_val in roles.items():
                if group_val is not None and group_val != "" and not isinstance(group_val, list):
                    raise ManifestParseError(
                        f"Failed to parse {path}: "
                        f"role group '{group_name}' must be a list"
                    )
    except ValueError as exc:
        raise ManifestParseError(
            f"Failed to parse {path}: {exc}"
        ) from exc

    if findings is not None and local_findings:
        findings.extend(local_findings)
    return manifest


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
) -> list[str]:
    """Append a skill entry to the ``skills:`` section of *manifest_path*.

    Uses text-based insertion since the YAML parser is read-only.
    The entry is appended after the last non-blank line in the
    ``skills:`` block.

    Returns a list of findings produced by re-validating the post-write
    manifest with :func:`read_manifest`: plain-scalar divergences when
    the emitted YAML is parseable, or a single FAIL entry tagged with
    ``_EMIT_CORRUPTION_MARKER`` when the emit step produced
    structurally invalid YAML or violated manifest-shape invariants.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        text = f.read()

    skill_type = "router" if router else "standalone"

    lines = text.split("\n")
    skills_idx = _find_section_index(lines, "skills:")
    if skills_idx is None:
        # No skills: section — insert before roles: to preserve
        # canonical section order (skills before roles).
        # Use default 2-space indent since there's nothing to infer from.
        entry = (
            f"  {name}:\n"
            f"    canonical: {DIR_SKILLS}/{name}/{FILE_SKILL_MD}\n"
            f"    type: {skill_type}\n"
        )
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
        # Infer indentation from existing skill keys.
        key_indent = _infer_child_indent(lines, skills_idx, fallback=2)
        # Find the first skill key to infer value indent from its children.
        first_key_idx = _find_first_child_key(lines, skills_idx, key_indent)
        if first_key_idx is not None:
            val_indent = _infer_child_indent(
                lines, first_key_idx, fallback=2,
            )
        else:
            val_indent = key_indent + 2
        key_pad = " " * key_indent
        val_pad = " " * val_indent
        entry = (
            f"{key_pad}{name}:\n"
            f"{val_pad}canonical: {DIR_SKILLS}/{name}/{FILE_SKILL_MD}\n"
            f"{val_pad}type: {skill_type}\n"
        )
        insert_pos = _find_section_end(lines, skills_idx)
        entry_parts = entry.rstrip("\n").split("\n")
        for j, part in enumerate(entry_parts):
            lines.insert(insert_pos + j, part)
        text = "\n".join(lines)

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(text)

    return _collect_emit_findings(manifest_path)


def append_role_entry(
    manifest_path: str,
    group: str,
    name: str,
) -> list[str]:
    """Append a role entry to the ``roles:`` section of *manifest_path*.

    Creates the group sub-key if it does not exist.

    Returns a list of findings produced by re-validating the post-write
    manifest with :func:`read_manifest`: plain-scalar divergences when
    the emitted YAML is parseable, or a single FAIL entry tagged with
    ``_EMIT_CORRUPTION_MARKER`` when the emit step produced
    structurally invalid YAML or violated manifest-shape invariants.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.split("\n")
    roles_idx = _find_section_index(lines, "roles:")

    if roles_idx is None:
        # No roles: section — append one at the end.
        # Use default indentation since there's nothing to infer from.
        entry_block = (
            f"    - name: {name}\n"
            f"      path: {DIR_ROLES}/{group}/{name}{EXT_MARKDOWN}"
        )
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\nroles:\n  {group}:\n{entry_block}\n"
    else:
        # Look for existing group within roles section.
        group_idx = _find_group_index(lines, roles_idx, group)
        if group_idx is not None:
            # Infer entry indentation from existing children.
            entry_indent = _infer_child_indent(lines, group_idx, fallback=2)
            item_pad = " " * entry_indent
            attr_pad = " " * (entry_indent + 2)
            entry_block = (
                f"{item_pad}- name: {name}\n"
                f"{attr_pad}path: {DIR_ROLES}/{group}/{name}{EXT_MARKDOWN}"
            )
            insert_pos = _find_group_end(lines, group_idx)
            entry_parts = entry_block.split("\n")
            for j, part in enumerate(entry_parts):
                lines.insert(insert_pos + j, part)
            text = "\n".join(lines)
        else:
            # Group does not exist — infer indent from existing groups
            # and append at end of roles section.
            group_indent = _infer_child_indent(lines, roles_idx, fallback=2)
            grp_pad = " " * group_indent
            item_pad = " " * (group_indent + 2)
            attr_pad = " " * (group_indent + 4)
            entry_block = (
                f"{item_pad}- name: {name}\n"
                f"{attr_pad}path: {DIR_ROLES}/{group}/{name}{EXT_MARKDOWN}"
            )
            insert_pos = _find_section_end(lines, roles_idx)
            group_block = f"{grp_pad}{group}:\n{entry_block}"
            group_parts = group_block.split("\n")
            for j, part in enumerate(group_parts):
                lines.insert(insert_pos + j, part)
            text = "\n".join(lines)

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(text)

    return _collect_emit_findings(manifest_path)


def _collect_emit_findings(manifest_path: str) -> list[str]:
    """Re-validate the post-write manifest for divergences and shape.

    Uses :func:`read_manifest` so manifest-shape invariants (top-level
    mapping, ``skills``/``roles`` mappings, role groups as lists) are
    enforced consistently with read-time validation — covering
    structural corruption that ``parse_yaml_subset`` alone would miss.
    Plain-scalar divergence findings flow through ``read_manifest``'s
    success path; structural failures surface as a single FAIL finding
    tagged with ``_EMIT_CORRUPTION_MARKER`` so callers can distinguish
    emit corruption from pre-existing divergences.
    """
    findings: list[str] = []
    try:
        read_manifest(manifest_path, findings)
    except ManifestParseError as exc:
        findings.append(f"{LEVEL_FAIL}: {_EMIT_CORRUPTION_MARKER}: {exc}")
    return findings


def update_manifest_for_skill(
    manifest_path: str,
    name: str,
    *,
    router: bool = False,
) -> tuple[bool, str | None, bool, list[str]]:
    """Ensure *manifest_path* exists and append a skill entry.

    Returns ``(updated, warning, created_manifest, findings)`` where
    *updated* is True when the manifest was modified, *warning* is a
    human-readable message when a conflict prevented the update or
    when the emit step produced structurally invalid YAML,
    *created_manifest* is True when a new manifest file was
    scaffolded, and *findings* is a list of plain-scalar divergence
    findings produced while reading the existing manifest plus any
    additional findings returned by ``append_skill_entry`` after the
    new entry is written.  When the emitted manifest fails to parse,
    *updated* is False and *warning* describes the corruption so
    callers that ignore *findings* still see the failure.
    """
    created_manifest = False
    # Treat non-existent or empty/whitespace-only files as missing.
    needs_scaffold = not os.path.isfile(manifest_path)
    if not needs_scaffold:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            needs_scaffold = not fh.read().strip()
    if needs_scaffold:
        scaffold_empty_manifest(manifest_path)
        created_manifest = True

    findings: list[str] = []
    try:
        manifest = read_manifest(manifest_path, findings)
    except ManifestParseError as exc:
        warning = f"{exc} — skipping manifest update"
        return False, warning, created_manifest, findings

    if has_skill_conflict(manifest, name):
        warning = (
            f"Skill '{name}' already exists in "
            f"{manifest_path} — skipping manifest update"
        )
        return False, warning, created_manifest, findings

    emit_findings = append_skill_entry(manifest_path, name, router=router)
    findings.extend(emit_findings)
    if has_emit_corruption(emit_findings):
        warning = (
            f"Manifest update wrote an invalid manifest at {manifest_path} "
            f"— inspect findings and repair the file"
        )
        return False, warning, created_manifest, findings
    return True, None, created_manifest, findings


def update_manifest_for_role(
    manifest_path: str,
    group: str,
    name: str,
) -> tuple[bool, str | None, bool, list[str]]:
    """Ensure *manifest_path* exists and append a role entry.

    Returns ``(updated, warning, created_manifest, findings)`` where
    *updated* is True when the manifest was modified, *warning* is a
    human-readable message when a conflict prevented the update or
    when the emit step produced structurally invalid YAML,
    *created_manifest* is True when a new manifest file was
    scaffolded, and *findings* is a list of plain-scalar divergence
    findings produced while reading the existing manifest plus any
    additional findings returned by ``append_role_entry`` after the
    new entry is written.  When the emitted manifest fails to parse,
    *updated* is False and *warning* describes the corruption so
    callers that ignore *findings* still see the failure.
    """
    created_manifest = False
    # Treat non-existent or empty/whitespace-only files as missing.
    needs_scaffold = not os.path.isfile(manifest_path)
    if not needs_scaffold:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            needs_scaffold = not fh.read().strip()
    if needs_scaffold:
        scaffold_empty_manifest(manifest_path)
        created_manifest = True

    findings: list[str] = []
    try:
        manifest = read_manifest(manifest_path, findings)
    except ManifestParseError as exc:
        warning = f"{exc} — skipping manifest update"
        return False, warning, created_manifest, findings

    if has_role_conflict(manifest, group, name):
        warning = (
            f"Role '{name}' in group '{group}' already exists in "
            f"{manifest_path} — skipping manifest update"
        )
        return False, warning, created_manifest, findings

    emit_findings = append_role_entry(manifest_path, group, name)
    findings.extend(emit_findings)
    if has_emit_corruption(emit_findings):
        warning = (
            f"Manifest update wrote an invalid manifest at {manifest_path} "
            f"— inspect findings and repair the file"
        )
        return False, warning, created_manifest, findings
    return True, None, created_manifest, findings


def has_emit_corruption(findings: list[str]) -> bool:
    """Return True when *findings* contains an emit-corruption marker.

    Distinguishes post-write structural corruption (emitted by
    ``_collect_emit_findings`` via ``_EMIT_CORRUPTION_MARKER``) from
    pre-existing plain-scalar divergences that may also carry a
    ``FAIL`` level.  Exposed publicly so CLI entry points
    (e.g., ``scaffold``) can promote emit corruption to a hard
    failure without re-implementing the marker string.
    """
    marker = f"{LEVEL_FAIL}: {_EMIT_CORRUPTION_MARKER}"
    return any(finding.startswith(marker) for finding in findings)


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
        # Skip indented lines (not top-level)
        if line[0:1].isspace():
            continue
        # Strip inline comments and get the key part
        head = line.split("#", 1)[0].rstrip()
        if ":" in head:
            key = head.split(":", 1)[0].strip()
            if key + ":" == section:
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
        # Skip top-level comments (they don't end the section)
        if not line[0].isspace() and line.lstrip().startswith("#"):
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
    i = roles_idx + 1
    group_indent: int | None = None
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue
        # Skip top-level comments (they don't end the section)
        if not line[0].isspace():
            if line.lstrip().startswith("#"):
                i += 1
                continue
            break  # Non-comment, non-indented line ends the section

        stripped = line.lstrip()

        # Skip indented comment-only lines so they don't influence
        # indent inference or group matching.
        if stripped.startswith("#"):
            i += 1
            continue

        indent = len(line) - len(stripped)

        # Infer the indentation used for group headers under roles:.
        if group_indent is None:
            group_indent = indent

        # Check for group header with space-before-colon support
        if indent == group_indent:
            head = stripped.split("#", 1)[0].rstrip()
            if ":" in head and head.split(":", 1)[0].strip() == group:
                return i
        i += 1
    return None


def _infer_child_indent(lines: list[str], parent_idx: int, fallback: int = 2) -> int:
    """Return the indentation level used by children under a parent key.

    Scans forward from *parent_idx* to find the first non-blank child
    line and returns its indentation.  Falls back to parent indent +
    *fallback* when the parent has no existing children.
    """
    parent_indent = len(lines[parent_idx]) - len(lines[parent_idx].lstrip())
    for i in range(parent_idx + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            continue
        # Skip comment-only lines so they don't drive indent inference.
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= parent_indent:
            break
        return indent
    return parent_indent + fallback


def _find_first_child_key(
    lines: list[str], parent_idx: int, child_indent: int,
) -> int | None:
    """Return the index of the first child key at *child_indent* under *parent_idx*.

    Scans forward from *parent_idx* + 1 looking for a non-blank line
    at exactly *child_indent* indentation.  Returns ``None`` when no
    such line exists before the section ends.
    """
    parent_indent = len(lines[parent_idx]) - len(lines[parent_idx].lstrip())
    for i in range(parent_idx + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= parent_indent:
            break
        if indent == child_indent:
            return i
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
