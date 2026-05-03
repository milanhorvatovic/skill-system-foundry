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

from lib.constants import LEVEL_INFO, LEVEL_WARN
from lib.orphans import find_orphan_references, find_unresolved_allowed_orphans


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
        # Under the redefined path-resolution rule
        # (references/path-resolution.md), capability bodies resolve
        # links file-relative.  A capability that wants to link its
        # own local reference uses ``references/<file>.md`` and the
        # walker resolves it to
        # ``capabilities/<name>/references/<file>.md``.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_capability_md(
                skill,
                "deploy",
                body=(
                    "# Deploy\n\n"
                    "See [setup](references/setup.md).\n"
                ),
            )
            write_text(
                os.path.join(
                    skill, "capabilities", "deploy", "references", "setup.md",
                ),
                "# Setup\n",
            )
            self.assertEqual(find_orphan_references(skill, []), [])


class FileRelativeResolutionTests(unittest.TestCase):
    """The walker resolves refs file-relative (standard markdown
    semantics) per the redefined path-resolution rule
    (``references/path-resolution.md``).  Each scope (skill root and
    capability root) owns its own subgraph; capability bodies use
    ``references/<file>.md`` to reach their own local references and
    ``../../references/<file>.md`` to reach the shared skill root."""

    def test_capability_local_reference_via_file_relative_is_reachable(self) -> None:
        # A capability that wants to link its own local reference uses
        # the file-relative ``references/<file>.md`` form — the link
        # resolves under the capability root, not the skill root.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            write_skill_md(
                skill,
                body="See [deploy](capabilities/deploy/capability.md).\n",
            )
            cap_dir = os.path.join(skill, "capabilities", "deploy")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Deploy\n\nSee [steps](references/steps.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "references", "steps.md"),
                "# Steps\n",
            )
            findings = find_orphan_references(
                skill, [], skill_audit_prefix="skill",
            )
            orphan = [f for f in findings if "is unreferenced" in f]
            self.assertEqual(
                orphan, [],
                "file-relative form must reach the capability-local "
                f"reference; got: {findings!r}",
            )

    def test_top_level_reference_resolves_from_skill_md(self) -> None:
        # ``SKILL.md`` sits at the skill root, so file-relative
        # resolution coincides with skill-root-relative resolution.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            write_skill_md(
                skill,
                body="See [guide](references/guide.md).\n",
            )
            write_text(
                os.path.join(skill, "references", "guide.md"),
                "# Guide\n",
            )
            findings = find_orphan_references(
                skill, [], skill_audit_prefix="skill",
            )
            self.assertEqual(
                findings, [],
                "top-level reference from SKILL.md must reach "
                f"references/guide.md; got: {findings!r}",
            )

    def test_capability_link_resolves_file_relative_to_capability_dir(self) -> None:
        # Positive pin: a capability body that writes
        # ``references/foo.md`` resolves to
        # ``capabilities/<name>/references/foo.md`` under the
        # redefined rule (file-relative resolution from the source
        # directory).  No broken-link WARN — the file is reachable
        # under the capability scope.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            write_skill_md(
                skill,
                body="See [deploy](capabilities/deploy/capability.md).\n",
            )
            cap_dir = os.path.join(skill, "capabilities", "deploy")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Deploy\n\nSee [steps](references/steps.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "references", "steps.md"),
                "# Steps\n",
            )
            findings = find_orphan_references(
                skill, [], skill_audit_prefix="skill",
            )
            broken = [f for f in findings if "does not exist" in f]
            self.assertEqual(
                broken, [],
                "capability link 'references/steps.md' must resolve "
                "file-relative to the capability dir; expected no "
                f"broken-link findings, got: {findings!r}",
            )

    def test_capability_external_reference_via_parent_traversal(self) -> None:
        # A capability reaching the shared skill root uses
        # ``../../references/<file>.md`` — two ``..`` segments
        # (one out of the capability dir, one out of ``capabilities/``)
        # and the walker follows the link without complaint.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            write_skill_md(
                skill,
                body="See [deploy](capabilities/deploy/capability.md).\n",
            )
            cap_dir = os.path.join(skill, "capabilities", "deploy")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Deploy\n\n"
                "See [shared](../../references/shared.md).\n",
            )
            write_text(
                os.path.join(skill, "references", "shared.md"),
                "# Shared\n",
            )
            findings = find_orphan_references(
                skill, [], skill_audit_prefix="skill",
            )
            self.assertEqual(
                findings, [],
                "external reference via '../../references/shared.md' "
                f"must reach the shared root; got: {findings!r}",
            )


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


