"""Tests for ``lib/prose_yaml.py``.

Test matrix:
- Known-good fence → no findings.
- Divergent fence → expected divergence finding surfaces.
- Strict-adjacency opt-out (both directions).
- ``yml`` / ``YAML`` / ``Yaml`` → INFO ``"did you mean 'yaml'?"``.
- Tilde / 4-backtick / indented fences invisible.
- Unterminated fence → FAIL.
- Empty fence → ``{}``, ordinal advances.
- Column-0 ``` `` ` ``` inside block scalar terminates early.
- Multi-fence ordinals monotonic.
- CRLF markdown handled identically to LF.
- Path with Windows-native separator → ``to_posix`` normalizes.
"""

import os
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib import prose_yaml  # noqa: E402


# ===================================================================
# extract_yaml_fences — fence shape rules
# ===================================================================


class ExtractYamlFencesShapeTests(unittest.TestCase):

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(prose_yaml.extract_yaml_fences(""), [])

    def test_simple_yaml_fence(self) -> None:
        text = "intro\n```yaml\nkey: value\n```\noutro\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["state"], "parsed")
        self.assertEqual(records[0]["text"], "key: value")
        self.assertEqual(records[0]["ordinal"], 1)

    def test_tilde_fence_is_invisible(self) -> None:
        text = "intro\n~~~yaml\nkey: value\n~~~\n"
        self.assertEqual(prose_yaml.extract_yaml_fences(text), [])

    def test_four_backtick_fence_is_invisible(self) -> None:
        text = "````yaml\nkey: value\n````\n"
        self.assertEqual(prose_yaml.extract_yaml_fences(text), [])

    def test_indented_fence_is_invisible(self) -> None:
        text = "  ```yaml\n  key: value\n  ```\n"
        self.assertEqual(prose_yaml.extract_yaml_fences(text), [])

    def test_whitespace_between_backticks_and_yaml_invisible(self) -> None:
        text = "``` yaml\nkey: value\n```\n"
        self.assertEqual(prose_yaml.extract_yaml_fences(text), [])

    def test_wrong_case_yml_recognised(self) -> None:
        text = "```yml\nkey: value\n```\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["state"], "wrong-case")

    def test_wrong_case_uppercase_recognised(self) -> None:
        text = "```YAML\nkey: value\n```\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(records[0]["state"], "wrong-case")

    def test_wrong_case_titlecase_recognised(self) -> None:
        text = "```Yaml\nkey: value\n```\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(records[0]["state"], "wrong-case")

    def test_unterminated_fence(self) -> None:
        text = "```yaml\nkey: value\nno-close\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(records[0]["state"], "unterminated")
        # unterminated stops the scan — only one record.
        self.assertEqual(len(records), 1)

    def test_empty_fence_state_parsed(self) -> None:
        text = "```yaml\n```\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(records[0]["state"], "parsed")
        self.assertEqual(records[0]["text"], "")

    def test_multiple_fences_ordinal_monotonic(self) -> None:
        text = (
            "```yaml\nk1: v1\n```\n"
            "between\n"
            "```yaml\nk2: v2\n```\n"
            "between\n"
            "```yaml\nk3: v3\n```\n"
        )
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual([r["ordinal"] for r in records], [1, 2, 3])

    def test_column_zero_backticks_inside_body_terminate_early(self) -> None:
        # ```yaml fence opens; the literal column-0 ``` inside the body
        # terminates the block per CommonMark.  Documented limit.
        text = "```yaml\nliteral: |\n```\n  more\n```\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(records[0]["state"], "parsed")
        self.assertEqual(records[0]["text"], "literal: |")

    def test_crlf_markdown_handled_identically(self) -> None:
        lf = "intro\n```yaml\nkey: value\n```\n"
        crlf = lf.replace("\n", "\r\n")
        self.assertEqual(
            prose_yaml.extract_yaml_fences(lf),
            prose_yaml.extract_yaml_fences(crlf),
        )


# ===================================================================
# extract_yaml_fences — opt-out marker
# ===================================================================


