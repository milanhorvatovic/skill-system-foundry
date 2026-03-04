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

from lib.references import find_containing_skill, should_skip_reference, strip_fragment


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


if __name__ == "__main__":
    unittest.main()
