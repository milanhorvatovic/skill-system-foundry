"""Tests for lib/router_table.py.

Covers ``parse_router_table`` and ``audit_router_table``.
"""

import os
import sys
import tempfile
import unittest

from helpers import write_text, write_skill_md

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.constants import LEVEL_FAIL
from lib.router_table import (
    audit_router_table,
    expected_path,
    parse_router_table,
)


def _write_capability(cap_dir: str) -> None:
    write_text(os.path.join(cap_dir, "capability.md"), "# Capability\n")


def _build_skill(
    skill_dir: str, table: str | None, capability_dirs: list[str],
) -> None:
    """Create a skill on disk with optional router table and capability dirs."""
    body = "# Skill\n"
    if table is not None:
        body += "\n## Capabilities\n\n" + table + "\n"
    write_skill_md(skill_dir, body=body)
    for cap in capability_dirs:
        _write_capability(os.path.join(skill_dir, "capabilities", cap))


CANONICAL_TABLE = (
    "| Capability | Trigger | Path |\n"
    "|---|---|---|\n"
    "| alpha | When alpha is needed | capabilities/alpha/capability.md |\n"
    "| beta | When beta is needed | capabilities/beta/capability.md |\n"
)


# ===================================================================
# parse_router_table
# ===================================================================


class ParseRouterTableTests(unittest.TestCase):
    def test_canonical_table_returns_rows(self) -> None:
        rows = parse_router_table(CANONICAL_TABLE)
        self.assertEqual(
            rows,
            [
                ("alpha", "When alpha is needed", "capabilities/alpha/capability.md"),
                ("beta", "When beta is needed", "capabilities/beta/capability.md"),
            ],
        )

    def test_no_table_returns_none(self) -> None:
        body = "# Skill\n\nNo tables here.\n"
        self.assertIsNone(parse_router_table(body))

    def test_only_non_router_table_returns_none(self) -> None:
        body = (
            "# Skill\n\n"
            "| Foo | Bar |\n"
            "|---|---|\n"
            "| a | b |\n"
        )
        self.assertIsNone(parse_router_table(body))

    def test_first_router_table_wins(self) -> None:
        body = (
            "# Skill\n\n"
            + CANONICAL_TABLE
            + "\n## Other\n\n"
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| ignored | x | capabilities/ignored/capability.md |\n"
        )
        rows = parse_router_table(body)
        names = [r[0] for r in rows or []]
        self.assertEqual(names, ["alpha", "beta"])

    def test_header_with_bold_and_backticks(self) -> None:
        body = (
            "| **Capability** | `Trigger` | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | capabilities/alpha/capability.md |\n"
        )
        rows = parse_router_table(body)
        self.assertEqual(rows, [("alpha", "t", "capabilities/alpha/capability.md")])

    def test_table_inside_code_fence_is_ignored(self) -> None:
        """Fenced tables are stripped so doc examples cannot shadow the canonical router."""
        body = (
            "# Skill\n\n"
            "```markdown\n"
            + CANONICAL_TABLE
            + "```\n"
        )
        self.assertIsNone(parse_router_table(body))

    def test_fenced_doc_table_does_not_shadow_real_router(self) -> None:
        """A fenced example placed before the real router must not win."""
        decoy = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| decoy | x | capabilities/decoy/capability.md |\n"
        )
        body = (
            "# Skill\n\n"
            "Example format:\n\n"
            "```markdown\n"
            + decoy
            + "```\n\n"
            "## Capabilities\n\n"
            + CANONICAL_TABLE
        )
        rows = parse_router_table(body)
        names = [r[0] for r in rows or []]
        self.assertEqual(names, ["alpha", "beta"])

    def test_tilde_fenced_table_is_ignored(self) -> None:
        """Tilde fences (``~~~``) are stripped on par with backticks."""
        body = (
            "# Skill\n\n"
            "~~~markdown\n"
            + CANONICAL_TABLE
            + "~~~\n"
        )
        self.assertIsNone(parse_router_table(body))

    def test_tilde_fenced_decoy_does_not_shadow_real_router(self) -> None:
        decoy = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| decoy | x | capabilities/decoy/capability.md |\n"
        )
        body = (
            "# Skill\n\n"
            "~~~markdown\n"
            + decoy
            + "~~~\n\n"
            "## Capabilities\n\n"
            + CANONICAL_TABLE
        )
        rows = parse_router_table(body)
        names = [r[0] for r in rows or []]
        self.assertEqual(names, ["alpha", "beta"])

    def test_trigger_cell_with_escaped_pipe_is_preserved(self) -> None:
        """A Trigger cell containing ``\\|`` must not truncate the table."""
        body = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | when alpha \\| beta is needed | capabilities/alpha/capability.md |\n"
            "| gamma | t | capabilities/gamma/capability.md |\n"
        )
        rows = parse_router_table(body)
        self.assertEqual(
            rows,
            [
                ("alpha", "when alpha | beta is needed", "capabilities/alpha/capability.md"),
                ("gamma", "t", "capabilities/gamma/capability.md"),
            ],
        )

    def test_header_without_separator_is_skipped(self) -> None:
        """A header row without a following separator is not a real table."""
        body = (
            "| Capability | Trigger | Path |\n"
            "Just text, not a separator.\n"
        )
        self.assertIsNone(parse_router_table(body))

    def test_wrong_column_order_returns_none(self) -> None:
        body = (
            "| Trigger | Capability | Path |\n"
            "|---|---|---|\n"
            "| t | alpha | capabilities/alpha/capability.md |\n"
        )
        self.assertIsNone(parse_router_table(body))

    def test_empty_body_returns_none(self) -> None:
        self.assertIsNone(parse_router_table(""))


