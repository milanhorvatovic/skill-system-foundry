"""Tests for lib/validation.py.

Covers validate_name with comprehensive test cases for all validation rules:
empty name, length limits, lowercase enforcement, format pattern, consecutive
hyphens, underscores, spaces, directory name matching, reserved words, and
minimum length warnings.
"""

import os
import sys
import unittest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.validation import validate_name
from lib.constants import (
    LEVEL_FAIL,
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

    def test_short_name_returns_warn(self) -> None:
        """A name shorter than MIN_NAME_CHARS produces a WARN."""
        # Use a single character — valid format but too short
        name = "a"
        errors, passes = validate_name(name, name)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        short_warns = [e for e in warn_errors if "character" in e]
        self.assertEqual(len(short_warns), 1)
        self.assertIn(str(len(name)), short_warns[0])

    def test_name_at_min_length_no_warn(self) -> None:
        """A name at exactly MIN_NAME_CHARS does not produce a WARN."""
        name = "a" * MIN_NAME_CHARS
        errors, passes = validate_name(name, name)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        short_warns = [e for e in warn_errors if "character" in e]
        self.assertEqual(short_warns, [])

    def test_name_one_below_min_length_returns_warn(self) -> None:
        """A name one character below MIN_NAME_CHARS produces a WARN."""
        name = "a" * (MIN_NAME_CHARS - 1)
        errors, passes = validate_name(name, name)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        short_warns = [e for e in warn_errors if "character" in e]
        self.assertEqual(len(short_warns), 1)


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
    """Tests for the reserved words rule (Anthropic-specific)."""

    def test_each_reserved_word_returns_fail(self) -> None:
        """Each reserved word in the name produces a FAIL."""
        for reserved in RESERVED_NAMES:
            name = f"my-{reserved}-skill"
            with self.subTest(reserved=reserved):
                errors, passes = validate_name(name, name)
                fail_errors = [
                    e for e in errors
                    if e.startswith(LEVEL_FAIL) and "reserved" in e
                ]
                self.assertGreaterEqual(
                    len(fail_errors), 1,
                    f"Expected reserved word FAIL for '{reserved}', "
                    f"got errors={errors}",
                )
                self.assertIn(reserved, fail_errors[0])

    def test_reserved_word_as_exact_name_returns_fail(self) -> None:
        """A name that is exactly a reserved word produces a FAIL."""
        for reserved in RESERVED_NAMES:
            with self.subTest(reserved=reserved):
                errors, passes = validate_name(reserved, reserved)
                fail_errors = [
                    e for e in errors
                    if e.startswith(LEVEL_FAIL) and "reserved" in e
                ]
                self.assertGreaterEqual(len(fail_errors), 1)

    def test_reserved_word_as_substring_returns_fail(self) -> None:
        """A reserved word appearing as a substring produces a FAIL."""
        for reserved in RESERVED_NAMES:
            # Embed the reserved word without hyphens
            name = f"my{reserved}tool"
            with self.subTest(reserved=reserved, name=name):
                errors, passes = validate_name(name, name)
                fail_errors = [
                    e for e in errors
                    if e.startswith(LEVEL_FAIL) and "reserved" in e
                ]
                self.assertGreaterEqual(
                    len(fail_errors), 1,
                    f"Expected reserved word FAIL for substring '{reserved}' "
                    f"in '{name}', got errors={errors}",
                )

    def test_no_reserved_words_no_error(self) -> None:
        """A name without reserved words does not produce a reserved FAIL."""
        name = "demo-skill"
        errors, passes = validate_name(name, name)
        fail_errors = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "reserved" in e
        ]
        self.assertEqual(fail_errors, [])


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
        """A name with a reserved word and directory mismatch produces both FAILs."""
        name = "my-claude-tool"
        errors, passes = validate_name(name, "different-dir")
        reserved_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "reserved" in e
        ]
        mismatch_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL) and "match" in e.lower()
        ]
        self.assertGreaterEqual(len(reserved_fails), 1)
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


if __name__ == "__main__":
    unittest.main()
