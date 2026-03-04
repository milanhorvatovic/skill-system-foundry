import os
import sys
import unittest


SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import bundle
from lib.references import should_skip_reference, strip_fragment


class ReferenceParsingTests(unittest.TestCase):
    def test_strip_fragment_matrix(self) -> None:
        cases = {
            "references/foo.md": "references/foo.md",
            "references/foo.md#section": "references/foo.md",
            "references/foo.md?mode=raw#section": "references/foo.md",
            "<references/foo.md#section>": "references/foo.md",
            "<references/foo.md?mode=raw#section> \"Title\"": "references/foo.md",
        }

        for raw_ref, expected in cases.items():
            with self.subTest(raw_ref=raw_ref):
                self.assertEqual(strip_fragment(raw_ref), expected)

    def test_should_skip_reference_matrix(self) -> None:
        cases = {
            "https://example.com/doc.md": True,
            "mailto:test@example.com": True,
            "#section": True,
            "references/foo.md": False,
            "<references/foo.md>": False,
            "<references/foo.md> \"Title\"": False,
        }

        for raw_ref, expected in cases.items():
            with self.subTest(raw_ref=raw_ref):
                self.assertEqual(should_skip_reference(raw_ref), expected)


class ReferenceRewriteTests(unittest.TestCase):
    def test_rewrite_matrix(self) -> None:
        rewrite_map = {
            "references/foo.md": "references/inlined/foo.md",
            "roles/reviewer.md": "roles/core/reviewer.md",
        }

        cases = {
            "See [doc](references/foo.md).": "See [doc](references/inlined/foo.md).",
            "See [doc](references/foo.md#overview).": "See [doc](references/inlined/foo.md#overview).",
            "See [doc](references/foo.md?mode=raw#overview).": "See [doc](references/inlined/foo.md?mode=raw#overview).",
            "See [doc](references/foo.md \"Guide\").": "See [doc](references/inlined/foo.md \"Guide\").",
            "See [doc](<references/foo.md#overview>).": "See [doc](<references/inlined/foo.md#overview>).",
            "See [doc](<references/foo.md?mode=raw#overview> \"Guide\").": "See [doc](<references/inlined/foo.md?mode=raw#overview> \"Guide\").",
            "Use `references/foo.md` and `roles/reviewer.md`.": "Use `references/inlined/foo.md` and `roles/core/reviewer.md`.",
            "Use `references/foo.md#overview`.": "Use `references/inlined/foo.md#overview`.",
            "Leave [doc](references/missing.md) unchanged.": "Leave [doc](references/missing.md) unchanged.",
        }

        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(bundle._rewrite_markdown_content(source, rewrite_map), expected)


if __name__ == "__main__":
    unittest.main()
