"""Tests for .github/scripts/check-per-file-coverage.py.

Covers load_threshold (valid config, decimal threshold, missing file,
missing section, missing key, non-numeric value, non-UTF-8 file),
check_per_file (all above, some below, all below, zero branches,
branchless without key, computed from raw counts, empty files, missing
key, out-of-range pct), and main integration (all pass, some fail,
threshold override, threshold range validation, load_threshold errors,
missing coverage JSON, malformed coverage JSON).
"""

import json
import os
import tempfile
import unittest

# The filename uses hyphens so we must import via importlib from a file path.
import importlib.util

_CI_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".github", "scripts")
)
_script_path = os.path.join(_CI_SCRIPTS_DIR, "check-per-file-coverage.py")
_spec = importlib.util.spec_from_file_location("check_per_file_coverage", _script_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load module from {_script_path}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
load_threshold = _mod.load_threshold
check_per_file = _mod.check_per_file
parse_file_threshold = _mod.parse_file_threshold
main = _mod.main


# ===================================================================
# Helpers
# ===================================================================


def _write(path: str, content: str) -> None:
    """Write *content* to *path*, creating parent directories."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _coverage_json(
    files: dict[str, float],
    *,
    use_num_branches_zero: set[str] | None = None,
    omit_percent_branches: set[str] | None = None,
) -> str:
    """Build a minimal coverage.json string.

    *files* maps filenames to ``percent_branches_covered`` values.
    Files listed in *use_num_branches_zero* get ``num_branches: 0``.
    Files listed in *omit_percent_branches* only get raw
    ``num_branches`` / ``covered_branches`` counts (no
    ``percent_branches_covered`` key) — mimicking coverage < 7.7
    output.  Branchless files in this set get both counts as 0.
    """
    use_zero = use_num_branches_zero or set()
    omit_pct = omit_percent_branches or set()
    file_data: dict[str, object] = {}
    for name, pct in files.items():
        if name in omit_pct:
            if name in use_zero:
                summary: dict[str, object] = {
                    "num_branches": 0,
                    "covered_branches": 0,
                }
            else:
                num = 100
                summary = {
                    "num_branches": num,
                    "covered_branches": round(pct * num / 100),
                }
        else:
            summary = {"percent_branches_covered": pct}
            if name in use_zero:
                summary["num_branches"] = 0
            else:
                summary["num_branches"] = 10
        file_data[name] = {"summary": summary}
    return json.dumps({"files": file_data})


# ===================================================================
# load_threshold — valid config
# ===================================================================


class LoadThresholdValidTests(unittest.TestCase):
    """Tests for load_threshold with well-formed .coveragerc files."""

    def test_integer_threshold(self) -> None:
        """Returns the integer fail_under value as a float."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".coveragerc", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("[report]\nfail_under = 70\n")
            path = fh.name
        try:
            self.assertEqual(load_threshold(path), 70.0)
        finally:
            os.unlink(path)

    def test_decimal_threshold(self) -> None:
        """Returns a decimal fail_under value correctly."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".coveragerc", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("[report]\nfail_under = 85.5\n")
            path = fh.name
        try:
            self.assertEqual(load_threshold(path), 85.5)
        finally:
            os.unlink(path)


# ===================================================================
# load_threshold — error cases
# ===================================================================


class LoadThresholdErrorTests(unittest.TestCase):
    """Tests for load_threshold when .coveragerc is missing or malformed."""

    def test_missing_file(self) -> None:
        """Raises SystemExit when the file does not exist."""
        with self.assertRaises(SystemExit):
            load_threshold("/nonexistent/path/.coveragerc")

    def test_missing_report_section(self) -> None:
        """Raises SystemExit when [report] section is absent."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".coveragerc", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("[run]\nsource = .\n")
            path = fh.name
        try:
            with self.assertRaises(SystemExit):
                load_threshold(path)
        finally:
            os.unlink(path)

    def test_missing_fail_under_key(self) -> None:
        """Raises SystemExit when fail_under is not in [report]."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".coveragerc", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("[report]\nexclude_lines = pragma: no cover\n")
            path = fh.name
        try:
            with self.assertRaises(SystemExit):
                load_threshold(path)
        finally:
            os.unlink(path)

    def test_non_numeric_fail_under(self) -> None:
        """Raises SystemExit when fail_under is not a valid number."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".coveragerc", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("[report]\nfail_under = abc\n")
            path = fh.name
        try:
            with self.assertRaises(SystemExit):
                load_threshold(path)
        finally:
            os.unlink(path)

    def test_non_utf8_file_raises_system_exit(self) -> None:
        """Raises SystemExit when .coveragerc contains invalid UTF-8 bytes."""
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".coveragerc", delete=False
        ) as fh:
            fh.write(b"[report]\nfail_under = \xff\xfe\n")
            path = fh.name
        try:
            with self.assertRaises(SystemExit):
                load_threshold(path)
        finally:
            os.unlink(path)

    def test_percent_sign_in_value_raises_system_exit(self) -> None:
        """Raises SystemExit when fail_under contains a percent sign.

        ConfigParser's default interpolation treats ``%`` as a special
        character.  With ``interpolation=None`` the value is read
        literally as ``"70%"``, which fails float conversion.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".coveragerc", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("[report]\nfail_under = 70%\n")
            path = fh.name
        try:
            with self.assertRaises(SystemExit):
                load_threshold(path)
        finally:
            os.unlink(path)


# ===================================================================
# check_per_file — passing scenarios
# ===================================================================


class CheckPerFilePassTests(unittest.TestCase):
    """Tests for check_per_file when all files meet the threshold."""

    def test_all_files_above_threshold(self) -> None:
        """Returns empty failures when every file exceeds the threshold."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(_coverage_json({"a.py": 80.0, "b.py": 90.0}))
            path = fh.name
        try:
            failures, passes = check_per_file(path, 70.0)
            self.assertEqual(failures, [])
            self.assertEqual(len(passes), 2)
        finally:
            os.unlink(path)

    def test_file_with_zero_branches(self) -> None:
        """A file with zero branches (100% by definition) passes."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                _coverage_json(
                    {"init.py": 100.0},
                    use_num_branches_zero={"init.py"},
                )
            )
            path = fh.name
        try:
            failures, passes = check_per_file(path, 70.0)
            self.assertEqual(failures, [])
            self.assertEqual(len(passes), 1)
        finally:
            os.unlink(path)

    def test_branchless_file_missing_percent_key_passes(self) -> None:
        """A branchless file without percent_branches_covered passes as 100%."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                _coverage_json(
                    {"init.py": 0.0, "real.py": 80.0},
                    omit_percent_branches={"init.py"},
                    use_num_branches_zero={"init.py"},
                )
            )
            path = fh.name
        try:
            failures, passes = check_per_file(path, 70.0)
            self.assertEqual(failures, [])
            self.assertEqual(len(passes), 2)
            pass_dict = dict(passes)
            self.assertAlmostEqual(pass_dict["init.py"], 100.0)
            self.assertAlmostEqual(pass_dict["real.py"], 80.0)
        finally:
            os.unlink(path)

    def test_computed_from_raw_counts_passes(self) -> None:
        """Files without percent_branches_covered pass when computed coverage meets threshold."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                _coverage_json(
                    {"lib.py": 80.0},
                    omit_percent_branches={"lib.py"},
                )
            )
            path = fh.name
        try:
            failures, passes = check_per_file(path, 70.0)
            self.assertEqual(failures, [])
            self.assertEqual(len(passes), 1)
            self.assertAlmostEqual(passes[0][1], 80.0)
        finally:
            os.unlink(path)

    def test_raw_counts_boundary_threshold_passes(self) -> None:
        """Raw-count coverage exactly at the threshold (7/10 = 70%) passes."""
        data = {"files": {"lib.py": {"summary": {
            "num_branches": 10,
            "covered_branches": 7,
        }}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            failures, passes = check_per_file(path, 70.0)
            self.assertEqual(failures, [])
            self.assertEqual(len(passes), 1)
            self.assertAlmostEqual(passes[0][1], 70.0)
        finally:
            os.unlink(path)

    def test_empty_files_dict(self) -> None:
        """Returns empty lists when the files dict is empty."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(json.dumps({"files": {}}))
            path = fh.name
        try:
            failures, passes = check_per_file(path, 70.0)
            self.assertEqual(failures, [])
            self.assertEqual(passes, [])
        finally:
            os.unlink(path)


