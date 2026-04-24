"""Tests for scripts/lib/version.py.

The helpers are pure functions with no I/O except the ``read_*`` group,
so most tests operate on in-memory strings.  File-backed tests use
``tempfile`` to stay hermetic across Linux and Windows runners.
"""

import importlib.util
import json
import os
import tempfile
import unittest

# Load the module by explicit path so the import does not collide with the
# meta-skill's ``lib`` package (which other tests pull onto sys.path first).
_VERSION_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts", "lib", "version.py")
)
_spec = importlib.util.spec_from_file_location(
    "repo_infra_version", _VERSION_PATH
)
assert _spec is not None and _spec.loader is not None
version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(version)


SAMPLE_SKILL_MD = """\
---
name: example
description: >
  A test skill.
metadata:
  author: Someone
  version: 1.1.0
  spec: agentskills.io
---

# Example

Body mentions version: 9.9.9 which must NOT be rewritten.

```yaml
metadata:
  version: 7.7.7
```
"""

SAMPLE_PLUGIN_JSON = """\
{
  "name": "example",
  "description": "A plugin.",
  "keywords": [
    "version-tag-in-keyword"
  ],
  "version": "1.1.0"
}
"""

SAMPLE_MARKETPLACE_JSON = """\
{
  "name": "example",
  "owner": {"name": "Someone"},
  "plugins": [
    {
      "name": "example",
      "description": "A plugin.",
      "version": "1.1.0",
      "tags": ["version-tag-in-tag"]
    }
  ]
}
"""


# ===================================================================
# Semver regex
# ===================================================================


class SemverRegexTests(unittest.TestCase):
    def test_accepts_basic_semver(self) -> None:
        for value in ("0.0.0", "1.2.3", "10.20.30", "1.0.0-rc.1", "2.0.0-alpha-2"):
            with self.subTest(value=value):
                self.assertTrue(version.SEMVER_RE.match(value))

    def test_rejects_v_prefix_and_build_metadata(self) -> None:
        for value in ("v1.2.3", "1.2.3+build", "1.2.3-rc.1+42", ""):
            with self.subTest(value=value):
                self.assertIsNone(version.SEMVER_RE.match(value))

    def test_rejects_non_numeric_core(self) -> None:
        for value in ("1.2", "1.2.3.4", "one.two.three", "1.2.3-"):
            with self.subTest(value=value):
                self.assertIsNone(version.SEMVER_RE.match(value))

    def test_rejects_leading_zero_in_core(self) -> None:
        for value in ("01.2.3", "1.02.3", "1.2.03"):
            with self.subTest(value=value):
                self.assertIsNone(version.SEMVER_RE.match(value))

    def test_rejects_empty_or_trailing_prerelease_identifiers(self) -> None:
        for value in ("1.2.3-alpha.", "1.2.3-.alpha", "1.2.3-alpha..1"):
            with self.subTest(value=value):
                self.assertIsNone(version.SEMVER_RE.match(value))

    def test_rejects_leading_zero_in_numeric_prerelease(self) -> None:
        # Per SemVer §9, numeric prerelease identifiers must not include
        # leading zeros.  ``rc.01`` is invalid; ``rc.10`` is valid.
        self.assertIsNone(version.SEMVER_RE.match("1.2.3-rc.01"))
        self.assertTrue(version.SEMVER_RE.match("1.2.3-rc.10"))


# ===================================================================
# parse / compare
# ===================================================================


class ParseTests(unittest.TestCase):
    def test_splits_core_and_prerelease(self) -> None:
        self.assertEqual(version.parse("1.2.3"), (1, 2, 3, ""))
        self.assertEqual(version.parse("1.2.3-rc.1"), (1, 2, 3, "rc.1"))

    def test_rejects_invalid(self) -> None:
        with self.assertRaises(ValueError):
            version.parse("v1.2.3")
        with self.assertRaises(ValueError):
            version.parse("")


