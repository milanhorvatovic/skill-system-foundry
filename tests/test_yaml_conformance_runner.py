"""Unit tests for ``skill-system-foundry/scripts/lib/yaml_conformance_runner.py``.

Synthetic in-memory corpora exercise each helper.  The real corpus is
exercised end-to-end by ``tests/test_yaml_conformance.py``.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "skill-system-foundry", "scripts"
    )
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from lib import yaml_conformance_runner as runner  # noqa: E402


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
    """``parse_digests_file`` honours the ``sha256sum`` shape."""

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

    def test_duplicate_path_raises(self) -> None:
        # Two manifest lines naming the same fixture path is
        # corruption (typically a merge artefact); silently letting
        # the second value win would mask drift depending on line
        # order, so the parser must raise.
        text = (
            "abc  supported/a.lf.yaml\n"
            "def  supported/a.lf.yaml\n"
        )
        with self.assertRaises(ValueError) as ctx:
            runner.parse_digests_file(text)
        self.assertIn(
            "duplicate digest entry", str(ctx.exception)
        )
        self.assertIn("supported/a.lf.yaml", str(ctx.exception))


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


class CheckParityCrashGuardTests(unittest.TestCase):
    """``check_parity`` must aggregate, never propagate parser raises."""

    def test_variant_parse_failure_is_aggregated_not_raised(self) -> None:
        # A supported/divergent variant whose bytes happen to trip the
        # parser raises in ``check_parity``'s reparse loop.  Without a
        # guard the whole harness aborts on a single malformed fixture
        # instead of recording one case as failed.  The check returns
        # a single skip message and never propagates.
        texts = ["key: value\n", "key: |2\n  text\n"]
        msgs = runner.check_parity(texts)
        self.assertEqual(msgs, ["parity skipped due to variant parse failure"])


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


class MalformedSidecarTests(unittest.TestCase):
    """A sidecar that fails to parse surfaces as a loud failure."""

    def test_malformed_expected_json_fails_case(self) -> None:
        b = _CorpusBuilder()
        try:
            for s in (".lf.yaml", ".crlf.yaml", ".mixed.yaml"):
                b.write_variant(
                    "supported", "k", s, "key: value\n"
                )
            # Corrupt the expected-side sidecar.
            _write(
                os.path.join(b.root, "supported", "k.expected.json"),
                "{ this is not json",
            )
            _write(
                os.path.join(b.root, "supported", "k.meta.json"),
                json.dumps({"origin": "original", "rationale": "x"}),
            )
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["failed"], 1)
            messages = summary["failures"][0]["messages"]
            self.assertTrue(
                any("sidecar parse error" in m for m in messages),
                messages,
            )
        finally:
            b.cleanup()


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

    def test_missing_digest_entry_fails_loud(self) -> None:
        # When a manifest is in play, a fixture variant without a
        # corresponding digests.txt entry is just as much a drift
        # signal as a hash mismatch.  Surface it as a per-variant
        # failure and skip parity for that variant so byte trust is
        # preserved.  ``test_no_manifest_does_not_enforce_per_variant``
        # pins the inverse: no manifest means no per-variant
        # enforcement (orphan-digest sweep covers the other side).
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
            # Manifest exists but only covers .lf — the other two
            # variants must surface as missing-entry failures.
            real_lf = runner.hash_file(
                os.path.join(b.root, "supported", "k.lf.yaml")
            )
            b.write_digests(f"{real_lf}  supported/k.lf.yaml\n")
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["failed"], 1)
            messages = summary["failures"][0]["messages"]
            self.assertFalse(
                any("missing digest entry: supported/k.lf.yaml" in m for m in messages),
                messages,
            )
            self.assertTrue(
                any("missing digest entry: supported/k.crlf.yaml" in m for m in messages)
            )
            self.assertTrue(
                any("missing digest entry: supported/k.mixed.yaml" in m for m in messages)
            )
            self.assertTrue(
                any("parity skipped due to byte drift" in m for m in messages)
            )
        finally:
            b.cleanup()

    def test_no_manifest_does_not_enforce_per_variant(self) -> None:
        # A corpus with no digests.txt at all (typical scaffolding
        # state) skips per-variant digest checks rather than failing
        # every variant.  Orphan-digest detection in run_corpus covers
        # the inverse class of drift; the "manifest absent" case
        # belongs to corpus setup, not corruption.
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
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["passed"], 1)
        finally:
            b.cleanup()

    def test_empty_manifest_still_enforces(self) -> None:
        # An empty-but-present digests.txt is a different signal from
        # an absent file: it almost certainly means the manifest was
        # accidentally truncated, so per-variant enforcement must
        # still fire (every variant surfaces as a missing entry).
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
            b.write_digests("")
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["failed"], 1)
            messages = summary["failures"][0]["messages"]
            for variant in (
                "supported/k.lf.yaml",
                "supported/k.crlf.yaml",
                "supported/k.mixed.yaml",
            ):
                self.assertTrue(
                    any(f"missing digest entry: {variant}" in m for m in messages),
                    f"expected missing-entry message for {variant} in {messages!r}",
                )
        finally:
            b.cleanup()

    def test_summary_invariant_passed_plus_failed_equals_total(self) -> None:
        # Sweep three corpus shapes that each previously had a chance
        # to break the ``passed + failed == total`` invariant before
        # the orphan-digest sweep was counted in ``total``: clean +
        # manifest, clean + no manifest, and orphan-digest failure on
        # an otherwise-clean corpus (which used to push ``passed``
        # below the case count).
        cases = [
            ("clean_with_manifest", True, False),
            ("clean_no_manifest", False, False),
            ("orphan_only", True, True),
        ]
        for label, write_manifest, with_orphan in cases:
            with self.subTest(label=label):
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
                    if write_manifest:
                        real_lf = runner.hash_file(
                            os.path.join(b.root, "supported", "k.lf.yaml")
                        )
                        real_crlf = runner.hash_file(
                            os.path.join(b.root, "supported", "k.crlf.yaml")
                        )
                        real_mixed = runner.hash_file(
                            os.path.join(b.root, "supported", "k.mixed.yaml")
                        )
                        ghost = (
                            "deadbeef  supported/ghost.lf.yaml\n"
                            if with_orphan else ""
                        )
                        b.write_digests(
                            f"{real_lf}  supported/k.lf.yaml\n"
                            f"{real_crlf}  supported/k.crlf.yaml\n"
                            f"{real_mixed}  supported/k.mixed.yaml\n"
                            f"{ghost}"
                        )
                    summary = runner.run_corpus(b.root)
                    self.assertEqual(
                        summary["passed"] + summary["failed"],
                        summary["total"],
                        summary,
                    )
                    self.assertGreaterEqual(summary["passed"], 0, summary)
                finally:
                    b.cleanup()

    def test_orphan_digest_entry_surfaces_as_corpus_failure(self) -> None:
        # A digests.txt line whose path is not a discovered fixture
        # (typically a leftover after a fixture deletion) is the inverse
        # of the missing-entry case and must also fail loud.
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
            real_lf = runner.hash_file(
                os.path.join(b.root, "supported", "k.lf.yaml")
            )
            real_crlf = runner.hash_file(
                os.path.join(b.root, "supported", "k.crlf.yaml")
            )
            real_mixed = runner.hash_file(
                os.path.join(b.root, "supported", "k.mixed.yaml")
            )
            b.write_digests(
                f"{real_lf}  supported/k.lf.yaml\n"
                f"{real_crlf}  supported/k.crlf.yaml\n"
                f"{real_mixed}  supported/k.mixed.yaml\n"
                "deadbeef  supported/ghost.lf.yaml\n"
            )
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["failed"], 1)
            entry = summary["failures"][0]
            self.assertEqual(entry["file"], "digests.txt")
            self.assertIn(
                "orphan digest entry: supported/ghost.lf.yaml",
                entry["messages"],
            )
        finally:
            b.cleanup()

    def test_malformed_meta_json_reports_meta_path(self) -> None:
        # When the meta.json sidecar is malformed, the failure message
        # must point at meta.json — not at expected.json (which loaded
        # fine).  Misreporting the path makes corpus debugging harder.
        b = _CorpusBuilder()
        try:
            for s in (".lf.yaml", ".crlf.yaml", ".mixed.yaml"):
                b.write_variant(
                    "supported", "k", s, "key: value\n"
                )
            _write(
                os.path.join(b.root, "supported", "k.expected.json"),
                json.dumps({"parsed": {"key": "value"}}),
            )
            _write(
                os.path.join(b.root, "supported", "k.meta.json"),
                "{ this is not json",
            )
            summary = runner.run_corpus(b.root)
            self.assertEqual(summary["failed"], 1)
            messages = summary["failures"][0]["messages"]
            self.assertTrue(
                any("sidecar parse error" in m and "k.meta.json" in m for m in messages),
                messages,
            )
            self.assertFalse(
                any("k.expected.json" in m for m in messages),
                messages,
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
