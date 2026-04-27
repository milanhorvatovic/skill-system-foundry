"""Tests for the language-agnostic fence extractor in ``lib.fence_scan``.

The extractor is the shared foundation for ``lib.prose_yaml`` (YAML
fence validation) and ``lib.validation`` (Bash fence/tool coherence
rule).  These tests cover the fence-edge mechanics in one place;
consumer-specific behaviour lives in the consumer test files.
"""

import os
import sys
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SCRIPTS_DIR = os.path.join(
    _REPO_ROOT, "skill-system-foundry", "scripts",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from lib.fence_scan import extract_fences, has_fence_with_language


# ===================================================================
# extract_fences — basic shape
# ===================================================================
class ExtractFencesShapeTests(unittest.TestCase):
    """Shape and language extraction for column-0 fences."""

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(extract_fences(""), [])

    def test_none_input_returns_empty(self) -> None:
        self.assertEqual(extract_fences(None), [])

    def test_simple_backtick_fence(self) -> None:
        text = "```bash\necho hi\n```\n"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["language"], "bash")
        self.assertEqual(records[0]["text"], "echo hi")
        self.assertEqual(records[0]["state"], "closed")
        self.assertEqual(records[0]["fence_marker"], "```")
        self.assertEqual(records[0]["open_line_index"], 0)
        self.assertEqual(records[0]["close_line_index"], 2)

    def test_simple_tilde_fence(self) -> None:
        text = "~~~bash\necho hi\n~~~\n"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["language"], "bash")
        self.assertEqual(records[0]["fence_marker"], "~~~")

    def test_no_language_token(self) -> None:
        text = "```\nplain\n```\n"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["language"], "")

    def test_four_backticks_invisible(self) -> None:
        text = "````bash\necho hi\n````\n"
        self.assertEqual(extract_fences(text), [])

    def test_four_tildes_invisible(self) -> None:
        text = "~~~~bash\necho hi\n~~~~\n"
        self.assertEqual(extract_fences(text), [])

    def test_indented_fence_invisible(self) -> None:
        text = "  ```bash\necho hi\n  ```\n"
        self.assertEqual(extract_fences(text), [])

    def test_whitespace_between_marker_and_language_invisible(self) -> None:
        # ``` followed by a space + token is not a valid opener under our
        # strict rule, so the bash fence is invisible.
        text = "``` bash\necho hi\n"
        records = extract_fences(text)
        self.assertEqual(
            [r for r in records if r["language"] == "bash"], [],
        )

    def test_whitespace_then_token_not_treated_as_empty_language_fence(
        self,
    ) -> None:
        # The strict subset rejects ``"``` bash"`` outright instead of
        # accepting it as a fence with ``language=""``.  Returning an
        # empty-language record here would consume the body and hide
        # any later well-formed fences (e.g. a real ```yaml block
        # below).  Confirm a subsequent proper fence is still detected.
        text = (
            "``` bash\n"
            "echo hi\n"
            "```yaml\n"
            "key: value\n"
            "```\n"
        )
        records = extract_fences(text)
        languages = [r["language"] for r in records]
        self.assertIn("yaml", languages)
        # Specifically: no record should claim ``language=""`` from the
        # malformed opener — the malformed line must be invisible.
        self.assertNotIn("", languages)

    def test_unterminated_fence_short_circuits(self) -> None:
        # Opens with bash, never closes — closer must be exactly "```"
        # (no language suffix). Per CommonMark, the rest of the document
        # is inside the unterminated fence so no further openers found.
        text = "intro\n```bash\necho hi\nmore body\n"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["state"], "unterminated")
        self.assertIsNone(records[0]["close_line_index"])

    def test_multiple_fences_assigned_sequential_ordinals(self) -> None:
        text = (
            "```bash\necho hi\n```\n"
            "text\n"
            "```python\nprint()\n```\n"
        )
        records = extract_fences(text)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["ordinal"], 1)
        self.assertEqual(records[0]["language"], "bash")
        self.assertEqual(records[1]["ordinal"], 2)
        self.assertEqual(records[1]["language"], "python")

    def test_crlf_input_normalized(self) -> None:
        text = "```bash\r\necho hi\r\n```\r\n"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["text"], "echo hi")

    def test_cr_only_input_normalized(self) -> None:
        text = "```bash\recho hi\r```\r"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["text"], "echo hi")

    def test_info_string_suffix_after_language_token(self) -> None:
        # CommonMark allows arbitrary info-string content after the
        # language token (separated by whitespace).  The extractor
        # captures the language and discards the suffix.
        text = "```yaml example.yml\nkey: value\n```\n"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["language"], "yaml")
        self.assertEqual(records[0]["state"], "closed")

    def test_info_string_suffix_with_tab_separator(self) -> None:
        text = "```bash\textra-info\necho hi\n```\n"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["language"], "bash")

    def test_info_string_suffix_on_tilde_fence(self) -> None:
        text = "~~~yaml example.yml\nkey: value\n~~~\n"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["language"], "yaml")


