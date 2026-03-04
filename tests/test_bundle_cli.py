import contextlib
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock


SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUNDLE_SCRIPT = os.path.join(SCRIPTS_DIR, "bundle.py")

import bundle


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class CLISmokeTests(unittest.TestCase):
    def test_output_parent_directory_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "system")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            _write(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            _write(
                os.path.join(skill_dir, "SKILL.md"),
                textwrap.dedent(
                    """\
                    ---
                    name: demo-skill
                    description: Packages a minimal demo skill for bundling smoke tests.
                    ---

                    # Demo Skill
                    """
                ),
            )

            output_path = os.path.join(tmpdir, "dist", "nested", "demo-skill.zip")
            proc = subprocess.run(
                [sys.executable, BUNDLE_SCRIPT, skill_dir, "--output", output_path],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertTrue(os.path.exists(output_path))

    def test_without_inferred_system_root_external_reference_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            shared_dir = os.path.join(tmpdir, "shared")
            _write(os.path.join(shared_dir, "guide.md"), "# Guide\n")
            _write(
                os.path.join(skill_dir, "SKILL.md"),
                textwrap.dedent(
                    """\
                    ---
                    name: demo-skill
                    description: Tests system-root inference safety behavior.
                    ---

                    # Demo Skill

                    See [Guide](../shared/guide.md).
                    """
                ),
            )

            proc = subprocess.run(
                [sys.executable, BUNDLE_SCRIPT, skill_dir],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 1)
            self.assertIn(
                "Found 1 external reference(s) but no system root could be determined",
                proc.stdout,
            )


class MainErrorHandlingTests(unittest.TestCase):
    def test_unexpected_create_bundle_error_is_reported_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            _write(
                os.path.join(skill_dir, "SKILL.md"),
                textwrap.dedent(
                    """\
                    ---
                    name: demo-skill
                    description: Tests unexpected bundle errors.
                    ---

                    # Demo Skill
                    """
                ),
            )

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


if __name__ == "__main__":
    unittest.main()
