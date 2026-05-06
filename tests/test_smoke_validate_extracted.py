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


class FindSkillDirsTests(unittest.TestCase):
    """``find_skill_dirs`` enumerates extracted skill roots deterministically."""

    def test_returns_single_match_for_clean_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_root = os.path.join(tmpdir, "demo")
            _write(os.path.join(skill_root, "SKILL.md"), "stub")
            self.assertEqual(
                smoke_validate.find_skill_dirs(tmpdir), [skill_root],
            )

    def test_only_walks_depth_one(self) -> None:
        """Nested SKILL.md (depth > 1) must not match.

        Pinned regression: the bundle contract is one top-level
        ``<skill-name>/`` entry per archive, so the helper walks
        only depth 1.  A future refactor that switched to
        ``os.walk`` would silently start matching nested files and
        let an unintended skill slip through the smoke validator;
        this test fails that refactor by construction.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "outer", "demo")
            _write(os.path.join(nested, "SKILL.md"), "stub")
            self.assertEqual(smoke_validate.find_skill_dirs(tmpdir), [])

    def test_returns_empty_when_root_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, "does-not-exist")
            self.assertEqual(smoke_validate.find_skill_dirs(missing), [])

    def test_returns_empty_when_root_has_no_directories(self) -> None:
        # An extraction that produced only loose files (no enclosing
        # directory) must not be treated as a valid skill root.
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "loose.txt"), "noise")
            self.assertEqual(smoke_validate.find_skill_dirs(tmpdir), [])

    def test_returns_every_match_in_sorted_order(self) -> None:
        # Two top-level directories both contain a SKILL.md.  The
        # helper now surfaces every candidate so the caller can
        # FAIL on the multi-match regression rather than silently
        # picking the alphabetically-first one.  Sorted output keeps
        # the failure message deterministic across runners (Linux
        # ext4 ordering differs from Windows NTFS).
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "beta", "SKILL.md"), "b")
            _write(os.path.join(tmpdir, "alpha", "SKILL.md"), "a")
            self.assertEqual(
                smoke_validate.find_skill_dirs(tmpdir),
                [
                    os.path.join(tmpdir, "alpha"),
                    os.path.join(tmpdir, "beta"),
                ],
            )


class MainTests(unittest.TestCase):
    """``main`` propagates validator exit code and surfaces clear errors."""

    def test_missing_layout_emits_clear_error_and_exits_non_zero(self) -> None:
        # The helper renders every path through ``to_posix`` so
        # finding text is byte-identical across Windows and POSIX
        # runners.  Compare on the ``to_posix``-normalised side too,
        # otherwise this assertion would pass on Linux/macOS but
        # fail on windows-latest where ``tmpdir`` carries native
        # backslashes the rendered message no longer contains.
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = StringIO()
            with redirect_stderr(stderr):
                rc = smoke_validate.main(
                    [tmpdir, "validate_skill.py"],
                )
            self.assertEqual(rc, 1)
            msg = stderr.getvalue()
            self.assertIn("no top-level directory", msg)
            self.assertIn(smoke_validate.to_posix(tmpdir), msg)
            self.assertIn("SKILL.md", msg)

    def test_missing_extracted_root_emits_clear_error(self) -> None:
        # ``find_skill_dirs`` returns [] for a missing root, then
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
            self.assertIn(smoke_validate.to_posix(missing), msg)

    def test_missing_root_error_omits_native_path_from_os_error(self) -> None:
        """The raw ``OSError`` path must not leak into diagnostics.

        Pinned regression: the helper normalised ``extracted_root``
        itself but still rendered ``str(exc)``.  On Windows,
        ``str(FileNotFoundError(..., filename='C:\\tmp\\missing'))``
        includes native backslashes, defeating the helper's
        byte-identical diagnostic contract.  Mock the Windows-shaped
        exception so the check runs on every host.
        """
        native = r"C:\tmp\missing"
        err = FileNotFoundError(
            2, "No such file or directory", native,
        )
        stderr = StringIO()
        with mock.patch.object(
            smoke_validate, "find_skill_dirs", return_value=[],
        ):
            with mock.patch.object(
                smoke_validate.os, "listdir", side_effect=err,
            ):
                with redirect_stderr(stderr):
                    rc = smoke_validate.main([native, "validate_skill.py"])
        self.assertEqual(rc, 1)
        msg = stderr.getvalue()
        self.assertIn("C:/tmp/missing", msg)
        self.assertNotIn(native, msg)
        self.assertIn("FileNotFoundError: No such file or directory", msg)

    def test_multi_match_layout_fails_without_invoking_validator(self) -> None:
        """Two top-level <skill-name>/SKILL.md entries fail loudly.

        The previous implementation silently picked the
        alphabetically-first entry and validated it, hiding a
        bundle-layout regression that the smoke job exists to
        catch.  ``main`` must FAIL with a clear message listing
        every candidate and must NOT invoke the validator at all
        (otherwise a green validator on the picked entry would
        report success).

        Pinned regression (windows-latest, 3.12 CI run 25461377074):
        the previous implementation rendered the candidate list via
        ``{matches!r}``, which on Windows escapes every backslash so
        the message contained ``\\\\`` sequences while
        ``os.path.join`` produced single ``\\`` paths — substring
        assertions failed.  ``to_posix`` normalises both sides so
        the assertion is byte-identical regardless of host.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "alpha", "SKILL.md"), "a")
            _write(os.path.join(tmpdir, "beta", "SKILL.md"), "b")
            stderr = StringIO()
            with mock.patch.object(
                smoke_validate.subprocess, "call",
            ) as call_mock:
                with redirect_stderr(stderr):
                    rc = smoke_validate.main(
                        [tmpdir, "/path/to/validate_skill.py"],
                    )
            self.assertEqual(rc, 1)
            call_mock.assert_not_called()
            msg = stderr.getvalue()
            self.assertIn("2 top-level directories", msg)
            self.assertIn("exactly one", msg)
            self.assertIn(
                smoke_validate.to_posix(os.path.join(tmpdir, "alpha")), msg,
            )
            self.assertIn(
                smoke_validate.to_posix(os.path.join(tmpdir, "beta")), msg,
            )

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
