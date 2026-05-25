"""Tests for lib.config_validation — load-time structure validation.

``validate_config_structure`` guards every key path ``constants.py``
dereferences from the parsed ``configuration.yaml``.  These tests run the
validator in ISOLATION against plain dicts (never the on-disk file) so a
missing or wrong-typed key is shown to raise ``ConfigurationError`` with a
message naming the offending dotted key path.

The canonical valid fixture is built by parsing the shipped
``configuration.yaml`` once and deep-copying it per test, so the
happy-path assertion tracks the real file and each mutation starts from a
structure the validator accepts.
"""

import copy
import os
import sys
import unittest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.config_validation import (
    ConfigurationError,
    validate_config_structure,
)
from lib.yaml_parser import parse_yaml_subset

_CONFIG_PATH = os.path.join(SCRIPTS_DIR, "lib", "configuration.yaml")

with open(_CONFIG_PATH, "r", encoding="utf-8") as _fh:
    _VALID_CONFIG = parse_yaml_subset(_fh.read())


def valid_config() -> dict:
    """Return a fresh deep copy of the parsed shipped configuration."""
    return copy.deepcopy(_VALID_CONFIG)


def _delete(config: dict, dotted: str) -> None:
    """Delete the leaf addressed by *dotted* (``a.b.c``) from *config*."""
    parts = dotted.split(".")
    node = config
    for part in parts[:-1]:
        node = node[part]
    del node[parts[-1]]


def _set(config: dict, dotted: str, value: object) -> None:
    """Set the leaf addressed by *dotted* (``a.b.c``) in *config*."""
    parts = dotted.split(".")
    node = config
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


# ===================================================================
# Happy Path
# ===================================================================


class ValidConfigTests(unittest.TestCase):
    """The shipped configuration passes structure validation."""

    def test_shipped_config_passes(self) -> None:
        # validate_config_structure returns None on a well-formed config.
        self.assertIsNone(validate_config_structure(valid_config()))

    def test_repeated_calls_do_not_mutate_config(self) -> None:
        config = valid_config()
        before = copy.deepcopy(config)
        validate_config_structure(config)
        validate_config_structure(config)
        self.assertEqual(config, before)


# ===================================================================
# Top-level shape
# ===================================================================


