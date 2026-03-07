"""Tests for Claude distribution metadata quality guardrails.

These checks keep `keywords` and `tags` semantically distinct so we avoid
duplicating the same discovery values across both fields.
"""

import json
import os
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN_PATH = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")
MARKETPLACE_PATH = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")

# Keep overlap conservative: tags are taxonomy facets, keywords are search terms.
MAX_KEYWORD_TAG_JACCARD = 0.40


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


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


class ClaudeDistributionMetadataTests(unittest.TestCase):
    """Quality checks for `.claude-plugin` distribution manifests."""

    def test_claude_distribution_keywords_and_tags_are_not_mostly_duplicates(self) -> None:
        """`keywords` and `tags` should have limited overlap per plugin."""
        marketplace = _load_json(MARKETPLACE_PATH)
        failures = []

        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            keywords = _normalize_terms(plugin.get("keywords", []))
            tags = _normalize_terms(plugin.get("tags", []))

            if not keywords or not tags:
                continue

            similarity = _jaccard_similarity(keywords, tags)
            if similarity > MAX_KEYWORD_TAG_JACCARD:
                overlap = sorted(keywords & tags)
                failures.append(
                    f"  {name}: overlap={similarity:.2f}, shared={overlap}"
                )

        if failures:
            self.fail(
                "keywords/tags overlap too high (Jaccard similarity > "
                f"{MAX_KEYWORD_TAG_JACCARD:.2f}).\n"
                "Use keywords for search intent terms and tags for taxonomy facets.\n"
                + "\n".join(failures)
            )

    def test_claude_distribution_marketplace_keywords_match_plugin_manifest(self) -> None:
        """Marketplace plugin `keywords` should match `.claude-plugin/plugin.json`."""
        plugin_manifest = _load_json(PLUGIN_PATH)
        marketplace = _load_json(MARKETPLACE_PATH)

        plugin_name = plugin_manifest.get("name", "<unknown>")
        manifest_keywords = _normalize_terms(plugin_manifest.get("keywords", []))

        marketplace_plugin = None
        for plugin in marketplace.get("plugins", []):
            if plugin.get("name") == plugin_name:
                marketplace_plugin = plugin
                break

        self.assertIsNotNone(
            marketplace_plugin,
            "No plugin entry in marketplace.json matches "
            f"plugin.json name '{plugin_name}'.",
        )

        assert marketplace_plugin is not None
        marketplace_keywords = _normalize_terms(marketplace_plugin.get("keywords", []))

        missing_in_marketplace = sorted(manifest_keywords - marketplace_keywords)
        extra_in_marketplace = sorted(marketplace_keywords - manifest_keywords)

        self.assertEqual(
            missing_in_marketplace,
            [],
            "Marketplace keywords are missing terms from plugin.json: "
            f"{missing_in_marketplace}",
        )
        self.assertEqual(
            extra_in_marketplace,
            [],
            "Marketplace keywords contain terms not present in plugin.json: "
            f"{extra_in_marketplace}",
        )

    def test_claude_distribution_plugin_keywords_are_alphabetically_ordered(self) -> None:
        """`plugin.json` keywords should be alphabetically ordered."""
        plugin_manifest = _load_json(PLUGIN_PATH)
        keywords = plugin_manifest.get("keywords", [])

        self.assertEqual(
            keywords,
            _sorted_terms(keywords),
            "plugin.json keywords must be alphabetically ordered.",
        )

    def test_claude_distribution_marketplace_keywords_and_tags_are_alphabetically_ordered(self) -> None:
        """Marketplace plugin `keywords` and `tags` should be ordered."""
        marketplace = _load_json(MARKETPLACE_PATH)
        failures = []

        for plugin in marketplace.get("plugins", []):
            name = plugin.get("name", "<unknown>")
            keywords = plugin.get("keywords", [])
            tags = plugin.get("tags", [])

            if keywords != _sorted_terms(keywords):
                failures.append(f"  {name}: keywords are not alphabetically ordered")
            if tags != _sorted_terms(tags):
                failures.append(f"  {name}: tags are not alphabetically ordered")

        if failures:
            self.fail(
                "marketplace.json metadata fields must be alphabetically ordered:\n"
                + "\n".join(failures)
            )


if __name__ == "__main__":
    unittest.main()
