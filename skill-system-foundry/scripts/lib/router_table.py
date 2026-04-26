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

Trigger column content is otherwise treated as opaque — its text helps
identify the canonical 3-column header, and each router row must have
a non-empty Trigger cell (an empty cell is a structural FAIL — see
``audit_router_table``).  Cells may include the escape sequence ``\\|``
to embed a literal pipe.  The Path column must be the literal string
``capabilities/<name>/capability.md`` (no backticks, no markdown link,
no fragment, no leading ``./``).  The Capability column must equal
``<name>`` from the Path column.

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
    LEVEL_WARN,
    ROUTER_HEADERS,
    ROUTER_HEADER_STRIP_CHARS,
)


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
    only fenced blocks are.  Per CommonMark §4.5, a fence opener may
    be indented 0–3 spaces; a line indented 4+ spaces is an indented
    code block and the backticks (or tildes) are literal content, so
    we leave it untouched.  Author router-table examples in fenced
    blocks so they cannot shadow the canonical router.
    """
    lines = body.splitlines()
    fence_char: str | None = None
    fence_len = 0
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if fence_char is None:
            # CommonMark §4.5: fenced code blocks accept 0–3 leading
            # spaces; 4+ spaces is an indented code block whose
            # backticks/tildes are literal content.
            if indent > 3:
                out.append(line)
                continue
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
            # A closer is also constrained to 0–3 spaces of indent
            # (CommonMark §4.5); a deeper-indented line cannot close
            # the fence and is treated as content.
            if indent <= 3 and stripped[:1] == fence_char:
                run = _fence_run_length(stripped, fence_char)
                # Closer must match opener length and have only
                # whitespace after the run.
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

    Uses a single-pass scan rather than a sentinel substitution so no
    placeholder string is ever embedded in the cell content — this
    avoids any collision with characters that happen to appear in the
    input (e.g., NUL bytes from binary-tainted clipboards).
    """
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    inner = stripped[1:-1]
    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner) and inner[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _is_separator_row(cells: list[str]) -> bool:
    """A separator row's cells are made of dashes, optional colons, and spaces.

    Also requires the cell count to match ``ROUTER_HEADERS`` so a
    malformed separator (e.g., ``|---|---|`` under the canonical
    3-column header) does not promote a non-table to the router table.
    """
    if len(cells) != len(ROUTER_HEADERS):
        return False
    for cell in cells:
        bare = cell.replace(":", "").replace("-", "").replace(" ", "")
        if bare or "-" not in cell:
            return False
    return True


def _normalize_header_cell(cell: str) -> str:
    """Strip emphasis markers, backticks, and whitespace from a header cell.

    The strip set covers both CommonMark italic forms (``*x*`` and
    ``_x_``), bold (``**x**``), and inline code (``` `x` ```).  See
    ``ROUTER_HEADER_STRIP_CHARS`` in ``constants.py``.

    The trailing ``.strip()`` is not redundant — the strip set includes
    a literal space, so ``"** Capability **"`` round-trips correctly,
    but ``"* Capability *"`` exposes inner spaces only after the
    asterisks are removed; the second strip cleans those up.
    """
    return cell.strip().strip(ROUTER_HEADER_STRIP_CHARS).strip()


def _is_router_header(cells: list[str]) -> bool:
    if len(cells) != len(ROUTER_HEADERS):
        return False
    return tuple(_normalize_header_cell(c) for c in cells) == ROUTER_HEADERS


def parse_router_table(
    body: str,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]] | None:
    """Return rows of the first router-shaped table in *body*.

    Returns ``(rows, findings)`` where ``rows`` is a list of
    ``(capability, trigger, path)`` tuples with each cell stripped, and
    ``findings`` is a list of ``(level, message)`` tuples — ``LEVEL_FAIL``
    for structural row malformations inside the matched table, and
    ``LEVEL_WARN`` when a second canonical-headed table is found later
    in the body.  Returns ``None`` if no Markdown table whose header is
    exactly ``Capability | Trigger | Path`` (after stripping ``*``,
    underscores, backticks, and whitespace — see
    ``ROUTER_HEADER_STRIP_CHARS``) appears in *body*.

    Mid-table rows whose column count differs from the header are
    recorded as FAIL findings and skipped, but scanning continues so
    trailing valid rows still appear in ``rows``.  This prevents a
    single malformed row from masking valid ones (and producing
    misleading orphan errors downstream).

    Only the first router-shaped table is parsed (first-table-wins),
    but the rest of the body is scanned for additional canonical
    headers paired with valid separator rows.  Each additional table
    emits a ``LEVEL_WARN`` finding pointing to its line number — the
    audit was designed to catch drift, and a silently ignored second
    table is exactly the failure mode that defeats it.  The parser
    deliberately does not parse rows from the second table; the warning
    is enough to direct the author to consolidate.

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
            findings: list[tuple[str, str]] = []
            j = i + 2
            while j < len(lines):
                row_cells = _split_row(lines[j])
                if row_cells is None:
                    break
                if len(row_cells) != len(ROUTER_HEADERS):
                    findings.append((
                        LEVEL_FAIL,
                        f"router table row at line {j + 1} has "
                        f"{len(row_cells)} columns (expected "
                        f"{len(ROUTER_HEADERS)})",
                    ))
                    j += 1
                    continue
                rows.append(
                    (row_cells[0], row_cells[1], row_cells[2])
                )
                j += 1
            findings.extend(_scan_extra_router_tables(lines, j))
            return rows, findings
        i += 1
    return None


def _scan_extra_router_tables(
    lines: list[str], start: int,
) -> list[tuple[str, str]]:
    """Emit a WARN per additional canonical-headed table after *start*.

    Detects a second (third, ...) router-shaped header followed by a
    valid separator.  Does not parse rows — the warning's purpose is to
    direct the author back to the canonical first table; row contents
    are not authoritative once duplicated.
    """
    findings: list[tuple[str, str]] = []
    k = start
    while k < len(lines):
        cells = _split_row(lines[k])
        if cells is not None and _is_router_header(cells):
            if k + 1 < len(lines):
                sep_cells = _split_row(lines[k + 1])
                if sep_cells is not None and _is_separator_row(sep_cells):
                    findings.append((
                        LEVEL_WARN,
                        f"additional router-shaped table found at line "
                        f"{k + 1}; only the first is audited — "
                        f"consolidate or remove the extra table",
                    ))
                    k += 2
                    continue
        k += 1
    return findings


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
    if (
        not middle
        or "/" in middle
        or "\\" in middle
        or middle in (".", "..")
    ):
        return None
    return middle


def _recover_segment(path_cell: str) -> str | None:
    """Return a best-effort ``<name>`` segment when the strict parser fails.

    Strips common author decorations — backticks, the ``[text](url)``
    markdown link wrapper, leading ``./``, and a trailing ``#fragment``
    — then re-runs the strict parser.  Returns ``None`` if nothing
    recoverable is left.

    Shape validation is delegated entirely to ``_parse_path_cell`` (the
    final ``return``) — this helper only handles decoration stripping.
    Pathological inputs (e.g., embedded parentheses) are rejected by
    the strict re-parse rather than by this function, so a future
    contributor can extend the decoration set without re-deriving the
    canonical-path semantics.

    The audit uses the recovered segment to suppress the orphan check
    so a single author error (e.g., wrapping the path in backticks)
    surfaces as exactly one FAIL ("malformed Path") instead of also
    triggering "no matching router row" for a directory the row was
    clearly trying to reference.
    """
    candidate = path_cell.strip()
    # Backticks: ``` `path` ```
    if candidate.startswith("`") and candidate.endswith("`"):
        candidate = candidate[1:-1].strip()
    # Markdown link: ``[text](path)``
    if candidate.startswith("[") and candidate.endswith(")"):
        bracket_end = candidate.find("](")
        if bracket_end != -1:
            candidate = candidate[bracket_end + 2:-1].strip()
    # Leading ``./``
    if candidate.startswith("./"):
        candidate = candidate[2:]
    # Fragment: ``path#anchor``
    hash_pos = candidate.find("#")
    if hash_pos != -1:
        candidate = candidate[:hash_pos]
    return _parse_path_cell(candidate)


def audit_router_table(skill_path: str) -> list[tuple[str, str]]:
    """Audit the router table of the skill at *skill_path*.

    Returns a list of ``(level, message)`` tuples.  Returns ``[]`` for
    standalone skills (no ``SKILL.md`` router table and no
    ``capabilities/`` directory) and when all checks pass.

    Messages are skill-relative — the caller (e.g.,
    ``audit_skill_system.py``) is responsible for prefixing the
    skill name when surfacing findings.  Do not embed the skill name
    into the messages here.

    Failure modes, in emission order:

    * (FAIL) ``capabilities/`` exists but ``SKILL.md`` is missing.
    * (FAIL) ``capabilities/`` exists but ``SKILL.md`` has no
      router-shaped table.
    * (FAIL) ``SKILL.md`` has a router table but ``capabilities/`` is
      missing.
    * (FAIL) A row inside the router table is structurally malformed
      (wrong number of columns).  Subsequent valid rows are still
      parsed.
    * (WARN) A second (or later) canonical-headed router table appears
      in ``SKILL.md``.  Only the first is audited; the warning directs
      the author to consolidate.  Emitted before the per-row audit
      checks (empty Trigger, malformed Path, duplicate row, missing
      target, orphan directory) — parse-row malformation FAILs from
      the first table still appear ahead of the WARN because they are
      emitted by ``parse_router_table`` itself.
    * (FAIL) A router row's Trigger cell is empty.  Trigger content is
      otherwise opaque, but emptiness is a structural failure (a
      half-edited row).
    * (FAIL) A router row's Path cell is not the literal
      ``capabilities/<name>/capability.md``.
    * (FAIL) A router row's Capability cell does not equal the
      ``<name>`` segment of its Path cell.  The path segment is still
      recorded as "declared" so the orphan check does not double-flag
      the on-disk directory.
    * (FAIL) Two rows declare the same capability segment (duplicate
      router entry).  Detected only when both rows have parseable Path
      cells — two rows whose Paths both fail ``_parse_path_cell``
      already each surface a "malformed Path" FAIL, so the duplicate is
      not silently lost; it is reported as two independent malformed
      rows rather than one duplicate.
    * (FAIL) A router row's Path does not resolve to an existing
      ``capability.md``.
    * (FAIL) A capability subdirectory has a ``capability.md`` but no
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

    parsed: tuple[
        list[tuple[str, str, str]], list[tuple[str, str]]
    ] | None = None
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

    rows, parse_findings = parsed
    findings: list[tuple[str, str]] = list(parse_findings)

    declared: set[str] = set()
    for capability, trigger, path in rows:
        if not trigger:
            findings.append((
                LEVEL_FAIL,
                f"router row '{capability}' has an empty Trigger cell",
            ))
        segment = _parse_path_cell(path)
        if segment is None:
            findings.append((
                LEVEL_FAIL,
                f"router row '{capability}' has malformed Path '{path}' "
                f"(expected literal '{expected_path('<name>')}')",
            ))
            # Recover a best-effort segment so the orphan check does not
            # double-flag a directory the malformed row clearly
            # references (e.g., "./capabilities/alpha/capability.md").
            recovered = _recover_segment(path)
            if recovered is not None:
                declared.add(recovered)
                # A malformed Path can ALSO point at a missing target.
                # Run the existence check against the canonical
                # ``capabilities/<recovered>/capability.md`` so the
                # author sees both problems in one audit pass instead
                # of fixing the decoration only to learn next run that
                # the target file is missing too.
                recovered_path = os.path.normpath(
                    os.path.join(skill_path, expected_path(recovered))
                )
                if not os.path.isfile(recovered_path):
                    findings.append((
                        LEVEL_FAIL,
                        f"router row '{recovered}' Path does not resolve "
                        f"to an existing {FILE_CAPABILITY_MD}",
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
            # The first occurrence already ran the existence check
            # below; both rows resolve to the same path so a second
            # ``os.path.isfile`` would just repeat the same answer.
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
