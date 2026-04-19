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

from lib.frontmatter import count_body_lines, load_frontmatter  # noqa: E402


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
