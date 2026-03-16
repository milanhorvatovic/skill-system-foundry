"""CLI-level tests for scaffold.py.

Tests run the scaffold script as a subprocess in a temporary directory,
verifying filesystem output, exit codes, and stdout messages.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCAFFOLD_SCRIPT = os.path.join(SCRIPTS_DIR, "scaffold.py")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from scaffold import (
    validate_name,
    read_template,
    write_file,
    create_dir_with_gitkeep,
    scaffold_skill,
    scaffold_capability,
    scaffold_role,
    _validate_flags,
    _parse_optional_dirs,
)
from lib.constants import (
    FILE_SKILL_MD,
    FILE_CAPABILITY_MD,
    FILE_GITKEEP,
    DIR_SKILLS,
    DIR_CAPABILITIES,
    DIR_ROLES,
    DIR_REFERENCES,
    DIR_SCRIPTS,
    DIR_ASSETS,
    TEMPLATE_SKILL_STANDALONE,
    TEMPLATE_SKILL_ROUTER,
    TEMPLATE_CAPABILITY,
    TEMPLATE_ROLE,
)


def _run(args, cwd):
    """Run scaffold.py with *args* in *cwd* and return the CompletedProcess."""
    return subprocess.run(
        [sys.executable, SCAFFOLD_SCRIPT] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _list_tree(root):
    """Return a set of all relative paths (dirs and files) under *root*."""
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
            entries = sorted(os.listdir(skill_dir))
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
        if proc.returncode != 0:
            raise RuntimeError(
                f"Router prerequisite failed (exit {proc.returncode}):\n"
                f"{proc.stdout}{proc.stderr}"
            )

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
            entries = sorted(os.listdir(cap_dir))
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
            self.assertIn("Unknown flag(s) for 'capability'", proc.stdout)
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
            self.assertIn("Unknown flag(s) for 'capability'", proc.stdout)
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
            self.assertIn("Unknown flag(s) for 'role'", proc.stdout)
            self.assertIn("--with-references", proc.stdout)

    def test_role_rejects_with_scripts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--with-scripts", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unknown flag(s) for 'role'", proc.stdout)

    def test_role_rejects_with_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--with-assets", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unknown flag(s) for 'role'", proc.stdout)

    def test_role_allowed_for_role_shows_update_manifest(self):
        """Error message for role should list --update-manifest as allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--with-references", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("--update-manifest", proc.stdout)


# ---------------------------------------------------------------------------
# Unknown flags (both --with-* and other --* flags)
# ---------------------------------------------------------------------------

