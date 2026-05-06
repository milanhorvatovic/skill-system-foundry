"""Tests for the cross-platform negative smoke fixture helper."""

import importlib.util
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock


SCRIPT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        ".github",
        "scripts",
        "smoke-cross-platform-fixtures.py",
    )
)


def load_script_module() -> object:
    """Load the helper script as a test module."""
    spec = importlib.util.spec_from_file_location(
        "smoke_cross_platform_fixtures",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load smoke fixture helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SmokeCrossPlatformFixtureTests(unittest.TestCase):
    """Negative smoke fixtures should trip the intended checks."""

    def setUp(self) -> None:
        self.script = load_script_module()

    def test_case_exact_fixture_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.script.assert_case_exact_failure(tmpdir)

    def test_long_path_fixture_fails_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.script.assert_long_path_failure(tmpdir)

    def test_main_runs_and_cleans_workdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            stdout = StringIO()
            try:
                os.chdir(tmpdir)
                with redirect_stdout(stdout):
                    result = self.script.main()
            finally:
                os.chdir(original_cwd)

            self.assertEqual(result, 0)
            self.assertIn(
                "Cross-platform negative smoke fixtures passed.",
                stdout.getvalue(),
            )
            self.assertFalse(
                os.path.exists(
                    os.path.join(tmpdir, "smoke-cross-platform-fixtures")
                )
            )


class SmokeFixtureNegativeBranchTests(unittest.TestCase):
    """Cover the ``raise AssertionError`` branches in the helper.

    The smoke helper's two assertion functions both end with an ``if
    not any(...): raise AssertionError(...)``.  The happy-path tests
    above exercise the False branch (the rule did fire as expected);
    these tests force the True branch by mocking the underlying
    rule helpers to return empty results, so coverage hits both
    outcomes of every branch in the file.  Without these the
    per-file branch coverage check counts each ``if`` as
    half-covered and falls below the configured threshold.
    """

    def setUp(self) -> None:
        self.script = load_script_module()

    def test_assert_case_exact_failure_raises_on_silent_validator(self) -> None:
        # Mock the helper's bound ``validate_skill`` to return no
        # findings — the fixture is set up correctly but the rule
        # does not fire.  The helper must surface this as
        # AssertionError so a future regression in the underlying
        # rule does not silently pass the smoke job.
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                self.script, "validate_skill", return_value=([], []),
            ):
                with self.assertRaises(AssertionError) as ctx:
                    self.script.assert_case_exact_failure(tmpdir)
            self.assertIn(
                "wrong-cased reference did not fail validation",
                str(ctx.exception),
            )

    def test_assert_long_path_failure_raises_on_silent_budget(self) -> None:
        # Same shape: mock ``check_long_paths`` to report nothing
        # so the AssertionError branch is exercised.
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                self.script, "check_long_paths", return_value=([], []),
            ):
                with self.assertRaises(AssertionError) as ctx:
                    self.script.assert_long_path_failure(tmpdir)
            self.assertIn(
                "long-path fixture did not fail the archive budget",
                str(ctx.exception),
            )

    def test_write_text_creates_file_at_root_without_parent(self) -> None:
        # ``write_text`` short-circuits the ``os.makedirs`` call when
        # the target's dirname is empty (a bare filename in the
        # current working directory).  Exercise that branch so both
        # outcomes of the ``if parent:`` guard are covered.
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                self.script.write_text("bare.txt", "hello\n")
                with open("bare.txt", "r", encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), "hello\n")
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