class OptOutAdjacencyTests(unittest.TestCase):

    def test_strict_adjacency_marks_ignored(self) -> None:
        text = "<!-- yaml-ignore -->\n```yaml\nbad: value\n```\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(records[0]["state"], "ignored")

    def test_blank_line_between_marker_and_fence_does_not_ignore(self) -> None:
        text = (
            "<!-- yaml-ignore -->\n"
            "\n"
            "```yaml\n"
            "still: validated\n"
            "```\n"
        )
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(records[0]["state"], "parsed")

    def test_marker_with_surrounding_whitespace_still_matches(self) -> None:
        text = "  <!-- yaml-ignore -->  \n```yaml\nbad: value\n```\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(records[0]["state"], "ignored")

    def test_wrong_case_covers_arbitrary_variants(self) -> None:
        # Any case variant of 'yaml' or 'yml' (other than the
        # canonical lowercase 'yaml') must surface as wrong-case.
        for token in ("YAML", "Yaml", "yAmL", "YML", "Yml", "yML"):
            text = f"```{token}\nfoo: bar\n```\n"
            records = prose_yaml.extract_yaml_fences(text)
            self.assertEqual(
                records[0]["state"], "wrong-case",
                f"{token!r} should be classified wrong-case",
            )
            self.assertEqual(records[0]["language"], token)

    def test_opt_out_marker_overrides_wrong_case(self) -> None:
        # The opt-out marker must apply regardless of opener classification,
        # so a wrong-case fence can be waived without surfacing an INFO.
        text = "<!-- yaml-ignore -->\n```YAML\nbad: value\n```\n"
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual(records[0]["state"], "ignored")

    def test_ordinal_advances_for_ignored_block(self) -> None:
        # An ignored fence still counts toward the ordinal stream so
        # the prose path's block numbering stays stable.
        text = (
            "<!-- yaml-ignore -->\n"
            "```yaml\nignored: 1\n```\n"
            "```yaml\nactive: 2\n```\n"
        )
        records = prose_yaml.extract_yaml_fences(text)
        self.assertEqual([r["state"] for r in records], ["ignored", "parsed"])
        self.assertEqual([r["ordinal"] for r in records], [1, 2])


# ===================================================================
# validate_prose_yaml — finding shape and routing
# ===================================================================


