import collections.abc
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

from helpers import write_skill_md, write_text


SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUNDLE_SCRIPT = os.path.join(SCRIPTS_DIR, "bundle.py")

import bundle
from lib.constants import (
    BUNDLE_DESCRIPTION_MAX_LENGTH,
    LEVEL_FAIL,
    LEVEL_WARN,
    SEPARATOR_WIDTH,
)


class CLISmokeTests(unittest.TestCase):
    def test_no_args_prints_docstring_usage(self) -> None:
        proc = subprocess.run(
            [sys.executable, BUNDLE_SCRIPT],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("Bundle a skill into a self-contained zip bundle", proc.stdout)
        self.assertIn("Usage:", proc.stdout)

    def test_output_parent_directory_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            write_skill_md(skill_dir)

            output_path = os.path.join(tmpdir, "dist", "nested", "demo-skill.zip")
            proc = subprocess.run(
                [sys.executable, BUNDLE_SCRIPT, skill_dir, "--output", output_path],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertTrue(os.path.exists(output_path))

    def test_invalid_system_root_markers_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "not-a-system-root")
            skill_dir = os.path.join(system_root, "demo-skill")
            # Keep skill inside provided root, but omit both manifest.yaml
            # and skills/ so root-shape validation fails.
            write_skill_md(skill_dir)

            proc = subprocess.run(
                [
                    sys.executable,
                    BUNDLE_SCRIPT,
                    skill_dir,
                    "--system-root",
                    system_root,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 1)
            self.assertIn("does not look like a skill system root", proc.stdout)
            self.assertIn("Provide a valid --system-root", proc.stdout)

    def test_output_directory_argument_writes_skill_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            output_dir = os.path.join(tmpdir, "dist")
            os.makedirs(output_dir, exist_ok=True)
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            write_skill_md(skill_dir)

            proc = subprocess.run(
                [sys.executable, BUNDLE_SCRIPT, skill_dir, "--output", output_dir],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "demo-skill.zip")))

    def test_zip_entries_use_forward_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            output_path = os.path.join(tmpdir, "bundle.zip")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            write_skill_md(skill_dir)

            proc = subprocess.run(
                [sys.executable, BUNDLE_SCRIPT, skill_dir, "--output", output_path],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            with zipfile.ZipFile(output_path, "r") as zf:
                names = zf.namelist()
            self.assertIn("demo-skill/SKILL.md", names)
            self.assertTrue(all("\\" not in name for name in names))

    def test_without_inferred_system_root_external_reference_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            shared_dir = os.path.join(tmpdir, "shared")
            write_text(os.path.join(shared_dir, "guide.md"), "# Guide\n")
            write_skill_md(
                skill_dir,
                description="Tests system-root inference safety behavior.",
                body="# Demo Skill\n\nSee [Guide](../shared/guide.md).\n",
            )

            proc = subprocess.run(
                [sys.executable, BUNDLE_SCRIPT, skill_dir],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 1)
            self.assertIn(
                "resolves outside the skill directory but no system root "
                "is available to enforce safety boundaries",
                proc.stdout,
            )


class MainErrorHandlingTests(unittest.TestCase):
    def test_unexpected_create_bundle_error_is_reported_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "manifest.yaml"), "name: demo\n")
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, description="Tests unexpected bundle errors.")

            output_path = os.path.join(tmpdir, "dist", "demo-skill.zip")
            fake_scan = {
                "external_files": set(),
                "errors": [],
                "warnings": [],
                "reference_map": {},
            }
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "bundle.py",
                        skill_dir,
                        "--system-root",
                        tmpdir,
                        "--output",
                        output_path,
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch("bundle.create_bundle", side_effect=RuntimeError("boom")),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()

            self.assertEqual(cm.exception.code, 1)
            self.assertIn("Bundling FAILED — unexpected error:", stdout.getvalue())
            self.assertIn(
                "FAIL: Unexpected error during bundle creation: RuntimeError: boom.",
                stdout.getvalue(),
            )
            self.assertEqual(stderr.getvalue(), "")

    def test_verbose_flag_prints_traceback_for_unexpected_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "manifest.yaml"), "name: demo\n")
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, description="Tests verbose traceback behavior.")

            output_path = os.path.join(tmpdir, "dist", "demo-skill.zip")
            fake_scan = {
                "external_files": set(),
                "errors": [],
                "warnings": [],
                "reference_map": {},
            }
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "bundle.py",
                        skill_dir,
                        "--system-root",
                        tmpdir,
                        "--output",
                        output_path,
                        "--verbose",
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch("bundle.create_bundle", side_effect=RuntimeError("boom")),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()

            self.assertEqual(cm.exception.code, 1)
            self.assertIn("Bundling FAILED — unexpected error:", stdout.getvalue())
            self.assertIn("Traceback", stderr.getvalue())


