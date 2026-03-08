import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
