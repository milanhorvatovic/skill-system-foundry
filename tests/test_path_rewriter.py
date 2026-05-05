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
    detect_ambiguous_legacy_target,
    detect_source_scope,
    find_ambiguous_legacy_refs,
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

    def test_dot_slash_legacy_form_is_rewritten(self) -> None:
        # A ``./``-prefixed legacy capability link such as
        # ``./references/foo.md`` from a capability resolves
        # file-relative to ``capabilities/<n>/references/foo.md``
        # (broken under the new rule) but lands on the shared-root
        # ``references/foo.md`` under legacy skill-root resolution.
        # The rewriter must surface this as a mechanically fixable
        # rewrite — proposing ``../../references/foo.md`` — instead
        # of treating the ``./`` prefix as "already canonical" and
        # returning None.  ``./`` is just a redundant
        # current-directory marker; it does not signal intentional
        # file-relative form the way ``../`` does.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "foo.md"), "# Foo\n",
            )
            cap_md = os.path.join(tmp, "capabilities", "demo", "capability.md")
            write_text(cap_md, "# Demo\n")
            replacement = compute_recommended_replacement(
                "./references/foo.md", cap_md, tmp,
            )
        self.assertEqual(replacement, "../../references/foo.md")

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

    def test_mid_path_traversal_escaping_skill_root_returns_none(self) -> None:
        # A ref like ``references/../../shared/foo.md`` does not start
        # with ``../`` (so the leading-prefix guard does not reject
        # it) but *normalizes* outside the skill root.  The rewriter
        # must refuse to suggest a replacement for these — both to
        # honor the validator's "no filesystem checks for paths
        # outside the skill" boundary and to avoid emitting a
        # non-canonical relative path that points outside the tree.
        with tempfile.TemporaryDirectory() as tmp:
            skill_root = os.path.join(tmp, "skill")
            outside_dir = os.path.join(tmp, "shared")
            write_text(os.path.join(skill_root, "SKILL.md"), "---\nname: t\n---\n")
            write_text(os.path.join(outside_dir, "foo.md"), "# Outside\n")
            cap_md = os.path.join(
                skill_root, "capabilities", "demo", "capability.md",
            )
            write_text(cap_md, "# Demo\n")
            replacement = compute_recommended_replacement(
                "references/../../shared/foo.md", cap_md, skill_root,
            )
        self.assertIsNone(replacement)

    def test_absolute_path_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            replacement = compute_recommended_replacement(
                "/etc/passwd", os.path.join(tmp, "SKILL.md"), tmp,
            )
        self.assertIsNone(replacement)

    def test_already_valid_file_relative_link_is_not_rewritten(self) -> None:
        # A capability-local link ``references/foo.md`` from
        # ``capabilities/demo/capability.md`` resolves file-relative
        # to ``capabilities/demo/references/foo.md``.  If the skill
        # root *also* has ``references/foo.md`` (a different file),
        # the legacy skill-root resolution would land on a real file
        # — but rewriting the working link to ``../../references/foo.md``
        # would silently re-target it from the capability-local file
        # to the unrelated shared-root file, breaking the link's
        # meaning.  The rewriter must skip refs whose file-relative
        # form already resolves to an in-scope file.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            # Shared-root foo.md (different file).
            write_text(
                os.path.join(tmp, "references", "foo.md"),
                "# Shared-root foo\n",
            )
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            cap_md = os.path.join(cap_dir, "capability.md")
            write_text(cap_md, "# Demo\n")
            # Capability-local foo.md (different file).
            write_text(
                os.path.join(cap_dir, "references", "foo.md"),
                "# Capability-local foo\n",
            )
            replacement = compute_recommended_replacement(
                "references/foo.md", cap_md, tmp,
            )
        # The link already resolves correctly under file-relative —
        # rewriting it would silently break the author's intent.
        self.assertIsNone(replacement)

    def test_drive_qualified_path_returns_none(self) -> None:
        # Windows drive-qualified refs like ``C:foo.md`` are not
        # caught by ``os.path.isabs`` but ``os.path.join(skill_root,
        # 'C:foo.md')`` drops the skill root entirely on Windows,
        # which would let the rewriter probe an out-of-skill file
        # and emit an out-of-skill replacement.  The shared
        # ``is_drive_qualified`` helper recognizes the form on every
        # platform — using ``os.path.splitdrive`` here would silently
        # pass on POSIX (it returns ``('', 'C:foo.md')``) and the
        # rejection would be inconsistent between the OSes the
        # foundry CI runs on.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            replacement = compute_recommended_replacement(
                "C:foo.md", os.path.join(tmp, "SKILL.md"), tmp,
            )
        self.assertIsNone(replacement)

    def test_anchor_suffix_is_preserved(self) -> None:
        # A legacy capability link with an anchor (``#section``) is a
        # mechanically fixable path-resolution issue: the filesystem
        # check must run on the path alone, but the anchor must
        # survive the rewrite verbatim.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "guide.md"), "# Guide\n",
            )
            cap_md = os.path.join(tmp, "capabilities", "demo", "capability.md")
            write_text(cap_md, "# Demo\n")
            replacement = compute_recommended_replacement(
                "references/guide.md#section", cap_md, tmp,
            )
        self.assertEqual(
            replacement, "../../references/guide.md#section",
        )

    def test_query_and_title_suffixes_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "guide.md"), "# Guide\n",
            )
            cap_md = os.path.join(tmp, "capabilities", "demo", "capability.md")
            write_text(cap_md, "# Demo\n")
            replacement_q = compute_recommended_replacement(
                "references/guide.md?v=2", cap_md, tmp,
            )
            replacement_t = compute_recommended_replacement(
                'references/guide.md "Title"', cap_md, tmp,
            )
        self.assertEqual(replacement_q, "../../references/guide.md?v=2")
        self.assertEqual(replacement_t, '../../references/guide.md "Title"')


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

    def test_query_suffixed_link_is_picked_up_by_walker(self) -> None:
        # A capability link with a query suffix
        # (``references/guide.md?v=2``) is a legitimate markdown
        # link.  The glob-metachar filter excludes ``?``, but the
        # filter must run on the path portion only — otherwise the
        # walker would drop a query-suffixed ref before
        # ``compute_recommended_replacement`` got a chance to rewrite
        # it, even though the rewriter's own API explicitly supports
        # preserving query suffixes through the rewrite.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "guide.md"), "# Guide\n",
            )
            cap_md = os.path.join(
                tmp, "capabilities", "demo", "capability.md",
            )
            write_text(
                cap_md,
                "# Demo\nSee [g](references/guide.md?v=2).\n",
            )
            rows = find_fixable_references(tmp)
        cap_rows = [
            r for r in rows
            if r["file_rel"].endswith("capability.md")
        ]
        self.assertEqual(len(cap_rows), 1)
        self.assertEqual(cap_rows[0]["original"], "references/guide.md?v=2")
        self.assertEqual(
            cap_rows[0]["replacement"],
            "../../references/guide.md?v=2",
        )

    def test_line_number_points_to_rewriteable_occurrence(self) -> None:
        # If the same legacy path appears first inside a fenced code
        # block (which ``apply_fixes`` leaves untouched) and later
        # outside as a real link, the reported ``line`` must point at
        # the real link — that's the line ``apply_fixes`` will
        # actually modify.  Otherwise the dry-run / JSON row sends
        # consumers to a fenced example that never changes.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "guide.md"), "# Guide\n",
            )
            cap_md = os.path.join(tmp, "capabilities", "demo", "capability.md")
            write_text(
                cap_md,
                "# Demo\n"
                "\n"
                "Example fence:\n"
                "\n"
                "```markdown\n"
                "[g](references/guide.md)\n"      # line 6, fenced
                "```\n"
                "\n"
                "Real link: [g](references/guide.md).\n"   # line 9, rewriteable
            )
            rows = find_fixable_references(tmp)
        capture = [r for r in rows if r["file_rel"].endswith("capability.md")]
        self.assertEqual(len(capture), 1)
        self.assertEqual(capture[0]["line"], 9)

    def test_line_number_skips_frontmatter(self) -> None:
        # ``apply_fixes`` skips YAML frontmatter during rewrite, so
        # the reported ``line`` must skip it too — otherwise a
        # legacy ref string that happens to appear inside a folded
        # ``description`` would surface a frontmatter line that the
        # eventual write never touches, sending consumers to the
        # wrong place.  Pin that the reported line is the body
        # occurrence.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "guide.md"), "# Guide\n",
            )
            cap_md = os.path.join(tmp, "capabilities", "demo", "capability.md")
            # Frontmatter ``description`` mentions the same legacy
            # path as the body link below.  Without the frontmatter
            # skip the reported line would be 3 (the description),
            # not 8 (the actual rewriteable body line).
            write_text(
                cap_md,
                "---\n"                                            # 1
                "name: demo\n"                                     # 2
                "description: see references/guide.md for setup\n" # 3
                "---\n"                                            # 4
                "# Demo\n"                                         # 5
                "\n"                                               # 6
                "\n"                                               # 7
                "Body link: [g](references/guide.md).\n"           # 8
            )
            rows = find_fixable_references(tmp)
        capture = [r for r in rows if r["file_rel"].endswith("capability.md")]
        self.assertEqual(len(capture), 1)
        self.assertEqual(capture[0]["line"], 8)

    def test_excludes_capability_local_scripts_and_assets_subtrees(self) -> None:
        # Top-level pruning isn't enough: capability-local
        # ``capabilities/<name>/scripts/`` and ``assets/`` markdown
        # content is *also* outside the prose link graph and must
        # not be rewritten by ``--fix --apply``.  Without component-
        # based pruning, a markdown asset under
        # ``capabilities/<name>/assets/`` could be mutated during a
        # routine fix run, silently changing template fixtures the
        # author did not expect to be touched.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "guide.md"), "# Guide\n",
            )
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            # Both of these would otherwise produce rewrite suggestions
            # — they live under capability-local excluded subtrees, so
            # the walker must skip them entirely.
            write_text(
                os.path.join(cap_dir, "scripts", "doc.md"),
                "# Doc\nSee [g](references/guide.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "assets", "template.md"),
                "# Template\nSee [g](references/guide.md).\n",
            )
            rows = find_fixable_references(tmp)
        for r in rows:
            self.assertNotIn("scripts/", r["file_rel"])
            self.assertNotIn("assets/", r["file_rel"])

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

    def test_does_not_rewrite_inside_fenced_blocks(self) -> None:
        # ``find_fixable_references`` strips fenced blocks before
        # scanning, so a path mentioned only inside a fence is never
        # in *rows*.  When the same path *also* appears outside a
        # fence (which is in *rows*), the rewrite must touch only the
        # outside occurrence — example links in ```yaml/```markdown
        # fences must survive untouched.
        with tempfile.TemporaryDirectory() as tmp:
            ref_a = os.path.join(tmp, "ref.md")
            write_text(
                ref_a,
                "Real link: [a](references/x.md)\n"
                "\n"
                "```markdown\n"
                "Example: [a](references/x.md)\n"
                "```\n",
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
        # Outside the fence: rewritten.
        self.assertIn("Real link: [a](x.md)", content)
        # Inside the fence: untouched.
        self.assertIn("Example: [a](references/x.md)", content)

    def test_does_not_rewrite_inside_frontmatter(self) -> None:
        # ``find_fixable_references`` strips YAML frontmatter before
        # scanning, so a path mentioned in frontmatter (e.g. quoted
        # inside a folded ``description``) is never in *rows*.  When
        # the same path *also* appears in the body, the rewrite must
        # touch only the body occurrence — frontmatter metadata that
        # the scan deliberately excluded must not be mutated by
        # ``--fix --apply``.
        with tempfile.TemporaryDirectory() as tmp:
            ref_a = os.path.join(tmp, "ref.md")
            write_text(
                ref_a,
                "---\n"
                "name: t\n"
                "description: >\n"
                "  Mentions references/x.md in the description.\n"
                "---\n"
                "\n"
                "Real link: [a](references/x.md)\n",
            )
            rows = [{
                "file": ref_a,
                "file_rel": "ref.md",
                "original": "references/x.md",
                "replacement": "x.md",
                "line": 8,
            }]
            modified = apply_fixes(rows)
            with open(ref_a, "r", encoding="utf-8") as f:
                content = f.read()
        self.assertEqual(modified, 1)
        # Frontmatter occurrence: untouched (still says references/x.md).
        self.assertIn(
            "Mentions references/x.md in the description",
            content,
        )
        # Body occurrence: rewritten.
        self.assertIn("Real link: [a](x.md)", content)

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


class DetectAmbiguousLegacyTargetTests(unittest.TestCase):
    """``detect_ambiguous_legacy_target`` returns ``(legacy, file_rel)``
    only when both resolutions land on existing in-scope files that
    are *different*.  Every other case must return ``None`` so the
    rewriter (and the conformance gate) cannot surface a false
    ambiguous finding for a normal link."""

    def _write_skill(self, tmp: str) -> str:
        skill = os.path.join(tmp, "skill")
        write_text(os.path.join(skill, "SKILL.md"), "---\nname: t\n---\n")
        return skill

    def test_ambiguous_returns_both_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            # Shared-root foo.md
            shared_root_foo = os.path.join(skill, "references", "foo.md")
            write_text(shared_root_foo, "# Shared\n")
            # Capability-local foo.md (different file)
            cap_md = os.path.join(skill, "capabilities", "demo", "capability.md")
            write_text(cap_md, "# Demo\n")
            cap_local_foo = os.path.join(
                skill, "capabilities", "demo", "references", "foo.md",
            )
            write_text(cap_local_foo, "# Local\n")
            result = detect_ambiguous_legacy_target(
                "references/foo.md", cap_md, skill,
            )
        self.assertIsNotNone(result)
        legacy_target, file_rel_target = result
        # ``detect_ambiguous_legacy_target`` returns native filesystem
        # paths (``os.path.normpath`` output), which use backslashes
        # on Windows.  Compare via ``samefile``-style normalization
        # so the test runs identically on POSIX and Windows.
        self.assertEqual(
            os.path.normcase(os.path.realpath(legacy_target)),
            os.path.normcase(os.path.realpath(shared_root_foo)),
        )
        self.assertEqual(
            os.path.normcase(os.path.realpath(file_rel_target)),
            os.path.normcase(os.path.realpath(cap_local_foo)),
        )

    def test_empty_ref_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            self.assertIsNone(
                detect_ambiguous_legacy_target(
                    "", os.path.join(skill, "SKILL.md"), skill,
                )
            )

    def test_absolute_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            self.assertIsNone(
                detect_ambiguous_legacy_target(
                    "/etc/passwd",
                    os.path.join(skill, "SKILL.md"),
                    skill,
                )
            )

    def test_drive_qualified_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            self.assertIsNone(
                detect_ambiguous_legacy_target(
                    "C:foo.md",
                    os.path.join(skill, "SKILL.md"),
                    skill,
                )
            )

    def test_dot_slash_prefix_returns_none(self) -> None:
        # Already file-relative — author trusted to know what they wrote.
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            self.assertIsNone(
                detect_ambiguous_legacy_target(
                    "./foo.md",
                    os.path.join(skill, "SKILL.md"),
                    skill,
                )
            )

    def test_dot_dot_slash_prefix_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            cap_md = os.path.join(
                skill, "capabilities", "demo", "capability.md",
            )
            write_text(cap_md, "# Demo\n")
            self.assertIsNone(
                detect_ambiguous_legacy_target(
                    "../../references/foo.md", cap_md, skill,
                )
            )

    def test_legacy_outside_skill_returns_none(self) -> None:
        # ``references/../../foo.md`` normalizes outside the skill;
        # legacy escape rules out ambiguity.
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            cap_md = os.path.join(
                skill, "capabilities", "demo", "capability.md",
            )
            write_text(cap_md, "# Demo\n")
            self.assertIsNone(
                detect_ambiguous_legacy_target(
                    "references/../../foo.md", cap_md, skill,
                )
            )

    def test_legacy_missing_returns_none(self) -> None:
        # legacy_target normalizes inside skill but the file does not exist
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            cap_md = os.path.join(
                skill, "capabilities", "demo", "capability.md",
            )
            write_text(cap_md, "# Demo\n")
            self.assertIsNone(
                detect_ambiguous_legacy_target(
                    "references/missing.md", cap_md, skill,
                )
            )

    def test_file_rel_missing_returns_none(self) -> None:
        # legacy resolves but file-relative target doesn't exist —
        # this is the rewrite-eligible case, not ambiguous.
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            write_text(
                os.path.join(skill, "references", "foo.md"),
                "# Foo\n",
            )
            cap_md = os.path.join(
                skill, "capabilities", "demo", "capability.md",
            )
            write_text(cap_md, "# Demo\n")
            self.assertIsNone(
                detect_ambiguous_legacy_target(
                    "references/foo.md", cap_md, skill,
                )
            )

    def test_same_file_returns_none(self) -> None:
        # Both resolutions land on the same file (e.g. SKILL.md → references/x.md
        # — legacy = file_rel because SKILL.md sits at skill root).
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._write_skill(tmp)
            write_text(
                os.path.join(skill, "references", "x.md"),
                "# X\n",
            )
            self.assertIsNone(
                detect_ambiguous_legacy_target(
                    "references/x.md",
                    os.path.join(skill, "SKILL.md"),
                    skill,
                )
            )

class FindAmbiguousLegacyRefsTests(unittest.TestCase):
    """``find_ambiguous_legacy_refs`` walks the skill and returns one
    row per ambiguous ref, with both targets and the rewriteable
    line number.  Pruning matches ``find_fixable_references``."""

    def test_collects_ambiguous_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "foo.md"),
                "# Shared\n",
            )
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [f](references/foo.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "references", "foo.md"),
                "# Local\n",
            )
            rows = find_ambiguous_legacy_refs(tmp)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["file_rel"], "capabilities/demo/capability.md")
        self.assertEqual(row["original"], "references/foo.md")
        self.assertEqual(row["legacy_target"], "references/foo.md")
        self.assertEqual(
            row["file_rel_target"],
            "capabilities/demo/references/foo.md",
        )
        self.assertGreater(row["line"], 0)

    def test_prunes_capability_local_assets_and_scripts(self) -> None:
        # Same component-based pruning rule as the rewriter scan —
        # capability-local assets/scripts must not contribute rows.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "foo.md"),
                "# Shared\n",
            )
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            # Place an ambiguous-shaped link inside an excluded subtree.
            write_text(
                os.path.join(cap_dir, "assets", "template.md"),
                "# Template\n\nSee [f](references/foo.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "scripts", "doc.md"),
                "# Doc\n\nSee [f](references/foo.md).\n",
            )
            rows = find_ambiguous_legacy_refs(tmp)
        for r in rows:
            self.assertNotIn("assets/", r["file_rel"])
            self.assertNotIn("scripts/", r["file_rel"])

    def test_skips_template_placeholder_refs(self) -> None:
        # Refs containing ``<`` or ``>`` are template placeholders.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [f](references/<placeholder>.md).\n",
            )
            rows = find_ambiguous_legacy_refs(tmp)
        self.assertEqual(rows, [])

    def test_unreadable_file_is_skipped(self) -> None:
        # A file whose UTF-8 read fails should not abort the walk —
        # other files must still produce rows.  Simulate by creating
        # a markdown file with non-UTF-8 bytes.
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "SKILL.md"), "---\nname: t\n---\n")
            write_text(
                os.path.join(tmp, "references", "foo.md"),
                "# Shared\n",
            )
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [f](references/foo.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "references", "foo.md"),
                "# Local\n",
            )
            # Drop a non-UTF-8 file under references/
            with open(
                os.path.join(tmp, "references", "binary.md"),
                "wb",
            ) as f:
                f.write(b"\xff\xfe\x00bad utf-8\n")
            rows = find_ambiguous_legacy_refs(tmp)
        # The capability link still produces an ambiguous row; the
        # unreadable file is silently skipped.
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
