"""Tests for lib/yaml_parser.py.

Covers the lightweight YAML-subset parser with comprehensive test cases for
all public and internal functions: parse_yaml_subset, _strip_inline_comment,
_unquote, _parse_structure, _parse_mapping, and _parse_list.  Includes edge
cases for empty input, comment-only input, inline comment stripping, quoted
string preservation, folded/literal block scalars, chomp indicators, nested
mappings, list items, and an integration test against the real
configuration.yaml file.
"""

import os
import sys
import unittest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.yaml_parser import (
    parse_yaml_subset,
    _strip_inline_comment,
    _unquote,
    _parse_structure,
    _parse_mapping,
    _parse_list,
)


# ===================================================================
# parse_yaml_subset — Empty / Whitespace / Comment-Only Input
# ===================================================================


class ParseYamlSubsetEmptyInputTests(unittest.TestCase):
    """Tests for parse_yaml_subset when input is empty or trivial."""

    def test_none_returns_empty_dict(self) -> None:
        """None input returns an empty dict."""
        result = parse_yaml_subset(None)
        self.assertEqual(result, {})

    def test_empty_string_returns_empty_dict(self) -> None:
        """An empty string returns an empty dict."""
        result = parse_yaml_subset("")
        self.assertEqual(result, {})

    def test_whitespace_only_returns_empty_dict(self) -> None:
        """Whitespace-only input returns an empty dict."""
        cases = [" ", "  ", "\t", "\n", "\n\n\n", "  \n  \t  \n"]
        for text in cases:
            with self.subTest(text=repr(text)):
                result = parse_yaml_subset(text)
                self.assertEqual(result, {})

    def test_comment_only_returns_empty_dict(self) -> None:
        """Comment-only input returns an empty dict."""
        cases = [
            "# just a comment",
            "# line 1\n# line 2\n# line 3",
            "  # indented comment",
        ]
        for text in cases:
            with self.subTest(text=text):
                result = parse_yaml_subset(text)
                self.assertEqual(result, {})

    def test_blank_lines_and_comments_returns_empty_dict(self) -> None:
        """Mixed blank lines and comments return an empty dict."""
        text = "\n\n# comment\n\n# another\n\n"
        result = parse_yaml_subset(text)
        self.assertEqual(result, {})


# ===================================================================
# parse_yaml_subset — Simple Key-Value Pairs
# ===================================================================


class ParseYamlSubsetKeyValueTests(unittest.TestCase):
    """Tests for parse_yaml_subset with simple key-value pairs."""

    def test_single_key_value(self) -> None:
        """A single key-value pair is parsed correctly."""
        result = parse_yaml_subset("name: my-skill")
        self.assertEqual(result, {"name": "my-skill"})

    def test_multiple_key_value_pairs(self) -> None:
        """Multiple key-value pairs are parsed correctly."""
        text = "name: my-skill\nversion: 1.0\nauthor: test"
        result = parse_yaml_subset(text)
        self.assertEqual(result, {
            "name": "my-skill",
            "version": "1.0",
            "author": "test",
        })

    def test_inline_comment_stripping(self) -> None:
        """Inline comments after values are stripped."""
        text = "name: my-skill # this is a comment"
        result = parse_yaml_subset(text)
        self.assertEqual(result, {"name": "my-skill"})

    def test_value_with_colon(self) -> None:
        """Values containing colons are preserved (only first colon splits)."""
        text = "pattern: ^[a-z]:[0-9]$"
        result = parse_yaml_subset(text)
        self.assertEqual(result, {"pattern": "^[a-z]:[0-9]$"})

    def test_blank_lines_between_pairs_ignored(self) -> None:
        """Blank lines between key-value pairs are ignored."""
        text = "name: alpha\n\nversion: 2"
        result = parse_yaml_subset(text)
        self.assertEqual(result, {"name": "alpha", "version": "2"})

    def test_comments_between_pairs_ignored(self) -> None:
        """Comment lines between key-value pairs are ignored."""
        text = "name: alpha\n# separator\nversion: 2"
        result = parse_yaml_subset(text)
        self.assertEqual(result, {"name": "alpha", "version": "2"})


# ===================================================================
# parse_yaml_subset — Quoted String Preservation
# ===================================================================


