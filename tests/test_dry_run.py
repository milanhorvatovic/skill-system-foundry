"""Tests for lib/dry_run.py — scaffold's dry-run formatting helpers."""

import os
import sys
import unittest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.dry_run import DRY_RUN_VERB, planned_line


# ===================================================================
# planned_line()
# ===================================================================


class PlannedLineTests(unittest.TestCase):
    """Tests for planned_line()."""

    def test_uses_dry_run_verb(self) -> None:
        """The line begins with the indented dry-run verb."""
        line = planned_line("a/b/c.md")
        self.assertEqual(line, f"  {DRY_RUN_VERB}: a/b/c.md")

    def test_normalises_backslashes_to_posix(self) -> None:
        """Windows-style separators are rewritten to forward slashes."""
        line = planned_line("a\\b\\c.md")
        self.assertEqual(line, f"  {DRY_RUN_VERB}: a/b/c.md")

    def test_verb_is_would_create(self) -> None:
        """The verb constant matches scaffold's documented wording."""
        self.assertEqual(DRY_RUN_VERB, "Would create")


if __name__ == "__main__":
    unittest.main()
