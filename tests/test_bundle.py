import os
import sys
import tempfile
import unittest
from unittest import mock

from helpers import write_text


SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.bundling import (
    _copy_external_files,
    _copy_skill,
    _rewrite_markdown_content,
    postvalidate,
)
from lib.references import compute_bundle_path


class MarkdownRewriteTests(unittest.TestCase):
    def test_rewrite_matrix(self) -> None:
        rewrite_map = {
            "references/foo.md": "references/inlined/foo.md",
            "roles/reviewer.md": "roles/core/reviewer.md",
        }

        cases = {
            "See [doc](references/foo.md).": "See [doc](references/inlined/foo.md).",
            "See [doc](references/foo.md#overview).": "See [doc](references/inlined/foo.md#overview).",
            "See [doc](references/foo.md?mode=raw#overview).": "See [doc](references/inlined/foo.md?mode=raw#overview).",
            "See [doc](references/foo.md \"Guide\").": "See [doc](references/inlined/foo.md \"Guide\").",
            "See [doc](<references/foo.md#overview>).": "See [doc](<references/inlined/foo.md#overview>).",
            "See [doc](<references/foo.md?mode=raw#overview> \"Guide\").": "See [doc](<references/inlined/foo.md?mode=raw#overview> \"Guide\").",
            "Use `references/foo.md` and `roles/reviewer.md`.": "Use `references/inlined/foo.md` and `roles/core/reviewer.md`.",
            "Use `references/foo.md#overview`.": "Use `references/inlined/foo.md#overview`.",
            "Leave [doc](references/missing.md) unchanged.": "Leave [doc](references/missing.md) unchanged.",
            # Non-canonical paths: normpath fallback rewrites equivalent forms
            "See [doc](references/../references/foo.md).": "See [doc](references/inlined/foo.md).",
            "See [doc](./references/foo.md).": "See [doc](references/inlined/foo.md).",
            "Use `roles/../roles/reviewer.md`.": "Use `roles/core/reviewer.md`.",
        }

        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(_rewrite_markdown_content(source, rewrite_map), expected)

    def test_image_link_prefix_preserved(self) -> None:
        rewrite_map = {"references/foo.md": "references/inlined/foo.md"}
        source = "![image](references/foo.md)"
        expected = "![image](references/inlined/foo.md)"
        self.assertEqual(_rewrite_markdown_content(source, rewrite_map), expected)


