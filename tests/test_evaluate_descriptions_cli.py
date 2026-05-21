"""CLI smoke tests for scripts/evaluate_descriptions.py.

Exercises the entry point end-to-end via subprocess and in-process: heuristic
pass, --soft on a failing corpus, --json shape, split, and error paths.
"""

import contextlib
import io
import json
import os
import subprocess
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

ENTRY = os.path.join(SCRIPTS_DIR, "evaluate_descriptions.py")

PASS_POSITIVES = [
    "validate skills", "audit systems", "validate consistency", "skills consistency",
    "audit skills", "validate systems", "systems consistency", "audit consistency",
]
PASS_NEGATIVES = [
    "package zip", "bundle distribution", "package bundle", "zip distribution",
    "translate french text", "debug react component", "configure postgres database",
    "render html template",
]
# Off-topic positives that route to neither capability -> recall floor -> a pure
# threshold breach. Deliberately share no prompt with PASS_NEGATIVES so the
# corpus carries no structural FAIL finding (a both-sides prompt would be one),
# keeping --soft's threshold-only suppression the property under test.
FAIL_POSITIVES = [
    "plot a sine wave", "brew fresh coffee", "walk the dog", "paint the fence",
    "book a flight", "water the plants", "knead the dough", "tune the guitar",
]


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    """Invoke evaluate_descriptions.main() in-process so coverage measures it."""
    import evaluate_descriptions as ed

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with (
        mock.patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        try:
            ed.main()
        except SystemExit as exc:
            if exc.code is None:
                code = 0
            elif isinstance(exc.code, int):
                code = exc.code
            else:
                code = 1
    return code, stdout.getvalue(), stderr.getvalue()


class CliBaseMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.skillset = os.path.join(self.root, "skillset")
        helpers.write_skill_md(
            self.skillset, name="foundry", description="Designs skill systems",
            body="# Foundry\n",
        )
        helpers.write_capability_md(
            self.skillset, "validation", allowed_tools="Bash Read",
            body="# Validation\n\nvalidate skills audit systems consistency\n",
        )
        helpers.write_capability_md(
            self.skillset, "bundling", allowed_tools="Bash Read",
            body="# Bundling\n\npackage skill zip bundle distribution\n",
        )
        self.corpus_dir = os.path.join(self.root, "corpus")

    def _write_corpus(self, positives: list[str], negatives: list[str]) -> None:
        path = os.path.join(self.corpus_dir, "validation.json")
        os.makedirs(self.corpus_dir, exist_ok=True)
        data = {
            "target": "validation", "kind": "capability",
            "positive": positives, "negative": negatives,
        }
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, indent=2))

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, ENTRY, *args], capture_output=True, text=True,
        )