class ParseYamlSubsetQuotedStringTests(unittest.TestCase):
    """Tests for parse_yaml_subset with quoted string values."""

    def test_double_quoted_value(self) -> None:
        """Double-quoted values have quotes stripped."""
        result = parse_yaml_subset('name: "my-skill"')
        self.assertEqual(result, {"name": "my-skill"})

    def test_single_quoted_value(self) -> None:
        """Single-quoted values have quotes stripped."""
        result = parse_yaml_subset("name: 'my-skill'")
        self.assertEqual(result, {"name": "my-skill"})

    def test_quoted_value_with_special_chars(self) -> None:
        """Quoted values preserve special characters like # and :."""
        result = parse_yaml_subset('pattern: "*.pyc"')
        self.assertEqual(result, {"pattern": "*.pyc"})

    def test_quoted_value_with_hash_inside(self) -> None:
        """Hash inside quotes is not treated as a comment."""
        result = parse_yaml_subset('tag: "color #red"')
        self.assertEqual(result, {"tag": "color #red"})

    def test_single_quoted_value_with_hash_inside(self) -> None:
        """Hash inside single quotes is not treated as a comment."""
        result = parse_yaml_subset("tag: 'color #red'")
        self.assertEqual(result, {"tag": "color #red"})


# ===================================================================
# _strip_inline_comment
# ===================================================================


class StripInlineCommentTests(unittest.TestCase):
    """Tests for _strip_inline_comment removing trailing comments."""

    def test_no_comment(self) -> None:
        """Text without a comment passes through unchanged."""
        self.assertEqual(_strip_inline_comment("key: value"), "key: value")

    def test_trailing_comment_stripped(self) -> None:
        """A trailing comment after a space is stripped."""
        self.assertEqual(_strip_inline_comment("key: value # comment"), "key: value")

    def test_hash_without_leading_space_preserved(self) -> None:
        """A hash without a preceding space is not treated as a comment."""
        self.assertEqual(_strip_inline_comment("color:#red"), "color:#red")

    def test_hash_at_start_preserved(self) -> None:
        """A hash at position 0 is not stripped (requires i > 0)."""
        self.assertEqual(_strip_inline_comment("# full comment"), "# full comment")

    def test_hash_inside_double_quotes_preserved(self) -> None:
        """A hash inside double quotes is not treated as a comment."""
        text = '"value # not a comment"'
        self.assertEqual(_strip_inline_comment(text), text)

    def test_hash_inside_single_quotes_preserved(self) -> None:
        """A hash inside single quotes is not treated as a comment."""
        text = "'value # not a comment'"
        self.assertEqual(_strip_inline_comment(text), text)

    def test_hash_after_quoted_value_stripped(self) -> None:
        """A comment after a closing quote is stripped."""
        text = '"value" # comment'
        self.assertEqual(_strip_inline_comment(text), '"value"')

    def test_hash_after_single_quoted_value_stripped(self) -> None:
        """A comment after a single-quoted value is stripped."""
        text = "'value' # comment"
        self.assertEqual(_strip_inline_comment(text), "'value'")

    def test_multiple_hashes_first_comment_wins(self) -> None:
        """Only the first valid comment marker triggers stripping."""
        text = "key: val # comment # more"
        self.assertEqual(_strip_inline_comment(text), "key: val")

    def test_no_false_positive_hash_in_quoted_string(self) -> None:
        """Hash inside quotes followed by a real comment is handled."""
        text = '"has # inside" # real comment'
        self.assertEqual(_strip_inline_comment(text), '"has # inside"')

    def test_empty_string(self) -> None:
        """An empty string passes through unchanged."""
        self.assertEqual(_strip_inline_comment(""), "")

    def test_only_spaces_before_hash(self) -> None:
        """Spaces followed by a hash at position > 0 are stripped."""
        text = "value # trailing"
        self.assertEqual(_strip_inline_comment(text), "value")

    def test_unclosed_double_quote_preserves_hash(self) -> None:
        """An unclosed double quote treats the rest as quoted; hash is preserved."""
        text = '"unclosed string # not a comment'
        self.assertEqual(_strip_inline_comment(text), text)

    def test_unclosed_single_quote_preserves_hash(self) -> None:
        """An unclosed single quote treats the rest as quoted; hash is preserved."""
        text = "'unclosed string # not a comment"
        self.assertEqual(_strip_inline_comment(text), text)


