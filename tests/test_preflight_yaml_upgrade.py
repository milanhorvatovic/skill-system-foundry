"""Tests for ``.github/scripts/preflight-yaml-upgrade.py``.

Covers:
- Crafted fixture per construct-id is flagged with the right token.
- Frontmatter-less Markdown is a no-op.
- ``--json`` output shape: list of ``{file, construct_id, position}``
  dicts; empty list on clean.
- Exit code 0 on clean, non-zero on any hit.
- The shipped repo's tracked content is currently clean.
"""

import importlib.util
import io
import json
import os
import unittest
import unittest.mock

_CI_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".github", "scripts")
)
_script_path = os.path.join(_CI_SCRIPTS_DIR, "preflight-yaml-upgrade.py")
_spec = importlib.util.spec_from_file_location(
    "preflight_yaml_upgrade", _script_path
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load module from {_script_path}")
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)


class ScanYamlTextConstructTests(unittest.TestCase):
    """Each crafted fixture trips the matching construct-id."""

    def test_anchor_with_trailing_in_key_flagged(self) -> None:
        text = "&anchor key: value\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        ids = [h["construct_id"] for h in hits]
        self.assertIn(preflight.ANCHOR_ID, ids)

    def test_tag_in_mapping_key_flagged(self) -> None:
        text = "!!str key: value\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        ids = [h["construct_id"] for h in hits]
        self.assertIn(preflight.TAG_ID, ids)

    def test_indent_indicator_block_scalar_flagged(self) -> None:
        text = "key: |2\n  some text\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        ids = [h["construct_id"] for h in hits]
        self.assertIn(preflight.INDENT_ID, ids)

    def test_indent_indicator_with_chomping_flagged(self) -> None:
        text = "key: >-3\n  text\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        ids = [h["construct_id"] for h in hits]
        self.assertIn(preflight.INDENT_ID, ids)

    def test_clean_input_yields_no_hits(self) -> None:
        text = "key: value\nblock: |\n  literal\nlist:\n  - a\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        self.assertEqual(hits, [])

    def test_position_is_line_number(self) -> None:
        text = "ok: value\n!!str trapped: x\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        positions = [h["position"] for h in hits if h["construct_id"] == preflight.TAG_ID]
        self.assertEqual(positions, ["line 2"])


class ExtractFrontmatterTests(unittest.TestCase):
    """Frontmatter-less Markdown returns ``None``."""

    def test_no_frontmatter_returns_none(self) -> None:
        self.assertIsNone(preflight.extract_frontmatter("# heading\n\nbody\n"))

    def test_frontmatter_returned_without_delimiters(self) -> None:
        text = "---\nname: x\n---\nbody\n"
        block = preflight.extract_frontmatter(text)
        self.assertIsNotNone(block)
        self.assertIn("name: x", block)

    def test_unterminated_frontmatter_returns_none(self) -> None:
        # Avoid surfacing a phantom hit when the closing --- is missing.
        self.assertIsNone(preflight.extract_frontmatter("---\nname: x\n"))


class ScanFileFrontmatterPositionTests(unittest.TestCase):
    """Markdown hits use ``"frontmatter"`` as their position token."""

    def test_markdown_frontmatter_position(self) -> None:
        import tempfile
        text = "---\n!!str trapped: x\n---\nbody\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(text)
            path = fh.name
        try:
            hits = preflight.scan_file(path, "synthetic.md")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["position"], "frontmatter")
            self.assertEqual(hits[0]["file"], "synthetic.md")
        finally:
            os.unlink(path)

    def test_frontmatterless_markdown_no_op(self) -> None:
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("# title\n\nbody only\n")
            path = fh.name
        try:
            hits = preflight.scan_file(path, "plain.md")
            self.assertEqual(hits, [])
        finally:
            os.unlink(path)


class MainExitCodeTests(unittest.TestCase):
    """Exit 0 on clean, non-zero on hits; JSON shape pinned."""

    def test_clean_repo_exits_zero(self) -> None:
        # The shipped tracked content must remain clean before commit 6.
        with unittest.mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(preflight.main([]), 0)

    def test_clean_repo_json_is_empty_list(self) -> None:
        buf = io.StringIO()
        with unittest.mock.patch("sys.stdout", new=buf):
            rc = preflight.main(["--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue()), [])

    def test_dirty_input_exits_one(self) -> None:
        # Inject a synthetic hit by patching collect_hits.
        synthetic = [
            {
                "file": "synthetic.yaml",
                "construct_id": preflight.ANCHOR_ID,
                "position": "line 1",
            }
        ]
        with unittest.mock.patch.object(
            preflight, "collect_hits", return_value=synthetic
        ):
            with unittest.mock.patch("sys.stdout", new=io.StringIO()):
                rc = preflight.main([])
        self.assertEqual(rc, 1)

    def test_dirty_json_shape(self) -> None:
        synthetic = [
            {
                "file": "a.yaml",
                "construct_id": preflight.INDENT_ID,
                "position": "line 5",
            }
        ]
        buf = io.StringIO()
        with unittest.mock.patch.object(
            preflight, "collect_hits", return_value=synthetic
        ):
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = preflight.main(["--json"])
        self.assertEqual(rc, 1)
        payload = json.loads(buf.getvalue())
        self.assertEqual(len(payload), 1)
        self.assertEqual(
            set(payload[0].keys()),
            {"file", "construct_id", "position"},
        )


if __name__ == "__main__":
    unittest.main()