class TopLevelShapeTests(unittest.TestCase):
    """A non-mapping top level is rejected with a clear message."""

    def test_non_dict_top_level_raises(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure([])  # type: ignore[arg-type]
        self.assertIn("did not parse to a mapping", str(ctx.exception))

    def test_empty_dict_names_first_missing_section(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure({})
        self.assertIn("skill", str(ctx.exception))
        self.assertIn("configuration.yaml", str(ctx.exception))


# ===================================================================
# Missing top-level sections
# ===================================================================


class MissingTopSectionTests(unittest.TestCase):
    """Each consumed top-level section, when absent, raises naming it."""

    def _assert_missing_raises(self, section: str) -> None:
        config = valid_config()
        del config[section]
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn(section, msg)
        self.assertIn("configuration.yaml", msg)

    def test_missing_skill_raises(self) -> None:
        self._assert_missing_raises("skill")

    def test_missing_plain_scalar_raises(self) -> None:
        self._assert_missing_raises("plain_scalar")

    def test_missing_path_resolution_raises(self) -> None:
        self._assert_missing_raises("path_resolution")

    def test_missing_prose_yaml_raises(self) -> None:
        self._assert_missing_raises("prose_yaml")

    def test_missing_yaml_conformance_raises(self) -> None:
        self._assert_missing_raises("yaml_conformance")

    def test_missing_codex_config_raises(self) -> None:
        self._assert_missing_raises("codex_config")

    def test_missing_dependency_direction_raises(self) -> None:
        self._assert_missing_raises("dependency_direction")

    def test_missing_role_composition_raises(self) -> None:
        self._assert_missing_raises("role_composition")

    def test_missing_orphan_references_raises(self) -> None:
        self._assert_missing_raises("orphan_references")

    def test_missing_bundle_raises(self) -> None:
        self._assert_missing_raises("bundle")

    def test_missing_stats_raises(self) -> None:
        self._assert_missing_raises("stats")


# ===================================================================
# Missing nested keys — message names the full dotted path
# ===================================================================


class MissingNestedKeyTests(unittest.TestCase):
    """Removing a consumed nested key raises a message naming the path."""

    def _assert_missing_path_raises(self, dotted: str) -> None:
        config = valid_config()
        _delete(config, dotted)
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        self.assertIn(dotted, str(ctx.exception))

    def test_missing_skill_name_max_length(self) -> None:
        self._assert_missing_path_raises("skill.name.max_length")

    def test_missing_skill_description_max_length(self) -> None:
        self._assert_missing_path_raises("skill.description.max_length")

    def test_missing_evaluation(self) -> None:
        self._assert_missing_path_raises("skill.description.evaluation")

    def test_missing_evaluation_thresholds_member(self) -> None:
        self._assert_missing_path_raises(
            "skill.description.evaluation.default_min_precision"
        )

    def test_missing_evaluation_coverage(self) -> None:
        self._assert_missing_path_raises(
            "skill.description.evaluation.coverage"
        )

    def test_missing_evaluation_coverage_corpus_root(self) -> None:
        self._assert_missing_path_raises(
            "skill.description.evaluation.coverage.corpus_root_relative"
        )

    def test_missing_structural_rules(self) -> None:
        self._assert_missing_path_raises(
            "skill.description.structural_rules"
        )

    def test_missing_structural_rules_member(self) -> None:
        self._assert_missing_path_raises(
            "skill.description.structural_rules.redundancy_max_ratio"
        )

    def test_missing_voice_pattern(self) -> None:
        self._assert_missing_path_raises(
            "skill.description.voice_patterns.first_person"
        )

    def test_missing_body_max_lines(self) -> None:
        self._assert_missing_path_raises("skill.body.max_lines")

    def test_missing_reference_pattern(self) -> None:
        self._assert_missing_path_raises(
            "skill.body.reference_patterns.markdown_link"
        )

    def test_missing_allowed_tools_max_tools(self) -> None:
        self._assert_missing_path_raises("skill.allowed_tools.max_tools")

    def test_missing_catalogs_claude_code(self) -> None:
        self._assert_missing_path_raises(
            "skill.allowed_tools.catalogs.claude_code"
        )

    def test_missing_claude_code_harness_tools(self) -> None:
        self._assert_missing_path_raises(
            "skill.allowed_tools.catalogs.claude_code.harness_tools"
        )

    def test_missing_metadata_version_pattern(self) -> None:
        self._assert_missing_path_raises("skill.metadata.version.pattern")

    def test_missing_license_known_spdx(self) -> None:
        self._assert_missing_path_raises("skill.license.known_spdx")

    def test_missing_capability_frontmatter_skill_only_fields(self) -> None:
        self._assert_missing_path_raises(
            "skill.capability_frontmatter.skill_only_fields"
        )

    def test_missing_path_resolution_reference_extensions(self) -> None:
        self._assert_missing_path_raises(
            "path_resolution.reference_extensions"
        )

    def test_missing_degraded_symlink_max_bytes(self) -> None:
        self._assert_missing_path_raises(
            "path_resolution.degraded_symlink.max_bytes"
        )

    def test_missing_bundle_long_path_threshold(self) -> None:
        self._assert_missing_path_raises("bundle.long_path.threshold")

    def test_missing_codex_interface_hex_color(self) -> None:
        self._assert_missing_path_raises(
            "codex_config.interface.hex_color_pattern"
        )

    def test_missing_role_min_skills(self) -> None:
        self._assert_missing_path_raises("role_composition.min_skills")

    def test_missing_stats_line_endings(self) -> None:
        self._assert_missing_path_raises("stats.line_endings")

    def test_missing_orphan_allowed_orphans(self) -> None:
        self._assert_missing_path_raises(
            "orphan_references.allowed_orphans"
        )

    def test_missing_prose_opt_out_marker(self) -> None:
        self._assert_missing_path_raises("prose_yaml.opt_out_marker")


# ===================================================================
# Wrong shape — mapping / list / scalar mismatch
# ===================================================================


class WrongShapeTests(unittest.TestCase):
    """A key authored with the wrong shape raises naming the path."""

    def test_skill_scalar_where_mapping_expected(self) -> None:
        config = valid_config()
        config["skill"] = "oops"
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill", msg)
        self.assertIn("expected a mapping", msg)

    def test_evaluation_list_where_mapping_expected(self) -> None:
        config = valid_config()
        _set(config, "skill.description.evaluation", [])
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.description.evaluation", msg)
        self.assertIn("expected a mapping", msg)

    def test_capability_frontmatter_list_where_mapping_expected(self) -> None:
        config = valid_config()
        _set(config, "skill.capability_frontmatter", [])
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.capability_frontmatter", msg)
        self.assertIn("expected a mapping", msg)

    def test_reserved_words_scalar_where_list_expected(self) -> None:
        config = valid_config()
        _set(config, "skill.name.reserved_words", "claude")
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.name.reserved_words", msg)
        self.assertIn("expected a list", msg)

    def test_known_spdx_mapping_where_list_expected(self) -> None:
        config = valid_config()
        _set(config, "skill.license.known_spdx", {"a": "b"})
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.license.known_spdx", msg)
        self.assertIn("expected a list", msg)

    def test_format_pattern_mapping_where_scalar_expected(self) -> None:
        config = valid_config()
        _set(config, "skill.name.format_pattern", {"nested": "x"})
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.name.format_pattern", msg)
        self.assertIn("expected a scalar", msg)

    def test_default_target_list_where_scalar_expected(self) -> None:
        config = valid_config()
        _set(config, "bundle.default_target", ["claude"])
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("bundle.default_target", msg)
        self.assertIn("expected a scalar", msg)

    def test_fence_language_entry_non_mapping_raises(self) -> None:
        config = valid_config()
        _set(config, "skill.allowed_tools.fence_languages", {"Bash": []})
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.allowed_tools.fence_languages.Bash", msg)
        self.assertIn("expected a mapping", msg)

    def test_fence_language_missing_languages_list_raises(self) -> None:
        config = valid_config()
        _set(
            config,
            "skill.allowed_tools.fence_languages",
            {"Bash": {"languages": "bash"}},
        )
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn(
            "skill.allowed_tools.fence_languages.Bash.languages", msg
        )
        self.assertIn("expected a list", msg)

    def test_orphan_allowed_orphans_mapping_rejected(self) -> None:
        config = valid_config()
        _set(config, "orphan_references.allowed_orphans", {"a": "b"})
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("orphan_references.allowed_orphans", msg)
        self.assertIn("expected a list", msg)

    def test_orphan_allowed_orphans_blank_is_accepted(self) -> None:
        # A key with no value parses as "" — the blank form is legal
        # (constants.py coerces it to an empty list) and must not raise.
        config = valid_config()
        _set(config, "orphan_references.allowed_orphans", "")
        self.assertIsNone(validate_config_structure(config))


# ===================================================================
# Malformed numerics — non-integer / non-float scalars
# ===================================================================


class MalformedNumericTests(unittest.TestCase):
    """A scalar destined for int()/float() that does not convert raises
    a message naming the key (not a bare ValueError)."""

    def test_non_integer_max_length_raises(self) -> None:
        config = valid_config()
        _set(config, "skill.name.max_length", "sixty-four")
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.name.max_length", msg)
        self.assertIn("expected an integer", msg)

    def test_non_integer_body_max_lines_raises(self) -> None:
        config = valid_config()
        _set(config, "skill.body.max_lines", "lots")
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.body.max_lines", msg)
        self.assertIn("expected an integer", msg)

    def test_non_integer_long_path_threshold_raises(self) -> None:
        config = valid_config()
        _set(config, "bundle.long_path.threshold", "wide")
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("bundle.long_path.threshold", msg)
        self.assertIn("expected an integer", msg)

    def test_non_float_cutoff_raises(self) -> None:
        config = valid_config()
        _set(config, "skill.frontmatter_suggestions.cutoff", "high")
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.frontmatter_suggestions.cutoff", msg)
        self.assertIn("expected a number", msg)

    def test_non_float_redundancy_max_ratio_raises(self) -> None:
        config = valid_config()
        _set(
            config,
            "skill.description.structural_rules.redundancy_max_ratio",
            "quarter",
        )
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn(
            "skill.description.structural_rules.redundancy_max_ratio", msg
        )
        self.assertIn("expected a number", msg)

    def test_integer_destined_value_as_mapping_reports_scalar(self) -> None:
        # An int key authored as a mapping is reported as a scalar
        # mismatch (the shape check fires before the int() attempt).
        config = valid_config()
        _set(config, "skill.name.max_length", {"x": 1})
        with self.assertRaises(ConfigurationError) as ctx:
            validate_config_structure(config)
        msg = str(ctx.exception)
        self.assertIn("skill.name.max_length", msg)
        self.assertIn("expected a scalar", msg)


if __name__ == "__main__":
    unittest.main()