# ===================================================================
# _unquote
# ===================================================================


class UnquoteTests(unittest.TestCase):
    """Tests for _unquote stripping surrounding quotes."""

    def test_double_quoted_string(self) -> None:
        """Double-quoted strings have quotes removed."""
        self.assertEqual(_unquote('"hello"'), "hello")

    def test_single_quoted_string(self) -> None:
        """Single-quoted strings have quotes removed."""
        self.assertEqual(_unquote("'hello'"), "hello")

    def test_unquoted_string_passes_through(self) -> None:
        """Strings without quotes pass through unchanged."""
        self.assertEqual(_unquote("hello"), "hello")

    def test_single_character_quoted_string(self) -> None:
        """Single-character quoted strings are unquoted correctly."""
        self.assertEqual(_unquote('"x"'), "x")
        self.assertEqual(_unquote("'y'"), "y")

    def test_empty_quoted_string(self) -> None:
        """Empty quoted strings return an empty string."""
        self.assertEqual(_unquote('""'), "")
        self.assertEqual(_unquote("''"), "")

    def test_mismatched_quotes_pass_through(self) -> None:
        """Mismatched quotes are not stripped."""
        self.assertEqual(_unquote("\"hello'"), "\"hello'")
        self.assertEqual(_unquote("'hello\""), "'hello\"")

    def test_single_character_unquoted(self) -> None:
        """A single unquoted character passes through unchanged."""
        self.assertEqual(_unquote("x"), "x")

    def test_single_quote_character(self) -> None:
        """A single quote character passes through unchanged."""
        self.assertEqual(_unquote('"'), '"')
        self.assertEqual(_unquote("'"), "'")

    def test_whitespace_stripped_before_unquoting(self) -> None:
        """Leading and trailing whitespace is stripped before unquoting."""
        self.assertEqual(_unquote('  "hello"  '), "hello")
        self.assertEqual(_unquote("  'world'  "), "world")

    def test_value_with_internal_quotes(self) -> None:
        """Values with internal quotes but different outer quotes pass through."""
        self.assertEqual(_unquote("it's"), "it's")
        self.assertEqual(_unquote('say "hi"'), 'say "hi"')

    def test_numeric_string(self) -> None:
        """Numeric strings pass through unchanged."""
        self.assertEqual(_unquote("42"), "42")

    def test_quoted_numeric_string(self) -> None:
        """Quoted numeric strings have quotes removed."""
        self.assertEqual(_unquote('"42"'), "42")


# ===================================================================
# _parse_structure — Dispatch
# ===================================================================


class ParseStructureTests(unittest.TestCase):
    """Tests for _parse_structure dispatching to mapping or list parser."""

    def test_dispatches_to_mapping(self) -> None:
        """Lines starting with a key dispatch to _parse_mapping."""
        lines = [(0, "key: value")]
        result, end = _parse_structure(lines, 0, 0)
        self.assertEqual(result, {"key": "value"})
        self.assertEqual(end, 1)

    def test_dispatches_to_list(self) -> None:
        """Lines starting with '- ' dispatch to _parse_list."""
        lines = [(0, "- item1"), (0, "- item2")]
        result, end = _parse_structure(lines, 0, 0)
        self.assertEqual(result, ["item1", "item2"])
        self.assertEqual(end, 2)

    def test_start_beyond_lines_returns_empty_dict(self) -> None:
        """Start index beyond available lines returns an empty dict."""
        lines = [(0, "key: value")]
        result, end = _parse_structure(lines, 5, 0)
        self.assertEqual(result, {})
        self.assertEqual(end, 5)

    def test_empty_lines_returns_empty_dict(self) -> None:
        """An empty lines list returns an empty dict."""
        result, end = _parse_structure([], 0, 0)
        self.assertEqual(result, {})
        self.assertEqual(end, 0)


# ===================================================================
# _parse_mapping — Basic Key-Value
# ===================================================================


