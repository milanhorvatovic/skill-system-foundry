import os
import sys
import tempfile
import unittest

from helpers import write_text


SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.references import (
    RE_TEXT_FILE_REF,
    find_containing_skill,
    scan_references,
    should_skip_reference,
    strip_fragment,
)


class StripFragmentTests(unittest.TestCase):
    def test_strip_fragment_matrix(self) -> None:
        cases = {
            "references/foo.md": "references/foo.md",
            "references/foo.md#section": "references/foo.md",
            "references/foo.md?mode=raw#section": "references/foo.md",
            "<references/foo.md#section>": "references/foo.md",
            "<references/foo.md?mode=raw#section> \"Title\"": "references/foo.md",
        }

        for raw_ref, expected in cases.items():
            with self.subTest(raw_ref=raw_ref):
                self.assertEqual(strip_fragment(raw_ref), expected)


class ShouldSkipReferenceTests(unittest.TestCase):
    def test_should_skip_reference_matrix(self) -> None:
        cases = {
            "https://example.com/doc.md": True,
            "mailto:test@example.com": True,
            "#section": True,
            "<https://example.com>": True,
            "<mailto:test@example.com>": True,
            "<ftp://files.example.com/data>": True,
            "file:///C:/docs/foo.md": True,
            "<file:///home/user/docs/foo.md>": True,
            "references/foo.md": False,
            "<references/foo.md>": False,
            "<references/foo.md> \"Title\"": False,
        }

        for raw_ref, expected in cases.items():
            with self.subTest(raw_ref=raw_ref):
                self.assertEqual(should_skip_reference(raw_ref), expected)