# ===================================================================
# expected_path
# ===================================================================


class ExpectedPathTests(unittest.TestCase):
    def test_returns_canonical_path(self) -> None:
        self.assertEqual(
            expected_path("alpha"), "capabilities/alpha/capability.md"
        )


# ===================================================================
# audit_router_table — no-op cases
# ===================================================================


class AuditRouterTableNoOpTests(unittest.TestCase):
    def test_standalone_skill_no_capabilities_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_skill_md(tmp)
            self.assertEqual(audit_router_table(tmp), [])

    def test_missing_skill_md_with_capabilities_fails(self) -> None:
        """capabilities/ without SKILL.md is a router skill that lost its
        entry point — find_skill_dirs would otherwise drop it silently,
        so this rule owns the FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_capability(os.path.join(tmp, "capabilities", "alpha"))
            findings = audit_router_table(tmp)
        self.assertEqual(len(findings), 1)
        level, msg = findings[0]
        self.assertEqual(level, LEVEL_FAIL)
        self.assertIn("SKILL.md is missing", msg)

    def test_router_table_without_capabilities_dir_fails(self) -> None:
        """SKILL.md declares a router but capabilities/ tree was deleted."""
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, CANONICAL_TABLE, capability_dirs=[])
            findings = audit_router_table(tmp)
        self.assertEqual(len(findings), 1)
        level, msg = findings[0]
        self.assertEqual(level, LEVEL_FAIL)
        self.assertIn("capabilities/ is missing", msg)


# ===================================================================
# audit_router_table — clean
# ===================================================================


class AuditRouterTableCleanTests(unittest.TestCase):
    def test_clean_router_table_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, CANONICAL_TABLE, ["alpha", "beta"])
            self.assertEqual(audit_router_table(tmp), [])


# ===================================================================
# audit_router_table — failure modes
# ===================================================================


class AuditRouterTableFailureTests(unittest.TestCase):
    def test_missing_table_when_capabilities_exist_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table=None, capability_dirs=["alpha"])
            findings = audit_router_table(tmp)
        self.assertEqual(len(findings), 1)
        level, msg = findings[0]
        self.assertEqual(level, LEVEL_FAIL)
        self.assertIn("no router table", msg)

    def test_row_without_directory_fails(self) -> None:
        """A router row whose capability dir is missing fails."""
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| ghost | t | capabilities/ghost/capability.md |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            # No capability dir on disk.
            _build_skill(tmp, table, capability_dirs=[])
            # Also need a capabilities/ directory so the rule applies.
            os.makedirs(os.path.join(tmp, "capabilities"))
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(any("does not resolve" in m for m in msgs))

    def test_directory_without_row_fails(self) -> None:
        """A capability directory without a router row fails (orphan)."""
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | capabilities/alpha/capability.md |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha", "extra"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(
            any("capabilities/extra/" in m and "no matching router row" in m for m in msgs)
        )

    def test_malformed_path_with_backticks_fails(self) -> None:
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | `capabilities/alpha/capability.md` |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(any("malformed Path" in m for m in msgs))

    def test_malformed_path_with_markdown_link_fails(self) -> None:
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | [link](capabilities/alpha/capability.md) |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(any("malformed Path" in m for m in msgs))

    def test_malformed_path_with_leading_dot_slash_fails(self) -> None:
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | ./capabilities/alpha/capability.md |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(any("malformed Path" in m for m in msgs))

    def test_malformed_path_with_fragment_fails(self) -> None:
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | capabilities/alpha/capability.md#anchor |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(any("malformed Path" in m for m in msgs))

    def test_capability_path_mismatch_fails(self) -> None:
        """Capability column != path segment is a FAIL."""
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| labeled | t | capabilities/actual/capability.md |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["actual"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(
            any("does not match Path segment" in m for m in msgs)
        )
        # Path-based existence check should still pass; only the
        # mismatch finding should appear.
        self.assertEqual(len(findings), 1)


if __name__ == "__main__":
    unittest.main()
