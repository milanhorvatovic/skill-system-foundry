"""Tests for lib.description_eval — heuristic activation evaluation.

Covers the corpus loader and shape rules, unit discovery + capability card
extraction, the Jaccard heuristic scorer, the deterministic split, metrics +
confusion matrix, pairwise confusion, and the evaluate orchestrator.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

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


def _unit(name: str, description: str) -> de.Unit:
    return de.Unit(
        name=name, kind=de.KIND_CAPABILITY, description=description, path=f"/{name}",
    )


def _scored(label: str, prediction: str | None, count: int) -> list[de.ScoredQuery]:
    return [
        de.ScoredQuery(prompt=f"{label}-{i}", label=label, prediction=prediction)
        for i in range(count)
    ]


# ===================================================================
# Corpus loader + shape rules
# ===================================================================


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
        path = self._write_dict(valid_corpus_dict())
        corpus, findings = de.load_corpus(path)
        self.assertIsNotNone(corpus)
        self.assertEqual(findings, [])
        self.assertEqual(corpus.target, "skill-design")
        self.assertEqual(corpus.kind, de.KIND_CAPABILITY)
        self.assertEqual(len(corpus.positive), 8)
        self.assertEqual(len(corpus.negative), 8)
        self.assertIsNone(corpus.min_precision)
        # source_path preserves the raw input path (no abspath) so load_corpus
        # and evaluate() findings share one path representation.
        self.assertEqual(corpus.source_path, path)

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

    def test_every_non_string_item_is_reported(self) -> None:
        # The validator enumerates all offenders rather than stopping at the
        # first, matching the unknown-key and required-key loops.
        data = valid_corpus_dict()
        data["positive"] = data["positive"][:6] + [123, {"x": 1}]
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus)
        offenders = [f for f in findings if "'positive' must contain only strings" in f]
        self.assertEqual(len(offenders), 2)
        self.assertTrue(any("123" in f for f in offenders))

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
        self.assertTrue(any("at least 8 are recommended" in f for f in findings))


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


class SourcePathLabelTests(LoadCorpusBaseMixin):
    def test_source_path_is_raw_input_not_abspath(self) -> None:
        # A '/./' segment survives to_posix but abspath would strip it; storing
        # the raw path keeps load_corpus and evaluate() labels identical.
        written = self._write_dict(valid_corpus_dict())
        raw = os.path.join(
            os.path.dirname(written), ".", os.path.basename(written),
        )
        corpus, _findings = de.load_corpus(raw)
        self.assertIsNotNone(corpus)
        self.assertEqual(corpus.source_path, raw)
        self.assertNotEqual(corpus.source_path, os.path.abspath(raw))

    def test_load_and_evaluate_share_path_label(self) -> None:
        # A target-not-found error from evaluate() must quote the same path
        # representation load_corpus uses — no relative/absolute divergence.
        data = valid_corpus_dict()
        data["target"] = "ghost"
        raw = os.path.join(self._tmp.name, ".", "skill.json")
        self._write_dict(data)  # writes to <tmp>/skill.json, reachable via raw
        corpus, _findings = de.load_corpus(raw)
        report = de.evaluate(
            [corpus], [], {"min_precision": 0.85, "min_recall": 0.85},
        )
        self.assertTrue(report.errors)
        self.assertIn(de.to_posix(raw), report.errors[0])


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

    def test_overlap_across_kinds_not_flagged(self) -> None:
        # A prompt positive for a skill and for a capability is not a real
        # ambiguity — different kinds do not compete in the scorer.
        skill = de.Corpus(
            target="foundry", kind=de.KIND_SKILL,
            positive=("shared prompt",), negative=(),
            min_precision=None, min_recall=None, source_path="/s.json",
        )
        cap = self._corpus("validation", ("shared prompt", "cap only"))
        self.assertEqual(de.check_cross_target_overlap([skill, cap]), [])


# ===================================================================
# Discovery + card extraction
# ===================================================================


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

    def test_unreadable_file_yields_empty_description(self) -> None:
        path = os.path.join(self._tmp.name, "binary.md")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xfe not valid utf-8 \x00")
        self.assertEqual(de.extract_capability_card(path, "broken"), ("broken", ""))

    def test_parse_error_frontmatter_yields_empty_card(self) -> None:
        with mock.patch.object(
            de, "load_frontmatter",
            return_value=({"_parse_error": "boom"}, "# H\n\nIntro\n", []),
        ):
            self.assertEqual(de._safe_load_frontmatter("/x"), ({}, ""))


# ===================================================================
# Heuristic scorer
# ===================================================================


class TokenizeTests(unittest.TestCase):
    def test_lowercases_splits_and_drops_stopwords(self) -> None:
        self.assertEqual(
            de.tokenize("The Validation, Audit! of-systems"),
            {"validation", "audit", "systems"},
        )

    def test_empty_text_yields_empty_set(self) -> None:
        self.assertEqual(de.tokenize("the of and"), set())


class ScoreHeuristicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            _unit("validation", "Validate skills and audit systems for consistency"),
            _unit("bundling", "Package a skill as a zip bundle"),
        ]

    def test_clear_winner_selected(self) -> None:
        prediction = de.score_heuristic(
            "audit skills and check systems for consistency", self.candidates,
        )
        self.assertEqual(prediction, "validation")

    def test_below_threshold_returns_none(self) -> None:
        prediction = de.score_heuristic("translate french text", self.candidates)
        self.assertIsNone(prediction)

    def test_tie_breaks_to_alphabetically_first(self) -> None:
        candidates = [_unit("beta", "shared word"), _unit("alpha", "shared word")]
        self.assertEqual(de.score_heuristic("shared word", candidates), "alpha")

    def test_empty_candidate_set_returns_none(self) -> None:
        self.assertIsNone(de.score_heuristic("anything", []))


# ===================================================================
# Metrics + pairwise
# ===================================================================


class AggregateTests(unittest.TestCase):
    def test_all_correct_passes(self) -> None:
        scored = (
            _scored(de.LABEL_POSITIVE, "skill-design", 4)
            + _scored(de.LABEL_NEGATIVE, None, 4)
        )
        metrics = de.aggregate(scored, "skill-design", 0.85, 0.85)
        self.assertEqual((metrics.tp, metrics.fp, metrics.tn, metrics.fn), (4, 0, 4, 0))
        self.assertEqual(metrics.precision, 1.0)
        self.assertEqual(metrics.recall, 1.0)
        self.assertTrue(metrics.passed)

    def test_all_wrong_fails(self) -> None:
        scored = (
            _scored(de.LABEL_POSITIVE, None, 4)
            + _scored(de.LABEL_NEGATIVE, "skill-design", 4)
        )
        metrics = de.aggregate(scored, "skill-design", 0.85, 0.85)
        self.assertEqual((metrics.tp, metrics.fp, metrics.tn, metrics.fn), (0, 4, 0, 4))
        self.assertEqual(metrics.precision, 0.0)
        self.assertEqual(metrics.recall, 0.0)
        self.assertFalse(metrics.passed)

    def test_negative_predicting_other_unit_is_true_negative(self) -> None:
        scored = (
            _scored(de.LABEL_POSITIVE, "skill-design", 4)
            + _scored(de.LABEL_NEGATIVE, "bundling", 4)
        )
        metrics = de.aggregate(scored, "skill-design", 0.85, 0.85)
        self.assertEqual((metrics.fp, metrics.tn), (0, 4))
        self.assertTrue(metrics.passed)

    def test_empty_denominator_defaults_to_one(self) -> None:
        metrics = de.aggregate(_scored(de.LABEL_NEGATIVE, None, 4), "x", 0.85, 0.85)
        self.assertEqual(metrics.precision, 1.0)
        self.assertEqual(metrics.recall, 1.0)
        self.assertTrue(metrics.passed)

    def test_threshold_gates_on_precision(self) -> None:
        scored = (
            _scored(de.LABEL_POSITIVE, "skill-design", 4)
            + _scored(de.LABEL_NEGATIVE, "skill-design", 1)
            + _scored(de.LABEL_NEGATIVE, None, 3)
        )
        metrics = de.aggregate(scored, "skill-design", 0.85, 0.85)
        self.assertAlmostEqual(metrics.precision, 0.8)
        self.assertEqual(metrics.recall, 1.0)
        self.assertFalse(metrics.passed)


class PairwiseConfusionTests(unittest.TestCase):
    def test_counts_only_misrouted_positives(self) -> None:
        scored = [
            de.ScoredQuery("p1", de.LABEL_POSITIVE, "skill-design"),  # correct
            de.ScoredQuery("p2", de.LABEL_POSITIVE, "bundling"),      # misrouted positive
            de.ScoredQuery("p3", de.LABEL_POSITIVE, "bundling"),      # misrouted positive
            de.ScoredQuery("p4", de.LABEL_POSITIVE, None),            # missed, not a steal
            de.ScoredQuery("n1", de.LABEL_NEGATIVE, "bundling"),      # negative correctly off-target
            de.ScoredQuery("n2", de.LABEL_NEGATIVE, "validation"),    # negative correctly off-target
        ]
        # Only positive prompts misrouted to a sibling count.
        self.assertEqual(
            de.pairwise_confusion(scored, "skill-design"), {"bundling": 2},
        )


# ===================================================================
# Evaluate orchestrator
# ===================================================================


class EvaluateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = de.Unit("foundry", de.KIND_SKILL, "Designs skill systems", "/S")
        self.validation = de.Unit(
            "validation", de.KIND_CAPABILITY,
            "validate skills audit systems consistency", "/v", parent="foundry",
        )
        self.bundling = de.Unit(
            "bundling", de.KIND_CAPABILITY,
            "package skill zip bundle distribution", "/b", parent="foundry",
        )
        self.candidates = [self.skill, self.validation, self.bundling]
        self.positive = (
            "validate skills", "audit systems consistency",
            "validate audit consistency", "skills audit systems",
        )
        self.negative = (
            "package zip bundle", "distribution package zip",
            "translate french text", "debug react component",
        )

    def _corpus(self, target: str = "validation", kind: str = de.KIND_CAPABILITY) -> de.Corpus:
        return de.Corpus(
            target=target, kind=kind, positive=self.positive, negative=self.negative,
            min_precision=None, min_recall=None, source_path="/c.json",
        )

    @staticmethod
    def _opts(**overrides: object) -> dict:
        base = {"min_precision": 0.85, "min_recall": 0.85}
        base.update(overrides)
        return base

    def test_heuristic_capability_eval_passes(self) -> None:
        report = de.evaluate([self._corpus()], self.candidates, self._opts())
        self.assertTrue(report.success)
        result = report.targets[0]
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.metrics.tp, 4)
        self.assertEqual(result.metrics.fp, 0)
        self.assertTrue(result.metrics.passed)
        # Positives all route correctly, so there is no boundary confusion.
        self.assertEqual(result.advisory["pairwise_confusion"], {})

    def test_missing_target_records_fail(self) -> None:
        report = de.evaluate(
            [self._corpus(target="ghost")], self.candidates, self._opts(),
        )
        self.assertFalse(report.success)
        self.assertEqual(report.targets, [])
        self.assertTrue(any("was not found" in e for e in report.errors))

    def test_skill_target_competes_with_skills(self) -> None:
        other = de.Unit("other", de.KIND_SKILL, "unrelated skill", "/o")
        candidates = self.candidates + [other]
        report = de.evaluate(
            [self._corpus(target="foundry", kind=de.KIND_SKILL)],
            candidates, self._opts(),
        )
        self.assertEqual(report.targets[0].candidate_count, 2)

    def test_ambiguous_capability_target_fails(self) -> None:
        # Two skills, each with a 'validation' capability — the corpus target
        # cannot be disambiguated, so it must FAIL rather than score the wrong one.
        candidates = [
            de.Unit("alpha", de.KIND_SKILL, "alpha skill", "/a"),
            de.Unit("validation", de.KIND_CAPABILITY, "validate alpha", "/a/v", parent="alpha"),
            de.Unit("beta", de.KIND_SKILL, "beta skill", "/b"),
            de.Unit("validation", de.KIND_CAPABILITY, "validate beta", "/b/v", parent="beta"),
        ]
        report = de.evaluate([self._corpus()], candidates, self._opts())
        self.assertFalse(report.success)
        self.assertEqual(report.targets, [])
        self.assertTrue(any("ambiguous" in e for e in report.errors))

    def test_per_corpus_threshold_override_recorded(self) -> None:
        corpus = de.Corpus(
            target="validation", kind=de.KIND_CAPABILITY,
            positive=self.positive, negative=self.negative,
            min_precision=0.5, min_recall=0.6, source_path="/c.json",
        )
        result = de.evaluate([corpus], self.candidates, self._opts()).targets[0]
        # Effective (overridden) thresholds are recorded on the result.
        self.assertEqual(result.min_precision, 0.5)
        self.assertEqual(result.min_recall, 0.6)

    def test_default_thresholds_recorded_without_override(self) -> None:
        result = de.evaluate([self._corpus()], self.candidates, self._opts()).targets[0]
        self.assertEqual(result.min_precision, 0.85)
        self.assertEqual(result.min_recall, 0.85)

    def test_injected_scorer_is_used_and_findings_flow(self) -> None:
        # A custom scorer overrides the heuristic and its findings reach the
        # report's error stream; here every prompt is forced to predict the
        # target, so all positives are TP and all negatives FP.
        def forced_scorer(corpus: de.Corpus, _cset: list[de.Unit]):
            scored = [
                de.ScoredQuery(p, de.LABEL_POSITIVE, corpus.target)
                for p in corpus.positive
            ] + [
                de.ScoredQuery(n, de.LABEL_NEGATIVE, corpus.target)
                for n in corpus.negative
            ]
            return scored, [f"{de.LEVEL_WARN}: [foundry] injected note"]

        report = de.evaluate(
            [self._corpus()], self.candidates, self._opts(), scorer=forced_scorer,
        )
        result = report.targets[0]
        self.assertEqual(result.metrics.fp, len(self.negative))
        self.assertTrue(any("injected note" in e for e in report.errors))


# ===================================================================
# Shipped corpora
# ===================================================================


class ShippedMetaSkillCorpusTests(unittest.TestCase):
    def test_all_shipped_corpora_are_schema_valid(self) -> None:
        corpus_root = os.path.join(os.path.dirname(__file__), "skill-corpus")
        files = []
        for dirpath, _dirnames, filenames in os.walk(corpus_root):
            for name in filenames:
                if name.endswith(".json"):
                    files.append(os.path.join(dirpath, name))
        self.assertTrue(files, "no shipped corpora found under tests/skill-corpus")
        for path in sorted(files):
            corpus, findings = de.load_corpus(path)
            fails = [f for f in findings if f.startswith(de.LEVEL_FAIL)]
            self.assertEqual(fails, [], f"{path} produced FAIL findings: {fails}")
            self.assertIsNotNone(corpus)


# ===================================================================
# Description hashing
# ===================================================================


class ComputeDescriptionSha256Tests(unittest.TestCase):
    """Tests for compute_description_sha256."""

    def test_matches_hashlib_reference(self) -> None:
        """Output equals a direct hashlib.sha256 hexdigest of UTF-8 bytes."""
        import hashlib

        text = "Validates skills against the specification."
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(de.compute_description_sha256(text), expected)

    def test_stable_across_calls(self) -> None:
        """Same input yields the same hex digest every call (deterministic)."""
        text = "Designs AI-agnostic skill systems"
        first = de.compute_description_sha256(text)
        second = de.compute_description_sha256(text)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_distinct_inputs_differ(self) -> None:
        """Different descriptions produce different digests."""
        self.assertNotEqual(
            de.compute_description_sha256("alpha"),
            de.compute_description_sha256("beta"),
        )

    def test_unicode_is_utf8_encoded(self) -> None:
        """Non-ASCII text hashes via its UTF-8 bytes, not str identity."""
        import hashlib

        text = "Designs skill systèms — naïve façade"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(de.compute_description_sha256(text), expected)

    def test_empty_string_hashes(self) -> None:
        """An empty description still produces the canonical empty digest."""
        import hashlib

        self.assertEqual(
            de.compute_description_sha256(""),
            hashlib.sha256(b"").hexdigest(),
        )


# ===================================================================
# Corpus description_sha256 extraction
# ===================================================================


class CorpusDescriptionShaExtractionTests(LoadCorpusBaseMixin):
    """load_corpus surfaces description_sha256 with graceful tolerance."""

    def test_absent_hash_is_none(self) -> None:
        corpus, findings = self.load_dict(valid_corpus_dict())
        self.assertIsNotNone(corpus)
        self.assertIsNone(corpus.description_sha256)
        self.assertEqual(findings, [])

    def test_string_hash_is_preserved(self) -> None:
        data = valid_corpus_dict()
        data["description_sha256"] = "a" * 64
        corpus, findings = self.load_dict(data)
        self.assertEqual(corpus.description_sha256, "a" * 64)
        self.assertEqual(findings, [])

    def test_null_hash_is_none_without_finding(self) -> None:
        data = valid_corpus_dict()
        data["description_sha256"] = None
        corpus, findings = self.load_dict(data)
        self.assertIsNone(corpus.description_sha256)
        self.assertEqual(findings, [])

    def test_non_string_hash_is_treated_as_absent(self) -> None:
        """A numeric / malformed hash is tolerated as None, not a crash."""
        data = valid_corpus_dict()
        data["description_sha256"] = 12345
        corpus, findings = self.load_dict(data)
        self.assertIsNotNone(corpus)
        self.assertIsNone(corpus.description_sha256)
        self.assertFalse(has_fail(findings))

    def test_blank_string_hash_is_treated_as_absent(self) -> None:
        data = valid_corpus_dict()
        data["description_sha256"] = "   "
        corpus, _ = self.load_dict(data)
        self.assertIsNone(corpus.description_sha256)


# ===================================================================
# backfill_corpus_hashes
# ===================================================================


class BackfillCorpusHashesTests(unittest.TestCase):
    """The lib-level backfill: matching, idempotency, byte stability."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _corpus(self, data: dict, name: str = "skill-design.json") -> str:
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
        return path

    def _unit(self, description: str) -> de.Unit:
        return de.Unit(
            name="skill-design", kind=de.KIND_CAPABILITY,
            description=description, path="/skill-design",
        )

    def test_writes_expected_hash_and_reports_updated(self) -> None:
        path = self._corpus(valid_corpus_dict())
        outcome = de.backfill_corpus_hashes([path], [self._unit("design skills")])
        self.assertEqual(outcome.updated, [path])
        self.assertEqual(outcome.unchanged, [])
        with open(path, "r", encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual(
            written["description_sha256"],
            de.compute_description_sha256("design skills"),
        )

    def test_second_run_is_a_byte_for_byte_no_op(self) -> None:
        path = self._corpus(valid_corpus_dict())
        units = [self._unit("design skills")]
        de.backfill_corpus_hashes([path], units)
        with open(path, "r", encoding="utf-8") as handle:
            after_first = handle.read()
        outcome = de.backfill_corpus_hashes([path], units)
        with open(path, "r", encoding="utf-8") as handle:
            after_second = handle.read()
        self.assertEqual(outcome.updated, [])
        self.assertEqual(outcome.unchanged, [path])
        self.assertEqual(after_first, after_second)

    def test_unmatched_target_warns_and_leaves_file_untouched(self) -> None:
        path = self._corpus(valid_corpus_dict())
        with open(path, "r", encoding="utf-8") as handle:
            before = handle.read()
        outcome = de.backfill_corpus_hashes([path], [])  # no candidate units
        self.assertEqual(outcome.updated, [])
        self.assertTrue(any("not found" in f for f in outcome.findings))
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)

    def test_malformed_corpus_surfaces_fail_and_skips(self) -> None:
        path = self._corpus({"target": "skill-design", "kind": "capability"})
        outcome = de.backfill_corpus_hashes([path], [self._unit("design")])
        self.assertTrue(has_fail(outcome.findings))
        self.assertEqual(outcome.updated, [])
        self.assertEqual(outcome.unchanged, [])

    def test_correct_hash_in_noncanonical_file_is_left_untouched(self) -> None:
        # A corpus already carrying the right hash must not be rewritten, even
        # when its on-disk formatting is non-canonical (4-space indent here).
        data = valid_corpus_dict()
        data["description_sha256"] = de.compute_description_sha256("design skills")
        path = os.path.join(self._tmp.name, "skill-design.json")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, indent=4) + "\n")  # non-canonical
        with open(path, "r", encoding="utf-8") as handle:
            before = handle.read()
        outcome = de.backfill_corpus_hashes([path], [self._unit("design skills")])
        self.assertEqual(outcome.unchanged, [path])
        self.assertEqual(outcome.updated, [])
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)  # bytes preserved

    def test_load_fail_alongside_corpus_skips_write(self) -> None:
        # Defensive: if load_corpus ever returns a Corpus alongside a FAIL,
        # backfill must surface the FAIL and not mutate the file.
        path = self._corpus(valid_corpus_dict())
        with open(path, "r", encoding="utf-8") as handle:
            before = handle.read()
        corpus = de.Corpus(
            target="skill-design", kind=de.KIND_CAPABILITY,
            positive=("p",) * 8, negative=("n",) * 8,
            min_precision=None, min_recall=None, source_path=path,
        )
        fail = f"{de.LEVEL_FAIL}: [foundry] {path}: forced load failure"
        with mock.patch.object(de, "load_corpus", return_value=(corpus, [fail])):
            outcome = de.backfill_corpus_hashes([path], [self._unit("design")])
        self.assertEqual(outcome.updated, [])
        self.assertEqual(outcome.unchanged, [])
        self.assertIn(fail, outcome.findings)
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)  # not mutated

    def test_write_failure_is_recorded_as_finding(self) -> None:
        # An OSError during the write (e.g. read-only file, race) must become a
        # structured FAIL finding, not an uncaught traceback, and not abort.
        path = self._corpus(valid_corpus_dict())
        with mock.patch.object(
            de, "_write_corpus_hash", side_effect=OSError("read-only"),
        ):
            outcome = de.backfill_corpus_hashes([path], [self._unit("design")])
        self.assertTrue(has_fail(outcome.findings))
        self.assertEqual(outcome.updated, [])
        self.assertEqual(outcome.unchanged, [])
        self.assertTrue(any("cannot write hash" in f for f in outcome.findings))

    def test_nonobject_json_in_write_path_is_a_structured_fail(self) -> None:
        # Race: load_corpus validated an object, but the file is replaced with
        # valid-but-non-object JSON (``[]``) before the write re-reads it.
        # json.loads succeeds, .get raises AttributeError — the shape guard in
        # _write_corpus_hash must convert that into a ValueError that the caller
        # records as a structured FAIL instead of crashing the sweep.
        path = self._corpus(valid_corpus_dict())
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("[]\n")  # valid JSON, not an object
        corpus = de.Corpus(
            target="skill-design", kind=de.KIND_CAPABILITY,
            positive=("p",) * 8, negative=("n",) * 8,
            min_precision=None, min_recall=None, source_path=path,
        )
        with mock.patch.object(de, "load_corpus", return_value=(corpus, [])):
            outcome = de.backfill_corpus_hashes(
                [path], [self._unit("design")],
            )
        self.assertTrue(has_fail(outcome.findings))
        self.assertEqual(outcome.updated, [])
        self.assertEqual(outcome.unchanged, [])
        self.assertTrue(any("cannot write hash" in f for f in outcome.findings))


