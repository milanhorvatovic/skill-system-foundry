"""Tests for Claude distribution metadata quality guardrails.

Validates `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`
for required fields, type correctness, cross-file consistency, and
keyword/tag semantics.

Keyword/tag convention (AvdLee pattern):
- ``keywords`` are exhaustive search terms — every term someone might search for.
- ``tags`` are a curated subset of ``keywords`` for display and filtering.
- Every tag must appear in keywords (strict subset enforcement).
"""

import json
import os
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN_PATH = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")
MARKETPLACE_PATH = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")

# Fields that must stay in sync between plugin.json and its marketplace entry.
SYNCED_FIELDS = ("name", "version", "description")
SYNCED_OBJECT_FIELDS = ("author",)


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _assert_string_list(values: object, label: str) -> list[str]:
    """Assert *values* is a ``list[str]`` of non-empty strings.

    Returns the validated list on success.  Raises ``AssertionError`` on
    any type or emptiness violation so callers get a clear diagnostic.
    """
    if not isinstance(values, list):
        raise AssertionError(
            f"{label} must be a list, got {type(values).__name__}: {values!r}"
        )
    for i, item in enumerate(values):
        if not isinstance(item, str):
            raise AssertionError(
                f"{label}[{i}] must be a string, "
                f"got {type(item).__name__}: {item!r}"
            )
        if not item.strip():
            raise AssertionError(
                f"{label}[{i}] must be a non-empty string, got {item!r}"
            )
    return values


def _normalize_terms(values: list[str]) -> set[str]:
    """Lowercase and deduplicate a validated ``list[str]``.

    Callers must pass values through ``_assert_string_list`` first;
    this function assumes every element is a non-empty ``str``.
    """
    return {v.strip().lower() for v in values}


def _find_marketplace_plugin(marketplace: dict, plugin_name: str) -> dict | None:
    """Find the marketplace plugin entry matching *plugin_name*."""
    plugins = marketplace.get("plugins", [])
    if not isinstance(plugins, list):
        raise AssertionError(
            f"marketplace.json 'plugins' must be a list, "
            f"got {type(plugins).__name__}"
        )
    for plugin in plugins:
        if plugin.get("name") == plugin_name:
            return plugin
    return None


# ------------------------------------------------------------------
# Required fields & type validation
# ------------------------------------------------------------------


class PluginManifestRequiredFieldsTests(unittest.TestCase):
    """Verify plugin.json contains all required metadata with correct types."""

    def test_plugin_json_has_required_fields(self) -> None:
        """plugin.json must contain name, description, version, author,
        keywords, and license."""
        manifest = _load_json(PLUGIN_PATH)
        required = ["name", "description", "version", "author", "keywords", "license"]
        missing = [f for f in required if f not in manifest]
        self.assertEqual(
            missing,
            [],
            f"plugin.json is missing required fields: {missing}",
        )

    def test_plugin_json_keywords_are_valid_non_empty_string_list(self) -> None:
        """plugin.json keywords must be a non-empty list of non-empty strings."""
        manifest = _load_json(PLUGIN_PATH)
        keywords = _assert_string_list(
            manifest.get("keywords"), "plugin.json keywords"
        )
        self.assertGreater(
            len(keywords), 0, "plugin.json keywords must not be empty."
        )


class MarketplaceRequiredFieldsTests(unittest.TestCase):
    """Verify marketplace.json contains all required metadata per plugin."""

    def test_marketplace_has_required_top_level_fields(self) -> None:
        """marketplace.json must have name, owner, and plugins."""
        marketplace = _load_json(MARKETPLACE_PATH)
        required = ["name", "owner", "plugins"]
        missing = [f for f in required if f not in marketplace]
        self.assertEqual(
            missing,
            [],
            f"marketplace.json is missing required top-level fields: {missing}",
        )

    def test_marketplace_plugins_is_a_list(self) -> None:
        """marketplace.json plugins field must be a list."""
        marketplace = _load_json(MARKETPLACE_PATH)
        plugins = marketplace.get("plugins")
        self.assertIsInstance(
            plugins, list, "marketplace.json 'plugins' must be a list."
        )

    def test_marketplace_plugins_have_required_fields(self) -> None:
        """Each marketplace plugin entry must have name, source, description,
        keywords, and tags."""
        marketplace = _load_json(MARKETPLACE_PATH)
        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            required = ["name", "source", "description", "keywords", "tags"]
            missing = [f for f in required if f not in plugin]
            with self.subTest(plugin=name):
                self.assertEqual(
                    missing,
                    [],
                    f"Marketplace plugin '{name}' is missing: {missing}",
                )

    def test_marketplace_plugin_keywords_and_tags_are_valid_non_empty_string_lists(
        self,
    ) -> None:
        """Each marketplace plugin must have non-empty keyword and tag lists
        of non-empty strings."""
        marketplace = _load_json(MARKETPLACE_PATH)
        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            for field in ("keywords", "tags"):
                with self.subTest(plugin=name, field=field):
                    values = plugin.get(field)
                    _assert_string_list(
                        values, f"Marketplace plugin '{name}' {field}"
                    )
                    self.assertGreater(
                        len(values),
                        0,
                        f"Marketplace plugin '{name}' {field} must not be empty.",
                    )


# ------------------------------------------------------------------
# Cross-file consistency
# ------------------------------------------------------------------


