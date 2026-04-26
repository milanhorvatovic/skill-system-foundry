"""Tests for lib/discovery.py.

Covers ``find_skill_dirs`` (system-root, deployed-system layout),
``find_router_audit_targets`` (union of registered skills, capability-only
directories, and the skill-root entry), and ``find_roles``.  The skill-root
branch is exercised exclusively through ``find_router_audit_targets`` —
the underlying helper is private and intentionally not imported here.
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
# find_router_audit_targets — skill-root mode (top-level SKILL.md)
# ===================================================================


class FindRouterAuditTargetsSkillRootTests(unittest.TestCase):
    """The skill-root branch is exercised through the public API.

    Each test names the directory shape it builds (top-level SKILL.md,
    relative call, ``"."`` call, no SKILL.md, nested-only) and asserts
    the resulting target list.  The internal helper that produces the
    synthetic registered entry is private; covering it through
    ``find_router_audit_targets`` upholds the privacy boundary while
    exercising every branch.
    """

    def test_top_level_skill_md_yields_registered_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "my-meta-skill")
            write_skill_md(skill_dir, name="my-meta-skill")
            targets = find_router_audit_targets(skill_dir)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["name"], "my-meta-skill")
        self.assertEqual(targets[0]["type"], "registered")
        # Path shape mirrors the caller's ``system_root`` (matches
        # ``find_skill_dirs``).
        self.assertEqual(targets[0]["path"], skill_dir)

    def test_relative_path_is_preserved(self) -> None:
        """A relative ``system_root`` is not abspath-promoted on the target's path."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "my-meta-skill")
            write_skill_md(skill_dir, name="my-meta-skill")
            saved_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                targets = find_router_audit_targets("my-meta-skill")
            finally:
                os.chdir(saved_cwd)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["path"], "my-meta-skill")
        # The name resolves from the absolute path, so callers passing
        # a relative path still get a real directory name.
        self.assertEqual(targets[0]["name"], "my-meta-skill")

    def test_dot_path_resolves_name_from_frontmatter(self) -> None:
        """``find_router_audit_targets(".")`` uses the SKILL.md frontmatter name."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "my-meta-skill")
            write_skill_md(skill_dir, name="my-meta-skill")
            saved_cwd = os.getcwd()
            try:
                os.chdir(skill_dir)
                targets = find_router_audit_targets(".")
            finally:
                os.chdir(saved_cwd)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["name"], "my-meta-skill")
        self.assertEqual(targets[0]["path"], ".")

    def test_skill_root_name_prefers_frontmatter_over_directory(self) -> None:
        """A renamed worktree directory must not change the finding prefix.

        Mirrors the worktree case (e.g., ``worktrees/feature-foo/`` holding
        the foundry meta-skill) where the on-disk basename diverges from
        the canonical SKILL.md ``name``.
        """
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "renamed-worktree-dir")
            write_skill_md(skill_dir, name="canonical-skill-name")
            targets = find_router_audit_targets(skill_dir)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["name"], "canonical-skill-name")

    def test_skill_root_falls_back_to_basename_when_frontmatter_missing(self) -> None:
        """A SKILL.md without frontmatter degrades to the directory basename."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "no-frontmatter-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "# A SKILL.md with no frontmatter at all\n",
            )
            targets = find_router_audit_targets(skill_dir)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["name"], "no-frontmatter-skill")

    def test_skill_root_falls_back_to_basename_when_frontmatter_unparseable(self) -> None:
        """A SKILL.md with malformed YAML degrades to the directory basename."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "broken-frontmatter-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: missing closing delimiter\n",
            )
            targets = find_router_audit_targets(skill_dir)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["name"], "broken-frontmatter-skill")

    def test_no_skill_md_at_root_yields_no_skill_root_entry(self) -> None:
        """Without a top-level SKILL.md the skill-root branch contributes nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(find_router_audit_targets(tmp), [])

    def test_nested_skill_md_alone_does_not_synthesize_skill_root_entry(self) -> None:
        """A nested ``skills/<name>/SKILL.md`` must not be promoted to a skill-root entry."""
        with tempfile.TemporaryDirectory() as tmp:
            inner = os.path.join(tmp, "skills", "inner-skill")
            write_skill_md(inner, name="inner-skill")
            targets = find_router_audit_targets(tmp)
        # Only the nested skill should appear; no synthetic skill-root entry
        # for *tmp* itself, because *tmp* has no SKILL.md.
        names = [t["name"] for t in targets]
        self.assertEqual(names, ["inner-skill"])


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

    def test_includes_top_level_capabilities_without_skill_md(self) -> None:
        """A skill-root with capabilities/ but no SKILL.md must still be audited.

        Without this branch ``find_router_audit_targets`` would skip the
        broken root entirely, downgrading the
        ``capabilities/ exists but SKILL.md is missing`` FAIL to the
        generic partial-audit WARN.  The synthetic entry uses the
        directory basename because no frontmatter is available.
        """
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "broken-meta-skill")
            _write_capability(os.path.join(skill_dir, "capabilities", "alpha"))
            targets = find_router_audit_targets(skill_dir)
        names = [t["name"] for t in targets]
        self.assertEqual(names, ["broken-meta-skill"])

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
        # The skill-root entry uses the SKILL.md frontmatter name
        # ("integrator-meta-skill"), not the temp-directory basename,
        # so findings stay stable across worktrees and renames.
        self.assertEqual(names, ["alpha", "beta", "integrator-meta-skill"])


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
