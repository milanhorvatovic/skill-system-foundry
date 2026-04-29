"""Tests for skill-system-foundry/scripts/lib/orphans.py.

Covers all acceptance-criteria cases from the orphan-reference audit
issue plus extras: nested capability ``references/`` orphans,
multi-skill audit-root keying, fenced-block negative cases, and
non-markdown orphans.
"""

import os
import sys
import tempfile
import unittest

from helpers import write_capability_md, write_skill_md, write_text

SCRIPTS_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "skill-system-foundry", "scripts",
    )
)

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.constants import LEVEL_WARN
from lib.orphans import find_orphan_references


# ===================================================================
# Helpers
# ===================================================================


def _build_skill(skill_dir: str, *, body: str = "# Demo\n") -> None:
    write_skill_md(skill_dir, body=body)


# ===================================================================
# Acceptance-criteria cases
# ===================================================================


class OrphanDetectionTests(unittest.TestCase):
    """Core cases listed in issue #102."""

    def test_orphan_present_warns_and_names_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", "orphan.md"),
                "# Orphan\n",
            )
            findings = find_orphan_references(skill, [])
            self.assertEqual(len(findings), 1)
            self.assertTrue(findings[0].startswith(LEVEL_WARN + ":"))
            self.assertIn("references/orphan.md", findings[0])

    def test_reachable_file_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(
                skill,
                body="See [guide](references/guide.md).\n",
            )
            write_text(
                os.path.join(skill, "references", "guide.md"),
                "# Guide\n",
            )
            self.assertEqual(find_orphan_references(skill, []), [])

    def test_allowed_orphan_skill_root_relative_suppresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", "staged.md"),
                "# Staged\n",
            )
            findings = find_orphan_references(
                skill, ["references/staged.md"],
            )
            self.assertEqual(findings, [])

    def test_empty_or_missing_references_directory_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_missing = os.path.join(tmp, "skill_missing")
            _build_skill(skill_missing)
            self.assertEqual(find_orphan_references(skill_missing, []), [])

            skill_empty = os.path.join(tmp, "skill_empty")
            _build_skill(skill_empty)
            os.makedirs(os.path.join(skill_empty, "references"))
            self.assertEqual(find_orphan_references(skill_empty, []), [])


# ===================================================================
# Extras requested in scope discussion
# ===================================================================


class NestedCapabilityReferencesTests(unittest.TestCase):
    """Files under ``capabilities/<name>/references/`` are in scope."""

    def test_unreferenced_capability_local_reference_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_capability_md(skill, "deploy")
            write_text(
                os.path.join(
                    skill, "capabilities", "deploy", "references", "stale.md",
                ),
                "# Stale\n",
            )
            findings = find_orphan_references(skill, [])
            self.assertEqual(len(findings), 1)
            self.assertIn(
                "capabilities/deploy/references/stale.md", findings[0],
            )

    def test_referenced_capability_local_reference_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_capability_md(
                skill,
                "deploy",
                body=(
                    "# Deploy\n\n"
                    "See [setup](capabilities/deploy/references/setup.md).\n"
                ),
            )
            write_text(
                os.path.join(
                    skill, "capabilities", "deploy", "references", "setup.md",
                ),
                "# Setup\n",
            )
            self.assertEqual(find_orphan_references(skill, []), [])


class MultiSkillAuditKeyingTests(unittest.TestCase):
    """Hybrid keying: ``skills/<name>/...`` is audit-root-relative."""

    def test_audit_root_relative_entry_targets_one_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_root = tmp
            foo = os.path.join(audit_root, "skills", "foo")
            bar = os.path.join(audit_root, "skills", "bar")
            _build_skill(foo)
            _build_skill(bar)
            write_text(
                os.path.join(foo, "references", "staged.md"),
                "# foo staged\n",
            )
            write_text(
                os.path.join(bar, "references", "staged.md"),
                "# bar staged\n",
            )
            allowed = ["skills/foo/references/staged.md"]

            foo_findings = find_orphan_references(
                foo, allowed,
                audit_root=audit_root,
                skill_audit_prefix="skills/foo",
            )
            self.assertEqual(foo_findings, [])

            bar_findings = find_orphan_references(
                bar, allowed,
                audit_root=audit_root,
                skill_audit_prefix="skills/bar",
            )
            self.assertEqual(len(bar_findings), 1)
            self.assertIn("skills/bar/references/staged.md", bar_findings[0])

    def test_skills_prefixed_entry_is_inert_when_audit_root_is_none(self) -> None:
        # In skill-root / single-skill mode the caller passes
        # audit_root=None.  ``skills/<name>/...`` entries have no
        # enclosing skills/ directory to disambiguate against, so
        # they must be silently skipped — never accidentally matched
        # against ``<skill_root>/skills/<name>/...``.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", "staged.md"),
                "# Staged\n",
            )
            findings = find_orphan_references(
                skill,
                ["skills/skill/references/staged.md"],
                audit_root=None,
            )
            self.assertEqual(len(findings), 1)
            self.assertIn("references/staged.md", findings[0])

    def test_skill_root_relative_entry_applies_to_every_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_root = tmp
            foo = os.path.join(audit_root, "skills", "foo")
            bar = os.path.join(audit_root, "skills", "bar")
            _build_skill(foo)
            _build_skill(bar)
            write_text(
                os.path.join(foo, "references", "staged.md"), "# foo\n",
            )
            write_text(
                os.path.join(bar, "references", "staged.md"), "# bar\n",
            )
            allowed = ["references/staged.md"]
            self.assertEqual(
                find_orphan_references(
                    foo, allowed, audit_root=audit_root,
                ),
                [],
            )
            self.assertEqual(
                find_orphan_references(
                    bar, allowed, audit_root=audit_root,
                ),
                [],
            )


