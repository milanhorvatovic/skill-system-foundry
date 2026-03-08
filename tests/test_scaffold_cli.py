"""CLI-level tests for scaffold.py.

Tests run the scaffold script as a subprocess in a temporary directory,
verifying filesystem output, exit codes, and stdout messages.
"""

import os
import subprocess
import sys
import tempfile
import unittest

from helpers import write_text

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCAFFOLD_SCRIPT = os.path.join(SCRIPTS_DIR, "scaffold.py")


def _run(args, cwd):
    """Run scaffold.py with *args* in *cwd* and return the CompletedProcess."""
    return subprocess.run(
        [sys.executable, SCAFFOLD_SCRIPT] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _list_tree(root):
    """Return a sorted set of all relative paths (dirs and files) under *root*."""
    paths = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            paths.add(os.path.relpath(os.path.join(dirpath, d), root))
        for f in filenames:
            paths.add(os.path.relpath(os.path.join(dirpath, f), root))
    return paths


# ---------------------------------------------------------------------------
# Standalone skill
# ---------------------------------------------------------------------------

class StandaloneSkillTests(unittest.TestCase):
    """Scaffold a standalone skill with and without optional directories."""

    def test_default_creates_only_skill_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(["skill", "my-skill", "--root", tmpdir], cwd=REPO_ROOT)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            skill_dir = os.path.join(tmpdir, "skills", "my-skill")
            entries = os.listdir(skill_dir)
            self.assertEqual(entries, ["SKILL.md"])
            self.assertTrue(os.path.isfile(os.path.join(skill_dir, "SKILL.md")))

    def test_with_references_creates_references_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "my-skill", "--with-references", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            skill_dir = os.path.join(tmpdir, "skills", "my-skill")
            tree = _list_tree(skill_dir)
            self.assertIn("references", tree)
            self.assertIn(os.path.join("references", ".gitkeep"), tree)

    def test_with_all_flags_creates_all_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                [
                    "skill", "my-skill",
                    "--with-references", "--with-scripts", "--with-assets",
                    "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            skill_dir = os.path.join(tmpdir, "skills", "my-skill")
            tree = _list_tree(skill_dir)
            for d in ("references", "scripts", "assets"):
                self.assertIn(d, tree)
                self.assertIn(os.path.join(d, ".gitkeep"), tree)

    def test_duplicate_flag_creates_directory_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                [
                    "skill", "my-skill",
                    "--with-references", "--with-references",
                    "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            # Only one "Created: ...references" line should appear
            created_lines = [
                line for line in proc.stdout.splitlines()
                if "Created:" in line and "references" in line
            ]
            self.assertEqual(len(created_lines), 1)


# ---------------------------------------------------------------------------
# Router skill
# ---------------------------------------------------------------------------

class RouterSkillTests(unittest.TestCase):
    """Scaffold a router skill with and without optional directories."""

    def test_default_creates_skill_md_and_capabilities(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "my-router", "--router", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            skill_dir = os.path.join(tmpdir, "skills", "my-router")
            entries = sorted(os.listdir(skill_dir))
            self.assertEqual(entries, ["SKILL.md", "capabilities"])
            # capabilities/ should contain .gitkeep
            self.assertTrue(
                os.path.isfile(os.path.join(skill_dir, "capabilities", ".gitkeep"))
            )

    def test_with_assets_creates_assets_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "my-router", "--router", "--with-assets", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            skill_dir = os.path.join(tmpdir, "skills", "my-router")
            tree = _list_tree(skill_dir)
            self.assertIn("assets", tree)
            self.assertIn(os.path.join("assets", ".gitkeep"), tree)


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------

class CapabilityTests(unittest.TestCase):
    """Scaffold a capability under an existing router."""

    def _create_router(self, tmpdir):
        """Helper: scaffold a router skill as a prerequisite."""
        proc = _run(
            ["skill", "my-domain", "--router", "--root", tmpdir],
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_default_creates_only_capability_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            proc = _run(
                ["capability", "my-domain", "my-cap", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            cap_dir = os.path.join(
                tmpdir, "skills", "my-domain", "capabilities", "my-cap"
            )
            entries = os.listdir(cap_dir)
            self.assertEqual(entries, ["capability.md"])

    def test_with_references_creates_references_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            proc = _run(
                [
                    "capability", "my-domain", "my-cap",
                    "--with-references", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            cap_dir = os.path.join(
                tmpdir, "skills", "my-domain", "capabilities", "my-cap"
            )
            tree = _list_tree(cap_dir)
            self.assertIn("references", tree)
            self.assertIn(os.path.join("references", ".gitkeep"), tree)

    def test_unsupported_with_scripts_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            proc = _run(
                [
                    "capability", "my-domain", "my-cap",
                    "--with-scripts", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unsupported flag(s) for 'capability'", proc.stdout)
            self.assertIn("--with-scripts", proc.stdout)

    def test_unsupported_with_assets_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            proc = _run(
                [
                    "capability", "my-domain", "my-cap",
                    "--with-assets", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unsupported flag(s) for 'capability'", proc.stdout)
            self.assertIn("--with-assets", proc.stdout)

    def test_multiple_unsupported_flags_all_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            proc = _run(
                [
                    "capability", "my-domain", "my-cap",
                    "--with-scripts", "--with-assets", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("--with-scripts", proc.stdout)
            self.assertIn("--with-assets", proc.stdout)


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------

class RoleTests(unittest.TestCase):
    """Scaffold a role, verifying --with-* flags are rejected."""

    def test_role_rejects_with_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--with-references", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unsupported flag(s) for 'role'", proc.stdout)
            self.assertIn("--with-references", proc.stdout)

    def test_role_rejects_with_scripts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--with-scripts", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unsupported flag(s) for 'role'", proc.stdout)

    def test_role_rejects_with_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--with-assets", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unsupported flag(s) for 'role'", proc.stdout)

    def test_role_allowed_for_role_shows_none(self):
        """Error message for role should show '(none)' as allowed flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--with-references", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("(none)", proc.stdout)


# ---------------------------------------------------------------------------
# Unknown --with-* flag
# ---------------------------------------------------------------------------

class UnknownWithFlagTests(unittest.TestCase):
    """Completely unknown --with-* flags (e.g. --with-foo) are rejected."""

    def test_skill_rejects_unknown_with_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "my-skill", "--with-foo", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unsupported flag(s) for 'skill'", proc.stdout)
            self.assertIn("--with-foo", proc.stdout)

    def test_capability_rejects_unknown_with_flag(self):
        """Unknown --with-* should fail even when mixed with valid flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create router prerequisite
            _run(["skill", "my-domain", "--router", "--root", tmpdir], cwd=REPO_ROOT)
            proc = _run(
                [
                    "capability", "my-domain", "my-cap",
                    "--with-references", "--with-foo", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("--with-foo", proc.stdout)


# ---------------------------------------------------------------------------
# Usage / help output
# ---------------------------------------------------------------------------

class UsageStringTests(unittest.TestCase):
    """Verify usage strings are accurate and consistent."""

    def test_no_args_prints_full_docstring(self):
        proc = _run([], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Usage:", proc.stdout)
        self.assertIn("python scripts/scaffold.py", proc.stdout)

    def test_skill_no_name_shows_usage_with_root(self):
        proc = _run(["skill"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--root <path>", proc.stdout)
        self.assertIn("python scripts/scaffold.py skill", proc.stdout)

    def test_capability_no_name_shows_usage_with_root(self):
        proc = _run(["capability", "my-domain"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--root <path>", proc.stdout)
        self.assertIn("python scripts/scaffold.py capability", proc.stdout)

    def test_role_no_name_shows_usage_with_root(self):
        proc = _run(["role", "my-group"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--root <path>", proc.stdout)
        self.assertIn("python scripts/scaffold.py role", proc.stdout)

    def test_help_text_mentions_gitkeep(self):
        proc = _run([], cwd=REPO_ROOT)
        self.assertIn(".gitkeep", proc.stdout)


if __name__ == "__main__":
    unittest.main()
