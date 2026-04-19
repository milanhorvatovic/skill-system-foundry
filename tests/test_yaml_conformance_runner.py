"""Unit tests for ``tests/lib/yaml_conformance_runner.py``.

Synthetic in-memory corpora exercise each helper.  The real corpus is
exercised end-to-end by ``tests/test_yaml_conformance.py``.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

_TESTS_LIB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "lib")
)
if _TESTS_LIB_DIR not in sys.path:
    sys.path.insert(0, _TESTS_LIB_DIR)

import yaml_conformance_runner as runner  # noqa: E402


def _write(path: str, content: bytes | str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    if isinstance(content, str):
        with open(path, mode, encoding="utf-8") as fh:
            fh.write(content)
    else:
        with open(path, mode) as fh:
            fh.write(content)


class _CorpusBuilder:
    """Build a synthetic corpus tree under a temporary directory."""

    def __init__(self) -> None:
        self.root = tempfile.mkdtemp()

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write_variant(self, bucket: str, base: str, suffix: str, text: str) -> str:
        rel = f"{bucket}/{base}{suffix}"
        _write(os.path.join(self.root, rel), text.encode("utf-8"))
        return rel

    def write_sidecar(self, bucket: str, base: str, expected: dict, meta: dict) -> None:
        _write(
            os.path.join(self.root, f"{bucket}/{base}.expected.json"),
            json.dumps(expected),
        )
        _write(
            os.path.join(self.root, f"{bucket}/{base}.meta.json"),
            json.dumps(meta),
        )

    def write_digests(self, contents: str) -> None:
        _write(os.path.join(self.root, "digests.txt"), contents)


class ParseDigestsFileTests(unittest.TestCase):
    """``parse_digests_file`` honours the ``sha256sum`` shape (G40)."""

    def test_simple_two_lines(self) -> None:
        text = "abc  supported/a.lf.yaml\ndef  rejected/b.lf.yaml\n"
        self.assertEqual(
            runner.parse_digests_file(text),
            {
                "supported/a.lf.yaml": "abc",
                "rejected/b.lf.yaml": "def",
            },
        )

    def test_empty_lines_skipped(self) -> None:
        text = "\nabc  a.lf.yaml\n\n"
        self.assertEqual(
            runner.parse_digests_file(text),
            {"a.lf.yaml": "abc"},
        )

    def test_malformed_line_raises(self) -> None:
        with self.assertRaises(ValueError):
            runner.parse_digests_file("no-second-field\n")


class HashFileTests(unittest.TestCase):
    """``hash_file`` returns a stable hex digest."""

    def test_known_bytes(self) -> None:
        b = _CorpusBuilder()
        try:
            path = os.path.join(b.root, "x")
            _write(path, b"abc")
            # SHA-256("abc")
            self.assertEqual(
                runner.hash_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )
        finally:
            b.cleanup()


class DiscoverFixturesTests(unittest.TestCase):
    """``discover_fixtures`` groups variants and detects orphans."""

    def test_groups_by_base_with_sidecars(self) -> None:
        b = _CorpusBuilder()
        try:
            for s in (".lf.yaml", ".crlf.yaml", ".mixed.yaml"):
                b.write_variant("supported", "case-a", s, "key: value\n")
            b.write_sidecar(
                "supported",
                "case-a",
                {"parsed": {"key": "value"}},
                {"origin": "original", "rationale": "smoke"},
            )
            cases = runner.discover_fixtures(b.root)
            self.assertEqual(len(cases["supported"]), 1)
            self.assertEqual(len(cases["divergent"]), 0)
            case = cases["supported"][0]
            self.assertEqual(case["base"], "supported/case-a")
            self.assertEqual(len(case["variants"]), 3)
            self.assertEqual(
                case["expected"], "supported/case-a.expected.json"
            )
            self.assertEqual(case["meta"], "supported/case-a.meta.json")
        finally:
            b.cleanup()

    def test_unknown_bucket_raises(self) -> None:
        b = _CorpusBuilder()
        try:
            os.makedirs(os.path.join(b.root, "rogue"))
            with self.assertRaises(ValueError) as ctx:
                runner.discover_fixtures(b.root)
            self.assertIn("unknown corpus bucket", str(ctx.exception))
        finally:
            b.cleanup()

    def test_orphan_sidecar_raises(self) -> None:
        b = _CorpusBuilder()
        try:
            _write(
                os.path.join(b.root, "supported/missing.expected.json"),
                json.dumps({"parsed": {}}),
            )
            _write(
                os.path.join(b.root, "supported/missing.meta.json"),
                json.dumps({"origin": "original", "rationale": "x"}),
            )
            with self.assertRaises(ValueError) as ctx:
                runner.discover_fixtures(b.root)
            self.assertIn("orphan sidecar", str(ctx.exception))
        finally:
            b.cleanup()

    def test_missing_corpus_root_returns_empty_buckets(self) -> None:
        cases = runner.discover_fixtures("/nonexistent/corpus")
        self.assertEqual(
            cases, {"supported": [], "divergent": [], "rejected": []}
        )


class CheckVariantParseTests(unittest.TestCase):
    """Assertions per bucket — supported / divergent / rejected."""

    def test_supported_clean_pass(self) -> None:
        errs = runner.check_variant_parse(
            "supported", "key: value\n", {"parsed": {"key": "value"}}
        )
        self.assertEqual(errs, [])

    def test_supported_dict_mismatch(self) -> None:
        errs = runner.check_variant_parse(
            "supported", "key: value\n", {"parsed": {"key": "wrong"}}
        )
        self.assertEqual(len(errs), 1)
        self.assertIn("parsed dict mismatch", errs[0])

    def test_supported_unexpected_findings(self) -> None:
        errs = runner.check_variant_parse(
            "supported", "key: *alias\n", {"parsed": {"key": "*alias"}}
        )
        self.assertTrue(any("emitted findings" in e for e in errs))

    def test_divergent_finding_match(self) -> None:
        errs = runner.check_variant_parse(
            "divergent",
            "key: *alias\n",
            {
                "parsed": {"key": "*alias"},
                "findings": [
                    {"severity": "fail", "substring": "alias indicator"}
                ],
            },
        )
        self.assertEqual(errs, [])

    def test_divergent_missing_finding(self) -> None:
        errs = runner.check_variant_parse(
            "divergent",
            "key: value\n",
            {
                "parsed": {"key": "value"},
                "findings": [
                    {"severity": "fail", "substring": "alias indicator"}
                ],
            },
        )
        self.assertTrue(any("missing finding" in e for e in errs))

    def test_rejected_raises_with_substring(self) -> None:
        errs = runner.check_variant_parse(
            "rejected",
            "key: |2\n  text\n",
            {"error_substring": "indent-indicator-block-scalar"},
        )
        self.assertEqual(errs, [])

    def test_rejected_when_parse_succeeds(self) -> None:
        errs = runner.check_variant_parse(
            "rejected", "key: value\n", {"error_substring": "anything"}
        )
        self.assertTrue(any("parse succeeded" in e for e in errs))


class CheckParityTests(unittest.TestCase):
    """Triplet parity asserts byte-different inputs parse identically."""

    def test_lf_crlf_mixed_match(self) -> None:
        text = "key: value\nlist:\n  - a\n  - b\n"
        crlf = text.replace("\n", "\r\n")
        mixed = "key: value\r\nlist:\n  - a\r  - b\n"
        self.assertEqual(
            runner.check_parity([text, crlf, mixed]),
            [],
        )

    def test_mismatch_detected(self) -> None:
        errs = runner.check_parity(["key: a\n", "key: b\n"])
        self.assertEqual(len(errs), 1)


class RunCaseAndCorpusTests(unittest.TestCase):
    """Integration over a synthetic in-memory corpus."""

    def test_supported_case_passes(self) -> None:
        b = _CorpusBuilder()
        try:
            for s, sep in (
                (".lf.yaml", "\n"),
                (".crlf.yaml", "\r\n"),
                (".mixed.yaml", "\n"),
            ):
                b.write_variant(
                    "supported", "k", s, "key: value" + sep
                )
            b.write_sidecar(
                "supported",
                "k",
                {"parsed": {"key": "value"}},
                {"origin": "original", "rationale": "smoke"},
            )
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["total"], 1)
            self.assertEqual(summary["passed"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["failures"], [])
        finally:
            b.cleanup()

    def test_rejected_case_passes(self) -> None:
        b = _CorpusBuilder()
        try:
            b.write_variant(
                "rejected", "indent", ".lf.yaml", "key: |2\n  text\n"
            )
            b.write_sidecar(
                "rejected",
                "indent",
                {"error_substring": "indent-indicator-block-scalar"},
                {"origin": "original", "rationale": "spec gap"},
            )
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["passed"], 1)
            self.assertEqual(summary["failed"], 0)
        finally:
            b.cleanup()

    def test_failure_surfaces_in_summary(self) -> None:
        b = _CorpusBuilder()
        try:
            b.write_variant(
                "rejected", "ok", ".lf.yaml", "key: value\n"
            )
            b.write_sidecar(
                "rejected",
                "ok",
                {"error_substring": "never-fires"},
                {"origin": "original", "rationale": "sanity"},
            )
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(summary["failures"][0]["file"], "rejected/ok")
        finally:
            b.cleanup()

    def test_missing_variant_in_supported_flagged(self) -> None:
        b = _CorpusBuilder()
        try:
            b.write_variant(
                "supported", "partial", ".lf.yaml", "key: value\n"
            )
            b.write_sidecar(
                "supported",
                "partial",
                {"parsed": {"key": "value"}},
                {"origin": "original", "rationale": "x"},
            )
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["failed"], 1)
            self.assertTrue(
                any(
                    "missing supported/partial.crlf.yaml" in m
                    for m in summary["failures"][0]["messages"]
                )
            )
        finally:
            b.cleanup()

    def test_digest_mismatch_skips_parity(self) -> None:
        b = _CorpusBuilder()
        try:
            for s, sep in (
                (".lf.yaml", "\n"),
                (".crlf.yaml", "\r\n"),
                (".mixed.yaml", "\n"),
            ):
                b.write_variant(
                    "supported", "k", s, "key: value" + sep
                )
            b.write_sidecar(
                "supported",
                "k",
                {"parsed": {"key": "value"}},
                {"origin": "original", "rationale": "smoke"},
            )
            b.write_digests(
                "0000000000000000000000000000000000000000000000000000000000000000  supported/k.lf.yaml\n"
            )
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["failed"], 1)
            messages = summary["failures"][0]["messages"]
            self.assertTrue(any("digest mismatch" in m for m in messages))
            self.assertTrue(
                any("parity skipped due to byte drift" in m for m in messages)
            )
        finally:
            b.cleanup()


if __name__ == "__main__":
    unittest.main()
