"""Tests for lib.description_eval — corpus loader and shape rules (step 4).

Covers the 12 corpus-shape rules: required keys, types, unknown keys, per-side
counts (FAIL < 4, WARN 4-7), duplicates, empty prompts, pos/neg contradiction,
cross-target overlap, phrasing diversity, length cap, and control characters.
"""

import json
import os
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import helpers
from lib import description_eval as de


def valid_corpus_dict() -> dict:
    """A schema-clean corpus: 8+8 prompts, distinct leading bigrams."""
    return {
        "target": "skill-design",
        "kind": "capability",
        "positive": [
            "Create a new validation skill",
            "How do I scaffold a capability",
            "Audit my skill system for drift",
            "Bundle this skill into a zip",
            "Migrate a flat skill to router",
            "Design a role composing two skills",
            "Write an effective skill description",
            "Validate references in my SKILL file",
        ],
        "negative": [
            "Help me write a web scraper",
            "Debug this React component please",
            "Set up a Postgres database now",
            "Explain monads in Haskell briefly",
            "Generate a marketing email draft",
            "Refactor my Java service layer",
            "Plot a sine wave with matplotlib",
            "Translate this paragraph to French",
        ],
    }


def has_fail(findings: list[str]) -> bool:
    return any(f.startswith(de.LEVEL_FAIL) for f in findings)


def has_warn(findings: list[str]) -> bool:
    return any(f.startswith(de.LEVEL_WARN) for f in findings)


class LoadCorpusBaseMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _write(self, content: str, name: str = "skill.json") -> str:
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        return path

    def _write_dict(self, data: dict, name: str = "skill.json") -> str:
        return self._write(json.dumps(data, indent=2), name)

    def load_dict(self, data: dict) -> tuple[object, list[str]]:
        return de.load_corpus(self._write_dict(data))


class ValidCorpusTests(LoadCorpusBaseMixin):
    def test_clean_corpus_returns_corpus_with_no_findings(self) -> None:
        corpus, findings = self.load_dict(valid_corpus_dict())
        self.assertIsNotNone(corpus)
        self.assertEqual(findings, [])
        self.assertEqual(corpus.target, "skill-design")
        self.assertEqual(corpus.kind, de.KIND_CAPABILITY)
        self.assertEqual(len(corpus.positive), 8)
        self.assertEqual(len(corpus.negative), 8)
        self.assertIsNone(corpus.min_precision)
        self.assertTrue(os.path.isabs(corpus.source_path))

    def test_underscore_keys_and_optional_metadata_tolerated(self) -> None:
        data = valid_corpus_dict()
        data["_comment"] = "explains intent"
        data["description_sha256"] = None
        data["min_precision"] = 0.9
        data["min_recall"] = 0.8
        corpus, findings = self.load_dict(data)
        self.assertIsNotNone(corpus)
        self.assertEqual(findings, [])
        self.assertEqual(corpus.min_precision, 0.9)
        self.assertEqual(corpus.min_recall, 0.8)


class RequiredKeyAndTypeTests(LoadCorpusBaseMixin):
    def test_missing_required_key_fails(self) -> None:
        data = valid_corpus_dict()
        del data["target"]
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(has_fail(findings))
        self.assertTrue(any("missing required key 'target'" in f for f in findings))

    def test_bad_kind_fails(self) -> None:
        data = valid_corpus_dict()
        data["kind"] = "role"
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("'kind' must be" in f for f in findings))

    def test_empty_target_fails(self) -> None:
        data = valid_corpus_dict()
        data["target"] = "   "
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("'target' must be a non-empty string" in f for f in findings))

    def test_positive_not_a_list_fails(self) -> None:
        data = valid_corpus_dict()
        data["positive"] = "not a list"
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("'positive' must be a list of strings" in f for f in findings))

    def test_positive_with_non_string_item_fails(self) -> None:
        data = valid_corpus_dict()
        data["positive"] = data["positive"][:7] + [123]
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("'positive' must contain only strings" in f for f in findings))

    def test_unknown_top_level_key_fails(self) -> None:
        data = valid_corpus_dict()
        data["bogus"] = 1
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("unknown top-level key 'bogus'" in f for f in findings))


