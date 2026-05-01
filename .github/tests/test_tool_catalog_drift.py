"""Tests for ``.github/scripts/tool-catalog-drift.py``.

Covers:
  * ``fetch`` — success, HTTP error, URL error, timeout/OSError,
    non-UTF-8 body.
  * ``extract_tools`` — real upstream fixture, header-row missing,
    no body, no separator row, zero matches, all-caps acronym,
    non-PascalCase row ignored.
  * ``parse_catalog`` — happy path, missing provenance, missing
    harness_tools, missing source_url/last_checked, empty list,
    inconsistent indent, missing harness bucket.
  * ``diff`` — set arithmetic.
  * ``apply_additions`` — append at end, alphabetical insert,
    last_checked rewrite, no-op when no additions, idempotent on
    re-run with same data, handles single-quoted and double-quoted
    last_checked values.
  * ``_replace_scalar`` — preserves leading whitespace, always
    double-quotes the new value.
  * ``render_summary`` — additions only, removals only, both,
    neither.
  * ``main`` — dry-run no drift, dry-run with drift, default mode
    rewrites the file, hard-fail on fetch error, hard-fail on
    parse error, summary-out file written.
"""

import datetime
import importlib.util
import io
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from typing import Any
from unittest import mock

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_SCRIPT_PATH = os.path.join(
    _REPO_ROOT, ".github", "scripts", "tool-catalog-drift.py"
)
_FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__), "fixtures"
)