# ===================================================================
# Agent-delegated tasks: make_task_id + build_tasks
# ===================================================================


class MakeTaskIdTests(unittest.TestCase):
    def test_format(self) -> None:
        self.assertEqual(
            de.make_task_id("validation", de.KIND_CAPABILITY, de.LABEL_POSITIVE, 3),
            "validation:capability:positive:3",
        )


class BuildTasksMixin(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = de.Unit("foundry", de.KIND_SKILL, "Designs skill systems", "/S")
        self.validation = de.Unit(
            "validation", de.KIND_CAPABILITY,
            "validate skills audit systems", "/v", parent="foundry",
        )
        self.bundling = de.Unit(
            "bundling", de.KIND_CAPABILITY,
            "package skill zip bundle", "/b", parent="foundry",
        )
        self.candidates = [self.skill, self.validation, self.bundling]

    def _corpus(self, target: str = "validation", kind: str = de.KIND_CAPABILITY) -> de.Corpus:
        return de.Corpus(
            target=target, kind=kind,
            positive=("validate skills", "audit systems"),
            negative=("package zip", "bundle distribution"),
            min_precision=None, min_recall=None, source_path="/c.json",
        )


class BuildTasksTests(BuildTasksMixin):
    def test_one_task_per_prompt_with_canonical_ids(self) -> None:
        tasks, findings = de.build_tasks([self._corpus()], self.candidates)
        self.assertEqual(findings, [])
        self.assertEqual(len(tasks), 4)  # 2 positive + 2 negative
        ids = [t.id for t in tasks]
        self.assertEqual(
            ids,
            [
                "validation:capability:positive:0",
                "validation:capability:positive:1",
                "validation:capability:negative:0",
                "validation:capability:negative:1",
            ],
        )

    def test_index_resets_per_label(self) -> None:
        tasks, _ = de.build_tasks([self._corpus()], self.candidates)
        positives = [t for t in tasks if t.label == de.LABEL_POSITIVE]
        negatives = [t for t in tasks if t.label == de.LABEL_NEGATIVE]
        self.assertEqual([t.id.rsplit(":", 1)[1] for t in positives], ["0", "1"])
        self.assertEqual([t.id.rsplit(":", 1)[1] for t in negatives], ["0", "1"])

    def test_cards_are_sibling_capabilities_name_sorted(self) -> None:
        tasks, _ = de.build_tasks([self._corpus()], self.candidates)
        # A capability competes with its sibling capabilities (not the skill),
        # and cards are name-sorted to match the heuristic candidate order.
        names = [card.name for card in tasks[0].cards]
        self.assertEqual(names, ["bundling", "validation"])
        self.assertEqual(tasks[0].cards[0].description, "package skill zip bundle")

    def test_skill_target_cards_are_sibling_skills(self) -> None:
        other = de.Unit("other", de.KIND_SKILL, "unrelated", "/o")
        tasks, _ = de.build_tasks(
            [self._corpus(target="foundry", kind=de.KIND_SKILL)],
            self.candidates + [other],
        )
        self.assertEqual([c.name for c in tasks[0].cards], ["foundry", "other"])

    def test_missing_target_records_fail_and_emits_no_tasks(self) -> None:
        tasks, findings = de.build_tasks(
            [self._corpus(target="ghost")], self.candidates,
        )
        self.assertEqual(tasks, [])
        self.assertTrue(has_fail(findings))
        self.assertTrue(any("was not found" in f for f in findings))

    def test_ambiguous_target_records_fail_and_emits_no_tasks(self) -> None:
        candidates = [
            de.Unit("alpha", de.KIND_SKILL, "alpha", "/a"),
            de.Unit("validation", de.KIND_CAPABILITY, "validate alpha", "/a/v", parent="alpha"),
            de.Unit("beta", de.KIND_SKILL, "beta", "/b"),
            de.Unit("validation", de.KIND_CAPABILITY, "validate beta", "/b/v", parent="beta"),
        ]
        tasks, findings = de.build_tasks([self._corpus()], candidates)
        self.assertEqual(tasks, [])
        self.assertTrue(any("ambiguous" in f for f in findings))


# ===================================================================
# Emitters: emit_tasks + emit_heuristic_predictions
# ===================================================================


class EmitterMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.candidates = [
            de.Unit("foundry", de.KIND_SKILL, "Designs skill systems", "/S"),
            de.Unit(
                "validation", de.KIND_CAPABILITY,
                "validate skills audit systems consistency", "/v", parent="foundry",
            ),
            de.Unit(
                "bundling", de.KIND_CAPABILITY,
                "package skill zip bundle distribution", "/b", parent="foundry",
            ),
        ]

    def _corpus_file(self, data: dict, name: str = "validation.json") -> str:
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
        return path

    def _valid_corpus(self) -> str:
        return self._corpus_file({
            "target": "validation", "kind": "capability",
            "positive": [
                "validate skills", "audit systems", "validate consistency",
                "skills consistency",
            ],
            "negative": [
                "package zip", "bundle distribution", "translate french",
                "debug react",
            ],
        })

    def _read(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)


class EmitTasksTests(EmitterMixin):
    def test_writes_envelope_with_tasks_and_instructions(self) -> None:
        corpus = self._valid_corpus()
        out = os.path.join(self.root, "out.tasks.json")
        outcome = de.emit_tasks([corpus], self.candidates, out)
        self.assertFalse(has_fail(outcome.findings))
        self.assertEqual(outcome.task_count, 8)
        self.assertEqual(outcome.corpora_count, 1)
        payload = self._read(out)
        self.assertEqual(payload["tool"], "evaluate_descriptions")
        self.assertEqual(payload["mode"], "emit-tasks")
        self.assertIn("instructions", payload)
        self.assertEqual(len(payload["tasks"]), 8)
        first = payload["tasks"][0]
        self.assertEqual(first["id"], "validation:capability:positive:0")
        self.assertEqual([c["name"] for c in first["cards"]], ["bundling", "validation"])

    def test_emit_is_byte_stable(self) -> None:
        corpus = self._valid_corpus()
        a = os.path.join(self.root, "a.tasks.json")
        b = os.path.join(self.root, "b.tasks.json")
        de.emit_tasks([corpus], self.candidates, a)
        de.emit_tasks([corpus], self.candidates, b)
        with open(a, "r", encoding="utf-8") as fa, open(b, "r", encoding="utf-8") as fb:
            self.assertEqual(fa.read(), fb.read())

    def test_malformed_corpus_is_a_fail_finding(self) -> None:
        bad = self._corpus_file({"target": "validation", "kind": "capability"})
        out = os.path.join(self.root, "out.tasks.json")
        outcome = de.emit_tasks([bad], self.candidates, out)
        self.assertTrue(has_fail(outcome.findings))
        self.assertEqual(outcome.task_count, 0)

    def test_unwritable_path_is_a_fail_finding(self) -> None:
        corpus = self._valid_corpus()
        blocker = os.path.join(self.root, "blocker")
        with open(blocker, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("not a dir")
        out = os.path.join(blocker, "sub", "out.tasks.json")
        outcome = de.emit_tasks([corpus], self.candidates, out)
        self.assertTrue(any("cannot write task file" in f for f in outcome.findings))


class EmitHeuristicPredictionsTests(EmitterMixin):
    def test_writes_id_to_name_or_null_map(self) -> None:
        corpus = self._valid_corpus()
        out = os.path.join(self.root, "h.predictions.json")
        outcome = de.emit_heuristic_predictions([corpus], self.candidates, out)
        self.assertFalse(has_fail(outcome.findings))
        predictions = self._read(out)
        self.assertEqual(len(predictions), 8)
        self.assertIn("validation:capability:positive:0", predictions)
        valid = {"validation", "bundling", None}
        for value in predictions.values():
            self.assertIn(value, valid)

    def test_values_match_score_heuristic(self) -> None:
        corpus = self._valid_corpus()
        out = os.path.join(self.root, "h.predictions.json")
        de.emit_heuristic_predictions([corpus], self.candidates, out)
        predictions = self._read(out)
        # The positive "validate skills" must route to the validation card.
        self.assertEqual(predictions["validation:capability:positive:0"], "validation")

    def test_unwritable_path_is_a_fail_finding(self) -> None:
        corpus = self._valid_corpus()
        blocker = os.path.join(self.root, "blocker")
        with open(blocker, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("not a dir")
        out = os.path.join(blocker, "sub", "h.predictions.json")
        outcome = de.emit_heuristic_predictions([corpus], self.candidates, out)
        self.assertTrue(any("cannot write predictions" in f for f in outcome.findings))

    def test_bare_filename_writes_in_cwd(self) -> None:
        # Exercises the no-dirname branch of _write_json_file: a relative bare
        # filename has no parent directory to create.
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        corpus = os.path.basename(self._valid_corpus())
        outcome = de.emit_heuristic_predictions([corpus], self.candidates, "bare.json")
        self.assertFalse(has_fail(outcome.findings))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "bare.json")))