class UnknownFlagTests(unittest.TestCase):
    """Unknown --* flags are rejected for all component types."""

    def test_skill_rejects_unknown_with_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "my-skill", "--with-foo", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unknown flag(s) for 'skill'", proc.stdout)
            self.assertIn("--with-foo", proc.stdout)

    def test_skill_rejects_typo_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "my-skill", "--routre", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unknown flag(s) for 'skill'", proc.stdout)
            self.assertIn("--routre", proc.stdout)

    def test_skill_rejects_arbitrary_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "my-skill", "--foo", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("--foo", proc.stdout)

    def test_capability_rejects_unknown_with_flag(self):
        """Unknown --with-* should fail even when mixed with valid flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create router prerequisite
            pre = _run(["skill", "my-domain", "--router", "--root", tmpdir], cwd=REPO_ROOT)
            if pre.returncode != 0:
                raise RuntimeError(f"Router prerequisite failed:\n{pre.stdout}{pre.stderr}")
            proc = _run(
                [
                    "capability", "my-domain", "my-cap",
                    "--with-references", "--with-foo", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("--with-foo", proc.stdout)

    def test_capability_rejects_arbitrary_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pre = _run(["skill", "my-domain", "--router", "--root", tmpdir], cwd=REPO_ROOT)
            if pre.returncode != 0:
                raise RuntimeError(f"Router prerequisite failed:\n{pre.stdout}{pre.stderr}")
            proc = _run(
                [
                    "capability", "my-domain", "my-cap",
                    "--verbose", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("--verbose", proc.stdout)

    def test_role_rejects_arbitrary_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--foo", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unknown flag(s) for 'role'", proc.stdout)
            self.assertIn("--foo", proc.stdout)


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

    def test_unknown_component_shows_fail_prefix(self):
        proc = _run(["bogus", "x"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL", proc.stdout)
        self.assertIn("Unknown component type: bogus", proc.stdout)


# ===================================================================
# Direct import tests (exercises code paths that subprocess-based
# tests cover functionally but that coverage cannot capture).
# ===================================================================


class ValidateNameUnitTests(unittest.TestCase):
    """Direct tests for scaffold.validate_name()."""

    def test_valid_name_returns_true(self) -> None:
        self.assertTrue(validate_name("my-skill"))

    def test_invalid_name_returns_false(self) -> None:
        self.assertFalse(validate_name("INVALID", json_output=True))

    def test_json_mode_suppresses_print(self) -> None:
        """json_output=True suppresses all stdout output."""
        import io
        from unittest.mock import patch as _patch

        buf = io.StringIO()
        with _patch("sys.stdout", buf):
            validate_name("INVALID", json_output=True)
        self.assertEqual(buf.getvalue(), "")


class ReadTemplateUnitTests(unittest.TestCase):
    """Direct tests for scaffold.read_template()."""

    def test_reads_standalone_skill_template(self) -> None:
        content = read_template(TEMPLATE_SKILL_STANDALONE)
        self.assertIsInstance(content, str)
        self.assertGreater(len(content), 0)

    def test_reads_router_skill_template(self) -> None:
        content = read_template(TEMPLATE_SKILL_ROUTER)
        self.assertIsInstance(content, str)
        self.assertGreater(len(content), 0)

    def test_reads_capability_template(self) -> None:
        content = read_template(TEMPLATE_CAPABILITY)
        self.assertIsInstance(content, str)

    def test_reads_role_template(self) -> None:
        content = read_template(TEMPLATE_ROLE)
        self.assertIsInstance(content, str)


class WriteFileUnitTests(unittest.TestCase):
    """Direct tests for scaffold.write_file()."""

    def test_creates_file_and_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "file.txt")
            write_file(path, "hello", quiet=True)
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "hello")


class CreateDirWithGitkeepUnitTests(unittest.TestCase):
    """Direct tests for scaffold.create_dir_with_gitkeep()."""

    def test_creates_directory_with_gitkeep(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "newdir")
            create_dir_with_gitkeep(target)
            self.assertTrue(os.path.isdir(target))
            self.assertTrue(os.path.exists(os.path.join(target, FILE_GITKEEP)))


class ValidateFlagsUnitTests(unittest.TestCase):
    """Direct tests for scaffold._validate_flags()."""

    def test_valid_skill_flags_pass(self) -> None:
        # Should not raise.
        _validate_flags(["--router", "--with-references"], "skill")

    def test_unknown_flag_exits(self) -> None:
        with self.assertRaises(SystemExit):
            _validate_flags(["--bogus"], "skill")

    def test_unknown_flag_json_mode_exits(self) -> None:
        with self.assertRaises(SystemExit):
            _validate_flags(["--bogus"], "skill", json_mode=True)


class ParseOptionalDirsUnitTests(unittest.TestCase):
    """Direct tests for scaffold._parse_optional_dirs()."""

    def test_parses_references(self) -> None:
        dirs = _parse_optional_dirs(["--with-references"])
        self.assertIn(DIR_REFERENCES, dirs)

    def test_parses_scripts(self) -> None:
        dirs = _parse_optional_dirs(["--with-scripts"])
        self.assertIn(DIR_SCRIPTS, dirs)

    def test_parses_assets(self) -> None:
        dirs = _parse_optional_dirs(["--with-assets"])
        self.assertIn(DIR_ASSETS, dirs)

    def test_ignores_non_with_flags(self) -> None:
        dirs = _parse_optional_dirs(["--router"])
        self.assertEqual(dirs, [])


class ScaffoldSkillUnitTests(unittest.TestCase):
    """Direct tests for scaffold_skill() with json_output=True."""

    def test_standalone_skill_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_skill("test-skill", root=tmpdir, json_output=True)
        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertEqual(result["component"], "skill")
        self.assertEqual(result["name"], "test-skill")
        self.assertFalse(result["router"])
        self.assertIn("created", result)

    def test_router_skill_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_skill("test-router", router=True, root=tmpdir, json_output=True)
        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertTrue(result["router"])

    def test_skill_with_optional_dirs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_skill(
                "test-skill",
                root=tmpdir,
                optional_dirs=[DIR_REFERENCES, DIR_SCRIPTS],
                json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertGreater(len(result["created"]), 1)

    def test_invalid_name_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_skill("INVALID", root=tmpdir, json_output=True)
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertIn("details", result)
        self.assertIsInstance(result["details"], list)
        self.assertGreater(len(result["details"]), 0)

    def test_duplicate_skill_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_skill("dup-skill", root=tmpdir, json_output=True)
            result = scaffold_skill("dup-skill", root=tmpdir, json_output=True)
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("already exists", result["error"])

    def test_scaffold_skill_json_template_not_found(self) -> None:
        """Missing template in JSON mode returns JSON error dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("scaffold.read_template") as mock_read:
                mock_read.side_effect = FileNotFoundError("Template not found: /fake/path.md")
                result = scaffold_skill("test-skill", router=False, root=tmpdir, json_output=True)
            self.assertIsNotNone(result)
            self.assertFalse(result["success"])
            self.assertIn("error", result)
            self.assertIn("Template not found", result["error"])