# ===================================================================
# extract_fences — fence_chars filter
# ===================================================================
class ExtractFencesFenceCharsTests(unittest.TestCase):
    """Restricting which fence characters are recognised."""

    def test_backtick_only_filter_hides_tilde(self) -> None:
        text = "~~~bash\necho hi\n~~~\n"
        self.assertEqual(
            extract_fences(text, fence_chars=frozenset({"`"})), [],
        )

    def test_backtick_only_filter_keeps_backtick(self) -> None:
        text = "```bash\necho hi\n```\n"
        records = extract_fences(text, fence_chars=frozenset({"`"}))
        self.assertEqual(len(records), 1)

    def test_default_accepts_both_kinds(self) -> None:
        text = (
            "```bash\necho hi\n```\n"
            "~~~python\nprint()\n~~~\n"
        )
        records = extract_fences(text)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["fence_marker"], "```")
        self.assertEqual(records[1]["fence_marker"], "~~~")

    def test_backtick_opener_does_not_close_on_tilde(self) -> None:
        text = "```bash\necho hi\n~~~\nplain\n```\n"
        records = extract_fences(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["state"], "closed")
        self.assertEqual(records[0]["text"], "echo hi\n~~~\nplain")


# ===================================================================
# extract_fences — language filter
# ===================================================================
class ExtractFencesLanguageFilterTests(unittest.TestCase):
    """Filtering returned records by language token."""

    def test_filter_returns_only_matching(self) -> None:
        text = (
            "```bash\necho\n```\n"
            "```python\nprint()\n```\n"
        )
        records = extract_fences(
            text, languages=frozenset({"bash"}),
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["language"], "bash")

    def test_filter_match_is_case_sensitive(self) -> None:
        text = "```Bash\necho\n```\n"
        records = extract_fences(
            text, languages=frozenset({"bash"}),
        )
        self.assertEqual(records, [])

    def test_filter_membership_set_with_multiple_languages(self) -> None:
        text = (
            "```bash\n```\n"
            "```sh\n```\n"
            "```python\n```\n"
        )
        records = extract_fences(
            text, languages=frozenset({"bash", "sh"}),
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(
            sorted(r["language"] for r in records), ["bash", "sh"],
        )

    def test_filter_none_returns_everything(self) -> None:
        text = (
            "```bash\n```\n"
            "```python\n```\n"
        )
        records = extract_fences(text, languages=None)
        self.assertEqual(len(records), 2)

    def test_filter_does_not_skip_intermediate_fences(self) -> None:
        # An intermediate non-matching fence still consumes its block;
        # the next opener is found correctly after it closes.
        text = (
            "```python\nprint()\n```\n"
            "```bash\necho\n```\n"
        )
        records = extract_fences(
            text, languages=frozenset({"bash"}),
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["language"], "bash")
        # Open line is line 3 of the document (0-indexed): the python
        # fence occupies lines 0-2 and the bash opener is line 3.
        self.assertEqual(records[0]["open_line_index"], 3)


# ===================================================================
# has_fence_with_language — predicate
# ===================================================================
class HasFenceWithLanguageTests(unittest.TestCase):
    """Boolean predicate for the tool-coherence rule."""

    def test_returns_true_when_match_present(self) -> None:
        text = "```bash\necho hi\n```\n"
        self.assertTrue(
            has_fence_with_language(text, frozenset({"bash"})),
        )

    def test_returns_false_when_no_match(self) -> None:
        text = "```python\nprint()\n```\n"
        self.assertFalse(
            has_fence_with_language(text, frozenset({"bash"})),
        )

    def test_returns_false_for_empty_input(self) -> None:
        self.assertFalse(
            has_fence_with_language("", frozenset({"bash"})),
        )

    def test_returns_false_for_none_input(self) -> None:
        self.assertFalse(
            has_fence_with_language(None, frozenset({"bash"})),
        )

    def test_returns_true_on_tilde_fence(self) -> None:
        text = "~~~bash\necho\n~~~\n"
        self.assertTrue(
            has_fence_with_language(text, frozenset({"bash"})),
        )

    def test_match_after_unmatched_intermediate_fence(self) -> None:
        text = (
            "```python\nprint()\n```\n"
            "```bash\necho\n```\n"
        )
        self.assertTrue(
            has_fence_with_language(text, frozenset({"bash"})),
        )

    def test_unterminated_non_match_returns_false(self) -> None:
        # First fence opens with python and never closes — the bash
        # fence below is inside the unterminated python block.
        text = (
            "```python\nprint()\n"
            "```bash\necho\n"
        )
        self.assertFalse(
            has_fence_with_language(text, frozenset({"bash"})),
        )

    def test_case_sensitive_match(self) -> None:
        text = "```Bash\necho\n```\n"
        self.assertFalse(
            has_fence_with_language(text, frozenset({"bash"})),
        )

    def test_membership_in_multi_language_set(self) -> None:
        text = "```sh\necho\n```\n"
        self.assertTrue(
            has_fence_with_language(
                text, frozenset({"bash", "sh", "shell", "zsh"}),
            ),
        )


if __name__ == "__main__":
    unittest.main()