# ===================================================================
# Prediction loading + scoring
# ===================================================================


class LoadPredictionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _write(self, content: str) -> str:
        path = os.path.join(self._tmp.name, "p.predictions.json")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        return path

    def test_valid_map_loads(self) -> None:
        path = self._write(json.dumps({"a:skill:positive:0": "foundry", "b": None}))
        predictions, findings = de.load_predictions(path)
        self.assertEqual(findings, [])
        self.assertEqual(predictions, {"a:skill:positive:0": "foundry", "b": None})

    def test_unreadable_path_fails(self) -> None:
        predictions, findings = de.load_predictions(
            os.path.join(self._tmp.name, "missing.json")
        )
        self.assertIsNone(predictions)
        self.assertTrue(any("cannot read" in f for f in findings))

    def test_invalid_json_fails(self) -> None:
        predictions, findings = de.load_predictions(self._write("{ not json ]"))
        self.assertIsNone(predictions)
        self.assertTrue(any("invalid JSON" in f for f in findings))

    def test_non_object_root_fails(self) -> None:
        predictions, findings = de.load_predictions(self._write("[]"))
        self.assertIsNone(predictions)
        self.assertTrue(any("must be an object" in f for f in findings))

    def test_non_string_non_null_value_fails(self) -> None:
        predictions, findings = de.load_predictions(
            self._write(json.dumps({"a": 3, "b": True}))
        )
        self.assertIsNone(predictions)
        self.assertTrue(has_fail(findings))
        self.assertTrue(any("string or null" in f for f in findings))


