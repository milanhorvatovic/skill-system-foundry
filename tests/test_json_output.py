"""Tests for --json flag across all CLI tools.

Covers JSON output for validate_skill.py, audit_skill_system.py,
scaffold.py, and bundle.py, plus the shared JSON helpers in
reporting.py.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import write_text, write_skill_md

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, "validate_skill.py")
AUDIT_SCRIPT = os.path.join(SCRIPTS_DIR, "audit_skill_system.py")
SCAFFOLD_SCRIPT = os.path.join(SCRIPTS_DIR, "scaffold.py")
BUNDLE_SCRIPT = os.path.join(SCRIPTS_DIR, "bundle.py")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.reporting import categorize_errors_for_json, to_json_output
from lib.constants import LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO, JSON_SCHEMA_VERSION


def _run(script: str, args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Run a script with *args* in *cwd* and return the result."""
    return subprocess.run(
        [sys.executable, script] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _parse_json(stdout: str) -> dict:
    """Parse stdout as a single JSON object.

    All CLI tools emit pure JSON to stdout in ``--json`` mode (human-
    readable output is suppressed).  This helper simply deserializes
    the output; it will raise on any non-JSON content.
    """
    return json.loads(stdout)


# ===================================================================
# reporting.py — JSON helpers
# ===================================================================


class ToJsonOutputTests(unittest.TestCase):
    """Tests for the to_json_output helper."""

    def test_returns_valid_json(self) -> None:
        """Output is valid JSON."""
        data = {"key": "value", "count": 42}
        result = to_json_output(data)
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "value")
        self.assertEqual(parsed["count"], 42)

    def test_keys_are_sorted(self) -> None:
        """Keys are sorted for deterministic output."""
        data = {"zebra": 1, "alpha": 2}
        result = to_json_output(data)
        parsed = json.loads(result)
        keys = list(parsed.keys())
        self.assertEqual(keys, ["alpha", "zebra"])

    def test_empty_dict(self) -> None:
        """An empty dict produces valid JSON."""
        result = to_json_output({})
        self.assertEqual(json.loads(result), {})

    def test_version_injected_when_tool_key_present(self) -> None:
        """A dict with a 'tool' key gets 'version' auto-injected."""
        data = {"tool": "test_tool", "success": True}
        result = to_json_output(data)
        parsed = json.loads(result)
        self.assertEqual(parsed["version"], JSON_SCHEMA_VERSION)

    def test_version_not_injected_without_tool_key(self) -> None:
        """A dict without a 'tool' key does NOT get 'version' injected."""
        data = {"key": "value"}
        result = to_json_output(data)
        parsed = json.loads(result)
        self.assertNotIn("version", parsed)

    def test_explicit_version_not_overwritten(self) -> None:
        """An explicit 'version' key is not overwritten by auto-injection."""
        data = {"tool": "test_tool", "version": 99}
        result = to_json_output(data)
        parsed = json.loads(result)
        self.assertEqual(parsed["version"], 99)


class CategorizeErrorsForJsonTests(unittest.TestCase):
    """Tests for the categorize_errors_for_json helper."""

    def test_categorizes_by_level(self) -> None:
        """Errors are split into failures, warnings, and info."""
        errors = [
            f"{LEVEL_FAIL}: name is too long",
            f"{LEVEL_WARN}: description uses imperative",
            f"{LEVEL_INFO}: unrecognized key",
        ]
        result = categorize_errors_for_json(errors)
        self.assertEqual(result["failures"], ["name is too long"])
        self.assertEqual(result["warnings"], ["description uses imperative"])
        self.assertEqual(result["info"], ["unrecognized key"])

    def test_empty_errors(self) -> None:
        """Empty error list produces empty categories."""
        result = categorize_errors_for_json([])
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["info"], [])

    def test_strips_level_prefix(self) -> None:
        """The level prefix is stripped from each message."""
        errors = [f"{LEVEL_FAIL}: something broke"]
        result = categorize_errors_for_json(errors)
        self.assertEqual(result["failures"], ["something broke"])
        # Should not contain the prefix
        self.assertNotIn(LEVEL_FAIL, result["failures"][0])


# ===================================================================
# validate_skill.py --json
# ===================================================================