class InlineOrchestratedSkillsCLITests(unittest.TestCase):
    """CLI tests for --inline-orchestrated-skills flag."""

    def _create_path1_layout(self, tmpdir: str) -> tuple[str, str]:
        """Create a Path 1 coordination skill layout.

        Returns (system_root, coordinator_skill_path).
        """
        system_root = os.path.join(tmpdir, "root")

        coordinator = os.path.join(system_root, "skills", "release-coordinator")
        write_text(
            os.path.join(coordinator, "SKILL.md"),
            "---\n"
            "name: release-coordinator\n"
            "description: Coordinates release workflows across domains.\n"
            "---\n\n"
            "# Release Coordinator\n\n"
            "Delegate to roles:\n"
            "- [QA Role](../../roles/qa-role.md)\n",
        )

        testing = os.path.join(system_root, "skills", "testing")
        write_text(
            os.path.join(testing, "SKILL.md"),
            "---\nname: testing\ndescription: Testing domain skill.\n---\n\n# Testing\n",
        )

        write_text(
            os.path.join(system_root, "roles", "qa-role.md"),
            "# QA Role\n\n"
            "Follow: [Testing](../skills/testing/SKILL.md)\n",
        )

        write_text(os.path.join(system_root, "manifest.yaml"), "name: test-system\n")

        return system_root, coordinator

    def test_inline_flag_produces_zip_with_capabilities(self) -> None:
        """The --inline-orchestrated-skills flag produces a valid zip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, coordinator = self._create_path1_layout(tmpdir)
            output_path = os.path.join(tmpdir, "release-coordinator.zip")

            proc = subprocess.run(
                [
                    sys.executable,
                    BUNDLE_SCRIPT,
                    coordinator,
                    "--system-root",
                    system_root,
                    "--output",
                    output_path,
                    "--inline-orchestrated-skills",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertTrue(os.path.exists(output_path))

            with zipfile.ZipFile(output_path, "r") as zf:
                names = zf.namelist()

            self.assertIn("release-coordinator/SKILL.md", names)
            self.assertIn(
                "release-coordinator/capabilities/testing/capability.md",
                names,
            )
            self.assertIn("release-coordinator/roles/qa-role.md", names)
            # No SKILL.md inside capabilities
            skill_md_entries = [n for n in names if n.endswith("/SKILL.md")]
            self.assertEqual(len(skill_md_entries), 1)  # Only the top-level one

    def test_inline_flag_with_output_directory(self) -> None:
        """--inline-orchestrated-skills with --output <directory> auto-names zip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, coordinator = self._create_path1_layout(tmpdir)
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(output_dir)

            proc = subprocess.run(
                [
                    sys.executable,
                    BUNDLE_SCRIPT,
                    coordinator,
                    "--system-root",
                    system_root,
                    "--output",
                    output_dir,
                    "--inline-orchestrated-skills",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            # Zip should be auto-named inside the directory
            zip_files = [f for f in os.listdir(output_dir) if f.endswith(".zip")]
            self.assertEqual(len(zip_files), 1, f"Expected 1 zip, got: {zip_files}")
            zip_path = os.path.join(output_dir, zip_files[0])

            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()

            self.assertIn("release-coordinator/SKILL.md", names)
            self.assertIn(
                "release-coordinator/capabilities/testing/capability.md",
                names,
            )

    def test_without_flag_cross_skill_fails_cli(self) -> None:
        """Without the flag, cross-skill references still fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, coordinator = self._create_path1_layout(tmpdir)
            output_path = os.path.join(tmpdir, "release-coordinator.zip")

            proc = subprocess.run(
                [
                    sys.executable,
                    BUNDLE_SCRIPT,
                    coordinator,
                    "--system-root",
                    system_root,
                    "--output",
                    output_path,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 1)
            self.assertIn("Cross-skill reference", proc.stdout)


class TargetFlagTests(unittest.TestCase):
    """Tests for the --target CLI flag."""

    def _make_skill_with_long_desc(self, skill_dir: str, desc: str) -> None:
        """Write a SKILL.md with the given description."""
        write_skill_md(skill_dir, description=desc)

    def test_target_claude_long_desc_fails(self) -> None:
        """--target claude (default) rejects descriptions exceeding the limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            long_desc = "A" * (BUNDLE_DESCRIPTION_MAX_LENGTH + 1)
            self._make_skill_with_long_desc(skill_dir, long_desc)

            proc = subprocess.run(
                [sys.executable, BUNDLE_SCRIPT, skill_dir, "--target", "claude"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 1)
            expected_len = BUNDLE_DESCRIPTION_MAX_LENGTH + 1
            self.assertIn(f"Description is {expected_len} characters", proc.stdout)

    def test_target_gemini_long_desc_warns_not_fails(self) -> None:
        """--target gemini downgrades the description length error to a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            long_desc = "A" * (BUNDLE_DESCRIPTION_MAX_LENGTH + 1)
            self._make_skill_with_long_desc(skill_dir, long_desc)
            output_path = os.path.join(tmpdir, "demo-skill.zip")

            proc = subprocess.run(
                [
                    sys.executable, BUNDLE_SCRIPT, skill_dir,
                    "--target", "gemini",
                    "--output", output_path,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            expected_len = BUNDLE_DESCRIPTION_MAX_LENGTH + 1
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn(f"Description is {expected_len} characters", proc.stdout)
            self.assertTrue(os.path.exists(output_path))

    def test_target_generic_long_desc_warns_not_fails(self) -> None:
        """--target generic downgrades the description length error to a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            long_desc = "A" * (BUNDLE_DESCRIPTION_MAX_LENGTH + 1)
            self._make_skill_with_long_desc(skill_dir, long_desc)
            output_path = os.path.join(tmpdir, "demo-skill.zip")

            proc = subprocess.run(
                [
                    sys.executable, BUNDLE_SCRIPT, skill_dir,
                    "--target", "generic",
                    "--output", output_path,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            expected_len = BUNDLE_DESCRIPTION_MAX_LENGTH + 1
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn(f"Description is {expected_len} characters", proc.stdout)
            self.assertTrue(os.path.exists(output_path))

    def test_invalid_target_rejected_by_argparse(self) -> None:
        """An unrecognized --target value is rejected by argparse."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            write_skill_md(skill_dir)

            proc = subprocess.run(
                [sys.executable, BUNDLE_SCRIPT, skill_dir, "--target", "unknown"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 1)  # parser.error() overridden to exit 1
            self.assertIn("invalid choice", proc.stderr)

    def test_default_target_is_claude(self) -> None:
        """Omitting --target defaults to claude (long desc fails)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            long_desc = "A" * (BUNDLE_DESCRIPTION_MAX_LENGTH + 1)
            self._make_skill_with_long_desc(skill_dir, long_desc)

            proc = subprocess.run(
                [sys.executable, BUNDLE_SCRIPT, skill_dir],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            expected_len = BUNDLE_DESCRIPTION_MAX_LENGTH + 1
            self.assertEqual(proc.returncode, 1)
            self.assertIn(f"Description is {expected_len} characters", proc.stdout)


# ===================================================================
# Helper for building mock-based in-process tests
# ===================================================================

def _make_fake_scan() -> dict:
    """Return a minimal fake scan result for mocked prevalidate."""
    return {
        "external_files": set(),
        "errors": [],
        "warnings": [],
        "reference_map": {},
        "inlined_skills": {},
    }


def _make_fake_stats(
    *,
    skill_name: str = "demo-skill",
    file_count: int = 1,
    total_size: int = 100,
    external_count: int = 0,
    rewrite_count: int = 0,
    inlined_skill_count: int = 0,
) -> dict:
    """Return a minimal fake stats dict for mocked create_bundle."""
    return {
        "skill_name": skill_name,
        "file_count": file_count,
        "total_size": total_size,
        "external_count": external_count,
        "rewrite_count": rewrite_count,
        "inlined_skill_count": inlined_skill_count,
    }


def _setup_bundling_env(tmpdir: str) -> tuple[str, str, str]:
    """Create a minimal bundling env. Returns (system_root, skill_dir, output_path)."""
    write_text(os.path.join(tmpdir, "manifest.yaml"), "name: demo\n")
    skill_dir = os.path.join(tmpdir, "demo-skill")
    write_skill_md(skill_dir)
    output_path = os.path.join(tmpdir, "out.zip")
    return tmpdir, skill_dir, output_path


def _create_zip_side_effect() -> collections.abc.Callable[[str, str], None]:
    """Return a side_effect for create_zip that writes a dummy zip."""
    def _side_effect(bundle_dir: str, out_path: str) -> None:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with zipfile.ZipFile(out_path, "w") as zf:
            zf.writestr("demo-skill/SKILL.md", "# demo\n")
    return _side_effect


# ===================================================================
# 1. FormatSizeTests
# ===================================================================

class FormatSizeTests(unittest.TestCase):
    """Tests for bundle._format_size() helper."""

    def test_bytes_below_1024(self) -> None:
        self.assertEqual(bundle._format_size(500), "500 B")

    def test_exactly_0_bytes(self) -> None:
        self.assertEqual(bundle._format_size(0), "0 B")

    def test_kilobytes(self) -> None:
        self.assertEqual(bundle._format_size(2048), "2.0 KB")

    def test_kilobytes_boundary(self) -> None:
        self.assertEqual(bundle._format_size(1024), "1.0 KB")

    def test_megabytes(self) -> None:
        self.assertEqual(bundle._format_size(5242880), "5.0 MB")

    def test_megabytes_boundary(self) -> None:
        self.assertEqual(bundle._format_size(1048576), "1.0 MB")


# ===================================================================
# 2. PrintFailureBlockTests
# ===================================================================

class PrintFailureBlockTests(unittest.TestCase):
    """Tests for bundle._print_failure_block() helper."""

    def test_errors_only(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            bundle._print_failure_block(
                "test failure",
                [f"{LEVEL_FAIL}: something broke"],
            )
        output = stdout.getvalue()
        self.assertIn("=" * SEPARATOR_WIDTH, output)
        self.assertIn("Bundling FAILED", output)
        self.assertIn("something broke", output)

    def test_errors_with_warnings(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            bundle._print_failure_block(
                "test failure",
                [f"{LEVEL_FAIL}: an error"],
                warnings=[f"{LEVEL_WARN}: a warning"],
            )
        output = stdout.getvalue()
        self.assertIn("an error", output)
        self.assertIn("a warning", output)

    def test_with_guidance(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            bundle._print_failure_block(
                "test failure",
                [f"{LEVEL_FAIL}: err"],
                guidance="Fix it now.",
            )
        output = stdout.getvalue()
        self.assertIn("Fix it now.", output)

    def test_without_guidance(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            bundle._print_failure_block(
                "test failure",
                [f"{LEVEL_FAIL}: err"],
            )
        output = stdout.getvalue()
        self.assertNotIn("Fix it now.", output)


# ===================================================================
# 3. WindowsConsoleReconfigureTests
# ===================================================================

class WindowsConsoleReconfigureTests(unittest.TestCase):
    """Tests for Windows console reconfiguration (lines 106-109)."""

    def test_reconfigure_called_when_available(self) -> None:
        """When stdout/stderr have reconfigure, it is called."""

        class FakeStreamWithReconfigure:
            def __init__(self) -> None:
                self.buffer: list[str] = []
                self.reconfigure_calls: list[dict] = []

            def write(self, s: str) -> int:
                self.buffer.append(s)
                return len(s)

            def flush(self) -> None:
                pass

            def reconfigure(self, **kwargs: str) -> None:
                self.reconfigure_calls.append(kwargs)

        fake_out = FakeStreamWithReconfigure()
        fake_err = FakeStreamWithReconfigure()

        with (
            mock.patch.object(sys, "argv", ["bundle.py"]),
            mock.patch.object(sys, "stdout", fake_out),
            mock.patch.object(sys, "stderr", fake_err),
        ):
            with self.assertRaises(SystemExit):
                bundle.main()

        self.assertTrue(
            any(c.get("errors") == "replace" for c in fake_out.reconfigure_calls),
            "reconfigure(errors='replace') should be called on stdout",
        )
        self.assertTrue(
            any(c.get("errors") == "replace" for c in fake_err.reconfigure_calls),
            "reconfigure(errors='replace') should be called on stderr",
        )

    def test_no_reconfigure_when_missing(self) -> None:
        """When stdout/stderr lack reconfigure, no AttributeError."""

        class FakeStreamWithoutReconfigure:
            def __init__(self) -> None:
                self.buffer: list[str] = []

            def write(self, s: str) -> int:
                self.buffer.append(s)
                return len(s)

            def flush(self) -> None:
                pass

        fake_out = FakeStreamWithoutReconfigure()
        fake_err = FakeStreamWithoutReconfigure()

        with (
            mock.patch.object(sys, "argv", ["bundle.py"]),
            mock.patch.object(sys, "stdout", fake_out),
            mock.patch.object(sys, "stderr", fake_err),
        ):
            with self.assertRaises(SystemExit):
                bundle.main()

        # No AttributeError means the hasattr branch was skipped correctly.
        self.assertFalse(hasattr(fake_out, "reconfigure"))
        self.assertFalse(hasattr(fake_err, "reconfigure"))


# ===================================================================
# 4. NoArgsInProcessTests
# ===================================================================

class NoArgsInProcessTests(unittest.TestCase):
    """In-process test for no-arguments path (lines 111-114)."""

    def test_no_args_prints_usage_and_exits_1(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["bundle.py"]),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as cm:
                bundle.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("Usage:", stdout.getvalue())


# ===================================================================
# 5. CliAwareErrorTests
# ===================================================================

class CliAwareErrorTests(unittest.TestCase):
    """Tests for _cli_aware_error() parser override (lines 190-201)."""

    def test_invalid_target_human_mode(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                sys, "argv",
                ["bundle.py", "some-skill", "--target", "invalid"],
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as cm:
                bundle.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_invalid_target_json_mode(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                sys, "argv",
                ["bundle.py", "some-skill", "--target", "invalid", "--json"],
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as cm:
                bundle.main()
        self.assertEqual(cm.exception.code, 1)
        result = json.loads(stdout.getvalue())
        self.assertFalse(result["success"])
        self.assertIn("invalid choice", result["error"])


# ===================================================================
# 6. InputValidationTests
# ===================================================================

class InputValidationTests(unittest.TestCase):
    """In-process tests for fast-fail input validation branches."""

    def test_skill_path_not_a_directory_human(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                sys, "argv",
                ["bundle.py", "/nonexistent/path/to/skill"],
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as cm:
                bundle.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn(LEVEL_FAIL, stdout.getvalue())
        self.assertIn("is not a directory", stdout.getvalue())

    def test_skill_path_not_a_directory_json(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                sys, "argv",
                ["bundle.py", "/nonexistent/path/to/skill", "--json"],
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as cm:
                bundle.main()
        self.assertEqual(cm.exception.code, 1)
        result = json.loads(stdout.getvalue())
        self.assertFalse(result["success"])
        self.assertIn("is not a directory", result["error"])

    def test_missing_skill_md_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "empty-skill")
            os.makedirs(skill_dir)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(sys, "argv", ["bundle.py", skill_dir]),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            self.assertIn(LEVEL_FAIL, stdout.getvalue())
            self.assertIn("SKILL.md", stdout.getvalue())

    def test_missing_skill_md_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "empty-skill")
            os.makedirs(skill_dir)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv", ["bundle.py", skill_dir, "--json"],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["success"])
            self.assertIn("SKILL.md", result["error"])

    def test_system_root_not_a_directory_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["bundle.py", skill_dir, "--system-root", "/nonexistent/root"],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            self.assertIn(LEVEL_FAIL, stdout.getvalue())
            self.assertIn("is not a directory", stdout.getvalue())

    def test_system_root_not_a_directory_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", "/nonexistent/root",
                        "--json",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["success"])
            self.assertIn("is not a directory", result["error"])

    def test_skill_not_within_system_root_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill-a")
            write_skill_md(skill_dir)
            other_root = os.path.join(tmpdir, "other-root")
            os.makedirs(other_root)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["bundle.py", skill_dir, "--system-root", other_root],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            self.assertIn(LEVEL_FAIL, stdout.getvalue())
            self.assertIn("is not within", stdout.getvalue())

    def test_skill_not_within_system_root_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill-a")
            write_skill_md(skill_dir)
            other_root = os.path.join(tmpdir, "other-root")
            os.makedirs(other_root)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", other_root,
                        "--json",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["success"])
            self.assertIn("is not within", result["error"])

    def test_system_root_missing_markers_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "bare-root")
            skill_dir = os.path.join(system_root, "demo-skill")
            write_skill_md(skill_dir)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["bundle.py", skill_dir, "--system-root", system_root],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("does not look like a skill system root", stdout.getvalue())

    def test_system_root_missing_markers_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "bare-root")
            skill_dir = os.path.join(system_root, "demo-skill")
            write_skill_md(skill_dir)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--json",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["success"])
            self.assertIn("does not look like a skill system root", result["error"])


# ===================================================================
# 7. SystemRootAutoCorrectionTests
# ===================================================================

class SystemRootAutoCorrectionTests(unittest.TestCase):
    """Tests for --system-root auto-correction (lines 271-286)."""

    def test_skills_dir_as_system_root_is_corrected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skills_dir = os.path.join(system_root, "skills")
            skill_dir = os.path.join(skills_dir, "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "out.zip")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", skills_dir,
                        "--output", output_path,
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            output = stdout.getvalue()
            self.assertIn("appears to be a", output)
            self.assertIn("skills/", output)

    def test_skills_dir_correction_json_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skills_dir = os.path.join(system_root, "skills")
            skill_dir = os.path.join(skills_dir, "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "out.zip")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", skills_dir,
                        "--output", output_path,
                        "--json",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            # In JSON mode, auto-correction note should not appear
            # but the command should succeed (exit 0)
            self.assertEqual(cm.exception.code, 0)
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["success"])


# ===================================================================
# 8. SystemRootInferenceTests
# ===================================================================

class SystemRootInferenceTests(unittest.TestCase):
    """Tests for system root inference (lines 313-329)."""

    def test_inferred_root_message_printed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "out.zip")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["bundle.py", skill_dir, "--output", output_path],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            self.assertIn("Inferred system root:", stdout.getvalue())

    def test_no_root_inferred_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Isolated skill with no recognizable parent structure
            skill_dir = os.path.join(tmpdir, "isolated-skill")
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "out.zip")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["bundle.py", skill_dir, "--output", output_path],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Bundling may succeed or fail depending on skill content,
                # but the warning should be emitted either way.
                try:
                    bundle.main()
                except SystemExit:
                    pass
            self.assertIn("Could not infer system root", stdout.getvalue())


# ===================================================================
# 9. OutputPathEdgeCaseTests
# ===================================================================

class OutputPathEdgeCaseTests(unittest.TestCase):
    """Tests for output path resolution edge cases."""

    def _setup_skill(self, tmpdir: str) -> tuple[str, str]:
        """Create a minimal skill for bundling. Returns (system_root, skill_dir)."""
        system_root = os.path.join(tmpdir, "root")
        skill_dir = os.path.join(system_root, "skills", "demo-skill")
        write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
        write_skill_md(skill_dir)
        return system_root, skill_dir

    def test_trailing_separator_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir = self._setup_skill(tmpdir)
            output_dir = os.path.join(tmpdir, "dist") + os.sep

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_dir,
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            expected_zip = os.path.join(tmpdir, "dist", "demo-skill.zip")
            self.assertTrue(os.path.exists(expected_zip))

    def test_altsep_trailing_separator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir = self._setup_skill(tmpdir)
            output_dir = os.path.join(tmpdir, "dist") + "/"

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_dir,
                    ],
                ),
                mock.patch("bundle.os.altsep", "/"),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            expected_zip = os.path.join(tmpdir, "dist", "demo-skill.zip")
            self.assertTrue(os.path.exists(expected_zip))

    def test_default_output_in_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir = self._setup_skill(tmpdir)
            fake_cwd = os.path.join(tmpdir, "fake-cwd")
            os.makedirs(fake_cwd)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["bundle.py", skill_dir, "--system-root", system_root],
                ),
                mock.patch("bundle.os.getcwd", return_value=fake_cwd),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            expected_zip = os.path.join(fake_cwd, "demo-skill.zip")
            self.assertTrue(os.path.exists(expected_zip))


# ===================================================================
# 10. ValueErrorHandlerTests
# ===================================================================

class ValueErrorHandlerTests(unittest.TestCase):
    """Tests for ValueError exception handler (lines 483-490)."""

    def test_value_error_human_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "manifest.yaml"), "name: demo\n")
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "out.zip")

            fake_scan = _make_fake_scan()
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", tmpdir,
                        "--output", output_path,
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    side_effect=ValueError("bad input"),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            output = stdout.getvalue()
            self.assertIn("Bundling FAILED", output)
            self.assertIn("bad input", output)

    def test_value_error_json_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "manifest.yaml"), "name: demo\n")
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "out.zip")

            fake_scan = _make_fake_scan()
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", tmpdir,
                        "--output", output_path,
                        "--json",
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    side_effect=ValueError("bad input"),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["success"])
            self.assertIn("bad input", result["error"])


