"""Tests for the cross-platform negative smoke fixture helper."""

import importlib.util
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO


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


if __name__ == "__main__":
    unittest.main()