class ValidateSkillJsonTests(unittest.TestCase):
    """Tests for validate_skill.py --json output."""

    def test_valid_skill_json_output(self) -> None:
        """A valid skill produces JSON with success=true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            proc = _run(VALIDATE_SCRIPT, [skill_dir, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertEqual(data["tool"], "validate_skill")
        self.assertTrue(data["success"])
        self.assertEqual(data["type"], "registered skill")
        self.assertEqual(data["summary"]["failures"], 0)
        self.assertIn("errors", data)

    def test_invalid_skill_json_output(self) -> None:
        """A skill with FAIL errors produces JSON with success=false."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            os.makedirs(skill_dir)
            # No SKILL.md — triggers FAIL
            proc = _run(VALIDATE_SCRIPT, [skill_dir, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertGreater(data["summary"]["failures"], 0)
        self.assertGreater(len(data["errors"]["failures"]), 0)

    def test_warn_only_json_exits_zero(self) -> None:
        """A skill with only WARN errors exits 0 with success=true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(
                skill_dir,
                description="Process data files and generate reports.",
            )
            proc = _run(VALIDATE_SCRIPT, [skill_dir, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertTrue(data["success"])
        self.assertGreater(data["summary"]["warnings"], 0)

    def test_json_verbose_includes_passes(self) -> None:
        """--json --verbose includes the passes list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            proc = _run(
                VALIDATE_SCRIPT,
                [skill_dir, "--json", "--verbose"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertIn("passes", data)
        self.assertIsInstance(data["passes"], list)
        self.assertGreater(len(data["passes"]), 0)

    def test_json_without_verbose_omits_passes(self) -> None:
        """--json without --verbose omits the passes list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            proc = _run(VALIDATE_SCRIPT, [skill_dir, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertNotIn("passes", data)

    def test_json_capability_type(self) -> None:
        """--json --capability shows type as 'capability'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# My Capability\n",
            )
            proc = _run(
                VALIDATE_SCRIPT,
                [cap_dir, "--capability", "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertEqual(data["type"], "capability")

    def test_json_non_directory_error(self) -> None:
        """--json with a non-directory path produces JSON error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "not-a-dir.txt")
            write_text(file_path, "content")
            proc = _run(VALIDATE_SCRIPT, [file_path, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("not a directory", data["error"])

    def test_json_output_is_valid_json(self) -> None:
        """The entire stdout is parseable as JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            proc = _run(VALIDATE_SCRIPT, [skill_dir, "--json"], cwd=REPO_ROOT)
        # Should not raise
        json.loads(proc.stdout)

    def test_json_includes_version(self) -> None:
        """JSON output includes the schema version field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            proc = _run(VALIDATE_SCRIPT, [skill_dir, "--json"], cwd=REPO_ROOT)
        data = _parse_json(proc.stdout)
        self.assertEqual(data["version"], JSON_SCHEMA_VERSION)

    def test_json_no_path_produces_json_error(self) -> None:
        """--json with no skill path produces a JSON error (via argparse)."""
        proc = _run(VALIDATE_SCRIPT, ["--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_json_no_human_output_mixed_in(self) -> None:
        """--json suppresses human-readable output (no 'Validating:' line)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            proc = _run(VALIDATE_SCRIPT, [skill_dir, "--json"], cwd=REPO_ROOT)
        self.assertNotIn("Validating:", proc.stdout)
        self.assertNotIn("---", proc.stdout.split("{")[0])


# ===================================================================
# audit_skill_system.py --json
# ===================================================================


class AuditSkillSystemJsonTests(unittest.TestCase):
    """Tests for audit_skill_system.py --json output."""

    def test_valid_system_json_output(self) -> None:
        """A valid skill system produces JSON with success=true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            proc = _run(AUDIT_SCRIPT, [tmpdir, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertEqual(data["tool"], "audit_skill_system")
        self.assertTrue(data["success"])
        self.assertEqual(data["summary"]["failures"], 0)

    def test_invalid_system_json_output(self) -> None:
        """A system with FAIL errors produces JSON with success=false."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "# Demo Skill\n\nNo frontmatter.\n",
            )
            proc = _run(AUDIT_SCRIPT, [tmpdir, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertGreater(data["summary"]["failures"], 0)

    def test_json_no_arguments_error(self) -> None:
        """--json with no system root produces JSON error."""
        proc = _run(AUDIT_SCRIPT, ["--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_json_non_directory_error(self) -> None:
        """--json with a non-directory path produces JSON error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "not-a-dir.txt")
            write_text(file_path, "content")
            proc = _run(AUDIT_SCRIPT, [file_path, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("not a directory", data["error"])

    def test_json_suppresses_verbose_terminal_output(self) -> None:
        """--json suppresses human-readable output even with --verbose."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            proc = _run(
                AUDIT_SCRIPT,
                [tmpdir, "--json", "--verbose"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        # Should be valid JSON without human-readable lines mixed in
        data = json.loads(proc.stdout)
        self.assertTrue(data["success"])
        # Should not contain section headers
        self.assertNotIn("Spec Compliance", proc.stdout)

    def test_json_output_is_valid_json(self) -> None:
        """The entire stdout is parseable as JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            proc = _run(AUDIT_SCRIPT, [tmpdir, "--json"], cwd=REPO_ROOT)
        json.loads(proc.stdout)

    def test_json_includes_version(self) -> None:
        """JSON output includes the schema version field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            proc = _run(AUDIT_SCRIPT, [tmpdir, "--json"], cwd=REPO_ROOT)
        data = _parse_json(proc.stdout)
        self.assertEqual(data["version"], JSON_SCHEMA_VERSION)

    def test_json_includes_component_counts(self) -> None:
        """JSON output includes counts of skills, capabilities, and roles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a skill
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            proc = _run(AUDIT_SCRIPT, [tmpdir, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertIn("counts", data)
        counts = data["counts"]
        self.assertIn("skills", counts)
        self.assertIn("capabilities", counts)
        self.assertIn("roles", counts)
        self.assertEqual(counts["skills"], 1)
        self.assertEqual(counts["capabilities"], 0)
        self.assertEqual(counts["roles"], 0)

    def test_json_no_path_produces_json_error(self) -> None:
        """--json with no system root produces a JSON error (via argparse)."""
        proc = _run(AUDIT_SCRIPT, ["--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_json_warn_only_exits_zero(self) -> None:
        """A system with only WARN errors exits 0 with success=true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            # Missing manifest triggers WARN, not FAIL
            proc = _run(AUDIT_SCRIPT, [tmpdir, "--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertTrue(data["success"])


# ===================================================================
# scaffold.py --json
# ===================================================================


class ScaffoldJsonTests(unittest.TestCase):
    """Tests for scaffold.py --json output."""

    def test_skill_json_output(self) -> None:
        """Scaffolding a skill with --json produces JSON with success=true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                SCAFFOLD_SCRIPT,
                ["skill", "my-skill", "--root", tmpdir, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertEqual(data["tool"], "scaffold")
        self.assertEqual(data["component"], "skill")
        self.assertEqual(data["name"], "my-skill")
        self.assertTrue(data["success"])
        self.assertIn("path", data)
        self.assertIn("created_paths", data)
        self.assertIsInstance(data["created_paths"], list)
        self.assertGreater(len(data["created_paths"]), 0)

    def test_router_skill_json_output(self) -> None:
        """Scaffolding a router skill with --json includes router=true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                SCAFFOLD_SCRIPT,
                ["skill", "my-router", "--router", "--root", tmpdir, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertTrue(data["success"])
        self.assertTrue(data["router"])

    def test_capability_json_output(self) -> None:
        """Scaffolding a capability with --json produces JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create router prerequisite
            _run(
                SCAFFOLD_SCRIPT,
                ["skill", "my-domain", "--router", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            proc = _run(
                SCAFFOLD_SCRIPT,
                ["capability", "my-domain", "my-cap", "--root", tmpdir, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertEqual(data["component"], "capability")
        self.assertEqual(data["name"], "my-cap")
        self.assertEqual(data["domain"], "my-domain")
        self.assertTrue(data["success"])

    def test_role_json_output(self) -> None:
        """Scaffolding a role with --json produces JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                SCAFFOLD_SCRIPT,
                ["role", "my-group", "my-role", "--root", tmpdir, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertEqual(data["component"], "role")
        self.assertEqual(data["name"], "my-role")
        self.assertEqual(data["group"], "my-group")
        self.assertTrue(data["success"])

    def test_invalid_name_json_output(self) -> None:
        """An invalid name with --json produces JSON with success=false."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = _run(
                SCAFFOLD_SCRIPT,
                ["skill", "INVALID-NAME", "--root", tmpdir, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_duplicate_skill_json_output(self) -> None:
        """Scaffolding a duplicate skill with --json produces JSON error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create first
            _run(
                SCAFFOLD_SCRIPT,
                ["skill", "my-skill", "--root", tmpdir],
                cwd=REPO_ROOT,
            )
            # Try duplicate
            proc = _run(
                SCAFFOLD_SCRIPT,
                ["skill", "my-skill", "--root", tmpdir, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("already exists", data["error"])

    def test_no_args_json_output(self) -> None:
        """No arguments with --json produces JSON error."""
        proc = _run(SCAFFOLD_SCRIPT, ["--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])

    def test_unknown_component_json_output(self) -> None:
        """Unknown component type with --json produces JSON error."""
        proc = _run(
            SCAFFOLD_SCRIPT,
            ["bogus", "x", "--json"],
            cwd=REPO_ROOT,
        )
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("Unknown component type", data["error"])

    def test_json_missing_root_path_produces_json_error(self) -> None:
        """--json with --root but no path argument produces JSON error."""
        proc = _run(
            SCAFFOLD_SCRIPT,
            ["skill", "demo", "--root", "--json"],
            cwd=REPO_ROOT,
        )
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("--root requires a path argument", data["error"])

    def test_json_root_at_end_without_value(self) -> None:
        """--json with --root as last arg (no value) produces JSON error."""
        proc = _run(
            SCAFFOLD_SCRIPT,
            ["--json", "skill", "demo", "--root"],
            cwd=REPO_ROOT,
        )
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("--root requires a path argument", data["error"])

    def test_json_root_flag_as_value_produces_json_error(self) -> None:
        """--root with another flag as value (e.g. --root --verbose) is rejected."""
        proc = _run(
            SCAFFOLD_SCRIPT,
            ["skill", "demo", "--root", "--with-references", "--json"],
            cwd=REPO_ROOT,
        )
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("--root requires a path argument", data["error"])


# ===================================================================
# bundle.py --json
# ===================================================================


class BundleJsonTests(unittest.TestCase):
    """Tests for bundle.py --json output."""

    def test_successful_bundle_json_output(self) -> None:
        """A successful bundle produces JSON with success=true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(
                os.path.join(system_root, "manifest.yaml"),
                "name: demo\n",
            )
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "demo-skill.zip")
            proc = _run(
                BUNDLE_SCRIPT,
                [skill_dir, "--output", output_path, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        data = _parse_json(proc.stdout)
        self.assertEqual(data["tool"], "bundle")
        self.assertTrue(data["success"])
        self.assertIn("output", data)
        self.assertIn("stats", data)
        self.assertIn("file_count", data["stats"])
        self.assertIn("archive_size", data["stats"])

    def test_failed_bundle_json_output(self) -> None:
        """A failed bundle produces JSON with success=false."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            os.makedirs(skill_dir)
            # No SKILL.md
            proc = _run(
                BUNDLE_SCRIPT,
                [skill_dir, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_json_suppresses_human_output(self) -> None:
        """--json suppresses human-readable phase output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(
                os.path.join(system_root, "manifest.yaml"),
                "name: demo\n",
            )
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "demo-skill.zip")
            proc = _run(
                BUNDLE_SCRIPT,
                [skill_dir, "--output", output_path, "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        # Should not contain human-readable phase headers
        self.assertNotIn("Phase 1:", proc.stdout)
        self.assertNotIn("Phase 2:", proc.stdout)
        self.assertNotIn("Phase 3:", proc.stdout)
        self.assertNotIn("Bundling:", proc.stdout)

    def test_json_output_is_valid_json(self) -> None:
        """The entire stdout is parseable as JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(
                os.path.join(system_root, "manifest.yaml"),
                "name: demo\n",
            )
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "demo-skill.zip")
            proc = _run(
                BUNDLE_SCRIPT,
                [skill_dir, "--output", output_path, "--json"],
                cwd=REPO_ROOT,
            )
        json.loads(proc.stdout)

    def test_json_no_args_produces_json_error(self) -> None:
        """--json with no skill path produces JSON error (via argparse)."""
        proc = _run(BUNDLE_SCRIPT, ["--json"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_json_invalid_target_produces_json_error(self) -> None:
        """--json with invalid --target choice produces JSON error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            os.makedirs(skill_dir)
            write_text(os.path.join(skill_dir, "SKILL.md"), "# Demo\n")
            proc = _run(
                BUNDLE_SCRIPT,
                [skill_dir, "--target", "invalid", "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)
        self.assertIn("invalid choice", data["error"])

    def test_json_unrecognized_argument_produces_json_error(self) -> None:
        """--json with unrecognized argument produces JSON error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            os.makedirs(skill_dir)
            write_text(os.path.join(skill_dir, "SKILL.md"), "# Demo\n")
            proc = _run(
                BUNDLE_SCRIPT,
                [skill_dir, "--bogus-flag", "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 1)
        data = _parse_json(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("error", data)
        self.assertIn("unrecognized arguments", data["error"])


if __name__ == "__main__":
    unittest.main()