class StrictSemanticsTests(unittest.TestCase):
    """References inside fenced code blocks or YAML frontmatter do
    NOT count as reachable — confirmed by case #7."""

    def test_reference_only_inside_fenced_block_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(
                skill,
                body=(
                    "# Demo\n\n"
                    "Example fence:\n\n"
                    "```\n"
                    "[guide](references/guide.md)\n"
                    "```\n"
                ),
            )
            write_text(
                os.path.join(skill, "references", "guide.md"), "# Guide\n",
            )
            findings = find_orphan_references(skill, [])
            self.assertEqual(len(findings), 1)
            self.assertIn("references/guide.md", findings[0])

    def test_reference_only_inside_frontmatter_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            write_skill_md(
                skill,
                description=(
                    "Packages a demo. Triggers when running smoke tests "
                    "via references/guide.md."
                ),
                body="# Demo\n",
            )
            write_text(
                os.path.join(skill, "references", "guide.md"), "# Guide\n",
            )
            findings = find_orphan_references(skill, [])
            self.assertEqual(len(findings), 1)
            self.assertIn("references/guide.md", findings[0])


class NonMarkdownOrphanTests(unittest.TestCase):
    """All file types under references/ are checked, not just .md (#3)."""

    def test_unreferenced_svg_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", "diagram.svg"),
                "<svg/>\n",
            )
            findings = find_orphan_references(skill, [])
            self.assertEqual(len(findings), 1)
            self.assertIn("references/diagram.svg", findings[0])

    def test_referenced_svg_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(
                skill,
                body="![diagram](references/diagram.svg)\n",
            )
            write_text(
                os.path.join(skill, "references", "diagram.svg"),
                "<svg/>\n",
            )
            self.assertEqual(find_orphan_references(skill, []), [])


# ===================================================================
# Path normalization
# ===================================================================


class WalkWarningSurfacingTests(unittest.TestCase):
    """Reachability-walk diagnostics surface as findings so audit
    consumers can see why a file appears orphan."""

    def test_broken_link_emits_warn_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(
                skill,
                body="See [missing](references/missing.md).\n",
            )
            findings = find_orphan_references(
                skill, [], skill_audit_prefix="skill",
            )
            broken = [f for f in findings if "does not exist" in f]
            self.assertEqual(len(broken), 1)
            self.assertTrue(broken[0].startswith(LEVEL_WARN + ":"))
            self.assertIn("skill", broken[0])
            self.assertIn("references/missing.md", broken[0])

    def test_surface_walk_warnings_false_suppresses_diagnostics(self) -> None:
        # validate_skill passes surface_walk_warnings=False because
        # validate_skill_references already emits broken-reference
        # findings against the same graph.  Surfacing them again
        # would double the WARN count for every broken intra-skill
        # link.  Orphan findings (the rule's actual scope) must still
        # fire — the gating only suppresses the upstream diagnostics.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(
                skill,
                body="See [missing](references/missing.md).\n",
            )
            write_text(
                os.path.join(skill, "references", "orphan.md"),
                "# Orphan\n",
            )
            findings = find_orphan_references(
                skill, [],
                skill_audit_prefix="skill",
                surface_walk_warnings=False,
            )
            self.assertFalse(
                any("does not exist" in f for f in findings),
                f"walk warnings should be suppressed, got {findings!r}",
            )
            orphan = [f for f in findings if "is unreferenced" in f]
            self.assertEqual(len(orphan), 1)
            self.assertIn("references/orphan.md", orphan[0])


class PathNormalizationTests(unittest.TestCase):
    """Allow-list entries normalize Windows separators and ./ prefixes."""

    def test_backslash_entry_matches_posix_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", "staged.md"), "# x\n",
            )
            findings = find_orphan_references(
                skill, [r"references\staged.md"],
            )
            self.assertEqual(findings, [])

    def test_dot_slash_prefix_is_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", "staged.md"), "# x\n",
            )
            findings = find_orphan_references(
                skill, ["./references/staged.md"],
            )
            self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
