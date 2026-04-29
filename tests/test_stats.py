"""Tests for skill-system-foundry/scripts/lib/stats.py.

Covers byte counting, frontmatter discovery boundaries, the load
graph traversal (capabilities + references), the scripts/assets load
filter, alphabetical sort order, multi-parent ``reachable_from``
aggregation, broken-reference findings, cycle handling, and external
reference handling.
"""

import os
import sys
import tempfile
import unittest

from helpers import write_text, write_skill_md

SCRIPTS_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "skill-system-foundry", "scripts",
    )
)

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.stats import (
    category_of,
    compute_stats,
    discovery_bytes_of,
    extract_body_references,
    is_excluded_from_load,
    read_bytes_count,
)
from lib.constants import LEVEL_FAIL, LEVEL_INFO, LEVEL_WARN


# ============================================================
# Byte counting primitives
# ============================================================


class ReadBytesCountTests(unittest.TestCase):
    """Tests for ``read_bytes_count``."""

    def test_counts_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "file.md")
            with open(path, "wb") as f:
                f.write(b"hello\n")
            self.assertEqual(read_bytes_count(path), 6)

    def test_crlf_counted_as_two_bytes(self) -> None:
        """CRLF preserved on disk → byte count is higher than LF-only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "file.md")
            with open(path, "wb") as f:
                f.write(b"hello\r\nworld\r\n")
            self.assertEqual(read_bytes_count(path), 14)

    def test_utf8_multibyte_chars_counted_as_bytes_not_codepoints(self) -> None:
        """A 4-byte UTF-8 emoji counts as 4, not 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "file.md")
            with open(path, "wb") as f:
                f.write("\U0001f600".encode("utf-8"))
            self.assertEqual(read_bytes_count(path), 4)


# ============================================================
# Discovery bytes (frontmatter block)
# ============================================================


class DiscoveryBytesTests(unittest.TestCase):
    """Tests for ``discovery_bytes_of``."""

    def test_inclusive_of_both_fences(self) -> None:
        """Block runs from opening --- to closing --- inclusive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "SKILL.md")
            content = "---\nname: x\ndescription: y\n---\n# Body\n"
            with open(path, "wb") as f:
                f.write(content.encode("utf-8"))
            # "---\n" (4) + "name: x\n" (8) + "description: y\n" (15)
            # + "---\n" (4) = 31
            self.assertEqual(discovery_bytes_of(path), 31)

    def test_no_frontmatter_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "SKILL.md")
            with open(path, "wb") as f:
                f.write(b"# Just a body\n")
            self.assertEqual(discovery_bytes_of(path), 0)

    def test_unclosed_frontmatter_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "SKILL.md")
            with open(path, "wb") as f:
                f.write(b"---\nname: x\nno closer here\n")
            self.assertEqual(discovery_bytes_of(path), 0)

    def test_crlf_frontmatter_counted_with_carriage_returns(self) -> None:
        """CRLF terminators contribute to the byte count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "SKILL.md")
            with open(path, "wb") as f:
                f.write(b"---\r\nname: x\r\n---\r\n# Body\r\n")
            # Each line gets +1 byte for the CR.  4 lines in the
            # frontmatter block → +3 bytes vs. the LF-only count
            # (the body's \r\n is excluded).
            # LF-only count for the same content would be 18:
            # "---\n" (4) + "name: x\n" (8) + "---\n" (4) + "...".
            # Actually the LF-only block is 4+8+4 = 16; +3 CRs = 19.
            self.assertEqual(discovery_bytes_of(path), 19)


# ============================================================
# Boundary agreement with frontmatter.split_frontmatter
# ============================================================


