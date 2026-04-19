"""SKILL.md frontmatter extraction and body utilities."""

from .yaml_parser import parse_yaml_subset


def split_frontmatter(content: str) -> tuple[str | None, str]:
    """Split *content* into ``(frontmatter_text, body_text)``.

    Returns ``(None, content)`` when the text does not start with the
    ``---`` open marker.  When the open marker is present but the
    closing marker is missing, returns ``(content[3:], "")`` so the
    caller can surface the malformed block as a structured finding.

    This is the one true frontmatter splitter: ``load_frontmatter`` and
    the prose-YAML check both use it so delimiter rules cannot drift.
    """
    if not content.startswith("---"):
        return None, content
    try:
        end = content.index("---", 3)
    except ValueError:
        return content[3:], ""
    return content[3:end], content[end + 3:]


def load_frontmatter(filepath: str) -> tuple[dict | None, str, list[str]]:
    """Extract YAML frontmatter from a SKILL.md file.

    Returns ``(frontmatter_dict, body_string, scalar_findings)``.
    *scalar_findings* contains plain-scalar divergence findings
    (FAIL and WARN level) collected during parsing (empty list when
    none).  If no frontmatter is found, returns
    ``(None, full_content, [])``.  Parse errors are returned as a dict
    with a ``_parse_error`` key.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    frontmatter_raw, body_raw = split_frontmatter(content)
    if frontmatter_raw is None:
        return None, content, []
    if body_raw == "":
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
