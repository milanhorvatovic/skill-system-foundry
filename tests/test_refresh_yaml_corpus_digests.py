"""Tests for ``.github/scripts/refresh-yaml-corpus-digests.py``.

Covers:
- Pass path: unchanged corpus → zero diff.
- Drift path: changed fixture → regenerated digest, ``--check`` fails.
- ``--check`` mode both branches.
- Whitespace-in-path is rejected.
"""

import importlib.util
import io
import os
import shutil
import tempfile
import unittest
import unittest.mock

_CI_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".github", "scripts")
)
_script_path = os.path.join(
    _CI_SCRIPTS_DIR, "refresh-yaml-corpus-digests.py"
)
_spec = importlib.util.spec_from_file_location(
    "refresh_yaml_corpus_digests", _script_path
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load module from {_script_path}")
refresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refresh)


def _write(path: str, content: bytes) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)


class _CorpusFixture:
    """Build a tiny temp corpus with a couple of variants."""

    def __init__(self) -> None:
        self.root = tempfile.mkdtemp()
        _write(
            os.path.join(self.root, "supported", "a.lf.yaml"),
            b"key: value\n",
        )
        _write(
            os.path.join(self.root, "supported", "a.crlf.yaml"),
            b"key: value\r\n",
        )
        _write(
            os.path.join(self.root, "rejected", "b.lf.yaml"),
            b"!!str key: value\n",
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def manifest_path(self) -> str:
        return os.path.join(self.root, "digests.txt")


class CollectManifestTests(unittest.TestCase):
    """``collect_manifest`` produces deterministic, sorted output."""

    def test_manifest_is_sorted_by_path(self) -> None:
        cf = _CorpusFixture()
        try:
            text = refresh.collect_manifest(cf.root)
            paths = [line.split("  ", 1)[1] for line in text.strip().splitlines()]
            self.assertEqual(paths, sorted(paths))
        finally:
            cf.cleanup()

    def test_manifest_contains_only_variant_files(self) -> None:
        cf = _CorpusFixture()
        try:
            # Drop a sidecar; refresh must not list it.
            _write(
                os.path.join(cf.root, "supported", "a.expected.json"),
                b"{}\n",
            )
            text = refresh.collect_manifest(cf.root)
            self.assertNotIn("expected.json", text)
        finally:
            cf.cleanup()

    def test_whitespace_in_path_raises(self) -> None:
        cf = _CorpusFixture()
        try:
            _write(
                os.path.join(cf.root, "supported", "bad name.lf.yaml"),
                b"key: value\n",
            )
            with self.assertRaises(ValueError) as ctx:
                refresh.collect_manifest(cf.root)
            self.assertIn("whitespace", str(ctx.exception))
        finally:
            cf.cleanup()


class WriteManifestAtomicTests(unittest.TestCase):
    """Atomic-write semantics — output is the new manifest text."""

    def test_writes_and_replaces(self) -> None:
        cf = _CorpusFixture()
        try:
            text = refresh.collect_manifest(cf.root)
            path = refresh.write_manifest_atomic(cf.root, text)
            self.assertEqual(path, cf.manifest_path())
            with open(path, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), text)
        finally:
            cf.cleanup()

    def test_replaces_existing_manifest(self) -> None:
        cf = _CorpusFixture()
        try:
            _write(cf.manifest_path(), b"obsolete content\n")
            text = refresh.collect_manifest(cf.root)
            refresh.write_manifest_atomic(cf.root, text)
            with open(cf.manifest_path(), "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), text)
        finally:
            cf.cleanup()


class MainCheckModeTests(unittest.TestCase):
    """``--check`` exits 0 on match, 1 on drift."""

    def test_clean_exits_zero(self) -> None:
        cf = _CorpusFixture()
        try:
            text = refresh.collect_manifest(cf.root)
            refresh.write_manifest_atomic(cf.root, text)
            with unittest.mock.patch("sys.stdout", new=io.StringIO()):
                rc = refresh.main(["--corpus-root", cf.root, "--check"])
            self.assertEqual(rc, 0)
        finally:
            cf.cleanup()

    def test_drift_exits_one(self) -> None:
        cf = _CorpusFixture()
        try:
            _write(cf.manifest_path(), b"deadbeef  supported/a.lf.yaml\n")
            buf = io.StringIO()
            with unittest.mock.patch("sys.stderr", new=buf):
                rc = refresh.main(["--corpus-root", cf.root, "--check"])
            self.assertEqual(rc, 1)
            self.assertIn("drift", buf.getvalue())
        finally:
            cf.cleanup()


class MainRegenerateModeTests(unittest.TestCase):
    """Without ``--check`` the script rewrites the manifest."""

    def test_regenerates_into_directory(self) -> None:
        cf = _CorpusFixture()
        try:
            with unittest.mock.patch("sys.stdout", new=io.StringIO()):
                rc = refresh.main(["--corpus-root", cf.root])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(cf.manifest_path()))
        finally:
            cf.cleanup()

    def test_missing_corpus_root_returns_one(self) -> None:
        with unittest.mock.patch("sys.stderr", new=io.StringIO()):
            rc = refresh.main(["--corpus-root", "/nonexistent/x"])
        self.assertEqual(rc, 1)

    def test_whitespace_path_returns_one(self) -> None:
        cf = _CorpusFixture()
        try:
            _write(
                os.path.join(cf.root, "supported", "bad name.lf.yaml"),
                b"key: value\n",
            )
            with unittest.mock.patch("sys.stderr", new=io.StringIO()):
                rc = refresh.main(["--corpus-root", cf.root])
            self.assertEqual(rc, 1)
        finally:
            cf.cleanup()


