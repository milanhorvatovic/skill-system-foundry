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

from lib.constants import LEVEL_FAIL, LEVEL_WARN
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


def _parse_rows(body: str) -> list[tuple[str, str, str]]:
    """Unwrap ``parse_router_table`` for tests that expect a clean parse.

    Asserts that the parser found a router table and reported no FAIL
    findings, then returns the row list.  WARN findings (e.g., the
    "additional router-shaped table" warning) are tolerated here; tests
    that need to assert on warnings call ``parse_router_table``
    directly.  Tests for the ``None`` case also call the parser
    directly.
    """
    result = parse_router_table(body)
    if result is None:
        raise AssertionError("expected a router table in body, got None")
    rows, findings = result
    fails = [f for f in findings if f[0] == LEVEL_FAIL]
    if fails:
        raise AssertionError(f"unexpected parse failures: {fails}")
    return rows


# ===================================================================
# parse_router_table
# ===================================================================


class ParseRouterTableTests(unittest.TestCase):
    def test_canonical_table_returns_rows(self) -> None:
        rows = _parse_rows(CANONICAL_TABLE)
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
        result = parse_router_table(body)
        assert result is not None
        rows, findings = result
        names = [r[0] for r in rows]
        self.assertEqual(names, ["alpha", "beta"])
        warns = [f for f in findings if f[0] == LEVEL_WARN]
        self.assertEqual(len(warns), 1)
        self.assertIn("additional router-shaped table", warns[0][1])

    def test_third_router_table_emits_second_warning(self) -> None:
        """Three canonical-headed tables → two WARN findings (one per extra)."""
        extra = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| z | x | capabilities/z/capability.md |\n"
        )
        body = "# Skill\n\n" + CANONICAL_TABLE + "\n" + extra + "\n" + extra
        result = parse_router_table(body)
        assert result is not None
        _, findings = result
        warns = [f for f in findings if f[0] == LEVEL_WARN]
        self.assertEqual(len(warns), 2)

    def test_second_table_without_separator_does_not_warn(self) -> None:
        """A pseudo-header without a real separator is not a second table."""
        body = (
            "# Skill\n\n"
            + CANONICAL_TABLE
            + "\nA pseudo header below:\n\n"
            "| Capability | Trigger | Path |\n"
            "Just text after the header, no separator.\n"
        )
        result = parse_router_table(body)
        assert result is not None
        _, findings = result
        warns = [f for f in findings if f[0] == LEVEL_WARN]
        self.assertEqual(warns, [])

    def test_fenced_second_table_does_not_warn(self) -> None:
        """A second table inside a code fence is stripped — no WARN."""
        body = (
            "# Skill\n\n"
            + CANONICAL_TABLE
            + "\n```markdown\n"
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| example | x | capabilities/example/capability.md |\n"
            "```\n"
        )
        result = parse_router_table(body)
        assert result is not None
        _, findings = result
        warns = [f for f in findings if f[0] == LEVEL_WARN]
        self.assertEqual(warns, [])

    def test_header_with_bold_and_backticks(self) -> None:
        body = (
            "| **Capability** | `Trigger` | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | capabilities/alpha/capability.md |\n"
        )
        rows = _parse_rows(body)
        self.assertEqual(rows, [("alpha", "t", "capabilities/alpha/capability.md")])

    def test_header_with_underscore_italics(self) -> None:
        """``_Capability_`` (CommonMark italic with underscores) is recognized.

        CommonMark italic emphasis can be expressed with either ``*`` or
        ``_``; the strip set must accept both so authors do not see an
        opaque "no router table" failure for underscore decoration.
        """
        body = (
            "| _Capability_ | _Trigger_ | _Path_ |\n"
            "|---|---|---|\n"
            "| alpha | t | capabilities/alpha/capability.md |\n"
        )
        rows = _parse_rows(body)
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
        rows = _parse_rows(body)
        names = [r[0] for r in rows]
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
        rows = _parse_rows(body)
        names = [r[0] for r in rows]
        self.assertEqual(names, ["alpha", "beta"])

    def test_trigger_cell_with_escaped_pipe_is_preserved(self) -> None:
        """A Trigger cell containing ``\\|`` must not truncate the table."""
        body = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | when alpha \\| beta is needed | capabilities/alpha/capability.md |\n"
            "| gamma | t | capabilities/gamma/capability.md |\n"
        )
        rows = _parse_rows(body)
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

    def test_canonical_header_with_two_cell_separator_returns_none(self) -> None:
        """A canonical 3-cell header followed by a 2-cell separator is not a router table.

        Without this guard a malformed table (e.g., authoring mistake or
        prose example) would be promoted to the canonical router and
        cause spurious failures elsewhere in the audit.
        """
        body = (
            "| Capability | Trigger | Path |\n"
            "|---|---|\n"
            "| alpha | t | capabilities/alpha/capability.md |\n"
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

    def test_malformed_path_with_existing_dir_does_not_double_flag(self) -> None:
        """A recoverable malformed Path (backticks, link wrapper, ./, #fragment)
        whose target directory exists must surface exactly one FAIL —
        the malformed Path — and not also the orphan finding.

        Otherwise a single author error produces two findings and sends
        the reader on a wrong-cause hunt.
        """
        decorations = (
            "`capabilities/alpha/capability.md`",
            "[link](capabilities/alpha/capability.md)",
            "./capabilities/alpha/capability.md",
            "capabilities/alpha/capability.md#anchor",
        )
        for decorated in decorations:
            with self.subTest(path=decorated):
                table = (
                    "| Capability | Trigger | Path |\n"
                    "|---|---|---|\n"
                    f"| alpha | t | {decorated} |\n"
                )
                with tempfile.TemporaryDirectory() as tmp:
                    _build_skill(tmp, table, capability_dirs=["alpha"])
                    findings = audit_router_table(tmp)
                msgs = [m for _, m in findings]
                self.assertTrue(
                    any("malformed Path" in m for m in msgs),
                    f"expected malformed-Path FAIL for {decorated!r}, got: {msgs}",
                )
                self.assertFalse(
                    any("no matching router row" in m for m in msgs),
                    f"orphan finding must be suppressed when the malformed "
                    f"Path is recoverable, got: {msgs}",
                )
                self.assertEqual(
                    len(findings), 1,
                    f"expected exactly one FAIL for {decorated!r}, got: {msgs}",
                )

    def test_unrecoverable_malformed_path_still_flags_orphan(self) -> None:
        """A malformed Path with no recoverable segment still surfaces the
        on-disk directory as orphan — there is no alternative signal that
        the row was meant to reference it."""
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | totally-wrong-shape |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(
            any("malformed Path" in m for m in msgs),
            f"expected malformed-Path FAIL, got: {msgs}",
        )
        self.assertTrue(
            any("capabilities/alpha/" in m and "no matching router row" in m for m in msgs),
            f"unrecoverable path leaves the on-disk dir genuinely orphan, got: {msgs}",
        )

    def test_traversal_segment_in_path_is_malformed(self) -> None:
        """A Path segment of ``.`` or ``..`` must be flagged as malformed.

        ``os.path.normpath`` would otherwise collapse such a path so it
        could resolve to an unrelated ``capability.md`` and silently
        escape the ``capabilities/<name>/`` shape the audit enforces.
        """
        for traversal in (".", ".."):
            with self.subTest(segment=traversal):
                table = (
                    "| Capability | Trigger | Path |\n"
                    "|---|---|---|\n"
                    f"| alpha | t | capabilities/{traversal}/capability.md |\n"
                )
                with tempfile.TemporaryDirectory() as tmp:
                    _build_skill(tmp, table, capability_dirs=["alpha"])
                    findings = audit_router_table(tmp)
                msgs = [m for _, m in findings]
                self.assertTrue(
                    any("malformed Path" in m for m in msgs),
                    f"expected malformed-Path FAIL for '{traversal}', got: {msgs}",
                )

    def test_backslash_segment_in_path_is_malformed(self) -> None:
        """A Path segment containing a backslash is not a single capability name."""
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | capabilities/al\\pha/capability.md |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(
            any("malformed Path" in m for m in msgs),
            f"expected malformed-Path FAIL for backslash segment, got: {msgs}",
        )

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

    def test_mid_table_malformed_row_does_not_truncate(self) -> None:
        """A malformed mid-row must surface a FAIL and not drop trailing rows.

        Regression: parser previously broke at the first wrong-cell-count
        row, dropping later valid rows and surfacing them as misleading
        orphan errors.
        """
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | t | capabilities/alpha/capability.md |\n"
            "| broken |\n"
            "| beta | t | capabilities/beta/capability.md |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha", "beta"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        # Parse error surfaces.
        self.assertTrue(
            any("has 1 columns" in m or "has 1 column" in m for m in msgs),
            f"expected wrong-column-count FAIL, got: {msgs}",
        )
        # Trailing valid row was still parsed — beta is not flagged orphan.
        self.assertFalse(
            any("capabilities/beta/" in m and "no matching router row" in m for m in msgs),
            f"trailing valid row should not be reported as orphan: {msgs}",
        )

    def test_duplicate_router_rows_fail(self) -> None:
        """Two rows declaring the same capability segment must produce a FAIL."""
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha | first  | capabilities/alpha/capability.md |\n"
            "| alpha | second | capabilities/alpha/capability.md |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha"])
            findings = audit_router_table(tmp)
        msgs = [m for _, m in findings]
        self.assertTrue(
            any("duplicate row for 'alpha'" in m for m in msgs),
            f"expected duplicate-row FAIL, got: {msgs}",
        )

    def test_empty_trigger_cell_fails(self) -> None:
        """A row with an empty Trigger cell is a structural failure.

        Trigger content is otherwise opaque, but emptiness is almost
        certainly a half-edited row, so the audit flags it.  The
        capability is still wired up correctly otherwise — only the
        empty-trigger FAIL should surface.
        """
        table = (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| alpha |  | capabilities/alpha/capability.md |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, table, capability_dirs=["alpha"])
            findings = audit_router_table(tmp)
        self.assertEqual(len(findings), 1)
        level, msg = findings[0]
        self.assertEqual(level, LEVEL_FAIL)
        self.assertIn("empty Trigger", msg)
        self.assertIn("'alpha'", msg)

    def test_second_router_table_emits_warn(self) -> None:
        """A second canonical-headed table in SKILL.md surfaces a WARN.

        The first table is still audited normally; the WARN directs
        the author to consolidate.  The skill is otherwise clean, so
        only the WARN should appear.
        """
        body = CANONICAL_TABLE + "\n## Stale\n\n" + (
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| ignored | x | capabilities/ignored/capability.md |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, body, capability_dirs=["alpha", "beta"])
            findings = audit_router_table(tmp)
        warns = [f for f in findings if f[0] == LEVEL_WARN]
        fails = [f for f in findings if f[0] == LEVEL_FAIL]
        self.assertEqual(len(warns), 1)
        self.assertIn("additional router-shaped table", warns[0][1])
        self.assertEqual(fails, [])


