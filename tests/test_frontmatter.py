"""Tests for lib/frontmatter.py.

Covers ``load_frontmatter`` round-trip behavior with line-ending
normalization — the same on-disk content with LF, CRLF, or mixed
terminators must yield byte-identical frontmatter dicts and LF-only
body strings.
"""

import os
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.frontmatter import (  # noqa: E402
    count_body_lines,
    load_frontmatter,
    parse_frontmatter,
)


def _write_bytes(content_bytes: bytes) -> str:
    """Write *content_bytes* to a temp file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".md", delete=False
    ) as fh:
        fh.write(content_bytes)
        return fh.name


class LoadFrontmatterLineEndingsTests(unittest.TestCase):
    """Line-ending normalization on file ingestion."""

    LF_CONTENT = (
        "---\n"
        "name: example\n"
        "description: short text\n"
        "---\n"
        "First body line\n"
        "Second body line\n"
    )

    def _load_with_endings(self, sep: str) -> tuple[dict | None, str, list[str]]:
        text = self.LF_CONTENT.replace("\n", sep)
        path = _write_bytes(text.encode("utf-8"))
        try:
            return load_frontmatter(path)
        finally:
            os.unlink(path)

    def test_lf_input(self) -> None:
        fm, body, findings = self._load_with_endings("\n")
        self.assertEqual(fm, {"name": "example", "description": "short text"})
        self.assertEqual(body, "First body line\nSecond body line")
        self.assertEqual(findings, [])

    def test_crlf_input_matches_lf(self) -> None:
        lf = self._load_with_endings("\n")
        crlf = self._load_with_endings("\r\n")
        self.assertEqual(crlf, lf)

    def test_cr_only_input_matches_lf(self) -> None:
        lf = self._load_with_endings("\n")
        cr = self._load_with_endings("\r")
        self.assertEqual(cr, lf)

    def test_body_contains_no_carriage_returns(self) -> None:
        _, body, _ = self._load_with_endings("\r\n")
        self.assertNotIn("\r", body)


class ParseFrontmatterTests(unittest.TestCase):
    """``parse_frontmatter`` validates in-memory content (no file read)."""

    def test_valid_content_parses(self) -> None:
        fm, body, findings = parse_frontmatter(
            "---\nname: example\n---\nBody line\n"
        )
        self.assertEqual(fm, {"name": "example"})
        self.assertEqual(body, "Body line")
        self.assertEqual(findings, [])

    def test_missing_closing_delimiter_is_parse_error(self) -> None:
        fm, _body, _findings = parse_frontmatter("---\nname: example\n")
        self.assertIsInstance(fm, dict)
        self.assertIn("_parse_error", fm)

    def test_no_frontmatter_returns_none(self) -> None:
        fm, body, findings = parse_frontmatter("# Just a heading\n")
        self.assertIsNone(fm)
        self.assertEqual(body, "# Just a heading\n")
        self.assertEqual(findings, [])

    def test_crlf_normalized(self) -> None:
        fm, body, _ = parse_frontmatter("---\r\nname: x\r\n---\r\nBody\r\n")
        self.assertEqual(fm, {"name": "x"})
        self.assertNotIn("\r", body)

    def test_matches_load_frontmatter(self) -> None:
        content = "---\nname: example\ndescription: text\n---\nBody\n"
        path = _write_bytes(content.encode("utf-8"))
        try:
            from_file = load_frontmatter(path)
        finally:
            os.unlink(path)
        self.assertEqual(parse_frontmatter(content), from_file)


class CountBodyLinesTests(unittest.TestCase):
    """``count_body_lines`` — cross-platform line counting."""

    def test_empty_returns_zero(self) -> None:
        self.assertEqual(count_body_lines(""), 0)

    def test_whitespace_only_returns_zero(self) -> None:
        self.assertEqual(count_body_lines("   \n\n"), 0)

    def test_single_line(self) -> None:
        self.assertEqual(count_body_lines("hello"), 1)

    def test_three_lines(self) -> None:
        self.assertEqual(count_body_lines("a\nb\nc"), 3)


if __name__ == "__main__":
    unittest.main()
