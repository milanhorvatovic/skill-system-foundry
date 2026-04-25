"""Tests for lib/discovery.py.

Covers ``find_skill_dirs`` discovery in both system-root mode (with
``skills/`` directory) and skill-root mode (top-level ``SKILL.md``).
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

from lib.discovery import find_skill_dirs, find_roles


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
# find_skill_dirs — skill-root mode
# ===================================================================


class FindSkillDirsSkillRootTests(unittest.TestCase):
    """Top-level ``SKILL.md`` discovery (single-skill layout)."""

    def test_top_level_skill_md_registers_root(self) -> None:
        """A SKILL.md at system_root registers system_root as a skill."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "my-meta-skill")
            write_skill_md(skill_dir, name="my-meta-skill")
            entries = find_skill_dirs(skill_dir)
        registered = [e for e in entries if e["type"] == "registered"]
        self.assertEqual(len(registered), 1)
        self.assertEqual(registered[0]["name"], "my-meta-skill")
        self.assertEqual(registered[0]["path"], os.path.abspath(skill_dir))

    def test_top_level_skill_with_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "my-meta-skill")
            write_skill_md(skill_dir, name="my-meta-skill")
            _write_capability(os.path.join(skill_dir, "capabilities", "alpha"))
            _write_capability(os.path.join(skill_dir, "capabilities", "beta"))
            entries = find_skill_dirs(skill_dir)
        names = sorted((e["name"], e["type"]) for e in entries)
        self.assertEqual(
            names,
            [
                ("alpha", "capability"),
                ("beta", "capability"),
                ("my-meta-skill", "registered"),
            ],
        )
        # Capability entries record the meta-skill as parent.
        for e in entries:
            if e["type"] == "capability":
                self.assertEqual(e["parent"], "my-meta-skill")

    def test_skill_root_and_skills_dir_coexist(self) -> None:
        """Both modes can apply at once; results are concatenated."""
        with tempfile.TemporaryDirectory() as tmp:
            outer = os.path.join(tmp, "outer-skill")
            write_skill_md(outer, name="outer-skill")
            inner = os.path.join(outer, "skills", "inner-skill")
            write_skill_md(inner, name="inner-skill")
            entries = find_skill_dirs(outer)
        names = sorted(e["name"] for e in entries if e["type"] == "registered")
        self.assertEqual(names, ["inner-skill", "outer-skill"])

    def test_no_skill_md_no_skills_dir_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(find_skill_dirs(tmp), [])


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