# ===================================================================
# 11. GenericExceptionJsonTests
# ===================================================================

class GenericExceptionJsonTests(unittest.TestCase):
    """Test generic Exception handler in JSON mode (lines 492-506)."""

    def test_unexpected_error_json_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "manifest.yaml"), "name: demo\n")
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            output_path = os.path.join(tmpdir, "out.zip")

            fake_scan = _make_fake_scan()
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", tmpdir,
                        "--output", output_path,
                        "--json",
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    side_effect=RuntimeError("boom"),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["success"])
            self.assertIn("Unexpected error", result["error"])


# ===================================================================
# 12. JsonOutputTests
# ===================================================================

class JsonOutputTests(unittest.TestCase):
    """Tests for JSON output paths (success, warnings, failures)."""

    def test_json_success_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats()

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                        "--json",
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=[]),
                mock.patch(
                    "bundle.create_zip",
                    side_effect=_create_zip_side_effect(),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 0)
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["success"])
            self.assertIn("stats", result)
            self.assertEqual(result["output"], output_path)
            self.assertTrue(
                os.path.exists(output_path),
                "Archive file should exist after successful JSON bundle",
            )
            self.assertEqual(result["stats"]["skill_name"], "demo-skill")

    def test_json_success_with_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats()
            warn_msg = f"{LEVEL_WARN}: Some concern"

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                        "--json",
                    ],
                ),
                mock.patch(
                    "bundle.prevalidate",
                    return_value=([], [warn_msg], fake_scan),
                ),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=[]),
                mock.patch(
                    "bundle.create_zip",
                    side_effect=_create_zip_side_effect(),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 0)
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["success"])
            self.assertIn("warnings", result)
            # The WARN prefix must be fully stripped — assert exact value
            self.assertIn("Some concern", result["warnings"])
            # No warning entry should still carry the LEVEL_WARN prefix
            for w in result["warnings"]:
                self.assertFalse(
                    w.startswith(LEVEL_WARN),
                    f"Warning still has LEVEL_WARN prefix: {w!r}",
                )

    def test_json_prevalidation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            errors = [f"{LEVEL_FAIL}: Something is wrong"]

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                        "--json",
                    ],
                ),
                mock.patch(
                    "bundle.prevalidate",
                    return_value=(errors, [], None),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["success"])
            self.assertEqual(result["phase"], "pre-validation")

    def test_json_postvalidation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats()
            post_errors = [f"{LEVEL_FAIL}: Post-validation issue"]

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                        "--json",
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=post_errors),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["success"])
            self.assertEqual(result["phase"], "post-validation")

    def test_json_missing_scan_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                        "--json",
                    ],
                ),
                mock.patch(
                    "bundle.prevalidate",
                    return_value=([], [], None),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["success"])
            self.assertIn("Internal error", result["error"])