class ValidateProseYamlTests(unittest.TestCase):

    def test_known_good_fence_no_findings(self) -> None:
        text = "```yaml\nkey: value\n```\n"
        self.assertEqual(prose_yaml.validate_prose_yaml("doc.md", text), [])

    def test_divergent_fence_surfaces_finding(self) -> None:
        text = "```yaml\nkey: *alias\n```\n"
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f["severity"], "fail")
        self.assertEqual(f["tag"], "[spec]")
        self.assertEqual(f["block_ordinal"], 1)
        self.assertEqual(f["file"], "doc.md")
        self.assertIn("alias indicator", f["message"])

    def test_unterminated_fence_emits_fail(self) -> None:
        text = "```yaml\nkey: value\n"
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "fail")
        self.assertIn("unterminated", findings[0]["message"])

    def test_wrong_case_emits_info(self) -> None:
        text = "```YAML\nkey: value\n```\n"
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "info")
        self.assertIn("did you mean 'yaml'", findings[0]["message"])

    def test_structural_value_error_caught_and_emitted(self) -> None:
        # When the underlying parser raises ValueError, the prose path
        # catches it and emits a single LEVEL_FAIL finding rather than
        # propagating.  Mock the parser to guarantee the raise path
        # fires regardless of which constructs the parser rejects today.
        import unittest.mock
        with unittest.mock.patch(
            "lib.prose_yaml.parse_yaml_subset",
            side_effect=ValueError("synthetic structural failure"),
        ):
            findings = prose_yaml.validate_prose_yaml(
                "doc.md", "```yaml\nkey: value\n```\n"
            )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "fail")
        self.assertIn("structural parse error", findings[0]["message"])
        self.assertIn(
            "synthetic structural failure", findings[0]["message"]
        )

    def test_frontmatter_with_no_body_is_treated_as_valid(self) -> None:
        # A file where the closing ``---`` is the final line (no body
        # content after it) is still a valid frontmatter block; it
        # must not be mistaken for an unterminated block.
        text = "---\nname: demo\n---\n"
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(findings, [])

    def test_unterminated_opener_still_scans_body_fences(self) -> None:
        # A file that opens with ``---`` but has no closing delimiter
        # is ambiguous — it could be malformed frontmatter, or a
        # thematic break at line 1.  The prose check stays
        # conservative and scans the full text so body-level divergent
        # fences still reach the validator.  ``load_frontmatter``
        # surfaces the parse error separately when intent was
        # frontmatter.
        text = (
            "---\n"
            "some prose without a closing delimiter\n"
            "```yaml\n"
            "bad: *alias\n"
            "```\n"
        )
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(len(findings), 1)

    def test_prose_block_between_dashes_not_stripped(self) -> None:
        # A doc that starts with a thematic break ``---`` followed by
        # plain prose and another ``---`` must not have that leading
        # block silently stripped — ``parse_yaml_subset`` returns
        # ``{}`` for prose, but an empty parsed mapping is not enough
        # evidence that the block is real frontmatter.
        text = (
            "---\n"
            "Just a paragraph, not YAML.\n"
            "---\n"
            "```yaml\n"
            "bad: *alias\n"
            "```\n"
        )
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(len(findings), 1)

    def test_empty_frontmatter_is_stripped(self) -> None:
        # A ``---\\n---\\n`` block is still frontmatter for scope
        # purposes; fences after it are validated, fences before the
        # closer must not be.
        text = (
            "---\n"
            "---\n"
            "```yaml\nbad: *alias\n```\n"
        )
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(len(findings), 1)

    def test_frontmatter_boundary_is_line_based(self) -> None:
        # A ``---`` substring inside a YAML block scalar value must
        # not terminate the frontmatter block early.
        text = (
            "---\n"
            "description: |\n"
            "  embedded --- dashes are fine\n"
            "---\n"
            "```yaml\nbad: *alias\n```\n"
        )
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        # Body contains one divergent fence; the frontmatter contents
        # (including the line with ``---``) are not scanned.
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["block_ordinal"], 1)

    def test_thematic_break_is_not_stripped_as_frontmatter(self) -> None:
        # A Markdown thematic break (``---`` at column 0) at the top of
        # a file must not be misread as frontmatter — otherwise an
        # arbitrary chunk of the body would silently skip validation.
        text = (
            "---\n"
            "\n"
            "After the break, a divergent fence:\n"
            "---\n"
            "```yaml\nbad: *alias\n```\n"
        )
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["block_ordinal"], 1)

    def test_frontmatter_yaml_fence_not_scanned(self) -> None:
        # A ```yaml fence embedded inside a folded description in the
        # frontmatter must not be validated as body content.
        text = (
            "---\n"
            "name: demo\n"
            "description: >\n"
            "  sample: ```yaml\n"
            "  body here\n"
            "  ```\n"
            "---\n"
            "# Body\n"
            "```yaml\nok: value\n```\n"
        )
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(findings, [])

    def test_ignored_fence_produces_no_findings(self) -> None:
        text = "<!-- yaml-ignore -->\n```yaml\nbad: *alias\n```\n"
        self.assertEqual(prose_yaml.validate_prose_yaml("doc.md", text), [])

    def test_empty_fence_produces_no_findings(self) -> None:
        text = "```yaml\n```\n"
        self.assertEqual(prose_yaml.validate_prose_yaml("doc.md", text), [])

    def test_multi_fence_findings_carry_ordinal(self) -> None:
        text = (
            "```yaml\nok: value\n```\n"
            "between\n"
            "```yaml\nbad: *alias\n```\n"
        )
        findings = prose_yaml.validate_prose_yaml("doc.md", text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["block_ordinal"], 2)

    def test_file_path_echoed_verbatim(self) -> None:
        # The function does not normalise paths; the caller does.
        text = "```yaml\nbad: *alias\n```\n"
        findings = prose_yaml.validate_prose_yaml(
            "skill\\caps\\thing.md", text
        )
        self.assertEqual(findings[0]["file"], "skill\\caps\\thing.md")


# ===================================================================
# read_and_validate — convenience wrapper, to_posix normalization
# ===================================================================