class CompareTests(unittest.TestCase):
    def test_core_ordering(self) -> None:
        self.assertEqual(version.compare("1.0.0", "1.0.1"), -1)
        self.assertEqual(version.compare("2.0.0", "1.9.9"), 1)
        self.assertEqual(version.compare("1.0.0", "1.0.0"), 0)

    def test_prerelease_rules(self) -> None:
        # A version with a prerelease is less than the same version without.
        self.assertEqual(version.compare("1.0.0-rc.1", "1.0.0"), -1)
        self.assertEqual(version.compare("1.0.0", "1.0.0-rc.1"), 1)
        # Alphanumeric identifiers compare lexically.
        self.assertEqual(version.compare("1.0.0-alpha", "1.0.0-beta"), -1)
        self.assertEqual(version.compare("1.0.0-rc.2", "1.0.0-rc.1"), 1)
        self.assertEqual(version.compare("1.0.0-rc.1", "1.0.0-rc.1"), 0)

    def test_prerelease_numeric_identifiers_compare_numerically(self) -> None:
        # Lex order would put ``rc.10`` below ``rc.2``; SemVer §11 ranks
        # numeric identifiers numerically.
        self.assertEqual(version.compare("1.0.0-rc.10", "1.0.0-rc.2"), 1)
        self.assertEqual(version.compare("1.0.0-rc.2", "1.0.0-rc.10"), -1)

    def test_prerelease_numeric_below_alphanumeric(self) -> None:
        # SemVer §11.4.3: numeric identifiers always have lower precedence
        # than alphanumeric identifiers.
        self.assertEqual(version.compare("1.0.0-1", "1.0.0-alpha"), -1)
        self.assertEqual(version.compare("1.0.0-alpha", "1.0.0-1"), 1)

    def test_prerelease_shorter_identifier_set_is_lower(self) -> None:
        # SemVer §11.4.4: a smaller set of identifiers (with all preceding
        # equal) has lower precedence than a larger set.
        self.assertEqual(version.compare("1.0.0-alpha", "1.0.0-alpha.1"), -1)
        self.assertEqual(version.compare("1.0.0-alpha.1", "1.0.0-alpha"), 1)


# ===================================================================
# read_* helpers
# ===================================================================


class ReadSkillMdVersionTests(unittest.TestCase):
    def test_reads_metadata_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "SKILL.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(SAMPLE_SKILL_MD)
            self.assertEqual(version.read_skill_md_version(path), "1.1.0")

    def test_returns_none_when_no_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "SKILL.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# Title only\n")
            self.assertIsNone(version.read_skill_md_version(path))

    def test_returns_none_when_metadata_missing_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "SKILL.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("---\nname: x\nmetadata:\n  author: A\n---\n")
            self.assertIsNone(version.read_skill_md_version(path))


class ReadPluginJsonVersionTests(unittest.TestCase):
    def test_reads_top_level_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plugin.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(SAMPLE_PLUGIN_JSON)
            self.assertEqual(version.read_plugin_json_version(path), "1.1.0")

    def test_returns_none_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plugin.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"name": "x"}, fh)
            self.assertIsNone(version.read_plugin_json_version(path))

    def test_returns_none_when_non_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plugin.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"version": 1}, fh)
            self.assertIsNone(version.read_plugin_json_version(path))


class ReadMarketplaceJsonVersionTests(unittest.TestCase):
    def test_matches_plugin_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "marketplace.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(SAMPLE_MARKETPLACE_JSON)
            self.assertEqual(
                version.read_marketplace_json_version(path, "example"),
                "1.1.0",
            )

    def test_returns_none_when_name_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "marketplace.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(SAMPLE_MARKETPLACE_JSON)
            self.assertIsNone(
                version.read_marketplace_json_version(path, "other")
            )

    def test_returns_none_when_plugins_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "marketplace.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"name": "x"}, fh)
            self.assertIsNone(
                version.read_marketplace_json_version(path, "example")
            )


# ===================================================================
# plan_* helpers
# ===================================================================