class ScaffoldCapabilityUnitTests(unittest.TestCase):
    """Direct tests for scaffold_capability() with json_output=True."""

    def test_capability_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create router prerequisite.
            scaffold_skill("my-domain", router=True, root=tmpdir, json_output=True)
            result = scaffold_capability(
                "my-domain", "my-cap", root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertEqual(result["component"], "capability")
        self.assertIn("created", result)

    def test_invalid_domain_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_capability(
                "BAD", "my-cap", root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])

    def test_invalid_cap_name_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_skill("my-domain", router=True, root=tmpdir, json_output=True)
            result = scaffold_capability(
                "my-domain", "BAD", root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])

    def test_missing_parent_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_capability(
                "no-parent", "my-cap", root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("Parent skill not found", result["error"])

    def test_duplicate_capability_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_skill("my-domain", router=True, root=tmpdir, json_output=True)
            scaffold_capability("my-domain", "dup-cap", root=tmpdir, json_output=True)
            result = scaffold_capability(
                "my-domain", "dup-cap", root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("already exists", result["error"])

    def test_scaffold_capability_json_template_not_found(self) -> None:
        """Missing template in JSON mode returns JSON error dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create router skill first
            skill_dir = os.path.join(tmpdir, "skills", "test-domain")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("# Test Domain\n")

            with patch("scaffold.read_template") as mock_read:
                mock_read.side_effect = FileNotFoundError("Template not found: /fake/path.md")
                result = scaffold_capability("test-domain", "test-cap", root=tmpdir, json_output=True)
            self.assertIsNotNone(result)
            self.assertFalse(result["success"])
            self.assertIn("error", result)
            self.assertIn("Template not found", result["error"])


class ScaffoldRoleUnitTests(unittest.TestCase):
    """Direct tests for scaffold_role() with json_output=True."""

    def test_role_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_role(
                "my-group", "my-role", root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertEqual(result["component"], "role")
        self.assertIn("created", result)

    def test_invalid_group_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_role(
                "BAD", "my-role", root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])

    def test_invalid_role_name_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_role(
                "my-group", "BAD", root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])

    def test_duplicate_role_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_role("my-group", "dup-role", root=tmpdir, json_output=True)
            result = scaffold_role(
                "my-group", "dup-role", root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("already exists", result["error"])

    def test_scaffold_role_json_template_not_found(self) -> None:
        """Missing template in JSON mode returns JSON error dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("scaffold.read_template") as mock_read:
                mock_read.side_effect = FileNotFoundError("Template not found: /fake/path.md")
                result = scaffold_role("test-group", "test-role", root=tmpdir, json_output=True)
            self.assertIsNotNone(result)
            self.assertFalse(result["success"])
            self.assertIn("error", result)
            self.assertIn("Template not found", result["error"])


class CreatedGitkeepTests(unittest.TestCase):
    """Verify created includes .gitkeep files for directories."""

    def test_router_skill_includes_gitkeep_in_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_skill(
                "test-router", router=True, root=tmpdir, json_output=True,
            )
        self.assertIsNotNone(result)
        gitkeep_paths = [p for p in result["created"] if p.endswith(FILE_GITKEEP)]
        # At least one .gitkeep for the capabilities/ directory
        self.assertGreater(len(gitkeep_paths), 0)

    def test_skill_with_optional_dirs_includes_gitkeeps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_skill(
                "test-skill", root=tmpdir,
                optional_dirs=[DIR_REFERENCES],
                json_output=True,
            )
        self.assertIsNotNone(result)
        gitkeep_paths = [p for p in result["created"] if p.endswith(FILE_GITKEEP)]
        self.assertEqual(len(gitkeep_paths), 1)

    def test_capability_with_optional_dirs_includes_gitkeeps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_skill("my-domain", router=True, root=tmpdir, json_output=True)
            result = scaffold_capability(
                "my-domain", "my-cap", root=tmpdir,
                optional_dirs=[DIR_REFERENCES],
                json_output=True,
            )
        self.assertIsNotNone(result)
        gitkeep_paths = [p for p in result["created"] if p.endswith(FILE_GITKEEP)]
        self.assertEqual(len(gitkeep_paths), 1)


class ScaffoldInternalErrorJsonTests(unittest.TestCase):
    """Verify JSON output on internal scaffold failures (OSError etc.)."""

    def test_filesystem_error_produces_json_via_main(self) -> None:
        """A filesystem error during scaffolding produces JSON via main()."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            # Place a regular file where skills/ directory should be
            # created, causing os.makedirs inside write_file to fail.
            blocker = os.path.join(tmpdir, "skills")
            with open(blocker, "w", encoding="utf-8") as f:
                f.write("blocker")
            proc = _run(
                ["skill", "test-skill", "--root", tmpdir, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)


class BundleParseErrorExitCodeTests(unittest.TestCase):
    """Verify bundle.py parse errors use exit code 1 in all modes."""

    def test_human_mode_missing_args_exits_one(self) -> None:
        """Missing positional arg in human mode exits with code 1."""
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "bundle.py"), "--verbose"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)

    def test_json_mode_missing_args_exits_one(self) -> None:
        """Missing positional arg in --json mode exits with code 1."""
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "bundle.py"), "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        import json
        data = json.loads(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)


# ---------------------------------------------------------------------------
# --update-manifest integration tests
# ---------------------------------------------------------------------------

class UpdateManifestSkillTests(unittest.TestCase):
    """Test --update-manifest flag for skill scaffolding."""

    def test_creates_manifest_if_missing(self) -> None:
        """--update-manifest creates manifest.yaml when it does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "new-skill", "--update-manifest", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            self.assertTrue(os.path.isfile(manifest_path))

    def test_appends_skill_to_existing_manifest(self) -> None:
        """--update-manifest appends a skill entry to an existing manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal manifest first.
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write("# Manifest\n\nskills:\n\nroles:\n")
            proc = _run(
                ["skill", "my-new-skill", "--update-manifest", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            with open(manifest_path, "r", encoding="utf-8") as f:
                text = f.read()
            self.assertIn("my-new-skill:", text)
            self.assertIn("type: standalone", text)

    def test_detects_name_conflict_and_warns(self) -> None:
        """--update-manifest warns on name conflict and skips update."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "  conflict-skill:\n"
                    "    canonical: skills/conflict-skill/SKILL.md\n"
                    "    type: standalone\n"
                    "\nroles:\n"
                )
            proc = _run(
                ["skill", "conflict-skill", "--update-manifest", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            # The skill directory doesn't exist, so scaffolding succeeds.
            # The manifest already has the name, so the manifest update warns.
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("WARN", proc.stdout)
            self.assertIn("already exists", proc.stdout)

    def test_router_skill_creates_correct_entry(self) -> None:
        """--update-manifest with --router creates a router type entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "my-router", "--router", "--update-manifest", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "r", encoding="utf-8") as f:
                text = f.read()
            self.assertIn("my-router:", text)
            self.assertIn("type: router", text)

    def test_json_includes_manifest_updated(self) -> None:
        """--update-manifest with --json includes manifest_updated key."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "json-skill", "--update-manifest", "--json", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            self.assertIn("manifest_updated", data)
            self.assertTrue(data["manifest_updated"])

    def test_json_created_includes_manifest_when_scaffolded(self) -> None:
        """--update-manifest includes manifest.yaml in created list when newly scaffolded."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "created-test", "--update-manifest", "--json", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            manifest_abs = os.path.abspath(os.path.join(tmpdir, "manifest.yaml"))
            self.assertIn(manifest_abs, data["created"])

    def test_json_created_excludes_manifest_when_preexisting(self) -> None:
        """--update-manifest does not add manifest.yaml to created if it already exists."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write("# Manifest\n\nskills:\n\nroles:\n")
            proc = _run(
                ["skill", "existing-mf", "--update-manifest", "--json", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            manifest_abs = os.path.abspath(manifest_path)
            self.assertNotIn(manifest_abs, data["created"])

    def test_json_conflict_includes_manifest_warning(self) -> None:
        """--update-manifest with --json includes manifest_warning on conflict."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "  dup-skill:\n"
                    "    canonical: skills/dup-skill/SKILL.md\n"
                    "    type: standalone\n"
                    "\nroles:\n"
                )
            proc = _run(
                ["skill", "dup-skill", "--update-manifest", "--json", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            self.assertFalse(data["manifest_updated"])
            self.assertIn("manifest_warning", data)
            self.assertIn("already exists", data["manifest_warning"])


class UpdateManifestCapabilityTests(unittest.TestCase):
    """Test --update-manifest flag for capability scaffolding."""

    def _create_router(self, tmpdir: str) -> None:
        proc = _run(
            ["skill", "my-domain", "--router", "--root", tmpdir],
            cwd=REPO_ROOT,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Router prerequisite failed:\n{proc.stdout}{proc.stderr}"
            )

    def test_capability_warns_no_manifest_update(self) -> None:
        """--update-manifest for capability prints info message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            proc = _run(
                [
                    "capability", "my-domain", "my-cap",
                    "--update-manifest", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("not added to manifest.yaml directly", proc.stdout)

    def test_capability_json_manifest_updated_false(self) -> None:
        """--update-manifest for capability in JSON mode sets manifest_updated=false."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            proc = _run(
                [
                    "capability", "my-domain", "my-cap",
                    "--update-manifest", "--json", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            self.assertFalse(data["manifest_updated"])
            self.assertIn("manifest_warning", data)


class UpdateManifestRoleTests(unittest.TestCase):
    """Test --update-manifest flag for role scaffolding."""

    def test_creates_manifest_and_adds_role(self) -> None:
        """--update-manifest creates manifest and adds role entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--update-manifest", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            self.assertTrue(os.path.isfile(manifest_path))
            with open(manifest_path, "r", encoding="utf-8") as f:
                text = f.read()
            self.assertIn("my-role", text)
            self.assertIn("my-group", text)

    def test_role_json_includes_manifest_updated(self) -> None:
        """--update-manifest with --json includes manifest_updated for roles."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "my-role", "--update-manifest", "--json", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            self.assertIn("manifest_updated", data)
            self.assertTrue(data["manifest_updated"])

    def test_role_json_created_includes_manifest_when_scaffolded(self) -> None:
        """--update-manifest includes manifest.yaml in created list for roles."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["role", "my-group", "cr-role", "--update-manifest", "--json", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            manifest_abs = os.path.abspath(os.path.join(tmpdir, "manifest.yaml"))
            self.assertIn(manifest_abs, data["created"])

    def test_role_conflict_warns(self) -> None:
        """--update-manifest for role warns on name conflict."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "\nroles:\n"
                    "  my-group:\n"
                    "    - name: dup-role\n"
                    "      path: roles/my-group/dup-role.md\n"
                )
            proc = _run(
                ["role", "my-group", "dup-role", "--update-manifest", "--json", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            self.assertFalse(data["manifest_updated"])
            self.assertIn("manifest_warning", data)


class UpdateManifestMalformedTests(unittest.TestCase):
    """End-to-end tests for --update-manifest with malformed manifest content."""

    def test_malformed_skills_list_warns_and_succeeds(self) -> None:
        """Scaffold succeeds but warns when manifest has skills as a list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write("skills:\n  - item1\n  - item2\n")
            proc = _run(
                ["skill", "some-name", "--update-manifest", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("WARN", proc.stdout)
            self.assertIn("skipping manifest update", proc.stdout)
            # Skill directory should still be created.
            skill_dir = os.path.join(tmpdir, "skills", "some-name")
            self.assertTrue(os.path.isdir(skill_dir))

    def test_malformed_skills_list_json_output(self) -> None:
        """JSON output shows manifest_updated=false and manifest_warning."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write("skills:\n  - item1\n  - item2\n")
            proc = _run(
                ["skill", "some-name", "--update-manifest", "--json", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            self.assertFalse(data["manifest_updated"])
            self.assertIn("manifest_warning", data)


if __name__ == "__main__":
    unittest.main()
