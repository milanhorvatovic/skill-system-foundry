"""Tests for ``.github/scripts/smoke-validate-extracted.py``.

The helper resolves the extracted skill directory and invokes
``validate_skill.py`` against it.  The previous inline one-liner
crashed with a ``TypeError`` when extraction did not produce a
top-level ``<skill-name>/SKILL.md`` layout — the helper turns that
into a clear failure with an actionable diagnostic.  Pin the
discovery shape and the missing-layout failure mode so a future
refactor cannot regress either branch silently.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from contextlib import redirect_stderr
from unittest import mock


_CI_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".github", "scripts")
)
_script_path = os.path.join(
    _CI_SCRIPTS_DIR, "smoke-validate-extracted.py"
)
_spec = importlib.util.spec_from_file_location(
    "smoke_validate_extracted", _script_path
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load module from {_script_path}")
smoke_validate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke_validate)


def _write(path: str, content: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


class FindSkillDirTests(unittest.TestCase):
    """``find_skill_dir`` resolves the extracted skill root deterministically."""

    def test_returns_top_level_dir_with_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_root = os.path.join(tmpdir, "demo")
            _write(os.path.join(skill_root, "SKILL.md"), "stub")
            self.assertEqual(
                smoke_validate.find_skill_dir(tmpdir), skill_root,
            )

    def test_returns_none_when_no_top_level_skill_md(self) -> None:
        # A nested ``SKILL.md`` (not at depth 1) must NOT match —
        # the bundle layout puts it at the top level by contract.
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "outer", "demo")
            _write(os.path.join(nested, "SKILL.md"), "stub")
            self.assertIsNone(smoke_validate.find_skill_dir(tmpdir))

    def test_returns_none_when_root_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, "does-not-exist")
            self.assertIsNone(smoke_validate.find_skill_dir(missing))

    def test_returns_none_when_root_has_no_directories(self) -> None:
        # An extraction that produced only loose files (no enclosing
        # directory) must not be treated as a valid skill root.
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "loose.txt"), "noise")
            self.assertIsNone(smoke_validate.find_skill_dir(tmpdir))

    def test_picks_first_sorted_match_when_multiple_candidates(self) -> None:
        # Two top-level directories both contain a SKILL.md — pick
        # the lexicographically first one so the smoke job is
        # deterministic across runners (Linux ext4 ordering differs
        # from Windows NTFS).
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "beta", "SKILL.md"), "b")
            _write(os.path.join(tmpdir, "alpha", "SKILL.md"), "a")
            self.assertEqual(
                smoke_validate.find_skill_dir(tmpdir),
                os.path.join(tmpdir, "alpha"),
            )


class MainTests(unittest.TestCase):
    """``main`` propagates validator exit code and surfaces clear errors."""

    def test_missing_layout_emits_clear_error_and_exits_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = StringIO()
            with redirect_stderr(stderr):
                rc = smoke_validate.main(
                    [tmpdir, "validate_skill.py"],
                )
            self.assertEqual(rc, 1)
            msg = stderr.getvalue()
            self.assertIn("no top-level directory", msg)
            self.assertIn(tmpdir, msg)
            self.assertIn("SKILL.md", msg)

    def test_missing_extracted_root_emits_clear_error(self) -> None:
        # ``find_skill_dir`` returns None for a missing root, then
        # ``main`` re-attempts ``os.listdir`` for diagnostics — that
        # OSError must be reported, not propagated as a traceback.
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, "does-not-exist")
            stderr = StringIO()
            with redirect_stderr(stderr):
                rc = smoke_validate.main(
                    [missing, "validate_skill.py"],
                )
            self.assertEqual(rc, 1)
            msg = stderr.getvalue()
            self.assertIn("cannot list extracted root", msg)
            self.assertIn(missing, msg)

    def test_propagates_validator_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_root = os.path.join(tmpdir, "demo")
            _write(os.path.join(skill_root, "SKILL.md"), "stub")
            with mock.patch.object(
                smoke_validate.subprocess, "call", return_value=7,
            ) as call_mock:
                rc = smoke_validate.main(
                    [tmpdir, "/path/to/validate_skill.py"],
                )
            self.assertEqual(rc, 7)
            call_mock.assert_called_once_with(
                [sys.executable, "/path/to/validate_skill.py", skill_root],
            )


class CliEntrypointTests(unittest.TestCase):
    """The script is invokable as a CLI and propagates exit codes."""

    def test_cli_exits_non_zero_on_missing_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    _script_path,
                    tmpdir,
                    "/path/to/validate_skill.py",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("no top-level directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
