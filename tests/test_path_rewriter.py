"""Tests for ``lib/path_rewriter.py`` — the mechanical rewrite engine
behind ``validate_skill.py --fix``.

The rewriter only suggests a replacement when:

* The original ref is not already file-relative.
* The legacy skill-root resolution lands on an existing file.
* The new file-relative form points at the same target.

Anything that fails one of these conditions returns ``None`` (no
suggestion), and the validator surfaces the broken link without a
mechanical fix-up.
"""

import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_REPO_ROOT, "skill-system-foundry", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from lib.path_rewriter import (  # noqa: E402
    apply_fixes,
    compute_recommended_replacement,
    detect_source_scope,
    find_fixable_references,
)

from helpers import write_text  # noqa: E402


class DetectSourceScopeTests(unittest.TestCase):
    """Source scope is derived from the skill-root-relative path."""

    def test_skill_root_files(self) -> None:
        self.assertEqual(detect_source_scope("SKILL.md"), ("skill", ""))
        self.assertEqual(
            detect_source_scope("references/guide.md"), ("skill", ""),
        )
        self.assertEqual(
            detect_source_scope("assets/template.md"), ("skill", ""),
        )

    def test_capability_files(self) -> None:
        self.assertEqual(
            detect_source_scope("capabilities/demo/capability.md"),
            ("capability", "demo"),
        )
        self.assertEqual(
            detect_source_scope("capabilities/demo/references/setup.md"),
            ("capability", "demo"),
        )


class ComputeRecommendedReplacementTests(unittest.TestCase):
    """The rewriter suggests canonical file-relative replacements
    when the legacy resolution would have worked."""

    def test_capability_skill_root_form_to_external(self) -> None:
        # Capability's link `references/foo.md` was meant to reach the
        # shared skill root; rewrite to `../../references/foo.md`.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "foo.md"), "# Foo\n",
            )
            cap_md = os.path.join(tmp, "capabilities", "demo", "capability.md")
            write_text(cap_md, "# Demo\n")
            replacement = compute_recommended_replacement(
                "references/foo.md", cap_md, tmp,
            )
        self.assertEqual(replacement, "../../references/foo.md")

    def test_self_prefix_form_strips_to_capability_local(self) -> None:
        # Capability's link `capabilities/demo/references/foo.md` was
        # meant to reach its own local reference; rewrite to
        # `references/foo.md`.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            cap_md = os.path.join(cap_dir, "capability.md")
            write_text(cap_md, "# Demo\n")
            write_text(
                os.path.join(cap_dir, "references", "foo.md"), "# Foo\n",
            )
            replacement = compute_recommended_replacement(
                "capabilities/demo/references/foo.md", cap_md, tmp,
            )
        self.assertEqual(replacement, "references/foo.md")

    def test_redundant_references_prefix_in_shared_reference(self) -> None:
        # A reference file linking `references/sibling.md` resolves
        # broken under file-relative semantics; rewrite to `sibling.md`.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            ref_a = os.path.join(tmp, "references", "a.md")
            write_text(ref_a, "# A\n")
            write_text(
                os.path.join(tmp, "references", "sibling.md"), "# Sibling\n",
            )
            replacement = compute_recommended_replacement(
                "references/sibling.md", ref_a, tmp,
            )
        self.assertEqual(replacement, "sibling.md")

    def test_already_canonical_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "foo.md"), "# Foo\n",
            )
            skill_md = os.path.join(tmp, "SKILL.md")
            replacement = compute_recommended_replacement(
                "references/foo.md", skill_md, tmp,
            )
        # SKILL.md is at skill root — file-relative coincides with
        # skill-root-relative.  No rewrite needed.
        self.assertIsNone(replacement)

    def test_already_file_relative_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            cap_md = os.path.join(tmp, "capabilities", "demo", "capability.md")
            write_text(cap_md, "# Demo\n")
            replacement = compute_recommended_replacement(
                "../../references/foo.md", cap_md, tmp,
            )
        self.assertIsNone(replacement)

    def test_legacy_resolution_misses_no_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            cap_md = os.path.join(tmp, "capabilities", "demo", "capability.md")
            write_text(cap_md, "# Demo\n")
            replacement = compute_recommended_replacement(
                "references/missing.md", cap_md, tmp,
            )
        self.assertIsNone(replacement)

    def test_absolute_path_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            replacement = compute_recommended_replacement(
                "/etc/passwd", os.path.join(tmp, "SKILL.md"), tmp,
            )
        self.assertIsNone(replacement)


class FindFixableReferencesTests(unittest.TestCase):
    """``find_fixable_references`` walks the skill and aggregates
    rewriter rows for every legacy ref it finds."""

    def test_collects_rows_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "guide.md"),
                "# Guide\nSee [a](references/anti.md).\n",
            )
            write_text(
                os.path.join(tmp, "references", "anti.md"), "# Anti\n",
            )
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\nSee [g](references/guide.md).\n",
            )
            rows = find_fixable_references(tmp)
        targets = {(r["file_rel"], r["original"]) for r in rows}
        self.assertIn(
            ("references/guide.md", "references/anti.md"), targets,
        )
        self.assertIn(
            ("capabilities/demo/capability.md", "references/guide.md"),
            targets,
        )

    def test_excludes_scripts_and_assets_subtrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "guide.md"), "# Guide\n",
            )
            # Both of these would otherwise produce rewrite suggestions
            # — they live under excluded subtrees, so the walker must
            # skip them entirely.
            write_text(
                os.path.join(tmp, "scripts", "doc.md"),
                "# Doc\nSee [g](references/guide.md).\n",
            )
            write_text(
                os.path.join(tmp, "assets", "doc.md"),
                "# Doc\nSee [g](references/guide.md).\n",
            )
            rows = find_fixable_references(tmp)
        for r in rows:
            self.assertFalse(r["file_rel"].startswith("scripts/"))
            self.assertFalse(r["file_rel"].startswith("assets/"))


class ApplyFixesTests(unittest.TestCase):
    """``apply_fixes`` rewrites the source files in place."""

    def test_applies_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref_a = os.path.join(tmp, "ref.md")
            write_text(
                ref_a,
                "See [a](references/x.md) and [a](references/x.md).\n",
            )
            rows = [{
                "file": ref_a,
                "file_rel": "ref.md",
                "original": "references/x.md",
                "replacement": "x.md",
                "line": 1,
            }]
            modified = apply_fixes(rows)
            with open(ref_a, "r", encoding="utf-8") as f:
                content = f.read()
        self.assertEqual(modified, 1)
        self.assertEqual(content, "See [a](x.md) and [a](x.md).\n")

    def test_unchanged_file_not_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref_a = os.path.join(tmp, "ref.md")
            write_text(ref_a, "Plain content.\n")
            rows = [{
                "file": ref_a,
                "file_rel": "ref.md",
                "original": "no-such-string",
                "replacement": "irrelevant",
                "line": 0,
            }]
            modified = apply_fixes(rows)
        self.assertEqual(modified, 0)


if __name__ == "__main__":
    unittest.main()