class TextFileRefRegexTests(unittest.TestCase):
    def test_boundary_prevents_mid_token_match(self) -> None:
        """Prefixes embedded in longer words must not match."""
        cases = {
            # Should match — standalone prefix at start or after non-word char
            "references/guide.md": ["references/guide.md"],
            " references/guide.md": ["references/guide.md"],
            "path: references/guide.md": ["references/guide.md"],
            "skills/beta/notes.md": ["skills/beta/notes.md"],
            # Should NOT match — prefix is part of a longer word
            "myreferences/guide.md": [],
            "allskills/beta/notes.md": [],
            "extra_scripts/run.py": [],
            # Should NOT match — preceded by / (part of a longer path)
            "foo/references/guide.md": [],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                matches = RE_TEXT_FILE_REF.findall(text)
                self.assertEqual(matches, expected)


class FindContainingSkillTests(unittest.TestCase):
    def test_sibling_prefix_path_is_not_treated_as_in_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "project-root")
            sibling_root = os.path.join(tmpdir, "project-root-sibling")

            write_text(os.path.join(system_root, "skills", "alpha", "SKILL.md"), "---\n---\n")
            outside_file = os.path.join(sibling_root, "skills", "beta", "doc.md")
            write_text(outside_file, "outside")

            self.assertIsNone(find_containing_skill(outside_file, system_root))

    def test_symlinked_path_to_outside_root_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            outside_skill = os.path.join(tmpdir, "outside-skill")
            link_parent = os.path.join(system_root, "skills")
            link_path = os.path.join(link_parent, "linked-skill")

            write_text(os.path.join(outside_skill, "SKILL.md"), "---\n---\n")
            write_text(os.path.join(outside_skill, "doc.md"), "content")
            os.makedirs(link_parent, exist_ok=True)

            try:
                os.symlink(outside_skill, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            linked_doc = os.path.join(link_path, "doc.md")
            self.assertIsNone(find_containing_skill(linked_doc, system_root))


class ScanReferencesTests(unittest.TestCase):
    """End-to-end tests for scan_references()."""

    def test_broken_reference_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [guide](references/nonexistent.md)\n",
            )

            result = scan_references(skill_dir, system_root)

            fails = [e for e in result["errors"] if "Broken reference" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("nonexistent.md", fails[0])

    def test_cross_skill_reference_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_a = os.path.join(system_root, "skills", "alpha")
            skill_b = os.path.join(system_root, "skills", "beta")
            write_text(os.path.join(skill_a, "SKILL.md"), "---\nname: alpha\n---\n")
            write_text(os.path.join(skill_b, "SKILL.md"), "---\nname: beta\n---\n")
            write_text(os.path.join(skill_b, "notes.md"), "Beta notes\n")
            write_text(
                os.path.join(skill_a, "doc.md"),
                "See [beta notes](../beta/notes.md)\n",
            )

            result = scan_references(skill_a, system_root)

            fails = [e for e in result["errors"] if "Cross-skill reference" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("beta", fails[0])

    def test_depth_limit_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            # Create a chain: skill -> ext_0 -> ext_1 -> ext_2
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [ext](../../references/ext_0.md)\n",
            )
            for i in range(3):
                write_text(
                    os.path.join(system_root, "references", f"ext_{i}.md"),
                    f"See [next](ext_{i + 1}.md)\n",
                )

            result = scan_references(skill_dir, system_root, max_depth=2)

            fails = [e for e in result["errors"] if "depth limit" in e]
            self.assertEqual(len(fails), 1)

    def test_cycle_between_external_docs_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [a](../../references/a.md)\n",
            )
            write_text(
                os.path.join(system_root, "references", "a.md"),
                "See [b](b.md)\n",
            )
            write_text(
                os.path.join(system_root, "references", "b.md"),
                "See [a](a.md)\n",
            )

            result = scan_references(skill_dir, system_root)

            fails = [e for e in result["errors"] if "Circular reference" in e]
            self.assertEqual(len(fails), 1)

    def test_text_detected_reference_produces_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "config.yaml"),
                "path: references/guide.md\n",
            )
            write_text(
                os.path.join(system_root, "references", "guide.md"),
                "Guide content\n",
            )

            result = scan_references(skill_dir, system_root)

            warns = [w for w in result["warnings"] if "Non-markdown" in w]
            self.assertEqual(len(warns), 1)
            self.assertIn("guide.md", warns[0])
            # The referenced file should still be in external_files
            guide = os.path.join(system_root, "references", "guide.md")
            self.assertIn(os.path.abspath(guide), result["external_files"])

    def test_valid_external_reference_collected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [role](../../roles/reviewer.md)\n",
            )
            write_text(
                os.path.join(system_root, "roles", "reviewer.md"),
                "Reviewer role\n",
            )

            result = scan_references(skill_dir, system_root)

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["warnings"], [])
            role = os.path.join(system_root, "roles", "reviewer.md")
            self.assertIn(os.path.abspath(role), result["external_files"])

    def test_no_system_root_with_external_ref_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Place skill in a flat directory with no system root markers
            # so that infer_system_root() returns None.
            skill_dir = os.path.join(tmpdir, "skill")
            ext_file = os.path.join(tmpdir, "outside.md")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [ext](../outside.md)\n",
            )
            write_text(ext_file, "Outside\n")

            # system_root=None triggers inference; with no system root
            # markers the inferred root is None, so external refs fail.
            result = scan_references(skill_dir, system_root=None)

            fails = [e for e in result["errors"] if "no system root" in e]
            self.assertEqual(len(fails), 1)


    def test_symlink_inside_skill_to_outside_target_is_internal(self) -> None:
        """A symlink living inside the skill but pointing outside should be
        classified as internal (apparent path is within the skill), so that
        _copy_skill() handles it and _copy_external_files() does not
        duplicate it."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            shared_dir = os.path.join(system_root, "shared")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            # Shared file outside the skill but within the system root.
            shared_file = os.path.join(shared_dir, "common.md")
            write_text(shared_file, "Shared content\n")
            # Symlink inside the skill pointing to the shared file.
            link_path = os.path.join(skill_dir, "refs", "common.md")
            os.makedirs(os.path.dirname(link_path), exist_ok=True)
            try:
                os.symlink(shared_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")
            # Skill doc references the symlink via its apparent path.
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [common](refs/common.md)\n",
            )

            result = scan_references(skill_dir, system_root)

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["warnings"], [])
            # The symlink target must NOT appear as an external file.
            self.assertEqual(result["external_files"], set())

    def test_symlinked_file_escaping_boundary_produces_fail(self) -> None:
        """A symlinked file in the skill tree whose real target escapes the
        allowed boundary should produce a FAIL and not be traversed."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            # File outside the system root entirely.
            outside_file = os.path.join(tmpdir, "outside", "secret.md")
            write_text(outside_file, "Secret content\n")

            # Symlink inside the skill pointing to the outside file.
            link_path = os.path.join(skill_dir, "secret.md")
            try:
                os.symlink(outside_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            result = scan_references(skill_dir, system_root)

            fails = [e for e in result["errors"] if "escapes allowed boundary" in e]
            self.assertEqual(len(fails), 1)

    def test_symlink_to_another_skill_produces_fail(self) -> None:
        """A symlink inside the skill whose real target is inside another
        skill under system_root/skills/ should produce a cross-skill FAIL
        when referenced from a markdown file."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_a = os.path.join(system_root, "skills", "alpha")
            skill_b = os.path.join(system_root, "skills", "beta")
            write_text(os.path.join(skill_b, "SKILL.md"), "---\nname: beta\n---\n")
            target_file = os.path.join(skill_b, "references", "shared.md")
            write_text(target_file, "Shared content from beta\n")

            # Symlink inside alpha pointing to a file in beta.
            link_path = os.path.join(skill_a, "references", "borrowed.md")
            os.makedirs(os.path.dirname(link_path), exist_ok=True)
            try:
                os.symlink(target_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # SKILL.md references the symlinked file — the lexical path
            # is inside the skill but the real target is in another skill.
            write_text(
                os.path.join(skill_a, "SKILL.md"),
                "---\nname: alpha\n---\nSee [shared](references/borrowed.md)\n",
            )

            result = scan_references(skill_a, system_root)

            fails = [e for e in result["errors"] if "Cross-skill" in e and "symlink" in e.lower()]
            self.assertEqual(len(fails), 1, (
                f"Expected exactly one cross-skill symlink FAIL. "
                f"Errors: {result['errors']}"
            ))

    def test_text_detected_cross_skill_reference_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_a = os.path.join(system_root, "skills", "alpha")
            skill_b = os.path.join(system_root, "skills", "beta")
            write_text(os.path.join(skill_a, "SKILL.md"), "---\nname: alpha\n---\n")
            write_text(os.path.join(skill_b, "SKILL.md"), "---\nname: beta\n---\n")
            write_text(os.path.join(skill_b, "notes.md"), "Beta notes\n")
            # Non-markdown file with a skills/ prefix reference
            write_text(
                os.path.join(skill_a, "config.yaml"),
                "ref: skills/beta/notes.md\n",
            )

            result = scan_references(skill_a, system_root)

            # Cross-skill references must be a hard FAIL even when the
            # originating file is non-markdown (text_detected).
            fails = [e for e in result["errors"] if "Cross-skill" in e]
            self.assertEqual(len(fails), 1, (
                f"Expected exactly one Cross-skill FAIL. "
                f"Errors: {result['errors']}"
            ))
            self.assertIn("beta", fails[0])


class InlineOrchestratedSkillsTests(unittest.TestCase):
    """Tests for scan_references() with inline_orchestrated_skills=True."""

    def test_cross_skill_collected_when_flag_set(self) -> None:
        """Cross-skill references are collected instead of rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing_skill = os.path.join(system_root, "skills", "testing")
            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing_skill, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing_skill, "references", "guide.md"), "Guide\n")

            # Role references the testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            # Coordinator references the role
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # No errors — cross-skill references are tolerated
            self.assertEqual(result["errors"], [])
            # The testing skill should be collected for inlining
            self.assertEqual(len(result["inlined_skills"]), 1)
            abs_testing = os.path.abspath(testing_skill)
            self.assertIn(abs_testing, result["inlined_skills"])
            self.assertEqual(result["inlined_skills"][abs_testing], "testing")
            # The role should be in external_files
            self.assertIn(os.path.abspath(role_file), result["external_files"])

    def test_cross_skill_still_rejected_without_flag(self) -> None:
        """Without the flag, cross-skill references produce FAIL as before."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing_skill = os.path.join(system_root, "skills", "testing")
            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing_skill, "SKILL.md"), "---\nname: testing\n---\n")

            # Role references the testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            result = scan_references(coordinator, system_root)

            fails = [e for e in result["errors"] if "Cross-skill reference" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("testing", fails[0])
            self.assertEqual(len(result["inlined_skills"]), 0)

    def test_inlined_skills_empty_when_no_cross_refs(self) -> None:
        """A skill with no cross-skill references has an empty inlined_skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            result = scan_references(
                skill_dir, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["inlined_skills"], {})

    def test_inlined_skill_transitive_external_deps_collected(self) -> None:
        """External files referenced by an inlined skill are collected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill references an external shared reference
            shared_guide = os.path.join(system_root, "references", "shared-guide.md")
            write_text(shared_guide, "# Shared Guide\n")
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [guide](../../references/shared-guide.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # The shared guide should be discovered as an external file
            self.assertIn(os.path.abspath(shared_guide), result["external_files"])
            # Both the role and the shared guide should be external
            self.assertIn(os.path.abspath(role_file), result["external_files"])

    def test_inlined_skill_internal_refs_not_external(self) -> None:
        """Files inside an inlined skill that reference other files in
        the same skill should not appear in external_files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has internal references between its own files
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [guide](references/test-guide.md)\n",
            )
            internal_guide = os.path.join(testing, "references", "test-guide.md")
            write_text(internal_guide, "# Internal Guide\n")

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # The internal guide should NOT be in external_files
            self.assertNotIn(os.path.abspath(internal_guide), result["external_files"])

    def test_inlined_skill_broken_ref_produces_fail(self) -> None:
        """A broken reference inside an inlined skill is still reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has a broken reference
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [missing](references/nonexistent.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            fails = [e for e in result["errors"] if "Broken reference" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("nonexistent.md", fails[0])

    def test_unreachable_file_in_inlined_skill_scanned(self) -> None:
        """A file in an inlined skill NOT referenced from SKILL.md but
        having its own external dependency should still be scanned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing SKILL.md does NOT reference the helper file
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n# Testing\n",
            )
            # But the helper file references a shared external doc
            shared_ref = os.path.join(system_root, "references", "shared-guide.md")
            write_text(shared_ref, "# Shared Guide\n")
            write_text(
                os.path.join(testing, "references", "helper.md"),
                "See [shared](../../../references/shared-guide.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # The shared guide should be discovered even though it's
            # only reachable from the unreferenced helper.md
            self.assertIn(os.path.abspath(shared_ref), result["external_files"])

    def test_unreachable_broken_ref_in_inlined_skill_reported(self) -> None:
        """A broken reference in an unreferenced file inside an inlined
        skill should still produce a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # SKILL.md is clean
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n# Testing\n",
            )
            # But an unreferenced file has a broken reference to a
            # non-existent file within the skill (using a relative path
            # that stays within the skill boundary).
            write_text(
                os.path.join(testing, "references", "broken.md"),
                "See [missing](nonexistent.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            fails = [e for e in result["errors"] if "FAIL" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("nonexistent.md", fails[0])

    def test_text_detected_cross_skill_ref_warns_when_inlining(self) -> None:
        """A text_detected cross-skill reference emits a WARN in inline mode
        because non-markdown references are not automatically rewritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing, "notes.md"), "Testing notes\n")

            # Non-markdown file with a text_detected cross-skill reference
            write_text(
                os.path.join(coordinator, "config.yaml"),
                "ref: skills/testing/notes.md\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # No hard errors — the skill is collected for inlining
            self.assertEqual(result["errors"], [])
            # But a warning about the non-rewritable reference
            warns = [w for w in result["warnings"] if "Non-markdown cross-skill" in w]
            self.assertEqual(len(warns), 1, (
                f"Expected exactly one non-markdown cross-skill WARN. "
                f"Warnings: {result['warnings']}"
            ))
            self.assertIn("testing", warns[0])
            self.assertIn("config.yaml", warns[0])
            # The testing skill should still be collected for inlining
            abs_testing = os.path.abspath(testing)
            self.assertIn(abs_testing, result["inlined_skills"])

    def test_explicit_empty_exclude_patterns_respected(self) -> None:
        """An explicit empty exclude_patterns=[] must not fall back to
        BUNDLE_EXCLUDE_PATTERNS — it should scan all files including those
        that the defaults would skip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has a file in a .git directory (normally excluded)
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n",
            )
            hidden_file = os.path.join(testing, ".git", "config.md")
            write_text(hidden_file, "See [broken](nonexistent.md)\n")

            # With default excludes, .git is skipped — no error from hidden_file
            result_default = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )
            fails_default = [e for e in result_default["errors"] if "Broken reference" in e]
            self.assertEqual(len(fails_default), 0)

            # With exclude_patterns=[], nothing is skipped — the broken ref
            # in .git/config.md should be discovered
            result_empty = scan_references(
                coordinator, system_root,
                exclude_patterns=[],
                inline_orchestrated_skills=True,
            )
            fails_empty = [e for e in result_empty["errors"] if "Broken reference" in e]
            self.assertGreaterEqual(len(fails_empty), 1, (
                f"Expected broken reference FAIL when exclude_patterns=[]. "
                f"Errors: {result_empty['errors']}"
            ))

    def test_inlined_skill_symlink_boundary_violation_produces_fail(self) -> None:
        """A symlink in an inlined skill that escapes the boundary should
        produce a FAIL instead of crashing with ValueError."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")

            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # File completely outside the system root
            outside_file = os.path.join(tmpdir, "outside", "secret.md")
            write_text(outside_file, "Secret content\n")

            # Symlink inside the testing skill pointing outside the boundary
            link_path = os.path.join(testing, "secret.md")
            try:
                os.symlink(outside_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # This must NOT raise — it should produce a FAIL entry
            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            fails = [e for e in result["errors"] if "escapes" in e.lower()]
            self.assertGreaterEqual(len(fails), 1, (
                f"Expected at least one boundary violation FAIL. "
                f"Errors: {result['errors']}"
            ))
            # Should mention the inlined skill name
            boundary_fails = [e for e in fails if "inlined skill" in e]
            self.assertGreaterEqual(len(boundary_fails), 1, (
                f"Expected boundary FAIL to mention 'inlined skill'. "
                f"Errors: {fails}"
            ))


    def test_text_detected_ref_into_already_inlined_skill_warns(self) -> None:
        """A text_detected reference into an already-collected inlined skill
        must still emit a WARN (the path won't be rewritten)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing, "notes.md"), "Testing notes\n")

            # A markdown role reference collects 'testing' for inlining first
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # A non-markdown file also references files inside 'testing'.
            # By the time this is scanned, 'testing' is already collected
            # — so it hits the "already-inlined" early-return path.
            write_text(
                os.path.join(coordinator, "config.yaml"),
                "ref: skills/testing/notes.md\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # The warning should still be emitted for the text_detected ref
            warns = [w for w in result["warnings"] if "Non-markdown cross-skill" in w]
            self.assertGreaterEqual(len(warns), 1, (
                f"Expected at least one non-markdown cross-skill WARN. "
                f"Warnings: {result['warnings']}"
            ))
            # Should mention the config.yaml source file
            config_warns = [w for w in warns if "config.yaml" in w]
            self.assertGreaterEqual(len(config_warns), 1, (
                f"Expected WARN to mention config.yaml. "
                f"Warnings: {warns}"
            ))


    def test_inlined_skill_depth_does_not_inherit_coordinator_depth(self) -> None:
        """Inlined skill scanning should start at depth 0, not inherit the
        coordinator's depth.  With max_depth=2, a coordinator at depth 1
        that discovers a skill should still scan the inlined skill's own
        2-level reference chain without hitting a false depth limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Coordinator references a role (depth 1 from coordinator)
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has a 2-level external reference chain:
            # testing/SKILL.md -> ../../references/a.md -> b.md
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [a](../../references/a.md)\n",
            )
            write_text(
                os.path.join(system_root, "references", "a.md"),
                "See [b](b.md)\n",
            )
            write_text(
                os.path.join(system_root, "references", "b.md"),
                "Final doc\n",
            )

            # With max_depth=2, if the inlined skill inherited the
            # coordinator's depth, scanning a.md (depth 2+1=3) would
            # fail.  Starting at 0 means a.md is at depth 1 and b.md
            # at depth 2 — both within limit.
            result = scan_references(
                coordinator, system_root,
                max_depth=2,
                inline_orchestrated_skills=True,
            )

            depth_fails = [e for e in result["errors"] if "depth limit" in e]
            self.assertEqual(len(depth_fails), 0, (
                f"Inlined skill scanning should start at depth 0. "
                f"Errors: {result['errors']}"
            ))
            # Both external files should be discovered
            abs_a = os.path.abspath(os.path.join(system_root, "references", "a.md"))
            abs_b = os.path.abspath(os.path.join(system_root, "references", "b.md"))
            self.assertIn(abs_a, result["external_files"])
            self.assertIn(abs_b, result["external_files"])

    def test_inlined_skill_cross_skill_symlink_detected(self) -> None:
        """A symlink inside an inlined skill that points to another skill
        should be detected as a cross-skill symlink violation, using the
        inlined skill as the context (not the coordinator)."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")
            deploy = os.path.join(system_root, "skills", "deploy")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(deploy, "SKILL.md"), "---\nname: deploy\n---\n")
            write_text(os.path.join(deploy, "doc.md"), "Deploy doc\n")

            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Symlink inside testing that points to a file in deploy
            link_path = os.path.join(testing, "refs", "deploy-doc.md")
            os.makedirs(os.path.dirname(link_path), exist_ok=True)
            try:
                os.symlink(
                    os.path.join(deploy, "doc.md"),
                    link_path,
                )
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # testing/SKILL.md references the symlink
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [deploy](refs/deploy-doc.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # The cross-skill symlink from testing -> deploy should be
            # detected using testing as the context, not coordinator.
            cross_skill_fails = [
                e for e in result["errors"]
                if "Cross-skill" in e and "symlink" in e.lower()
            ]
            self.assertGreaterEqual(len(cross_skill_fails), 1, (
                f"Expected cross-skill symlink FAIL from testing -> deploy. "
                f"Errors: {result['errors']}"
            ))

    def test_inlined_skill_internal_ref_not_flagged_as_cross_skill(self) -> None:
        """Files inside an inlined skill that reference other files within
        the same skill should be treated as internal (using the inlined
        skill as context), not misidentified as cross-skill references."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has multiple files referencing each other
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [guide](references/guide.md)\n",
            )
            write_text(
                os.path.join(testing, "references", "guide.md"),
                "See [helpers](helpers.md)\n",
            )
            write_text(
                os.path.join(testing, "references", "helpers.md"),
                "Helper content\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # No errors — internal refs within the inlined skill should
            # be handled correctly with the proper skill context.
            self.assertEqual(result["errors"], [], (
                f"Internal refs within an inlined skill should not produce "
                f"errors. Errors: {result['errors']}"
            ))
            # No cross-skill warnings about internal references
            cross_warns = [w for w in result["warnings"] if "cross-skill" in w.lower()]
            self.assertEqual(len(cross_warns), 0, (
                f"Internal refs should not produce cross-skill warnings. "
                f"Warnings: {result['warnings']}"
            ))
            # The internal files should NOT appear as external files
            abs_guide = os.path.abspath(os.path.join(testing, "references", "guide.md"))
            abs_helpers = os.path.abspath(os.path.join(testing, "references", "helpers.md"))
            self.assertNotIn(abs_guide, result["external_files"])
            self.assertNotIn(abs_helpers, result["external_files"])


    def test_coordinator_back_reference_not_inlined(self) -> None:
        """If an inlined skill references back to the coordinator, the
        coordinator must NOT be collected for inlining into itself."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill references the coordinator back
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n"
                "See [coordinator](../coordinator/SKILL.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # Only testing should be inlined, NOT the coordinator
            self.assertEqual(len(result["inlined_skills"]), 1, (
                f"Expected only 1 inlined skill (testing), not coordinator. "
                f"Inlined: {result['inlined_skills']}"
            ))
            # The inlined skill should be testing
            names = list(result["inlined_skills"].values())
            self.assertIn("testing", names)
            self.assertNotIn("coordinator", names)

    def test_symlinked_skill_reference_deduplicates(self) -> None:
        """When the same skill is referenced via a symlink and a direct
        path, it should only be collected once for inlining."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing, "doc.md"), "Test doc\n")

            # Create a symlink: skills/testing-alias -> skills/testing
            alias_path = os.path.join(system_root, "skills", "testing-alias")
            try:
                os.symlink(testing, alias_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # Two roles: one references via direct path, one via symlink
            role_a = os.path.join(system_root, "roles", "role-a.md")
            role_b = os.path.join(system_root, "roles", "role-b.md")
            write_text(
                role_a,
                "See [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                role_b,
                "See [skill](../skills/testing-alias/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [a](../../roles/role-a.md)\nSee [b](../../roles/role-b.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # Should only have 1 inlined skill (not 2)
            self.assertEqual(len(result["inlined_skills"]), 1, (
                f"Expected exactly 1 inlined skill after dedup. "
                f"Inlined: {result['inlined_skills']}"
            ))
            # The name should be the canonical directory name, not the alias
            names = list(result["inlined_skills"].values())
            self.assertIn("testing", names)
            self.assertNotIn("testing-alias", names)

    def test_alias_first_reference_uses_canonical_name(self) -> None:
        """When the first cross-skill reference is through a symlink alias,
        the capability name must still be the canonical (realpath-resolved)
        directory name, not the alias."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")

            # Create alias symlink
            alias_path = os.path.join(system_root, "skills", "testing-alias")
            try:
                os.symlink(testing, alias_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # Role references ONLY via alias — this is the first (and only)
            # reference, so it determines the inlined skill name.
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "See [skill](../skills/testing-alias/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            self.assertEqual(len(result["inlined_skills"]), 1)
            # Name must be canonical ("testing"), not the alias
            names = list(result["inlined_skills"].values())
            self.assertIn("testing", names, (
                f"Expected canonical name 'testing', got: {names}"
            ))
            self.assertNotIn("testing-alias", names, (
                f"Alias name should not appear: {names}"
            ))


if __name__ == "__main__":
    unittest.main()