# ===================================================================
# check_per_file — failing scenarios
# ===================================================================


class CheckPerFileFailTests(unittest.TestCase):
    """Tests for check_per_file when some or all files are below threshold."""

    def test_some_files_below_threshold(self) -> None:
        """Returns only the files that are below threshold."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                _coverage_json({"good.py": 80.0, "bad.py": 50.0})
            )
            path = fh.name
        try:
            failures, passes = check_per_file(path, 70.0)
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0][0], "bad.py")
            self.assertAlmostEqual(failures[0][1], 50.0)
            self.assertEqual(len(passes), 1)
        finally:
            os.unlink(path)

    def test_computed_from_raw_counts_below_threshold(self) -> None:
        """Files without percent_branches_covered fail when computed coverage is below threshold."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                _coverage_json(
                    {"bad.py": 50.0},
                    omit_percent_branches={"bad.py"},
                )
            )
            path = fh.name
        try:
            failures, passes = check_per_file(path, 70.0)
            self.assertEqual(len(failures), 1)
            self.assertAlmostEqual(failures[0][1], 50.0)
            self.assertEqual(len(passes), 0)
        finally:
            os.unlink(path)

    def test_all_files_below_threshold(self) -> None:
        """Returns all files when every file is below threshold."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                _coverage_json({"x.py": 50.0, "y.py": 60.0})
            )
            path = fh.name
        try:
            failures, passes = check_per_file(path, 70.0)
            self.assertEqual(len(failures), 2)
            self.assertEqual(len(passes), 0)
        finally:
            os.unlink(path)


# ===================================================================
# check_per_file — malformed data
# ===================================================================


class CheckPerFileMalformedTests(unittest.TestCase):
    """Tests for check_per_file with malformed coverage data."""

    def test_missing_percent_branches_covered_key(self) -> None:
        """Raises ValueError when percent_branches_covered is missing."""
        data = {"files": {"a.py": {"summary": {"percent_covered": 80.0}}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_missing_percent_with_nonzero_branches_raises(self) -> None:
        """Raises ValueError when percent_branches_covered is missing but num_branches > 0."""
        data = {"files": {"a.py": {"summary": {"num_branches": 5}}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_missing_summary_key(self) -> None:
        """Raises ValueError when summary is missing from a file entry."""
        data = {"files": {"a.py": {"executed_lines": [1, 2, 3]}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_missing_files_key_raises_value_error(self) -> None:
        """Raises ValueError when top-level 'files' key is missing."""
        data = {"totals": {"percent_covered": 80.0}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_percent_branches_covered_not_a_number(self) -> None:
        """Raises ValueError when percent_branches_covered is not a number."""
        data = {"files": {"a.py": {"summary": {"percent_branches_covered": "high"}}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_percent_branches_covered_boolean_raises_value_error(self) -> None:
        """Raises ValueError when percent_branches_covered is a boolean."""
        data = {"files": {"a.py": {"summary": {
            "num_branches": 5,
            "percent_branches_covered": True,
        }}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_num_branches_boolean_raises_value_error(self) -> None:
        """Raises ValueError when num_branches is a boolean."""
        data = {"files": {"a.py": {"summary": {
            "num_branches": False,
            "covered_branches": 0,
        }}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_pct_above_100_raises_value_error(self) -> None:
        """Raises ValueError when percent_branches_covered exceeds 100."""
        data = {"files": {"a.py": {"summary": {"percent_branches_covered": 150.0}}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_pct_negative_raises_value_error(self) -> None:
        """Raises ValueError when percent_branches_covered is negative."""
        data = {"files": {"a.py": {"summary": {"percent_branches_covered": -10.0}}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_computed_pct_above_100_raises_value_error(self) -> None:
        """Raises ValueError when covered_branches exceeds num_branches."""
        data = {"files": {"a.py": {"summary": {
            "num_branches": 10,
            "covered_branches": 15,
        }}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_zero_branches_with_positive_covered_raises(self) -> None:
        """Raises ValueError when num_branches is 0 but covered_branches > 0."""
        data = {"files": {"a.py": {"summary": {
            "num_branches": 0,
            "covered_branches": 3,
        }}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_zero_branches_with_string_covered_raises(self) -> None:
        """Raises ValueError when num_branches is 0 but covered_branches is non-numeric."""
        data = {"files": {"a.py": {"summary": {
            "num_branches": 0,
            "covered_branches": "none",
        }}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_json_root_is_null_raises_value_error(self) -> None:
        """Raises ValueError when coverage.json root is null."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("null")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_json_root_is_number_raises_value_error(self) -> None:
        """Raises ValueError when coverage.json root is a number."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("42")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)

    def test_json_root_is_boolean_raises_value_error(self) -> None:
        """Raises ValueError when coverage.json root is a boolean."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("true")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                check_per_file(path, 70.0)
        finally:
            os.unlink(path)