# ===================================================================
# 13. HumanReadableSummaryTests
# ===================================================================

class HumanReadableSummaryTests(unittest.TestCase):
    """Tests for human-readable success summary output."""

    def test_success_summary_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats(file_count=5, total_size=2048)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=[]),
                mock.patch(
                    "bundle.create_zip",
                    side_effect=_create_zip_side_effect(),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            output = stdout.getvalue()
            self.assertIn("Bundle created:", output)
            self.assertIn("demo-skill", output)
            self.assertIn("5", output)

    def test_success_summary_with_external_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats(external_count=3)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=[]),
                mock.patch(
                    "bundle.create_zip",
                    side_effect=_create_zip_side_effect(),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            self.assertIn("External files:", stdout.getvalue())

    def test_success_summary_with_inlined_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats(inlined_skill_count=2)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=[]),
                mock.patch(
                    "bundle.create_zip",
                    side_effect=_create_zip_side_effect(),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            self.assertIn("Inlined skills:", stdout.getvalue())


# ===================================================================
# 14. HumanModePhaseOutputTests
# ===================================================================

class HumanModePhaseOutputTests(unittest.TestCase):
    """Tests for human-readable phase output lines."""

    def test_human_mode_phase_headers_printed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats()

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=[]),
                mock.patch(
                    "bundle.create_zip",
                    side_effect=_create_zip_side_effect(),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            output = stdout.getvalue()
            self.assertIn("Phase 1:", output)
            self.assertIn("Phase 2:", output)
            self.assertIn("Phase 3:", output)
            self.assertIn("Creating archive...", output)

    def test_human_mode_prevalidation_notices(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats()
            warn_msg = f"{LEVEL_WARN}: Watch out"

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                    ],
                ),
                mock.patch(
                    "bundle.prevalidate",
                    return_value=([], [warn_msg], fake_scan),
                ),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=[]),
                mock.patch(
                    "bundle.create_zip",
                    side_effect=_create_zip_side_effect(),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            output = stdout.getvalue()
            self.assertIn("Notices:", output)
            self.assertIn("Watch out", output)

    def test_human_mode_rewrite_count_printed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats(rewrite_count=3)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=[]),
                mock.patch(
                    "bundle.create_zip",
                    side_effect=_create_zip_side_effect(),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                # Human-readable success path does not call sys.exit()
                bundle.main()
            self.assertIn("Rewrote references", stdout.getvalue())

    def test_human_mode_prevalidation_failure(self) -> None:
        """Human-readable pre-validation failure prints failure block."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            errors = [f"{LEVEL_FAIL}: Something broke"]
            warnings = [f"{LEVEL_WARN}: Also watch this"]

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                    ],
                ),
                mock.patch(
                    "bundle.prevalidate",
                    return_value=(errors, warnings, None),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            output = stdout.getvalue()
            self.assertIn("Bundling FAILED", output)
            self.assertIn("pre-validation", output)

    def test_human_mode_postvalidation_failure(self) -> None:
        """Human-readable post-validation failure prints failure block."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)
            fake_scan = _make_fake_scan()
            fake_stats = _make_fake_stats()
            post_errors = [f"{LEVEL_FAIL}: Post issue"]

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                    ],
                ),
                mock.patch("bundle.prevalidate", return_value=([], [], fake_scan)),
                mock.patch(
                    "bundle.create_bundle",
                    return_value=("/tmp/fake-bundle", {}, fake_stats),
                ),
                mock.patch("bundle.postvalidate", return_value=post_errors),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            output = stdout.getvalue()
            self.assertIn("Bundling FAILED", output)
            self.assertIn("post-validation", output)

    def test_human_mode_missing_scan_result(self) -> None:
        """Human-readable missing scan result prints error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, skill_dir, output_path = _setup_bundling_env(tmpdir)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "bundle.py", skill_dir,
                        "--system-root", system_root,
                        "--output", output_path,
                    ],
                ),
                mock.patch(
                    "bundle.prevalidate",
                    return_value=([], [], None),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as cm:
                    bundle.main()
            self.assertEqual(cm.exception.code, 1)
            output = stdout.getvalue()
            self.assertIn(LEVEL_FAIL, output)
            self.assertIn("Internal error", output)


if __name__ == "__main__":
    unittest.main()
