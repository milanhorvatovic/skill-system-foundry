"""Tests for lib.audit_coverage — audit-level corpus-coverage rules.

Covers the five rules (missing corpus, stale allow-list, freshness, sibling
parity, size escalation), the identity / path helpers, and the orchestrator's
self-skip behaviour when the corpus root is absent.
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
from lib import audit_coverage as ac
from lib import description_eval as de
from lib.constants import LEVEL_FAIL, LEVEL_INFO, LEVEL_WARN


def _prompts(prefix: str, n: int = 8) -> list[str]:
    """N prompts with distinct leading bigrams (no diversity WARN)."""
    return [f"{prefix}{i} please handle this case" for i in range(n)]


def _corpus_dict(target: str, kind: str, n: int = 8) -> dict:
    return {
        "target": target,
        "kind": kind,
        "positive": _prompts(f"pos-{target}-", n),
        "negative": _prompts(f"neg-{target}-", n),
    }


# ===================================================================
# Fixture
# ===================================================================


class CoverageBaseMixin(unittest.TestCase):
    """A skill 'demo' with capabilities 'alpha' and 'beta' plus a corpus root."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.skill_root = os.path.join(self._tmp.name, "demo")
        helpers.write_skill_md(
            self.skill_root, name="demo",
            description="Designs and audits demo skill systems when asked",
            body="# Demo\n",
        )
        helpers.write_capability_md(
            self.skill_root, "alpha", body="# Alpha\n\nalpha capability description\n",
        )
        helpers.write_capability_md(
            self.skill_root, "beta", body="# Beta\n\nbeta capability description\n",
        )
        # Corpus root resolvable by the orchestrator: <skill_root>/tests/skill-corpus
        self.corpus_root = os.path.join(self.skill_root, "tests", "skill-corpus")
        self.units = de.discover_units(self.skill_root)
        self.by_qual = {ac.unit_qualified_name(u): u for u in self.units}

    def _write_corpus(self, unit: de.Unit, data: dict | None = None) -> str:
        rel = ac.expected_corpus_relpath(unit)
        path = os.path.join(self.corpus_root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if data is None:
            kind = (
                de.KIND_CAPABILITY if unit.kind == de.KIND_CAPABILITY
                else de.KIND_SKILL
            )
            data = _corpus_dict(unit.name, kind)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
        return path

    def _write_all(self) -> None:
        for unit in self.units:
            self._write_corpus(unit)

    def _loaded(self) -> "ac.LoadedCorpora":
        """The shared single-read corpus cache the rules now consume."""
        return ac.load_present_corpora(self.units, self.corpus_root)


# ===================================================================
# Identity + path helpers
# ===================================================================


class HelperTests(CoverageBaseMixin):
    def test_qualified_name_skill_is_bare_name(self) -> None:
        self.assertEqual(ac.unit_qualified_name(self.by_qual["demo"]), "demo")

    def test_qualified_name_capability_is_scoped(self) -> None:
        cap = self.by_qual["demo/capabilities/alpha"]
        self.assertEqual(
            ac.unit_qualified_name(cap), "demo/capabilities/alpha"
        )

    def test_expected_relpath_skill(self) -> None:
        self.assertEqual(
            ac.expected_corpus_relpath(self.by_qual["demo"]), "demo/skill.json"
        )

    def test_expected_relpath_capability(self) -> None:
        cap = self.by_qual["demo/capabilities/alpha"]
        self.assertEqual(
            ac.expected_corpus_relpath(cap), "demo/capabilities/alpha.json"
        )

    def test_resolve_corpus_root_joins_relative_to_system_root(self) -> None:
        root = ac.resolve_corpus_root(self.skill_root)
        self.assertEqual(root, os.path.abspath(self.corpus_root))


# ===================================================================
# Identity safety (path-traversal guard)
# ===================================================================


class IdentitySafetyTests(CoverageBaseMixin):
    def test_plain_names_are_safe(self) -> None:
        for unit in self.units:
            self.assertTrue(ac._has_safe_corpus_identity(unit))

    def test_separator_in_name_is_unsafe(self) -> None:
        evil = de.Unit(
            name="../../etc/secrets", kind=de.KIND_SKILL,
            description="x", path="x",
        )
        self.assertFalse(ac._has_safe_corpus_identity(evil))

    def test_dotdot_parent_is_unsafe(self) -> None:
        evil = de.Unit(
            name="cap", kind=de.KIND_CAPABILITY,
            description="x", path="x", parent="..",
        )
        self.assertFalse(ac._has_safe_corpus_identity(evil))

    def test_drive_letter_name_is_unsafe(self) -> None:
        # "D:escape" has no separator and is not "..", but os.path.join
        # resolves it to a drive-relative path on Windows, escaping the
        # corpus root.  The guard must reject it like constants.py does.
        evil = de.Unit(
            name="D:escape", kind=de.KIND_SKILL, description="x", path="x",
        )
        self.assertFalse(ac._has_safe_corpus_identity(evil))

    def test_drive_letter_parent_is_unsafe(self) -> None:
        evil = de.Unit(
            name="cap", kind=de.KIND_CAPABILITY,
            description="x", path="x", parent="C:evil",
        )
        self.assertFalse(ac._has_safe_corpus_identity(evil))

    def test_loader_never_reads_outside_corpus_root(self) -> None:
        # Plant a file where a "../escape" traversal would resolve; the unsafe
        # unit must be skipped, never probed or read.
        outside = os.path.join(self.corpus_root, "..", "escape", "skill.json")
        os.makedirs(os.path.dirname(outside), exist_ok=True)
        with open(outside, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("{}\n")
        evil = de.Unit(
            name="../escape", kind=de.KIND_SKILL, description="x", path="x",
        )
        loaded = ac.load_present_corpora([evil], self.corpus_root)
        self.assertEqual(loaded, {})

    def test_missing_rule_warns_on_unsafe_name(self) -> None:
        evil = de.Unit(
            name="../escape", kind=de.KIND_SKILL, description="x", path="x",
        )
        findings = ac.find_missing_corpora([evil], [], {})
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith(LEVEL_WARN))
        self.assertIn("path separator", findings[0])


# ===================================================================
# Rule 1 — Missing corpus
# ===================================================================


class MissingCorpusTests(CoverageBaseMixin):
    def test_all_present_no_findings(self) -> None:
        self._write_all()
        findings = ac.find_missing_corpora(self.units, [], self._loaded())
        self.assertEqual(findings, [])

    def test_missing_corpus_warns_per_unit(self) -> None:
        # Only the skill corpus exists; both capabilities are missing.
        self._write_corpus(self.by_qual["demo"])
        findings = ac.find_missing_corpora(self.units, [], self._loaded())
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(f.startswith(LEVEL_WARN) for f in findings))
        self.assertTrue(any("demo/capabilities/alpha" in f for f in findings))

    def test_allow_listed_unit_suppressed(self) -> None:
        self._write_corpus(self.by_qual["demo"])
        self._write_corpus(self.by_qual["demo/capabilities/beta"])
        findings = ac.find_missing_corpora(
            self.units, ["demo/capabilities/alpha"], self._loaded()
        )
        self.assertEqual(findings, [])

    def test_mismatched_target_is_not_coverage(self) -> None:
        # A corpus exists at the expected path but its target/kind names a
        # different unit — no effective coverage, so the unit is still missing.
        unit = self.by_qual["demo"]
        self._write_corpus(unit, _corpus_dict("someone-else", de.KIND_SKILL))
        findings = ac.find_missing_corpora([unit], [], self._loaded())
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith(LEVEL_WARN))
        self.assertIn("targets a different unit", findings[0])

    def test_present_but_unloadable_not_reported_missing(self) -> None:
        # A present corpus that failed to load is the size rule's concern (it
        # owns the load FAIL); the missing rule must not double-report it.
        unit = self.by_qual["demo"]
        loaded = {unit: (None, [f"{LEVEL_FAIL}: [foundry] x: broken"])}
        findings = ac.find_missing_corpora([unit], [], loaded)
        self.assertEqual(findings, [])