# ===================================================================
# _strip_fenced_regions — fence run length
# ===================================================================


class StripFencedRegionsTests(unittest.TestCase):
    """Long-fence behavior: a 4-tick fence is not closed by a 3-tick line."""

    def test_long_backtick_fence_survives_short_inner_close(self) -> None:
        """````-fenced block must not be closed by ``` inside it."""
        body = (
            "# Skill\n\n"
            "````\n"
            "```\n"  # inner short fence — must NOT close the outer
            + CANONICAL_TABLE
            + "```\n"  # still inside the outer fence
            "````\n"  # this is the real closer
            "## Capabilities\n\n"
            + CANONICAL_TABLE
        )
        rows = _parse_rows(body)
        names = [r[0] for r in rows]
        self.assertEqual(names, ["alpha", "beta"])

    def test_indented_4_space_backticks_are_not_a_fence(self) -> None:
        """A line indented 4+ spaces is an indented code block, not a fence.

        CommonMark §4.5 caps a fence opener at 0–3 leading spaces.
        A 4-space-indented run of backticks is literal content and
        must not strip the surrounding lines, so a real router table
        following such a line stays visible.
        """
        body = (
            "# Skill\n\n"
            "    ```\n"  # 4-space indent — indented code block, NOT a fence
            "    decoy line still inside the same indented block\n"
            "\n"
            "## Capabilities\n\n"
            + CANONICAL_TABLE
        )
        rows = _parse_rows(body)
        names = [r[0] for r in rows]
        self.assertEqual(names, ["alpha", "beta"])

    def test_3_space_indented_fence_is_recognized(self) -> None:
        """0–3 leading spaces on a fence opener still counts as a fence."""
        body = (
            "# Skill\n\n"
            "   ```markdown\n"  # 3-space indent — still a valid fence
            + CANONICAL_TABLE
            + "   ```\n"
        )
        self.assertIsNone(parse_router_table(body))


if __name__ == "__main__":
    unittest.main()
