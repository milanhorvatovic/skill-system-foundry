"""Tests for .github/scripts/verify-action-pins.py.

Covers:
  * ``classify`` — every row of the rules table plus rejected forms
    (tag, branch name, uppercase hex, short hex, missing '@', missing
    owner or repo segment, parent-traversal local path, empty value,
    whitespace-only value, bare ``./``, bare ``docker://``).
  * ``_strip_inline`` — unquoted + trailing YAML comment, single- and
    double-quoted values with trailing comment, no comment, unterminated
    quote, tab-separated comment.
  * ``scan_workflow`` — list-item form (``- uses:``), key form, full-line
    comment skipping, indented keys, multiple violations, zero
    violations, line numbering.
  * ``collect_violations`` — mixed workflow directory with allowed and
    disallowed forms, relative-path reporting, unreadable-file
    surfacing, empty directory.
  * ``main`` — human output, JSON output, usage-error exit code,
    run against the real repository workflows.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

# The filename uses hyphens so import the module via importlib.
import importlib.util

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
_SCRIPT_PATH = os.path.join(
    _REPO_ROOT, ".github", "scripts", "verify-action-pins.py"
)
_spec = importlib.util.spec_from_file_location(
    "verify_action_pins", _SCRIPT_PATH
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load module from {_SCRIPT_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
classify = _mod.classify
_strip_inline = _mod._strip_inline
scan_workflow = _mod.scan_workflow
collect_violations = _mod.collect_violations
list_workflow_files = _mod.list_workflow_files
format_human = _mod.format_human
main = _mod.main


# A canonical 40-character lowercase hex SHA for fixtures.
_SHA = "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
_OTHER_SHA = "a" * 40


def _write(path: str, content: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


# ===================================================================
# classify — rules table
# ===================================================================


class ClassifyAllowedTests(unittest.TestCase):
    """Every row of the 'allowed' column must return None."""

    def test_org_repo_sha(self) -> None:
        self.assertIsNone(classify(f"actions/checkout@{_SHA}"))

    def test_org_repo_subpath_sha(self) -> None:
        self.assertIsNone(
            classify(f"milanhorvatovic/codex-ai-code-review-action/prepare@{_SHA}")
        )

    def test_org_repo_multi_subpath_sha(self) -> None:
        self.assertIsNone(classify(f"org/repo/a/b/c@{_SHA}"))

    def test_local_action_dot_slash(self) -> None:
        self.assertIsNone(classify("./.github/actions/foo"))

    def test_docker_tag(self) -> None:
        self.assertIsNone(classify("docker://alpine:3.19"))

    def test_docker_sha256(self) -> None:
        self.assertIsNone(
            classify("docker://alpine@sha256:" + "a" * 64)
        )


class ClassifyRejectedTests(unittest.TestCase):
    """Every disallowed form must return a non-empty reason string."""

    def test_tag_ref_rejected(self) -> None:
        reason = classify("actions/checkout@v4")
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("40-character", reason)

    def test_branch_ref_rejected(self) -> None:
        reason = classify("actions/checkout@main")
        self.assertIsNotNone(reason)

    def test_short_sha_rejected(self) -> None:
        reason = classify("actions/checkout@abcdef0")
        self.assertIsNotNone(reason)

    def test_uppercase_hex_rejected(self) -> None:
        # Policy is lowercase hex only.
        reason = classify("actions/checkout@" + _SHA.upper())
        self.assertIsNotNone(reason)

    def test_forty_char_non_hex_rejected(self) -> None:
        reason = classify("actions/checkout@" + "g" * 40)
        self.assertIsNotNone(reason)

    def test_missing_at_rejected(self) -> None:
        reason = classify("actions/checkout")
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("pin", reason)

    def test_missing_owner_rejected(self) -> None:
        reason = classify(f"checkout@{_SHA}")
        self.assertIsNotNone(reason)

    def test_parent_traversal_local_path_rejected(self) -> None:
        reason = classify("../foo")
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("parent traversal", reason)

    def test_dot_slash_parent_traversal_rejected(self) -> None:
        # The accept-./ branch must not short-circuit when the path
        # immediately escapes via ../ — this was a Codex-flagged bypass.
        reason = classify("./../foo")
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("parent traversal", reason)

    def test_embedded_parent_traversal_rejected(self) -> None:
        reason = classify("./foo/../bar")
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("parent traversal", reason)

    def test_trailing_parent_segment_rejected(self) -> None:
        reason = classify("./foo/..")
        self.assertIsNotNone(reason)

    def test_bare_double_dot_rejected(self) -> None:
        reason = classify("..")
        self.assertIsNotNone(reason)

    def test_empty_value_rejected(self) -> None:
        reason = classify("")
        self.assertIsNotNone(reason)

    def test_trailing_at_with_empty_ref_rejected(self) -> None:
        reason = classify("actions/checkout@")
        self.assertIsNotNone(reason)

    def test_empty_repo_segment_rejected(self) -> None:
        # Copilot-flagged bypass: ``org/@<sha>`` previously passed
        # because the naive ``"/" in prefix`` check was truthy even
        # though the repo segment is empty.
        reason = classify(f"org/@{_SHA}")
        self.assertIsNotNone(reason)

    def test_empty_owner_segment_rejected(self) -> None:
        reason = classify(f"/repo@{_SHA}")
        self.assertIsNotNone(reason)

    def test_double_slash_in_prefix_rejected(self) -> None:
        reason = classify(f"org//sub@{_SHA}")
        self.assertIsNotNone(reason)

    def test_bare_slash_prefix_rejected(self) -> None:
        reason = classify(f"/@{_SHA}")
        self.assertIsNotNone(reason)

    def test_bare_dot_slash_rejected(self) -> None:
        # ``./`` with no suffix is not a real local action path.
        reason = classify("./")
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("empty", reason)

    def test_bare_docker_scheme_rejected(self) -> None:
        # ``docker://`` with no image reference is a malformed value
        # that would fail at workflow runtime; the gate rejects it.
        reason = classify("docker://")
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("empty", reason)

    def test_whitespace_only_value_is_empty(self) -> None:
        # classify strips its input so a standalone caller passing
        # whitespace-only text gets the same "empty uses value" reason
        # the scan path produces.
        reason = classify("    ")
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("empty", reason)


# ===================================================================
# _strip_inline — comment and quote handling
# ===================================================================


class StripInlineTests(unittest.TestCase):

    def test_plain_value(self) -> None:
        self.assertEqual(
            _strip_inline(f"actions/checkout@{_SHA}"),
            f"actions/checkout@{_SHA}",
        )

    def test_trailing_space_comment_stripped(self) -> None:
        self.assertEqual(
            _strip_inline(f"actions/checkout@{_SHA} # @v6 as 6.0.2"),
            f"actions/checkout@{_SHA}",
        )

    def test_trailing_tab_comment_stripped(self) -> None:
        self.assertEqual(
            _strip_inline(f"actions/checkout@{_SHA}\t# pinned"),
            f"actions/checkout@{_SHA}",
        )

    def test_single_quoted_value(self) -> None:
        self.assertEqual(
            _strip_inline(f"'actions/checkout@{_SHA}'  # comment"),
            f"actions/checkout@{_SHA}",
        )

    def test_double_quoted_value(self) -> None:
        self.assertEqual(
            _strip_inline(f'"actions/checkout@{_SHA}"'),
            f"actions/checkout@{_SHA}",
        )

    def test_unterminated_quote_falls_through(self) -> None:
        # Should not crash; returns as-is so classify surfaces a failure.
        result = _strip_inline(f"'actions/checkout@{_SHA}")
        self.assertIn(_SHA, result)

    def test_hash_without_leading_space_kept(self) -> None:
        # '#' not preceded by whitespace is part of the value, not a
        # comment. Classifier will still reject because the ref is not
        # a bare 40-hex SHA — but the stripper must not eat it.
        self.assertEqual(
            _strip_inline("actions/checkout@abc#frag"),
            "actions/checkout@abc#frag",
        )

    def test_empty_input(self) -> None:
        self.assertEqual(_strip_inline(""), "")

    def test_leading_hash_treated_as_empty(self) -> None:
        # A YAML value that is a bare comment ("uses: # trailing") has
        # no real right-hand side — return empty so classify reports
        # "empty uses value" rather than a misleading pin reason.
        self.assertEqual(_strip_inline("# comment"), "")
        self.assertEqual(_strip_inline("#"), "")


# ===================================================================
# scan_workflow — line-level behaviour
# ===================================================================


_VALID_WORKFLOW = f"""name: ok
on: push
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@{_SHA} # @v6 as 6.0.2
      - uses: org/repo/sub@{_OTHER_SHA}
      - name: Local
        uses: ./.github/actions/foo
      - name: Docker
        uses: docker://alpine:3.19
