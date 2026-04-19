"""CLI-level tests for scaffold.py.

Tests are organised in two styles:

- **Subprocess tests** run the scaffold script as a child process in a
  temporary directory, verifying filesystem output, exit codes, and stdout
  messages.
- **In-process tests** call ``main()`` and individual helper functions
  directly (with ``sys.argv`` patching where needed) so that coverage can
  observe the execution paths without subprocess overhead.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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
    main,
)
from lib.constants import (
    FILE_SKILL_MD,
    FILE_CAPABILITY_MD,
    FILE_GITKEEP,
    FILE_MANIFEST,
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
    LEVEL_FAIL,
    LEVEL_WARN,
    LEVEL_INFO,
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
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            _validate_flags(["--bogus"], "skill")
        self.assertEqual(ctx.exception.code, 1)
        output = buf.getvalue()
        self.assertIn(LEVEL_FAIL, output)

    def test_unknown_flag_json_mode_exits(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            _validate_flags(["--bogus"], "skill", json_mode=True)
        self.assertEqual(ctx.exception.code, 1)


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


# ===================================================================
# main() function tests — exercises the entire main() dispatch
# via sys.argv patching so coverage can observe execution.
# ===================================================================


class MainFunctionInsufficientArgsTests(unittest.TestCase):
    """Test main() with insufficient arguments."""

    def test_no_args_non_json_prints_docstring_and_exits(self) -> None:
        """No arguments in non-JSON mode prints docstring and exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Usage:", buf.getvalue())

    def test_no_args_json_prints_error_and_exits(self) -> None:
        """No arguments in JSON mode outputs JSON error and exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "--json"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["success"])
        self.assertIn("Insufficient arguments", data["error"])

    def test_only_component_no_name_non_json_exits(self) -> None:
        """Only component type but no name in non-JSON mode exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "skill"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("python scripts/scaffold.py skill", buf.getvalue())

    def test_only_component_no_name_json_exits(self) -> None:
        """Only component type and a dummy arg but no real name in JSON mode."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "skill", "--json"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["success"])
        # After --json is stripped, args are ["scaffold.py", "skill"] which is < 3
        self.assertIn("Insufficient arguments", data["error"])


class MainFunctionRootParsingTests(unittest.TestCase):
    """Test main() --root option parsing."""

    def test_root_missing_value_non_json_exits(self) -> None:
        """--root without a value in non-JSON mode exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "skill", "test-skill", "--root"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("--root requires a path argument", buf.getvalue())

    def test_root_missing_value_json_exits(self) -> None:
        """--root without a value in JSON mode exits 1 with JSON error."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "skill", "test-skill", "--root", "--json"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["success"])
        self.assertIn("--root requires a path argument", data["error"])

    def test_root_value_starts_with_dashes_exits(self) -> None:
        """--root followed by another flag exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "skill", "test-skill", "--root", "--other"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("--root requires a path argument", buf.getvalue())

    def test_root_happy_path(self) -> None:
        """--root with a valid path creates skill under that root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "skill", "test-skill", "--root", tmpdir]), \
                 mock.patch("sys.stdout", buf):
                main()
            skill_dir = os.path.join(tmpdir, DIR_SKILLS, "test-skill")
            self.assertTrue(os.path.isdir(skill_dir))


class MainFunctionUnknownComponentTests(unittest.TestCase):
    """Test main() with an unknown component type."""

    def test_unknown_component_non_json_exits(self) -> None:
        """Unknown component type in non-JSON mode exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "bogus", "x"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        output = buf.getvalue()
        self.assertIn(LEVEL_FAIL, output)
        self.assertIn("Unknown component type: bogus", output)
        self.assertIn("Valid types: skill, capability, role", output)

    def test_unknown_component_json_exits(self) -> None:
        """Unknown component type in JSON mode exits 1 with JSON error."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "bogus", "x", "--json"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["success"])
        self.assertIn("Unknown component type: bogus", data["error"])


class MainFunctionSkillDispatchTests(unittest.TestCase):
    """Test main() skill dispatch paths."""

    def test_skill_missing_name_non_json_exits(self) -> None:
        """Skill with only flags but no name in non-JSON mode exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "skill", "--router"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("python scripts/scaffold.py skill", buf.getvalue())

    def test_skill_missing_name_json_exits(self) -> None:
        """Skill with only flags but no name in JSON mode exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "skill", "--router", "--json"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["success"])
        self.assertIn("Missing skill name", data["error"])

    def test_skill_json_success(self) -> None:
        """Skill dispatch with --json prints JSON result and exits 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "skill", "test-skill", "--json", "--root", tmpdir]), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["success"])
            self.assertEqual(data["name"], "test-skill")

    def test_skill_json_with_router_flag(self) -> None:
        """Skill dispatch with --router creates a router skill."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "skill", "test-router", "--router", "--json", "--root", tmpdir]), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["success"])
            self.assertTrue(data["router"])

    def test_skill_json_with_update_manifest(self) -> None:
        """Skill dispatch with --update-manifest includes manifest_updated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "skill", "test-skill", "--update-manifest", "--json", "--root", tmpdir]), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["success"])
            self.assertIn("manifest_updated", data)

    def test_skill_json_invalid_name_exits(self) -> None:
        """Skill dispatch with invalid name in JSON mode exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "skill", "INVALID", "--json", "--root", tmpdir]), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 1)
            data = json.loads(buf.getvalue())
            self.assertFalse(data["success"])

    def test_skill_exception_json_catches(self) -> None:
        """Generic exception during skill scaffold in JSON mode exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "skill", "test-skill", "--json", "--root", tmpdir]), \
                 mock.patch("scaffold.scaffold_skill", side_effect=RuntimeError("boom")), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 1)
            data = json.loads(buf.getvalue())
            self.assertFalse(data["success"])
            self.assertIn("RuntimeError: boom", data["error"])

    def test_skill_exception_non_json_reraises(self) -> None:
        """Generic exception during skill scaffold in non-JSON mode re-raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("sys.argv", ["scaffold.py", "skill", "test-skill", "--root", tmpdir]), \
                 mock.patch("scaffold.scaffold_skill", side_effect=RuntimeError("boom")), \
                 self.assertRaises(RuntimeError) as ctx:
                main()
            self.assertIn("boom", str(ctx.exception))


class MainFunctionCapabilityDispatchTests(unittest.TestCase):
    """Test main() capability dispatch paths."""

    def test_capability_missing_name_non_json_exits(self) -> None:
        """Capability with only domain in non-JSON mode exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "capability", "my-domain"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("python scripts/scaffold.py capability", buf.getvalue())

    def test_capability_missing_name_json_exits(self) -> None:
        """Capability with only domain in JSON mode exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "capability", "my-domain", "--json"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["success"])
        self.assertIn("Missing domain or capability name", data["error"])

    def test_capability_json_success(self) -> None:
        """Capability dispatch with --json prints JSON result and exits 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_skill("my-domain", router=True, root=tmpdir, json_output=True)
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "capability", "my-domain", "my-cap", "--json", "--root", tmpdir]), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["success"])
            self.assertEqual(data["component"], "capability")

    def test_capability_exception_json_catches(self) -> None:
        """Generic exception during capability scaffold in JSON mode exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "capability", "my-domain", "my-cap", "--json", "--root", tmpdir]), \
                 mock.patch("scaffold.scaffold_capability", side_effect=RuntimeError("cap-boom")), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 1)
            data = json.loads(buf.getvalue())
            self.assertFalse(data["success"])
            self.assertIn("RuntimeError: cap-boom", data["error"])

    def test_capability_exception_non_json_reraises(self) -> None:
        """Generic exception during capability scaffold in non-JSON mode re-raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("sys.argv", ["scaffold.py", "capability", "my-domain", "my-cap", "--root", tmpdir]), \
                 mock.patch("scaffold.scaffold_capability", side_effect=RuntimeError("cap-boom")), \
                 self.assertRaises(RuntimeError) as ctx:
                main()
            self.assertIn("cap-boom", str(ctx.exception))


