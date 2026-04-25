"""Router-table consistency audit.

A router skill's ``SKILL.md`` lists its capabilities in a Markdown table
whose header is ``| Capability | Trigger | Path |``.  This module
parses that table and reports drift between the router rows and the
``capabilities/`` directory.

The audit fires only on skills that have a ``capabilities/`` directory.
Standalone skills (no router, no capabilities) are a no-op.

Trigger column content is treated as opaque — its only audit role is to
identify the canonical 3-column header.  The Path column must be the
literal string ``capabilities/<name>/capability.md`` (no backticks, no
markdown link, no fragment, no leading ``./``).  The Capability column
must equal ``<name>`` from the Path column.
"""

import os

from .constants import (
    DIR_CAPABILITIES,
    FILE_CAPABILITY_MD,
    FILE_SKILL_MD,
    LEVEL_FAIL,
)


ROUTER_HEADERS: tuple[str, str, str] = ("Capability", "Trigger", "Path")
HEADER_STRIP_CHARS = " *`"


def _split_row(line: str) -> list[str] | None:
    """Split a Markdown table row into trimmed cells.

    Returns ``None`` if *line* is not a pipe-delimited row.
    """
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    inner = stripped[1:-1]
    return [cell.strip() for cell in inner.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    """A separator row's cells are made of dashes, optional colons, and spaces."""
    if not cells:
        return False
    for cell in cells:
        bare = cell.replace(":", "").replace("-", "").replace(" ", "")
        if bare or "-" not in cell:
            return False
    return True


def _normalize_header_cell(cell: str) -> str:
    """Strip ``*``, backticks, and surrounding whitespace from a header cell."""
    return cell.strip().strip(HEADER_STRIP_CHARS).strip()


def _is_router_header(cells: list[str]) -> bool:
    if len(cells) != len(ROUTER_HEADERS):
        return False
    return tuple(_normalize_header_cell(c) for c in cells) == ROUTER_HEADERS


def parse_router_table(body: str) -> list[tuple[str, str, str]] | None:
    """Return rows of the first router-shaped table in *body*.

    A row is ``(capability, trigger, path)`` with each cell stripped.
    Returns ``None`` if no Markdown table whose header is exactly
    ``Capability | Trigger | Path`` (after stripping ``*``, backticks,
    and whitespace) appears in *body*.

    Code fences are *not* stripped before scanning — a router-shaped
    table inside a fenced block still counts, because an AI agent
    consuming the SKILL.md sees that content too.
    """
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        cells = _split_row(lines[i])
        if cells is not None and _is_router_header(cells):
            # Expect a separator row immediately after the header.
            if i + 1 >= len(lines):
                return None
            sep_cells = _split_row(lines[i + 1])
            if sep_cells is None or not _is_separator_row(sep_cells):
                # Not a real table — keep scanning for a later one.
                i += 1
                continue
            rows: list[tuple[str, str, str]] = []
            j = i + 2
            while j < len(lines):
                row_cells = _split_row(lines[j])
                if row_cells is None:
                    break
                if len(row_cells) != len(ROUTER_HEADERS):
                    # Malformed row — stop the table here.
                    break
                rows.append(
                    (row_cells[0], row_cells[1], row_cells[2])
                )
                j += 1
            return rows
        i += 1
    return None


def expected_path(capability_name: str) -> str:
    """Return the canonical Path-cell value for a capability name."""
    return f"{DIR_CAPABILITIES}/{capability_name}/{FILE_CAPABILITY_MD}"


def _parse_path_cell(path_cell: str) -> str | None:
    """Return the ``<name>`` segment from ``capabilities/<name>/capability.md``.

    Returns ``None`` if *path_cell* does not match the canonical literal
    shape.  Strict matching is intentional — see module docstring.
    """
    prefix = f"{DIR_CAPABILITIES}/"
    suffix = f"/{FILE_CAPABILITY_MD}"
    if not path_cell.startswith(prefix) or not path_cell.endswith(suffix):
        return None
    middle = path_cell[len(prefix):-len(suffix)]
    if not middle or "/" in middle:
        return None
    return middle


def audit_router_table(skill_path: str) -> list[tuple[str, str]]:
    """Audit the router table of the skill at *skill_path*.

    Returns a list of ``(level, message)`` tuples.  Returns ``[]`` when
    the skill has no ``capabilities/`` directory (standalone skill —
    rule does not apply) or when all checks pass.

    Failure modes (all FAIL):

    * ``capabilities/`` exists but ``SKILL.md`` has no router-shaped
      table.
    * A router row's Path cell is not the literal
      ``capabilities/<name>/capability.md``.
    * A router row's Capability cell does not equal the ``<name>``
      segment of its Path cell.
    * A router row's Path does not resolve to an existing
      ``capability.md``.
    * A capability subdirectory has a ``capability.md`` but no
      matching router row.
    """
    cap_dir = os.path.join(skill_path, DIR_CAPABILITIES)
    if not os.path.isdir(cap_dir):
        return []

    skill_md = os.path.join(skill_path, FILE_SKILL_MD)
    if not os.path.isfile(skill_md):
        # The missing-SKILL.md case is reported by other rules; do not
        # double-flag here.
        return []

    with open(skill_md, "r", encoding="utf-8") as fh:
        # Read body only — frontmatter cannot contain a router table.
        # We intentionally pass the full content to ``parse_router_table``
        # because the frontmatter delimiters ('---') are not pipe rows
        # and won't be mistaken for a header.
        content = fh.read()

    rows = parse_router_table(content)
    if rows is None:
        return [(
            LEVEL_FAIL,
            f"{FILE_SKILL_MD} has {DIR_CAPABILITIES}/ but no router "
            f"table with header 'Capability | Trigger | Path'",
        )]

    findings: list[tuple[str, str]] = []
    declared: set[str] = set()

    for capability, _trigger, path in rows:
        segment = _parse_path_cell(path)
        if segment is None:
            findings.append((
                LEVEL_FAIL,
                f"router row '{capability}' has malformed Path '{path}' "
                f"(expected '{DIR_CAPABILITIES}/<name>/{FILE_CAPABILITY_MD}')",
            ))
            continue
        if capability != segment:
            findings.append((
                LEVEL_FAIL,
                f"router row Capability '{capability}' does not match "
                f"Path segment '{segment}'",
            ))
            # Continue with the path-based name so existence/orphan
            # checks still cover the cell that is on disk.
        declared.add(segment)
        resolved = os.path.join(skill_path, path)
        if not os.path.isfile(resolved):
            findings.append((
                LEVEL_FAIL,
                f"router row '{segment}' Path does not resolve to an "
                f"existing {FILE_CAPABILITY_MD}",
            ))

    on_disk: set[str] = set()
    for entry in os.listdir(cap_dir):
        entry_path = os.path.join(cap_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        if not os.path.isfile(os.path.join(entry_path, FILE_CAPABILITY_MD)):
            continue
        on_disk.add(entry)

    for orphan in sorted(on_disk - declared):
        findings.append((
            LEVEL_FAIL,
            f"{DIR_CAPABILITIES}/{orphan}/ has no matching router row",
        ))

    return findings