# ===================================================================
# Rule 2 — Stale allow-list entry
# ===================================================================


class StaleAllowListTests(CoverageBaseMixin):
    def test_matching_entry_no_finding(self) -> None:
        findings = ac.find_stale_allowed_missing(
            self.units, ["demo/capabilities/alpha"]
        )
        self.assertEqual(findings, [])

    def test_unknown_entry_is_info(self) -> None:
        findings = ac.find_stale_allowed_missing(
            self.units, ["demo/capabilities/ghost"]
        )
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith(LEVEL_INFO))
        self.assertIn("ghost", findings[0])


# ===================================================================
# Rule 3 — Freshness
# ===================================================================


class FreshnessTests(CoverageBaseMixin):
    def test_no_hash_skips(self) -> None:
        self._write_all()  # corpora carry no description_sha256
        findings = ac.find_stale_corpora(self.units, self._loaded())
        self.assertEqual(findings, [])

    def test_matching_hash_no_finding(self) -> None:
        unit = self.by_qual["demo"]
        data = _corpus_dict("demo", de.KIND_SKILL)
        data["description_sha256"] = de.compute_description_sha256(unit.description)
        self._write_corpus(unit, data)
        findings = ac.find_stale_corpora([unit], self._loaded())
        self.assertEqual(findings, [])

    def test_mismatched_hash_warns(self) -> None:
        unit = self.by_qual["demo/capabilities/alpha"]
        data = _corpus_dict("alpha", de.KIND_CAPABILITY)
        data["description_sha256"] = "0" * 64
        self._write_corpus(unit, data)
        findings = ac.find_stale_corpora([unit], self._loaded())
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith(LEVEL_WARN))
        self.assertIn("stale", findings[0])

    def test_mismatched_target_skips_freshness(self) -> None:
        # A hash-bearing corpus that targets a different unit is the missing
        # rule's concern, not freshness — comparing its hash here would be noise.
        unit = self.by_qual["demo"]
        data = _corpus_dict("someone-else", de.KIND_SKILL)
        data["description_sha256"] = "0" * 64
        self._write_corpus(unit, data)
        findings = ac.find_stale_corpora([unit], self._loaded())
        self.assertEqual(findings, [])

    def test_absent_corpus_skips(self) -> None:
        findings = ac.find_stale_corpora(self.units, self._loaded())
        self.assertEqual(findings, [])