class MainFunctionRoleDispatchTests(unittest.TestCase):
    """Test main() role dispatch paths."""

    def test_role_missing_name_non_json_exits(self) -> None:
        """Role with only group in non-JSON mode exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "role", "my-group"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("python scripts/scaffold.py role", buf.getvalue())

    def test_role_missing_name_json_exits(self) -> None:
        """Role with only group in JSON mode exits 1."""
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scaffold.py", "role", "my-group", "--json"]), \
             mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["success"])
        self.assertIn("Missing group or role name", data["error"])

    def test_role_json_success(self) -> None:
        """Role dispatch with --json prints JSON result and exits 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "role", "my-group", "my-role", "--json", "--root", tmpdir]), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["success"])
            self.assertEqual(data["component"], "role")

    def test_role_exception_json_catches(self) -> None:
        """Generic exception during role scaffold in JSON mode exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.argv", ["scaffold.py", "role", "my-group", "my-role", "--json", "--root", tmpdir]), \
                 mock.patch("scaffold.scaffold_role", side_effect=RuntimeError("role-boom")), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 1)
            data = json.loads(buf.getvalue())
            self.assertFalse(data["success"])
            self.assertIn("RuntimeError: role-boom", data["error"])

    def test_role_exception_non_json_reraises(self) -> None:
        """Generic exception during role scaffold in non-JSON mode re-raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("sys.argv", ["scaffold.py", "role", "my-group", "my-role", "--root", tmpdir]), \
                 mock.patch("scaffold.scaffold_role", side_effect=RuntimeError("role-boom")), \
                 self.assertRaises(RuntimeError) as ctx:
                main()
            self.assertIn("role-boom", str(ctx.exception))


# ===================================================================
# Non-JSON output paths for scaffold_skill()
# ===================================================================


