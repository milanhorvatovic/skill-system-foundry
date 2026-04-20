"""SKILL.md frontmatter extraction and body utilities.

Line endings in the on-disk file are normalized to LF immediately after
``f.read()`` so the returned ``body`` is LF-only regardless of how the
file was checked out — the prose-YAML extractor and any other body
consumer can split on ``\\n`` without ferrying the original endings
through downstream processors.
"""

from .yaml_parser import parse_yaml_subset


def split_frontmatter(content: str) -> tuple[str | None, str | None]:
    """Split *content* into ``(frontmatter_text, body_text)``.

    Delimiter detection is line-based: the first line must be exactly
    ``---`` and the closing delimiter must be a standalone ``---``
    line.  This avoids matching a ``---`` substring inside the YAML
    value space (for example, inside a block scalar).

    Returns:
    - ``(None, content)`` when the first line is not the ``---`` open
      marker (no frontmatter present).
    - ``(frontmatter_text, body_text)`` when both delimiters are
      present; ``body_text`` may be the empty string when the closing
      delimiter is the final line and there is no body content.
    - ``(frontmatter_text, None)`` when the opening marker is present
      but the closing marker is missing.  ``body_text`` is ``None``
      (not ``""``) so callers can distinguish this malformed case from
      a legitimately empty body.

    This is the one true frontmatter splitter: ``load_frontmatter`` and
    the prose-YAML check both use it so delimiter rules cannot drift.
    CRLF input is handled transparently via ``splitlines(keepends=True)``.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None, content
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            return "".join(lines[1:index]), "".join(lines[index + 1:])
    return "".join(lines[1:]), None


def load_frontmatter(filepath: str) -> tuple[dict | None, str, list[str]]:
    """Extract YAML frontmatter from a SKILL.md file.

    Returns ``(frontmatter_dict, body_string, scalar_findings)``.
    *scalar_findings* contains plain-scalar divergence findings
    (FAIL and WARN level) collected during parsing (empty list when
    none).  If no frontmatter is found, returns
    ``(None, full_content, [])``.  Parse errors are returned as a dict
    with a ``_parse_error`` key.

    Input line endings are normalized to LF before any further
    processing, so both the frontmatter and the returned ``body`` use
    LF-only terminators (see module docstring).
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    content = content.replace("\r\n", "\n").replace("\r", "\n")

    frontmatter_raw, body_raw = split_frontmatter(content)
    if frontmatter_raw is None:
        return None, content, []
    if body_raw is None:
        return (
            {"_parse_error": "No closing '---' delimiter in frontmatter"},
            frontmatter_raw,
            [],
        )

    frontmatter_str = frontmatter_raw.strip()
    body = body_raw.strip()

    try:
        findings: list[str] = []
        frontmatter = parse_yaml_subset(frontmatter_str, findings)
    except (ValueError, KeyError) as e:
        return {"_parse_error": str(e)}, body, []

    return frontmatter, body, findings


def count_body_lines(body: str) -> int:
    """Count lines in the SKILL.md body (after frontmatter).

    Returns 0 for empty/whitespace-only body, otherwise the number
    of lines using splitlines() for cross-platform compatibility.
    """
    if not body or not body.strip():
        return 0
    return len(body.splitlines())
