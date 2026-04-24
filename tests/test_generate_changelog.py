"""Tests for scripts/generate_changelog.py.

Git is stubbed by monkey-patching ``run_git`` and ``tag_exists`` so
every test is hermetic — no real repository, no subprocess calls.
This keeps the suite fast and portable (CI runs on Linux and Windows).
"""

import io
import os
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import generate_changelog as gc  # noqa: E402


VERB_MAP = {
    "Add": "Added",
    "Update": "Changed",
    "Refactor": "Changed",
    "Increase": "Changed",
    "Fix": "Fixed",
    "Remove": "Removed",
}


# ===================================================================
# Configuration loading
# ===================================================================


class LoadVerbMappingTests(unittest.TestCase):
    """``load_verb_mapping`` inverts YAML sections to a flat verb lookup."""

    def test_real_configuration_loads(self) -> None:
        mapping = gc.load_verb_mapping()
        self.assertEqual(mapping["Add"], "Added")
        self.assertEqual(mapping["Update"], "Changed")
        self.assertEqual(mapping["Fix"], "Fixed")
        self.assertEqual(mapping["Remove"], "Removed")

    def test_extended_changed_verbs_present(self) -> None:
        mapping = gc.load_verb_mapping()
        for verb in ("Increase", "Enforce", "Restructure"):
            self.assertEqual(mapping[verb], "Changed")

    def test_unknown_verb_missing(self) -> None:
        mapping = gc.load_verb_mapping()
        self.assertNotIn("Replace", mapping)
        self.assertNotIn("Tweak", mapping)

    def test_security_and_deprecated_verbs_present(self) -> None:
        mapping = gc.load_verb_mapping()
        self.assertEqual(mapping["Deprecate"], "Deprecated")
        self.assertEqual(mapping["Patch"], "Security")
        self.assertEqual(mapping["Secure"], "Security")
        self.assertEqual(mapping["Mitigate"], "Security")

    def test_bump_verb_routes_to_changed(self) -> None:
        # Dependency-upgrade commits ("Bump X to Y") are the dominant
        # non-"Update" verb in practice; without a mapping they would hit
        # the unmapped path at every release.
        mapping = gc.load_verb_mapping()
        self.assertEqual(mapping["Bump"], "Changed")

    def test_unknown_section_rejected(self) -> None:
        bad = (
            "changelog:\n"
            "  verb_mapping:\n"
            "    Bogus:\n"
            "      - Tweak\n"
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False,
        ) as fh:
            fh.write(bad)
            path = fh.name
        try:
            with self.assertRaises(RuntimeError) as ctx:
                gc.load_verb_mapping(path)
            self.assertIn("Bogus", str(ctx.exception))
            self.assertIn("SECTION_ORDER", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_non_list_verb_entry_rejected(self) -> None:
        # A scalar where a list is expected (e.g., ``Added: Add`` instead
        # of ``Added: [Add]``) should fail loudly — silently dropping the
        # section would leave its verbs unclassified at release time.
        bad = (
            "changelog:\n"
            "  verb_mapping:\n"
            "    Added: Add\n"
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False,
        ) as fh:
            fh.write(bad)
            path = fh.name
        try:
            with self.assertRaises(RuntimeError) as ctx:
                gc.load_verb_mapping(path)
            self.assertIn("Added", str(ctx.exception))
            self.assertIn("must be a list", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_missing_changelog_block_rejected(self) -> None:
        # A config file that lacks the ``changelog.verb_mapping`` block
        # must fail loudly rather than silently routing every commit to
        # unmapped with no explanation.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False,
        ) as fh:
            fh.write("other:\n  key: value\n")
            path = fh.name
        try:
            with self.assertRaises(RuntimeError) as ctx:
                gc.load_verb_mapping(path)
            self.assertIn("changelog.verb_mapping", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_duplicate_verb_across_sections_rejected(self) -> None:
        # A verb listed under two sections would otherwise silently
        # route to whichever section loaded second — a YAML typo that
        # quietly reclassifies commits.  Fail loudly so the duplicate
        # is surfaced at config-load time.
        bad = (
            "changelog:\n"
            "  verb_mapping:\n"
            "    Added:\n"
            "      - Add\n"
            "    Changed:\n"
            "      - Add\n"
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False,
        ) as fh:
            fh.write(bad)
            path = fh.name
        try:
            with self.assertRaises(RuntimeError) as ctx:
                gc.load_verb_mapping(path)
            message = str(ctx.exception)
            self.assertIn("'Add'", message)
            self.assertIn("Added", message)
            self.assertIn("Changed", message)
        finally:
            os.unlink(path)

    def test_non_mapping_verb_mapping_rejected(self) -> None:
        # ``verb_mapping: [Add, Fix]`` (a list instead of a mapping)
        # would previously raise ``AttributeError`` on ``.items()``;
        # it now raises ``RuntimeError`` with a clear message.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False,
        ) as fh:
            fh.write("changelog:\n  verb_mapping:\n    - Add\n    - Fix\n")
            path = fh.name
        try:
            with self.assertRaises(RuntimeError) as ctx:
                gc.load_verb_mapping(path)
            self.assertIn("must be a mapping", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_non_mapping_top_level_yaml_rejected(self) -> None:
        # Defensive guard: if the YAML parser ever returns a non-dict
        # top-level value (a list, a scalar), ``config.get("changelog")``
        # would raise AttributeError and escape past main()'s
        # RuntimeError/OSError/ValueError handler.  The foundry's
        # current stdlib parser happens to coerce such input to ``{}``,
        # so we stub the parser here to exercise the guard.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False,
        ) as fh:
            fh.write("(parser stubbed)\n")
            path = fh.name
        try:
            with mock.patch.object(
                gc, "_require_yaml_parser",
                return_value=lambda _text: ["Add", "Fix"],
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    gc.load_verb_mapping(path)
            message = str(ctx.exception)
            self.assertIn("top-level mapping", message)
            self.assertIn("list", message)
        finally:
            os.unlink(path)

    def test_non_string_verb_element_rejected(self) -> None:
        # Regression guard: a nested mapping in place of a plain verb
        # string (e.g. ``- Add: true``) used to raise TypeError at
        # ``verb in flat``, which main() does not catch — the traceback
        # would escape instead of the documented error: / exit 2
        # contract.  Validate each list element as a string first.
        #
        # parse_yaml_subset turns ``- key: value`` into ``[{"key":
        # "value"}]`` inside the list, so this is the realistic shape
        # a typo would produce.
        bad = (
            "changelog:\n"
            "  verb_mapping:\n"
            "    Added:\n"
            "      - Add: true\n"
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False,
        ) as fh:
            fh.write(bad)
            path = fh.name
        try:
            with self.assertRaises(RuntimeError) as ctx:
                gc.load_verb_mapping(path)
            message = str(ctx.exception)
            self.assertIn("Added", message)
            self.assertIn("must contain only strings", message)
        finally:
            os.unlink(path)


# ===================================================================
# Classification
# ===================================================================


class ClassifyCommitsTests(unittest.TestCase):
    """First-word bucketing, multi-verb handling, unmapped routing."""

    def test_simple_bucketing(self) -> None:
        commits = [
            ("aaa", "Add feature X"),
            ("bbb", "Fix bug Y"),
            ("ccc", "Update module Z"),
        ]
        buckets, unmapped = gc.classify_commits(commits, VERB_MAP)
        self.assertEqual(buckets["Added"], ["Add feature X"])
        self.assertEqual(buckets["Fixed"], ["Fix bug Y"])
        self.assertEqual(buckets["Changed"], ["Update module Z"])
        self.assertEqual(buckets["Removed"], [])
        self.assertEqual(unmapped, [])

    def test_unmapped_verb_routed(self) -> None:
        commits = [("zzz", "Replace bundle.py with simple zip")]
        buckets, unmapped = gc.classify_commits(commits, VERB_MAP)
        for section in gc.SECTION_ORDER:
            self.assertEqual(buckets[section], [])
        self.assertEqual(unmapped, [("zzz", "Replace bundle.py with simple zip")])

    def test_multi_verb_uses_first_word(self) -> None:
        commits = [("abc", "Update X and add Y")]
        buckets, _ = gc.classify_commits(commits, VERB_MAP)
        self.assertEqual(buckets["Changed"], ["Update X and add Y"])

    def test_extended_verb_restructure(self) -> None:
        commits = [("rrr", "Restructure foundry into router")]
        map_with_restructure = {**VERB_MAP, "Restructure": "Changed"}
        buckets, unmapped = gc.classify_commits(commits, map_with_restructure)
        self.assertEqual(buckets["Changed"], ["Restructure foundry into router"])
        self.assertEqual(unmapped, [])

    def test_empty_commit_list(self) -> None:
        buckets, unmapped = gc.classify_commits([], VERB_MAP)
        for section in gc.SECTION_ORDER:
            self.assertEqual(buckets[section], [])
        self.assertEqual(unmapped, [])

    def test_preserves_order(self) -> None:
        commits = [
            ("1", "Add A"),
            ("2", "Add B"),
            ("3", "Add C"),
        ]
        buckets, _ = gc.classify_commits(commits, VERB_MAP)
        self.assertEqual(buckets["Added"], ["Add A", "Add B", "Add C"])


# ===================================================================
# Rendering
# ===================================================================


class RenderSectionTests(unittest.TestCase):
    """Markdown output — heading format, subsection ordering, empty omission."""

    def test_heading_format(self) -> None:
        section = gc.render_section("1.2.3", "2026-04-01", {})
        self.assertTrue(section.startswith("## [1.2.3] - 2026-04-01"))

    def test_empty_subsections_omitted(self) -> None:
        buckets = {"Added": ["Add X"], "Changed": [], "Fixed": [], "Removed": []}
        section = gc.render_section("1.0.0", "2026-01-01", buckets)
        self.assertIn("### Added", section)
        self.assertNotIn("### Changed", section)
        self.assertNotIn("### Fixed", section)
        self.assertNotIn("### Removed", section)

    def test_subsection_order_is_fixed(self) -> None:
        # Canonical Keep-a-Changelog order — matches SECTION_ORDER.
        buckets = {
            "Security": ["Patch S"],
            "Fixed": ["Fix F"],
            "Removed": ["Remove R"],
            "Deprecated": ["Deprecate D"],
            "Changed": ["Update C"],
            "Added": ["Add A"],
        }
        section = gc.render_section("1.0.0", "2026-01-01", buckets)
        positions = [section.index(f"### {name}") for name in gc.SECTION_ORDER]
        self.assertEqual(positions, sorted(positions))

    def test_entries_rendered_as_list_items(self) -> None:
        buckets = {"Added": ["Add feature X (#42)"], "Changed": [], "Fixed": [], "Removed": []}
        section = gc.render_section("1.0.0", "2026-01-01", buckets)
        self.assertIn("- Add feature X (#42)", section)


# ===================================================================
# Splicing
# ===================================================================


NEW_SECTION = "## [1.1.0] - 2026-03-22\n\n### Added\n\n- Add X\n"


class SpliceIntoChangelogTests(unittest.TestCase):
    """Insertion after H1, preamble synthesis, preservation of prior sections."""

    def test_insert_after_h1(self) -> None:
        existing = (
            "# Changelog\n"
            "\n"
            "Intro text.\n"
            "\n"
            "## [1.0.0] - 2026-01-01\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        h1_pos = merged.index("# Changelog")
        new_pos = merged.index("## [1.1.0]")
        old_pos = merged.index("## [1.0.0]")
        self.assertLess(h1_pos, new_pos)
        self.assertLess(new_pos, old_pos)

    def test_prior_sections_preserved(self) -> None:
        existing = (
            "# Changelog\n"
            "\n"
            "## [1.0.0] - 2026-01-01\n"
            "\n"
            "### Added\n"
            "\n"
            "- Initial release\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        self.assertIn("## [1.0.0] - 2026-01-01", merged)
        self.assertIn("- Initial release", merged)

    def test_empty_existing_synthesizes_preamble_and_inserts_section(self) -> None:
        merged = gc.splice_into_changelog("", NEW_SECTION)
        self.assertTrue(merged.startswith("# Changelog"))
        self.assertIn("Keep a Changelog", merged)
        self.assertIn("## [1.1.0] - 2026-03-22", merged)

    def test_duplicate_version_raises(self) -> None:
        existing = (
            "# Changelog\n"
            "\n"
            "## [1.1.0] - 2026-03-22\n"
            "\n"
            "### Added\n"
            "\n"
            "- Old entry\n"
        )
        with self.assertRaises(RuntimeError) as ctx:
            gc.splice_into_changelog(existing, NEW_SECTION)
        self.assertIn("1.1.0", str(ctx.exception))
        self.assertIn("already contains", str(ctx.exception))

    def test_different_version_splices_alongside_existing(self) -> None:
        existing = (
            "# Changelog\n"
            "\n"
            "## [1.0.0] - 2026-01-01\n"
            "\n"
            "- Initial\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        self.assertIn("## [1.1.0]", merged)
        self.assertIn("## [1.0.0]", merged)

    def test_version_prefix_is_not_false_match(self) -> None:
        # Existing section for 1.1.0 must NOT trip a duplicate check
        # when the new section is for 1.1 — the two are distinct
        # versions and the guard must compare by extracted token, not
        # substring prefix.  (1.1 itself would be rejected by the CLI
        # semver validator, but splice_into_changelog is tested in
        # isolation.)
        existing = (
            "# Changelog\n"
            "\n"
            "## [1.1.0] - 2026-03-22\n"
            "\n"
            "- Existing\n"
        )
        new_for_prefix = "## [1.1] - 2026-04-01\n\n### Added\n\n- Add Y\n"
        merged = gc.splice_into_changelog(existing, new_for_prefix)
        self.assertIn("## [1.1]", merged)
        self.assertIn("## [1.1.0]", merged)

    def test_prerelease_does_not_match_release(self) -> None:
        # 1.1.0 is not a duplicate of 1.1.0-rc.1 — both should coexist.
        existing = (
            "# Changelog\n"
            "\n"
            "## [1.1.0-rc.1] - 2026-03-22\n"
            "\n"
            "- RC entry\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        self.assertIn("## [1.1.0]", merged)
        self.assertIn("## [1.1.0-rc.1]", merged)

    def test_build_metadata_matches_plain_release(self) -> None:
        # Per semver 2.0.0 §10, build metadata does not affect
        # precedence: 1.1.0 and 1.1.0+build.42 are the same version
        # for uniqueness purposes.  The splice guard must refuse a
        # new 1.1.0+build.42 when 1.1.0 already exists (and vice
        # versa) rather than letting both coexist.
        existing = (
            "# Changelog\n"
            "\n"
            "## [1.1.0] - 2026-03-22\n"
            "\n"
            "- Existing\n"
        )
        new_with_build = "## [1.1.0+build.42] - 2026-04-01\n\n### Added\n\n- Add Y\n"
        with self.assertRaises(RuntimeError) as ctx:
            gc.splice_into_changelog(existing, new_with_build)
        self.assertIn("1.1.0", str(ctx.exception))
        self.assertIn("already contains", str(ctx.exception))

    def test_build_metadata_in_existing_matches_plain_new(self) -> None:
        # Symmetric case: 1.1.0+build.42 already in CHANGELOG must
        # block a new 1.1.0 (same version per semver precedence).
        existing = (
            "# Changelog\n"
            "\n"
            "## [1.1.0+build.42] - 2026-03-22\n"
            "\n"
            "- Existing\n"
        )
        with self.assertRaises(RuntimeError) as ctx:
            gc.splice_into_changelog(existing, NEW_SECTION)
        self.assertIn("1.1.0", str(ctx.exception))
        self.assertIn("already contains", str(ctx.exception))

    def test_v_prefix_in_existing_matches_plain_new(self) -> None:
        # ``normalize_version`` strips ``v`` from the emitted heading,
        # so an existing ``## [v1.1.0]`` (common in hand-edited
        # CHANGELOGs) must still block a newly-emitted ``## [1.1.0]``.
        existing = (
            "# Changelog\n"
            "\n"
            "## [v1.1.0] - 2026-03-22\n"
            "\n"
            "- Existing\n"
        )
        with self.assertRaises(RuntimeError) as ctx:
            gc.splice_into_changelog(existing, NEW_SECTION)
        self.assertIn("1.1.0", str(ctx.exception))
        self.assertIn("already contains", str(ctx.exception))

    def test_preamble_is_preserved_between_h1_and_new_release(self) -> None:
        # Regression: splice used to insert between the H1 and the
        # preamble, pushing "All notable changes..." below the new
        # release.  The anchor is now the first ``## [`` section, so
        # preamble stays intact above the new entry.
        existing = (
            "# Changelog\n"
            "\n"
            "All notable changes to this project are documented in this file.\n"
            "\n"
            "The format is based on Keep a Changelog.\n"
            "\n"
            "## [1.0.0] - 2026-01-01\n"
            "\n"
            "- Initial release\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        h1_pos = merged.index("# Changelog")
        preamble_pos = merged.index("All notable changes")
        format_pos = merged.index("The format is based on")
        new_pos = merged.index("## [1.1.0]")
        old_pos = merged.index("## [1.0.0]")
        # Preamble paragraphs stay right under the H1, new release
        # slots in between the preamble and the previous release.
        self.assertLess(h1_pos, preamble_pos)
        self.assertLess(preamble_pos, format_pos)
        self.assertLess(format_pos, new_pos)
        self.assertLess(new_pos, old_pos)

    def test_fenced_version_heading_is_not_duplicate(self) -> None:
        # A ``## [1.1.0]`` line inside a ``` fence is an example, not a
        # real heading; it must not trip the duplicate-version guard.
        existing = (
            "# Changelog\n"
            "\n"
            "Example format:\n"
            "\n"
            "```md\n"
            "## [1.1.0] - 2026-03-22\n"
            "```\n"
            "\n"
            "## [1.0.0] - 2026-01-01\n"
            "\n"
            "- Initial release\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        # The new 1.1.0 release splices above 1.0.0, and the fenced
        # example survives unchanged above both.
        fence_pos = merged.index("```md")
        new_pos = merged.index("## [1.1.0] - 2026-03-22\n\n### Added")
        old_pos = merged.index("## [1.0.0]")
        self.assertLess(fence_pos, new_pos)
        self.assertLess(new_pos, old_pos)

    def test_fenced_version_heading_does_not_anchor_splice(self) -> None:
        # Without a real release section, the splice must not treat a
        # fenced example as an anchor and insert above it.
        existing = (
            "# Changelog\n"
            "\n"
            "```md\n"
            "## [0.9.0] - 2026-01-01\n"
            "```\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        fence_pos = merged.index("```md")
        new_pos = merged.index("## [1.1.0]")
        # New release lands below the fenced example, not above it.
        self.assertLess(fence_pos, new_pos)

    def test_appends_when_h1_only_has_preamble_no_release(self) -> None:
        # No ``## [`` section yet — the new release lands below the
        # existing preamble rather than between the H1 and the text.
        existing = (
            "# Changelog\n"
            "\n"
            "All notable changes to this project are documented in this file.\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        preamble_pos = merged.index("All notable changes")
        new_pos = merged.index("## [1.1.0]")
        self.assertLess(preamble_pos, new_pos)

    def test_unreleased_heading_is_not_an_anchor(self) -> None:
        # The Keep-a-Changelog convention keeps ``## [Unreleased]`` above
        # the latest release.  The splice must skip it as an anchor so
        # the new release lands BELOW Unreleased, not above it.
        existing = (
            "# Changelog\n"
            "\n"
            "## [Unreleased]\n"
            "\n"
            "- In-flight change\n"
            "\n"
            "## [1.0.0] - 2026-01-01\n"
            "\n"
            "- Initial release\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        unreleased_pos = merged.index("## [Unreleased]")
        new_pos = merged.index("## [1.1.0]")
        old_pos = merged.index("## [1.0.0]")
        self.assertLess(unreleased_pos, new_pos)
        self.assertLess(new_pos, old_pos)

    def test_non_h1_existing_content_rejected(self) -> None:
        # A non-empty CHANGELOG.md without a '# ' H1 heading is
        # unrecognized content.  Silently synthesizing a preamble on
        # top of it (and pushing the original text below the new
        # release) would be more surprising than raising — the caller
        # should add a heading or delete the file.
        existing = "Some notes that are not a changelog yet.\n"
        with self.assertRaises(RuntimeError) as ctx:
            gc.splice_into_changelog(existing, NEW_SECTION)
        message = str(ctx.exception)
        self.assertIn("H1", message)
        self.assertIn("refusing", message)

    def test_leading_text_before_h1_rejected(self) -> None:
        # Regression guard: ``any line starts with '# '`` used to
        # accept files with arbitrary leading text before the H1,
        # which would let the splice land at the bottom of a
        # malformed changelog.  Only a '# ' heading on the first
        # non-empty, non-fenced line should satisfy the H1 check.
        existing = (
            "Preface paragraph that has no business being here.\n"
            "\n"
            "# Changelog\n"
            "\n"
            "All notable changes…\n"
        )
        with self.assertRaises(RuntimeError) as ctx:
            gc.splice_into_changelog(existing, NEW_SECTION)
        message = str(ctx.exception)
        self.assertIn("H1", message)
        self.assertIn("refusing", message)

    def test_fenced_only_content_rejected(self) -> None:
        # Regression guard: a file whose only content lives inside
        # fenced code blocks leaves ``first_real_line`` unset because
        # ``_iter_heading_lines`` skips fenced lines.  Synthesizing a
        # preamble and returning ``preamble + new_section`` would
        # silently drop the original content — an in-place run would
        # be destructive.  Detect the non-empty-but-fenced-only case
        # from the raw text and raise.
        existing = (
            "```md\n"
            "## [0.9.0] - 2026-01-01\n"
            "- draft note\n"
            "```\n"
        )
        with self.assertRaises(RuntimeError) as ctx:
            gc.splice_into_changelog(existing, NEW_SECTION)
        message = str(ctx.exception)
        self.assertIn("fenced", message)
        self.assertIn("H1", message)

    def test_mixed_fence_markers_do_not_close_early(self) -> None:
        # Regression guard: the previous boolean toggle closed the
        # fence on any fence-looking line.  A ``` ``` block that
        # contains a ``~~~`` sequence inside it would therefore close
        # prematurely, exposing a ``## [X.Y.Z]`` inside the example
        # as a real release heading and causing the splice to pick a
        # wrong anchor.  CommonMark §4.5 requires the closing fence
        # to use the same character as the opener.
        existing = (
            "# Changelog\n"
            "\n"
            "```md\n"
            "Example showing nested tildes:\n"
            "~~~\n"
            "## [9.9.9] - 2099-01-01\n"
            "~~~\n"
            "```\n"
            "\n"
            "## [1.0.0] - 2026-01-01\n"
            "\n"
            "- Initial release\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        # The fenced ``## [9.9.9]`` is still inside the code block and
        # must not appear as a real heading; the new release anchors
        # against the real ``## [1.0.0]`` below the block.
        new_pos = merged.index("## [1.1.0] - 2026-03-22\n\n### Added")
        old_pos = merged.index("## [1.0.0] - 2026-01-01")
        self.assertLess(new_pos, old_pos)

    def test_short_inner_fence_does_not_close_longer_opener(self) -> None:
        # Regression guard: a ``````` (4-backtick) opener must only
        # close on a ``````` or longer backtick run.  The previous
        # toggle closed on any ```` ``` ```` run inside, exposing
        # headings inside the example as real release anchors.
        existing = (
            "# Changelog\n"
            "\n"
            "````md\n"
            "Triple backticks inside a four-backtick block:\n"
            "```\n"
            "## [9.9.9]\n"
            "```\n"
            "````\n"
            "\n"
            "## [1.0.0] - 2026-01-01\n"
            "\n"
            "- Initial release\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        new_pos = merged.index("## [1.1.0] - 2026-03-22\n\n### Added")
        old_pos = merged.index("## [1.0.0] - 2026-01-01")
        self.assertLess(new_pos, old_pos)

    def test_indented_fence_does_not_toggle(self) -> None:
        # CommonMark §4.5: indentation of 4+ spaces is an indented code
        # block, not a fence.  The previous ``^\s*`` regex treated any
        # leading whitespace as fence indentation, so a ``    ```md``
        # line inside an ordered-list continuation could flip
        # ``in_fence`` at the wrong time and mask a later release
        # anchor.  With the CommonMark-accurate regex, the real
        # ``## [1.0.0]`` heading below must still be treated as the
        # anchor.
        existing = (
            "# Changelog\n"
            "\n"
            "1. Historical note\n"
            "\n"
            "        ```md\n"  # 8 spaces — not a fence
            "        ## [9.9.9]\n"
            "        ```\n"
            "\n"
            "## [1.0.0] - 2026-01-01\n"
            "\n"
            "- Initial release\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        # New release lands immediately above the real 1.0.0 anchor,
        # not at the end of the file.
        new_pos = merged.index("## [1.1.0] - 2026-03-22\n\n### Added")
        old_pos = merged.index("## [1.0.0] - 2026-01-01")
        self.assertLess(new_pos, old_pos)

    def test_missing_h1_before_semver_anchor_rejected(self) -> None:
        # Regression guard: the H1 check used to run only when no
        # semver-shaped heading was found, so a file that starts with
        # ``## [1.0.0]`` (no parent '# ') would happily anchor and
        # splice, producing a non-Keep-a-Changelog shape.  The check
        # must run before the anchor scan.
        existing = (
            "## [1.0.0] - 2026-01-01\n"
            "\n"
            "- Initial release\n"
        )
        with self.assertRaises(RuntimeError) as ctx:
            gc.splice_into_changelog(existing, NEW_SECTION)
        message = str(ctx.exception)
        self.assertIn("H1", message)
        self.assertIn("refusing", message)

    def test_only_unreleased_falls_back_to_append(self) -> None:
        # If the only ``## [`` heading is ``[Unreleased]`` (no real
        # release yet), there is no semver anchor, so the new release
        # appends below the existing preamble / Unreleased block.
        existing = (
            "# Changelog\n"
            "\n"
            "## [Unreleased]\n"
            "\n"
            "- In-flight change\n"
        )
        merged = gc.splice_into_changelog(existing, NEW_SECTION)
        unreleased_pos = merged.index("## [Unreleased]")
        new_pos = merged.index("## [1.1.0]")
        self.assertLess(unreleased_pos, new_pos)


# ===================================================================
# Date resolution
# ===================================================================


class ResolveDateTests(unittest.TestCase):
    """Precedence: --date > tag commit date > today."""

    def test_override_wins(self) -> None:
        with mock.patch.object(gc, "tag_exists", return_value=True), \
             mock.patch.object(gc, "tag_commit_date", return_value="2026-03-22"):
            result = gc.resolve_date("1.1.0", "/tmp", "2025-12-31", "2026-04-23")
        self.assertEqual(result, "2025-12-31")

    def test_tag_date_when_tag_exists(self) -> None:
        with mock.patch.object(gc, "tag_exists", return_value=True), \
             mock.patch.object(gc, "tag_commit_date", return_value="2026-03-22"):
            result = gc.resolve_date("1.1.0", "/tmp", None, "2026-04-23")
        self.assertEqual(result, "2026-03-22")

    def test_today_when_tag_missing(self) -> None:
        with mock.patch.object(gc, "tag_exists", return_value=False):
            result = gc.resolve_date("2.0.0", "/tmp", None, "2026-04-23")
        self.assertEqual(result, "2026-04-23")

    def test_version_without_v_prefix_is_prefixed_for_tag_lookup(self) -> None:
        captured: list[str] = []

        def fake_tag_exists(tag: str, _repo: str) -> bool:
            captured.append(tag)
            return False

        with mock.patch.object(gc, "tag_exists", side_effect=fake_tag_exists):
            gc.resolve_date("1.1.0", "/tmp", None, "2026-04-23")
        self.assertEqual(captured, ["v1.1.0"])

    def test_version_with_v_prefix_not_double_prefixed(self) -> None:
        captured: list[str] = []

        def fake_tag_exists(tag: str, _repo: str) -> bool:
            captured.append(tag)
            return False

        with mock.patch.object(gc, "tag_exists", side_effect=fake_tag_exists):
            gc.resolve_date("v1.1.0", "/tmp", None, "2026-04-23")
        self.assertEqual(captured, ["v1.1.0"])


# ===================================================================
# Range endpoint resolution
# ===================================================================


class ResolveUntilTests(unittest.TestCase):
    def test_tag_exists_returns_tag(self) -> None:
        with mock.patch.object(gc, "tag_exists", return_value=True):
            self.assertEqual(gc.resolve_until("1.1.0", "/tmp"), "v1.1.0")

    def test_tag_missing_returns_head(self) -> None:
        with mock.patch.object(gc, "tag_exists", return_value=False):
            self.assertEqual(gc.resolve_until("2.0.0", "/tmp"), "HEAD")


# ===================================================================
# generate() end-to-end (pure function)
# ===================================================================


class GenerateTests(unittest.TestCase):
    """End-to-end assembly via mocked git plumbing."""

    def test_full_section_with_mix_of_sections(self) -> None:
        commits = [
            ("aaa", "Add feature X (#1)"),
            ("bbb", "Update module Y (#2)"),
            ("ccc", "Fix bug Z (#3)"),
        ]
        with mock.patch.object(gc, "tag_exists", return_value=True), \
             mock.patch.object(gc, "tag_commit_date", return_value="2026-03-22"), \
             mock.patch.object(gc, "collect_commits", return_value=commits):
            section, unmapped = gc.generate(
                since="v1.0.0",
                version="1.1.0",
                date_override=None,
                repo_root="/tmp",
                today="2026-04-23",
                verb_map=VERB_MAP,
            )
        self.assertIn("## [1.1.0] - 2026-03-22", section)
        self.assertIn("- Add feature X (#1)", section)
        self.assertIn("- Update module Y (#2)", section)
        self.assertIn("- Fix bug Z (#3)", section)
        self.assertEqual(unmapped, [])

    def test_unmapped_separated_from_rendered(self) -> None:
        commits = [
            ("aaa", "Add feature X"),
            ("zzz", "Replace bundle.py"),
        ]
        with mock.patch.object(gc, "tag_exists", return_value=True), \
             mock.patch.object(gc, "tag_commit_date", return_value="2026-03-22"), \
             mock.patch.object(gc, "collect_commits", return_value=commits):
            section, unmapped = gc.generate(
                since="v1.0.0",
                version="1.1.0",
                date_override=None,
                repo_root="/tmp",
                today="2026-04-23",
                verb_map=VERB_MAP,
            )
        self.assertIn("- Add feature X", section)
        self.assertNotIn("Replace bundle.py", section)
        self.assertEqual(unmapped, [("zzz", "Replace bundle.py")])

    def test_no_commits_yields_heading_only(self) -> None:
        with mock.patch.object(gc, "tag_exists", return_value=True), \
             mock.patch.object(gc, "tag_commit_date", return_value="2026-03-22"), \
             mock.patch.object(gc, "collect_commits", return_value=[]):
            section, unmapped = gc.generate(
                since="v1.0.0",
                version="1.1.0",
                date_override=None,
                repo_root="/tmp",
                today="2026-04-23",
                verb_map=VERB_MAP,
            )
        self.assertIn("## [1.1.0] - 2026-03-22", section)
        self.assertNotIn("### ", section)
        self.assertEqual(unmapped, [])


# ===================================================================
# Unmapped reporting
# ===================================================================


class ReportUnmappedTests(unittest.TestCase):
    def test_writes_sha_prefix_and_subject(self) -> None:
        buf = io.StringIO()
        gc.report_unmapped(
            [("abcdef1234567890abc", "Replace the widget")],
            buf,
        )
        out = buf.getvalue()
        self.assertIn("unmapped — review manually", out)
        self.assertIn("abcdef123456", out)
        self.assertIn("Replace the widget", out)

    def test_empty_list_writes_nothing(self) -> None:
        buf = io.StringIO()
        gc.report_unmapped([], buf)
        self.assertEqual(buf.getvalue(), "")


# ===================================================================
# CLI / main()
# ===================================================================


class MainCliTests(unittest.TestCase):
    """Exercises the main() entry point with git fully stubbed."""

    def _patch_git(self, commits: list[tuple[str, str]]):
        return mock.patch.multiple(
            gc,
            tag_exists=mock.MagicMock(return_value=True),
            tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
            collect_commits=mock.MagicMock(return_value=commits),
            find_repo_root=mock.MagicMock(return_value="/tmp/fake-repo"),
        )

    def test_default_prints_section_to_stdout(self) -> None:
        with self._patch_git([("aaa", "Add X")]):
            with mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()):
                rc = gc.main(["--since", "v1.0.0", "--version", "1.1.0"])
        self.assertEqual(rc, 0)
        self.assertIn("## [1.1.0]", out.getvalue())

    def test_unmapped_goes_to_stderr_and_exits_three(self) -> None:
        # Exit 3 is the "soft failure" signal reserved for human-review
        # situations; distinct from 2 (argparse / runtime error) so CI
        # pipelines can branch on "needs classification" vs "broken".
        with self._patch_git([("zzz", "Replace the thing")]):
            with mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()) as err:
                rc = gc.main(["--since", "v1.0.0", "--version", "1.1.0"])
        self.assertEqual(rc, 3)
        self.assertIn("unmapped", err.getvalue())
        self.assertNotIn("Replace the thing", out.getvalue())

    def test_invalid_version_is_rejected(self) -> None:
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            with self.assertRaises(SystemExit) as ctx:
                gc.main(["--since", "v1.0.0", "--version", "latest"])
        # argparse.error exits with code 2.
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--version", err.getvalue())

    def test_invalid_version_short_form_rejected(self) -> None:
        with mock.patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit):
                gc.main(["--since", "v1.0.0", "--version", "1.1"])

    def test_prerelease_version_accepted(self) -> None:
        with self._patch_git([("aaa", "Add X")]):
            with mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()):
                rc = gc.main(["--since", "v1.0.0", "--version", "1.1.0-rc.1"])
        self.assertEqual(rc, 0)
        self.assertIn("## [1.1.0-rc.1]", out.getvalue())

    def test_dry_run_without_in_place_rejected(self) -> None:
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            with self.assertRaises(SystemExit) as ctx:
                gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0", "--dry-run",
                ])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--dry-run", err.getvalue())

    def test_in_place_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            changelog = os.path.join(repo_root, "CHANGELOG.md")
            with open(changelog, "w", encoding="utf-8") as fh:
                fh.write("# Changelog\n\n## [1.0.0] - 2026-01-01\n")

            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=True),
                tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
                collect_commits=mock.MagicMock(return_value=[("a", "Add X")]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()), \
                 mock.patch("sys.stderr", new=io.StringIO()):
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0", "--in-place",
                ])
            self.assertEqual(rc, 0)
            with open(changelog, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("## [1.1.0]", content)
            self.assertIn("## [1.0.0]", content)

    def test_dry_run_with_in_place_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            changelog = os.path.join(repo_root, "CHANGELOG.md")
            original = "# Changelog\n\n## [1.0.0] - 2026-01-01\n"
            with open(changelog, "w", encoding="utf-8") as fh:
                fh.write(original)

            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=True),
                tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
                collect_commits=mock.MagicMock(return_value=[("a", "Add X")]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()):
                gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0",
                    "--in-place", "--dry-run",
                ])
            with open(changelog, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), original)
            self.assertIn("## [1.1.0]", out.getvalue())

    def test_in_place_write_preserves_lf_line_endings(self) -> None:
        # On Windows, default text-mode writes convert \n to \r\n.
        # The in-place write opens with newline="" to pin LF so the
        # CHANGELOG.md does not churn across CI platforms.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            changelog = os.path.join(repo_root, "CHANGELOG.md")
            with open(changelog, "w", encoding="utf-8", newline="") as fh:
                fh.write("# Changelog\n\n## [1.0.0] - 2026-01-01\n")

            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=True),
                tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
                collect_commits=mock.MagicMock(return_value=[("a", "Add X")]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()), \
                 mock.patch("sys.stderr", new=io.StringIO()):
                gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0", "--in-place",
                ])
            with open(changelog, "rb") as fh:
                raw = fh.read()
            self.assertNotIn(b"\r\n", raw)
            self.assertIn(b"## [1.1.0]", raw)

    def test_in_place_normalizes_crlf_on_read(self) -> None:
        # Regression guard: a Windows checkout with ``core.autocrlf=true``
        # yields CHANGELOG.md with CRLF line endings.  Previously the
        # in-place read opened with ``newline=""`` which preserved CRLF
        # and let stray ``\r`` characters survive the splice's
        # ``rstrip("\n")`` / manual ``"\n\n"`` joins.  The read must
        # use universal-newline translation so the splice sees LF-only
        # content and the written file has no CRLF.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            changelog = os.path.join(repo_root, "CHANGELOG.md")
            # Write raw CRLF bytes, bypassing text-mode translation, to
            # simulate a Windows checkout regardless of test platform.
            with open(changelog, "wb") as fh:
                fh.write(b"# Changelog\r\n\r\n## [1.0.0] - 2026-01-01\r\n")

            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=True),
                tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
                collect_commits=mock.MagicMock(return_value=[("a", "Add X")]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()), \
                 mock.patch("sys.stderr", new=io.StringIO()):
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0", "--in-place",
                ])
            self.assertEqual(rc, 0)
            with open(changelog, "rb") as fh:
                raw = fh.read()
            self.assertNotIn(b"\r", raw, "no CR byte should survive the splice")
            self.assertIn(b"## [1.1.0]", raw)
            self.assertIn(b"## [1.0.0]", raw)

    def test_date_override_wins(self) -> None:
        with self._patch_git([("a", "Add X")]):
            with mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()):
                gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0",
                    "--date", "2024-01-01",
                ])
        self.assertIn("## [1.1.0] - 2024-01-01", out.getvalue())

    def test_in_place_refuses_without_date_when_tag_absent(self) -> None:
        # Regression guard: the documented release flow generates
        # CHANGELOG.md before creating the tag, so the target tag
        # does not yet exist at generate time.  In that state
        # ``resolve_date`` would fall back to today's date, which is
        # wrong if the tag ends up being created on a different day.
        # Refuse the in-place write and point the operator at --date
        # so the stamp is deterministic.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=False),
                collect_commits=mock.MagicMock(return_value=[("a", "Add X")]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()), \
                 mock.patch("sys.stderr", new=io.StringIO()) as err:
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.2.0", "--in-place",
                ])
            self.assertEqual(rc, 2)
            message = err.getvalue()
            self.assertIn("error:", message)
            self.assertIn("--date", message)
            self.assertIn("v1.2.0", message)

    def test_in_place_allowed_without_date_when_tag_exists(self) -> None:
        # The refusal is only for the "tag does not yet exist" case —
        # retrospective regeneration of a tagged release must still
        # work without --date since the tag's committer date is the
        # authoritative source.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            changelog = os.path.join(repo_root, "CHANGELOG.md")
            with open(changelog, "w", encoding="utf-8") as fh:
                fh.write("# Changelog\n\n## [1.0.0] - 2026-01-01\n")
            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=True),
                tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
                collect_commits=mock.MagicMock(return_value=[("a", "Add X")]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()), \
                 mock.patch("sys.stderr", new=io.StringIO()):
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0", "--in-place",
                ])
            self.assertEqual(rc, 0)

    def test_stdout_mode_still_falls_back_to_today(self) -> None:
        # Previews (no --in-place) keep the today-fallback for
        # convenience; only the on-disk write is guarded.
        with mock.patch.multiple(
            gc,
            tag_exists=mock.MagicMock(return_value=False),
            collect_commits=mock.MagicMock(return_value=[("a", "Add X")]),
            find_repo_root=mock.MagicMock(return_value="/tmp/fake"),
        ):
            with mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()):
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.2.0",
                ])
        self.assertEqual(rc, 0)
        self.assertIn("## [1.2.0]", out.getvalue())

    def test_runtime_error_surfaced_and_exits_two(self) -> None:
        # A duplicate-version splice raises RuntimeError; main() must
        # turn that into an "error: ..." line on stderr and return 2
        # rather than leaking a traceback.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            changelog = os.path.join(repo_root, "CHANGELOG.md")
            with open(changelog, "w", encoding="utf-8") as fh:
                fh.write("# Changelog\n\n## [1.1.0] - 2026-03-22\n")

            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=True),
                tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
                collect_commits=mock.MagicMock(return_value=[("a", "Add X")]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()), \
                 mock.patch("sys.stderr", new=io.StringIO()) as err:
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0", "--in-place",
                ])
        self.assertEqual(rc, 2)
        self.assertIn("error:", err.getvalue())
        self.assertIn("already contains", err.getvalue())

    def test_build_metadata_version_rejected(self) -> None:
        # Release tags in this repo are ``vX.Y.Z`` only.  SemVer build
        # metadata is valid under the grammar but would splice a
        # ``## [X.Y.Z+build]`` heading that the duplicate-version guard
        # later collapses to plain ``X.Y.Z`` — blocking the real
        # release.  Reject at the CLI boundary.
        for bad in ("1.1.0+build.42", "1.1.0+1", "v1.1.0+a"):
            with mock.patch("sys.stderr", new=io.StringIO()) as err:
                with self.assertRaises(SystemExit) as ctx:
                    gc.main(["--since", "v1.0.0", "--version", bad])
            self.assertEqual(ctx.exception.code, 2, f"should reject {bad!r}")
            self.assertIn("build metadata", err.getvalue())

    def test_malformed_prerelease_rejected(self) -> None:
        # Lone dot is not a valid prerelease identifier per semver 2.0.0.
        with mock.patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                gc.main(["--since", "v1.0.0", "--version", "1.1.0-."])
        self.assertEqual(ctx.exception.code, 2)

    def test_leading_zero_numeric_core_rejected(self) -> None:
        # Semver 2.0.0 §2 forbids leading zeros on numeric identifiers
        # in the core version.  ``01.2.3`` must not splice into
        # CHANGELOG.md as a canonical release.
        for bad in ("01.2.3", "1.02.3", "1.2.03", "v01.2.3"):
            with mock.patch("sys.stderr", new=io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    gc.main(["--since", "v1.0.0", "--version", bad])
            self.assertEqual(ctx.exception.code, 2, f"should reject {bad!r}")

    def test_leading_zero_numeric_prerelease_rejected(self) -> None:
        # Semver 2.0.0 §9: numeric prerelease identifiers must not have
        # leading zeros.  ``1.2.3-01`` is invalid; ``1.2.3-0`` (plain 0)
        # and ``1.2.3-0a`` (alphanumeric, not purely numeric) are valid.
        for bad in ("1.1.0-01", "1.1.0-rc.01"):
            with mock.patch("sys.stderr", new=io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    gc.main(["--since", "v1.0.0", "--version", bad])
            self.assertEqual(ctx.exception.code, 2, f"should reject {bad!r}")

    def test_valid_prerelease_edge_cases_accepted(self) -> None:
        # Regression guard for the leading-zero tightening: ``0`` alone
        # and alphanumeric identifiers that start with a digit must
        # still pass.
        for good in ("1.1.0-0", "1.1.0-0a", "1.1.0-rc.0", "1.1.0-alpha-1"):
            with self._patch_git([("aaa", "Add X")]):
                with mock.patch("sys.stdout", new=io.StringIO()), \
                     mock.patch("sys.stderr", new=io.StringIO()):
                    rc = gc.main(["--since", "v1.0.0", "--version", good])
            self.assertEqual(rc, 0, f"should accept {good!r}")

    def test_value_error_from_config_surfaces_as_exit_two(self) -> None:
        # ValueError from the YAML parser (or anywhere in the pipeline)
        # must route through the "error: ..." / exit 2 contract instead
        # of leaking a traceback.
        patches = mock.patch.multiple(
            gc,
            find_repo_root=mock.MagicMock(return_value="/tmp/fake"),
            load_verb_mapping=mock.MagicMock(
                side_effect=ValueError("bad yaml token at line 3")
            ),
        )
        with patches, \
             mock.patch("sys.stdout", new=io.StringIO()), \
             mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = gc.main(["--since", "v1.0.0", "--version", "1.1.0"])
        self.assertEqual(rc, 2)
        self.assertIn("error:", err.getvalue())
        self.assertIn("bad yaml token", err.getvalue())

    def test_invalid_date_format_rejected(self) -> None:
        # ``--date 2026-13-45`` would otherwise splice a malformed
        # heading into CHANGELOG.md.  argparse.error exits with code 2.
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            with self.assertRaises(SystemExit) as ctx:
                gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0",
                    "--date", "2026-13-45",
                ])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--date", err.getvalue())

    def test_non_iso_date_rejected(self) -> None:
        # Free-form strings like ``today`` must fail the format check
        # rather than land in the rendered heading verbatim.
        with mock.patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0",
                    "--date", "today",
                ])
        self.assertEqual(ctx.exception.code, 2)

    def test_in_place_refuses_when_unmapped_exists(self) -> None:
        # Writing a partial section under --in-place would trap the
        # user: the duplicate-version guard blocks a clean re-run, so
        # the recovery path is manual deletion.  Refuse and return 3
        # (same "needs human classification" code as the stdout and
        # --dry-run paths) so release automation can treat all three
        # unmapped surfaces uniformly; 2 stays reserved for argparse
        # and genuine runtime errors.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            changelog = os.path.join(repo_root, "CHANGELOG.md")
            original = "# Changelog\n\n## [1.0.0] - 2026-01-01\n"
            with open(changelog, "w", encoding="utf-8") as fh:
                fh.write(original)

            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=True),
                tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
                collect_commits=mock.MagicMock(return_value=[
                    ("aaa", "Add X"),
                    ("zzz", "Replace bundle"),
                ]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()), \
                 mock.patch("sys.stderr", new=io.StringIO()) as err:
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0", "--in-place",
                ])
            self.assertEqual(rc, 3)
            self.assertIn("refusing", err.getvalue())
            with open(changelog, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), original)

    def test_in_place_dry_run_allowed_with_unmapped(self) -> None:
        # --in-place --dry-run only previews; no disk mutation, so
        # emitting the partial merge to stdout is safe even with
        # unmapped commits.  Preserves the "see what would happen"
        # workflow for reclassification.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            changelog = os.path.join(repo_root, "CHANGELOG.md")
            original = "# Changelog\n\n## [1.0.0] - 2026-01-01\n"
            with open(changelog, "w", encoding="utf-8") as fh:
                fh.write(original)

            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=True),
                tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
                collect_commits=mock.MagicMock(return_value=[
                    ("aaa", "Add X"),
                    ("zzz", "Replace bundle"),
                ]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()):
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0",
                    "--in-place", "--dry-run",
                ])
            self.assertEqual(rc, 3)
            self.assertIn("## [1.1.0]", out.getvalue())
            with open(changelog, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), original)

    def test_in_place_with_no_existing_changelog(self) -> None:
        # --in-place against a repo without CHANGELOG.md must synthesize
        # the Keep-a-Changelog preamble and write the new release to a
        # fresh file rather than erroring on the missing path.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = tmp
            os.makedirs(os.path.join(repo_root, ".git"))
            changelog = os.path.join(repo_root, "CHANGELOG.md")
            self.assertFalse(os.path.exists(changelog))

            patches = mock.patch.multiple(
                gc,
                tag_exists=mock.MagicMock(return_value=True),
                tag_commit_date=mock.MagicMock(return_value="2026-03-22"),
                collect_commits=mock.MagicMock(return_value=[("a", "Add X")]),
                find_repo_root=mock.MagicMock(return_value=repo_root),
            )
            with patches, \
                 mock.patch("sys.stdout", new=io.StringIO()), \
                 mock.patch("sys.stderr", new=io.StringIO()):
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0", "--in-place",
                ])
            self.assertEqual(rc, 0)
            with open(changelog, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("# Changelog", content)
            self.assertIn("Keep a Changelog", content)
            self.assertIn("## [1.1.0]", content)

# ===================================================================
# first_word — edge cases
# ===================================================================


class FirstWordTests(unittest.TestCase):
    def test_normal_subject(self) -> None:
        self.assertEqual(gc.first_word("Add feature X"), "Add")

    def test_empty_string(self) -> None:
        self.assertEqual(gc.first_word(""), "")

    def test_leading_whitespace(self) -> None:
        self.assertEqual(gc.first_word("  Add feature"), "Add")

    def test_whitespace_only_returns_empty(self) -> None:
        # Whitespace is truthy but split() yields no tokens; the helper
        # must return "" rather than indexing into an empty list.
        self.assertEqual(gc.first_word("   "), "")


# ===================================================================
# Git plumbing (subprocess.run mocked)
# ===================================================================


def _fake_completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return mock.MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


class RunGitTests(unittest.TestCase):
    def test_returns_stdout_on_success(self) -> None:
        with mock.patch.object(gc.subprocess, "run", return_value=_fake_completed("abc\n")):
            self.assertEqual(gc.run_git(["status"], "/tmp"), "abc\n")

    def test_raises_on_non_zero_exit(self) -> None:
        with mock.patch.object(
            gc.subprocess, "run",
            return_value=_fake_completed(stderr="boom", returncode=1),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                gc.run_git(["log"], "/tmp")
        self.assertIn("git log failed", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_pins_utf8_encoding(self) -> None:
        # Regression guard: text=True without ``encoding`` decodes per
        # process locale.  On Windows code pages, a UTF-8 commit
        # subject then raises UnicodeDecodeError before ``returncode``
        # is checked, crashing the generator with a traceback instead
        # of producing output.  Pin UTF-8 with ``errors="replace"`` so
        # decoding is locale-independent.
        captured: dict = {}

        def _record(*args: object, **kwargs: object) -> object:
            captured.update(kwargs)
            return _fake_completed("ok\n")

        with mock.patch.object(gc.subprocess, "run", side_effect=_record):
            gc.run_git(["status"], "/tmp")
        self.assertEqual(captured.get("encoding"), "utf-8")
        self.assertEqual(captured.get("errors"), "replace")
        self.assertTrue(captured.get("text"))


class TagExistsTests(unittest.TestCase):
    def test_zero_exit_means_exists(self) -> None:
        with mock.patch.object(gc.subprocess, "run", return_value=_fake_completed(returncode=0)):
            self.assertTrue(gc.tag_exists("v1.0.0", "/tmp"))

    def test_non_zero_means_missing(self) -> None:
        with mock.patch.object(gc.subprocess, "run", return_value=_fake_completed(returncode=1)):
            self.assertFalse(gc.tag_exists("v99.0.0", "/tmp"))


class TagCommitDateTests(unittest.TestCase):
    def test_strips_trailing_newline(self) -> None:
        with mock.patch.object(gc, "run_git", return_value="2026-03-22\n"):
            self.assertEqual(gc.tag_commit_date("v1.1.0", "/tmp"), "2026-03-22")

    def test_uses_committer_date_format(self) -> None:
        # Regression guard: ``%as`` is the author date, which can be
        # older than the actual tagged commit after a rebase or
        # cherry-pick and would stamp a stale release date into
        # CHANGELOG.md.  ``%cs`` is the commit date, which tracks the
        # tag's actual timeline.
        with mock.patch.object(gc, "run_git", return_value="2026-03-22\n") as run:
            gc.tag_commit_date("v1.1.0", "/tmp")
        call_args = run.call_args[0][0]
        self.assertIn("--format=%cs", call_args)
        self.assertNotIn("--format=%as", call_args)


class CollectCommitsTests(unittest.TestCase):
    def test_parses_sha_and_subject(self) -> None:
        raw = "aaa111\x00Add feature X\nbbb222\x00Fix bug Y\n"
        with mock.patch.object(gc, "run_git", return_value=raw):
            commits = gc.collect_commits("v1.0.0", "HEAD", "/tmp")
        self.assertEqual(
            commits,
            [("aaa111", "Add feature X"), ("bbb222", "Fix bug Y")],
        )

    def test_skips_malformed_lines(self) -> None:
        raw = "line-without-null\nccc\x00Add thing\n\n"
        with mock.patch.object(gc, "run_git", return_value=raw):
            commits = gc.collect_commits("v1.0.0", "HEAD", "/tmp")
        self.assertEqual(commits, [("ccc", "Add thing")])

    def test_empty_output_yields_empty_list(self) -> None:
        with mock.patch.object(gc, "run_git", return_value=""):
            self.assertEqual(gc.collect_commits("v1.0.0", "HEAD", "/tmp"), [])


class FindRepoRootTests(unittest.TestCase):
    def test_finds_git_dir_in_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real_tmp = os.path.realpath(tmp)
            os.makedirs(os.path.join(real_tmp, ".git"))
            nested = os.path.join(real_tmp, "a", "b", "c")
            os.makedirs(nested)
            self.assertEqual(gc.find_repo_root(nested), real_tmp)

    def test_raises_when_no_git_anywhere(self) -> None:
        # Can't simulate "no .git anywhere up to filesystem root" with a
        # real tempdir — the outer worktree has its own .git — so patch
        # os.path.exists to return False for the whole walk.
        with mock.patch.object(gc.os.path, "exists", return_value=False):
            with self.assertRaises(RuntimeError):
                gc.find_repo_root("/tmp/does-not-matter")


class NormalizeVersionTests(unittest.TestCase):
    def test_strips_leading_v(self) -> None:
        self.assertEqual(gc.normalize_version("v1.2.3"), "1.2.3")

    def test_leaves_unprefixed_alone(self) -> None:
        self.assertEqual(gc.normalize_version("1.2.3"), "1.2.3")


class TodayIsoTests(unittest.TestCase):
    def test_returns_iso_date_format(self) -> None:
        result = gc.today_iso()
        # YYYY-MM-DD — 10 chars, two hyphens.
        self.assertEqual(len(result), 10)
        self.assertEqual(result[4], "-")
        self.assertEqual(result[7], "-")


# ===================================================================
# _write_preserving_lf — Windows buffer branch
# ===================================================================


class WritePreservingLfTests(unittest.TestCase):
    """Covers both branches of the LF-preserving writer."""

    def test_uses_buffer_write_when_available(self) -> None:
        # Real stdout/stderr expose a ``buffer`` attribute; on Windows,
        # text-mode ``write`` would rewrite \n to \r\n, so the function
        # must route through the buffer with explicit UTF-8 bytes.
        fake_buffer = mock.MagicMock()
        fake_stream = mock.MagicMock(buffer=fake_buffer, spec=["buffer", "write"])
        gc._write_preserving_lf("hello\nworld\n", fake_stream)
        fake_buffer.write.assert_called_once_with(b"hello\nworld\n")
        fake_stream.write.assert_not_called()

    def test_falls_back_to_write_when_no_buffer(self) -> None:
        # StringIO has no ``buffer`` attribute; the function must fall
        # back to a plain text write so tests and other surrogates keep
        # working.
        buf = io.StringIO()
        gc._write_preserving_lf("plain\n", buf)
        self.assertEqual(buf.getvalue(), "plain\n")

    def test_uses_stream_encoding_when_set(self) -> None:
        # Regression guard: hardcoding UTF-8 to ``stream.buffer``
        # produces mojibake on Windows consoles whose code page is
        # still cp1252.  Encode with the stream's own ``encoding``
        # instead (with ``errors="replace"`` so an unmappable
        # character becomes ``?`` rather than a traceback).
        fake_buffer = mock.MagicMock()
        fake_stream = mock.MagicMock(
            buffer=fake_buffer,
            encoding="cp1252",
            spec=["buffer", "write", "encoding"],
        )
        gc._write_preserving_lf("smart quote — dash\n", fake_stream)
        # The em dash ``—`` (U+2014) encodes as 0x97 in cp1252.
        written = fake_buffer.write.call_args[0][0]
        self.assertEqual(written, "smart quote — dash\n".encode("cp1252"))

    def test_unmappable_character_does_not_raise(self) -> None:
        # ``errors="replace"`` keeps the script alive when a commit
        # subject contains a character the terminal encoding cannot
        # represent — we would rather emit a ``?`` than abort the
        # release with a traceback.
        fake_buffer = mock.MagicMock()
        fake_stream = mock.MagicMock(
            buffer=fake_buffer,
            encoding="ascii",
            spec=["buffer", "write", "encoding"],
        )
        gc._write_preserving_lf("café\n", fake_stream)
        written = fake_buffer.write.call_args[0][0]
        self.assertEqual(written, b"caf?\n")


# ===================================================================
# _require_yaml_parser — deferred import contract
# ===================================================================


class RequireYamlParserTests(unittest.TestCase):
    """The parser load is deferred so failures route through exit 2."""

    def test_returns_parser_when_available(self) -> None:
        parse = gc._require_yaml_parser()
        # Sanity-check it is actually the foundry's parser.
        self.assertTrue(callable(parse))
        self.assertEqual(parse("a: 1\n"), {"a": "1"})

    def test_missing_parser_file_raises_actionable_runtime_error(self) -> None:
        # Point the loader at a path that does not exist and confirm the
        # error message tells the caller where to look and why.
        with mock.patch.object(gc, "_YAML_PARSER_PATH", "/nonexistent/yaml_parser.py"):
            with self.assertRaises(RuntimeError) as ctx:
                gc._require_yaml_parser()
        message = str(ctx.exception)
        self.assertIn("yaml_parser.py", message)
        self.assertIn("/nonexistent/yaml_parser.py", message)

    def test_missing_parse_yaml_subset_attribute_surfaces_runtime_error(self) -> None:
        # If the meta-skill's yaml_parser.py is ever refactored to
        # rename or remove ``parse_yaml_subset``, the attribute miss
        # must route through main()'s ``error: …`` / exit 2 contract,
        # not escape as a bare ``AttributeError`` traceback.  Simulate
        # the refactor by pointing the loader at a stub module file.
        with tempfile.TemporaryDirectory() as tmp:
            stub_path = os.path.join(tmp, "yaml_parser.py")
            with open(stub_path, "w", encoding="utf-8") as fh:
                fh.write("# intentionally missing parse_yaml_subset\n")
            with mock.patch.object(gc, "_YAML_PARSER_PATH", stub_path):
                with self.assertRaises(RuntimeError) as ctx:
                    gc._require_yaml_parser()
        message = str(ctx.exception)
        self.assertIn("parse_yaml_subset", message)

    def test_non_callable_parse_yaml_subset_surfaces_runtime_error(self) -> None:
        # Same contract if parse_yaml_subset is redefined as a non-callable
        # (e.g. a constant) in a downstream fork of the parser.
        with tempfile.TemporaryDirectory() as tmp:
            stub_path = os.path.join(tmp, "yaml_parser.py")
            with open(stub_path, "w", encoding="utf-8") as fh:
                fh.write("parse_yaml_subset = 42\n")
            with mock.patch.object(gc, "_YAML_PARSER_PATH", stub_path):
                with self.assertRaises(RuntimeError) as ctx:
                    gc._require_yaml_parser()
        message = str(ctx.exception)
        self.assertIn("not callable", message)

    def test_syntax_error_in_parser_file_surfaces_runtime_error(self) -> None:
        # Broader exec_module guard: a SyntaxError while executing
        # yaml_parser.py must surface as RuntimeError so main() can
        # convert it to ``error: …`` / exit 2 instead of a traceback.
        with tempfile.TemporaryDirectory() as tmp:
            stub_path = os.path.join(tmp, "yaml_parser.py")
            with open(stub_path, "w", encoding="utf-8") as fh:
                fh.write("def broken(:\n")  # deliberate syntax error
            with mock.patch.object(gc, "_YAML_PARSER_PATH", stub_path):
                with self.assertRaises(RuntimeError) as ctx:
                    gc._require_yaml_parser()
        message = str(ctx.exception)
        self.assertIn("yaml_parser", message)
        self.assertIn("SyntaxError", message)


if __name__ == "__main__":
    unittest.main()
