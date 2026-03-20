"""Tests for symlink-based deployment pointer creation.

Validates that directory-level and file-level symlinks work as documented
in tool-integration.md and the deployment capability's symlink-setup.md.
"""

import os
import tempfile
import unittest


def _create_symlink(target: str, link_path: str) -> None:
    """Create a symlink, raising unittest.SkipTest on unsupported platforms."""
    if not hasattr(os, "symlink"):
        raise unittest.SkipTest("symlink is not supported on this platform")
    try:
        os.symlink(target, link_path)
    except OSError:
        raise unittest.SkipTest(
            "symlink creation is not permitted in this environment"
        )


class SymlinkCreationTests(unittest.TestCase):
    """Verify that directory-level and file-level symlinks work as documented."""

    def test_directory_level_symlink(self) -> None:
        """ln -s creates a directory symlink that resolves SKILL.md."""
        with tempfile.TemporaryDirectory() as tmp:
            # Set up canonical skill
            canonical = os.path.join(tmp, ".agents", "skills", "my-skill")
            os.makedirs(canonical)
            skill_content = "# My Skill\n"
            with open(
                os.path.join(canonical, "SKILL.md"), "w", encoding="utf-8"
            ) as f:
                f.write(skill_content)

            # Create directory-level symlink (as documented)
            pointer_parent = os.path.join(tmp, ".claude", "skills")
            os.makedirs(pointer_parent)
            link_path = os.path.join(pointer_parent, "my-skill")
            target = os.path.join("..", "..", ".agents", "skills", "my-skill")
            _create_symlink(target, link_path)

            # Verify symlink resolves
            self.assertTrue(os.path.islink(link_path))
            self.assertTrue(os.path.isdir(link_path))
            resolved_skill = os.path.join(link_path, "SKILL.md")
            self.assertTrue(os.path.isfile(resolved_skill))
            with open(resolved_skill, encoding="utf-8") as f:
                self.assertEqual(f.read(), skill_content)

    def test_file_level_symlink(self) -> None:
        """ln -s creates a file symlink that resolves SKILL.md."""
        with tempfile.TemporaryDirectory() as tmp:
            # Set up canonical skill
            canonical = os.path.join(tmp, ".agents", "skills", "my-skill")
            os.makedirs(canonical)
            skill_content = "# My Skill\n"
            with open(
                os.path.join(canonical, "SKILL.md"), "w", encoding="utf-8"
            ) as f:
                f.write(skill_content)

            # Create file-level symlink (as documented)
            pointer_dir = os.path.join(tmp, ".claude", "skills", "my-skill")
            os.makedirs(pointer_dir)
            link_path = os.path.join(pointer_dir, "SKILL.md")
            target = os.path.join(
                "..", "..", "..", ".agents", "skills", "my-skill", "SKILL.md"
            )
            _create_symlink(target, link_path)

            # Verify symlink resolves
            self.assertTrue(os.path.islink(link_path))
            self.assertTrue(os.path.isfile(link_path))
            with open(link_path, encoding="utf-8") as f:
                self.assertEqual(f.read(), skill_content)

    def test_symlink_uses_relative_path(self) -> None:
        """Symlinks must use relative paths, not absolute."""
        with tempfile.TemporaryDirectory() as tmp:
            canonical = os.path.join(tmp, ".agents", "skills", "my-skill")
            os.makedirs(canonical)
            with open(
                os.path.join(canonical, "SKILL.md"), "w", encoding="utf-8"
            ) as f:
                f.write("# Skill\n")

            pointer_parent = os.path.join(tmp, ".claude", "skills")
            os.makedirs(pointer_parent)
            link_path = os.path.join(pointer_parent, "my-skill")
            target = os.path.join("..", "..", ".agents", "skills", "my-skill")
            _create_symlink(target, link_path)

            # The symlink target should be relative (as anti-pattern docs warn)
            raw_target = os.readlink(link_path)
            self.assertFalse(
                os.path.isabs(raw_target),
                f"Symlink target should be relative, got: {raw_target}",
            )

    def test_multiple_tool_pointers_to_same_canonical(self) -> None:
        """Multiple tool directories can symlink to the same canonical skill."""
        with tempfile.TemporaryDirectory() as tmp:
            # Set up canonical skill
            canonical = os.path.join(tmp, ".agents", "skills", "my-skill")
            os.makedirs(canonical)
            skill_content = "# My Skill\n"
            with open(
                os.path.join(canonical, "SKILL.md"), "w", encoding="utf-8"
            ) as f:
                f.write(skill_content)

            # Create symlinks for multiple tools
            tools = [".claude", ".cursor", ".kiro"]
            for tool in tools:
                pointer_parent = os.path.join(tmp, tool, "skills")
                os.makedirs(pointer_parent)
                link_path = os.path.join(pointer_parent, "my-skill")
                target = os.path.join(
                    "..", "..", ".agents", "skills", "my-skill"
                )
                _create_symlink(target, link_path)

            # All resolve to the same content
            for tool in tools:
                resolved = os.path.join(
                    tmp, tool, "skills", "my-skill", "SKILL.md"
                )
                with self.subTest(tool=tool):
                    self.assertTrue(os.path.isfile(resolved))
                    with open(resolved, encoding="utf-8") as f:
                        self.assertEqual(f.read(), skill_content)


if __name__ == "__main__":
    unittest.main()
