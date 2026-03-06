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


if __name__ == "__main__":
    unittest.main()
