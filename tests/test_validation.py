"""Tests for lib/validation.py.

Covers validate_name with comprehensive test cases for all validation rules:
empty name, length limits, lowercase enforcement, format pattern, consecutive
hyphens, underscores, spaces, directory name matching, reserved words, and
minimum length warnings.
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

from helpers import write_capability_md, write_skill_md, write_text
from lib.validation import (
    aggregate_capability_allowed_tools,
    parse_allowed_tools_tokens,
    validate_capability_skill_only_fields,
    validate_description_triggers,
    validate_name,
    validate_tool_coherence,
)
from lib.constants import (
    DESCRIPTION_TRIGGER_PHRASES,
    LEVEL_FAIL,
    LEVEL_INFO,
    LEVEL_WARN,
    MAX_NAME_CHARS,
    MIN_NAME_CHARS,
    RESERVED_NAMES,
)


# ===================================================================
# Empty Name
# ===================================================================


class ValidateNameEmptyTests(unittest.TestCase):
    """Tests for validate_name when the name is empty."""

    def test_empty_string_returns_fail(self) -> None:
        """An empty name produces a single FAIL error and no passes."""
        errors, passes = validate_name("", "some-dir")
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_FAIL, errors[0])
        self.assertIn("empty", errors[0])
        self.assertEqual(passes, [])

    def test_empty_string_short_circuits(self) -> None:
        """An empty name returns immediately without running further checks."""
        errors, passes = validate_name("", "")
        # Only the single "empty" error — no format, length, or directory checks
        self.assertEqual(len(errors), 1)
        self.assertEqual(passes, [])


# ===================================================================
# Name Length
# ===================================================================


class ValidateNameLengthTests(unittest.TestCase):
    """Tests for the name length validation (max and min)."""

    def test_name_at_max_length_passes(self) -> None:
        """A name at exactly MAX_NAME_CHARS passes the length check."""
        name = "a" * MAX_NAME_CHARS
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "exceeds" in e]
        self.assertEqual(fail_errors, [])
        char_pass = [p for p in passes if "chars" in p]
        self.assertEqual(len(char_pass), 1)
        self.assertIn(str(MAX_NAME_CHARS), char_pass[0])

    def test_name_one_over_max_length_returns_fail(self) -> None:
        """A name one character over MAX_NAME_CHARS produces a FAIL."""
        name = "a" * (MAX_NAME_CHARS + 1)
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "exceeds" in e]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn(str(MAX_NAME_CHARS), fail_errors[0])
        self.assertIn(str(MAX_NAME_CHARS + 1), fail_errors[0])
        # No char-count pass when over limit
        char_pass = [p for p in passes if "chars" in p]
        self.assertEqual(char_pass, [])

    def test_name_well_over_max_length_returns_fail(self) -> None:
        """A name well above MAX_NAME_CHARS produces a FAIL."""
        name = "a" * (MAX_NAME_CHARS + 50)
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "exceeds" in e]
        self.assertEqual(len(fail_errors), 1)

    def test_short_name_returns_info(self) -> None:
        """A name shorter than MIN_NAME_CHARS produces an INFO (foundry convention)."""
        # Use a single character — valid format but short by foundry standards
        name = "a"
        errors, passes = validate_name(name, name)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        short_infos = [e for e in info_errors if "character" in e]
        self.assertEqual(len(short_infos), 1)
        self.assertIn(str(len(name)), short_infos[0])
        self.assertIn("[foundry]", short_infos[0])

    def test_name_at_min_length_no_info(self) -> None:
        """A name at exactly MIN_NAME_CHARS does not produce an INFO."""
        name = "a" * MIN_NAME_CHARS
        errors, passes = validate_name(name, name)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        short_infos = [e for e in info_errors if "character" in e]
        self.assertEqual(short_infos, [])

    def test_name_one_below_min_length_returns_info(self) -> None:
        """A name one character below MIN_NAME_CHARS produces an INFO."""
        name = "a" * (MIN_NAME_CHARS - 1)
        errors, passes = validate_name(name, name)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        short_infos = [e for e in info_errors if "character" in e]
        self.assertEqual(len(short_infos), 1)


# ===================================================================
# Lowercase Enforcement
# ===================================================================


class ValidateNameLowercaseTests(unittest.TestCase):
    """Tests for the lowercase enforcement rule."""

    def test_uppercase_name_returns_fail(self) -> None:
        """A name with uppercase characters produces a FAIL."""
        name = "Demo-Skill"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "uppercase" in e]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn(name, fail_errors[0])

    def test_all_uppercase_name_returns_fail(self) -> None:
        """An all-uppercase name produces a FAIL."""
        name = "DEMO-SKILL"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "uppercase" in e]
        self.assertEqual(len(fail_errors), 1)

    def test_mixed_case_name_returns_fail(self) -> None:
        """A mixed-case name produces a FAIL."""
        name = "demoSkill"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "uppercase" in e]
        self.assertEqual(len(fail_errors), 1)

    def test_lowercase_name_no_uppercase_error(self) -> None:
        """A fully lowercase name does not produce an uppercase FAIL."""
        name = "demo-skill"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "uppercase" in e]
        self.assertEqual(fail_errors, [])


# ===================================================================
# Format Pattern
# ===================================================================


class ValidateNameFormatTests(unittest.TestCase):
    """Tests for the name format pattern (lowercase alphanumeric + hyphens)."""

    def test_leading_hyphen_returns_fail(self) -> None:
        """A name starting with a hyphen produces a FAIL."""
        name = "-demo-skill"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "invalid format" in e]
        self.assertEqual(len(fail_errors), 1)

    def test_trailing_hyphen_returns_fail(self) -> None:
        """A name ending with a hyphen produces a FAIL."""
        name = "demo-skill-"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "invalid format" in e]
        self.assertEqual(len(fail_errors), 1)

    def test_special_characters_return_fail(self) -> None:
        """Names with special characters produce a FAIL."""
        invalid_names = ["demo.skill", "demo@skill", "demo!skill", "demo#skill"]
        for name in invalid_names:
            with self.subTest(name=name):
                errors, passes = validate_name(name, name)
                fail_errors = [
                    e for e in errors
                    if e.startswith(LEVEL_FAIL) and "invalid format" in e
                ]
                self.assertGreaterEqual(
                    len(fail_errors), 1,
                    f"Expected format FAIL for '{name}', got errors={errors}",
                )

    def test_valid_format_passes(self) -> None:
        """A valid format name produces a format pass."""
        name = "demo-skill"
        errors, passes = validate_name(name, name)
        format_pass = [p for p in passes if "valid format" in p]
        self.assertEqual(len(format_pass), 1)

    def test_single_character_valid_format(self) -> None:
        """A single lowercase character is a valid format."""
        name = "a"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "invalid format" in e]
        self.assertEqual(fail_errors, [])
        format_pass = [p for p in passes if "valid format" in p]
        self.assertEqual(len(format_pass), 1)

    def test_single_digit_valid_format(self) -> None:
        """A single digit is a valid format."""
        name = "7"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "invalid format" in e]
        self.assertEqual(fail_errors, [])

    def test_alphanumeric_with_hyphens_passes(self) -> None:
        """A name with letters, digits, and hyphens passes format check."""
        name = "my-skill-v2"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL) and "invalid format" in e]
        self.assertEqual(fail_errors, [])
        format_pass = [p for p in passes if "valid format" in p]
        self.assertEqual(len(format_pass), 1)


# ===================================================================
# Consecutive Hyphens
# ===================================================================


class ValidateNameConsecutiveHyphensTests(unittest.TestCase):
    """Tests for the consecutive hyphens rule."""

    def test_consecutive_hyphens_returns_fail(self) -> None:
        """A name with consecutive hyphens produces a FAIL."""
        name = "demo--skill"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "consecutive hyphens" in e
        ]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn(name, fail_errors[0])

    def test_triple_hyphens_returns_fail(self) -> None:
        """A name with triple hyphens produces a FAIL."""
        name = "demo---skill"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "consecutive hyphens" in e
        ]
        self.assertEqual(len(fail_errors), 1)

    def test_single_hyphens_no_consecutive_error(self) -> None:
        """A name with only single hyphens does not produce a consecutive FAIL."""
        name = "demo-skill-test"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "consecutive hyphens" in e
        ]
        self.assertEqual(fail_errors, [])


# ===================================================================
# Underscores
# ===================================================================


class ValidateNameUnderscoresTests(unittest.TestCase):
    """Tests for the underscores rule."""

    def test_underscore_returns_fail(self) -> None:
        """A name with underscores produces a FAIL."""
        name = "demo_skill"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "underscores" in e
        ]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn(name, fail_errors[0])

    def test_multiple_underscores_returns_fail(self) -> None:
        """A name with multiple underscores produces a FAIL."""
        name = "demo_skill_test"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "underscores" in e
        ]
        self.assertEqual(len(fail_errors), 1)

    def test_no_underscores_no_error(self) -> None:
        """A name without underscores does not produce an underscore FAIL."""
        name = "demo-skill"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "underscores" in e
        ]
        self.assertEqual(fail_errors, [])


# ===================================================================
# Spaces
# ===================================================================


class ValidateNameSpacesTests(unittest.TestCase):
    """Tests for the spaces rule."""

    def test_space_returns_fail(self) -> None:
        """A name with spaces produces a FAIL."""
        name = "demo skill"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "spaces" in e
        ]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn(name, fail_errors[0])

    def test_multiple_spaces_returns_fail(self) -> None:
        """A name with multiple spaces produces a FAIL."""
        name = "demo skill test"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "spaces" in e
        ]
        self.assertEqual(len(fail_errors), 1)

    def test_no_spaces_no_error(self) -> None:
        """A name without spaces does not produce a spaces FAIL."""
        name = "demo-skill"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "spaces" in e
        ]
        self.assertEqual(fail_errors, [])


# ===================================================================
# Directory Name Matching
# ===================================================================


class ValidateNameDirectoryMatchTests(unittest.TestCase):
    """Tests for the directory name matching rule."""

    def test_name_matches_directory_passes(self) -> None:
        """A name matching the directory name produces a pass."""
        name = "demo-skill"
        errors, passes = validate_name(name, name)
        dir_pass = [p for p in passes if "matches directory" in p]
        self.assertEqual(len(dir_pass), 1)

    def test_name_does_not_match_directory_returns_fail(self) -> None:
        """A name not matching the directory name produces a FAIL."""
        errors, passes = validate_name("demo-skill", "other-dir")
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "match" in e.lower()
        ]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn("demo-skill", fail_errors[0])
        self.assertIn("other-dir", fail_errors[0])

    def test_case_sensitive_directory_mismatch_returns_fail(self) -> None:
        """Directory matching is case-sensitive — different case produces a FAIL."""
        errors, passes = validate_name("demo-skill", "Demo-Skill")
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "match" in e.lower()
        ]
        self.assertEqual(len(fail_errors), 1)

    def test_directory_match_no_error_when_equal(self) -> None:
        """No directory mismatch error when name equals dir_name."""
        name = "my-tool"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "match" in e.lower()
        ]
        self.assertEqual(fail_errors, [])


# ===================================================================
# Reserved Words
# ===================================================================


class ValidateNameReservedWordsTests(unittest.TestCase):
    """Tests for the reserved words rule (platform: Anthropic)."""

    def test_each_reserved_word_returns_warn(self) -> None:
        """Each reserved word in the name produces a WARN (platform: Anthropic)."""
        for reserved in RESERVED_NAMES:
            name = f"my-{reserved}-skill"
            with self.subTest(reserved=reserved):
                errors, passes = validate_name(name, name)
                warn_errors = [
                    e for e in errors
                    if e.startswith(LEVEL_WARN) and "reserved" in e
                ]
                self.assertGreaterEqual(
                    len(warn_errors), 1,
                    f"Expected reserved word WARN for '{reserved}', "
                    f"got errors={errors}",
                )
                self.assertIn(reserved, warn_errors[0])
                self.assertIn("platform: Anthropic", warn_errors[0])

    def test_reserved_word_as_exact_name_returns_warn(self) -> None:
        """A name that is exactly a reserved word produces a WARN."""
        for reserved in RESERVED_NAMES:
            with self.subTest(reserved=reserved):
                errors, passes = validate_name(reserved, reserved)
                warn_errors = [
                    e for e in errors
                    if e.startswith(LEVEL_WARN) and "reserved" in e
                ]
                self.assertGreaterEqual(len(warn_errors), 1)

    def test_reserved_word_as_substring_returns_warn(self) -> None:
        """A reserved word appearing as a substring produces a WARN."""
        for reserved in RESERVED_NAMES:
            # Embed the reserved word without hyphens
            name = f"my{reserved}tool"
            with self.subTest(reserved=reserved, name=name):
                errors, passes = validate_name(name, name)
                warn_errors = [
                    e for e in errors
                    if e.startswith(LEVEL_WARN) and "reserved" in e
                ]
                self.assertGreaterEqual(
                    len(warn_errors), 1,
                    f"Expected reserved word WARN for substring '{reserved}' "
                    f"in '{name}', got errors={errors}",
                )

    def test_no_reserved_words_no_error(self) -> None:
        """A name without reserved words does not produce a reserved WARN."""
        name = "demo-skill"
        errors, passes = validate_name(name, name)
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "reserved" in e
        ]
        self.assertEqual(warn_errors, [])


# ===================================================================
# Valid Names (Happy Path)
# ===================================================================


class ValidateNameValidTests(unittest.TestCase):
    """Tests for valid names that should produce no FAIL errors."""

    def test_typical_valid_name(self) -> None:
        """A typical valid name produces no FAIL errors and expected passes."""
        name = "demo-skill"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        # Should have passes for: char count, valid format, matches directory
        self.assertGreaterEqual(len(passes), 3, msg=f"passes={passes}")
        char_pass = [p for p in passes if "chars" in p]
        format_pass = [p for p in passes if "valid format" in p]
        dir_pass = [p for p in passes if "matches directory" in p]
        self.assertEqual(len(char_pass), 1)
        self.assertEqual(len(format_pass), 1)
        self.assertEqual(len(dir_pass), 1)

    def test_valid_names_representative_sample(self) -> None:
        """A representative sample of valid names all pass without FAIL."""
        valid_names = [
            "my-skill",
            "data-processor",
            "skill-system-foundry",
            "a1b2c3",
            "test-v2",
            "ab",
        ]
        for name in valid_names:
            with self.subTest(name=name):
                errors, passes = validate_name(name, name)
                fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
                self.assertEqual(
                    fail_errors, [],
                    f"Expected no FAIL for valid name '{name}', "
                    f"got errors={errors}",
                )

    def test_numeric_name_passes(self) -> None:
        """A purely numeric name passes all checks."""
        name = "123"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_name_with_digits_and_hyphens_passes(self) -> None:
        """A name mixing digits and hyphens passes all checks."""
        name = "v2-data-tool-3"
        errors, passes = validate_name(name, name)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])


# ===================================================================
# Multiple Errors
# ===================================================================


class ValidateNameMultipleErrorsTests(unittest.TestCase):
    """Tests verifying that multiple violations produce multiple errors."""

    def test_uppercase_and_underscore_produce_two_fails(self) -> None:
        """A name with both uppercase and underscores produces multiple FAILs."""
        name = "Demo_Skill"
        errors, passes = validate_name(name, name)
        uppercase_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "uppercase" in e
        ]
        underscore_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "underscores" in e
        ]
        self.assertEqual(len(uppercase_fails), 1)
        self.assertEqual(len(underscore_fails), 1)

    def test_directory_mismatch_with_reserved_word(self) -> None:
        """A name with a reserved word produces WARN and directory mismatch produces FAIL."""
        name = "my-claude-tool"
        errors, passes = validate_name(name, "different-dir")
        reserved_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "reserved" in e
        ]
        mismatch_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "match" in e.lower()
        ]
        self.assertGreaterEqual(len(reserved_warns), 1)
        self.assertEqual(len(mismatch_fails), 1)

    def test_over_max_length_and_uppercase(self) -> None:
        """A name that is too long and has uppercase produces both FAILs."""
        name = "A" * (MAX_NAME_CHARS + 1)
        errors, passes = validate_name(name, name)
        length_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "exceeds" in e
        ]
        uppercase_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "uppercase" in e
        ]
        self.assertEqual(len(length_fails), 1)
        self.assertEqual(len(uppercase_fails), 1)


# ===================================================================
# parse_allowed_tools_tokens
# ===================================================================


class ParseAllowedToolsTokensTests(unittest.TestCase):
    """Normalisation of ``allowed-tools`` values to bare tokens."""

    def test_string_space_separated(self) -> None:
        self.assertEqual(
            parse_allowed_tools_tokens("Bash Read Write"),
            {"Bash", "Read", "Write"},
        )

    def test_yaml_list_form(self) -> None:
        self.assertEqual(
            parse_allowed_tools_tokens(["Bash", "Read", "Write"]),
            {"Bash", "Read", "Write"},
        )

    def test_yaml_list_with_argument_pattern(self) -> None:
        self.assertEqual(
            parse_allowed_tools_tokens(
                ["Bash(git add *)", "Read"],
            ),
            {"Bash", "Read"},
        )

    def test_strips_paren_arguments(self) -> None:
        self.assertEqual(
            parse_allowed_tools_tokens("Bash(git add *) Read"),
            {"Bash", "Read"},
        )

    def test_multiple_paren_args_in_string(self) -> None:
        # Spec example: ``Bash(git:*) Bash(jq:*) Read``.  Both
        # restricted Bash entries collapse to a single ``Bash`` token.
        self.assertEqual(
            parse_allowed_tools_tokens("Bash(git:*) Bash(jq:*) Read"),
            {"Bash", "Read"},
        )

    def test_empty_string_returns_empty_set(self) -> None:
        self.assertEqual(parse_allowed_tools_tokens(""), set())

    def test_whitespace_only_returns_empty_set(self) -> None:
        self.assertEqual(parse_allowed_tools_tokens("   \t  "), set())

    def test_none_returns_empty_set(self) -> None:
        self.assertEqual(parse_allowed_tools_tokens(None), set())

    def test_empty_list_returns_empty_set(self) -> None:
        self.assertEqual(parse_allowed_tools_tokens([]), set())

    def test_non_string_non_list_returns_empty_set(self) -> None:
        self.assertEqual(parse_allowed_tools_tokens(42), set())
        self.assertEqual(parse_allowed_tools_tokens({"Bash": 1}), set())

    def test_list_with_non_string_elements_skipped(self) -> None:
        self.assertEqual(
            parse_allowed_tools_tokens(["Bash", 42, None, "Read"]),
            {"Bash", "Read"},
        )

    def test_case_sensitive(self) -> None:
        # Lowercase ``bash`` is distinct from PascalCase ``Bash``.
        tokens = parse_allowed_tools_tokens("bash Bash")
        self.assertIn("bash", tokens)
        self.assertIn("Bash", tokens)


# ===================================================================
# validate_tool_coherence
# ===================================================================


def _bash_fence_body(tag: str = "bash") -> str:
    return f"# Skill\n\n```{tag}\necho hi\n```\n"


class ValidateToolCoherenceTests(unittest.TestCase):
    """End-to-end behaviour of the fence/script vs allowed-tools rule."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.skill_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- Fence check ---

    def test_bash_fence_with_bash_declared_silent(self) -> None:
        write_skill_md(
            self.skill_dir, allowed_tools="Bash", body=_bash_fence_body(),
        )
        errors, passes = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": "Bash"},
        )
        self.assertEqual(errors, [])
        self.assertTrue(any("'Bash' declared" in p for p in passes))

    def test_bash_fence_without_bash_declaration_fails(self) -> None:
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        errors, passes = validate_tool_coherence(
            self.skill_dir, {"description": "no bash declared"},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn("Bash", fail_errors[0])
        self.assertIn("SKILL.md", fail_errors[0])

    def test_no_fence_no_scripts_silent(self) -> None:
        write_skill_md(
            self.skill_dir, body="# Skill\n\nplain text body\n",
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "trivial"},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(fail_errors, [])
        self.assertEqual(warn_errors, [])

    def test_bash_arg_form_satisfies_rule(self) -> None:
        write_skill_md(
            self.skill_dir,
            allowed_tools="Bash(git add *)",
            body=_bash_fence_body(),
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir,
            {"allowed-tools": "Bash(git add *)"},
        )
        self.assertEqual(errors, [])

    def test_tilde_bash_fence_detected(self) -> None:
        body = "# Skill\n\n~~~bash\necho hi\n~~~\n"
        write_skill_md(self.skill_dir, body=body)
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "tilde fence"},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)

    def test_lowercase_bash_in_allowed_tools_does_not_satisfy(self) -> None:
        # Per harness semantics, lowercase ``bash`` does not grant the
        # PascalCase Bash tool.
        write_skill_md(
            self.skill_dir, allowed_tools="bash", body=_bash_fence_body(),
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": "bash"},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)

    def test_capability_fence_without_declaration_fails(self) -> None:
        write_skill_md(
            self.skill_dir, body="# Skill\n\nplain body\n",
        )
        write_capability_md(
            self.skill_dir, "demo", body=_bash_fence_body(),
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "capability has fence"},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)
        # Coherence FAIL paths are normalized to forward slashes for
        # cross-platform output stability.
        self.assertIn(
            "capabilities/demo/capability.md",
            fail_errors[0],
        )

    def test_nested_capability_fence_detected(self) -> None:
        # Capabilities nested below the conventional one-level depth
        # must still be scanned — matches the recursive glob used by
        # the prose-YAML check.
        write_skill_md(
            self.skill_dir, body="# Skill\n\nplain body\n",
        )
        nested = os.path.join(
            self.skill_dir, "capabilities", "group", "sub", "capability.md",
        )
        write_text(nested, _bash_fence_body())
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "nested capability"},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)
        # Coherence FAIL paths are normalized to forward slashes for
        # cross-platform output stability.
        self.assertIn(
            "capabilities/group/sub/capability.md",
            fail_errors[0],
        )

    def test_other_fence_languages_supported(self) -> None:
        for tag in ("sh", "shell", "zsh"):
            with tempfile.TemporaryDirectory() as fresh:
                write_skill_md(fresh, body=_bash_fence_body(tag))
                errors, _ = validate_tool_coherence(
                    fresh, {"description": "fence kind " + tag},
                )
                fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
                self.assertEqual(
                    len(fail_errors), 1,
                    f"fence ``{tag}`` should trigger FAIL: {errors!r}",
                )

    def test_allowed_tools_absent_with_fence_fails(self) -> None:
        # The painful failure mode: field missing entirely.
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        errors, _ = validate_tool_coherence(self.skill_dir, {})
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)

    def test_explicit_empty_string_suppresses_fence_fail(self) -> None:
        # ``allowed-tools: ""`` is a deliberate "no tools" declaration —
        # docs-only skills with example fences should not be forced to
        # add a fake ``Bash`` entry.
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        errors, passes = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": ""},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(fail_errors, [])
        self.assertEqual(warn_errors, [])
        self.assertTrue(any("explicit empty" in p for p in passes))

    def test_explicit_empty_list_suppresses_fence_fail(self) -> None:
        # The YAML-list form (``allowed-tools: []``) is treated the
        # same as the empty string — both parse to zero tokens.
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": []},
        )
        self.assertEqual(errors, [])

    def test_malformed_scalar_value_does_not_suppress_fence_fail(self) -> None:
        # A non-string / non-list scalar (e.g. integer) is malformed
        # frontmatter — it parses to zero tokens but is *not* a
        # deliberate "no tools" declaration and will not grant Bash at
        # runtime.  The coherence rule must still fire so the failure
        # mode #100 catches is not hidden behind invalid YAML.
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": 123},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn("Bash", fail_errors[0])

    def test_malformed_mapping_value_does_not_suppress_fence_fail(self) -> None:
        # A mapping value is malformed for the same reason — it does
        # not declare any tools, so coherence must still run.
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": {"Bash": True}},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)

    def test_paren_only_string_does_not_suppress_fence_fail(self) -> None:
        # ``(Bash)`` parses to zero tokens but ``validate_allowed_tools``
        # already flags it as broken input.  The coherence rule should
        # not silently treat it as an opt-out — the painful failure
        # mode (Bash fence + no real declaration) must still surface.
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": "(Bash)"},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)

    def test_non_string_list_items_do_not_suppress_fence_fail(self) -> None:
        # A non-empty list whose items are not strings parses to zero
        # tokens but is malformed — coherence must still run.
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": [1, 2, 3]},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)

    def test_explicit_empty_suppresses_scripts_warn(self) -> None:
        # The script-presence WARN is also gated on the explicit-empty
        # opt-out — pure-docs skills that ship a non-shell ``scripts/``
        # tree (Python helpers, asset generators) declare no tools and
        # should not be nagged.
        write_skill_md(self.skill_dir, body="# Skill\n")
        os.makedirs(os.path.join(self.skill_dir, "scripts"))
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": ""},
        )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])

    def test_yaml_list_form_of_allowed_tools(self) -> None:
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        errors, _ = validate_tool_coherence(
            self.skill_dir,
            {"allowed-tools": ["Bash", "Read"]},
        )
        self.assertEqual(errors, [])

    def test_fence_inside_frontmatter_not_counted(self) -> None:
        # A bash fence inside a frontmatter folded description (between
        # the ``---`` markers) must not trigger the rule.
        content = (
            "---\n"
            "name: demo-skill\n"
            "description: >\n"
            "  A description that mentions ```bash``` inline.\n"
            "---\n\n"
            "# Skill\n\nplain body\n"
        )
        write_text(os.path.join(self.skill_dir, "SKILL.md"), content)
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "..."},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    # --- Script-presence check ---

    def test_scripts_dir_without_bash_declaration_warns(self) -> None:
        write_skill_md(self.skill_dir, body="# Skill\n")
        write_text(
            os.path.join(self.skill_dir, "scripts", "noop.sh"),
            "#!/usr/bin/env bash\n",
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "scripts present"},
        )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("scripts/", warn_errors[0])
        self.assertIn("Bash", warn_errors[0])

    def test_empty_scripts_dir_still_warns(self) -> None:
        write_skill_md(self.skill_dir, body="# Skill\n")
        os.makedirs(os.path.join(self.skill_dir, "scripts"))
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "empty scripts dir"},
        )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)

    def test_scripts_dir_with_bash_declared_silent(self) -> None:
        write_skill_md(
            self.skill_dir, allowed_tools="Bash", body="# Skill\n",
        )
        write_text(
            os.path.join(self.skill_dir, "scripts", "noop.sh"),
            "#!/usr/bin/env bash\n",
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": "Bash"},
        )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])

    def test_scripts_absent_with_no_fence_silent(self) -> None:
        write_skill_md(self.skill_dir, body="# Skill\n")
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "neither signal"},
        )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])

    def test_both_signals_present_fence_fails_and_scripts_warns(self) -> None:
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        write_text(
            os.path.join(self.skill_dir, "scripts", "noop.sh"),
            "#!/usr/bin/env bash\n",
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "both signals"},
        )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(fail_errors), 1)
        self.assertEqual(len(warn_errors), 1)

    def test_allowed_tools_absent_with_scripts_warns(self) -> None:
        write_skill_md(self.skill_dir, body="# Skill\n")
        os.makedirs(os.path.join(self.skill_dir, "scripts"))
        errors, _ = validate_tool_coherence(self.skill_dir, {})
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)