# ===================================================================
# Rule 4 — Sibling parity
# ===================================================================


class SiblingParityTests(CoverageBaseMixin):
    def test_all_capabilities_covered_no_finding(self) -> None:
        self._write_all()
        findings = ac.find_sibling_parity_violations(
            self.units, [], self._loaded()
        )
        self.assertEqual(findings, [])

    def test_no_capabilities_covered_no_finding(self) -> None:
        # Only the skill corpus exists; both caps uncovered -> not "mixed".
        self._write_corpus(self.by_qual["demo"])
        findings = ac.find_sibling_parity_violations(
            self.units, [], self._loaded()
        )
        self.assertEqual(findings, [])

    def test_mixed_coverage_warns(self) -> None:
        self._write_corpus(self.by_qual["demo/capabilities/alpha"])
        findings = ac.find_sibling_parity_violations(
            self.units, [], self._loaded()
        )
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith(LEVEL_WARN))
        self.assertIn("demo", findings[0])

    def test_allow_listed_gap_is_neutral(self) -> None:
        self._write_corpus(self.by_qual["demo/capabilities/alpha"])
        findings = ac.find_sibling_parity_violations(
            self.units, ["demo/capabilities/beta"], self._loaded()
        )
        self.assertEqual(findings, [])

    def test_mismatched_capability_counts_as_missing(self) -> None:
        # alpha is effectively covered; beta's file targets a different unit, so
        # it is uncovered -> the skill is in the mixed (parity-violating) state.
        self._write_corpus(self.by_qual["demo/capabilities/alpha"])
        self._write_corpus(
            self.by_qual["demo/capabilities/beta"],
            _corpus_dict("not-beta", de.KIND_CAPABILITY),
        )
        findings = ac.find_sibling_parity_violations(
            self.units, [], self._loaded()
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("sibling parity", findings[0])

    def test_unsafe_capability_is_neutral_for_parity(self) -> None:
        # An unsafe-named capability is neither covered nor missing here (the
        # missing rule surfaces it), so it cannot trip sibling parity.
        good = de.Unit(
            name="alpha", kind=de.KIND_CAPABILITY,
            description="x", path="x", parent="demo",
        )
        evil = de.Unit(
            name="../evil", kind=de.KIND_CAPABILITY,
            description="x", path="x", parent="demo",
        )
        corpus = de.Corpus(
            target="alpha", kind=de.KIND_CAPABILITY,
            positive=("p",) * 8, negative=("n",) * 8,
            min_precision=None, min_recall=None, source_path="x",
        )
        loaded = {good: (corpus, [])}
        findings = ac.find_sibling_parity_violations([good, evil], [], loaded)
        self.assertEqual(findings, [])


# ===================================================================
# Rule 5 — Size escalation
# ===================================================================


class SizeEscalationTests(CoverageBaseMixin):
    def test_at_floor_no_finding(self) -> None:
        self._write_all()  # 8/8 == floor
        findings = ac.find_undersized_corpora(self.units, self._loaded(), 8)
        self.assertEqual(findings, [])

    def test_below_floor_fails(self) -> None:
        unit = self.by_qual["demo/capabilities/alpha"]
        self._write_corpus(unit, _corpus_dict("alpha", de.KIND_CAPABILITY, n=5))
        findings = ac.find_undersized_corpora([unit], self._loaded(), 8)
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith(LEVEL_FAIL))
        self.assertIn("5 prompts", findings[0])

    def test_below_hard_floor_surfaces_load_fail(self) -> None:
        # 3 per side fails to load (< EVAL_MIN_PROMPTS); the load FAIL surfaces.
        unit = self.by_qual["demo/capabilities/beta"]
        self._write_corpus(unit, _corpus_dict("beta", de.KIND_CAPABILITY, n=3))
        findings = ac.find_undersized_corpora([unit], self._loaded(), 8)
        self.assertTrue(any(f.startswith(LEVEL_FAIL) for f in findings))

    def test_load_fail_alongside_corpus_is_not_dropped(self) -> None:
        # Defensive: if load_corpus ever returns a Corpus alongside a FAIL,
        # the size rule must still surface that FAIL (not silently drop it).
        unit = self.by_qual["demo/capabilities/alpha"]
        corpus = de.Corpus(
            target="alpha", kind=de.KIND_CAPABILITY,
            positive=("p",) * 8, negative=("n",) * 8,
            min_precision=None, min_recall=None, source_path="x",
        )
        fail = f"{LEVEL_FAIL}: [foundry] x: forced load failure"
        loaded = {unit: (corpus, [fail])}
        findings = ac.find_undersized_corpora([unit], loaded, 8)
        self.assertIn(fail, findings)