class ParseMappingBasicTests(unittest.TestCase):
    """Tests for _parse_mapping with basic key-value pairs."""

    def test_single_pair(self) -> None:
        """A single key-value pair is parsed correctly."""
        lines = [(0, "name: test")]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"name": "test"})
        self.assertEqual(end, 1)

    def test_multiple_pairs(self) -> None:
        """Multiple key-value pairs at the same indent are parsed."""
        lines = [(0, "a: 1"), (0, "b: 2"), (0, "c: 3")]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"a": "1", "b": "2", "c": "3"})
        self.assertEqual(end, 3)

    def test_stops_at_lower_indent(self) -> None:
        """Parsing stops when indent drops below base_indent."""
        lines = [(2, "inner: val"), (0, "outer: val")]
        result, end = _parse_mapping(lines, 0, 2)
        self.assertEqual(result, {"inner": "val"})
        self.assertEqual(end, 1)

    def test_stops_at_higher_indent(self) -> None:
        """Parsing stops when indent exceeds base_indent (unexpected)."""
        lines = [(0, "a: 1"), (4, "b: 2")]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"a": "1"})
        self.assertEqual(end, 1)

    def test_line_without_colon_skipped(self) -> None:
        """Lines without a colon are skipped."""
        lines = [(0, "no-colon-here"), (0, "key: value")]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"key": "value"})
        self.assertEqual(end, 2)

    def test_empty_value_after_colon(self) -> None:
        """A key with no value and no nested content returns empty string."""
        lines = [(0, "key:")]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"key": ""})
        self.assertEqual(end, 1)


# ===================================================================
# _parse_mapping — Folded Block Scalars
# ===================================================================


class ParseMappingFoldedBlockTests(unittest.TestCase):
    """Tests for _parse_mapping with folded block scalars (>)."""

    def test_folded_block_joins_with_spaces(self) -> None:
        """Folded block scalar (>) joins continuation lines with spaces."""
        lines = [
            (0, "description: >"),
            (2, "This is a long"),
            (2, "description text."),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(
            result, {"description": "This is a long description text."}
        )
        self.assertEqual(end, 3)

    def test_folded_block_with_chomp(self) -> None:
        """Folded block scalar with chomp indicator (>-) joins with spaces."""
        lines = [
            (0, "description: >-"),
            (2, "Line one"),
            (2, "line two."),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"description": "Line one line two."})
        self.assertEqual(end, 3)

    def test_folded_block_multiple_continuation_lines(self) -> None:
        """Folded block scalar collects all indented continuation lines."""
        lines = [
            (0, "text: >"),
            (2, "alpha"),
            (2, "beta"),
            (2, "gamma"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"text": "alpha beta gamma"})
        self.assertEqual(end, 4)

    def test_folded_block_stops_at_same_indent(self) -> None:
        """Folded block scalar stops collecting at same or lower indent."""
        lines = [
            (0, "desc: >"),
            (2, "folded line"),
            (0, "next: value"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"desc": "folded line", "next": "value"})
        self.assertEqual(end, 3)

    def test_folded_block_no_continuation_lines(self) -> None:
        """Folded block scalar with no continuation lines yields empty string."""
        lines = [
            (0, "desc: >"),
            (0, "next: value"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"desc": "", "next": "value"})
        self.assertEqual(end, 2)

    def test_literal_block_no_continuation_lines(self) -> None:
        """Literal block scalar with no continuation lines yields empty string."""
        lines = [
            (0, "script: |"),
            (0, "next: value"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"script": "", "next": "value"})
        self.assertEqual(end, 2)

    def test_folded_block_chomp_no_continuation_lines(self) -> None:
        """Folded block with chomp (>-) and no continuation yields empty string."""
        lines = [
            (0, "desc: >-"),
            (0, "next: value"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"desc": "", "next": "value"})
        self.assertEqual(end, 2)

    def test_literal_block_chomp_no_continuation_lines(self) -> None:
        """Literal block with chomp (|-) and no continuation yields empty string."""
        lines = [
            (0, "script: |-"),
            (0, "next: value"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"script": "", "next": "value"})
        self.assertEqual(end, 2)

    def test_block_scalar_at_end_of_input(self) -> None:
        """Block scalar indicator as the last line with no lines following."""
        lines = [
            (0, "desc: >"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"desc": ""})
        self.assertEqual(end, 1)