class ScaffoldSkillHumanOutputTests(unittest.TestCase):
    """Non-JSON output paths for scaffold_skill()."""

    def test_invalid_name_exits(self) -> None:
        """Invalid name in non-JSON mode exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_skill("INVALID", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn("Error:", output)

    def test_duplicate_directory_exits(self) -> None:
        """Duplicate skill directory in non-JSON mode prints FAIL and exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            scaffold_skill("dup-test", root=tmpdir, json_output=True)
            with mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_skill("dup-test", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn(LEVEL_FAIL, output)
            self.assertIn("already exists", output)

    def test_router_optional_dir_prints_created(self) -> None:
        """Router skill with optional dirs prints Created lines and Note."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_skill("test-router", router=True, optional_dirs=[DIR_REFERENCES], root=tmpdir)
            output = buf.getvalue()
            self.assertIn("Created:", output)
            self.assertIn("Note:", output)
            self.assertIn(DIR_REFERENCES, output)

    def test_standalone_optional_dir_prints_created(self) -> None:
        """Standalone skill with optional dirs prints Created line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_skill("test-standalone", optional_dirs=[DIR_REFERENCES], root=tmpdir)
            output = buf.getvalue()
            self.assertIn("Created:", output)
            self.assertIn(DIR_REFERENCES, output)

    def test_router_template_not_found_non_json_exits(self) -> None:
        """Missing router template in non-JSON mode prints FAIL and exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("scaffold.read_template", side_effect=FileNotFoundError("Template not found")), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_skill("test-skill", router=True, root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn(LEVEL_FAIL, output)
            self.assertIn("Template not found", output)

    def test_standalone_template_not_found_non_json_exits(self) -> None:
        """Missing standalone template in non-JSON mode prints FAIL and exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("scaffold.read_template", side_effect=FileNotFoundError("Template not found")), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_skill("test-skill", router=False, root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn(LEVEL_FAIL, output)
            self.assertIn("Template not found", output)

    def test_manifest_update_non_json_prints_messages(self) -> None:
        """update_manifest=True in non-JSON mode prints Created/Updated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_skill("test-skill", update_manifest=True, root=tmpdir)
            output = buf.getvalue()
            # Manifest is created (new) and updated (entry added)
            self.assertIn("Created:", output)
            self.assertIn("Updated:", output)

    def test_manifest_warning_non_json_prints_warn(self) -> None:
        """Manifest conflict in non-JSON mode prints WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, FILE_MANIFEST)
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "  conflict-skill:\n"
                    "    canonical: skills/conflict-skill/SKILL.md\n"
                    "    type: standalone\n"
                    "\nroles:\n"
                )
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_skill("conflict-skill", update_manifest=True, root=tmpdir)
            output = buf.getvalue()
            self.assertIn(LEVEL_WARN, output)

    def test_success_message_without_update_manifest(self) -> None:
        """Success message without update_manifest includes manifest guidance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_skill("test-skill", root=tmpdir)
            output = buf.getvalue()
            self.assertIn("Skill 'test-skill' scaffolded at", output)
            self.assertIn("Next:", output)
            manifest_path = os.path.join(tmpdir, FILE_MANIFEST)
            self.assertIn(manifest_path, output)

    def test_success_message_with_update_manifest(self) -> None:
        """Success message with update_manifest omits manifest guidance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_skill("test-skill", update_manifest=True, root=tmpdir)
            output = buf.getvalue()
            self.assertIn("Skill 'test-skill' scaffolded at", output)
            self.assertIn("Next: edit", output)
            # Check that the "Next:" line does NOT tell user to update manifest
            manifest_path = os.path.join(tmpdir, FILE_MANIFEST)
            next_lines = [line for line in output.splitlines() if "Next:" in line]
            for line in next_lines:
                self.assertNotIn("update " + manifest_path, line)


# ===================================================================
# Non-JSON output paths for scaffold_capability()
# ===================================================================