class ScoredFromPredictionsTests(unittest.TestCase):
    def _task(self, task_id: str, label: str, prompt: str = "p") -> de.Task:
        return de.Task(
            id=task_id, target="validation", kind=de.KIND_CAPABILITY,
            label=label, prompt=prompt,
            cards=(de.Card("validation", "d1"), de.Card("bundling", "d2")),
        )

    def test_null_is_no_activation(self) -> None:
        task = self._task("validation:capability:negative:0", de.LABEL_NEGATIVE)
        scored, findings = de.scored_from_predictions([task], {task.id: None})
        self.assertEqual(findings, [])
        self.assertIsNone(scored[0].prediction)

    def test_candidate_name_is_kept(self) -> None:
        task = self._task("validation:capability:positive:0", de.LABEL_POSITIVE)
        scored, findings = de.scored_from_predictions([task], {task.id: "validation"})
        self.assertEqual(findings, [])
        self.assertEqual(scored[0].prediction, "validation")

    def test_missing_id_fails_and_scores_no_activation(self) -> None:
        task = self._task("validation:capability:positive:0", de.LABEL_POSITIVE)
        scored, findings = de.scored_from_predictions([task], {})
        self.assertTrue(any("missing prediction" in f for f in findings))
        self.assertIsNone(scored[0].prediction)

    def test_unknown_name_fails_and_coerces_to_no_activation(self) -> None:
        task = self._task("validation:capability:positive:0", de.LABEL_POSITIVE)
        scored, findings = de.scored_from_predictions([task], {task.id: "ghost"})
        self.assertTrue(any("not a candidate unit name" in f for f in findings))
        self.assertTrue(has_fail(findings))
        self.assertIsNone(scored[0].prediction)


