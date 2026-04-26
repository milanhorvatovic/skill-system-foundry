"""Tests for lib/discovery.py.

Covers ``find_skill_dirs`` (system-root, deployed-system layout),
``find_skill_root`` (skill-root mode for meta-skill audits),
``find_router_audit_targets`` (union of the above plus capability-only
directories), and ``find_roles``.
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

from lib.discovery import (
    find_roles,
    find_router_audit_targets,
    find_skill_dirs,
    find_skill_root,
)


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
        # Path shape mirrors the caller's ``system_root`` (matches
        # ``find_skill_dirs``); the basename is computed from the
        # absolute path so callers passing "." still get a real name.
        self.assertEqual(entry["path"], skill_dir)

    def test_relative_path_is_preserved(self) -> None:
        """find_skill_root must not abspath-promote the caller's path."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "my-meta-skill")
            write_skill_md(skill_dir, name="my-meta-skill")
            saved_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                entry = find_skill_root("my-meta-skill")
            finally:
                os.chdir(saved_cwd)
        assert entry is not None
        self.assertEqual(entry["path"], "my-meta-skill")
        # name still resolves correctly even with a relative path.
        self.assertEqual(entry["name"], "my-meta-skill")

    def test_dot_path_resolves_name_from_abspath(self) -> None:
        """When called with ``"."`` the name comes from the resolved abspath."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "my-meta-skill")
            write_skill_md(skill_dir, name="my-meta-skill")
            saved_cwd = os.getcwd()
            try:
                os.chdir(skill_dir)
                entry = find_skill_root(".")
            finally:
                os.chdir(saved_cwd)
        assert entry is not None
        self.assertEqual(entry["name"], "my-meta-skill")
        self.assertEqual(entry["path"], ".")

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
# find_router_audit_targets — union of registered, skill-root, and
# capability-only directories
# ===================================================================


class FindRouterAuditTargetsTests(unittest.TestCase):
    def test_empty_root_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(find_router_audit_targets(tmp), [])

    def test_includes_registered_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_skill_md(os.path.join(tmp, "skills", "alpha"), name="alpha")
            write_skill_md(os.path.join(tmp, "skills", "beta"), name="beta")
            names = sorted(t["name"] for t in find_router_audit_targets(tmp))
        self.assertEqual(names, ["alpha", "beta"])

    def test_includes_skill_root_when_top_level_skill_md_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "my-meta-skill")
            write_skill_md(skill_dir, name="my-meta-skill")
            names = [t["name"] for t in find_router_audit_targets(skill_dir)]
        self.assertEqual(names, ["my-meta-skill"])

    def test_includes_capability_only_directory_without_skill_md(self) -> None:
        """A skills/<name>/ with capabilities/ but no SKILL.md must surface."""
        with tempfile.TemporaryDirectory() as tmp:
            ghost_dir = os.path.join(tmp, "skills", "ghost")
            _write_capability(os.path.join(ghost_dir, "capabilities", "alpha"))
            names = [t["name"] for t in find_router_audit_targets(tmp)]
        self.assertEqual(names, ["ghost"])

    def test_does_not_double_count_registered_with_capabilities(self) -> None:
        """A skill that has both SKILL.md and capabilities/ appears once."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "skills", "alpha")
            write_skill_md(skill_dir, name="alpha")
            _write_capability(os.path.join(skill_dir, "capabilities", "cap"))
            targets = find_router_audit_targets(tmp)
        names = [t["name"] for t in targets]
        self.assertEqual(names, ["alpha"])

    def test_skips_files_that_are_not_directories_under_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "skills"))
            write_text(os.path.join(tmp, "skills", "stray.md"), "# stray\n")
            self.assertEqual(find_router_audit_targets(tmp), [])

    def test_returns_union_when_top_level_skill_and_skills_tree_coexist(self) -> None:
        """A directory that is itself a skill *and* hosts a skills/ tree
        (e.g., an integrator's meta-skill kept alongside deployed skills)
        must surface every audit target — the meta-skill at the top
        level and each subdirectory under skills/.  Names must not
        collide because the candidate iterator never walks the system
        root itself.
        """
        with tempfile.TemporaryDirectory() as tmp:
            write_skill_md(tmp, name="integrator-meta-skill")
            write_skill_md(os.path.join(tmp, "skills", "alpha"), name="alpha")
            _write_capability(
                os.path.join(tmp, "skills", "alpha", "capabilities", "cap")
            )
            write_skill_md(os.path.join(tmp, "skills", "beta"), name="beta")
            targets = find_router_audit_targets(tmp)
        names = sorted(t["name"] for t in targets)
        self.assertEqual(
            names, ["alpha", "beta", os.path.basename(os.path.abspath(tmp))]
        )


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