class ScaffoldCapabilityHumanOutputTests(unittest.TestCase):
    """Non-JSON output paths for scaffold_capability()."""

    def _create_router(self, tmpdir: str) -> None:
        """Helper: create a router skill prerequisite."""
        scaffold_skill("my-domain", router=True, root=tmpdir, json_output=True)

    def test_invalid_domain_exits(self) -> None:
        """Invalid domain name in non-JSON mode exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_capability("INVALID", "my-cap", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn("Error:", output)

    def test_invalid_name_exits(self) -> None:
        """Invalid capability name in non-JSON mode exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_capability("my-domain", "INVALID", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn("Error:", output)

    def test_duplicate_capability_exits(self) -> None:
        """Duplicate capability in non-JSON mode prints FAIL and exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            scaffold_capability("my-domain", "dup-cap", root=tmpdir, json_output=True)
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_capability("my-domain", "dup-cap", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn(LEVEL_FAIL, output)
            self.assertIn("already exists", output)

    def test_missing_parent_exits(self) -> None:
        """Missing parent router skill in non-JSON mode prints FAIL and exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_capability("no-parent", "my-cap", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn(LEVEL_FAIL, output)
            self.assertIn("Parent skill not found", output)

    def test_template_not_found_non_json_exits(self) -> None:
        """Missing template in non-JSON mode prints FAIL and exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            buf = io.StringIO()
            with mock.patch("scaffold.read_template", side_effect=FileNotFoundError("Template not found")), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_capability("my-domain", "my-cap", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn(LEVEL_FAIL, output)

    def test_optional_dir_prints_created(self) -> None:
        """Capability with optional dirs prints Created line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_capability("my-domain", "my-cap", root=tmpdir, optional_dirs=[DIR_REFERENCES])
            output = buf.getvalue()
            self.assertIn("Created:", output)
            self.assertIn(DIR_REFERENCES, output)

    def test_success_message_non_json(self) -> None:
        """Success message includes checkmark, Next: lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_capability("my-domain", "my-cap", root=tmpdir)
            output = buf.getvalue()
            self.assertIn("Capability 'my-cap' scaffolded at", output)
            self.assertIn("Next:", output)
            self.assertIn("routing table", output)
            # The manifest path includes the tmpdir prefix
            manifest_path = os.path.join(tmpdir, FILE_MANIFEST)
            self.assertIn("update " + manifest_path, output)

    def test_update_manifest_info_non_json(self) -> None:
        """With update_manifest=True, prints INFO about not adding to manifest directly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_capability("my-domain", "my-cap", root=tmpdir, update_manifest=True)
            output = buf.getvalue()
            self.assertIn(LEVEL_INFO, output)
            self.assertIn("not added to manifest.yaml directly", output)

    def test_no_update_manifest_shows_manifest_guidance(self) -> None:
        """Without update_manifest, prints Next: update <manifest_path>."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_router(tmpdir)
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_capability("my-domain", "my-cap", root=tmpdir, update_manifest=False)
            output = buf.getvalue()
            manifest_path = os.path.join(tmpdir, FILE_MANIFEST)
            self.assertIn("Next: update " + manifest_path, output)


# ===================================================================
# Non-JSON output paths for scaffold_role()
# ===================================================================


class ScaffoldRoleHumanOutputTests(unittest.TestCase):
    """Non-JSON output paths for scaffold_role()."""

    def test_invalid_group_exits(self) -> None:
        """Invalid group name in non-JSON mode exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_role("INVALID", "my-role", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn("Error:", output)

    def test_invalid_name_exits(self) -> None:
        """Invalid role name in non-JSON mode exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_role("my-group", "INVALID", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn("Error:", output)

    def test_duplicate_role_exits(self) -> None:
        """Duplicate role in non-JSON mode prints FAIL and exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_role("my-group", "dup-role", root=tmpdir, json_output=True)
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_role("my-group", "dup-role", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn(LEVEL_FAIL, output)
            self.assertIn("already exists", output)

    def test_template_not_found_non_json_exits(self) -> None:
        """Missing template in non-JSON mode prints FAIL and exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("scaffold.read_template", side_effect=FileNotFoundError("Template not found")), \
                 mock.patch("sys.stdout", buf), \
                 self.assertRaises(SystemExit) as ctx:
                scaffold_role("my-group", "my-role", root=tmpdir)
            self.assertEqual(ctx.exception.code, 1)
            output = buf.getvalue()
            self.assertIn(LEVEL_FAIL, output)

    def test_roles_readme_created(self) -> None:
        """First role in a fresh tmpdir creates roles/README.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_role("my-group", "my-role", root=tmpdir)
            roles_readme = os.path.join(tmpdir, DIR_ROLES, "README.md")
            self.assertTrue(os.path.isfile(roles_readme))

    def test_group_readme_created(self) -> None:
        """First role in a group creates roles/<group>/README.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_role("my-group", "my-role", root=tmpdir)
            group_readme = os.path.join(tmpdir, DIR_ROLES, "my-group", "README.md")
            self.assertTrue(os.path.isfile(group_readme))

    def test_readmes_not_recreated(self) -> None:
        """Second role in same group does not recreate READMEs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_role("my-group", "first-role", root=tmpdir, json_output=True)
            roles_readme = os.path.join(tmpdir, DIR_ROLES, "README.md")
            group_readme = os.path.join(tmpdir, DIR_ROLES, "my-group", "README.md")
            # Write a sentinel string into each README after the first scaffold
            sentinel = "SENTINEL-DO-NOT-OVERWRITE"
            for path in (roles_readme, group_readme):
                with open(path, "a", encoding="utf-8") as f:
                    f.write(sentinel)
            # Create a second role in the same group
            scaffold_role("my-group", "second-role", root=tmpdir, json_output=True)
            # Sentinels must still be present — files were not recreated
            for path in (roles_readme, group_readme):
                with open(path, "r", encoding="utf-8") as f:
                    self.assertIn(sentinel, f.read())

    def test_manifest_update_non_json_prints_messages(self) -> None:
        """update_manifest=True in non-JSON mode prints Created/Updated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_role("my-group", "my-role", update_manifest=True, root=tmpdir)
            output = buf.getvalue()
            self.assertIn("Created:", output)
            self.assertIn("Updated:", output)

    def test_manifest_warning_non_json_prints_warn(self) -> None:
        """Manifest conflict in non-JSON mode prints WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, FILE_MANIFEST)
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "\nroles:\n"
                    "  my-group:\n"
                    "    - name: my-role\n"
                    "      path: roles/my-group/my-role.md\n"
                )
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_role("my-group", "my-role", update_manifest=True, root=tmpdir)
            output = buf.getvalue()
            self.assertIn(LEVEL_WARN, output)

    def test_success_message_non_json(self) -> None:
        """Success message includes checkmark and Next: guidance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_role("my-group", "my-role", root=tmpdir)
            output = buf.getvalue()
            self.assertIn("Role 'my-role' scaffolded at", output)
            self.assertIn("Next: edit", output)
            manifest_path = os.path.join(tmpdir, FILE_MANIFEST)
            self.assertIn("Next: update " + manifest_path, output)

    def test_success_message_with_update_manifest(self) -> None:
        """Success with update_manifest omits manifest guidance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                scaffold_role("my-group", "my-role", update_manifest=True, root=tmpdir)
            output = buf.getvalue()
            self.assertIn("Role 'my-role' scaffolded at", output)
            # Should not contain "Next: update <manifest_path>"
            manifest_path = os.path.join(tmpdir, FILE_MANIFEST)
            next_lines = [line for line in output.splitlines() if "Next:" in line]
            for line in next_lines:
                self.assertNotIn("update " + manifest_path, line)


# ===================================================================
# validate_name() human-readable output
# ===================================================================


class ValidateNameHumanOutputTests(unittest.TestCase):
    """Human-readable output paths for validate_name()."""

    def test_fail_prefixed_error_prints_error(self) -> None:
        """FAIL-prefixed error prints 'Error:' prefix."""
        buf = io.StringIO()
        with mock.patch(
            "scaffold._validate_name_detailed",
            return_value=([LEVEL_FAIL + ": Invalid name"], []),
        ), mock.patch("sys.stdout", buf):
            result = validate_name("some-name")
        self.assertFalse(result)
        self.assertIn("Error:", buf.getvalue())

    def test_warn_prefixed_error_prints_warning(self) -> None:
        """WARN-prefixed error prints 'Warning:' prefix."""
        buf = io.StringIO()
        with mock.patch(
            "scaffold._validate_name_detailed",
            return_value=([LEVEL_WARN + ": Name too long"], []),
        ), mock.patch("sys.stdout", buf):
            result = validate_name("some-name")
        # WARN does not fail validation (no FAIL prefix)
        self.assertTrue(result)
        self.assertIn("Warning:", buf.getvalue())

    def test_no_prefix_error_treated_as_warning(self) -> None:
        """Error with no recognized level prefix is treated as Warning."""
        buf = io.StringIO()
        with mock.patch(
            "scaffold._validate_name_detailed",
            return_value=(["Some unexpected message"], []),
        ), mock.patch("sys.stdout", buf):
            result = validate_name("some-name")
        # No FAIL prefix means validation passes
        self.assertTrue(result)
        output = buf.getvalue()
        self.assertIn("Warning:", output)
        self.assertIn("Some unexpected message", output)


# ===================================================================
# read_template() FileNotFoundError
# ===================================================================


class ReadTemplateErrorTests(unittest.TestCase):
    """Test read_template() raises FileNotFoundError for missing template."""

    def test_nonexistent_template_raises(self) -> None:
        """Non-existent template raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError) as ctx:
            read_template("nonexistent-template.md")
        self.assertIn("Template not found", str(ctx.exception))


# ===================================================================
# write_file() non-quiet print path
# ===================================================================


class WriteFileOutputTests(unittest.TestCase):
    """Test write_file() prints Created message when quiet=False."""

    def test_default_quiet_false_prints_created(self) -> None:
        """Default quiet=False prints 'Created:' message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "test.txt")
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                write_file(path, "content")
            self.assertIn("Created:", buf.getvalue())
            self.assertIn(path, buf.getvalue())


# ===================================================================
# _validate_flags() JSON mode output
# ===================================================================


class ValidateFlagsJsonTests(unittest.TestCase):
    """Test _validate_flags() JSON mode output format."""

    def test_unknown_flag_json_mode_outputs_json(self) -> None:
        """Unknown flag in JSON mode prints JSON with error message."""
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf), \
             self.assertRaises(SystemExit) as ctx:
            _validate_flags(["--bogus"], "skill", json_mode=True)
        self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["success"])
        self.assertIn("Unknown flag(s)", data["error"])
        self.assertIn("Allowed:", data["error"])