class HeuristicCliTests(CliBaseMixin):
    def test_passing_corpus_exits_zero_with_json(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        result = self._run(self.corpus_dir, "--skill-set", self.skillset, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tool"], "evaluate_descriptions")
        self.assertTrue(payload["success"])
        self.assertEqual(payload["targets"][0]["target"], "validation")
        self.assertEqual(payload["targets"][0]["candidate_count"], 2)
        self.assertTrue(payload["targets"][0]["metrics"]["passed"])
        # Categorized stream uses the repo-convention "errors" key, not "findings".
        self.assertIn("errors", payload)
        self.assertNotIn("findings", payload)
        # Effective per-target thresholds are surfaced.
        self.assertIn("thresholds", payload["targets"][0])

    def test_passing_corpus_human_output(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        result = self._run(self.corpus_dir, "--skill-set", self.skillset)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Overall: PASS", result.stdout)

    def test_failing_corpus_exits_one(self) -> None:
        self._write_corpus(FAIL_POSITIVES, PASS_NEGATIVES)
        result = self._run(self.corpus_dir, "--skill-set", self.skillset, "--json")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["success"])

    def test_soft_flips_failing_exit_to_zero(self) -> None:
        self._write_corpus(FAIL_POSITIVES, PASS_NEGATIVES)
        result = self._run(
            self.corpus_dir, "--skill-set", self.skillset, "--soft", "--json",
        )
        self.assertEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)["success"])

    def test_missing_corpus_path_errors(self) -> None:
        result = self._run(
            os.path.join(self.root, "nope"), "--skill-set", self.skillset, "--json",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("error", json.loads(result.stdout))


class InProcessCliTests(CliBaseMixin):
    """In-process main() coverage mirroring the subprocess scenarios."""

    def _argv(self, *extra: str) -> list[str]:
        return ["evaluate_descriptions.py", self.corpus_dir, "--skill-set", self.skillset, *extra]

    def test_no_args_prints_doc(self) -> None:
        code, out, _err = _run_main(["evaluate_descriptions.py"])
        self.assertEqual(code, 1)
        self.assertIn("Evaluate skill", out)

    def test_pass_json(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, out, _err = _run_main(self._argv("--json"))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["success"])

    def test_pass_human_verbose(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, out, _err = _run_main(self._argv("--verbose"))
        self.assertEqual(code, 0)
        self.assertIn("Overall: PASS", out)

    def test_fail_then_soft(self) -> None:
        self._write_corpus(FAIL_POSITIVES, PASS_NEGATIVES)
        code, _out, _err = _run_main(self._argv("--json"))
        self.assertEqual(code, 1)
        soft_code, soft_out, _serr = _run_main(self._argv("--soft", "--json"))
        self.assertEqual(soft_code, 0)
        self.assertFalse(json.loads(soft_out)["success"])

    def _write_raw_corpus(self, content: str, name: str) -> None:
        os.makedirs(self.corpus_dir, exist_ok=True)
        with open(
            os.path.join(self.corpus_dir, name), "w", encoding="utf-8", newline="\n",
        ) as handle:
            handle.write(content)

    def test_soft_does_not_swallow_evaluate_fail(self) -> None:
        # A schema-valid corpus whose target is not among the discovered units
        # produces a FAIL finding. --soft suppresses threshold breaches only, so
        # the FAIL must still drive a non-zero exit (a stale self-corpus must
        # not pass CI green).
        data = {
            "target": "ghost", "kind": "capability",
            "positive": PASS_POSITIVES, "negative": PASS_NEGATIVES,
        }
        self._write_raw_corpus(json.dumps(data, indent=2), "ghost.json")
        code, out, _err = _run_main(self._argv("--soft", "--json"))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["success"])

    def test_soft_does_not_swallow_load_corpus_fail(self) -> None:
        # A malformed corpus FAILs at load time; --soft must not mask it.
        self._write_raw_corpus("{ not json ]", "broken.json")
        code, out, _err = _run_main(self._argv("--soft", "--json"))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["success"])

    def test_missing_corpus_errors(self) -> None:
        code, out, _err = _run_main(
            ["evaluate_descriptions.py", os.path.join(self.root, "nope"),
             "--skill-set", self.skillset, "--json"]
        )
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(out))

    def test_single_corpus_file_path(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        corpus_file = os.path.join(self.corpus_dir, "validation.json")
        code, out, _err = _run_main(
            ["evaluate_descriptions.py", corpus_file, "--skill-set", self.skillset, "--json"]
        )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["success"])

    def test_non_json_files_ignored(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        with open(os.path.join(self.corpus_dir, "README.txt"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write("ignore me")
        code, _out, _err = _run_main(self._argv("--json"))
        self.assertEqual(code, 0)

    def test_human_failing_output(self) -> None:
        self._write_corpus(FAIL_POSITIVES, PASS_NEGATIVES)
        code, out, _err = _run_main(self._argv())
        self.assertEqual(code, 1)
        self.assertIn("Overall: FAIL", out)

    def test_human_error_path_without_json(self) -> None:
        code, out, _err = _run_main(
            ["evaluate_descriptions.py", os.path.join(self.root, "nope"),
             "--skill-set", self.skillset]
        )
        self.assertEqual(code, 1)
        self.assertIn("no corpus JSON", out)

    def test_warn_finding_is_printed(self) -> None:
        self._write_corpus(PASS_POSITIVES[:5], PASS_NEGATIVES)
        code, out, _err = _run_main(self._argv())
        self.assertEqual(code, 0)
        self.assertIn("Overall: PASS", out)
        self.assertIn("recommended", out)

    def test_verbose_shows_pairwise(self) -> None:
        # One positive uses bundling vocabulary, so it misroutes to the sibling
        # 'bundling' capability -> pairwise confusion is non-empty.
        positives = PASS_POSITIVES[:7] + ["package zip bundle distribution archive"]
        self._write_corpus(positives, PASS_NEGATIVES)
        code, out, _err = _run_main(self._argv("--verbose", "--soft"))
        self.assertIn("confused with", out)

    def test_out_of_range_min_precision_errors(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, out, _err = _run_main(self._argv("--min-precision", "-1", "--json"))
        self.assertEqual(code, 1)
        self.assertIn("between 0 and 1", json.loads(out)["error"])

    def test_invalid_arg_emits_json_error(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, out, _err = _run_main(self._argv("--min-precision", "notafloat", "--json"))
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertFalse(payload["success"])
        self.assertIn("error", payload)

    def test_invalid_arg_human_error(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, _out, err = _run_main(self._argv("--min-precision", "notafloat"))
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_flag_abbreviation_disabled(self) -> None:
        # allow_abbrev=False: --js is not accepted as --json, so the pre-parse
        # scan and parsed value cannot diverge at parse time.
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, _out, err = _run_main(self._argv("--min-precision", "0.9", "--js"))
        self.assertEqual(code, 1)
        self.assertIn("unrecognized arguments", err)


# ===================================================================
# --backfill-hash
# ===================================================================


class BackfillHashCliTests(CliBaseMixin):
    """The --backfill-hash write mode: idempotent, header-preserving."""

    def _corpus_path(self) -> str:
        return os.path.join(self.corpus_dir, "validation.json")

    def _read(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_backfill_writes_expected_hash(self) -> None:
        from lib.description_eval import compute_description_sha256

        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, out, err = _run_main(
            [ENTRY, self.corpus_dir, "--skill-set", self.skillset, "--backfill-hash"]
        )
        self.assertEqual(code, 0, err)
        self.assertIn("updated", out)
        # The "validation" capability's description is its first body paragraph.
        expected = compute_description_sha256(
            "validate skills audit systems consistency"
        )
        self.assertEqual(
            self._read(self._corpus_path())["description_sha256"], expected
        )

    def test_backfill_is_idempotent(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        argv = [ENTRY, self.corpus_dir, "--skill-set", self.skillset, "--backfill-hash"]
        _run_main(argv)
        with open(self._corpus_path(), "r", encoding="utf-8") as handle:
            after_first = handle.read()
        code, out, _err = _run_main(argv)
        with open(self._corpus_path(), "r", encoding="utf-8") as handle:
            after_second = handle.read()
        self.assertEqual(code, 0)
        self.assertEqual(after_first, after_second)
        self.assertIn("unchanged", out)

    def test_backfill_preserves_other_keys(self) -> None:
        os.makedirs(self.corpus_dir, exist_ok=True)
        data = {
            "target": "validation", "kind": "capability",
            "_comment": "keep me", "positive": PASS_POSITIVES,
            "negative": PASS_NEGATIVES,
        }
        with open(self._corpus_path(), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
        _run_main(
            [ENTRY, self.corpus_dir, "--skill-set", self.skillset, "--backfill-hash"]
        )
        written = self._read(self._corpus_path())
        self.assertEqual(written["_comment"], "keep me")
        self.assertIn("description_sha256", written)

    def test_backfill_json_shape(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, out, _err = _run_main([
            ENTRY, self.corpus_dir, "--skill-set", self.skillset,
            "--backfill-hash", "--json",
        ])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["mode"], "backfill")
        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["updated"]), 1)
        self.assertEqual(payload["unchanged"], [])

    def test_backfill_unmatched_target_warns_and_skips_write(self) -> None:
        os.makedirs(self.corpus_dir, exist_ok=True)
        data = {
            "target": "ghost", "kind": "capability",
            "positive": PASS_POSITIVES, "negative": PASS_NEGATIVES,
        }
        with open(self._corpus_path(), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, indent=2))
        code, out, _err = _run_main([
            ENTRY, self.corpus_dir, "--skill-set", self.skillset, "--backfill-hash",
        ])
        # Unmatched target is a WARN, not a FAIL — exit stays 0.
        self.assertEqual(code, 0)
        self.assertIn("not found", out)
        self.assertNotIn("description_sha256", self._read(self._corpus_path()))


# ===================================================================
# Agent-delegated modes: --emit-tasks / --emit-heuristic-predictions / --predictions
# ===================================================================


class AgentDelegatedCliTests(CliBaseMixin):
    """Two-phase agent mode end to end, plus the resolve-skip hardening."""

    def _argv(self, *extra: str) -> list[str]:
        return [
            "evaluate_descriptions.py", self.corpus_dir,
            "--skill-set", self.skillset, *extra,
        ]

    def _read(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_raw_corpus(self, content: str, name: str) -> None:
        os.makedirs(self.corpus_dir, exist_ok=True)
        with open(
            os.path.join(self.corpus_dir, name), "w", encoding="utf-8", newline="\n",
        ) as handle:
            handle.write(content)

    def test_emit_tasks_writes_envelope(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        out = os.path.join(self.root, "out.tasks.json")
        code, stdout, _err = _run_main(self._argv("--emit-tasks", out, "--json"))
        self.assertEqual(code, 0, stdout)
        payload = json.loads(stdout)
        self.assertEqual(payload["mode"], "emit-tasks")
        self.assertTrue(payload["success"])
        self.assertEqual(
            payload["task_count"], len(PASS_POSITIVES) + len(PASS_NEGATIVES)
        )
        env = self._read(out)
        self.assertEqual(env["mode"], "emit-tasks")
        self.assertIn("instructions", env)

    def test_emit_tasks_human_output(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        out = os.path.join(self.root, "out.tasks.json")
        code, stdout, _err = _run_main(self._argv("--emit-tasks", out))
        self.assertEqual(code, 0)
        self.assertIn("wrote", stdout)

    def test_emit_tasks_malformed_corpus_exits_one(self) -> None:
        self._write_raw_corpus("{ not json ]", "broken.json")
        out = os.path.join(self.root, "out.tasks.json")
        code, stdout, _err = _run_main(self._argv("--emit-tasks", out, "--json"))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout)["success"])

    def test_emit_tasks_malformed_corpus_human_output(self) -> None:
        self._write_raw_corpus("{ not json ]", "broken.json")
        out = os.path.join(self.root, "out.tasks.json")
        code, stdout, _err = _run_main(self._argv("--emit-tasks", out))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", stdout)
        self.assertNotIn("wrote", stdout)

    def test_emit_heuristic_predictions_writes_map(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        out = os.path.join(self.root, "h.predictions.json")
        code, stdout, _err = _run_main(
            self._argv("--emit-heuristic-predictions", out, "--json")
        )
        self.assertEqual(code, 0, stdout)
        self.assertEqual(json.loads(stdout)["mode"], "emit-heuristic-predictions")
        self.assertEqual(
            len(self._read(out)), len(PASS_POSITIVES) + len(PASS_NEGATIVES)
        )

    def _baseline(self) -> str:
        path = os.path.join(self.root, "h.predictions.json")
        _run_main(self._argv("--emit-heuristic-predictions", path))
        return path

    def test_predictions_scores_and_omits_mode_key(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, stdout, _err = _run_main(
            self._argv("--predictions", self._baseline(), "--json")
        )
        self.assertEqual(code, 0, stdout)
        payload = json.loads(stdout)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["targets"][0]["target"], "validation")
        # Predictions reuse the report shape verbatim — no emit-style mode key.
        self.assertNotIn("mode", payload)

    def test_predictions_json_keys_match_heuristic(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        baseline = self._baseline()
        _code, heuristic_out, _e = _run_main(self._argv("--json"))
        _code, pred_out, _e2 = _run_main(self._argv("--predictions", baseline, "--json"))
        self.assertEqual(set(json.loads(heuristic_out)), set(json.loads(pred_out)))

    def test_predictions_human_output(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, stdout, _err = _run_main(self._argv("--predictions", self._baseline()))
        self.assertEqual(code, 0)
        self.assertIn("Overall: PASS", stdout)

    def test_predictions_unknown_name_fails_under_soft(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        tasks_out = os.path.join(self.root, "out.tasks.json")
        _run_main(self._argv("--emit-tasks", tasks_out))
        env = self._read(tasks_out)
        bad = {task["id"]: "ghost-unit" for task in env["tasks"]}
        bad_path = os.path.join(self.root, "bad.predictions.json")
        with open(bad_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(bad))
        code, stdout, _err = _run_main(
            self._argv("--predictions", bad_path, "--soft", "--json")
        )
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout)["success"])

    def test_predictions_missing_file_fails(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, stdout, _err = _run_main(
            self._argv(
                "--predictions", os.path.join(self.root, "nope.predictions.json"),
                "--json",
            )
        )
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout)["success"])

    def test_modes_are_mutually_exclusive(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, stdout, _err = _run_main(
            self._argv(
                "--emit-tasks", os.path.join(self.root, "x.tasks.json"),
                "--backfill-hash", "--json",
            )
        )
        self.assertEqual(code, 1)
        self.assertIn("mutually exclusive", json.loads(stdout)["error"])

    def test_run_artifacts_in_corpus_dir_are_skipped(self) -> None:
        # A leftover tasks / predictions file in the corpus dir must not be
        # loaded as a corpus (which would FAIL on its unknown keys).
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        self._write_raw_corpus(json.dumps({"x": None}), "leftover.predictions.json")
        self._write_raw_corpus(
            json.dumps({"tool": "evaluate_descriptions", "tasks": []}),
            "leftover.tasks.json",
        )
        code, stdout, _err = _run_main(self._argv("--json"))
        self.assertEqual(code, 0, stdout)
        self.assertTrue(json.loads(stdout)["success"])


if __name__ == "__main__":
    unittest.main()