# ===================================================================
# Orchestrator
# ===================================================================


class OrchestratorTests(CoverageBaseMixin):
    def test_absent_corpus_root_self_skips(self) -> None:
        # No corpus written anywhere -> corpus root absent -> [].
        findings = ac.audit_corpus_coverage(self.skill_root)
        self.assertEqual(findings, [])

    def test_clean_full_coverage_no_findings(self) -> None:
        self._write_all()
        findings = ac.audit_corpus_coverage(self.skill_root)
        self.assertEqual(findings, [])

    def test_aggregates_missing_and_parity(self) -> None:
        self._write_corpus(self.by_qual["demo"])
        self._write_corpus(self.by_qual["demo/capabilities/alpha"])
        findings = ac.audit_corpus_coverage(self.skill_root)
        # Missing WARN for beta + a parity WARN for demo.
        self.assertTrue(any("has no corpus" in f for f in findings))
        self.assertTrue(any("sibling parity" in f for f in findings))

    def test_freshness_disabled_skips_rule(self) -> None:
        unit = self.by_qual["demo"]
        for u in self.units:
            self._write_corpus(u)
        # Overwrite the skill corpus with a deliberately stale hash.
        data = _corpus_dict("demo", de.KIND_SKILL)
        data["description_sha256"] = "0" * 64
        self._write_corpus(unit, data)
        with_fresh = ac.audit_corpus_coverage(
            self.skill_root, freshness_enabled=True
        )
        without_fresh = ac.audit_corpus_coverage(
            self.skill_root, freshness_enabled=False
        )
        self.assertTrue(any("stale" in f for f in with_fresh))
        self.assertFalse(any("stale" in f for f in without_fresh))


if __name__ == "__main__":
    unittest.main()
