"""Tests for lib.description_eval — corpus loader and shape rules (step 4).

Covers the 12 corpus-shape rules: required keys, types, unknown keys, per-side
counts (FAIL < 4, WARN 4-7), duplicates, empty prompts, pos/neg contradiction,
cross-target overlap, phrasing diversity, length cap, and control characters.
"""

import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error

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


def _unit(name: str, description: str) -> de.Unit:
    return de.Unit(
        name=name, kind=de.KIND_CAPABILITY, description=description, path=f"/{name}",
    )


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


class SplitTrainValidationTests(unittest.TestCase):
    def _corpus(self) -> de.Corpus:
        return de.Corpus(
            target="skill-design", kind=de.KIND_CAPABILITY,
            positive=tuple(f"pos {i}" for i in range(10)),
            negative=tuple(f"neg {i}" for i in range(10)),
            min_precision=0.9, min_recall=0.8, source_path="/x.json",
        )

    def test_split_is_deterministic_for_same_seed(self) -> None:
        corpus = self._corpus()
        first = de.split_train_validation(corpus, 0.6, seed=7)
        second = de.split_train_validation(corpus, 0.6, seed=7)
        self.assertEqual(first, second)

    def test_split_preserves_stratification_and_counts(self) -> None:
        corpus = self._corpus()
        train, validation = de.split_train_validation(corpus, 0.6, seed=7)
        # 60% train of 10 -> 6 train / 4 validation, per side.
        self.assertEqual(len(train.positive), 6)
        self.assertEqual(len(validation.positive), 4)
        self.assertEqual(len(train.negative), 6)
        self.assertEqual(len(validation.negative), 4)
        # No prompt is lost or duplicated across halves.
        self.assertEqual(
            set(train.positive) | set(validation.positive), set(corpus.positive),
        )
        self.assertEqual(
            len(train.positive) + len(validation.positive), len(corpus.positive),
        )

    def test_split_carries_metadata(self) -> None:
        corpus = self._corpus()
        train, validation = de.split_train_validation(corpus, 0.6, seed=1)
        for half in (train, validation):
            self.assertEqual(half.target, "skill-design")
            self.assertEqual(half.kind, de.KIND_CAPABILITY)
            self.assertEqual(half.min_precision, 0.9)
            self.assertEqual(half.min_recall, 0.8)


def _scored(label: str, prediction: str | None, count: int) -> list[de.ScoredQuery]:
    return [
        de.ScoredQuery(
            prompt=f"{label}-{i}", label=label, prediction=prediction,
            trigger_rate=None, runs=1,
        )
        for i in range(count)
    ]


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
        # Only negatives, all correctly rejected: TP+FP == 0 and TP+FN == 0.
        metrics = de.aggregate(_scored(de.LABEL_NEGATIVE, None, 4), "x", 0.85, 0.85)
        self.assertEqual(metrics.precision, 1.0)
        self.assertEqual(metrics.recall, 1.0)
        self.assertTrue(metrics.passed)

    def test_threshold_gates_on_precision(self) -> None:
        # 4 TP, 1 FP -> precision 0.8 < 0.85 -> fail even with full recall.
        scored = (
            _scored(de.LABEL_POSITIVE, "skill-design", 4)
            + _scored(de.LABEL_NEGATIVE, "skill-design", 1)
            + _scored(de.LABEL_NEGATIVE, None, 3)
        )
        metrics = de.aggregate(scored, "skill-design", 0.85, 0.85)
        self.assertAlmostEqual(metrics.precision, 0.8)
        self.assertEqual(metrics.recall, 1.0)
        self.assertFalse(metrics.passed)


class _FakeResponse:
    """Minimal context-manager stand-in for urllib's urlopen return value."""

    def __init__(self, payload: object = None, raw: str | None = None) -> None:
        if raw is not None:
            self._data = raw.encode("utf-8")
        else:
            self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class BuildClassifierPromptTests(unittest.TestCase):
    def test_lists_candidates_none_and_request(self) -> None:
        candidates = [_unit("validation", "Validate skills"), _unit("bundling", "Package as zip")]
        text = de.build_classifier_prompt("audit my skills", candidates)
        self.assertIn("- validation: Validate skills", text)
        self.assertIn("- bundling: Package as zip", text)
        self.assertIn("- none:", text)
        self.assertIn("User request: audit my skills", text)

    def test_missing_description_uses_placeholder(self) -> None:
        text = de.build_classifier_prompt("x", [_unit("empty", "")])
        self.assertIn("- empty: (no description)", text)


class AnthropicMessagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [_unit("validation", "Validate skills")]

    def _call(self) -> str:
        return de._anthropic_messages(
            "audit", self.candidates, "model-x", "key", "https://api/messages",
        )

    def test_success_returns_first_nonblank_line(self) -> None:
        response = _FakeResponse({"content": [{"type": "text", "text": "\nvalidation\n"}]})
        with unittest.mock.patch.object(de.urllib.request, "urlopen", return_value=response):
            self.assertEqual(self._call(), "validation")

    def test_http_error_raises_runtime_error_with_status(self) -> None:
        error = urllib.error.HTTPError(
            "https://api/messages", 401, "Unauthorized", {},
            io.BytesIO(b'{"error":"bad key"}'),
        )
        with unittest.mock.patch.object(de.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as ctx:
                self._call()
        self.assertIn("401", str(ctx.exception))

    def test_url_error_raises_runtime_error(self) -> None:
        error = urllib.error.URLError("connection refused")
        with unittest.mock.patch.object(de.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError):
                self._call()

    def test_malformed_json_raises(self) -> None:
        with unittest.mock.patch.object(
            de.urllib.request, "urlopen", return_value=_FakeResponse(raw="{ not json"),
        ):
            with self.assertRaises(RuntimeError):
                self._call()

    def test_missing_content_key_raises(self) -> None:
        with unittest.mock.patch.object(
            de.urllib.request, "urlopen", return_value=_FakeResponse({"unexpected": "shape"}),
        ):
            with self.assertRaises(RuntimeError):
                self._call()


class _ScriptedClient:
    """Returns queued answers in order; repeats the last when exhausted."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = answers
        self._index = 0

    def __call__(self, prompt: str, candidates: list) -> str:
        answer = self._answers[min(self._index, len(self._answers) - 1)]
        self._index += 1
        return answer


class ScoreLlmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [_unit("validation", "Validate"), _unit("bundling", "Bundle")]

    def test_target_selected_every_run(self) -> None:
        prediction, rate = de.score_llm(
            "p", "validation", self.candidates, 3, _ScriptedClient(["validation"]),
        )
        self.assertEqual(prediction, "validation")
        self.assertEqual(rate, 1.0)

    def test_none_every_run(self) -> None:
        prediction, rate = de.score_llm(
            "p", "validation", self.candidates, 3, _ScriptedClient(["none"]),
        )
        self.assertIsNone(prediction)
        self.assertEqual(rate, 0.0)

    def test_sibling_majority_predicts_sibling_with_zero_trigger(self) -> None:
        prediction, rate = de.score_llm(
            "p", "validation", self.candidates, 3, _ScriptedClient(["bundling"]),
        )
        self.assertEqual(prediction, "bundling")
        self.assertEqual(rate, 0.0)

    def test_two_of_three_target_is_fp_rate(self) -> None:
        client = _ScriptedClient(["validation", "validation", "none"])
        prediction, rate = de.score_llm("p", "validation", self.candidates, 3, client)
        self.assertEqual(prediction, "validation")
        self.assertAlmostEqual(rate, 2 / 3)

    def test_no_majority_predicts_none(self) -> None:
        client = _ScriptedClient(["validation", "bundling", "none"])
        prediction, rate = de.score_llm("p", "validation", self.candidates, 3, client)
        self.assertIsNone(prediction)
        self.assertAlmostEqual(rate, 1 / 3)

    def test_case_insensitive_and_unknown_answers(self) -> None:
        client = _ScriptedClient(["VALIDATION."])
        prediction, rate = de.score_llm("p", "validation", self.candidates, 1, client)
        self.assertEqual(prediction, "validation")
        self.assertEqual(rate, 1.0)
        unknown = _ScriptedClient(["something-else"])
        prediction, rate = de.score_llm("p", "validation", self.candidates, 1, unknown)
        self.assertIsNone(prediction)
        self.assertEqual(rate, 0.0)


def _q(label: str, prediction: str | None, trigger_rate: float | None) -> de.ScoredQuery:
    return de.ScoredQuery(
        prompt=f"{label}:{prediction}:{trigger_rate}", label=label,
        prediction=prediction, trigger_rate=trigger_rate, runs=3,
    )


class BootstrapConfidenceIntervalTests(unittest.TestCase):
    def _mixed(self) -> list[de.ScoredQuery]:
        return (
            _scored(de.LABEL_POSITIVE, "skill-design", 3)
            + _scored(de.LABEL_POSITIVE, None, 1)
            + _scored(de.LABEL_NEGATIVE, None, 3)
            + _scored(de.LABEL_NEGATIVE, "skill-design", 1)
        )

    def test_deterministic_for_same_input(self) -> None:
        scored = self._mixed()
        first = de.bootstrap_confidence_interval(scored, "skill-design", 200, 0.95)
        second = de.bootstrap_confidence_interval(scored, "skill-design", 200, 0.95)
        self.assertEqual(first, second)

    def test_bounds_are_ordered_and_in_range(self) -> None:
        result = de.bootstrap_confidence_interval(self._mixed(), "skill-design", 200, 0.95)
        for key in ("precision", "recall"):
            low, high = result[key]
            self.assertLessEqual(0.0, low)
            self.assertLessEqual(low, high)
            self.assertLessEqual(high, 1.0)

    def test_empty_scored_returns_unit_bounds(self) -> None:
        result = de.bootstrap_confidence_interval([], "skill-design", 200, 0.95)
        self.assertEqual(result["precision"], [1.0, 1.0])
        self.assertEqual(result["recall"], [1.0, 1.0])


class FlagUnstableQueriesTests(unittest.TestCase):
    def test_flags_only_in_window_and_skips_none(self) -> None:
        scored = [
            _q(de.LABEL_POSITIVE, "skill-design", 1.0),   # stable, out of window
            _q(de.LABEL_POSITIVE, "skill-design", 0.5),   # in window
            _q(de.LABEL_NEGATIVE, None, 0.33),            # in window
            _q(de.LABEL_NEGATIVE, None, None),            # heuristic mode, skipped
        ]
        flagged = de.flag_unstable_queries(scored, 0.3, 0.7)
        self.assertEqual(len(flagged), 2)
        self.assertIn(scored[1].prompt, flagged)
        self.assertIn(scored[2].prompt, flagged)


class PairwiseConfusionTests(unittest.TestCase):
    def test_counts_only_wrong_units(self) -> None:
        scored = [
            _q(de.LABEL_POSITIVE, "skill-design", 1.0),   # correct, ignored
            _q(de.LABEL_NEGATIVE, None, 0.0),             # none, ignored
            _q(de.LABEL_NEGATIVE, "bundling", 0.0),       # wrong unit
            _q(de.LABEL_POSITIVE, "bundling", 0.2),       # wrong unit
            _q(de.LABEL_NEGATIVE, "validation", 0.0),     # wrong unit
        ]
        self.assertEqual(
            de.pairwise_confusion(scored, "skill-design"),
            {"bundling": 2, "validation": 1},
        )


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
        base = {
            "runs": 3, "min_precision": 0.85, "min_recall": 0.85,
            "split_seed": None, "ratio": 0.6,
        }
        base.update(overrides)
        return base

    def test_heuristic_capability_eval_passes(self) -> None:
        report = de.evaluate(
            [self._corpus()], self.candidates, de.MODE_HEURISTIC, self._opts(),
        )
        self.assertTrue(report.success)
        result = report.targets[0]
        # Capability target competes only with sibling capabilities (not the skill).
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.metrics.tp, 4)
        self.assertEqual(result.metrics.fp, 0)
        self.assertTrue(result.metrics.passed)
        # Heuristic mode: no bootstrap CI, no variance flags.
        self.assertIsNone(result.advisory["bootstrap_ci"])
        self.assertEqual(result.advisory["unstable_queries"], [])
        # Negatives that picked bundling are recorded as pairwise confusion.
        self.assertEqual(result.advisory["pairwise_confusion"], {"bundling": 2})

    def test_missing_target_records_fail(self) -> None:
        report = de.evaluate(
            [self._corpus(target="ghost")], self.candidates,
            de.MODE_HEURISTIC, self._opts(),
        )
        self.assertFalse(report.success)
        self.assertEqual(report.targets, [])
        self.assertTrue(any("was not found" in e for e in report.errors))

    def test_llm_mode_produces_bootstrap_ci(self) -> None:
        positives = set(self.positive)

        def client(prompt: str, candidates: list) -> str:
            return "validation" if prompt in positives else "none"

        report = de.evaluate(
            [self._corpus()], self.candidates, de.MODE_LLM,
            self._opts(client_fn=client, provider="anthropic", model="m"),
        )
        self.assertEqual(report.mode, "llm")
        result = report.targets[0]
        self.assertTrue(result.metrics.passed)
        self.assertIsInstance(result.advisory["bootstrap_ci"], dict)
        self.assertIn("precision", result.advisory["bootstrap_ci"])

    def test_split_uses_validation_half_as_gate(self) -> None:
        report = de.evaluate(
            [self._corpus()], self.candidates, de.MODE_HEURISTIC,
            self._opts(split_seed=1),
        )
        result = report.targets[0]
        self.assertIsNotNone(result.validation_metrics)
        self.assertEqual(report.split, {"seed": 1, "ratio": 0.6})
        self.assertIs(result.gate_metrics, result.validation_metrics)

    def test_skill_target_competes_with_skills(self) -> None:
        other = de.Unit("other", de.KIND_SKILL, "unrelated skill", "/o")
        candidates = self.candidates + [other]
        report = de.evaluate(
            [self._corpus(target="foundry", kind=de.KIND_SKILL)],
            candidates, de.MODE_HEURISTIC, self._opts(),
        )
        # Two skills discovered (foundry, other); capabilities excluded.
        self.assertEqual(report.targets[0].candidate_count, 2)


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


if __name__ == "__main__":
    unittest.main()
