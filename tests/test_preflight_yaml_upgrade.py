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

    def test_anchor_with_non_word_chars_in_name_flagged(self) -> None:
        # The parser rejects any mapping key whose first whitespace-
        # separated token starts with ``&`` and has trailing key text,
        # regardless of which non-colon characters appear in the
        # anchor name.  Preflight must mirror that breadth so the
        # WARN→ValueError gate is not blind to anchors whose names
        # use ``.`` / ``/`` etc.  ``:`` is the colon-key boundary, so
        # tokens containing ``:`` are handled by
        # ``test_anchor_with_colon_inside_name_not_flagged`` below.
        for header in (
            "&a.b key: value\n",
            "&a/b key: value\n",
            "& key: value\n",
        ):
            with self.subTest(header=header.rstrip()):
                hits = preflight.scan_yaml_text(
                    header, lambda n: f"line {n}"
                )
                ids = [h["construct_id"] for h in hits]
                self.assertIn(preflight.ANCHOR_ID, ids, header)

    def test_anchor_with_colon_inside_name_not_flagged(self) -> None:
        # ``&a:b key: value`` — the parser splits the line on the
        # first colon, so the key is ``&a`` (no trailing text after
        # whitespace-split), and ``_check_mapping_key_construct``
        # does NOT raise for it.  Preflight must mirror the parser's
        # silence here, otherwise it false-positives clean content at
        # the upgrade gate.
        text = "&a:b key: value\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        ids = [h["construct_id"] for h in hits]
        self.assertNotIn(preflight.ANCHOR_ID, ids)

    def test_tag_in_mapping_key_flagged(self) -> None:
        text = "!!str key: value\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        ids = [h["construct_id"] for h in hits]
        self.assertIn(preflight.TAG_ID, ids)

    def test_tag_without_trailing_key_text_flagged(self) -> None:
        # The parser raises for any mapping key whose first token starts
        # with ``!`` — trailing key text is NOT required (this is the
        # tag/anchor asymmetry: anchors raise only with trailing text,
        # tags raise unconditionally).  Preflight must mirror that, or
        # ``!tag: value`` and ``!!str: value`` slip through and surface
        # only at parser time.
        for header in (
            "!tag: value\n",
            "!!str: value\n",
            "!my:custom: value\n",
        ):
            with self.subTest(header=header.rstrip()):
                hits = preflight.scan_yaml_text(
                    header, lambda n: f"line {n}"
                )
                ids = [h["construct_id"] for h in hits]
                self.assertIn(preflight.TAG_ID, ids, header)

    def test_tag_with_whitespace_gap_before_colon_flagged(self) -> None:
        # The parser splits the line on the first ``:`` and then
        # whitespace-splits the resulting key.  ``! : value`` and
        # ``!tag : value`` therefore have first-token ``!`` / ``!tag``
        # in mapping-key position and raise — even though the tag
        # token is separated from the colon by whitespace rather
        # than concatenated.  Preflight must catch the gap forms.
        for header in (
            "! : value\n",
            "!tag : value\n",
            "!!str : value\n",
            "  ! : value\n",
        ):
            with self.subTest(header=header.rstrip()):
                hits = preflight.scan_yaml_text(
                    header, lambda n: f"line {n}"
                )
                ids = [h["construct_id"] for h in hits]
                self.assertIn(preflight.TAG_ID, ids, header)

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

    def test_indent_indicator_without_post_colon_space_flagged(self) -> None:
        # ``parse_yaml_subset`` strips whitespace after the colon, so
        # ``key:|2`` raises the same upgraded ValueError as ``key: |2``.
        # Preflight must mirror that or the WARN→ValueError gate is
        # blind to a real parser-failure shape.
        for text in (
            "key:|2\n",
            "- key:|2\n",
            "key:>-3\n",
        ):
            with self.subTest(text=text.rstrip()):
                hits = preflight.scan_yaml_text(
                    text, lambda n: f"line {n}"
                )
                ids = [h["construct_id"] for h in hits]
                self.assertIn(preflight.INDENT_ID, ids, text)

    def test_indent_indicator_with_comment_attached_not_flagged(self) -> None:
        # ``|2#note`` (no whitespace before ``#``) is not an
        # indent-indicator header per parser semantics — the parser
        # only raises when the ``#`` is preceded by whitespace per
        # YAML §8.1.1.  Preflight must mirror that or it
        # false-positives clean content.
        text = "key: |2#note\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        ids = [h["construct_id"] for h in hits]
        self.assertNotIn(preflight.INDENT_ID, ids)

    def test_indent_indicator_with_proper_comment_flagged(self) -> None:
        # ``|2 # note`` (whitespace before ``#``) IS an indent-indicator
        # header — the parser raises, so preflight must too.
        text = "key: |2 # note\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        ids = [h["construct_id"] for h in hits]
        self.assertIn(preflight.INDENT_ID, ids)

    def test_comment_line_with_colon_not_flagged(self) -> None:
        # A whole-line YAML comment containing colon-shaped content
        # must not trip the construct regexes — the parser never
        # treats comment text as keys/values.
        text = "# &anchor key: value | also !!str other: x and key: |2\n"
        hits = preflight.scan_yaml_text(text, lambda n: f"line {n}")
        self.assertEqual(hits, [])

    def test_indent_indicator_with_spaces_in_key_flagged(self) -> None:
        # The parser slices keys from values on the first colon, so
        # ``my key: |2`` raises the upgraded ValueError despite the
        # space in the key.  Preflight must mirror that or the
        # WARN→ValueError gate is blind to a real parser-failure
        # shape that authors are likely to produce by accident.
        for text in (
            "my key: |2\n",
            "- my key: |2\n",
            "key with several words: >-3\n",
        ):
            with self.subTest(text=text.rstrip()):
                hits = preflight.scan_yaml_text(
                    text, lambda n: f"line {n}"
                )
                ids = [h["construct_id"] for h in hits]
                self.assertIn(preflight.INDENT_ID, ids, text)

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

    def test_block_scalar_dashes_do_not_terminate_frontmatter(self) -> None:
        # A literal ``---`` inside a block scalar value is not a closer;
        # detection is line-based so the embedded substring is included
        # in the returned block, not used to slice it short.
        text = (
            "---\n"
            "description: |\n"
            "  embedded --- dashes are fine\n"
            "---\n"
            "body\n"
        )
        block = preflight.extract_frontmatter(text)
        self.assertIsNotNone(block)
        self.assertIn("embedded --- dashes are fine", block)