class PlanSkillMdEditTests(unittest.TestCase):
    def test_replaces_frontmatter_version_only(self) -> None:
        out = version.plan_skill_md_edit(SAMPLE_SKILL_MD, "1.1.0", "1.2.0")
        self.assertIn("  version: 1.2.0", out)
        # The body mention and the fenced-code example must stay intact.
        self.assertIn("Body mentions version: 9.9.9", out)
        self.assertIn("  version: 7.7.7", out)

    def test_rejects_missing_current(self) -> None:
        with self.assertRaises(ValueError):
            version.plan_skill_md_edit(SAMPLE_SKILL_MD, "9.9.9", "1.2.0")

    def test_rejects_missing_frontmatter(self) -> None:
        with self.assertRaises(ValueError):
            version.plan_skill_md_edit(
                "# no frontmatter\n", "1.0.0", "1.1.0"
            )

    def test_rejects_unterminated_frontmatter(self) -> None:
        with self.assertRaises(ValueError):
            version.plan_skill_md_edit(
                "---\nname: x\nmetadata:\n  version: 1.0.0\n", "1.0.0", "1.1.0"
            )

    def test_plans_quoted_version_and_preserves_quote_style(self) -> None:
        # ``read_skill_md_version`` strips matched surrounding quotes, so a
        # quoted manifest must round-trip through the planner — preserving
        # the exact quote character the file used.
        for quote in ('"', "'"):
            content = (
                "---\nname: x\nmetadata:\n  "
                f"version: {quote}1.0.0{quote}\n---\n"
            )
            with self.subTest(quote=quote):
                out = version.plan_skill_md_edit(content, "1.0.0", "1.1.0")
                self.assertIn(f"version: {quote}1.1.0{quote}", out)
                self.assertNotIn(f"version: {quote}1.0.0{quote}", out)


class PlanPluginJsonEditTests(unittest.TestCase):
    def test_replaces_version(self) -> None:
        out = version.plan_plugin_json_edit(SAMPLE_PLUGIN_JSON, "1.1.0", "1.2.0")
        self.assertIn('"version": "1.2.0"', out)
        # Keyword content containing the substring "version" must not change.
        self.assertIn("version-tag-in-keyword", out)

    def test_rejects_missing_current(self) -> None:
        with self.assertRaises(ValueError):
            version.plan_plugin_json_edit(SAMPLE_PLUGIN_JSON, "9.9.9", "1.2.0")

    def test_rejects_multiple_version_lines(self) -> None:
        # Two structurally valid top-level version lines would be a plan failure.
        content = (
            '{\n  "version": "1.1.0",\n  "sidecar": {\n    "version": "1.1.0"\n  }\n}\n'
        )
        with self.assertRaises(ValueError):
            version.plan_plugin_json_edit(content, "1.1.0", "1.2.0")

    def test_rejects_compact_json_with_pretty_format_hint(self) -> None:
        # A compact one-line JSON document is valid JSON but the planner
        # cannot anchor on it — surface the formatting contract in the
        # error message so the operator knows how to recover.
        content = '{"name":"demo","version":"1.1.0"}\n'
        with self.assertRaises(ValueError) as ctx:
            version.plan_plugin_json_edit(content, "1.1.0", "1.2.0")
        self.assertIn("pretty-printed", str(ctx.exception))


class PlanMarketplaceJsonEditTests(unittest.TestCase):
    def test_replaces_nested_version(self) -> None:
        out = version.plan_marketplace_json_edit(
            SAMPLE_MARKETPLACE_JSON, "1.1.0", "1.2.0"
        )
        self.assertIn('"version": "1.2.0"', out)
        self.assertIn("version-tag-in-tag", out)

    def test_rejects_missing_current(self) -> None:
        with self.assertRaises(ValueError):
            version.plan_marketplace_json_edit(
                SAMPLE_MARKETPLACE_JSON, "9.9.9", "1.2.0"
            )


# ===================================================================
# path helpers
# ===================================================================


class PathHelperTests(unittest.TestCase):
    def test_paths_are_joined_correctly(self) -> None:
        root = os.path.join("a", "b")
        self.assertEqual(
            version.skill_md_path(root),
            os.path.join(root, "skill-system-foundry", "SKILL.md"),
        )
        self.assertEqual(
            version.plugin_json_path(root),
            os.path.join(root, ".claude-plugin", "plugin.json"),
        )
        self.assertEqual(
            version.marketplace_json_path(root),
            os.path.join(root, ".claude-plugin", "marketplace.json"),
        )


if __name__ == "__main__":
    unittest.main()
