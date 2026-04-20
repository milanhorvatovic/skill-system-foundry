"""Tests for ``skill-system-foundry/scripts/yaml_conformance_report.py``.

Covers:
- Clean corpus → exit 0, JSON shape pinned (``corpus.total/passed/...``).
- Synthetic failing corpus → non-zero exit, failure surfaced in output.
- Default mode is human; ``--json`` is explicit.
"""

import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock

_SCRIPT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "skill-system-foundry", "scripts",
        "yaml_conformance_report.py",
    )
)
_spec = importlib.util.spec_from_file_location(
    "yaml_conformance_report", _SCRIPT_PATH
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load module from {_SCRIPT_PATH}")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def _write(path: str, content: bytes | str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if isinstance(content, str):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    else:
        with open(path, "wb") as fh:
            fh.write(content)


class _SyntheticCorpus:
    """Build a small synthetic corpus under a temp directory."""

    def __init__(self, *, fail: bool = False) -> None:
        self.root = tempfile.mkdtemp()
        # One supported case, complete triplet.
        for suffix, sep in (
            (".lf.yaml", "\n"),
            (".crlf.yaml", "\r\n"),
            (".mixed.yaml", "\n"),
        ):
            _write(
                os.path.join(self.root, "supported", f"a{suffix}"),
                f"key: value{sep}",
            )
        _write(
            os.path.join(self.root, "supported", "a.expected.json"),
            json.dumps(
                {"parsed": {"key": "wrong" if fail else "value"}}
            ),
        )
        _write(
            os.path.join(self.root, "supported", "a.meta.json"),
            json.dumps({"origin": "original", "rationale": "x"}),
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class CleanCorpusTests(unittest.TestCase):
    """Real shipped corpus exits 0 with the pinned JSON shape."""

    def test_default_human_output_exits_zero(self) -> None:
        with unittest.mock.patch("sys.stdout", new=io.StringIO()) as buf:
            rc = report.main([])
        self.assertEqual(rc, 0)
        self.assertIn("YAML conformance corpus", buf.getvalue())

    def test_json_output_shape(self) -> None:
        buf = io.StringIO()
        with unittest.mock.patch("sys.stdout", new=buf):
            rc = report.main(["--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("corpus", payload)
        corpus = payload["corpus"]
        self.assertEqual(
            set(corpus.keys()),
            {"total", "passed", "failed", "failures"},
        )
        for k in ("total", "passed", "failed"):
            self.assertIsInstance(corpus[k], int)
        self.assertEqual(corpus["failures"], [])
        self.assertEqual(corpus["passed"], corpus["total"])


class SyntheticFailureTests(unittest.TestCase):
    """A bad expected dict surfaces as a non-zero exit and listed failure."""

    def test_failing_corpus_returns_one(self) -> None:
        sc = _SyntheticCorpus(fail=True)
        try:
            buf = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = report.main(["--corpus-root", sc.root, "--json"])
            self.assertEqual(rc, 1)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["corpus"]["failed"], 1)
            self.assertEqual(
                payload["corpus"]["failures"][0]["file"],
                "supported/a",
            )
        finally:
            sc.cleanup()

    def test_human_failure_output_includes_messages(self) -> None:
        sc = _SyntheticCorpus(fail=True)
        try:
            buf = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = report.main(["--corpus-root", sc.root])
            self.assertEqual(rc, 1)
            output = buf.getvalue()
            self.assertIn("FAIL supported/a", output)
            self.assertIn("parsed dict mismatch", output)
        finally:
            sc.cleanup()


class MissingCorpusRootTests(unittest.TestCase):
    """Bad ``--corpus-root`` surfaces a clear error."""

    def test_missing_root_returns_one(self) -> None:
        with unittest.mock.patch("sys.stderr", new=io.StringIO()):
            rc = report.main(["--corpus-root", "/nonexistent/path"])
        self.assertEqual(rc, 1)

    def test_malformed_manifest_human_mode_writes_stderr(self) -> None:
        # Human mode for the same corpus-load failure path emits a
        # stderr message and exits 1 — covered separately so both
        # branches of the new try/except are exercised.
        import shutil
        import tempfile
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "supported"))
            with open(
                os.path.join(root, "supported", "k.lf.yaml"),
                "wb",
            ) as fh:
                fh.write(b"key: value\n")
            with open(
                os.path.join(root, "digests.txt"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("not-a-valid-line\n")
            err = io.StringIO()
            with unittest.mock.patch("sys.stderr", new=err):
                rc = report.main(["--corpus-root", root])
            self.assertEqual(rc, 1)
            self.assertIn("corpus load failure", err.getvalue())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_malformed_manifest_emits_json_corpus_load_failure(self) -> None:
        # If digests.txt contains a malformed line, ``runner.run_corpus``
        # raises ValueError at parse time.  ``--json`` consumers
        # depend on the pinned ``corpus`` shape on every exit, so the
        # script must catch the raise and emit a structured payload
        # rather than crashing with a traceback.
        import json
        import shutil
        import tempfile
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "supported"))
            with open(
                os.path.join(root, "supported", "k.lf.yaml"),
                "wb",
            ) as fh:
                fh.write(b"key: value\n")
            with open(
                os.path.join(root, "digests.txt"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("not-a-valid-line-without-digest-and-path\n")
            buf = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = report.main(
                    ["--corpus-root", root, "--json"]
                )
            self.assertEqual(rc, 1)
            payload = json.loads(buf.getvalue())
            self.assertIn("corpus", payload)
            corpus = payload["corpus"]
            self.assertEqual(corpus["total"], 1)
            self.assertEqual(corpus["passed"], 0)
            self.assertEqual(corpus["failed"], 1)
            self.assertEqual(corpus["failures"][0]["file"], "corpus")
            self.assertTrue(
                any(
                    "corpus load failure" in m
                    and "malformed digests.txt line" in m
                    for m in corpus["failures"][0]["messages"]
                )
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_root_emits_json_payload(self) -> None:
        # Tooling consumers parsing --json output need a structured
        # payload on every exit path.  The missing-corpus-root error
        # previously printed plain stderr text regardless of --json,
        # which broke the contract for callers that pipe stdout into a
        # JSON parser.
        import json
        buf = io.StringIO()
        with unittest.mock.patch("sys.stdout", new=buf):
            rc = report.main(
                ["--corpus-root", "/nonexistent/path", "--json"]
            )
        self.assertEqual(rc, 1)
        payload = json.loads(buf.getvalue())
        self.assertIn("corpus", payload)
        corpus = payload["corpus"]
        # Counts must be internally consistent: the missing-root
        # condition counts as one failed corpus-level assertion so
        # ``passed + failed == total`` holds and consumers keying on
        # ``failed`` rather than exit code see the same answer.
        self.assertEqual(corpus["total"], 1)
        self.assertEqual(corpus["passed"], 0)
        self.assertEqual(corpus["failed"], 1)
        self.assertEqual(len(corpus["failures"]), 1)
        self.assertEqual(corpus["failures"][0]["file"], "corpus_root")
        self.assertTrue(
            any(
                "corpus root not found" in m
                for m in corpus["failures"][0]["messages"]
            )
        )


if __name__ == "__main__":
    unittest.main()
