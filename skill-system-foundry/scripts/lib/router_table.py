"""Router-table consistency audit.

A router skill's ``SKILL.md`` lists its capabilities in a Markdown table
whose header is ``| Capability | Trigger | Path |``.  This module
parses that table and reports drift between the router rows and the
``capabilities/`` directory.

The audit fires on any router skill — that is, any skill where either
the ``SKILL.md`` declares a router table **or** a ``capabilities/``
directory exists on disk.  When only one half is present the rule
FAILs: a router table without ``capabilities/`` means the on-disk tree
was deleted; a ``capabilities/`` directory without a router table means
the router section was removed.  Standalone skills (neither half
present) are a no-op.

Trigger column content is treated as opaque — its only audit role is to
identify the canonical 3-column header.  Cells may include the escape
sequence ``\\|`` to embed a literal pipe.  The Path column must be the
literal string ``capabilities/<name>/capability.md`` (no backticks, no
markdown link, no fragment, no leading ``./``).  The Capability column
must equal ``<name>`` from the Path column.

The router header tuple lives in ``constants.py`` (alongside
``DIR_CAPABILITIES`` and ``FILE_SKILL_MD``) — it is a structural
constant, not a tunable validation rule.
"""

import os

from .constants import (
    DIR_CAPABILITIES,
    FILE_CAPABILITY_MD,
    FILE_SKILL_MD,
    LEVEL_FAIL,
    ROUTER_HEADERS,
    ROUTER_HEADER_STRIP_CHARS,
)


_PIPE_ESCAPE_PLACEHOLDER = "\x00PIPE\x00"


def _fence_run_length(stripped: str, ch: str) -> int:
    """Count the leading run of *ch* characters at the start of *stripped*."""
    n = 0
    while n < len(stripped) and stripped[n] == ch:
        n += 1
    return n


def _strip_fenced_regions(body: str) -> str:
    """Replace fenced code blocks with blank lines.

    Keeps line numbers stable so error messages from upstream tooling
    still line up, while ensuring fenced documentation examples cannot
    shadow the canonical router table (first-table-wins).

    Recognizes both backtick (```` ``` ````) and tilde (``~~~``)
    CommonMark fences with arbitrary run length.  A fence is closed by
    a marker of the **same family** whose run length is at least the
    opener's; mixing families (opening with ```` ``` ```` and closing
    with ``~~~``) is not balanced and would leave the rest of the
    document treated as fenced.

    CommonMark indented (4-space) code blocks are **not** stripped —
    only fenced blocks are.  Author router-table examples in fenced
    blocks so they cannot shadow the canonical router.
    """
    lines = body.splitlines()
    fence_char: str | None = None
    fence_len = 0
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if fence_char is None:
            opener: str | None = None
            if stripped.startswith("```"):
                opener = "`"
            elif stripped.startswith("~~~"):
                opener = "~"
            if opener is None:
                out.append(line)
                continue
            fence_char = opener
            fence_len = _fence_run_length(stripped, fence_char)
            out.append("")
        else:
            if stripped[:1] == fence_char:
                run = _fence_run_length(stripped, fence_char)
                # Closer must match opener length and have only
                # whitespace after the run (CommonMark §4.5).
                if run >= fence_len and stripped[run:].strip() == "":
                    fence_char = None
                    fence_len = 0
            out.append("")
    return "\n".join(out)


def _split_row(line: str) -> list[str] | None:
    """Split a Markdown table row into trimmed cells.

    Honors the CommonMark ``\\|`` escape so a Trigger cell containing
    a literal pipe does not truncate the table.  Returns ``None`` if
    *line* is not a pipe-delimited row.
    """
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    inner = stripped[1:-1]
    inner = inner.replace("\\|", _PIPE_ESCAPE_PLACEHOLDER)
    return [
        cell.strip().replace(_PIPE_ESCAPE_PLACEHOLDER, "|")
        for cell in inner.split("|")
    ]


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
    return cell.strip().strip(ROUTER_HEADER_STRIP_CHARS).strip()


def _is_router_header(cells: list[str]) -> bool:
    if len(cells) != len(ROUTER_HEADERS):
        return False
    return tuple(_normalize_header_cell(c) for c in cells) == ROUTER_HEADERS


