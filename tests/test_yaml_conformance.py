"""End-to-end YAML 1.2.2 conformance harness.

Imports helpers from ``tests/lib/yaml_conformance_runner.py`` and runs
them against the real corpus under ``tests/fixtures/yaml-conformance/``.

Failures surface per case so the unittest output names the offending
fixture instead of dumping the whole summary.
"""

import os
import sys
import unittest

_TESTS_LIB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "lib")
)
if _TESTS_LIB_DIR not in sys.path:
    sys.path.insert(0, _TESTS_LIB_DIR)

import yaml_conformance_runner as runner  # noqa: E402

_CORPUS_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures", "yaml-conformance")
)


class CorpusLayoutTests(unittest.TestCase):
    """Three-bucket layout (G100) and required infrastructure files."""

    def test_corpus_root_exists(self) -> None:
        self.assertTrue(
            os.path.isdir(_CORPUS_ROOT),
            f"corpus root missing: {_CORPUS_ROOT}",
        )

    def test_required_top_level_files(self) -> None:
        for name in ("LICENSE", "README.md", "digests.txt"):
            self.assertTrue(
                os.path.isfile(os.path.join(_CORPUS_ROOT, name)),
                f"corpus missing required file: {name}",
            )

    def test_only_recognized_buckets_present(self) -> None:
        unexpected = [
            entry
            for entry in sorted(os.listdir(_CORPUS_ROOT))
            if os.path.isdir(os.path.join(_CORPUS_ROOT, entry))
            and entry not in runner.BUCKETS
        ]
        self.assertEqual(unexpected, [])

    def test_discover_does_not_raise(self) -> None:
        # ``discover_fixtures`` enforces sidecar discipline and bucket
        # layout — surfacing any structural issue as a ValueError.
        runner.discover_fixtures(_CORPUS_ROOT)


class CorpusRunPerCaseTests(unittest.TestCase):
    """One subTest per logical case with a focused failure message."""

    def test_corpus_runs_clean(self) -> None:
        digests_path = os.path.join(_CORPUS_ROOT, "digests.txt")
        with open(digests_path, "r", encoding="utf-8") as fh:
            digests = runner.parse_digests_file(fh.read())
        cases_by_bucket = runner.discover_fixtures(_CORPUS_ROOT)
        for bucket in runner.BUCKETS:
            for case in cases_by_bucket[bucket]:
                with self.subTest(case=case["base"]):
                    messages = runner.run_case(
                        _CORPUS_ROOT, bucket, case, digests
                    )
                    self.assertEqual(
                        messages, [],
                        f"corpus failure in {case['base']}: {messages}",
                    )


class CorpusSummaryShapeTests(unittest.TestCase):
    """``run_corpus`` returns the pinned summary shape (G127)."""

    def test_summary_keys_and_types(self) -> None:
        summary = runner.run_corpus(_CORPUS_ROOT)
        self.assertEqual(
            set(summary.keys()),
            {"total", "passed", "failed", "failures"},
        )
        for k in ("total", "passed", "failed"):
            self.assertIsInstance(summary[k], int)
        self.assertIsInstance(summary["failures"], list)
        self.assertEqual(
            summary["passed"] + summary["failed"], summary["total"]
        )

    def test_corpus_is_currently_clean(self) -> None:
        summary = runner.run_corpus(_CORPUS_ROOT)
        self.assertEqual(summary["failed"], 0, summary["failures"])
        self.assertGreater(summary["total"], 0)


if __name__ == "__main__":
    unittest.main()