class HiddenFileOrphanTests(unittest.TestCase):
    """Hidden files and hidden subdirectories under references/ are
    audited the same as any other entry — the rule's documented
    surface is "every file under references/", and silently skipping
    dotfiles would let a stale ``references/.notes.md`` (or anything
    under a hidden subdirectory) accumulate invisibly.  Genuinely
    transient noise (``.DS_Store``, editor swap files) belongs in
    ``.gitignore`` or ``orphan_references.allowed_orphans``."""

    def test_hidden_file_under_references_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", ".notes.md"),
                "# Hidden notes\n",
            )
            findings = find_orphan_references(skill, [])
            self.assertEqual(len(findings), 1)
            self.assertIn("references/.notes.md", findings[0])

    def test_file_under_hidden_directory_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", ".draft", "stale.md"),
                "# Draft\n",
            )
            findings = find_orphan_references(skill, [])
            self.assertEqual(len(findings), 1)
            self.assertIn("references/.draft/stale.md", findings[0])

    def test_allow_list_can_suppress_hidden_orphan(self) -> None:
        # Hidden files that must remain in the tree opt out the same
        # way visible orphans do — through ``allowed_orphans``.  This
        # gives users an explicit, auditable suppression instead of
        # the previous undocumented blind spot.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", ".DS_Store"),
                "",
            )
            findings = find_orphan_references(
                skill, ["references/.DS_Store"],
            )
            self.assertEqual(findings, [])


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

    def test_parent_traversal_escaping_skill_root_emits_info_finding(self) -> None:
        # ``..`` segments are legal under the redefined rule (they are
        # how a capability reaches the shared skill root).  But a path
        # that escapes the *skill root* entirely is by definition out
        # of scope for the intra-skill reachability walk — surfaced as
        # an INFO finding so the audit can see it without flagging it
        # as broken.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(
                skill,
                body="See [escape](../escape.md).\n",
            )
            findings = find_orphan_references(
                skill, [], skill_audit_prefix="skill",
            )
            outside = [
                f for f in findings
                if "outside the skill directory" in f
                and "[path-resolution]" in f
            ]
            self.assertEqual(
                len(outside), 1,
                f"expected one out-of-skill INFO, got {findings!r}",
            )
            self.assertTrue(outside[0].startswith(LEVEL_INFO + ":"))
            self.assertIn("skill", outside[0])
            self.assertIn("../escape.md", outside[0])

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


class FindUnresolvedAllowedOrphansTests(unittest.TestCase):
    """Stale allow-list detection: entries that don't resolve to a real
    file are surfaced as INFO so the list does not silently rot."""

    def test_resolved_skill_root_relative_entry_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            write_text(
                os.path.join(skill, "references", "real.md"), "# Real\n",
            )
            self.assertEqual(
                find_unresolved_allowed_orphans(
                    ["references/real.md"], [skill], None,
                ),
                [],
            )

    def test_unresolved_skill_root_relative_entry_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            findings = find_unresolved_allowed_orphans(
                ["references/missing.md"], [skill], None,
            )
            self.assertEqual(len(findings), 1)
            self.assertTrue(findings[0].startswith(LEVEL_INFO + ":"))
            self.assertIn("references/missing.md", findings[0])

    def test_skill_root_relative_matches_any_skill(self) -> None:
        # When the entry resolves under at least one skill in the
        # audit, it is doing its job — even if other skills lack
        # the file — so no INFO is emitted.
        with tempfile.TemporaryDirectory() as tmp:
            audit = tmp
            foo = os.path.join(audit, "skills", "foo")
            bar = os.path.join(audit, "skills", "bar")
            _build_skill(foo)
            _build_skill(bar)
            write_text(
                os.path.join(foo, "references", "shared.md"), "# Shared\n",
            )
            self.assertEqual(
                find_unresolved_allowed_orphans(
                    ["references/shared.md"], [foo, bar], audit,
                ),
                [],
            )

    def test_skills_prefixed_entry_resolved_under_audit_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = tmp
            foo = os.path.join(audit, "skills", "foo")
            _build_skill(foo)
            write_text(
                os.path.join(foo, "references", "staged.md"), "# Staged\n",
            )
            self.assertEqual(
                find_unresolved_allowed_orphans(
                    ["skills/foo/references/staged.md"], [foo], audit,
                ),
                [],
            )

    def test_skills_prefixed_entry_unresolved_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = tmp
            foo = os.path.join(audit, "skills", "foo")
            _build_skill(foo)
            findings = find_unresolved_allowed_orphans(
                ["skills/foo/references/missing.md"], [foo], audit,
            )
            self.assertEqual(len(findings), 1)
            self.assertIn(
                "skills/foo/references/missing.md", findings[0],
            )

    def test_skills_prefixed_entry_inert_when_audit_root_is_none(self) -> None:
        # In skill-root mode skills/...-prefixed entries can't apply
        # (the layout has no skills/ directory).  They are silently
        # skipped from stale-detection so a config shared across
        # modes doesn't generate noise on every skill-root run.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            self.assertEqual(
                find_unresolved_allowed_orphans(
                    ["skills/foo/references/missing.md"],
                    [skill],
                    None,
                ),
                [],
            )

    def test_empty_or_blank_entries_are_skipped(self) -> None:
        # ``_normalize_path`` collapses leading "./" and whitespace;
        # a fully blank entry is dropped so it doesn't fire a
        # nonsense INFO every audit run.
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "skill")
            _build_skill(skill)
            self.assertEqual(
                find_unresolved_allowed_orphans(
                    ["", "  "], [skill], None,
                ),
                [],
            )

    def test_fully_empty_audit_returns_no_findings(self) -> None:
        # Distribution-repo / partial-audit mode: no skill roots and
        # no audit root means the audit cannot reach any skill.  An
        # allow-list entry has nothing to resolve against, but it is
        # not "stale" — it is simply out of scope for this run.  The
        # partial-audit WARN already signals the limitation; emitting
        # one INFO per allow-list entry would just be noise.
        self.assertEqual(
            find_unresolved_allowed_orphans(
                ["references/anything.md", "skills/foo/x.md"],
                [],
                None,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
