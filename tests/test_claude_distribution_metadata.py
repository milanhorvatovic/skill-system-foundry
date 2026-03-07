"""Tests for Claude distribution metadata quality guardrails.

Validates `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`
for required fields, cross-file consistency, and keyword/tag semantics.

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


def _normalize_terms(values: list[str]) -> set[str]:
    normalized = set()
    for value in values:
        text = str(value).strip().lower()
        if text:
            normalized.add(text)
    return normalized


def _sorted_terms(values: list[str]) -> list[str]:
    return sorted(values, key=lambda value: str(value).lower())


def _find_marketplace_plugin(marketplace: dict, plugin_name: str) -> dict | None:
    """Find the marketplace plugin entry matching *plugin_name*."""
    for plugin in marketplace.get("plugins", []):
        if plugin.get("name") == plugin_name:
            return plugin
    return None


class PluginManifestRequiredFieldsTests(unittest.TestCase):
    """Verify plugin.json contains all required metadata."""

    def test_plugin_json_has_required_fields(self) -> None:
        """plugin.json must contain name, description, version, author, and keywords."""
        manifest = _load_json(PLUGIN_PATH)
        required = ["name", "description", "version", "author", "keywords", "license"]
        missing = [f for f in required if f not in manifest]
        self.assertEqual(
            missing,
            [],
            f"plugin.json is missing required fields: {missing}",
        )

    def test_plugin_json_keywords_are_non_empty(self) -> None:
        """plugin.json keywords must not be empty."""
        manifest = _load_json(PLUGIN_PATH)
        keywords = manifest.get("keywords", [])
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

    def test_marketplace_plugin_keywords_and_tags_are_non_empty(self) -> None:
        """Each marketplace plugin must have non-empty keywords and tags."""
        marketplace = _load_json(MARKETPLACE_PATH)
        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            with self.subTest(plugin=name, field="keywords"):
                self.assertGreater(
                    len(plugin.get("keywords", [])),
                    0,
                    f"Marketplace plugin '{name}' keywords must not be empty.",
                )
            with self.subTest(plugin=name, field="tags"):
                self.assertGreater(
                    len(plugin.get("tags", [])),
                    0,
                    f"Marketplace plugin '{name}' tags must not be empty.",
                )


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
        manifest_kw = _normalize_terms(self.manifest.get("keywords", []))
        market_kw = _normalize_terms(
            self.marketplace_plugin.get("keywords", [])
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


class KeywordTagSemanticsTests(unittest.TestCase):
    """Enforce the AvdLee convention: tags are a curated subset of keywords."""

    def test_tags_are_subset_of_keywords(self) -> None:
        """Every marketplace tag must appear in the plugin's keywords."""
        marketplace = _load_json(MARKETPLACE_PATH)
        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            keywords = _normalize_terms(plugin.get("keywords", []))
            tags = _normalize_terms(plugin.get("tags", []))
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
            keywords = plugin.get("keywords", [])
            tags = plugin.get("tags", [])
            with self.subTest(plugin=name):
                self.assertLess(
                    len(tags),
                    len(keywords),
                    f"Plugin '{name}' has {len(tags)} tags and "
                    f"{len(keywords)} keywords. Tags should be a curated "
                    f"subset, strictly smaller than keywords.",
                )


class AlphabeticalOrderTests(unittest.TestCase):
    """Keywords and tags must be alphabetically ordered for maintainability."""

    def test_plugin_json_keywords_are_ordered(self) -> None:
        """plugin.json keywords must be alphabetically ordered."""
        manifest = _load_json(PLUGIN_PATH)
        keywords = manifest.get("keywords", [])
        self.assertEqual(
            keywords,
            _sorted_terms(keywords),
            "plugin.json keywords must be alphabetically ordered.",
        )

    def test_marketplace_keywords_and_tags_are_ordered(self) -> None:
        """Marketplace plugin keywords and tags must be alphabetically ordered."""
        marketplace = _load_json(MARKETPLACE_PATH)
        failures = []
        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            keywords = plugin.get("keywords", [])
            tags = plugin.get("tags", [])
            if keywords != _sorted_terms(keywords):
                failures.append(f"  {name}: keywords are not ordered")
            if tags != _sorted_terms(tags):
                failures.append(f"  {name}: tags are not ordered")
        if failures:
            self.fail(
                "marketplace.json metadata fields must be alphabetically "
                "ordered:\n" + "\n".join(failures)
            )


if __name__ == "__main__":
    unittest.main()