"""


_INVALID_WORKFLOW = f"""name: bad
on: push
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@main
      - uses: '../escape'
      # uses: actions/ignored@v1   # full-line comment, must be skipped
      - uses: "actions/quoted@v2"
"""


class ScanWorkflowTests(unittest.TestCase):

    def test_valid_workflow_has_no_violations(self) -> None:
        self.assertEqual(scan_workflow(_VALID_WORKFLOW), [])

    def test_invalid_workflow_flags_each_bad_line(self) -> None:
        violations = scan_workflow(_INVALID_WORKFLOW)
        # Expect four violations: v4, main, ../escape, quoted@v2.
        self.assertEqual(len(violations), 4)
        values = [v[1] for v in violations]
        self.assertIn("actions/checkout@v4", values)
        self.assertIn("actions/setup-python@main", values)
        self.assertIn("../escape", values)
        self.assertIn("actions/quoted@v2", values)

    def test_full_line_comment_is_skipped(self) -> None:
        violations = scan_workflow(_INVALID_WORKFLOW)
        self.assertFalse(
            any("ignored" in v[1] for v in violations),
            f"commented-out line was picked up: {violations}",
        )

    def test_line_numbers_are_one_indexed(self) -> None:
        text = "steps:\n  - uses: actions/checkout@v4\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][0], 2)

    def test_key_form_without_list_marker(self) -> None:
        text = f"uses: actions/checkout@v4\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "actions/checkout@v4")

    def test_indented_key_form(self) -> None:
        text = f"        uses: actions/checkout@{_SHA}\n"
        self.assertEqual(scan_workflow(text), [])

    def test_uses_inside_run_block_not_flagged_when_commented(self) -> None:
        # Full-line comment is always safe; the line-based scanner is
        # not expected to understand multi-line ``run:`` bodies, so this
        # test only asserts the commented-out form is skipped.
        text = "      # uses: actions/checkout@v4\n"
        self.assertEqual(scan_workflow(text), [])

    def test_single_quoted_key_is_flagged(self) -> None:
        # Codex-flagged bypass: YAML permits quoted mapping keys, and
        # GitHub Actions treats them identically. The gate must detect
        # them or an unpinned action can slip past.
        text = "      - 'uses': actions/checkout@v4\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "actions/checkout@v4")

    def test_double_quoted_key_is_flagged(self) -> None:
        text = '      - "uses": actions/checkout@main\n'
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "actions/checkout@main")

    def test_quoted_key_with_quoted_value_is_flagged(self) -> None:
        text = "      - 'uses': 'actions/checkout@v4'\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "actions/checkout@v4")

    def test_empty_uses_value_is_flagged(self) -> None:
        # Copilot-flagged hole: an empty ``uses:`` used to be missed
        # because the value regex required at least one non-whitespace
        # character. classify already rejects "" — the scanner must now
        # reach it.
        text = "      - uses:\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "")
        self.assertIn("empty", violations[0][2])

    def test_whitespace_only_uses_value_is_flagged(self) -> None:
        text = "      - uses:   \n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "")

    def test_dot_slash_parent_traversal_line_is_flagged(self) -> None:
        text = "      - uses: ./../escape\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertIn("parent traversal", violations[0][2])

    def test_inline_comment_after_empty_uses_is_flagged_as_empty(self) -> None:
        # Copilot-flagged misleading output: ``uses: # comment`` must
        # report an empty value rather than treating the comment as the
        # literal reference.
        text = "      - uses: # just a note\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "")
        self.assertIn("empty", violations[0][2])

    def test_flow_style_tag_is_flagged(self) -> None:
        # Copilot-flagged flow-style bypass: ``- { uses: ref }`` is
        # valid YAML and valid GHA step syntax; the gate must match it.
        text = "      - { uses: actions/checkout@v4 }\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "actions/checkout@v4")

    def test_flow_style_pinned_is_allowed(self) -> None:
        text = f"      - {{ uses: actions/checkout@{_SHA} }}\n"
        self.assertEqual(scan_workflow(text), [])

    def test_flow_style_uses_after_other_keys_is_flagged(self) -> None:
        text = "      - { name: co, uses: actions/checkout@main }\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "actions/checkout@main")

    def test_flow_style_quoted_key_is_flagged(self) -> None:
        text = "      - { 'uses': actions/checkout@v4 }\n"
        violations = scan_workflow(text)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "actions/checkout@v4")


# ===================================================================
# collect_violations / list_workflow_files
# ===================================================================


class CollectViolationsTests(unittest.TestCase):

    def test_mixed_directory_labels_paths_canonically(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            wf = os.path.join(root, ".github", "workflows")
            _write(
                os.path.join(wf, "good.yaml"),
                _VALID_WORKFLOW,
            )
            _write(
                os.path.join(wf, "bad.yml"),
                _INVALID_WORKFLOW,
            )
            violations = collect_violations(wf)
            files = {v["file"] for v in violations}
            # Only bad.yml should contribute, labelled with the
            # production .github/workflows/ prefix regardless of where
            # the temp directory lives on disk.
            self.assertEqual(
                files,
                {".github/workflows/bad.yml"},
            )
            # Paths use forward slashes even on Windows.
            for v in violations:
                self.assertNotIn("\\", v["file"])

    def test_sorted_by_file_then_line(self) -> None:
        with tempfile.TemporaryDirectory() as wf:
            _write(
                os.path.join(wf, "z.yaml"),
                f"uses: actions/checkout@v4\nuses: actions/checkout@main\n",
            )
            _write(
                os.path.join(wf, "a.yaml"),
                f"uses: actions/checkout@v4\n",
            )
            violations = collect_violations(wf)
            self.assertEqual(
                [(v["file"], v["line"]) for v in violations],
                [
                    (".github/workflows/a.yaml", 1),
                    (".github/workflows/z.yaml", 1),
                    (".github/workflows/z.yaml", 2),
                ],
            )

    def test_missing_directory_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                collect_violations(os.path.join(root, "does-not-exist")),
                [],
            )
            self.assertEqual(
                list_workflow_files(os.path.join(root, "does-not-exist")),
                [],
            )

    def test_non_yaml_file_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as wf:
            _write(
                os.path.join(wf, "README.md"),
                "uses: actions/checkout@v4\n",
            )
            self.assertEqual(collect_violations(wf), [])

    def test_empty_workflow_file_produces_no_violations(self) -> None:
        with tempfile.TemporaryDirectory() as wf:
            _write(os.path.join(wf, "empty.yaml"), "")
            self.assertEqual(collect_violations(wf), [])

    def test_comments_only_file_produces_no_violations(self) -> None:
        with tempfile.TemporaryDirectory() as wf:
            _write(
                os.path.join(wf, "comments.yaml"),
                "# uses: actions/checkout@v4\n# another comment\n",
            )
            self.assertEqual(collect_violations(wf), [])

    def test_unreadable_file_surfaces_as_read_error(self) -> None:
        with tempfile.TemporaryDirectory() as wf:
            path = os.path.join(wf, "oops.yaml")
            _write(path, "placeholder")
            # Force an OSError from ``open`` without touching the FS.
            real_open = open

            def _boom(p, *args, **kwargs):  # type: ignore[no-untyped-def]
                if os.path.abspath(p) == os.path.abspath(path):
                    raise OSError("simulated unreadable")
                return real_open(p, *args, **kwargs)

            with mock.patch("builtins.open", side_effect=_boom):
                violations = collect_violations(wf)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0]["line"], 0)
            self.assertIn("read-error", violations[0]["reason"])


# ===================================================================
# format_human
# ===================================================================


class FormatHumanTests(unittest.TestCase):

    def test_empty(self) -> None:
        self.assertEqual(
            format_human([]),
            "All workflow `uses:` references are SHA-pinned.",
        )

    def test_single(self) -> None:
        line = format_human(
            [
                {
                    "file": ".github/workflows/bad.yaml",
                    "line": 7,
                    "uses": "actions/checkout@v4",
                    "reason": "not pinned",
                }
            ]
        )
        self.assertEqual(
            line,
            "FAIL: .github/workflows/bad.yaml:7: actions/checkout@v4 -- not pinned",
        )


# ===================================================================
# main — CLI wiring
# ===================================================================


class MainTests(unittest.TestCase):

    def _run(
        self, argv: list[str]
    ) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_clean_run_human(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            wf = os.path.join(root, ".github", "workflows")
            _write(os.path.join(wf, "ok.yaml"), _VALID_WORKFLOW)
            code, stdout, _ = self._run(["--workflows-dir", wf])
        self.assertEqual(code, 0)
        self.assertIn("SHA-pinned", stdout)

    def test_violations_return_one(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            wf = os.path.join(root, ".github", "workflows")
            _write(os.path.join(wf, "bad.yaml"), _INVALID_WORKFLOW)
            code, stdout, _ = self._run(["--workflows-dir", wf])
        self.assertEqual(code, 1)
        self.assertIn("FAIL:", stdout)

    def test_json_output_shape(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            wf = os.path.join(root, ".github", "workflows")
            _write(os.path.join(wf, "bad.yaml"), _INVALID_WORKFLOW)
            code, stdout, _ = self._run(["--workflows-dir", wf, "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout)
        self.assertIsInstance(payload, list)
        self.assertTrue(payload)
        for entry in payload:
            self.assertEqual(
                set(entry.keys()), {"file", "line", "uses", "reason"}
            )
            self.assertEqual(entry["file"], ".github/workflows/bad.yaml")

    def test_json_empty_output(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            wf = os.path.join(root, ".github", "workflows")
            _write(os.path.join(wf, "ok.yaml"), _VALID_WORKFLOW)
            code, stdout, _ = self._run(["--workflows-dir", wf, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), [])

    def test_usage_error_returns_two(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--nope"])
        self.assertEqual(code, 2)

    def test_real_repository_workflows_pass(self) -> None:
        # The whole point: the repo's current workflow files are all
        # SHA-pinned, so the default invocation must succeed.
        code, _, _ = self._run([])
        self.assertEqual(code, 0)

    def test_missing_workflows_dir_fails_closed(self) -> None:
        # Copilot-flagged false-green: a missing directory used to exit
        # 0 with "All workflow `uses:` references are SHA-pinned." The
        # gate now fails closed with a clear error on stderr.
        with tempfile.TemporaryDirectory() as root:
            ghost = os.path.join(root, "does-not-exist")
            code, stdout, stderr = self._run(["--workflows-dir", ghost])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("workflows directory not found", stderr)


if __name__ == "__main__":
    unittest.main()