# ===================================================================
# _parse_mapping — Literal Block Scalars
# ===================================================================


class ParseMappingLiteralBlockTests(unittest.TestCase):
    """Tests for _parse_mapping with literal block scalars (|)."""

    def test_literal_block_preserves_newlines(self) -> None:
        """Literal block scalar (|) preserves newlines between lines."""
        lines = [
            (0, "script: |"),
            (2, "echo hello"),
            (2, "echo world"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"script": "echo hello\necho world"})
        self.assertEqual(end, 3)

    def test_literal_block_with_chomp(self) -> None:
        """Literal block scalar with chomp indicator (|-) preserves newlines."""
        lines = [
            (0, "script: |-"),
            (2, "line one"),
            (2, "line two"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"script": "line one\nline two"})
        self.assertEqual(end, 3)

    def test_literal_block_single_line(self) -> None:
        """Literal block scalar with a single continuation line."""
        lines = [
            (0, "cmd: |"),
            (2, "single line"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"cmd": "single line"})
        self.assertEqual(end, 2)

    def test_literal_block_stops_at_same_indent(self) -> None:
        """Literal block scalar stops collecting at same or lower indent."""
        lines = [
            (0, "script: |"),
            (2, "echo hello"),
            (0, "next: value"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"script": "echo hello", "next": "value"})
        self.assertEqual(end, 3)


# ===================================================================
# _parse_mapping — Nested Mappings
# ===================================================================