def parse_router_table(
    body: str,
) -> tuple[list[tuple[str, str, str]], list[str]] | None:
    """Return rows of the first router-shaped table in *body*.

    Returns ``(rows, parse_errors)`` where ``rows`` is a list of
    ``(capability, trigger, path)`` tuples with each cell stripped, and
    ``parse_errors`` is a list of human-readable messages for rows that
    were structurally malformed (e.g., wrong column count) but appeared
    inside the table region.  Returns ``None`` if no Markdown table
    whose header is exactly ``Capability | Trigger | Path`` (after
    stripping ``*``, backticks, and whitespace) appears in *body*.

    Mid-table rows whose column count differs from the header are
    recorded in ``parse_errors`` and skipped, but scanning continues
    so trailing valid rows still appear in ``rows``.  This prevents a
    single malformed row from masking valid ones (and producing
    misleading orphan errors downstream).

    Fenced code blocks are stripped before scanning so a documentation
    example in a ```` ```markdown ```` block cannot shadow the canonical
    router (first-table-wins).  Indented (4-space) code blocks are not
    stripped — see ``_strip_fenced_regions``.

    A header line that matches the tuple but is not followed by a
    Markdown separator row (``|---|---|---|``) does not terminate the
    scan — the parser advances past the pseudo-header and keeps looking
    for a real table.
    """
    cleaned = _strip_fenced_regions(body)
    lines = cleaned.splitlines()
    i = 0
    while i < len(lines):
        cells = _split_row(lines[i])
        if cells is not None and _is_router_header(cells):
            if i + 1 >= len(lines):
                return None
            sep_cells = _split_row(lines[i + 1])
            if sep_cells is None or not _is_separator_row(sep_cells):
                i += 1
                continue
            rows: list[tuple[str, str, str]] = []
            parse_errors: list[str] = []
            j = i + 2
            while j < len(lines):
                row_cells = _split_row(lines[j])
                if row_cells is None:
                    break
                if len(row_cells) != len(ROUTER_HEADERS):
                    parse_errors.append(
                        f"router table row at line {j + 1} has "
                        f"{len(row_cells)} columns (expected "
                        f"{len(ROUTER_HEADERS)})"
                    )
                    j += 1
                    continue
                rows.append(
                    (row_cells[0], row_cells[1], row_cells[2])
                )
                j += 1
            return rows, parse_errors
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

    Returns a list of ``(level, message)`` tuples.  Returns ``[]`` for
    standalone skills (no ``SKILL.md`` router table and no
    ``capabilities/`` directory) and when all checks pass.

    Failure modes (all FAIL):

    * ``capabilities/`` exists but ``SKILL.md`` is missing.
    * ``SKILL.md`` has a router table but ``capabilities/`` is missing.
    * ``capabilities/`` exists but ``SKILL.md`` has no router-shaped
      table.
    * A row inside the router table is structurally malformed (wrong
      number of columns).  Subsequent valid rows are still parsed.
    * Two rows declare the same capability segment (duplicate router
      entry).
    * A router row's Path cell is not the literal
      ``capabilities/<name>/capability.md``.
    * A router row's Capability cell does not equal the ``<name>``
      segment of its Path cell.  The path segment is still recorded as
      "declared" so the orphan check does not double-flag the on-disk
      directory.
    * A router row's Path does not resolve to an existing
      ``capability.md``.
    * A capability subdirectory has a ``capability.md`` but no
      matching router row.
    """
    cap_dir = os.path.join(skill_path, DIR_CAPABILITIES)
    has_cap_dir = os.path.isdir(cap_dir)

    skill_md = os.path.join(skill_path, FILE_SKILL_MD)
    has_skill_md = os.path.isfile(skill_md)

    if has_cap_dir and not has_skill_md:
        # find_skill_dirs silently drops directories without SKILL.md,
        # so no other rule reaches this case.  Flag it here; the
        # presence of capabilities/ proves the directory is meant to be
        # a router skill.
        return [(
            LEVEL_FAIL,
            f"{DIR_CAPABILITIES}/ exists but {FILE_SKILL_MD} is missing",
        )]

    parsed: tuple[list[tuple[str, str, str]], list[str]] | None = None
    if has_skill_md:
        with open(skill_md, "r", encoding="utf-8") as fh:
            content = fh.read()
        parsed = parse_router_table(content)

    if not has_cap_dir and parsed is None:
        # Standalone skill — neither half of the rule is present.
        return []

    if has_cap_dir and parsed is None:
        return [(
            LEVEL_FAIL,
            f"{FILE_SKILL_MD} has {DIR_CAPABILITIES}/ but no router "
            f"table with header 'Capability | Trigger | Path'",
        )]

    if not has_cap_dir and parsed is not None:
        return [(
            LEVEL_FAIL,
            f"{FILE_SKILL_MD} declares a router table but "
            f"{DIR_CAPABILITIES}/ is missing",
        )]

    rows, parse_errors = parsed
    findings: list[tuple[str, str]] = []
    for parse_error in parse_errors:
        findings.append((LEVEL_FAIL, parse_error))

    declared: set[str] = set()
    for capability, _trigger, path in rows:
        segment = _parse_path_cell(path)
        if segment is None:
            findings.append((
                LEVEL_FAIL,
                f"router row '{capability}' has malformed Path '{path}' "
                f"(expected literal '{DIR_CAPABILITIES}/<name>/{FILE_CAPABILITY_MD}')",
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
        if segment in declared:
            findings.append((
                LEVEL_FAIL,
                f"router has duplicate row for '{segment}'",
            ))
            continue
        declared.add(segment)
        resolved = os.path.normpath(os.path.join(skill_path, path))
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
            f"{DIR_CAPABILITIES}/{orphan}/ has no matching router row "
            f"(expected Path '{expected_path(orphan)}')",
        ))

    return findings