class DiscoveryBoundaryAgreementTests(unittest.TestCase):
    """Pin ``discovery_bytes_of`` to ``frontmatter.split_frontmatter``.

    The two implementations exist for legitimate reasons (raw on-disk
    bytes vs LF-normalized parser view), but on LF-only content they
    must agree on where the frontmatter block ends.  Without this
    test, a future refactor of either side could silently disagree
    and the only symptom would be wrong byte counts.
    """

    def _expected_bytes(self, lf_content: str) -> int:
        """Return the boundary the parser sees, expressed in bytes.

        On LF-only input, ``split_frontmatter`` returns the body
        starting after the closing ``---`` line; the bytes before
        that point are the discovery block.
        """
        from lib.frontmatter import split_frontmatter

        frontmatter_text, body_text = split_frontmatter(lf_content)
        if frontmatter_text is None or body_text is None:
            return 0
        # The block is everything in lf_content except body_text (the
        # parser strips the trailing closing ``---\n``).
        return len(lf_content.encode("utf-8")) - len(
            body_text.encode("utf-8")
        )

    def test_agrees_on_minimal_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "SKILL.md")
            content = "---\nname: x\n---\n# Body\n"
            with open(path, "wb") as f:
                f.write(content.encode("utf-8"))
            self.assertEqual(
                discovery_bytes_of(path), self._expected_bytes(content)
            )

    def test_agrees_on_multi_field_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "SKILL.md")
            content = (
                "---\n"
                "name: x\n"
                "description: triggers when invoked\n"
                "license: MIT\n"
                "---\n"
                "# Body line one.\n"
                "Body line two.\n"
            )
            with open(path, "wb") as f:
                f.write(content.encode("utf-8"))
            self.assertEqual(
                discovery_bytes_of(path), self._expected_bytes(content)
            )

    def test_agrees_when_body_immediately_follows_closer(self) -> None:
        """No blank line between closing fence and body content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "SKILL.md")
            content = "---\nname: x\n---\nBody.\n"
            with open(path, "wb") as f:
                f.write(content.encode("utf-8"))
            self.assertEqual(
                discovery_bytes_of(path), self._expected_bytes(content)
            )


# ============================================================
# Reference extraction helpers
# ============================================================


class ExtractBodyReferencesTests(unittest.TestCase):
    """Tests for ``extract_body_references``."""

    def test_capability_link_detected_when_entry(self) -> None:
        """A markdown link to a capability.md is picked up by the
        body regex when the caller is processing the entry SKILL.md."""
        body = "[design](capabilities/design/capability.md)"
        self.assertIn(
            "capabilities/design/capability.md",
            extract_body_references(body, include_router_table=True),
        )

    def test_capability_link_filtered_when_not_entry(self) -> None:
        """A markdown link to a capability.md inside a non-entry body
        (capability or reference doc) is NOT returned — capability
        paths are entry-point-only edges, even when written as links."""
        body = "[design](capabilities/design/capability.md)"
        self.assertNotIn(
            "capabilities/design/capability.md",
            extract_body_references(body),
        )

    def test_nested_capability_resource_kept_in_non_entry_body(self) -> None:
        """A capability that links into its OWN nested resources via
        the skill-root-relative path (``capabilities/<name>/references/foo.md``)
        is a legitimate intra-capability reference and must stay in the
        load graph — only ``capabilities/<name>/capability.md`` itself
        is filtered as an entry-point-only edge."""
        body = (
            "# Design\n\n"
            "See [setup](capabilities/design/references/setup.md) "
            "for details.\n"
        )
        refs = extract_body_references(body)
        self.assertIn("capabilities/design/references/setup.md", refs)

    def test_reference_link_detected(self) -> None:
        body = "[guide](references/guide.md)"
        self.assertIn("references/guide.md", extract_body_references(body))

    def test_backtick_reference_detected(self) -> None:
        body = "see `references/guide.md` for details"
        self.assertIn("references/guide.md", extract_body_references(body))

    def test_fenced_block_refs_ignored(self) -> None:
        body = (
            "Real: [g](references/real.md)\n"
            "```markdown\n"
            "[fake](references/fake.md)\n"
            "```\n"
        )
        refs = extract_body_references(body)
        self.assertIn("references/real.md", refs)
        self.assertNotIn("references/fake.md", refs)

    def test_template_placeholders_dropped(self) -> None:
        body = "[x](references/<placeholder>.md) and [y](references/real.md)"
        refs = extract_body_references(body)
        self.assertNotIn("references/<placeholder>.md", refs)
        self.assertIn("references/real.md", refs)

    def test_anchor_fragments_stripped(self) -> None:
        body = "[g](references/guide.md#section)"
        self.assertEqual(
            extract_body_references(body), ["references/guide.md"]
        )

    def test_duplicates_removed_in_first_seen_order(self) -> None:
        body = (
            "[a](references/a.md)\n"
            "[b](references/b.md)\n"
            "`references/a.md`\n"
        )
        self.assertEqual(
            extract_body_references(body),
            ["references/a.md", "references/b.md"],
        )

    def test_external_path_not_matched_by_patterns(self) -> None:
        """README.md and similar top-level files are not in scope."""
        body = "[r](README.md) [g](references/guide.md)"
        refs = extract_body_references(body)
        self.assertNotIn("README.md", refs)
        self.assertIn("references/guide.md", refs)

    def test_router_table_capability_paths_extracted_when_entry(self) -> None:
        """Bare capability paths in a router-table cell are picked up
        when ``include_router_table`` is True (entry SKILL.md only)."""
        body = (
            "# Skill\n\n"
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| design | when designing | "
            "capabilities/design/capability.md |\n"
            "| validation | when validating | "
            "capabilities/validation/capability.md |\n"
        )
        refs = extract_body_references(body, include_router_table=True)
        self.assertIn("capabilities/design/capability.md", refs)
        self.assertIn("capabilities/validation/capability.md", refs)

    def test_router_table_skipped_when_not_entry(self) -> None:
        """Default (non-entry) calls do NOT pick up router-table paths."""
        body = (
            "# Skill\n\n"
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| design | when designing | "
            "capabilities/design/capability.md |\n"
        )
        refs = extract_body_references(body)
        self.assertNotIn("capabilities/design/capability.md", refs)

    def test_router_table_decorated_path_cell_recovered(self) -> None:
        """Backtick-wrapped router-table path cells are still recovered."""
        body = (
            "# Skill\n\n"
            "| Capability | Trigger | Path |\n"
            "|---|---|---|\n"
            "| design | when | `capabilities/design/capability.md` |\n"
        )
        refs = extract_body_references(body, include_router_table=True)
        self.assertIn("capabilities/design/capability.md", refs)


class CategoryHelpersTests(unittest.TestCase):
    """Tests for ``category_of`` and ``is_excluded_from_load``."""

    def test_top_level_file_returns_basename(self) -> None:
        self.assertEqual(category_of("SKILL.md"), "SKILL.md")

    def test_subdirectory_returns_first_segment(self) -> None:
        self.assertEqual(
            category_of("capabilities/design/capability.md"), "capabilities",
        )
        self.assertEqual(
            category_of("references/guide.md"), "references",
        )

    def test_scripts_excluded_from_load(self) -> None:
        self.assertTrue(is_excluded_from_load("scripts/foo.py"))

    def test_assets_excluded_from_load(self) -> None:
        self.assertTrue(is_excluded_from_load("assets/template.md"))

    def test_skill_md_not_excluded(self) -> None:
        self.assertFalse(is_excluded_from_load("SKILL.md"))

    def test_capabilities_not_excluded(self) -> None:
        self.assertFalse(
            is_excluded_from_load("capabilities/design/capability.md")
        )

    def test_references_not_excluded(self) -> None:
        self.assertFalse(is_excluded_from_load("references/guide.md"))


# ============================================================
# compute_stats end-to-end
# ============================================================


class ComputeStatsBasicTests(unittest.TestCase):
    """Tests for the basic happy path of ``compute_stats``."""

    def test_missing_skill_md_returns_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = compute_stats(tmpdir)
        self.assertEqual(result["discovery_bytes"], 0)
        self.assertEqual(result["load_bytes"], 0)
        self.assertEqual(result["files"], [])
        fails = [e for e in result["errors"] if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fails), 1)
        self.assertIn("No SKILL.md", fails[0])

    def test_skill_md_only_no_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir, body="# Skill body\n")
            result = compute_stats(tmpdir)
            skill_md_bytes = read_bytes_count(
                os.path.join(tmpdir, "SKILL.md")
            )
        self.assertEqual(result["metric"], "bytes")
        self.assertEqual(result["skill"], "demo-skill")
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["path"], "SKILL.md")
        self.assertEqual(result["files"][0]["reachable_from"], [])
        self.assertEqual(result["load_bytes"], skill_md_bytes)
        # discovery_bytes is non-zero (frontmatter present)
        self.assertGreater(result["discovery_bytes"], 0)
        # No findings — clean run
        self.assertEqual(result["errors"], [])

    def test_skill_name_from_directory_when_frontmatter_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "my-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "# Skill without frontmatter\n",
            )
            result = compute_stats(skill_dir)
        self.assertEqual(result["skill"], "my-skill")
        # discovery WARN since no frontmatter
        warns = [e for e in result["errors"] if e.startswith(LEVEL_WARN)]
        self.assertTrue(any("frontmatter" in w for w in warns))


class ComputeStatsGraphTests(unittest.TestCase):
    """Tests for transitive load-graph traversal."""

    def test_capability_and_reference_files_included(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "See [design](capabilities/design/capability.md) "
                    "and [guide](references/guide.md).\n"
                ),
            )
            write_text(
                os.path.join(tmpdir, "capabilities", "design", "capability.md"),
                "# Design\n\nCapability body.\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nReference body.\n",
            )
            result = compute_stats(tmpdir)
            paths = [entry["path"] for entry in result["files"]]
            expected_load = sum(
                read_bytes_count(os.path.join(tmpdir, p)) for p in paths
            )
        self.assertIn("SKILL.md", paths)
        self.assertIn("capabilities/design/capability.md", paths)
        self.assertIn("references/guide.md", paths)
        # Sorted alphabetically by POSIX path
        self.assertEqual(paths, sorted(paths))
        # Reachable-from points back to SKILL.md for both children
        for entry in result["files"]:
            if entry["path"] == "SKILL.md":
                self.assertEqual(entry["reachable_from"], [])
            else:
                self.assertEqual(entry["reachable_from"], ["SKILL.md"])
        self.assertEqual(result["load_bytes"], expected_load)

    def test_transitive_reference_followed(self) -> None:
        """Reference files that link to other reference files are followed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body="# Skill\n\nSee [a](references/a.md).\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "a.md"),
                "# A\n\nSee [b](references/b.md).\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "b.md"),
                "# B\n\nLeaf.\n",
            )
            result = compute_stats(tmpdir)
        paths = [entry["path"] for entry in result["files"]]
        self.assertIn("references/b.md", paths)
        b_entry = next(
            entry for entry in result["files"]
            if entry["path"] == "references/b.md"
        )
        self.assertEqual(b_entry["reachable_from"], ["references/a.md"])

    def test_scripts_and_assets_excluded_from_load(self) -> None:
        """A scripts/ or assets/ link does not contribute to load_bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "Run `scripts/runner.py` and use "
                    "[tmpl](assets/template.md).\n"
                ),
            )
            write_text(
                os.path.join(tmpdir, "scripts", "runner.py"),
                "print('hi')\n",
            )
            write_text(
                os.path.join(tmpdir, "assets", "template.md"),
                "# Template body.\n",
            )
            result = compute_stats(tmpdir)
            skill_bytes = read_bytes_count(os.path.join(tmpdir, "SKILL.md"))
        paths = [entry["path"] for entry in result["files"]]
        self.assertNotIn("scripts/runner.py", paths)
        self.assertNotIn("assets/template.md", paths)
        self.assertEqual(paths, ["SKILL.md"])
        self.assertEqual(result["load_bytes"], skill_bytes)

    def test_multiple_parents_aggregated_and_sorted(self) -> None:
        """A file referenced from two parents lists both, sorted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "See [a](capabilities/a/capability.md) "
                    "and [b](capabilities/b/capability.md).\n"
                ),
            )
            shared = "shared body\nlink to [s](references/shared.md)\n"
            write_text(
                os.path.join(tmpdir, "capabilities", "a", "capability.md"),
                shared,
            )
            write_text(
                os.path.join(tmpdir, "capabilities", "b", "capability.md"),
                shared,
            )
            write_text(
                os.path.join(tmpdir, "references", "shared.md"),
                "shared\n",
            )
            result = compute_stats(tmpdir)
        shared_entry = next(
            entry for entry in result["files"]
            if entry["path"] == "references/shared.md"
        )
        self.assertEqual(
            shared_entry["reachable_from"],
            [
                "capabilities/a/capability.md",
                "capabilities/b/capability.md",
            ],
        )

    def test_cycle_short_circuits_without_infinite_recursion(self) -> None:
        """A back-edge to an already-visited file just records the parent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body="# Skill\n\nSee [a](references/a.md).\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "a.md"),
                "# A\n\nSee [b](references/b.md).\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "b.md"),
                "# B\n\nSee [a](references/a.md).\n",
            )
            result = compute_stats(tmpdir)
        a_entry = next(
            entry for entry in result["files"]
            if entry["path"] == "references/a.md"
        )
        self.assertEqual(
            a_entry["reachable_from"],
            ["SKILL.md", "references/b.md"],
        )

    def test_broken_reference_emits_warn_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "See [missing](references/missing.md) "
                    "and [present](references/present.md).\n"
                ),
            )
            write_text(
                os.path.join(tmpdir, "references", "present.md"),
                "# Present\n",
            )
            result = compute_stats(tmpdir)
        warns = [e for e in result["errors"] if e.startswith(LEVEL_WARN)]
        self.assertTrue(
            any("references/missing.md" in w for w in warns),
            f"expected missing-ref WARN, got: {warns}",
        )
        # The present file is still counted
        paths = [entry["path"] for entry in result["files"]]
        self.assertIn("references/present.md", paths)
        self.assertNotIn("references/missing.md", paths)

    def test_router_table_capabilities_walked_and_counted(self) -> None:
        """End-to-end: a capability declared only in the SKILL.md router
        table (no markdown link) is walked and contributes to load_bytes
        with reachable_from == ['SKILL.md']."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(
                os.path.join(tmpdir, "SKILL.md"),
                "---\nname: x\ndescription: triggers when invoked\n---\n"
                "# Skill\n\n"
                "| Capability | Trigger | Path |\n"
                "|---|---|---|\n"
                "| design | when designing | "
                "capabilities/design/capability.md |\n",
            )
            write_text(
                os.path.join(tmpdir, "capabilities", "design", "capability.md"),
                "# Design\n\nBody.\n",
            )
            result = compute_stats(tmpdir)
            cap_bytes = read_bytes_count(
                os.path.join(
                    tmpdir, "capabilities", "design", "capability.md",
                )
            )
            skill_bytes = read_bytes_count(os.path.join(tmpdir, "SKILL.md"))
        paths = [entry["path"] for entry in result["files"]]
        self.assertIn("capabilities/design/capability.md", paths)
        cap = next(
            entry for entry in result["files"]
            if entry["path"] == "capabilities/design/capability.md"
        )
        self.assertEqual(cap["reachable_from"], ["SKILL.md"])
        self.assertEqual(cap["bytes"], cap_bytes)
        # load_bytes is the sum of SKILL.md + the router-table-discovered cap
        self.assertEqual(result["load_bytes"], skill_bytes + cap_bytes)

    def test_router_table_only_runs_on_entry_not_capability(self) -> None:
        """A router-shaped table inside a capability.md is NOT followed —
        only the entry SKILL.md scans for router-table capability paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "[design](capabilities/design/capability.md)\n"
                ),
            )
            # The capability body contains a doc-example router table
            # that mentions a non-existent ghost capability.  Without
            # the entry-only guard, stats would chase it.
            write_text(
                os.path.join(tmpdir, "capabilities", "design", "capability.md"),
                "# Design\n\n"
                "Documentation example below:\n\n"
                "| Capability | Trigger | Path |\n"
                "|---|---|---|\n"
                "| ghost | example only | "
                "capabilities/ghost/capability.md |\n",
            )
            result = compute_stats(tmpdir)
        paths = [entry["path"] for entry in result["files"]]
        self.assertIn("capabilities/design/capability.md", paths)
        # The ghost capability is doc-example only — must not be chased.
        self.assertNotIn("capabilities/ghost/capability.md", paths)
        # And no broken-link WARN should be raised for the ghost path.
        warns = [e for e in result["errors"] if e.startswith(LEVEL_WARN)]
        self.assertFalse(any("ghost" in w for w in warns))

    def test_undecodable_referenced_md_excluded_from_load_bytes(self) -> None:
        """A referenced .md file that exists but is not valid UTF-8
        is excluded from files[] and load_bytes — only the WARN
        finding remains.  Pins the documented recovery boundary that
        unreadable referenced files do not contribute to load_bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body="# Skill\n\n[broken](references/broken.md)\n",
            )
            ref_path = os.path.join(tmpdir, "references", "broken.md")
            os.makedirs(os.path.dirname(ref_path), exist_ok=True)
            # Bytes that aren't valid UTF-8.
            with open(ref_path, "wb") as f:
                f.write(b"# Heading\n\xff\xfe broken bytes\n")
            result = compute_stats(tmpdir)
            skill_md_size = os.path.getsize(
                os.path.join(tmpdir, "SKILL.md")
            )
        paths = [entry["path"] for entry in result["files"]]
        self.assertNotIn("references/broken.md", paths)
        warns = [e for e in result["errors"] if e.startswith(LEVEL_WARN)]
        self.assertTrue(
            any(
                "references/broken.md" in w and "cannot decode" in w
                for w in warns
            ),
            f"expected decode-error WARN for references/broken.md, got: {warns}",
        )
        # load_bytes is just SKILL.md
        self.assertEqual(result["load_bytes"], skill_md_size)

    def test_unreadable_skill_md_emits_fail_not_traceback(self) -> None:
        """A SKILL.md that exists but cannot be decoded as UTF-8
        produces a structured FAIL finding, not a traceback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            # Write bytes that are not valid UTF-8.
            with open(skill_md, "wb") as f:
                f.write(b"---\nname: x\n\xff\xfe invalid utf-8\n---\n# Body\n")
            result = compute_stats(tmpdir)
        fails = [e for e in result["errors"] if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fails), 1)
        self.assertIn("cannot read", fails[0])
        # No metrics computed beyond the early exit
        self.assertEqual(result["files"], [])

    def test_capability_path_in_non_entry_body_not_followed(self) -> None:
        """A capability or reference body that mentions
        ``capabilities/<name>/capability.md`` in backticks or markdown
        links is NOT treated as a live load edge — that's an entry-
        point-only edge.  Pins the non-entry capability-path filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "[a](capabilities/a/capability.md)\n"
                ),
            )
            # Capability A's body mentions capability B in backticks
            # as a documentation example.  B is NOT linked from
            # SKILL.md and must NOT be added to the load graph.
            write_text(
                os.path.join(tmpdir, "capabilities", "a", "capability.md"),
                "# A\n\nFor a similar pattern see "
                "`capabilities/b/capability.md`.\n",
            )
            write_text(
                os.path.join(tmpdir, "capabilities", "b", "capability.md"),
                "# B\n\nUnrelated capability that is not linked.\n",
            )
            result = compute_stats(tmpdir)
        paths = [entry["path"] for entry in result["files"]]
        self.assertIn("capabilities/a/capability.md", paths)
        self.assertNotIn("capabilities/b/capability.md", paths)
        # No broken-ref WARN for capability B either.
        warns = [e for e in result["errors"] if e.startswith(LEVEL_WARN)]
        self.assertFalse(any("capabilities/b" in w for w in warns))

    def test_missing_excluded_category_ref_does_not_warn(self) -> None:
        """A missing scripts/foo.py or assets/template.md reference
        is silently excluded from load_bytes — no broken-ref WARN
        because the category is excluded at the gate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(
                tmpdir,
                body=(
                    "# Skill\n\n"
                    "Run `scripts/missing.py` and use "
                    "[tmpl](assets/missing.md).\n"
                ),
            )
            result = compute_stats(tmpdir)
        warns = [e for e in result["errors"] if e.startswith(LEVEL_WARN)]
        self.assertFalse(
            any(
                "scripts/missing.py" in w or "assets/missing.md" in w
                for w in warns
            ),
            f"expected no WARN for excluded categories, got: {warns}",
        )
        # And neither path is in files[]
        paths = [entry["path"] for entry in result["files"]]
        self.assertNotIn("scripts/missing.py", paths)
        self.assertNotIn("assets/missing.md", paths)

    def test_external_symlink_classified_as_info(self) -> None:
        """A symlink whose target lies outside the skill root is
        classified as external (INFO) and excluded from load_bytes.

        This pins the ``is_within_directory`` defense — a future
        regression to a lexical relpath check would silently pass the
        rest of the suite while over-counting load_bytes for any
        skill that uses symlinks for shared resources.
        """
        if not hasattr(os, "symlink"):
            self.skipTest("symlink unavailable on this platform")
        with tempfile.TemporaryDirectory() as outer:
            skill_dir = os.path.join(outer, "skill")
            external = os.path.join(outer, "elsewhere", "external.md")
            write_text(external, "# External body\n")
            write_skill_md(
                skill_dir,
                body="# Skill\n\n[ext](references/external.md)\n",
            )
            os.makedirs(os.path.join(skill_dir, "references"))
            link_path = os.path.join(
                skill_dir, "references", "external.md",
            )
            try:
                os.symlink(external, link_path)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation not permitted")
            result = compute_stats(skill_dir)
        paths = [entry["path"] for entry in result["files"]]
        # The symlink target lives outside the skill — must not be
        # counted toward load_bytes or appear in files[].
        self.assertNotIn("references/external.md", paths)
        infos = [e for e in result["errors"] if e.startswith(LEVEL_INFO)]
        self.assertTrue(
            any(
                "outside the skill directory" in i
                and "references/external.md" in i
                for i in infos
            ),
            f"expected external-ref INFO finding, got: {infos}",
        )

    def test_parent_traversal_skipped_with_warn(self) -> None:
        """A `../` in a body reference is rejected as a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Build the body with a parent-traversal capabilities link
            # so the body regex still matches it.
            write_text(
                os.path.join(tmpdir, "SKILL.md"),
                "---\nname: x\ndescription: triggers when invoked\n---\n"
                "# Skill\n\n[bad](capabilities/../escape.md)\n",
            )
            result = compute_stats(tmpdir)
        warns = [e for e in result["errors"] if e.startswith(LEVEL_WARN)]
        self.assertTrue(
            any("parent traversal" in w for w in warns),
            f"expected parent-traversal WARN, got: {warns}",
        )


# ============================================================
# Schema shape
# ============================================================


class ComputeStatsSchemaTests(unittest.TestCase):
    """Verify the returned dict matches the documented schema."""

    def test_top_level_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir)
            result = compute_stats(tmpdir)
        self.assertEqual(
            set(result.keys()),
            {"skill", "metric", "discovery_bytes", "load_bytes",
             "files", "errors"},
        )
        self.assertEqual(result["metric"], "bytes")
        self.assertIsInstance(result["discovery_bytes"], int)
        self.assertIsInstance(result["load_bytes"], int)
        self.assertIsInstance(result["files"], list)
        self.assertIsInstance(result["errors"], list)

    def test_file_entry_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir)
            result = compute_stats(tmpdir)
        for entry in result["files"]:
            self.assertEqual(
                set(entry.keys()), {"path", "bytes", "reachable_from"},
            )
            self.assertIsInstance(entry["bytes"], int)
            self.assertIsInstance(entry["reachable_from"], list)


if __name__ == "__main__":
    unittest.main()
