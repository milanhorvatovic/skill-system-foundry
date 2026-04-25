"""Tests for lib/discovery.py.

Covers ``find_skill_dirs`` (system-root, deployed-system layout),
``find_skill_root`` (skill-root mode for meta-skill audits), and
``find_roles``.
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

from lib.discovery import find_skill_dirs, find_skill_root, find_roles


def _write_capability(cap_dir: str, body: str = "# Capability\n") -> None:
    write_text(os.path.join(cap_dir, "capability.md"), body)


# ===================================================================
# find_skill_dirs — system-root mode
# ===================================================================


class FindSkillDirsSystemRootTests(unittest.TestCase):
    """``skills/<name>/SKILL.md`` discovery (deployed-system layout)."""

    def test_empty_root_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(find_skill_dirs(tmp), [])

    def test_skills_dir_with_one_registered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "skills", "demo-skill")
            write_skill_md(skill_dir)
            entries = find_skill_dirs(tmp)
        names = [(e["name"], e["type"]) for e in entries]
        self.assertEqual(names, [("demo-skill", "registered")])

    def test_skills_dir_with_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "skills", "demo-skill")
            write_skill_md(skill_dir)
            _write_capability(os.path.join(skill_dir, "capabilities", "my-cap"))
            entries = find_skill_dirs(tmp)
        types = sorted((e["name"], e["type"]) for e in entries)
        self.assertEqual(
            types, [("demo-skill", "registered"), ("my-cap", "capability")]
        )
        cap_entry = [e for e in entries if e["type"] == "capability"][0]
        self.assertEqual(cap_entry["parent"], "demo-skill")


# ===================================================================
# find_skill_root — skill-root mode
# ===================================================================


class FindSkillRootTests(unittest.TestCase):
    """``SKILL.md`` at system_root yields a synthetic registered entry."""

    def test_top_level_skill_md_returns_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "my-meta-skill")
            write_skill_md(skill_dir, name="my-meta-skill")
            entry = find_skill_root(skill_dir)
        self.assertIsNotNone(entry)
        assert entry is not None  # for the type checker
        self.assertEqual(entry["name"], "my-meta-skill")
        self.assertEqual(entry["type"], "registered")
        self.assertEqual(entry["path"], os.path.abspath(skill_dir))

    def test_no_skill_md_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_skill_root(tmp))

    def test_only_returns_top_level_not_subdirectory_skill(self) -> None:
        """find_skill_root checks only system_root itself, not nested skills."""
        with tempfile.TemporaryDirectory() as tmp:
            inner = os.path.join(tmp, "skills", "inner-skill")
            write_skill_md(inner, name="inner-skill")
            self.assertIsNone(find_skill_root(tmp))


# ===================================================================
# find_roles
# ===================================================================


class FindRolesTests(unittest.TestCase):
    """``find_roles`` discovers role markdown files under ``roles/<group>/``."""

    def test_no_roles_dir_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(find_roles(tmp), [])

    def test_finds_role_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            role_path = os.path.join(tmp, "roles", "ops", "reviewer.md")
            write_text(role_path, "# Reviewer\n")
            entries = find_roles(tmp)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "reviewer")
        self.assertEqual(entries[0]["group"], "ops")

    def test_skips_readme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "roles", "ops")
            write_text(os.path.join(base, "README.md"), "# README\n")
            write_text(os.path.join(base, "reviewer.md"), "# Reviewer\n")
            entries = find_roles(tmp)
        names = [e["name"] for e in entries]
        self.assertEqual(names, ["reviewer"])


if __name__ == "__main__":
    unittest.main()