class OptionalThresholdTests(LoadCorpusBaseMixin):
    def test_out_of_range_min_precision_fails(self) -> None:
        data = valid_corpus_dict()
        data["min_precision"] = 1.5
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("'min_precision' must be between 0 and 1" in f for f in findings))

    def test_non_numeric_min_recall_fails(self) -> None:
        data = valid_corpus_dict()
        data["min_recall"] = "high"
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("'min_recall' must be a number" in f for f in findings))

    def test_boolean_threshold_rejected(self) -> None:
        data = valid_corpus_dict()
        data["min_precision"] = True
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("'min_precision' must be a number" in f for f in findings))


class PromptCountTests(LoadCorpusBaseMixin):
    def test_fewer_than_four_fails(self) -> None:
        data = valid_corpus_dict()
        data["positive"] = data["positive"][:3]
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("at least 4 are required" in f for f in findings))

    def test_four_to_seven_warns_but_loads(self) -> None:
        data = valid_corpus_dict()
        data["positive"] = data["positive"][:5]
        corpus, findings = self.load_dict(data)
        self.assertIsNotNone(corpus)
        self.assertFalse(has_fail(findings))
        self.assertTrue(any("8-10 are recommended" in f for f in findings))


class PromptHygieneTests(LoadCorpusBaseMixin):
    def test_duplicate_within_side_fails(self) -> None:
        data = valid_corpus_dict()
        data["positive"][1] = data["positive"][0]
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("duplicate prompt in 'positive'" in f for f in findings))

    def test_empty_prompt_fails(self) -> None:
        data = valid_corpus_dict()
        data["positive"][0] = "   "
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("empty or whitespace-only prompt" in f for f in findings))

    def test_same_prompt_both_sides_fails(self) -> None:
        data = valid_corpus_dict()
        data["negative"][0] = data["positive"][0]
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("appears in both 'positive' and 'negative'" in f for f in findings))

    def test_overlong_prompt_fails(self) -> None:
        data = valid_corpus_dict()
        data["positive"][0] = "x" * (de.EVAL_MAX_PROMPT_CHARS + 1)
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("exceeds" in f and "characters" in f for f in findings))

    def test_control_char_prompt_fails(self) -> None:
        data = valid_corpus_dict()
        data["positive"][0] = "create a skill\x07now"
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        self.assertTrue(any("control / non-printable" in f for f in findings))


class DiversityTests(LoadCorpusBaseMixin):
    def test_low_diversity_warns_but_loads(self) -> None:
        data = valid_corpus_dict()
        # Force every positive to share the leading bigram "create skill".
        data["positive"] = [f"create skill variant number {i}" for i in range(8)]
        corpus, findings = self.load_dict(data)
        self.assertIsNotNone(corpus)
        self.assertFalse(has_fail(findings))
        self.assertTrue(any("phrasing diversity" in f for f in findings))


class MalformedFileTests(LoadCorpusBaseMixin):
    def test_invalid_json_fails(self) -> None:
        path = self._write("{ not json ]")
        corpus, findings = de.load_corpus(path)
        self.assertIsNone(corpus)
        self.assertTrue(any("invalid JSON" in f for f in findings))

    def test_non_object_top_level_fails(self) -> None:
        path = self._write("[1, 2, 3]")
        corpus, findings = de.load_corpus(path)
        self.assertIsNone(corpus)
        self.assertTrue(any("must be an object" in f for f in findings))

    def test_missing_file_fails(self) -> None:
        corpus, findings = de.load_corpus(os.path.join(self._tmp.name, "nope.json"))
        self.assertIsNone(corpus)
        self.assertTrue(any("cannot read corpus file" in f for f in findings))