# ===================================================================
# main — argument parsing errors
# ===================================================================


class MainArgparseErrorTests(unittest.TestCase):
    """Integration tests for main with invalid CLI arguments."""

    def test_invalid_threshold_type_returns_two(self) -> None:
        """Returns 2 when --threshold receives a non-numeric value."""
        result = main(["--threshold", "abc"])
        self.assertEqual(result, 2)

    def test_unknown_flag_returns_two(self) -> None:
        """Returns 2 when an unknown flag is passed."""
        result = main(["--bogus"])
        self.assertEqual(result, 2)


# ===================================================================
# main — integration tests
# ===================================================================


class MainAllPassTests(unittest.TestCase):
    """Integration tests for main when all files pass."""

    def test_all_files_pass_returns_zero(self) -> None:
        """Exit code 0 when all files meet the threshold."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            rc_path = os.path.join(tmpdir, ".coveragerc")
            _write(json_path, _coverage_json({"a.py": 80.0, "b.py": 90.0}))
            _write(rc_path, "[report]\nfail_under = 70\n")
            result = main([
                "--coverage-json", json_path,
                "--coveragerc", rc_path,
            ])
            self.assertEqual(result, 0)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class MainSomeFailTests(unittest.TestCase):
    """Integration tests for main when some files fail."""

    def test_some_files_fail_returns_one(self) -> None:
        """Exit code 1 when at least one file is below threshold."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            rc_path = os.path.join(tmpdir, ".coveragerc")
            _write(json_path, _coverage_json({"ok.py": 80.0, "bad.py": 40.0}))
            _write(rc_path, "[report]\nfail_under = 70\n")
            result = main([
                "--coverage-json", json_path,
                "--coveragerc", rc_path,
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class MainThresholdOverrideTests(unittest.TestCase):
    """Integration tests for main with --threshold override."""

    def test_threshold_override_ignores_coveragerc(self) -> None:
        """The --threshold flag overrides the .coveragerc value."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 50.0}))
            # Use --threshold so .coveragerc is not required
            result = main([
                "--coverage-json", json_path,
                "--threshold", "40",
            ])
            self.assertEqual(result, 0)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class MainThresholdRangeTests(unittest.TestCase):
    """Integration tests for main with out-of-range thresholds."""

    def test_negative_threshold_returns_one(self) -> None:
        """Returns 1 when --threshold is negative."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 80.0}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "-1",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_threshold_above_100_returns_one(self) -> None:
        """Returns 1 when --threshold exceeds 100."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 80.0}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "101",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_threshold_zero_is_valid(self) -> None:
        """Returns 0 when --threshold is 0 (boundary, all files pass)."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 0.0}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "0",
            ])
            self.assertEqual(result, 0)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_threshold_100_is_valid(self) -> None:
        """Returns 0 when --threshold is 100 and all files are at 100%."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 100.0}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "100",
            ])
            self.assertEqual(result, 0)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class MainLoadThresholdErrorTests(unittest.TestCase):
    """Integration tests for main when load_threshold fails."""

    def test_missing_coveragerc_returns_one(self) -> None:
        """Returns 1 (not SystemExit) when .coveragerc does not exist."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 80.0}))
            result = main([
                "--coverage-json", json_path,
                "--coveragerc", os.path.join(tmpdir, "missing.coveragerc"),
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_malformed_coveragerc_returns_one(self) -> None:
        """Returns 1 (not SystemExit) when .coveragerc is malformed."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            rc_path = os.path.join(tmpdir, ".coveragerc")
            _write(json_path, _coverage_json({"a.py": 80.0}))
            _write(rc_path, "[run]\nsource = .\n")
            result = main([
                "--coverage-json", json_path,
                "--coveragerc", rc_path,
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class MainMissingCoverageJsonTests(unittest.TestCase):
    """Integration tests for main with missing coverage.json."""

    def test_missing_coverage_json_returns_one(self) -> None:
        """Returns 1 when coverage.json does not exist."""
        tmpdir = tempfile.mkdtemp()
        try:
            rc_path = os.path.join(tmpdir, ".coveragerc")
            _write(rc_path, "[report]\nfail_under = 70\n")
            result = main([
                "--coverage-json", os.path.join(tmpdir, "nope.json"),
                "--coveragerc", rc_path,
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


# ===================================================================
# main — malformed coverage.json
# ===================================================================


class MainMalformedCoverageJsonTests(unittest.TestCase):
    """Integration tests for main with malformed coverage.json data."""

    def test_missing_files_key_returns_one(self) -> None:
        """Returns 1 when coverage.json has no top-level 'files' key."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, json.dumps({"totals": {"percent_covered": 80.0}}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_files_key_is_list_returns_one(self) -> None:
        """Returns 1 when 'files' is a list instead of a dict."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, json.dumps({"files": ["a.py", "b.py"]}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_files_key_is_null_returns_one(self) -> None:
        """Returns 1 when 'files' is null."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, json.dumps({"files": None}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_files_key_is_string_returns_one(self) -> None:
        """Returns 1 when 'files' is a string instead of a dict."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, json.dumps({"files": "not a dict"}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_invalid_json_returns_one(self) -> None:
        """Returns 1 with a clear error when coverage.json is not valid JSON."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, "{{not valid json")
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_missing_summary_in_file_entry_returns_one(self) -> None:
        """Returns 1 when a file entry is missing 'summary'."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            data = {"files": {"a.py": {"executed_lines": [1, 2]}}}
            _write(json_path, json.dumps(data))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_missing_percent_branches_covered_returns_one(self) -> None:
        """Returns 1 when a file entry is missing 'percent_branches_covered'."""
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            data = {"files": {"a.py": {"summary": {"percent_covered": 80.0}}}}
            _write(json_path, json.dumps(data))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


# ===================================================================
# parse_file_threshold — argument parsing
# ===================================================================


class ParseFileThresholdTests(unittest.TestCase):
    """Tests for ``parse_file_threshold`` PATH=PCT parsing."""

    def test_simple_path_and_integer(self) -> None:
        self.assertEqual(
            parse_file_threshold("a/b.py=90"),
            ("a/b.py", 90.0),
        )

    def test_path_with_equals_sign_uses_last(self) -> None:
        # Splits on the LAST '='; paths may contain '='.
        self.assertEqual(
            parse_file_threshold("weird=name.py=85"),
            ("weird=name.py", 85.0),
        )

    def test_zero_and_hundred_boundary(self) -> None:
        self.assertEqual(parse_file_threshold("a.py=0"), ("a.py", 0.0))
        self.assertEqual(parse_file_threshold("a.py=100"), ("a.py", 100.0))

    def test_missing_equals_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_file_threshold("no-equals-sign")

    def test_empty_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_file_threshold("=90")

    def test_non_integer_pct_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_file_threshold("a.py=ninety")

    def test_decimal_pct_raises(self) -> None:
        # PCT must be an integer; decimals are rejected.
        with self.assertRaises(ValueError):
            parse_file_threshold("a.py=90.5")

    def test_negative_pct_raises(self) -> None:
        # The minus sign also defeats isdigit() — covered, but pin the
        # shape explicitly so a future refactor can't regress it.
        with self.assertRaises(ValueError):
            parse_file_threshold("a.py=-1")

    def test_above_100_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_file_threshold("a.py=101")


# ===================================================================
# check_per_file — per-file overrides
# ===================================================================


class CheckPerFileOverrideTests(unittest.TestCase):
    """Tests for ``check_per_file`` honoring per-file overrides."""

    def test_override_hit_promotes_threshold(self) -> None:
        # Global threshold 70; override raises a.py to 95.  a.py at 90%
        # now fails, b.py at 80% still passes against the global.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(_coverage_json({"a.py": 90.0, "b.py": 80.0}))
            path = fh.name
        try:
            failures, passes = check_per_file(
                path, 70.0, {"a.py": 95.0}
            )
            self.assertEqual([f[0] for f in failures], ["a.py"])
            self.assertEqual([p[0] for p in passes], ["b.py"])
        finally:
            os.unlink(path)

    def test_override_targeting_unmeasured_file_raises(self) -> None:
        # An override targeting a path the coverage data does not contain
        # (typically because .coveragerc 'source'/'omit' excludes it, or
        # the path is mistyped) is a dead letter that must surface as a
        # ValueError instead of silently allowing the bar to be unenforced.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(_coverage_json({"a.py": 50.0, "b.py": 80.0}))
            path = fh.name
        try:
            with self.assertRaises(ValueError) as ctx:
                check_per_file(path, 70.0, {"c.py": 99.0})
            message = str(ctx.exception)
            self.assertIn("c.py", message)
            self.assertIn("absent from coverage data", message)
        finally:
            os.unlink(path)

    def test_unmatched_overrides_listed_sorted(self) -> None:
        # Multiple unmatched overrides surface together, sorted, so a
        # CI log shows the full set in one shot rather than only the
        # first miss.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(_coverage_json({"a.py": 90.0}))
            path = fh.name
        try:
            with self.assertRaises(ValueError) as ctx:
                check_per_file(
                    path,
                    70.0,
                    {"a.py": 80.0, "z.py": 99.0, "m.py": 90.0},
                )
            message = str(ctx.exception)
            self.assertIn("m.py, z.py", message)
            self.assertNotIn("a.py", message.split("absent")[1])
        finally:
            os.unlink(path)

    def test_multiple_overrides_apply_independently(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                _coverage_json({"a.py": 92.0, "b.py": 85.0, "c.py": 75.0})
            )
            path = fh.name
        try:
            failures, passes = check_per_file(
                path,
                70.0,
                {"a.py": 95.0, "b.py": 80.0},
            )
            self.assertEqual([f[0] for f in failures], ["a.py"])
            self.assertEqual(
                sorted(p[0] for p in passes),
                ["b.py", "c.py"],
            )
        finally:
            os.unlink(path)

    def test_override_lower_than_global_lets_low_file_pass(self) -> None:
        # Per-file override may also relax — a.py at 50% passes when
        # override drops to 40%, even though the global is 70%.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(_coverage_json({"a.py": 50.0}))
            path = fh.name
        try:
            failures, passes = check_per_file(
                path, 70.0, {"a.py": 40.0}
            )
            self.assertEqual(failures, [])
            self.assertEqual([p[0] for p in passes], ["a.py"])
        finally:
            os.unlink(path)


class MainFileThresholdTests(unittest.TestCase):
    """Integration tests for ``--file-threshold`` end-to-end."""

    def test_repeated_overrides_pass(self) -> None:
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 92.0, "b.py": 88.0}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
                "--file-threshold", "a.py=90",
                "--file-threshold", "b.py=80",
            ])
            self.assertEqual(result, 0)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_override_failure_returns_one(self) -> None:
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 80.0}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
                "--file-threshold", "a.py=90",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_override_failure_reports_override_threshold(self) -> None:
        # When a per-file override is the reason a file fails, the
        # output must name the override threshold (not the global
        # floor) so the CI log is actionable.
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 80.0}))
            buf_out: list[str] = []
            import contextlib
            import io
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main([
                    "--coverage-json", json_path,
                    "--threshold", "70",
                    "--file-threshold", "a.py=90",
                ])
            buf_out.append(stdout.getvalue())
            self.assertEqual(code, 1)
            output = buf_out[0]
            self.assertIn("override threshold 90.0%", output)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_override_path_normalisation_matches_coverage_filename(self) -> None:
        # CLI input may use different equivalent path forms than what
        # ``coverage.json`` stores (``./x.py`` prefix, backslashes on
        # Windows, etc.).  Normalisation must make the override apply
        # regardless.
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"pkg/x.py": 80.0}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
                "--file-threshold", "./pkg/x.py=90",
            ])
            self.assertEqual(result, 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_malformed_override_returns_usage_error(self) -> None:
        # Usage errors follow argparse convention and exit with code 2,
        # matching the contract documented on ``main``.
        tmpdir = tempfile.mkdtemp()
        try:
            json_path = os.path.join(tmpdir, "coverage.json")
            _write(json_path, _coverage_json({"a.py": 90.0}))
            result = main([
                "--coverage-json", json_path,
                "--threshold", "70",
                "--file-threshold", "a.py=ninety",
            ])
            self.assertEqual(result, 2)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


if __name__ == "__main__":
    unittest.main()