class ParseMappingNestedTests(unittest.TestCase):
    """Tests for _parse_mapping with nested mappings."""

    def test_single_level_nesting(self) -> None:
        """A key with no value followed by indented keys creates nesting."""
        lines = [
            (0, "parent:"),
            (2, "child: value"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"parent": {"child": "value"}})
        self.assertEqual(end, 2)

    def test_two_level_nesting(self) -> None:
        """Two levels of nesting are parsed correctly."""
        lines = [
            (0, "level1:"),
            (2, "level2:"),
            (4, "level3: deep"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(
            result, {"level1": {"level2": {"level3": "deep"}}}
        )
        self.assertEqual(end, 3)

    def test_nested_with_sibling(self) -> None:
        """Nested mapping followed by a sibling key at the same indent."""
        lines = [
            (0, "parent:"),
            (2, "child: value"),
            (0, "sibling: other"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(
            result, {"parent": {"child": "value"}, "sibling": "other"}
        )
        self.assertEqual(end, 3)

    def test_multiple_nested_children(self) -> None:
        """A parent with multiple nested children."""
        lines = [
            (0, "parent:"),
            (2, "a: 1"),
            (2, "b: 2"),
            (2, "c: 3"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(
            result, {"parent": {"a": "1", "b": "2", "c": "3"}}
        )
        self.assertEqual(end, 4)

    def test_empty_value_no_nested_content(self) -> None:
        """A key with empty value and no indented content returns empty string."""
        lines = [
            (0, "empty:"),
            (0, "next: val"),
        ]
        result, end = _parse_mapping(lines, 0, 0)
        self.assertEqual(result, {"empty": "", "next": "val"})
        self.assertEqual(end, 2)


# ===================================================================
# _parse_list — Simple Scalar Items
# ===================================================================


class ParseListSimpleTests(unittest.TestCase):
    """Tests for _parse_list with simple scalar list items."""

    def test_single_item(self) -> None:
        """A single list item is parsed correctly."""
        lines = [(0, "- item1")]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(result, ["item1"])
        self.assertEqual(end, 1)

    def test_multiple_items(self) -> None:
        """Multiple list items are parsed correctly."""
        lines = [(0, "- alpha"), (0, "- beta"), (0, "- gamma")]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(result, ["alpha", "beta", "gamma"])
        self.assertEqual(end, 3)

    def test_quoted_items(self) -> None:
        """Quoted list items have quotes stripped."""
        lines = [(0, '- "quoted"'), (0, "- 'single'")]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(result, ["quoted", "single"])
        self.assertEqual(end, 2)

    def test_stops_at_different_indent(self) -> None:
        """List parsing stops when indent changes."""
        lines = [(2, "- inner"), (0, "- outer")]
        result, end = _parse_list(lines, 0, 2)
        self.assertEqual(result, ["inner"])
        self.assertEqual(end, 1)

    def test_stops_at_non_list_line(self) -> None:
        """List parsing stops at a line that does not start with '- '."""
        lines = [(0, "- item"), (0, "key: value")]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(result, ["item"])
        self.assertEqual(end, 1)


# ===================================================================
# _parse_list — Dictionary Items Inside Lists
# ===================================================================


class ParseListDictItemTests(unittest.TestCase):
    """Tests for _parse_list with dictionary items inside lists."""

    def test_single_dict_item(self) -> None:
        """A list item with key: value creates a dict entry."""
        lines = [(0, "- name: alpha")]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(result, [{"name": "alpha"}])
        self.assertEqual(end, 1)

    def test_multiple_dict_items(self) -> None:
        """Multiple list items with key: value create dict entries."""
        lines = [(0, "- name: alpha"), (0, "- name: beta")]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(result, [{"name": "alpha"}, {"name": "beta"}])
        self.assertEqual(end, 2)

    def test_dict_item_with_continuation_keys(self) -> None:
        """A dict item with continuation keys at higher indent."""
        lines = [
            (0, "- name: alpha"),
            (2, "version: 1.0"),
            (2, "author: test"),
        ]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(
            result,
            [{"name": "alpha", "version": "1.0", "author": "test"}],
        )
        self.assertEqual(end, 3)

    def test_multiple_dict_items_with_continuations(self) -> None:
        """Multiple dict items each with continuation keys."""
        lines = [
            (0, "- name: alpha"),
            (2, "version: 1"),
            (0, "- name: beta"),
            (2, "version: 2"),
        ]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(
            result,
            [
                {"name": "alpha", "version": "1"},
                {"name": "beta", "version": "2"},
            ],
        )
        self.assertEqual(end, 4)

    def test_dict_item_with_empty_first_value(self) -> None:
        """A dict item where the first key has no inline value."""
        lines = [
            (0, "- parent:"),
            (4, "child: nested"),
        ]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(result, [{"parent": {"child": "nested"}}])
        self.assertEqual(end, 2)

    def test_dict_item_empty_value_no_nested(self) -> None:
        """A dict item with empty value and no nested content."""
        lines = [
            (0, "- key:"),
            (0, "- other: val"),
        ]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(result, [{"key": ""}, {"other": "val"}])
        self.assertEqual(end, 2)


# ===================================================================
# _parse_list — Nested Structures in List Items
# ===================================================================


class ParseListNestedTests(unittest.TestCase):
    """Tests for _parse_list with nested structures inside list items."""

    def test_continuation_key_with_folded_block(self) -> None:
        """A continuation key with a folded block scalar."""
        lines = [
            (0, "- name: alpha"),
            (2, "description: >"),
            (4, "A long"),
            (4, "description."),
        ]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(
            result,
            [{"name": "alpha", "description": "A long description."}],
        )
        self.assertEqual(end, 4)

    def test_continuation_key_with_literal_block(self) -> None:
        """A continuation key with a literal block scalar."""
        lines = [
            (0, "- name: alpha"),
            (2, "script: |"),
            (4, "echo hello"),
            (4, "echo world"),
        ]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(
            result,
            [{"name": "alpha", "script": "echo hello\necho world"}],
        )
        self.assertEqual(end, 4)

    def test_continuation_key_with_nested_mapping(self) -> None:
        """A continuation key with a nested mapping."""
        lines = [
            (0, "- name: alpha"),
            (2, "config:"),
            (4, "timeout: 30"),
            (4, "retries: 3"),
        ]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(
            result,
            [{"name": "alpha", "config": {"timeout": "30", "retries": "3"}}],
        )
        self.assertEqual(end, 4)

    def test_continuation_key_empty_value_no_nested(self) -> None:
        """A continuation key with empty value and no nested content."""
        lines = [
            (0, "- name: alpha"),
            (2, "extra:"),
        ]
        result, end = _parse_list(lines, 0, 0)
        self.assertEqual(result, [{"name": "alpha", "extra": ""}])
        self.assertEqual(end, 2)

    def test_continuation_key_with_chomp_indicators(self) -> None:
        """Continuation keys with chomp indicators (>- and |-)."""
        cases = [
            ("description: >-", True),
            ("description: |-", False),
        ]
        for indicator, is_folded in cases:
            with self.subTest(indicator=indicator):
                lines = [
                    (0, "- name: test"),
                    (2, indicator),
                    (4, "line one"),
                    (4, "line two"),
                ]
                result, end = _parse_list(lines, 0, 0)
                if is_folded:
                    expected_val = "line one line two"
                else:
                    expected_val = "line one\nline two"
                self.assertEqual(
                    result,
                    [{"name": "test", "description": expected_val}],
                )

    def test_continuation_line_without_colon_breaks(self) -> None:
        """A continuation line without a colon stops continuation collection."""
        lines = [
            (0, "- name: alpha"),
            (2, "no-colon-here"),
        ]
        result, end = _parse_list(lines, 0, 0)
        # The continuation loop breaks when sub_colon < 0, so only
        # the first key from the '- ' line is captured.
        self.assertEqual(result, [{"name": "alpha"}])
        # The line without a colon is left unconsumed.
        self.assertEqual(end, 1)


# ===================================================================
# parse_yaml_subset — Full Document Parsing
# ===================================================================


class ParseYamlSubsetFullDocumentTests(unittest.TestCase):
    """Tests for parse_yaml_subset with complete YAML documents."""

    def test_nested_mapping_with_list(self) -> None:
        """A nested mapping containing a list is parsed correctly."""
        text = (
            "skill:\n"
            "  name:\n"
            "    max_length: 64\n"
            "  reserved_words:\n"
            "    - anthropic\n"
            "    - claude\n"
        )
        result = parse_yaml_subset(text)
        self.assertIn("skill", result)
        self.assertIn("name", result["skill"])
        self.assertEqual(result["skill"]["name"]["max_length"], "64")
        self.assertIn("reserved_words", result["skill"])
        self.assertEqual(
            result["skill"]["reserved_words"], ["anthropic", "claude"]
        )

    def test_multiple_top_level_sections(self) -> None:
        """Multiple top-level sections are parsed correctly."""
        text = (
            "section_a:\n"
            "  key1: val1\n"
            "section_b:\n"
            "  key2: val2\n"
        )
        result = parse_yaml_subset(text)
        self.assertEqual(
            result,
            {
                "section_a": {"key1": "val1"},
                "section_b": {"key2": "val2"},
            },
        )

    def test_top_level_list_returns_empty_dict(self) -> None:
        """A top-level list is not a valid mapping and returns empty dict."""
        text = "- item1\n- item2\n"
        result = parse_yaml_subset(text)
        # parse_yaml_subset returns {} if result is not a dict
        self.assertEqual(result, {})

    def test_document_with_comments_and_blanks(self) -> None:
        """Comments and blank lines are ignored in a full document."""
        text = (
            "# Header comment\n"
            "\n"
            "name: test\n"
            "\n"
            "# Section\n"
            "version: 1\n"
        )
        result = parse_yaml_subset(text)
        self.assertEqual(result, {"name": "test", "version": "1"})

    def test_deeply_nested_structure(self) -> None:
        """Three levels of nesting are parsed correctly."""
        text = (
            "level1:\n"
            "  level2:\n"
            "    level3:\n"
            "      key: deep-value\n"
        )
        result = parse_yaml_subset(text)
        self.assertEqual(
            result,
            {"level1": {"level2": {"level3": {"key": "deep-value"}}}},
        )


# ===================================================================
# Integration — Real configuration.yaml
# ===================================================================


class ConfigurationYamlIntegrationTests(unittest.TestCase):
    """Integration test parsing the real configuration.yaml file."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load and parse configuration.yaml once for all tests."""
        config_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "skill-system-foundry",
            "scripts",
            "lib",
            "configuration.yaml",
        )
        config_path = os.path.abspath(config_path)
        with open(config_path, encoding="utf-8") as fh:
            cls.config = parse_yaml_subset(fh.read())

    def test_config_is_dict(self) -> None:
        """The parsed configuration is a non-empty dict."""
        self.assertIsInstance(self.config, dict)
        self.assertGreater(len(self.config), 0)

    def test_skill_section_exists(self) -> None:
        """The top-level 'skill' section exists."""
        self.assertIn("skill", self.config)

    def test_skill_name_max_length(self) -> None:
        """skill.name.max_length is a string representing a positive integer."""
        self.assertIn("name", self.config["skill"])
        self.assertIn("max_length", self.config["skill"]["name"])
        value = self.config["skill"]["name"]["max_length"]
        self.assertIsInstance(value, str)
        self.assertTrue(value.isdigit(), f"Expected digit string, got {value!r}")
        self.assertGreater(int(value), 0)

    def test_skill_name_min_length(self) -> None:
        """skill.name.min_length is a string representing a non-negative integer."""
        value = self.config["skill"]["name"]["min_length"]
        self.assertIsInstance(value, str)
        self.assertTrue(value.isdigit(), f"Expected digit string, got {value!r}")
        self.assertGreaterEqual(int(value), 0)

    def test_skill_name_format_pattern(self) -> None:
        """skill.name.format_pattern is present and non-empty."""
        pattern = self.config["skill"]["name"]["format_pattern"]
        self.assertIsInstance(pattern, str)
        self.assertGreater(len(pattern), 0)

    def test_skill_name_reserved_words(self) -> None:
        """skill.name.reserved_words is a list containing expected entries."""
        reserved = self.config["skill"]["name"]["reserved_words"]
        self.assertIsInstance(reserved, list)
        self.assertIn("anthropic", reserved)
        self.assertIn("claude", reserved)

    def test_skill_description_max_length(self) -> None:
        """skill.description.max_length is present."""
        self.assertIn("description", self.config["skill"])
        self.assertIn("max_length", self.config["skill"]["description"])

    def test_skill_body_max_lines(self) -> None:
        """skill.body.max_lines is present."""
        self.assertIn("body", self.config["skill"])
        self.assertIn("max_lines", self.config["skill"]["body"])

    def test_skill_recognized_subdirectories(self) -> None:
        """skill.recognized_subdirectories is a list with expected entries."""
        subdirs = self.config["skill"]["recognized_subdirectories"]
        self.assertIsInstance(subdirs, list)
        expected = ["scripts", "references", "assets", "shared", "capabilities"]
        for entry in expected:
            with self.subTest(entry=entry):
                self.assertIn(entry, subdirs)

    def test_bundle_section_exists(self) -> None:
        """The top-level 'bundle' section exists."""
        self.assertIn("bundle", self.config)

    def test_bundle_max_reference_depth(self) -> None:
        """bundle.max_reference_depth is a string representing a positive integer."""
        value = self.config["bundle"]["max_reference_depth"]
        self.assertIsInstance(value, str)
        self.assertTrue(value.isdigit(), f"Expected digit string, got {value!r}")
        self.assertGreater(int(value), 0)

    def test_bundle_description_max_length(self) -> None:
        """bundle.description_max_length is a string representing a positive integer."""
        value = self.config["bundle"]["description_max_length"]
        self.assertIsInstance(value, str)
        self.assertTrue(value.isdigit(), f"Expected digit string, got {value!r}")
        self.assertGreater(int(value), 0)

    def test_bundle_exclude_patterns(self) -> None:
        """bundle.exclude_patterns is a list with expected entries."""
        patterns = self.config["bundle"]["exclude_patterns"]
        self.assertIsInstance(patterns, list)
        expected = [".git", "__pycache__", ".DS_Store"]
        for entry in expected:
            with self.subTest(entry=entry):
                self.assertIn(entry, patterns)

    def test_dependency_direction_section_exists(self) -> None:
        """The top-level 'dependency_direction' section exists."""
        self.assertIn("dependency_direction", self.config)

    def test_bundle_infer_max_walk_depth(self) -> None:
        """bundle.infer_max_walk_depth is a string representing a positive integer."""
        value = self.config["bundle"]["infer_max_walk_depth"]
        self.assertIsInstance(value, str)
        self.assertTrue(value.isdigit(), f"Expected digit string, got {value!r}")
        self.assertGreater(int(value), 0)


if __name__ == "__main__":
    unittest.main()