class CrossTargetOverlapTests(unittest.TestCase):
    def _corpus(self, target: str, positive: tuple[str, ...]) -> de.Corpus:
        return de.Corpus(
            target=target, kind=de.KIND_CAPABILITY,
            positive=positive, negative=(),
            min_precision=None, min_recall=None, source_path="/x.json",
        )

    def test_shared_positive_warns(self) -> None:
        a = self._corpus("alpha", ("shared prompt", "alpha only"))
        b = self._corpus("beta", ("shared prompt", "beta only"))
        findings = de.check_cross_target_overlap([a, b])
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith(de.LEVEL_WARN))
        self.assertIn("shared prompt", findings[0])
        self.assertIn("alpha", findings[0])
        self.assertIn("beta", findings[0])

    def test_no_overlap_returns_empty(self) -> None:
        a = self._corpus("alpha", ("alpha one", "alpha two"))
        b = self._corpus("beta", ("beta one", "beta two"))
        self.assertEqual(de.check_cross_target_overlap([a, b]), [])


class DiscoveryBaseMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name


class DiscoverUnitsSkillRootTests(DiscoveryBaseMixin):
    def test_skill_root_discovers_skill_and_capabilities(self) -> None:
        helpers.write_skill_md(
            self.root, name="skill-system-foundry",
            description="Designs AI-agnostic skill systems.", body="# Foundry\n",
        )
        helpers.write_capability_md(
            self.root, "validation", allowed_tools="Bash Read",
            body="# Validation\n\nValidate skills and audit systems.\n",
        )
        helpers.write_capability_md(
            self.root, "bundling", allowed_tools="Bash Read",
            body="# Bundling\n\nPackage a skill as a zip bundle.\n",
        )
        by_name = {u.name: u for u in de.discover_units(self.root)}

        self.assertEqual(by_name["skill-system-foundry"].kind, de.KIND_SKILL)
        self.assertEqual(
            by_name["skill-system-foundry"].description,
            "Designs AI-agnostic skill systems.",
        )
        self.assertEqual(by_name["validation"].kind, de.KIND_CAPABILITY)
        self.assertEqual(
            by_name["validation"].description, "Validate skills and audit systems.",
        )
        self.assertEqual(by_name["validation"].parent, "skill-system-foundry")
        self.assertEqual(by_name["bundling"].parent, "skill-system-foundry")
        self.assertEqual(
            by_name["validation"].card_text,
            "validation Validate skills and audit systems.",
        )

    def test_skill_without_capabilities_returns_only_skill(self) -> None:
        helpers.write_skill_md(self.root, name="lonely", description="Solo skill.")
        units = de.discover_units(self.root)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].kind, de.KIND_SKILL)
        self.assertIsNone(units[0].parent)


class DiscoverUnitsDeployedTests(DiscoveryBaseMixin):
    def test_deployed_layout_discovers_each_skill(self) -> None:
        helpers.write_skill_md(
            os.path.join(self.root, "alpha"), name="alpha", description="Alpha skill.",
        )
        helpers.write_skill_md(
            os.path.join(self.root, "beta"), name="beta", description="Beta skill.",
        )
        os.makedirs(os.path.join(self.root, "not-a-skill"))
        units = de.discover_units(self.root)
        self.assertEqual(sorted(u.name for u in units), ["alpha", "beta"])
        self.assertTrue(all(u.kind == de.KIND_SKILL for u in units))

    def test_missing_directory_returns_empty(self) -> None:
        self.assertEqual(de.discover_units(os.path.join(self.root, "nope")), [])


class CapabilityCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _cap(self, text: str) -> str:
        path = os.path.join(self._tmp.name, "capability.md")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        return path

    def test_multiline_intro_paragraph_joined(self) -> None:
        path = self._cap(
            "---\nallowed-tools: Bash\n---\n\n# Migration\n\n"
            "Convert flat skills\ninto routers.\n\nSecond paragraph.\n"
        )
        name, description = de.extract_capability_card(path, "migration")
        self.assertEqual(name, "migration")
        self.assertEqual(description, "Convert flat skills into routers.")

    def test_heading_only_yields_empty_description(self) -> None:
        path = self._cap("---\nallowed-tools: Bash\n---\n\n# OnlyHeading\n")
        self.assertEqual(de.extract_capability_card(path, "lonely"), ("lonely", ""))

    def test_no_heading_uses_first_paragraph(self) -> None:
        path = self._cap("Plain intro line.\n\nMore.\n")
        _name, description = de.extract_capability_card(path, "x")
        self.assertEqual(description, "Plain intro line.")


if __name__ == "__main__":
    unittest.main()
