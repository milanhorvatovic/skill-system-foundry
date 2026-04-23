"""Tests for scripts/generate_changelog.py.

Git is stubbed by monkey-patching ``run_git`` and ``tag_exists`` so
every test is hermetic — no real repository, no subprocess calls.
This keeps the suite fast and portable (CI runs on Linux and Windows).
"""

import io
import os
import sys
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
        self.assertNotIn("Bump", mapping)

    def test_security_and_deprecated_verbs_present(self) -> None:
        mapping = gc.load_verb_mapping()
        self.assertEqual(mapping["Deprecate"], "Deprecated")
        self.assertEqual(mapping["Patch"], "Security")
        self.assertEqual(mapping["Secure"], "Security")
        self.assertEqual(mapping["Mitigate"], "Security")

    def test_unknown_section_rejected(self) -> None:
        import tempfile

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
        import tempfile

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
        import tempfile

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

    def test_non_mapping_verb_mapping_rejected(self) -> None:
        # ``verb_mapping: [Add, Fix]`` (a list instead of a mapping)
        # would previously raise ``AttributeError`` on ``.items()``;
        # it now raises ``RuntimeError`` with a clear message.
        import tempfile

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

    def test_no_h1_synthesizes_preamble(self) -> None:
        merged = gc.splice_into_changelog("", NEW_SECTION)
        self.assertTrue(merged.startswith("# Changelog"))
        self.assertIn("Keep a Changelog", merged)
        self.assertIn("## [1.1.0]", merged)

    def test_empty_existing_yields_preamble_plus_section(self) -> None:
        merged = gc.splice_into_changelog("", NEW_SECTION)
        # No leftover empty-file content.
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

    def test_unmapped_goes_to_stderr_and_exits_non_zero(self) -> None:
        with self._patch_git([("zzz", "Replace the thing")]):
            with mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()) as err:
                rc = gc.main(["--since", "v1.0.0", "--version", "1.1.0"])
        self.assertEqual(rc, 1)
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
        import tempfile

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
        import tempfile

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
        import tempfile

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

    def test_date_override_wins(self) -> None:
        with self._patch_git([("a", "Add X")]):
            with mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()):
                gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0",
                    "--date", "2024-01-01",
                ])
        self.assertIn("## [1.1.0] - 2024-01-01", out.getvalue())

    def test_runtime_error_surfaced_and_exits_two(self) -> None:
        # A duplicate-version splice raises RuntimeError; main() must
        # turn that into an "error: ..." line on stderr and return 2
        # rather than leaking a traceback.
        import tempfile

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

    def test_build_metadata_version_accepted(self) -> None:
        with self._patch_git([("aaa", "Add X")]):
            with mock.patch("sys.stdout", new=io.StringIO()) as out, \
                 mock.patch("sys.stderr", new=io.StringIO()):
                rc = gc.main([
                    "--since", "v1.0.0", "--version", "1.1.0+build.42",
                ])
        self.assertEqual(rc, 0)
        self.assertIn("## [1.1.0+build.42]", out.getvalue())

    def test_malformed_prerelease_rejected(self) -> None:
        # Lone dot is not a valid prerelease identifier per semver 2.0.0.
        with mock.patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                gc.main(["--since", "v1.0.0", "--version", "1.1.0-."])
        self.assertEqual(ctx.exception.code, 2)

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

    def test_attribute_error_from_config_surfaces_as_exit_two(self) -> None:
        # AttributeError happens when a malformed config yields a
        # non-mapping where a mapping is expected; must exit 2 cleanly.
        patches = mock.patch.multiple(
            gc,
            find_repo_root=mock.MagicMock(return_value="/tmp/fake"),
            load_verb_mapping=mock.MagicMock(
                side_effect=AttributeError(
                    "'str' object has no attribute 'items'"
                )
            ),
        )
        with patches, \
             mock.patch("sys.stdout", new=io.StringIO()), \
             mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = gc.main(["--since", "v1.0.0", "--version", "1.1.0"])
        self.assertEqual(rc, 2)
        self.assertIn("error:", err.getvalue())


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
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            real_tmp = os.path.realpath(tmp)
            os.makedirs(os.path.join(real_tmp, ".git"))
            nested = os.path.join(real_tmp, "a", "b", "c")
            os.makedirs(nested)
            self.assertEqual(gc.find_repo_root(nested), real_tmp)

    def test_raises_when_no_git_anywhere(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "no-git-here")
            os.makedirs(nested)
            # Can't easily simulate "no .git anywhere up to filesystem root"
            # because the real repo above would match.  Use a patched
            # os.path.exists that always returns False.
            with mock.patch.object(gc.os.path, "exists", return_value=False):
                with self.assertRaises(RuntimeError):
                    gc.find_repo_root(nested)


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


if __name__ == "__main__":
    unittest.main()