# ===================================================================
# Description Trigger-Phrase Heuristic
# ===================================================================


class ValidateDescriptionTriggersTests(unittest.TestCase):
    """Tests for validate_description_triggers.

    The helper enforces the agentskills.io spec requirement that a
    description state when the skill activates.  Detection is a
    case-insensitive substring match against
    DESCRIPTION_TRIGGER_PHRASES; for non-empty descriptions, missing
    every phrase produces a single WARN.  Empty / whitespace-only
    inputs short-circuit silently — the spec-required non-empty FAIL
    is owned by the caller, not this helper.
    """

    def test_phrase_present_emits_no_warn(self) -> None:
        desc = "Validates skills against the spec. Triggers when a skill is created."
        errors, passes = validate_description_triggers(desc)
        self.assertEqual(errors, [])
        self.assertEqual(len(passes), 1)
        self.assertIn("triggers when", passes[0])

    def test_phrase_absent_emits_single_warn(self) -> None:
        desc = "Validates skills against the spec. Reports findings to stdout."
        errors, passes = validate_description_triggers(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("[spec]", warn_errors[0])
        self.assertIn("when the skill activates", warn_errors[0])
        self.assertEqual(passes, [])

    def test_match_is_case_insensitive(self) -> None:
        desc = "Validates skills against the spec. ACTIVATES WHEN a skill is touched."
        errors, _ = validate_description_triggers(desc)
        self.assertEqual(errors, [])

    def test_match_after_folded_multiline_input(self) -> None:
        # YAML folded block scalars collapse newlines to spaces before
        # the value reaches this helper.  Simulate the post-folding
        # shape: original text was split across lines, folding joins
        # the segments with a space, and the phrase lands on one line.
        desc = (
            "Validates skills against the spec. Activates "
            "when a skill is created or edited."
        )
        errors, _ = validate_description_triggers(desc)
        self.assertEqual(errors, [])

    def test_phrase_matches_within_longer_word(self) -> None:
        # "activates whenever" contains "activates when" as a
        # substring; the issue's acceptance examples rely on this.
        desc = (
            "Greets a single recipient with a friendly welcome message. "
            "Activates whenever the conversation asks to say hello."
        )
        errors, _ = validate_description_triggers(desc)
        self.assertEqual(errors, [])

    def test_empty_input_short_circuits(self) -> None:
        for value in ("", "   ", "\n\n  \t"):
            errors, passes = validate_description_triggers(value)
            self.assertEqual(errors, [])
            self.assertEqual(passes, [])

    def test_pass_message_names_matched_phrase(self) -> None:
        # Pass entry should reference one of the configured phrases so
        # --verbose output explains why the rule was satisfied.
        desc = "Audits skill systems. Use when the structure may have drifted."
        _, passes = validate_description_triggers(desc)
        self.assertEqual(len(passes), 1)
        matched = next(
            (p for p in DESCRIPTION_TRIGGER_PHRASES if p in passes[0]),
            None,
        )
        self.assertIsNotNone(matched)


# ===================================================================
# aggregate_capability_allowed_tools
# ===================================================================


class AggregateCapabilityAllowedToolsTests(unittest.TestCase):
    """Bottom-up aggregation: parent SKILL.md must be a superset of
    the union of capability-declared ``allowed-tools``."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.skill_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- No capabilities or all silent ---

    def test_no_capabilities_emits_pass_entry_no_fails(self) -> None:
        # SKILL.md body has a Bash fence so the parent-unused INFO is
        # suppressed for that observable token; ``Read`` has no
        # observation mechanism so it never produces an INFO either.
        # The pass entry confirms the rule ran with no capability
        # declarations.
        write_skill_md(
            self.skill_dir, allowed_tools="Bash Read",
            body=_bash_fence_body(),
        )
        errors, passes = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])
        self.assertTrue(any("aggregation:" in p for p in passes))

    def test_all_capabilities_silent_emits_pass_entry_no_fails(self) -> None:
        # Silent capabilities inherit the parent's set; one carries
        # the Bash fence so the observable parent-unused INFO is
        # suppressed.  ``Read`` is unobservable.
        write_skill_md(self.skill_dir, allowed_tools="Bash Read")
        write_capability_md(self.skill_dir, "alpha", body=_bash_fence_body())
        write_capability_md(self.skill_dir, "beta")
        errors, passes = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])
        self.assertTrue(any("no capabilities declare" in p for p in passes))

    def test_silent_only_router_with_unsignalled_observable_tool_emits_info(
        self,
    ) -> None:
        # Router declares Bash, no capability declares allowed-tools,
        # no body anywhere has a Bash fence, no scripts/ directory —
        # the parent is over-permissioned and the INFO must fire even
        # though no capability has opted into the field.  Without
        # this scan a router with only silent capabilities never
        # surfaces the over-permissioning until the first capability
        # adopts ``allowed-tools``.
        write_skill_md(self.skill_dir, allowed_tools="Bash Read")
        write_capability_md(self.skill_dir, "alpha")
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read"},
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(infos), 1)
        self.assertIn("Bash", infos[0])

    # --- Clean superset ---

    def test_parent_superset_clean(self) -> None:
        write_skill_md(self.skill_dir, allowed_tools="Bash Read Write")
        write_capability_md(self.skill_dir, "alpha", allowed_tools="Bash")
        write_capability_md(self.skill_dir, "beta", allowed_tools="Read")
        errors, passes = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read Write"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])
        self.assertTrue(
            any("'Bash' covered by SKILL.md" in p for p in passes)
        )

    def test_capability_subset_of_parent_clean(self) -> None:
        write_skill_md(self.skill_dir, allowed_tools="Bash Read Write")
        write_capability_md(self.skill_dir, "alpha", allowed_tools="Bash")
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read Write"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])

    # --- FAIL paths (parent missing tool) ---

    def test_capability_declares_tool_parent_missing_fails(self) -> None:
        write_skill_md(self.skill_dir, allowed_tools="Read")
        write_capability_md(
            self.skill_dir, "alpha", allowed_tools="Bash Read",
        )
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Read"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fails), 1)
        self.assertIn("Bash", fails[0])
        self.assertIn("capabilities/alpha/capability.md", fails[0])

    def test_parent_missing_field_entirely_fails(self) -> None:
        write_skill_md(self.skill_dir)
        write_capability_md(self.skill_dir, "alpha", allowed_tools="Bash")
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"description": "no allowed-tools field"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fails), 1)
        self.assertIn("Bash", fails[0])
        self.assertIn("capabilities/alpha/capability.md", fails[0])

    def test_explicit_empty_parent_with_capability_tools_fails(self) -> None:
        write_skill_md(self.skill_dir, allowed_tools='""')
        write_capability_md(self.skill_dir, "alpha", allowed_tools="Bash")
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": ""},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fails), 1)
        self.assertIn("Bash", fails[0])

    def test_per_capability_attribution_with_multiple(self) -> None:
        write_skill_md(self.skill_dir, allowed_tools="Read")
        write_capability_md(self.skill_dir, "alpha", allowed_tools="Bash")
        write_capability_md(self.skill_dir, "beta", allowed_tools="Bash")
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Read"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        # Two FAILs — one per capability — same tool name, different
        # attribution.
        self.assertEqual(len(fails), 2)
        self.assertTrue(any("alpha" in f for f in fails))
        self.assertTrue(any("beta" in f for f in fails))

    # --- INFO path (parent unused) ---

    def test_parent_unused_tool_emits_info(self) -> None:
        # Bash IS observable (fence-language entry defined) so a
        # parent-declared Bash that no capability declares — and that
        # has no Bash fence in SKILL.md and no scripts/ directory —
        # genuinely fires the parent-unused INFO.
        write_skill_md(self.skill_dir, allowed_tools="Bash Read")
        write_capability_md(self.skill_dir, "alpha", allowed_tools="Read")
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read"},
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(infos), 1)
        self.assertIn("Bash", infos[0])

    def test_parent_unused_no_signal_mechanism_suppressed(self) -> None:
        # ``Read`` has no fence-language entry and is not a
        # scripts_dir_indicator — the validator has no observable
        # basis to flag it.  Even when no capability declares it, the
        # INFO must NOT fire (would otherwise be a false positive
        # against any genuine SKILL.md-body use of the tool).
        write_skill_md(self.skill_dir, allowed_tools="Read Write")
        write_capability_md(self.skill_dir, "alpha", allowed_tools="Write")
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Read Write"},
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(infos, [])

    def test_parent_unused_tool_with_signal_silenced(self) -> None:
        # When SKILL.md body has a Bash fence, the INFO for "Bash
        # unused by any capability" should be suppressed because the
        # parent body itself signals the need.
        body = "# Skill\n\n```bash\necho hi\n```\n"
        write_skill_md(self.skill_dir, allowed_tools="Bash Read", body=body)
        write_capability_md(self.skill_dir, "alpha", allowed_tools="Read")
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read"},
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(infos, [])

    def test_parent_unused_tool_with_scripts_dir_silenced(self) -> None:
        write_skill_md(self.skill_dir, allowed_tools="Bash Read")
        write_capability_md(self.skill_dir, "alpha", allowed_tools="Read")
        os.makedirs(os.path.join(self.skill_dir, "scripts"))
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read"},
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(infos, [])

    # --- Set semantics: scoped argument forms ---

    def test_scoped_capability_token_satisfied_by_bare_parent(self) -> None:
        # ``Bash(git:*)`` in capability + ``Bash`` in parent should
        # satisfy the rule — set check is bare-token only.
        write_skill_md(self.skill_dir, allowed_tools="Bash")
        write_capability_md(
            self.skill_dir, "alpha", allowed_tools="Bash(git add *)",
        )
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])

    def test_nested_capability_contributes_to_union(self) -> None:
        # Nested capabilities are a separate FAIL in the audit, but
        # the aggregation rule must still see them so coherence and
        # aggregation cannot drift on which files contribute.
        write_skill_md(self.skill_dir, allowed_tools="Read")
        nested = os.path.join(
            self.skill_dir, "capabilities", "outer", "capabilities", "inner",
        )
        os.makedirs(nested)
        with open(
            os.path.join(nested, "capability.md"), "w", encoding="utf-8",
        ) as fh:
            fh.write("---\nallowed-tools: Bash\n---\n\n# Inner\n")
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Read"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fails), 1)
        self.assertIn("Bash", fails[0])
        self.assertIn("inner", fails[0])

    def test_silent_capability_fence_suppresses_parent_unused_info(self) -> None:
        # Parent declares Bash + Read; one capability declares Read,
        # another is silent on ``allowed-tools`` and contains a Bash
        # fence (it inherits the parent set).  The INFO "Bash unused
        # by any capability" must NOT fire — removing Bash from the
        # parent would break the silent capability's coherence.
        write_skill_md(self.skill_dir, allowed_tools="Bash Read")
        write_capability_md(
            self.skill_dir, "alpha", allowed_tools="Read",
        )
        write_capability_md(
            self.skill_dir, "beta", body=_bash_fence_body(),
        )
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read"},
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(infos, [])

    def test_declaring_capability_fence_suppresses_parent_unused_info(
        self,
    ) -> None:
        # Parent declares Bash + Read; the only capability declares
        # ``allowed-tools: Read`` but its body still contains a Bash
        # fence.  Coherence FAILs separately on the capability for
        # the missing Bash declaration; aggregation's parent-unused
        # INFO must not fire and contradict that FAIL with a
        # "Bash unused" message about the same token.
        write_skill_md(self.skill_dir, allowed_tools="Bash Read")
        write_capability_md(
            self.skill_dir, "alpha", allowed_tools="Read",
            body=_bash_fence_body(),
        )
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read"},
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(infos, [])

    def test_explicit_empty_capability_fence_does_not_suppress_info(
        self,
    ) -> None:
        # ``allowed-tools: ""`` opts the capability out of local fence
        # semantics; a Bash fence in such a capability is docs-only
        # and must not be treated as evidence the parent needs Bash.
        # The parent-unused INFO should fire so over-permissioning
        # surfaces.  A second declaring capability provides the
        # union so the rule actually runs (capabilities_with_field>0).
        write_skill_md(self.skill_dir, allowed_tools="Bash Read")
        write_capability_md(
            self.skill_dir, "alpha",
            allowed_tools='""',
            body=_bash_fence_body(),
        )
        write_capability_md(
            self.skill_dir, "beta", allowed_tools="Read",
        )
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Bash Read"},
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(infos), 1)
        self.assertIn("Bash", infos[0])

    def test_capability_parse_error_skipped(self) -> None:
        # Malformed capability frontmatter must not crash the rule.
        write_skill_md(self.skill_dir, allowed_tools="Read")
        cap_path = os.path.join(
            self.skill_dir, "capabilities", "broken", "capability.md",
        )
        os.makedirs(os.path.dirname(cap_path))
        with open(cap_path, "w", encoding="utf-8") as fh:
            fh.write("---\nallowed-tools: [unterminated\n")
        errors, passes = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Read"},
        )
        # No crash; the broken capability contributes nothing to the union.
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])

    def test_parse_artifact_token_does_not_pressure_parent(self) -> None:
        # ``allowed-tools: []`` parses as the literal string token
        # ``"[]"`` under the foundry's stdlib-only YAML parser.  That
        # token is a parse artifact, not a real tool, and pressuring
        # the author to copy it into the parent SKILL.md would make
        # the parent strictly worse.  Aggregation must skip
        # unrecognised tokens — ``validate_allowed_tools`` already
        # diagnoses them on the offending capability — and only
        # enforce parent-superset for catalog/MCP/harness-shaped
        # tokens.
        write_skill_md(self.skill_dir, allowed_tools="Read")
        write_capability_md(
            self.skill_dir, "alpha", allowed_tools="[]",
        )
        errors, _ = aggregate_capability_allowed_tools(
            self.skill_dir, {"allowed-tools": "Read"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])


# ===================================================================
# validate_capability_skill_only_fields
# ===================================================================


class ValidateCapabilitySkillOnlyFieldsTests(unittest.TestCase):
    """Capabilities declaring skill-wide frontmatter fields produce an
    INFO redirect."""

    def test_no_frontmatter_emits_pass(self) -> None:
        errors, passes = validate_capability_skill_only_fields(
            None, "capabilities/foo/capability.md",
        )
        self.assertEqual(errors, [])
        self.assertEqual(passes, [])

    def test_empty_frontmatter_emits_pass(self) -> None:
        errors, passes = validate_capability_skill_only_fields(
            {}, "capabilities/foo/capability.md",
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(passes), 1)
        self.assertIn("no skill-only fields", passes[0])

    def test_license_declared_emits_info(self) -> None:
        errors, _ = validate_capability_skill_only_fields(
            {"license": "MIT"}, "capabilities/foo/capability.md",
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(infos), 1)
        self.assertIn("'license'", infos[0])
        self.assertIn("capabilities/foo/capability.md", infos[0])

    def test_compatibility_declared_emits_info(self) -> None:
        errors, _ = validate_capability_skill_only_fields(
            {"compatibility": "Python 3.12"}, "capabilities/foo/capability.md",
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(infos), 1)
        self.assertIn("'compatibility'", infos[0])

    def test_metadata_author_declared_emits_info(self) -> None:
        errors, _ = validate_capability_skill_only_fields(
            {"metadata": {"author": "x"}}, "capabilities/foo/capability.md",
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(infos), 1)
        self.assertIn("'metadata.author'", infos[0])

    def test_metadata_version_declared_emits_info(self) -> None:
        errors, _ = validate_capability_skill_only_fields(
            {"metadata": {"version": "1.0.0"}},
            "capabilities/foo/capability.md",
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(infos), 1)
        self.assertIn("'metadata.version'", infos[0])

    def test_metadata_spec_declared_emits_info(self) -> None:
        errors, _ = validate_capability_skill_only_fields(
            {"metadata": {"spec": "agentskills.io"}},
            "capabilities/foo/capability.md",
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(infos), 1)
        self.assertIn("'metadata.spec'", infos[0])

    def test_multiple_fields_emit_one_info_per_field(self) -> None:
        errors, _ = validate_capability_skill_only_fields(
            {
                "license": "MIT",
                "metadata": {"author": "x", "version": "1.0.0"},
            },
            "capabilities/foo/capability.md",
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(infos), 3)

    def test_non_skill_only_fields_are_silent(self) -> None:
        # ``allowed-tools`` is the per-capability field — declaring it
        # must NOT trigger the redirect.
        errors, passes = validate_capability_skill_only_fields(
            {"allowed-tools": "Bash"},
            "capabilities/foo/capability.md",
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(passes), 1)

    def test_metadata_without_targeted_subfield_silent(self) -> None:
        errors, passes = validate_capability_skill_only_fields(
            {"metadata": {"experimental": True}},
            "capabilities/foo/capability.md",
        )
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(infos, [])

    def test_non_dict_metadata_does_not_crash(self) -> None:
        errors, _ = validate_capability_skill_only_fields(
            {"metadata": "scalar"},
            "capabilities/foo/capability.md",
        )
        # ``metadata`` is a scalar, no nested keys present; rule is silent.
        infos = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(infos, [])


# ===================================================================
# validate_tool_coherence — per-file effective set (issue #120)
# ===================================================================


class ValidateToolCoherencePerFileTests(unittest.TestCase):
    """Capability-level ``allowed-tools`` overrides the parent fallback
    inside ``validate_tool_coherence`` for fence findings local to the
    capability."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.skill_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_capability_declared_satisfies_local_fence(self) -> None:
        # Parent omits ``allowed-tools`` entirely; capability declares
        # ``Bash`` and contains a Bash fence.  Coherence rule should
        # not FAIL on the capability fence (the capability covers it).
        # Parent SKILL.md has no fence so no parent FAIL either —
        # aggregation, not coherence, owns the parent-superset finding.
        write_skill_md(self.skill_dir, body="# Skill\n\nplain body\n")
        write_capability_md(
            self.skill_dir, "alpha",
            allowed_tools="Bash",
            body=_bash_fence_body(),
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "parent has no allowed-tools"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])

    def test_capability_silent_falls_back_to_parent(self) -> None:
        # Capability silent on the field; parent declares Bash; fence
        # in capability is covered by the parent fallback.
        write_skill_md(
            self.skill_dir, allowed_tools="Bash",
            body="# Skill\n\nplain body\n",
        )
        write_capability_md(
            self.skill_dir, "alpha", body=_bash_fence_body(),
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"allowed-tools": "Bash"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])

    def test_capability_explicit_empty_suppresses_local_fence(self) -> None:
        # Capability declares ``allowed-tools: ""`` — opts itself out
        # of fence FAIL even when the parent declares nothing.
        write_skill_md(self.skill_dir, body="# Skill\n\nplain body\n")
        write_capability_md(
            self.skill_dir, "alpha",
            allowed_tools='""',
            body=_bash_fence_body(),
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "parent has no allowed-tools"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fails, [])

    def test_offending_paths_use_forward_slashes(self) -> None:
        # FAIL messages must cite capability paths with forward
        # slashes regardless of platform — Windows ``os.sep`` is the
        # backslash, which would otherwise leak into output and break
        # cross-platform-deterministic test assertions.
        write_skill_md(self.skill_dir, body="# Skill\n\nplain body\n")
        write_capability_md(
            self.skill_dir, "alpha", body=_bash_fence_body(),
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "no allowed-tools"},
        )
        fence_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "fence(s) found in" in e
        ]
        self.assertEqual(len(fence_fails), 1)
        self.assertIn("capabilities/alpha/capability.md", fence_fails[0])
        self.assertNotIn("capabilities\\alpha", fence_fails[0])

    def test_capability_declared_does_not_cover_parent_fence(self) -> None:
        # Capability declares Bash; SKILL.md has a Bash fence; parent
        # does not declare Bash → FAIL on the parent file (the
        # capability declaration does not propagate upward — that's
        # the aggregation rule's job).
        write_skill_md(self.skill_dir, body=_bash_fence_body())
        write_capability_md(
            self.skill_dir, "alpha", allowed_tools="Bash",
        )
        errors, _ = validate_tool_coherence(
            self.skill_dir, {"description": "parent omits"},
        )
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fails), 1)
        self.assertIn("SKILL.md", fails[0])


if __name__ == "__main__":
    unittest.main()