class CrossFileConsistencyTests(unittest.TestCase):
    """Fields shared between plugin.json and marketplace.json must stay in sync."""

    def setUp(self) -> None:
        self.manifest = _load_json(PLUGIN_PATH)
        self.marketplace = _load_json(MARKETPLACE_PATH)
        self.plugin_name = self.manifest.get("name", "<unknown>")
        self.marketplace_plugin = _find_marketplace_plugin(
            self.marketplace, self.plugin_name
        )

    def test_marketplace_contains_matching_plugin_entry(self) -> None:
        """A marketplace plugin entry must match plugin.json name."""
        self.assertIsNotNone(
            self.marketplace_plugin,
            f"No marketplace plugin entry matches plugin.json name "
            f"'{self.plugin_name}'.",
        )

    def test_synced_string_fields_match(self) -> None:
        """name, version, and description must be identical across both files."""
        if self.marketplace_plugin is None:
            self.skipTest("No matching marketplace entry found.")
        for field in SYNCED_FIELDS:
            with self.subTest(field=field):
                manifest_value = self.manifest.get(field)
                marketplace_value = self.marketplace_plugin.get(field)
                self.assertEqual(
                    manifest_value,
                    marketplace_value,
                    f"'{field}' mismatch — plugin.json has "
                    f"{manifest_value!r}, marketplace.json has "
                    f"{marketplace_value!r}.",
                )

    def test_synced_object_fields_match(self) -> None:
        """author must be identical across both files."""
        if self.marketplace_plugin is None:
            self.skipTest("No matching marketplace entry found.")
        for field in SYNCED_OBJECT_FIELDS:
            with self.subTest(field=field):
                manifest_value = self.manifest.get(field)
                marketplace_value = self.marketplace_plugin.get(field)
                self.assertEqual(
                    manifest_value,
                    marketplace_value,
                    f"'{field}' mismatch — plugin.json has "
                    f"{manifest_value!r}, marketplace.json has "
                    f"{marketplace_value!r}.",
                )

    def test_keywords_match_across_files(self) -> None:
        """plugin.json and marketplace plugin entry must have identical keywords."""
        if self.marketplace_plugin is None:
            self.skipTest("No matching marketplace entry found.")
        manifest_kw = _normalize_terms(
            _assert_string_list(
                self.manifest.get("keywords"), "plugin.json keywords"
            )
        )
        market_kw = _normalize_terms(
            _assert_string_list(
                self.marketplace_plugin.get("keywords"),
                "marketplace.json keywords",
            )
        )
        missing = sorted(manifest_kw - market_kw)
        extra = sorted(market_kw - manifest_kw)
        self.assertEqual(
            missing,
            [],
            f"Marketplace keywords are missing terms from plugin.json: {missing}",
        )
        self.assertEqual(
            extra,
            [],
            f"Marketplace keywords contain terms not in plugin.json: {extra}",
        )


# ------------------------------------------------------------------
# Keyword / tag semantics
# ------------------------------------------------------------------


class KeywordTagSemanticsTests(unittest.TestCase):
    """Enforce the AvdLee convention: tags are a curated subset of keywords."""

    def test_tags_are_subset_of_keywords(self) -> None:
        """Every marketplace tag must appear in the plugin's keywords."""
        marketplace = _load_json(MARKETPLACE_PATH)
        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            keywords = _normalize_terms(
                _assert_string_list(
                    plugin.get("keywords"), f"plugin '{name}' keywords"
                )
            )
            tags = _normalize_terms(
                _assert_string_list(
                    plugin.get("tags"), f"plugin '{name}' tags"
                )
            )
            not_in_keywords = sorted(tags - keywords)
            with self.subTest(plugin=name):
                self.assertEqual(
                    not_in_keywords,
                    [],
                    f"Tags not present in keywords for '{name}': "
                    f"{not_in_keywords}. Tags must be a subset of keywords.",
                )

    def test_tags_are_strictly_smaller_than_keywords(self) -> None:
        """Tags should be a curated subset, not a copy of keywords."""
        marketplace = _load_json(MARKETPLACE_PATH)
        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            keywords = _assert_string_list(
                plugin.get("keywords"), f"plugin '{name}' keywords"
            )
            tags = _assert_string_list(
                plugin.get("tags"), f"plugin '{name}' tags"
            )
            with self.subTest(plugin=name):
                self.assertLess(
                    len(tags),
                    len(keywords),
                    f"Plugin '{name}' has {len(tags)} tags and "
                    f"{len(keywords)} keywords. Tags should be a curated "
                    f"subset, strictly smaller than keywords.",
                )


# ------------------------------------------------------------------
# Alphabetical ordering
# ------------------------------------------------------------------


class AlphabeticalOrderTests(unittest.TestCase):
    """Keywords and tags must be alphabetically ordered for maintainability."""

    def test_plugin_json_keywords_are_ordered(self) -> None:
        """plugin.json keywords must be alphabetically ordered."""
        manifest = _load_json(PLUGIN_PATH)
        keywords = _assert_string_list(
            manifest.get("keywords"), "plugin.json keywords"
        )
        expected = sorted(keywords, key=str.lower)
        self.assertEqual(
            keywords,
            expected,
            "plugin.json keywords must be alphabetically ordered.",
        )

    def test_marketplace_keywords_and_tags_are_ordered(self) -> None:
        """Marketplace plugin keywords and tags must be alphabetically ordered."""
        marketplace = _load_json(MARKETPLACE_PATH)
        failures: list[str] = []
        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            for field in ("keywords", "tags"):
                values = _assert_string_list(
                    plugin.get(field), f"plugin '{name}' {field}"
                )
                expected = sorted(values, key=str.lower)
                if values != expected:
                    failures.append(f"  {name}: {field} are not ordered")
        if failures:
            self.fail(
                "marketplace.json metadata fields must be alphabetically "
                "ordered:\n" + "\n".join(failures)
            )


if __name__ == "__main__":
    unittest.main()