class PostValidateTests(unittest.TestCase):
    def test_error_paths_use_forward_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(os.path.join(bundle_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(bundle_dir, "references", "guide.md"),
                "[Missing](missing.md)\n",
            )

            import lib.bundling as bundling_mod

            original_relpath = os.path.relpath

            def fake_relpath(path: str, start: str = "") -> str:
                rel = original_relpath(path, start) if start else original_relpath(path)
                return rel.replace("/", "\\")

            with mock.patch("lib.bundling.os.path.relpath", side_effect=fake_relpath), mock.patch.object(bundling_mod.os, "sep", "\\"):
                errors = postvalidate(bundle_dir)

            unresolved = [
                err for err in errors
                if "Unresolved markdown reference in bundle" in err
            ]
            self.assertEqual(len(unresolved), 1)
            self.assertIn("'references/guide.md' line 1", unresolved[0])
            self.assertNotIn("\\", unresolved[0])


class CopyExternalFilesCollisionTests(unittest.TestCase):
    def test_excluded_external_file_is_rejected(self) -> None:
        """An external file whose real path contains an excluded component."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)

            # Create a file inside a .git directory
            ext_file = os.path.join(system_root, ".git", "config")
            write_text(ext_file, "sensitive data")

            with self.assertRaises(ValueError) as cm:
                _copy_external_files(
                    {ext_file}, system_root, bundle_dir,
                    exclude_patterns=[".git"],
                )

            self.assertIn("excluded path", str(cm.exception))

    def test_external_vs_external_collision_is_rejected(self) -> None:
        """Two different external files mapping to the same bundle path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)

            # Create two files that will both classify to references/<same name>
            ext_a = os.path.join(system_root, "shared", "guide.md")
            ext_b = os.path.join(system_root, "docs", "guide.md")
            write_text(ext_a, "Guide A")
            write_text(ext_b, "Guide B")

            # Both should map to references/guide.md (non-standard dirs
            # fall back to references/<basename>).
            path_a = compute_bundle_path(ext_a, system_root)
            path_b = compute_bundle_path(ext_b, system_root)
            self.assertEqual(path_a, path_b)

            with self.assertRaises(ValueError) as cm:
                _copy_external_files({ext_a, ext_b}, system_root, bundle_dir)

            self.assertIn("Bundle path collision", str(cm.exception))

    def test_external_overwrites_internal_file_is_rejected(self) -> None:
        """An external file would overwrite a skill-internal file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            bundle_dir = os.path.join(tmpdir, "bundle")

            # Create a skill with references/guide.md
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(skill_dir, "references", "guide.md"), "Internal")

            # Simulate _copy_skill: put the skill file in the bundle
            internal_target = os.path.join(bundle_dir, "references", "guide.md")
            write_text(internal_target, "Internal")

            # Create an external file that maps to references/guide.md
            ext_file = os.path.join(system_root, "references", "guide.md")
            write_text(ext_file, "External")
            self.assertEqual(
                compute_bundle_path(ext_file, system_root), "references/guide.md"
            )

            with self.assertRaises(ValueError) as cm:
                _copy_external_files({ext_file}, system_root, bundle_dir)

            self.assertIn("overwrite skill-internal file", str(cm.exception))


class CopySkillSymlinkBoundaryTests(unittest.TestCase):
    def test_symlink_escaping_boundary_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            outside_file = os.path.join(tmpdir, "outside", "secret.txt")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(outside_file, "secret content")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create a symlink inside the skill pointing outside the root
            link_path = os.path.join(skill_dir, "secret.txt")
            try:
                os.symlink(outside_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            with self.assertRaises(ValueError) as cm:
                _copy_skill(skill_dir, bundle_dir, [], system_root)

            self.assertIn("Symlinked file escapes system boundary", str(cm.exception))

    def test_symlink_within_boundary_is_allowed(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            internal_file = os.path.join(system_root, "shared", "allowed.txt")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(internal_file, "allowed content")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create a symlink inside the skill pointing within the root
            link_path = os.path.join(skill_dir, "allowed.txt")
            try:
                os.symlink(internal_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            # Should not raise
            _copy_skill(skill_dir, bundle_dir, [], system_root)

            copied = os.path.join(bundle_dir, "allowed.txt")
            self.assertTrue(os.path.exists(copied))
            with open(copied, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "allowed content")

    def test_symlinked_dir_escaping_boundary_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            outside_dir = os.path.join(tmpdir, "outside", "data")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(outside_dir, "secret.txt"), "secret")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create a symlinked directory inside the skill pointing outside
            link_path = os.path.join(skill_dir, "data")
            try:
                os.symlink(outside_dir, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            with self.assertRaises(ValueError) as cm:
                _copy_skill(skill_dir, bundle_dir, [], system_root)

            self.assertIn("Symlinked directory escapes system boundary", str(cm.exception))

    def test_symlinked_dir_within_boundary_is_traversed(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            internal_dir = os.path.join(system_root, "shared", "docs")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(internal_dir, "guide.txt"), "guide content")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create a symlinked directory inside the skill pointing within root
            link_path = os.path.join(skill_dir, "docs")
            try:
                os.symlink(internal_dir, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            # Should not raise and should traverse the symlinked directory
            _copy_skill(skill_dir, bundle_dir, [], system_root)

            copied = os.path.join(bundle_dir, "docs", "guide.txt")
            self.assertTrue(os.path.exists(copied))
            with open(copied, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "guide content")

    def test_symlinked_dir_to_excluded_target_is_skipped(self) -> None:
        """A symlink like docs -> .git should be excluded even though
        the symlink name itself does not match any exclude pattern."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            git_dir = os.path.join(system_root, ".git")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(git_dir, "config"), "secret")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create symlink "docs" pointing to ".git" inside the root
            link_path = os.path.join(skill_dir, "docs")
            try:
                os.symlink(git_dir, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            _copy_skill(skill_dir, bundle_dir, [".git"], system_root)

            # The symlink target matches .git, so it must be excluded
            self.assertFalse(
                os.path.exists(os.path.join(bundle_dir, "docs", "config"))
            )
            # SKILL.md should still be copied
            self.assertTrue(
                os.path.exists(os.path.join(bundle_dir, "SKILL.md"))
            )


if __name__ == "__main__":
    unittest.main()