class ReadAndValidateTests(unittest.TestCase):

    def test_round_trip(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("```yaml\nbad: *alias\n```\n")
            path = fh.name
        try:
            findings = prose_yaml.read_and_validate(path)
            self.assertEqual(len(findings), 1)
            # File path is POSIX even when the OS uses backslashes.
            self.assertNotIn("\\", findings[0]["file"])
        finally:
            os.unlink(path)

    def test_missing_file_propagates_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            prose_yaml.read_and_validate("/nonexistent/file.md")


class FindInScopeFilesTests(unittest.TestCase):
    """``find_in_scope_files`` walks the three configured globs only."""

    def _make_skill_root(self) -> str:
        root = tempfile.mkdtemp()
        # In-scope files
        for rel in (
            "SKILL.md",
            "capabilities/foo/capability.md",
            "capabilities/foo/sub.md",
            "references/main.md",
            "references/nested/deep.md",
        ):
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# heading\n")
        # Out-of-scope files
        for rel in ("README.md", "CHANGELOG.md", "assets/template.md"):
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# heading\n")
        return root

    def test_only_in_scope_files_returned(self) -> None:
        root = self._make_skill_root()
        try:
            paths = prose_yaml.find_in_scope_files(root)
            relatives = sorted(
                os.path.relpath(p, root).replace(os.sep, "/")
                for p in paths
            )
            self.assertEqual(
                relatives,
                [
                    "SKILL.md",
                    "capabilities/foo/capability.md",
                    "capabilities/foo/sub.md",
                    "references/main.md",
                    "references/nested/deep.md",
                ],
            )
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


class CollectProseFindingsTests(unittest.TestCase):
    """``collect_prose_findings`` aggregates fences across in-scope files."""

    def _build_skill(self, content_by_rel: dict[str, str]) -> str:
        root = tempfile.mkdtemp()
        for rel, text in content_by_rel.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path) or root, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return root

    def test_clean_skill_returns_no_findings(self) -> None:
        root = self._build_skill({
            "SKILL.md": "intro\n```yaml\nkey: value\n```\n",
        })
        try:
            findings, checked, per_file = prose_yaml.collect_prose_findings(root)
            self.assertEqual(findings, [])
            self.assertEqual(checked, 1)
            self.assertEqual(per_file, [("SKILL.md", 1)])
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_divergent_skill_aggregates_findings(self) -> None:
        root = self._build_skill({
            "SKILL.md": "```yaml\nkey: *alias\n```\n",
            "references/foo.md": "```yaml\nbad: @reserved\n```\n",
        })
        try:
            findings, checked, _ = prose_yaml.collect_prose_findings(root)
            self.assertEqual(checked, 2)
            self.assertEqual(len(findings), 2)
            self.assertEqual(
                {f["file"] for f in findings},
                {"SKILL.md", "references/foo.md"},
            )
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_audit_prefix_applied(self) -> None:
        root = self._build_skill({
            "SKILL.md": "```yaml\nkey: *alias\n```\n",
        })
        try:
            findings, _, per_file = prose_yaml.collect_prose_findings(
                root, audit_prefix="skills/demo"
            )
            self.assertEqual(findings[0]["file"], "skills/demo/SKILL.md")
            self.assertEqual(per_file[0][0], "skills/demo/SKILL.md")
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


    def test_unreadable_file_becomes_structured_fail(self) -> None:
        # A UTF-8 decode failure must surface as a FAIL finding rather
        # than a raw exception that tears down the walk.
        root = tempfile.mkdtemp()
        try:
            skill_md = os.path.join(root, "SKILL.md")
            with open(skill_md, "wb") as fh:
                fh.write(b"\xff\xfe not utf-8 at all")
            findings, checked, per_file = prose_yaml.collect_prose_findings(root)
            self.assertEqual(checked, 0)
            self.assertEqual(per_file, [("SKILL.md", 0)])
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["severity"], "fail")
            self.assertEqual(findings[0]["file"], "SKILL.md")
            self.assertIsNone(findings[0]["block_ordinal"])
            self.assertIn("could not read file", findings[0]["message"])
            # The human-formatted line omits the "block N" segment.
            formatted = prose_yaml.format_finding_as_string(findings[0])
            self.assertNotIn("block 0", formatted)
            self.assertNotIn("block None", formatted)
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


class FormatFindingAsStringTests(unittest.TestCase):
    """Round-trip a structured finding back into the parser-string shape."""

    def test_fail_with_spec_tag(self) -> None:
        finding = {
            "file": "doc.md",
            "block_ordinal": 2,
            "severity": "fail",
            "tag": "[spec]",
            "message": "'key': bad value; advice",
        }
        self.assertEqual(
            prose_yaml.format_finding_as_string(finding),
            "FAIL: [spec] doc.md block 2: 'key': bad value; advice",
        )

    def test_warn_with_empty_tag_defaults_to_spec(self) -> None:
        finding = {
            "file": "x.md",
            "block_ordinal": 1,
            "severity": "warn",
            "tag": "",
            "message": "structural parse error",
        }
        self.assertEqual(
            prose_yaml.format_finding_as_string(finding),
            "WARN: [spec] x.md block 1: structural parse error",
        )

    def test_info_severity(self) -> None:
        finding = {
            "file": "x.md",
            "block_ordinal": 3,
            "severity": "info",
            "tag": "[spec]",
            "message": "something",
        }
        self.assertEqual(
            prose_yaml.format_finding_as_string(finding),
            "INFO: [spec] x.md block 3: something",
        )


if __name__ == "__main__":
    unittest.main()
