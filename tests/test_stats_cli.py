"""Tests for skill-system-foundry/scripts/stats.py (CLI entry point).

Covers argument parsing, exit codes, JSON schema, error paths
(missing directory, missing SKILL.md), human-readable output shape,
and the --verbose parent-list expansion.

The in-process ``_run_main`` helper exercises the same code paths
under coverage; subprocess-based tests cannot contribute to coverage
because the coverage session does not span child Python processes.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from helpers import write_text, write_skill_md

SCRIPTS_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "skill-system-foundry", "scripts",
    )
)
STATS_SCRIPT = os.path.join(SCRIPTS_DIR, "stats.py")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, STATS_SCRIPT] + args,
        capture_output=True,
        text=True,
    )


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    """Invoke stats.main() in-process and capture streams."""
    import stats as st

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with (
        mock.patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        try:
            st.main()
        except SystemExit as exc:
            if exc.code is None:
                code = 0
            elif isinstance(exc.code, int):
                code = exc.code
            else:
                code = 1
    return code, stdout.getvalue(), stderr.getvalue()


class StatsCLIBasicTests(unittest.TestCase):
    """Argument parsing and top-level exit-code behavior."""

    def test_no_args_prints_docstring_and_exits_one(self) -> None:
        result = _run([])
        self.assertEqual(result.returncode, 1)
        self.assertIn("Usage", result.stdout)

    def test_nonexistent_path_exits_one(self) -> None:
        result = _run(["/tmp/__definitely_does_not_exist__/skill"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a directory", result.stdout)

    def test_nonexistent_path_json_emits_error_field(self) -> None:
        result = _run(["/tmp/__nope__", "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tool"], "stats")
        self.assertFalse(payload["success"])
        self.assertIn("not a directory", payload["error"])

    def test_missing_skill_md_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run([tmpdir])
        self.assertEqual(result.returncode, 1)
        self.assertIn("No SKILL.md", result.stdout)

    def test_missing_skill_md_json_returns_failures_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run([tmpdir, "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tool"], "stats")
        self.assertFalse(payload["success"])
        self.assertEqual(payload["summary"]["failures"], 1)
        self.assertTrue(
            any("No SKILL.md" in m for m in payload["errors"]["failures"])
        )

    def test_unknown_flag_exits_one_via_json_aware_handler(self) -> None:
        result = _run(["--bogus", "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["success"])


class StatsCLIHappyPathTests(unittest.TestCase):
    """Successful runs against synthesized skill fixtures."""

    def test_clean_skill_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir)
            result = _run([tmpdir])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Skill:", result.stdout)
        self.assertIn("Discovery:", result.stdout)
        self.assertIn("Load:", result.stdout)
        self.assertIn("SKILL.md", result.stdout)

    def test_json_schema_top_level_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir)
            result = _run([tmpdir, "--json"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        for key in (
            "tool", "version", "path", "success",
            "skill", "metric", "discovery_bytes", "load_bytes",
            "files", "summary", "errors",
        ):
            self.assertIn(key, payload, f"missing key {key}")
        self.assertEqual(payload["tool"], "stats")
        self.assertEqual(payload["metric"], "bytes")
        self.assertTrue(payload["success"])
        self.assertEqual(payload["summary"]["files"], len(payload["files"]))

    def test_json_files_sorted_alphabetically(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "[z](references/z.md) [a](references/a.md)\n"
                ),
            )
            write_text(os.path.join(tmpdir, "references", "a.md"), "a\n")
            write_text(os.path.join(tmpdir, "references", "z.md"), "z\n")
            result = _run([tmpdir, "--json"])
        payload = json.loads(result.stdout)
        paths = [entry["path"] for entry in payload["files"]]
        self.assertEqual(paths, sorted(paths))

    def test_human_output_shows_arrow_for_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir, body="# Skill\n\n[g](references/g.md)\n",
            )
            write_text(os.path.join(tmpdir, "references", "g.md"), "g\n")
            result = _run([tmpdir])
        self.assertEqual(result.returncode, 0)
        # Each child line shows the parent via the ← arrow.
        self.assertIn("← SKILL.md", result.stdout)

    def test_verbose_expands_multi_parent_arrow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "[a](capabilities/a/capability.md) "
                    "[b](capabilities/b/capability.md)\n"
                ),
            )
            shared_body = "see [s](references/shared.md)\n"
            write_text(
                os.path.join(tmpdir, "capabilities", "a", "capability.md"),
                shared_body,
            )
            write_text(
                os.path.join(tmpdir, "capabilities", "b", "capability.md"),
                shared_body,
            )
            write_text(
                os.path.join(tmpdir, "references", "shared.md"), "s\n",
            )
            terse = _run([tmpdir])
            verbose = _run([tmpdir, "--verbose"])
        # Terse mode shows "(+1 more)" suffix on the shared file
        self.assertIn("(+1 more)", terse.stdout)
        # Verbose mode lists both parents inline, no "more" suffix
        self.assertNotIn("(+1 more)", verbose.stdout)
        self.assertIn(
            "capabilities/a/capability.md, capabilities/b/capability.md",
            verbose.stdout,
        )

    def test_broken_ref_exits_zero_with_warning(self) -> None:
        """A broken ref is a WARN, not a FAIL — exit 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body="# Skill\n\n[m](references/missing.md)\n",
            )
            result = _run([tmpdir, "--json"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["summary"]["warnings"], 1)


class StatsCLIInProcessTests(unittest.TestCase):
    """In-process coverage for ``main()``.  Same scenarios as the
    subprocess tests above, run through ``_run_main`` so coverage
    can observe the entry point."""

    def test_no_args_prints_docstring_and_exits_one(self) -> None:
        code, out, _err = _run_main(["stats.py"])
        self.assertEqual(code, 1)
        self.assertIn("Usage", out)

    def test_nonexistent_path_text_mode(self) -> None:
        code, out, _err = _run_main(["stats.py", "/tmp/__nope_in_proc__"])
        self.assertEqual(code, 1)
        self.assertIn("not a directory", out)

    def test_nonexistent_path_json_mode(self) -> None:
        code, out, _err = _run_main(
            ["stats.py", "/tmp/__nope_in_proc__", "--json"]
        )
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertFalse(payload["success"])
        self.assertIn("not a directory", payload["error"])

    def test_missing_skill_md_text_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, _err = _run_main(["stats.py", tmpdir])
        self.assertEqual(code, 1)
        self.assertIn("No SKILL.md", out)

    def test_missing_skill_md_json_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, _err = _run_main(["stats.py", tmpdir, "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["summary"]["failures"], 1)

    def test_clean_skill_text_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir)
            code, out, _err = _run_main(["stats.py", tmpdir])
        self.assertEqual(code, 0)
        self.assertIn("Skill:", out)
        self.assertIn("Discovery:", out)

    def test_clean_skill_json_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir)
            code, out, _err = _run_main(["stats.py", tmpdir, "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["tool"], "stats")
        self.assertTrue(payload["success"])

    def test_verbose_text_mode_with_multi_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "[a](capabilities/a/capability.md) "
                    "[b](capabilities/b/capability.md)\n"
                ),
            )
            shared = "[s](references/shared.md)\n"
            write_text(
                os.path.join(tmpdir, "capabilities", "a", "capability.md"),
                shared,
            )
            write_text(
                os.path.join(tmpdir, "capabilities", "b", "capability.md"),
                shared,
            )
            write_text(
                os.path.join(tmpdir, "references", "shared.md"), "x\n",
            )
            code, out, _err = _run_main(["stats.py", tmpdir, "--verbose"])
        self.assertEqual(code, 0)
        self.assertIn(
            "capabilities/a/capability.md, capabilities/b/capability.md", out
        )

    def test_unknown_flag_text_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir)
            code, out, err = _run_main(["stats.py", tmpdir, "--bogus"])
        self.assertEqual(code, 1)
        # argparse error goes to stderr in text mode
        self.assertIn("unrecognized", err.lower())


if __name__ == "__main__":
    unittest.main()