class UnmatchedPredictionIdsTests(unittest.TestCase):
    def test_stale_id_warns(self) -> None:
        warnings = de.unmatched_prediction_ids({"a", "b"}, {"a": None, "c": "x"})
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith(de.LEVEL_WARN))
        self.assertIn("'c'", warnings[0])

    def test_no_stale_ids_is_empty(self) -> None:
        self.assertEqual(de.unmatched_prediction_ids({"a", "b"}, {"a": None}), [])


class EvaluateWithPredictionsTests(EmitterMixin):
    def _corpus_obj(self) -> de.Corpus:
        return de.Corpus(
            target="validation", kind=de.KIND_CAPABILITY,
            positive=("validate skills", "audit systems", "validate consistency", "skills consistency"),
            negative=("package zip", "bundle distribution", "translate french", "debug react"),
            min_precision=None, min_recall=None, source_path="/c.json",
        )

    def _opts(self) -> dict:
        return {"min_precision": 0.85, "min_recall": 0.85}

    def test_perfect_predictions_pass(self) -> None:
        corpus = self._corpus_obj()
        tasks, _ = de.build_tasks([corpus], self.candidates)
        predictions = {
            t.id: ("validation" if t.label == de.LABEL_POSITIVE else None)
            for t in tasks
        }
        report = de.evaluate_with_predictions(
            [corpus], self.candidates, predictions, self._opts(),
        )
        self.assertTrue(report.success)
        self.assertEqual(report.targets[0].metrics.tp, 4)

    def test_stale_prediction_id_warns(self) -> None:
        corpus = self._corpus_obj()
        tasks, _ = de.build_tasks([corpus], self.candidates)
        predictions = {t.id: None for t in tasks}
        predictions["validation:capability:positive:99"] = "validation"
        report = de.evaluate_with_predictions(
            [corpus], self.candidates, predictions, self._opts(),
        )
        self.assertTrue(any("matches no task" in e for e in report.errors))

    def test_missing_target_still_fails_via_evaluate(self) -> None:
        corpus = de.Corpus(
            target="ghost", kind=de.KIND_CAPABILITY,
            positive=("a", "b", "c", "d"), negative=("e", "f", "g", "h"),
            min_precision=None, min_recall=None, source_path="/c.json",
        )
        report = de.evaluate_with_predictions(
            [corpus], self.candidates, {}, self._opts(),
        )
        self.assertFalse(report.success)
        self.assertTrue(any("was not found" in e for e in report.errors))

    def test_heuristic_predictions_round_trip_matches_heuristic_metrics(self) -> None:
        # Feeding emit_heuristic_predictions output back through
        # evaluate_with_predictions must reproduce heuristic-mode metrics.
        corpus_path = self._valid_corpus()
        corpus, _ = de.load_corpus(corpus_path)
        out = os.path.join(self.root, "h.predictions.json")
        de.emit_heuristic_predictions([corpus_path], self.candidates, out)
        predictions = self._read(out)
        via_predictions = de.evaluate_with_predictions(
            [corpus], self.candidates, predictions, self._opts(),
        )
        via_heuristic = de.evaluate([corpus], self.candidates, self._opts())
        self.assertEqual(
            via_predictions.targets[0].metrics, via_heuristic.targets[0].metrics,
        )


if __name__ == "__main__":
    unittest.main()
