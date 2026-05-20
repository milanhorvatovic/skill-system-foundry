"""CLI smoke tests for scripts/evaluate_descriptions.py (step 15).

Exercises the entry point end-to-end via subprocess: heuristic pass, --soft on a
failing corpus, --json shape, error paths, and the missing-API-key path.
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

PASS_POSITIVES = [
    "validate skills", "audit systems", "validate consistency", "skills consistency",
    "audit skills", "validate systems", "systems consistency", "audit consistency",
]
PASS_NEGATIVES = [
    "package zip", "bundle distribution", "package bundle", "zip distribution",
    "translate french text", "debug react component", "configure postgres database",
    "render html template",
]
FAIL_POSITIVES = [
    "translate french text", "debug react component", "configure postgres database",
    "render html template", "plot a sine wave", "brew fresh coffee",
    "walk the dog", "paint the fence",
]


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

    def _run(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, ENTRY, *args],
            capture_output=True, text=True, env=env,
        )


class HeuristicCliTests(CliBaseMixin):
    def test_passing_corpus_exits_zero_with_json(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        result = self._run(self.corpus_dir, "--skill-set", self.skillset, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tool"], "evaluate_descriptions")
        self.assertTrue(payload["success"])
        self.assertEqual(payload["mode"], "heuristic")
        self.assertEqual(payload["targets"][0]["target"], "validation")
        self.assertEqual(payload["targets"][0]["candidate_count"], 2)
        self.assertTrue(payload["targets"][0]["metrics"]["passed"])

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
        # Findings still report the failure honestly.
        self.assertFalse(json.loads(result.stdout)["success"])


class CliErrorPathTests(CliBaseMixin):
    def test_missing_corpus_path_errors(self) -> None:
        result = self._run(
            os.path.join(self.root, "nope"), "--skill-set", self.skillset, "--json",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("error", json.loads(result.stdout))

    def test_llm_without_api_key_errors(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        result = self._run(
            self.corpus_dir, "--skill-set", self.skillset, "--llm", "--json", env=env,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("ANTHROPIC_API_KEY", json.loads(result.stdout)["error"])


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

    def test_split_seed_reports_validation(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        code, out, _err = _run_main(self._argv("--split-seed", "1", "--json"))
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["split"], {"seed": 1, "ratio": 0.6})
        self.assertIsNotNone(payload["targets"][0]["validation_metrics"])

    def test_missing_corpus_errors(self) -> None:
        code, out, _err = _run_main(
            ["evaluate_descriptions.py", os.path.join(self.root, "nope"),
             "--skill-set", self.skillset, "--json"]
        )
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(out))

    def test_llm_with_mocked_client(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        import evaluate_descriptions as ed
        positives = set(PASS_POSITIVES)

        def fake_client(prompt, candidates, model, api_key, endpoint):  # noqa: ANN001
            return "validation" if prompt in positives else "none"

        with (
            mock.patch.dict(ed._CLIENT_DISPATCH, {"anthropic_messages": fake_client}),
            mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
        ):
            code, out, _err = _run_main(self._argv("--llm", "--json"))
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["mode"], "llm")
        self.assertIsInstance(payload["targets"][0]["advisory"]["bootstrap_ci"], dict)

    def test_llm_missing_key_errors(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            code, out, _err = _run_main(self._argv("--llm", "--json"))
        self.assertEqual(code, 1)
        self.assertIn("ANTHROPIC_API_KEY", json.loads(out)["error"])

    def test_unknown_provider_errors(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            code, out, _err = _run_main(self._argv("--llm", "--provider", "ghost", "--json"))
        self.assertEqual(code, 1)
        self.assertIn("unknown provider", json.loads(out)["error"])

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
        # Five positives -> rule 5 WARN, but the gate still passes.
        self._write_corpus(PASS_POSITIVES[:5], PASS_NEGATIVES)
        code, out, _err = _run_main(self._argv())
        self.assertEqual(code, 0)
        self.assertIn("Overall: PASS", out)
        self.assertIn("recommended", out)

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

    def test_llm_verbose_flags_unstable(self) -> None:
        self._write_corpus(PASS_POSITIVES, PASS_NEGATIVES)
        import evaluate_descriptions as ed
        state = {"i": 0}

        def flaky(prompt, candidates, model, api_key, endpoint):  # noqa: ANN001
            index = state["i"]
            state["i"] += 1
            return "validation" if index % 3 != 2 else "none"  # 2-of-3 -> rate 0.67

        with (
            mock.patch.dict(ed._CLIENT_DISPATCH, {"anthropic_messages": flaky}),
            mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}),
        ):
            _code, out, _err = _run_main(self._argv("--llm", "--verbose", "--soft"))
        self.assertIn("unstable prompts", out)


if __name__ == "__main__":
    unittest.main()
