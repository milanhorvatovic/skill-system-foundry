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
            "references/foo.md": False,
            "<references/foo.md>": False,
            "<references/foo.md> \"Title\"": False,
        }

        for raw_ref, expected in cases.items():
            with self.subTest(raw_ref=raw_ref):
                self.assertEqual(should_skip_reference(raw_ref), expected)


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


if __name__ == "__main__":
    unittest.main()