# ===================================================================
# _parse_optional_dirs() deduplication
# ===================================================================


class ParseOptionalDirsDeduplicationTests(unittest.TestCase):
    """Test _parse_optional_dirs() deduplication logic."""

    def test_duplicate_flags_deduplicated(self) -> None:
        """Duplicate --with-references flags return single entry."""
        dirs = _parse_optional_dirs(["--with-references", "--with-references"])
        self.assertEqual(len(dirs), 1)
        self.assertEqual(dirs[0], DIR_REFERENCES)


# ===================================================================
# Manifest divergence findings (issue #89 stage 2)
# ===================================================================


class ManifestFindingsSurfacedTests(unittest.TestCase):
    """--update-manifest surfaces divergences in the existing manifest."""

    def _write_divergent_manifest(self, tmpdir: str) -> str:
        path = os.path.join(tmpdir, "manifest.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "skills:\n"
                "  demo:\n"
                "    canonical: skills/demo/SKILL.md\n"
                "    note: runs tasks: quickly\n"
                "\nroles:\n"
            )
        return path

    def test_text_mode_prints_findings_for_skill_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_divergent_manifest(tmpdir)
            proc = _run(
                ["skill", "added", "--update-manifest", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("FAIL:", proc.stdout)
            self.assertIn("': '", proc.stdout)

    def test_json_mode_includes_warnings_for_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_divergent_manifest(tmpdir)
            proc = _run(
                [
                    "skill", "added", "--update-manifest", "--json",
                    "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            self.assertIn("warnings", data)
            self.assertTrue(any("FAIL" in f for f in data["warnings"]))

    def test_clean_manifest_omits_warnings_key_in_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Manifest\n\nskills:\n\nroles:\n")
            proc = _run(
                [
                    "skill", "added", "--update-manifest", "--json",
                    "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertNotIn("warnings", data)

    def test_json_mode_includes_warnings_for_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "  demo:\n"
                    "    canonical: skills/demo/SKILL.md\n"
                    "    note: runs tasks: quickly\n"
                    "\nroles:\n"
                    "  dev-group:\n"
                    "    - name: existing\n"
                    "      path: roles/dev-group/existing.md\n"
                )
            proc = _run(
                [
                    "role", "dev-group", "added", "--update-manifest",
                    "--json", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["success"])
            self.assertIn("warnings", data)


# ===================================================================
# Frontmatter re-parse (issue #89 stage 6)
# ===================================================================


class ScaffoldFrontmatterReparseTests(unittest.TestCase):
    """Scaffold re-parses the written entry file for divergences."""

    def test_skill_template_substitution_produces_no_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                ["skill", "demo-skill", "--json", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertNotIn("warnings", data)

    def test_capability_template_substitution_produces_no_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _run(
                ["skill", "demo-domain", "--router", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            proc = _run(
                [
                    "capability", "demo-domain", "demo-cap",
                    "--json", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertNotIn("warnings", data)

    def test_divergent_frontmatter_surfaced_in_json(self) -> None:
        """Mock the re-parse helper to exercise the surfacing path."""
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmpdir:
            sample = ["FAIL: [spec] 'name': unquoted value … contains ': '"]
            with mock.patch(
                "scaffold._collect_frontmatter_findings",
                return_value=sample,
            ):
                from scaffold import scaffold_skill
                result = scaffold_skill(
                    "demo-skill", root=tmpdir, json_output=True,
                )
        self.assertIsNotNone(result)
        self.assertEqual(result["warnings"], sample)

    def test_divergent_frontmatter_surfaced_in_text_mode(self) -> None:
        """Text-mode scaffold prints findings after Created line."""
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmpdir:
            sample = ["FAIL: [spec] 'name': unquoted value … contains ': '"]
            buf = io.StringIO()
            with (
                mock.patch(
                    "scaffold._collect_frontmatter_findings",
                    return_value=sample,
                ),
                redirect_stdout(buf),
            ):
                from scaffold import scaffold_skill
                scaffold_skill("demo-skill", root=tmpdir, json_output=False)
            self.assertIn("FAIL:", buf.getvalue())
            self.assertIn("': '", buf.getvalue())

    def test_capability_divergent_frontmatter_surfaced_in_json(self) -> None:
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmpdir:
            _run(
                ["skill", "demo-domain", "--router", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            sample = ["WARN: [spec] 'name': unquoted value starts with '&'"]
            with mock.patch(
                "scaffold._collect_frontmatter_findings",
                return_value=sample,
            ):
                from scaffold import scaffold_capability
                result = scaffold_capability(
                    "demo-domain", "demo-cap", root=tmpdir, json_output=True,
                )
        self.assertIsNotNone(result)
        self.assertEqual(result["warnings"], sample)

    def test_role_template_substitution_produces_no_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                [
                    "role", "demo-group", "demo-role",
                    "--json", "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertNotIn("warnings", data)

    def test_role_divergent_frontmatter_surfaced_in_json(self) -> None:
        """scaffold_role surfaces frontmatter findings parallel to skill/capability."""
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmpdir:
            sample = ["FAIL: [spec] 'name': unquoted value … contains ': '"]
            with mock.patch(
                "scaffold._collect_frontmatter_findings",
                return_value=sample,
            ):
                from scaffold import scaffold_role
                result = scaffold_role(
                    "demo-group", "demo-role", root=tmpdir, json_output=True,
                )
        self.assertIsNotNone(result)
        self.assertEqual(result["warnings"], sample)

    def test_role_divergent_frontmatter_surfaced_in_text_mode(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmpdir:
            sample = ["FAIL: [spec] 'name': unquoted value … contains ': '"]
            buf = io.StringIO()
            with (
                mock.patch(
                    "scaffold._collect_frontmatter_findings",
                    return_value=sample,
                ),
                redirect_stdout(buf),
            ):
                from scaffold import scaffold_role
                scaffold_role(
                    "demo-group", "demo-role", root=tmpdir, json_output=False,
                )
            self.assertIn("FAIL:", buf.getvalue())
            self.assertIn("': '", buf.getvalue())


class ScaffoldEmitCorruptionTests(unittest.TestCase):
    """Scaffold treats manifest emit corruption as a hard failure."""

    def test_skill_emit_corruption_returns_success_false_in_json(self) -> None:
        from unittest import mock
        emit_finding = (
            "FAIL: manifest emit produced unparseable YAML: "
            "Failed to parse /tmp/m.yaml: 'skills' must be a mapping"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "scaffold.update_manifest_for_skill",
                return_value=(
                    False,
                    "Manifest update wrote an invalid manifest at /tmp/m.yaml",
                    False,
                    [emit_finding],
                ),
            ):
                from scaffold import scaffold_skill
                result = scaffold_skill(
                    "demo-skill",
                    root=tmpdir,
                    json_output=True,
                    update_manifest=True,
                )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn(emit_finding, result["warnings"])

    def test_skill_emit_corruption_exits_one_in_text_mode(self) -> None:
        from unittest import mock
        emit_finding = (
            "FAIL: manifest emit produced unparseable YAML: "
            "Failed to parse /tmp/m.yaml: 'skills' must be a mapping"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "scaffold.update_manifest_for_skill",
                return_value=(
                    False,
                    "Manifest update wrote an invalid manifest at /tmp/m.yaml",
                    False,
                    [emit_finding],
                ),
            ):
                from scaffold import scaffold_skill
                with self.assertRaises(SystemExit) as ctx:
                    scaffold_skill(
                        "demo-skill",
                        root=tmpdir,
                        json_output=False,
                        update_manifest=True,
                    )
        self.assertEqual(ctx.exception.code, 1)

    def test_role_emit_corruption_returns_success_false_in_json(self) -> None:
        from unittest import mock
        emit_finding = (
            "FAIL: manifest emit produced unparseable YAML: "
            "Failed to parse /tmp/m.yaml: 'roles' must be a mapping"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "scaffold.update_manifest_for_role",
                return_value=(
                    False,
                    "Manifest update wrote an invalid manifest at /tmp/m.yaml",
                    False,
                    [emit_finding],
                ),
            ):
                from scaffold import scaffold_role
                result = scaffold_role(
                    "demo-group", "demo-role",
                    root=tmpdir,
                    json_output=True,
                    update_manifest=True,
                )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn(emit_finding, result["warnings"])

    def test_role_emit_corruption_exits_one_in_text_mode(self) -> None:
        from unittest import mock
        emit_finding = (
            "FAIL: manifest emit produced unparseable YAML: "
            "Failed to parse /tmp/m.yaml: 'roles' must be a mapping"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "scaffold.update_manifest_for_role",
                return_value=(
                    False,
                    "Manifest update wrote an invalid manifest at /tmp/m.yaml",
                    False,
                    [emit_finding],
                ),
            ):
                from scaffold import scaffold_role
                with self.assertRaises(SystemExit) as ctx:
                    scaffold_role(
                        "demo-group", "demo-role",
                        root=tmpdir,
                        json_output=False,
                        update_manifest=True,
                    )
        self.assertEqual(ctx.exception.code, 1)

    def test_skill_frontmatter_parse_error_returns_success_false_in_json(self) -> None:
        from unittest import mock
        sample = ["FAIL: Invalid frontmatter in /tmp/SKILL.md: malformed YAML"]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "scaffold._collect_frontmatter_findings",
                return_value=sample,
            ):
                from scaffold import scaffold_skill
                result = scaffold_skill(
                    "demo-skill", root=tmpdir, json_output=True,
                )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertEqual(result["warnings"], sample)

    def test_skill_frontmatter_parse_error_exits_one_in_text_mode(self) -> None:
        from unittest import mock
        sample = ["FAIL: Invalid frontmatter in /tmp/SKILL.md: malformed YAML"]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "scaffold._collect_frontmatter_findings",
                return_value=sample,
            ):
                from scaffold import scaffold_skill
                with self.assertRaises(SystemExit) as ctx:
                    scaffold_skill(
                        "demo-skill", root=tmpdir, json_output=False,
                    )
        self.assertEqual(ctx.exception.code, 1)

    def test_capability_frontmatter_parse_error_returns_success_false_in_json(self) -> None:
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmpdir:
            _run(
                ["skill", "demo-domain", "--router", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            sample = ["FAIL: Invalid frontmatter in /tmp/cap.md: malformed YAML"]
            with mock.patch(
                "scaffold._collect_frontmatter_findings",
                return_value=sample,
            ):
                from scaffold import scaffold_capability
                result = scaffold_capability(
                    "demo-domain", "demo-cap", root=tmpdir, json_output=True,
                )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertEqual(result["warnings"], sample)

    def test_role_frontmatter_parse_error_returns_success_false_in_json(self) -> None:
        from unittest import mock
        sample = ["FAIL: Invalid frontmatter in /tmp/role.md: malformed YAML"]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "scaffold._collect_frontmatter_findings",
                return_value=sample,
            ):
                from scaffold import scaffold_role
                result = scaffold_role(
                    "demo-group", "demo-role",
                    root=tmpdir, json_output=True,
                )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertEqual(result["warnings"], sample)

    def test_plain_scalar_finding_does_not_trigger_hard_failure(self) -> None:
        """Pre-existing divergence FAIL findings must not promote to hard fail."""
        from unittest import mock
        sample = ["FAIL: [spec] 'name': unquoted value … contains ': '"]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "scaffold._collect_frontmatter_findings",
                return_value=sample,
            ):
                from scaffold import scaffold_skill
                result = scaffold_skill(
                    "demo-skill", root=tmpdir, json_output=True,
                )
        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertEqual(result["warnings"], sample)

    def test_name_conflict_warning_remains_warn_level(self) -> None:
        """Pre-existing name conflict still surfaces as WARN, not FAIL."""
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "  demo-skill:\n"
                    "    canonical: skills/demo-skill/SKILL.md\n"
                    "    type: standalone\n"
                )
            buf = io.StringIO()
            with redirect_stdout(buf):
                from scaffold import scaffold_skill
                scaffold_skill(
                    "demo-skill", root=tmpdir,
                    json_output=False, update_manifest=True,
                )
            output = buf.getvalue()
        self.assertIn("WARN:", output)
        self.assertNotIn("FAIL:", output)


class ScaffoldBadNameReparseTests(unittest.TestCase):
    """Bypassing validate_name, the re-parse catches literal divergent names.

    The re-parse path is defense-in-depth; validate_name normally
    rejects these names upfront, but these tests exercise the real
    pipeline with validate_name patched to pass, so the rendered
    frontmatter is what actually exercises _collect_frontmatter_findings.

    Colon-bearing names are skipped on Windows because ``:`` is
    reserved in NTFS paths — the filesystem rejects the directory
    before our re-parse runs.  The ``- foo`` case is POSIX-and-NTFS
    compatible and runs everywhere.
    """

    @unittest.skipIf(
        sys.platform == "win32",
        "':' is not a valid Windows path character; tested on POSIX only.",
    )
    def test_name_with_colon_space_triggers_real_finding(self) -> None:
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("scaffold.validate_name", return_value=True):
                from scaffold import scaffold_skill
                result = scaffold_skill(
                    "foo: bar", root=tmpdir, json_output=True,
                )
        self.assertIsNotNone(result)
        warnings = result.get("warnings", [])
        self.assertTrue(
            any("': '" in w and w.startswith("FAIL") for w in warnings),
            msg=f"expected ': ' FAIL in warnings, got: {warnings}",
        )

    def test_name_with_leading_dash_space_triggers_real_finding(self) -> None:
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("scaffold.validate_name", return_value=True):
                from scaffold import scaffold_skill
                result = scaffold_skill(
                    "- foo", root=tmpdir, json_output=True,
                )
        self.assertIsNotNone(result)
        warnings = result.get("warnings", [])
        self.assertTrue(
            any("block sequence" in w.lower() or "'-'" in w for w in warnings),
            msg=f"expected block-entry finding in warnings, got: {warnings}",
        )

    @unittest.skipIf(
        sys.platform == "win32",
        "':' is not a valid Windows path character; tested on POSIX only.",
    )
    def test_bad_name_file_remains_on_disk(self) -> None:
        """Re-parse warnings do not delete the scaffolded file."""
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("scaffold.validate_name", return_value=True):
                from scaffold import scaffold_skill
                scaffold_skill("foo: bar", root=tmpdir, json_output=True)
            skill_md = os.path.join(
                tmpdir, "skills", "foo: bar", "SKILL.md",
            )
            self.assertTrue(os.path.isfile(skill_md))


class ScaffoldWarningsDedupeTests(unittest.TestCase):
    """Scaffold merges read-time + emit-time findings without duplicates."""

    def test_repeated_finding_surfaces_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "  demo:\n"
                    "    canonical: skills/demo/SKILL.md\n"
                    "    note: runs tasks: quickly\n"
                )
            proc = _run(
                [
                    "skill", "added", "--update-manifest", "--json",
                    "--root", tmpdir,
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
        warnings = data.get("warnings", [])
        # The pre-existing divergence is seen by read_manifest and again
        # by the emit-site re-parse; dedupe keeps it once.
        self.assertEqual(len(warnings), 1)
        self.assertIn("': '", warnings[0])


class CollectFrontmatterFindingsTests(unittest.TestCase):
    """``_collect_frontmatter_findings`` helper edge cases."""

    def test_missing_file_returns_empty(self) -> None:
        from scaffold import _collect_frontmatter_findings
        with tempfile.TemporaryDirectory() as tmpdir:
            findings = _collect_frontmatter_findings(
                os.path.join(tmpdir, "nope.md"),
            )
        self.assertEqual(findings, [])

    def test_file_without_frontmatter_returns_empty(self) -> None:
        from scaffold import _collect_frontmatter_findings
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "note.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Just markdown\n")
            findings = _collect_frontmatter_findings(path)
        self.assertEqual(findings, [])

    def test_divergent_frontmatter_surfaces_finding(self) -> None:
        from scaffold import _collect_frontmatter_findings
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "bad.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "---\n"
                    "name: demo\n"
                    "description: runs tasks: quickly\n"
                    "---\n\n# Body\n",
                )
            findings = _collect_frontmatter_findings(path)
        self.assertTrue(any("': '" in f for f in findings))


if __name__ == "__main__":
    unittest.main()