_spec = importlib.util.spec_from_file_location(
    "tool_catalog_drift", _SCRIPT_PATH
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load module from {_SCRIPT_PATH}")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _read_fixture(name: str) -> str:
    """Return the contents of the named fixture file as a string."""
    with open(
        os.path.join(_FIXTURES_DIR, name), "r", encoding="utf-8"
    ) as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


class FetchTests(unittest.TestCase):
    """``fetch`` returns UTF-8 text on success and hard-fails loudly otherwise."""

    def _make_response(self, status: int, body: bytes) -> mock.MagicMock:
        response = mock.MagicMock()
        response.status = status
        response.read.return_value = body
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_returns_decoded_body_on_2xx(self) -> None:
        response = self._make_response(200, b"hello upstream")
        with mock.patch.object(
            mod.urllib.request, "urlopen", return_value=response
        ):
            self.assertEqual(mod.fetch("https://example.test"), "hello upstream")

    def test_raises_on_non_2xx_status(self) -> None:
        response = self._make_response(500, b"bad")
        with mock.patch.object(
            mod.urllib.request, "urlopen", return_value=response
        ):
            with self.assertRaises(mod.FetchError) as ctx:
                mod.fetch("https://example.test")
            self.assertIn("500", str(ctx.exception))

    def test_raises_on_http_error(self) -> None:
        http_error = urllib.error.HTTPError(
            url="https://example.test",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )
        with mock.patch.object(
            mod.urllib.request, "urlopen", side_effect=http_error
        ):
            with self.assertRaises(mod.FetchError) as ctx:
                mod.fetch("https://example.test")
            self.assertIn("404", str(ctx.exception))

    def test_raises_on_url_error(self) -> None:
        url_error = urllib.error.URLError("DNS lookup failed")
        with mock.patch.object(
            mod.urllib.request, "urlopen", side_effect=url_error
        ):
            with self.assertRaises(mod.FetchError) as ctx:
                mod.fetch("https://example.test")
            self.assertIn("network error", str(ctx.exception))

    def test_raises_on_timeout(self) -> None:
        with mock.patch.object(
            mod.urllib.request,
            "urlopen",
            side_effect=TimeoutError("read timed out"),
        ):
            with self.assertRaises(mod.FetchError) as ctx:
                mod.fetch("https://example.test")
            self.assertIn("I/O error", str(ctx.exception))

    def test_raises_on_non_utf8_body(self) -> None:
        # 0xff is invalid as a UTF-8 leading byte.
        response = self._make_response(200, b"\xff\xfe\xfd")
        with mock.patch.object(
            mod.urllib.request, "urlopen", return_value=response
        ):
            with self.assertRaises(mod.FetchError) as ctx:
                mod.fetch("https://example.test")
            self.assertIn("non-UTF-8", str(ctx.exception))


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------


class ExtractToolsTests(unittest.TestCase):
    """``extract_tools`` parses the upstream tools-reference table."""

    def test_real_fixture_yields_canonical_set(self) -> None:
        markdown = _read_fixture("tools-reference.md")
        tools = mod.extract_tools(markdown)
        # Spot-check against verbatim names from the captured table.
        for tool in (
            "Bash", "Read", "Edit", "Write", "Grep", "Glob",
            "WebFetch", "WebSearch", "Agent", "AskUserQuestion",
            "NotebookEdit", "Skill", "LSP", "PowerShell", "ToolSearch",
        ):
            self.assertIn(tool, tools)

    def test_real_fixture_excludes_stale_task_token(self) -> None:
        # ``Task`` (singular) is in our catalog but not in the upstream
        # table — it has been split into ``TaskCreate`` / ``TaskGet`` /
        # etc. The extractor must not return ``Task``.
        markdown = _read_fixture("tools-reference.md")
        tools = mod.extract_tools(markdown)
        self.assertNotIn("Task", tools)
        for split_form in (
            "TaskCreate", "TaskGet", "TaskList",
            "TaskOutput", "TaskStop", "TaskUpdate",
        ):
            self.assertIn(split_form, tools)

    def test_all_caps_acronym_lsp_recognised(self) -> None:
        # ``LSP`` is all-caps but matches the harness shape regex.
        markdown = _read_fixture("tools-reference.md")
        tools = mod.extract_tools(markdown)
        self.assertIn("LSP", tools)

    def test_no_header_row_raises(self) -> None:
        markdown = "# Some page\n\nNo table here.\n"
        with self.assertRaises(mod.ParseError) as ctx:
            mod.extract_tools(markdown)
        self.assertIn("header row", str(ctx.exception))

    def test_header_without_body_raises(self) -> None:
        markdown = (
            "# Tools\n\n"
            "| Tool | Description | Permission |\n"
        )
        with self.assertRaises(mod.ParseError) as ctx:
            mod.extract_tools(markdown)
        self.assertIn("no body", str(ctx.exception).lower())

    def test_header_without_separator_raises(self) -> None:
        markdown = (
            "# Tools\n\n"
            "| Tool | Description | Permission |\n"
            "| `Bash` | Runs commands | Yes |\n"
        )
        with self.assertRaises(mod.ParseError) as ctx:
            mod.extract_tools(markdown)
        self.assertIn("separator", str(ctx.exception))

    def test_zero_matches_raises(self) -> None:
        markdown = (
            "| Tool | Description | Permission |\n"
            "| :--- | :---------- | :--------- |\n"
            "| (deprecated) | Removed in v2 | No |\n"
            "\n"
        )
        with self.assertRaises(mod.ParseError) as ctx:
            mod.extract_tools(markdown)
        self.assertIn("zero", str(ctx.exception).lower())

    def test_non_pascalcase_row_ignored(self) -> None:
        markdown = (
            "| Tool | Description | Permission |\n"
            "| :--- | :---------- | :--------- |\n"
            "| `lowercase` | a bad row | No |\n"
            "| `Bash` | a good row | Yes |\n"
            "| `mcp__server__tool` | mcp shape | No |\n"
        )
        tools = mod.extract_tools(markdown)
        self.assertEqual(tools, {"Bash"})

    def test_table_terminated_by_blank_line(self) -> None:
        markdown = (
            "| Tool | Description | Permission |\n"
            "| :--- | :---------- | :--------- |\n"
            "| `Bash` | a good row | Yes |\n"
            "\n"
            "| Tool | Description | Permission |\n"
            "| :--- | :---------- | :--------- |\n"
            "| `Phantom` | should not be picked up | No |\n"
        )
        # First table only — blank line breaks scan.  ``Phantom`` is in
        # a second table that the extractor never enters.
        tools = mod.extract_tools(markdown)
        self.assertEqual(tools, {"Bash"})


# ---------------------------------------------------------------------------
# Parse catalog
# ---------------------------------------------------------------------------


_HAPPY_CATALOG = """\
skill:
  allowed_tools:
    catalogs:
      claude_code:
        provenance:
          source_url: https://example.test/tools.md
          last_checked: "2026-04-26"
        harness_tools:
          - Bash
          - Read
          - Edit
        cli_tools:
          - bash
"""


class ParseCatalogTests(unittest.TestCase):
    """``parse_catalog`` reads the harness slice of configuration.yaml."""

    def test_happy_path(self) -> None:
        parsed = mod.parse_catalog(_HAPPY_CATALOG)
        self.assertEqual(
            parsed["source_url"], "https://example.test/tools.md"
        )
        self.assertEqual(parsed["last_checked"], "2026-04-26")
        self.assertEqual(
            parsed["harness_tools"], ["Bash", "Read", "Edit"]
        )

    def test_real_configuration_yaml(self) -> None:
        # The actual repo configuration must parse cleanly under the
        # current schema.  This test is the canary for "did we break
        # the production catalog with an edit elsewhere?"
        path = os.path.join(
            _REPO_ROOT, "skill-system-foundry", "scripts", "lib",
            "configuration.yaml",
        )
        with open(path, "r", encoding="utf-8") as fh:
            parsed = mod.parse_catalog(fh.read())
        self.assertTrue(parsed["source_url"].startswith("https://"))
        self.assertRegex(parsed["last_checked"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn("Bash", parsed["harness_tools"])

    def test_missing_provenance_raises(self) -> None:
        text = _HAPPY_CATALOG.replace(
            "        provenance:\n"
            "          source_url: https://example.test/tools.md\n"
            "          last_checked: \"2026-04-26\"\n",
            "",
        )
        with self.assertRaises(mod.ParseError) as ctx:
            mod.parse_catalog(text)
        self.assertIn("provenance", str(ctx.exception))

    def test_missing_harness_tools_raises(self) -> None:
        text = _HAPPY_CATALOG.replace(
            "        harness_tools:\n"
            "          - Bash\n"
            "          - Read\n"
            "          - Edit\n",
            "",
        )
        with self.assertRaises(mod.ParseError) as ctx:
            mod.parse_catalog(text)
        self.assertIn("harness_tools", str(ctx.exception))

    def test_missing_source_url_raises(self) -> None:
        text = _HAPPY_CATALOG.replace(
            "          source_url: https://example.test/tools.md\n", ""
        )
        with self.assertRaises(mod.ParseError) as ctx:
            mod.parse_catalog(text)
        self.assertIn("source_url", str(ctx.exception))

    def test_missing_harness_bucket_raises(self) -> None:
        text = _HAPPY_CATALOG.replace("claude_code", "fake_harness")
        with self.assertRaises(mod.ParseError) as ctx:
            mod.parse_catalog(text)
        self.assertIn("claude_code", str(ctx.exception))

    def test_inconsistent_indent_raises(self) -> None:
        text = (
            "skill:\n"
            "  allowed_tools:\n"
            "    catalogs:\n"
            "      claude_code:\n"
            "        provenance:\n"
            "          source_url: x\n"
            "          last_checked: \"2026-01-01\"\n"
            "        harness_tools:\n"
            "          - Bash\n"
            "            - Read\n"  # extra indent on second item
        )
        with self.assertRaises(mod.ParseError):
            mod.parse_catalog(text)

    def test_quoted_last_checked_unquoted_correctly(self) -> None:
        parsed = mod.parse_catalog(_HAPPY_CATALOG)
        self.assertEqual(parsed["last_checked"], "2026-04-26")

    def test_single_quoted_last_checked_unquoted_correctly(self) -> None:
        text = _HAPPY_CATALOG.replace(
            'last_checked: "2026-04-26"',
            "last_checked: '2026-04-26'",
        )
        parsed = mod.parse_catalog(text)
        self.assertEqual(parsed["last_checked"], "2026-04-26")


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


class DiffTests(unittest.TestCase):
    def test_additions_and_removals(self) -> None:
        catalog = {"Bash", "Read", "Task"}
        extracted = {"Bash", "Read", "Edit", "Write"}
        additions, removals = mod.diff(catalog, extracted)
        self.assertEqual(additions, {"Edit", "Write"})
        self.assertEqual(removals, {"Task"})

    def test_no_drift(self) -> None:
        s = {"Bash", "Read"}
        additions, removals = mod.diff(s, s)
        self.assertEqual(additions, set())
        self.assertEqual(removals, set())


# ---------------------------------------------------------------------------
# Apply additions
# ---------------------------------------------------------------------------


class ApplyAdditionsTests(unittest.TestCase):
    """``apply_additions`` rewrites the YAML in place via line-level edits."""

    def test_appends_in_alphabetical_order(self) -> None:
        out = mod.apply_additions(
            _HAPPY_CATALOG, {"Glob", "WebFetch"}, "2026-05-01"
        )
        # New items go between existing list and the next sibling
        # (``cli_tools:``).
        self.assertIn("- Glob\n", out)
        self.assertIn("- WebFetch\n", out)
        # Alphabetical: Glob before WebFetch in the raw bytes.
        self.assertLess(out.find("- Glob"), out.find("- WebFetch"))
        # cli_tools section is preserved after the additions.
        self.assertIn("cli_tools:\n", out)
        self.assertLess(out.find("- WebFetch"), out.find("cli_tools:"))

    def test_rewrites_last_checked(self) -> None:
        out = mod.apply_additions(_HAPPY_CATALOG, set(), "2026-05-01")
        self.assertIn('last_checked: "2026-05-01"', out)
        self.assertNotIn('last_checked: "2026-04-26"', out)

    def test_no_additions_only_rewrites_date(self) -> None:
        out = mod.apply_additions(_HAPPY_CATALOG, set(), "2026-05-01")
        # All three existing tools survive unchanged.
        for tool in ("Bash", "Read", "Edit"):
            self.assertIn(f"- {tool}\n", out)

    def test_skips_already_present_additions(self) -> None:
        # ``Bash`` is already in the catalog — must not be duplicated.
        out = mod.apply_additions(
            _HAPPY_CATALOG, {"Bash", "Glob"}, "2026-05-01"
        )
        # Count occurrences of ``- Bash`` lines.
        self.assertEqual(out.count("- Bash\n"), 1)
        self.assertEqual(out.count("- Glob\n"), 1)

    def test_idempotent_on_rerun(self) -> None:
        first = mod.apply_additions(
            _HAPPY_CATALOG, {"Glob"}, "2026-05-01"
        )
        # Re-parse the rewritten YAML and apply the same additions.
        second = mod.apply_additions(first, {"Glob"}, "2026-05-01")
        self.assertEqual(first, second)

    def test_preserves_cli_tools_block(self) -> None:
        out = mod.apply_additions(
            _HAPPY_CATALOG, {"Glob"}, "2026-05-01"
        )
        self.assertIn("cli_tools:\n", out)
        self.assertIn("- bash\n", out)


# ---------------------------------------------------------------------------
# _replace_scalar
# ---------------------------------------------------------------------------


class ReplaceScalarTests(unittest.TestCase):
    def test_preserves_indent_and_double_quotes_value(self) -> None:
        out = mod._replace_scalar(
            '          last_checked: "2026-04-26"\n',
            "last_checked:",
            "2026-05-01",
        )
        self.assertEqual(
            out, '          last_checked: "2026-05-01"\n'
        )

    def test_handles_unquoted_input(self) -> None:
        out = mod._replace_scalar(
            "  last_checked: 2026-04-26\n",
            "last_checked:",
            "2026-05-01",
        )
        self.assertEqual(out, '  last_checked: "2026-05-01"\n')

    def test_handles_no_trailing_newline(self) -> None:
        out = mod._replace_scalar(
            'last_checked: "2026-04-26"',
            "last_checked:",
            "2026-05-01",
        )
        self.assertEqual(out, 'last_checked: "2026-05-01"')


# ---------------------------------------------------------------------------
# Render summary
# ---------------------------------------------------------------------------


class RenderSummaryTests(unittest.TestCase):
    def test_no_drift_message(self) -> None:
        out = mod.render_summary(set(), set(), "https://x", "2026-05-01")
        self.assertIn("No drift detected", out)
        self.assertIn("All catalog tools match", out)

    def test_additions_only(self) -> None:
        out = mod.render_summary(
            {"Glob", "Edit"}, set(), "https://x", "2026-05-01"
        )
        self.assertIn("drift detected", out)
        self.assertIn("Additions auto-applied (2)", out)
        self.assertIn("`Edit`", out)
        self.assertIn("`Glob`", out)
        self.assertNotIn("Candidate removals", out)

    def test_removals_only(self) -> None:
        out = mod.render_summary(
            set(), {"Stale"}, "https://x", "2026-05-01"
        )
        self.assertIn("drift detected", out)
        self.assertIn(
            "Candidate removals — review before deleting (1)", out
        )
        self.assertIn("`Stale`", out)
        self.assertNotIn("Additions auto-applied", out)

    def test_both_sections(self) -> None:
        out = mod.render_summary(
            {"Glob"}, {"Stale"}, "https://x", "2026-05-01"
        )
        self.assertIn("Additions auto-applied (1)", out)
        self.assertIn("Candidate removals — review before deleting (1)", out)


# ---------------------------------------------------------------------------
# Main / CLI
# ---------------------------------------------------------------------------


class _CatalogTempFile:
    """Context-manager helper: write a temp catalog file, yield its path."""

    def __init__(self, content: str) -> None:
        self._content = content
        self._path: str | None = None

    def __enter__(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._content)
        self._path = path
        return path

    def __exit__(self, *args: Any) -> None:
        if self._path is not None and os.path.exists(self._path):
            os.unlink(self._path)


def _patched_fetch(markdown: str) -> Any:
    """Return a mock that replaces ``mod.fetch`` with a fixed body."""
    return mock.patch.object(mod, "fetch", return_value=markdown)


_FIXTURE_MARKDOWN: str | None = None


def _load_fixture_markdown() -> str:
    global _FIXTURE_MARKDOWN
    if _FIXTURE_MARKDOWN is None:
        _FIXTURE_MARKDOWN = _read_fixture("tools-reference.md")
    return _FIXTURE_MARKDOWN


class MainTests(unittest.TestCase):
    """End-to-end tests of ``main`` with mocked fetch."""

    def test_default_mode_no_drift_does_not_modify_file(self) -> None:
        # No-drift runs must leave the YAML untouched so the catalog's
        # commit history is not polluted by weekly date-only bumps.
        markdown = _load_fixture_markdown()
        upstream = mod.extract_tools(markdown)
        catalog_yaml = _HAPPY_CATALOG.replace(
            "        harness_tools:\n"
            "          - Bash\n"
            "          - Read\n"
            "          - Edit\n",
            (
                "        harness_tools:\n"
                + "".join(f"          - {t}\n" for t in sorted(upstream))
            ),
        )
        with _CatalogTempFile(catalog_yaml) as path, _patched_fetch(markdown):
            with redirect_stdout(io.StringIO()):
                code = mod.main([
                    "--catalog-path", path,
                    "--today", "2026-05-01",
                ])
            self.assertEqual(code, 0)
            with open(path, "r", encoding="utf-8") as fh:
                rewritten = fh.read()
            self.assertEqual(rewritten, catalog_yaml)

    def test_dry_run_no_drift_exits_zero(self) -> None:
        # Build a catalog whose harness_tools matches the fixture exactly.
        markdown = _load_fixture_markdown()
        upstream = mod.extract_tools(markdown)
        catalog_yaml = _HAPPY_CATALOG.replace(
            "        harness_tools:\n"
            "          - Bash\n"
            "          - Read\n"
            "          - Edit\n",
            (
                "        harness_tools:\n"
                + "".join(f"          - {t}\n" for t in sorted(upstream))
            ),
        )
        with _CatalogTempFile(catalog_yaml) as path, _patched_fetch(markdown):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = mod.main([
                    "--dry-run",
                    "--catalog-path", path,
                    "--today", "2026-05-01",
                ])
            self.assertEqual(code, 0)
            self.assertIn("No drift detected", stdout.getvalue())

    def test_dry_run_drift_exits_one(self) -> None:
        markdown = _load_fixture_markdown()
        with _CatalogTempFile(_HAPPY_CATALOG) as path, _patched_fetch(markdown):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = mod.main([
                    "--dry-run",
                    "--catalog-path", path,
                    "--today", "2026-05-01",
                ])
            self.assertEqual(code, 1)
            self.assertIn("drift detected", stdout.getvalue())

    def test_default_mode_rewrites_file(self) -> None:
        markdown = _load_fixture_markdown()
        with _CatalogTempFile(_HAPPY_CATALOG) as path, _patched_fetch(markdown):
            with redirect_stdout(io.StringIO()):
                code = mod.main([
                    "--catalog-path", path,
                    "--today", "2026-05-01",
                ])
            self.assertEqual(code, 0)
            with open(path, "r", encoding="utf-8") as fh:
                rewritten = fh.read()
            # last_checked updated, additions inserted.
            self.assertIn('last_checked: "2026-05-01"', rewritten)
            self.assertIn("- WebFetch\n", rewritten)
            self.assertIn("- AskUserQuestion\n", rewritten)

    def test_dry_run_does_not_modify_file(self) -> None:
        markdown = _load_fixture_markdown()
        with _CatalogTempFile(_HAPPY_CATALOG) as path, _patched_fetch(markdown):
            with redirect_stdout(io.StringIO()):
                mod.main([
                    "--dry-run",
                    "--catalog-path", path,
                    "--today", "2026-05-01",
                ])
            with open(path, "r", encoding="utf-8") as fh:
                rewritten = fh.read()
            self.assertEqual(rewritten, _HAPPY_CATALOG)

    def test_fetch_error_exits_two(self) -> None:
        with _CatalogTempFile(_HAPPY_CATALOG) as path:
            with mock.patch.object(
                mod,
                "fetch",
                side_effect=mod.FetchError("HTTP 500"),
            ):
                stderr = io.StringIO()
                with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                    code = mod.main([
                        "--dry-run",
                        "--catalog-path", path,
                        "--today", "2026-05-01",
                    ])
                self.assertEqual(code, 2)
                self.assertIn("HTTP 500", stderr.getvalue())

    def test_parse_error_exits_three(self) -> None:
        broken = _HAPPY_CATALOG.replace("provenance:", "wrong_key:")
        with _CatalogTempFile(broken) as path, _patched_fetch("ignored"):
            stderr = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                code = mod.main([
                    "--dry-run",
                    "--catalog-path", path,
                    "--today", "2026-05-01",
                ])
            self.assertEqual(code, 3)
            self.assertIn("provenance", stderr.getvalue())

    def test_summary_out_writes_file(self) -> None:
        markdown = _load_fixture_markdown()
        fd, summary_path = tempfile.mkstemp(suffix=".md")
        os.close(fd)
        try:
            with _CatalogTempFile(_HAPPY_CATALOG) as path, \
                 _patched_fetch(markdown):
                with redirect_stdout(io.StringIO()):
                    code = mod.main([
                        "--catalog-path", path,
                        "--today", "2026-05-01",
                        "--summary-out", summary_path,
                    ])
                self.assertEqual(code, 0)
                with open(summary_path, "r", encoding="utf-8") as fh:
                    summary_text = fh.read()
                self.assertIn("Additions auto-applied", summary_text)
        finally:
            if os.path.exists(summary_path):
                os.unlink(summary_path)

    def test_json_mode_emits_machine_readable_payload(self) -> None:
        markdown = _load_fixture_markdown()
        with _CatalogTempFile(_HAPPY_CATALOG) as path, _patched_fetch(markdown):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = mod.main([
                    "--dry-run",
                    "--json",
                    "--catalog-path", path,
                    "--today", "2026-05-01",
                ])
            self.assertEqual(code, 1)
            import json as _json
            payload = _json.loads(stdout.getvalue())
            self.assertEqual(payload["drift"], True)
            self.assertEqual(payload["checked"], "2026-05-01")
            self.assertIn("AskUserQuestion", payload["additions"])
            # ``Edit`` is in the happy catalog already so it must NOT
            # appear in additions.
            self.assertNotIn("Edit", payload["additions"])
            self.assertEqual(payload["catalog_size"], 3)
            self.assertGreater(payload["upstream_size"], 30)
            self.assertIsInstance(payload["additions"], list)
            self.assertIsInstance(payload["removals"], list)
            # Lists are sorted for stable diffing.
            self.assertEqual(
                payload["additions"], sorted(payload["additions"])
            )

    def test_json_mode_no_drift_returns_empty_lists(self) -> None:
        markdown = _load_fixture_markdown()
        upstream = mod.extract_tools(markdown)
        catalog_yaml = _HAPPY_CATALOG.replace(
            "        harness_tools:\n"
            "          - Bash\n"
            "          - Read\n"
            "          - Edit\n",
            (
                "        harness_tools:\n"
                + "".join(f"          - {t}\n" for t in sorted(upstream))
            ),
        )
        with _CatalogTempFile(catalog_yaml) as path, _patched_fetch(markdown):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = mod.main([
                    "--dry-run",
                    "--json",
                    "--catalog-path", path,
                    "--today", "2026-05-01",
                ])
            self.assertEqual(code, 0)
            import json as _json
            payload = _json.loads(stdout.getvalue())
            self.assertEqual(payload["drift"], False)
            self.assertEqual(payload["additions"], [])
            self.assertEqual(payload["removals"], [])

    def test_today_default_uses_system_date(self) -> None:
        # Smoke-test: run without --today and confirm today's date
        # appears in the rewritten YAML.
        markdown = _load_fixture_markdown()
        today = datetime.date.today().isoformat()
        with _CatalogTempFile(_HAPPY_CATALOG) as path, _patched_fetch(markdown):
            with redirect_stdout(io.StringIO()):
                mod.main([
                    "--catalog-path", path,
                ])
            with open(path, "r", encoding="utf-8") as fh:
                rewritten = fh.read()
            self.assertIn(f'last_checked: "{today}"', rewritten)


if __name__ == "__main__":
    unittest.main()
