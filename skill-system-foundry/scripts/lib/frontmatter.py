"""SKILL.md frontmatter extraction and body utilities."""

from .yaml_parser import parse_yaml_subset


def load_frontmatter(filepath: str) -> tuple[dict | None, str]:
    """Extract YAML frontmatter from a SKILL.md file.

    Returns (frontmatter_dict, body_string). If no frontmatter is found,
    returns (None, full_content). Parse errors are returned as a dict
    with a '_parse_error' key.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        return None, content

    try:
        end = content.index("---", 3)
    except ValueError:
        return {"_parse_error": "No closing '---' delimiter in frontmatter"}, content[3:]

    frontmatter_str = content[3:end].strip()
    body = content[end + 3 :].strip()

    try:
        frontmatter = parse_yaml_subset(frontmatter_str)
    except (ValueError, KeyError) as e:
        return {"_parse_error": str(e)}, body

    return frontmatter, body


def count_body_lines(body: str) -> int:
    """Count lines in the SKILL.md body (after frontmatter).

    Returns 0 for empty/whitespace-only body, otherwise the number
    of lines using splitlines() for cross-platform compatibility.
    """
    if not body or not body.strip():
        return 0
    return len(body.splitlines())
