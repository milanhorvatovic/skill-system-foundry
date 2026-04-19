"""Tests for ``lib/prose_yaml.py``.

Matrix per IMPL-PLAN §4.7 / §4.2 / §4.3:
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
- Path with Windows-native separator → ``to_posix`` normalizes (G130).
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
        # terminates the block per CommonMark.  Documented limit (G13).
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
# extract_yaml_fences — opt-out marker (§4.3)
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
        # G120 — the function does not normalise paths; the caller does.
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
            # G68 — file path is POSIX even when the OS uses backslashes.
            self.assertNotIn("\\", findings[0]["file"])
        finally:
            os.unlink(path)

    def test_missing_file_propagates_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            prose_yaml.read_and_validate("/nonexistent/file.md")


if __name__ == "__main__":
    unittest.main()