class MainJsonOutputTests(unittest.TestCase):
    """``--json`` covers all four exit paths so tooling can consume them."""

    def test_check_clean_emits_drift_false(self) -> None:
        import json
        cf = _CorpusFixture()
        try:
            buf = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf):
                refresh.main(["--corpus-root", cf.root])  # populate
            buf2 = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf2):
                rc = refresh.main(
                    ["--corpus-root", cf.root, "--check", "--json"]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf2.getvalue())
            self.assertEqual(payload["action"], "check")
            self.assertFalse(payload["drift"])
            self.assertGreater(payload["fixture_count"], 0)
        finally:
            cf.cleanup()

    def test_check_drift_emits_diff(self) -> None:
        import json
        cf = _CorpusFixture()
        try:
            with unittest.mock.patch("sys.stdout", new=io.StringIO()):
                refresh.main(["--corpus-root", cf.root])
            # Mutate one fixture so the live digest no longer matches.
            with open(
                os.path.join(cf.root, "supported", "a.lf.yaml"),
                "wb",
            ) as fh:
                fh.write(b"key: changed\n")
            buf = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = refresh.main(
                    ["--corpus-root", cf.root, "--check", "--json"]
                )
            self.assertEqual(rc, 1)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["action"], "check")
            self.assertTrue(payload["drift"])
            self.assertIn("supported/a.lf.yaml", payload["changed"])
            self.assertEqual(payload["missing"], [])
            self.assertEqual(payload["extra"], [])
        finally:
            cf.cleanup()

    def test_regenerate_emits_path_and_count(self) -> None:
        import json
        cf = _CorpusFixture()
        try:
            buf = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = refresh.main(
                    ["--corpus-root", cf.root, "--json"]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["action"], "regenerated")
            self.assertTrue(payload["path"].endswith("digests.txt"))
            self.assertGreater(payload["fixture_count"], 0)
        finally:
            cf.cleanup()

    def test_error_emits_action_error(self) -> None:
        import json
        buf = io.StringIO()
        with unittest.mock.patch("sys.stdout", new=buf):
            rc = refresh.main(
                ["--corpus-root", "/nonexistent/x", "--json"]
            )
        self.assertEqual(rc, 1)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["action"], "error")
        self.assertIn("not found", payload["error"])

    def test_whitespace_path_emits_action_error_in_json(self) -> None:
        # The other ValueError exit path (whitespace in a fixture
        # filename) must also surface as a structured payload, not as
        # a stderr-only message — otherwise the tooling consumer sees
        # exit 1 with empty stdout.
        import json
        cf = _CorpusFixture()
        try:
            _write(
                os.path.join(cf.root, "supported", "bad name.lf.yaml"),
                b"key: value\n",
            )
            buf = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = refresh.main(
                    ["--corpus-root", cf.root, "--json"]
                )
            self.assertEqual(rc, 1)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["action"], "error")
            self.assertIn("whitespace", payload["error"])
        finally:
            cf.cleanup()


if __name__ == "__main__":
    unittest.main()