class ScanFileUnreadableTests(unittest.TestCase):
    """In-scope files that cannot be read/decoded surface as hits."""

    def test_undecodable_yaml_surfaces_unreadable_hit(self) -> None:
        # A tracked .yaml file that fails UTF-8 decode must surface
        # as a hit, not vanish silently — otherwise the upgrade gate
        # treats a corrupted tracked file the same as a clean one.
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".yaml", delete=False
        ) as fh:
            fh.write(b"\xff\xfe binary garbage")
            tmp_path = fh.name
        try:
            hits = preflight.scan_file(tmp_path, "fixtures/binary.yaml")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["construct_id"], preflight.UNREADABLE_ID)
            self.assertIn("UnicodeDecodeError", hits[0]["position"])
            self.assertEqual(hits[0]["file"], "fixtures/binary.yaml")
        finally:
            os.unlink(tmp_path)

    def test_missing_yaml_surfaces_unreadable_hit(self) -> None:
        # OSError (e.g. file removed between walk and read) likewise
        # fails loud rather than silently passing.
        hits = preflight.scan_file(
            "/nonexistent/path/x.yaml", "fixtures/x.yaml"
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["construct_id"], preflight.UNREADABLE_ID)
        self.assertIn("FileNotFoundError", hits[0]["position"])

    def test_out_of_scope_unreadable_file_still_silent(self) -> None:
        # Out-of-scope suffixes (binaries, archives, etc.) are not
        # the gate's concern — they continue to return empty without
        # opening so the walk avoids unnecessary I/O on the whole
        # repo.
        hits = preflight.scan_file(
            "/nonexistent/path/x.png", "assets/x.png"
        )
        self.assertEqual(hits, [])


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
        # Tracked content must stay clean against the upgraded
        # parser — preflight is the WARN→ValueError gate, so any hit
        # here means a tracked YAML/Markdown input would crash the
        # shipped parser and the upgrade has regressed.
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
