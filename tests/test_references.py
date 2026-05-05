import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from helpers import write_text


SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.references import (
    BoundaryViolation,
    RE_TEXT_FILE_REF,
    classify_external_file,
    compute_bundle_path,
    extract_references,
    find_containing_skill,
    infer_system_root,
    is_dangling_symlink,
    is_drive_qualified,
    is_glob_path,
    is_within_directory,
    looks_like_degraded_symlink,
    resolve_case_exact,
    resolve_reference,
    resolve_reference_with_reason,
    scan_references,
    should_skip_reference,
    strip_fragment,
    walk_skill_files,
)


class StripFragmentTests(unittest.TestCase):
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


class IsGlobPathTests(unittest.TestCase):
    """``is_glob_path`` returns True iff the *path portion* of a
    markdown link target contains a glob metacharacter.  ``?``
    after a recognized file extension is the markdown query
    separator and counts as suffix, not glob — so it must not
    register as glob.  Same characters in the path portion
    (before the extension, or in directory components) must
    register."""

    def test_query_suffix_is_not_glob(self) -> None:
        # Query separators after a recognized extension are part
        # of the suffix, not the path — they must not flag as glob.
        for ref in (
            "foo.md?v=2",
            "references/guide.md?mode=raw",
            "../foo.md?",
        ):
            with self.subTest(ref=ref):
                self.assertFalse(is_glob_path(ref), msg=ref)

    def test_arbitrary_extension_query_is_not_glob(self) -> None:
        # The boundary regex must recognize *any* extension shape,
        # not just the configured ``reference_extensions`` list.
        # Directory-anchored captures legitimately accept arbitrary
        # extensions for asset and shared-resource links — if the
        # boundary regex restricted itself to the configured list,
        # these links would have no extension match, ``path_part``
        # would fall back to the whole reference, and a query-suffix
        # ``?`` would be misclassified as a glob, dropping the link
        # from validation, conformance, and ``--fix``.
        for ref in (
            "assets/logo.svg?v=2",
            "shared/photo.png?w=64",
            "assets/diagram.webp?cache=1",
            'assets/icon.svg "Why?"',
            "assets/data.csv#row-3",
        ):
            with self.subTest(ref=ref):
                self.assertFalse(is_glob_path(ref), msg=ref)

    def test_anchor_suffix_is_not_glob(self) -> None:
        # Anchor separators after a recognized extension are
        # treated the same — they're suffix, not path.
        for ref in (
            "foo.md#section",
            "references/guide.md#part-1",
        ):
            with self.subTest(ref=ref):
                self.assertFalse(is_glob_path(ref), msg=ref)

    def test_title_suffix_is_not_glob(self) -> None:
        # Markdown link title annotations live after whitespace
        # following a recognized extension.  ``?`` or ``[``/``]``
        # inside a title are part of the human-readable title, not
        # the filesystem path — they must not flag the link as a
        # glob.  Without whitespace as a boundary character, a link
        # like ``[guide](missing.md "Why?")`` would be misclassified
        # as a glob and dropped before validation, hiding the
        # broken-link finding the validator should surface.
        for ref in (
            'foo.md "Why?"',
            'references/guide.md "Q[A]?"',
            "foo.md 'simple title'",
            'references/guide.md "title with #anchor-like text"',
        ):
            with self.subTest(ref=ref):
                self.assertFalse(is_glob_path(ref), msg=ref)

    def test_glob_in_path_is_glob(self) -> None:
        # Metachars *in the path* (before the extension or as a
        # directory wildcard) flag as glob.
        for ref in (
            "capabilities/**/*.md",
            "references/?ref.md",
            "references/[abc].md",
            "references/{a,b}.md",
            "*.md",
        ):
            with self.subTest(ref=ref):
                self.assertTrue(is_glob_path(ref), msg=ref)

    def test_non_extension_path_falls_back_to_full_check(self) -> None:
        # When the ref has no recognized extension boundary, the
        # whole string is treated as path — a ``?`` anywhere
        # registers as glob.
        self.assertTrue(is_glob_path("subdir/?other"))
        self.assertFalse(is_glob_path("subdir/other"))


class IsDriveQualifiedTests(unittest.TestCase):
    """``is_drive_qualified`` recognizes Windows ``C:`` -prefixed paths
    on every platform.  ``os.path.splitdrive`` is platform-dependent
    (returns empty drive on POSIX), so a check that relies on it
    would silently pass these forms on Linux CI.  Pin a small matrix
    of positive and negative cases to lock in the cross-platform
    behavior.
    """

    def test_positive_cases(self) -> None:
        for ref in (
            "C:foo.md",
            "c:foo.md",
            "Z:references/guide.md",
            "C:/foo.md",
            "C:\\foo.md",
        ):
            with self.subTest(ref=ref):
                self.assertTrue(is_drive_qualified(ref), msg=ref)

    def test_negative_cases(self) -> None:
        for ref in (
            "",
            "foo.md",
            "references/foo.md",
            "../foo.md",
            "./foo.md",
            ":colon-first.md",
            "1:digit-first.md",  # not a letter — ignore
            "/absolute/path.md",  # absolute, not drive-qualified
            # Non-ASCII Unicode letters must NOT be treated as drive
            # letters.  ``str.isalpha`` accepts hundreds of code
            # points across world scripts, so a relative file named
            # after a Greek/German/etc. letter would otherwise be
            # misclassified as drive-qualified and silently dropped
            # by the validator.  Drive letters are ASCII-only.
            "Ω:notes.md",
            "Ä:notes.md",
            "ß:notes.md",
        ):
            with self.subTest(ref=ref):
                self.assertFalse(is_drive_qualified(ref), msg=ref)


class ShouldSkipReferenceTests(unittest.TestCase):
    def test_should_skip_reference_matrix(self) -> None:
        cases = {
            "https://example.com/doc.md": True,
            "mailto:test@example.com": True,
            "#section": True,
            "<https://example.com>": True,
            "<mailto:test@example.com>": True,
            "<ftp://files.example.com/data>": True,
            "file:///C:/docs/foo.md": True,
            "<file:///home/user/docs/foo.md>": True,
            "": True,
            "  ": True,
            "<a <b>": True,
            "references/foo.md": False,
            "<references/foo.md>": False,
            "<references/foo.md> \"Title\"": False,
        }

        for raw_ref, expected in cases.items():
            with self.subTest(raw_ref=raw_ref):
                self.assertEqual(should_skip_reference(raw_ref), expected)


class TextFileRefRegexTests(unittest.TestCase):
    def test_boundary_prevents_mid_token_match(self) -> None:
        """Prefixes embedded in longer words must not match."""
        cases = {
            # Should match — standalone prefix at start or after non-word char
            "references/guide.md": ["references/guide.md"],
            " references/guide.md": ["references/guide.md"],
            "path: references/guide.md": ["references/guide.md"],
            "skills/beta/notes.md": ["skills/beta/notes.md"],
            # Should NOT match — prefix is part of a longer word
            "myreferences/guide.md": [],
            "allskills/beta/notes.md": [],
            "extra_scripts/run.py": [],
            # Should NOT match — preceded by / (part of a longer path)
            "foo/references/guide.md": [],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                matches = RE_TEXT_FILE_REF.findall(text)
                self.assertEqual(matches, expected)


class FindContainingSkillTests(unittest.TestCase):
    def test_sibling_prefix_path_is_not_treated_as_in_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "project-root")
            sibling_root = os.path.join(tmpdir, "project-root-sibling")

            write_text(os.path.join(system_root, "skills", "alpha", "SKILL.md"), "---\n---\n")
            outside_file = os.path.join(sibling_root, "skills", "beta", "doc.md")
            write_text(outside_file, "outside")

            self.assertIsNone(find_containing_skill(outside_file, system_root))

    def test_symlinked_path_to_outside_root_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            outside_skill = os.path.join(tmpdir, "outside-skill")
            link_parent = os.path.join(system_root, "skills")
            link_path = os.path.join(link_parent, "linked-skill")

            write_text(os.path.join(outside_skill, "SKILL.md"), "---\n---\n")
            write_text(os.path.join(outside_skill, "doc.md"), "content")
            os.makedirs(link_parent, exist_ok=True)

            try:
                os.symlink(outside_skill, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            linked_doc = os.path.join(link_path, "doc.md")
            self.assertIsNone(find_containing_skill(linked_doc, system_root))


class ScanReferencesTests(unittest.TestCase):
    """End-to-end tests for scan_references()."""

    def test_broken_reference_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [guide](references/nonexistent.md)\n",
            )

            result = scan_references(skill_dir, system_root)

            fails = [e for e in result["errors"] if "Broken reference" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("nonexistent.md", fails[0])

    def test_cross_skill_reference_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_a = os.path.join(system_root, "skills", "alpha")
            skill_b = os.path.join(system_root, "skills", "beta")
            write_text(os.path.join(skill_a, "SKILL.md"), "---\nname: alpha\n---\n")
            write_text(os.path.join(skill_b, "SKILL.md"), "---\nname: beta\n---\n")
            write_text(os.path.join(skill_b, "notes.md"), "Beta notes\n")
            write_text(
                os.path.join(skill_a, "doc.md"),
                "See [beta notes](../beta/notes.md)\n",
            )

            result = scan_references(skill_a, system_root)

            fails = [e for e in result["errors"] if "Cross-skill reference" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("beta", fails[0])

    def test_depth_limit_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            # Create a chain: skill -> ext_0 -> ext_1 -> ext_2
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [ext](../../references/ext_0.md)\n",
            )
            for i in range(3):
                write_text(
                    os.path.join(system_root, "references", f"ext_{i}.md"),
                    f"See [next](ext_{i + 1}.md)\n",
                )

            result = scan_references(skill_dir, system_root, max_depth=2)

            fails = [e for e in result["errors"] if "depth limit" in e]
            self.assertEqual(len(fails), 1)

    def test_cycle_between_external_docs_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [a](../../references/a.md)\n",
            )
            write_text(
                os.path.join(system_root, "references", "a.md"),
                "See [b](b.md)\n",
            )
            write_text(
                os.path.join(system_root, "references", "b.md"),
                "See [a](a.md)\n",
            )

            result = scan_references(skill_dir, system_root)

            fails = [e for e in result["errors"] if "Circular reference" in e]
            self.assertEqual(len(fails), 1)

    def test_text_detected_reference_produces_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "config.yaml"),
                "path: references/guide.md\n",
            )
            write_text(
                os.path.join(system_root, "references", "guide.md"),
                "Guide content\n",
            )

            result = scan_references(skill_dir, system_root)

            warns = [w for w in result["warnings"] if "Non-markdown" in w]
            self.assertEqual(len(warns), 1)
            self.assertIn("guide.md", warns[0])
            # The referenced file should still be in external_files
            guide = os.path.join(system_root, "references", "guide.md")
            self.assertIn(os.path.abspath(guide), result["external_files"])

    def test_valid_external_reference_collected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [role](../../roles/reviewer.md)\n",
            )
            write_text(
                os.path.join(system_root, "roles", "reviewer.md"),
                "Reviewer role\n",
            )

            result = scan_references(skill_dir, system_root)

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["warnings"], [])
            role = os.path.join(system_root, "roles", "reviewer.md")
            self.assertIn(os.path.abspath(role), result["external_files"])

    def test_no_system_root_with_external_ref_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Place skill in a flat directory with no system root markers
            # so that infer_system_root() returns None.
            skill_dir = os.path.join(tmpdir, "skill")
            ext_file = os.path.join(tmpdir, "outside.md")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [ext](../outside.md)\n",
            )
            write_text(ext_file, "Outside\n")

            # system_root=None triggers inference; with no system root
            # markers the inferred root is None, so external refs fail.
            result = scan_references(skill_dir, system_root=None)

            fails = [e for e in result["errors"] if "no system root" in e]
            self.assertEqual(len(fails), 1)


    def test_symlink_inside_skill_to_outside_target_is_internal(self) -> None:
        """A symlink living inside the skill but pointing outside should be
        classified as internal (apparent path is within the skill), so that
        _copy_skill() handles it and _copy_external_files() does not
        duplicate it."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            shared_dir = os.path.join(system_root, "shared")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            # Shared file outside the skill but within the system root.
            shared_file = os.path.join(shared_dir, "common.md")
            write_text(shared_file, "Shared content\n")
            # Symlink inside the skill pointing to the shared file.
            link_path = os.path.join(skill_dir, "refs", "common.md")
            os.makedirs(os.path.dirname(link_path), exist_ok=True)
            try:
                os.symlink(shared_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")
            # Skill doc references the symlink via its apparent path.
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [common](refs/common.md)\n",
            )

            result = scan_references(skill_dir, system_root)

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["warnings"], [])
            # The symlink target must NOT appear as an external file.
            self.assertEqual(result["external_files"], set())

    def test_symlinked_file_escaping_boundary_produces_fail(self) -> None:
        """A symlinked file in the skill tree whose real target escapes the
        allowed boundary should produce a FAIL and not be traversed."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            # File outside the system root entirely.
            outside_file = os.path.join(tmpdir, "outside", "secret.md")
            write_text(outside_file, "Secret content\n")

            # Symlink inside the skill pointing to the outside file.
            link_path = os.path.join(skill_dir, "secret.md")
            try:
                os.symlink(outside_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            result = scan_references(skill_dir, system_root)

            fails = [e for e in result["errors"] if "escapes allowed boundary" in e]
            self.assertEqual(len(fails), 1)

    def test_symlink_to_another_skill_produces_fail(self) -> None:
        """A symlink inside the skill whose real target is inside another
        skill under system_root/skills/ should produce a cross-skill FAIL
        when referenced from a markdown file."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_a = os.path.join(system_root, "skills", "alpha")
            skill_b = os.path.join(system_root, "skills", "beta")
            write_text(os.path.join(skill_b, "SKILL.md"), "---\nname: beta\n---\n")
            target_file = os.path.join(skill_b, "references", "shared.md")
            write_text(target_file, "Shared content from beta\n")

            # Symlink inside alpha pointing to a file in beta.
            link_path = os.path.join(skill_a, "references", "borrowed.md")
            os.makedirs(os.path.dirname(link_path), exist_ok=True)
            try:
                os.symlink(target_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # SKILL.md references the symlinked file — the lexical path
            # is inside the skill but the real target is in another skill.
            write_text(
                os.path.join(skill_a, "SKILL.md"),
                "---\nname: alpha\n---\nSee [shared](references/borrowed.md)\n",
            )

            result = scan_references(skill_a, system_root)

            fails = [e for e in result["errors"] if "Cross-skill" in e and "symlink" in e.lower()]
            self.assertEqual(len(fails), 1, (
                f"Expected exactly one cross-skill symlink FAIL. "
                f"Errors: {result['errors']}"
            ))

    def test_text_detected_cross_skill_reference_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_a = os.path.join(system_root, "skills", "alpha")
            skill_b = os.path.join(system_root, "skills", "beta")
            write_text(os.path.join(skill_a, "SKILL.md"), "---\nname: alpha\n---\n")
            write_text(os.path.join(skill_b, "SKILL.md"), "---\nname: beta\n---\n")
            write_text(os.path.join(skill_b, "notes.md"), "Beta notes\n")
            # Non-markdown file with a skills/ prefix reference
            write_text(
                os.path.join(skill_a, "config.yaml"),
                "ref: skills/beta/notes.md\n",
            )

            result = scan_references(skill_a, system_root)

            # Cross-skill references must be a hard FAIL even when the
            # originating file is non-markdown (text_detected).
            fails = [e for e in result["errors"] if "Cross-skill" in e]
            self.assertEqual(len(fails), 1, (
                f"Expected exactly one Cross-skill FAIL. "
                f"Errors: {result['errors']}"
            ))
            self.assertIn("beta", fails[0])


class InlineOrchestratedSkillsTests(unittest.TestCase):
    """Tests for scan_references() with inline_orchestrated_skills=True."""

    def test_cross_skill_collected_when_flag_set(self) -> None:
        """Cross-skill references are collected instead of rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing_skill = os.path.join(system_root, "skills", "testing")
            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing_skill, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing_skill, "references", "guide.md"), "Guide\n")

            # Role references the testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            # Coordinator references the role
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # No errors — cross-skill references are tolerated
            self.assertEqual(result["errors"], [])
            # The testing skill should be collected for inlining
            self.assertEqual(len(result["inlined_skills"]), 1)
            abs_testing = os.path.abspath(testing_skill)
            self.assertIn(abs_testing, result["inlined_skills"])
            self.assertEqual(result["inlined_skills"][abs_testing], "testing")
            # The role should be in external_files
            self.assertIn(os.path.abspath(role_file), result["external_files"])

    def test_cross_skill_still_rejected_without_flag(self) -> None:
        """Without the flag, cross-skill references produce FAIL as before."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing_skill = os.path.join(system_root, "skills", "testing")
            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing_skill, "SKILL.md"), "---\nname: testing\n---\n")

            # Role references the testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            result = scan_references(coordinator, system_root)

            fails = [e for e in result["errors"] if "Cross-skill reference" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("testing", fails[0])
            self.assertEqual(len(result["inlined_skills"]), 0)

    def test_inlined_skills_empty_when_no_cross_refs(self) -> None:
        """A skill with no cross-skill references has an empty inlined_skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            result = scan_references(
                skill_dir, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["inlined_skills"], {})

    def test_inlined_skill_transitive_external_deps_collected(self) -> None:
        """External files referenced by an inlined skill are collected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill references an external shared reference
            shared_guide = os.path.join(system_root, "references", "shared-guide.md")
            write_text(shared_guide, "# Shared Guide\n")
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [guide](../../references/shared-guide.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # The shared guide should be discovered as an external file
            self.assertIn(os.path.abspath(shared_guide), result["external_files"])
            # Both the role and the shared guide should be external
            self.assertIn(os.path.abspath(role_file), result["external_files"])

    def test_inlined_skill_internal_refs_not_external(self) -> None:
        """Files inside an inlined skill that reference other files in
        the same skill should not appear in external_files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has internal references between its own files
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [guide](references/test-guide.md)\n",
            )
            internal_guide = os.path.join(testing, "references", "test-guide.md")
            write_text(internal_guide, "# Internal Guide\n")

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # The internal guide should NOT be in external_files
            self.assertNotIn(os.path.abspath(internal_guide), result["external_files"])

    def test_inlined_skill_broken_ref_produces_fail(self) -> None:
        """A broken reference inside an inlined skill is still reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has a broken reference
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [missing](references/nonexistent.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            fails = [e for e in result["errors"] if "Broken reference" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("nonexistent.md", fails[0])

    def test_unreachable_file_in_inlined_skill_scanned(self) -> None:
        """A file in an inlined skill NOT referenced from SKILL.md but
        having its own external dependency should still be scanned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing SKILL.md does NOT reference the helper file
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n# Testing\n",
            )
            # But the helper file references a shared external doc
            shared_ref = os.path.join(system_root, "references", "shared-guide.md")
            write_text(shared_ref, "# Shared Guide\n")
            write_text(
                os.path.join(testing, "references", "helper.md"),
                "See [shared](../../../references/shared-guide.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # The shared guide should be discovered even though it's
            # only reachable from the unreferenced helper.md
            self.assertIn(os.path.abspath(shared_ref), result["external_files"])

    def test_unreachable_broken_ref_in_inlined_skill_reported(self) -> None:
        """A broken reference in an unreferenced file inside an inlined
        skill should still produce a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # SKILL.md is clean
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n# Testing\n",
            )
            # But an unreferenced file has a broken reference to a
            # non-existent file within the skill (using a relative path
            # that stays within the skill boundary).
            write_text(
                os.path.join(testing, "references", "broken.md"),
                "See [missing](nonexistent.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            fails = [e for e in result["errors"] if "FAIL" in e]
            self.assertEqual(len(fails), 1)
            self.assertIn("nonexistent.md", fails[0])

    def test_text_detected_cross_skill_ref_warns_when_inlining(self) -> None:
        """A text_detected cross-skill reference emits a WARN in inline mode
        because non-markdown references are not automatically rewritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing, "notes.md"), "Testing notes\n")

            # Non-markdown file with a text_detected cross-skill reference
            write_text(
                os.path.join(coordinator, "config.yaml"),
                "ref: skills/testing/notes.md\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # No hard errors — the skill is collected for inlining
            self.assertEqual(result["errors"], [])
            # But a warning about the non-rewritable reference
            warns = [w for w in result["warnings"] if "Non-markdown cross-skill" in w]
            self.assertEqual(len(warns), 1, (
                f"Expected exactly one non-markdown cross-skill WARN. "
                f"Warnings: {result['warnings']}"
            ))
            self.assertIn("testing", warns[0])
            self.assertIn("config.yaml", warns[0])
            # The testing skill should still be collected for inlining
            abs_testing = os.path.abspath(testing)
            self.assertIn(abs_testing, result["inlined_skills"])

    def test_explicit_empty_exclude_patterns_respected(self) -> None:
        """An explicit empty exclude_patterns=[] must not fall back to
        BUNDLE_EXCLUDE_PATTERNS — it should scan all files including those
        that the defaults would skip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has a file in a .git directory (normally excluded)
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n",
            )
            hidden_file = os.path.join(testing, ".git", "config.md")
            write_text(hidden_file, "See [broken](nonexistent.md)\n")

            # With default excludes, .git is skipped — no error from hidden_file
            result_default = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )
            fails_default = [e for e in result_default["errors"] if "Broken reference" in e]
            self.assertEqual(len(fails_default), 0)

            # With exclude_patterns=[], nothing is skipped — the broken ref
            # in .git/config.md should be discovered
            result_empty = scan_references(
                coordinator, system_root,
                exclude_patterns=[],
                inline_orchestrated_skills=True,
            )
            fails_empty = [e for e in result_empty["errors"] if "Broken reference" in e]
            self.assertGreaterEqual(len(fails_empty), 1, (
                f"Expected broken reference FAIL when exclude_patterns=[]. "
                f"Errors: {result_empty['errors']}"
            ))

    def test_inlined_skill_symlink_boundary_violation_produces_fail(self) -> None:
        """A symlink in an inlined skill that escapes the boundary should
        produce a FAIL instead of crashing with ValueError."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")

            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # File completely outside the system root
            outside_file = os.path.join(tmpdir, "outside", "secret.md")
            write_text(outside_file, "Secret content\n")

            # Symlink inside the testing skill pointing outside the boundary
            link_path = os.path.join(testing, "secret.md")
            try:
                os.symlink(outside_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # This must NOT raise — it should produce a FAIL entry
            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            fails = [e for e in result["errors"] if "escapes" in e.lower()]
            self.assertGreaterEqual(len(fails), 1, (
                f"Expected at least one boundary violation FAIL. "
                f"Errors: {result['errors']}"
            ))
            # Should mention the inlined skill name
            boundary_fails = [e for e in fails if "inlined skill" in e]
            self.assertGreaterEqual(len(boundary_fails), 1, (
                f"Expected boundary FAIL to mention 'inlined skill'. "
                f"Errors: {fails}"
            ))


    def test_text_detected_ref_into_already_inlined_skill_warns(self) -> None:
        """A text_detected reference into an already-collected inlined skill
        must still emit a WARN (the path won't be rewritten)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing, "notes.md"), "Testing notes\n")

            # A markdown role reference collects 'testing' for inlining first
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # A non-markdown file also references files inside 'testing'.
            # By the time this is scanned, 'testing' is already collected
            # — so it hits the "already-inlined" early-return path.
            write_text(
                os.path.join(coordinator, "config.yaml"),
                "ref: skills/testing/notes.md\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # The warning should still be emitted for the text_detected ref
            warns = [w for w in result["warnings"] if "Non-markdown cross-skill" in w]
            self.assertGreaterEqual(len(warns), 1, (
                f"Expected at least one non-markdown cross-skill WARN. "
                f"Warnings: {result['warnings']}"
            ))
            # Should mention the config.yaml source file
            config_warns = [w for w in warns if "config.yaml" in w]
            self.assertGreaterEqual(len(config_warns), 1, (
                f"Expected WARN to mention config.yaml. "
                f"Warnings: {warns}"
            ))


    def test_inlined_skill_depth_does_not_inherit_coordinator_depth(self) -> None:
        """Inlined skill scanning should start at depth 0, not inherit the
        coordinator's depth.  With max_depth=2, a coordinator at depth 1
        that discovers a skill should still scan the inlined skill's own
        2-level reference chain without hitting a false depth limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Coordinator references a role (depth 1 from coordinator)
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has a 2-level external reference chain:
            # testing/SKILL.md -> ../../references/a.md -> b.md
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [a](../../references/a.md)\n",
            )
            write_text(
                os.path.join(system_root, "references", "a.md"),
                "See [b](b.md)\n",
            )
            write_text(
                os.path.join(system_root, "references", "b.md"),
                "Final doc\n",
            )

            # With max_depth=2, if the inlined skill inherited the
            # coordinator's depth, scanning a.md (depth 2+1=3) would
            # fail.  Starting at 0 means a.md is at depth 1 and b.md
            # at depth 2 — both within limit.
            result = scan_references(
                coordinator, system_root,
                max_depth=2,
                inline_orchestrated_skills=True,
            )

            depth_fails = [e for e in result["errors"] if "depth limit" in e]
            self.assertEqual(len(depth_fails), 0, (
                f"Inlined skill scanning should start at depth 0. "
                f"Errors: {result['errors']}"
            ))
            # Both external files should be discovered
            abs_a = os.path.abspath(os.path.join(system_root, "references", "a.md"))
            abs_b = os.path.abspath(os.path.join(system_root, "references", "b.md"))
            self.assertIn(abs_a, result["external_files"])
            self.assertIn(abs_b, result["external_files"])

    def test_inlined_skill_cross_skill_symlink_detected(self) -> None:
        """A symlink inside an inlined skill that points to another skill
        should be detected as a cross-skill symlink violation, using the
        inlined skill as the context (not the coordinator)."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")
            deploy = os.path.join(system_root, "skills", "deploy")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(deploy, "SKILL.md"), "---\nname: deploy\n---\n")
            write_text(os.path.join(deploy, "doc.md"), "Deploy doc\n")

            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Symlink inside testing that points to a file in deploy
            link_path = os.path.join(testing, "refs", "deploy-doc.md")
            os.makedirs(os.path.dirname(link_path), exist_ok=True)
            try:
                os.symlink(
                    os.path.join(deploy, "doc.md"),
                    link_path,
                )
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # testing/SKILL.md references the symlink
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [deploy](refs/deploy-doc.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # The cross-skill symlink from testing -> deploy should be
            # detected using testing as the context, not coordinator.
            cross_skill_fails = [
                e for e in result["errors"]
                if "Cross-skill" in e and "symlink" in e.lower()
            ]
            self.assertGreaterEqual(len(cross_skill_fails), 1, (
                f"Expected cross-skill symlink FAIL from testing -> deploy. "
                f"Errors: {result['errors']}"
            ))

    def test_inlined_skill_internal_ref_not_flagged_as_cross_skill(self) -> None:
        """Files inside an inlined skill that reference other files within
        the same skill should be treated as internal (using the inlined
        skill as context), not misidentified as cross-skill references."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill has multiple files referencing each other
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\nSee [guide](references/guide.md)\n",
            )
            write_text(
                os.path.join(testing, "references", "guide.md"),
                "See [helpers](helpers.md)\n",
            )
            write_text(
                os.path.join(testing, "references", "helpers.md"),
                "Helper content\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # No errors — internal refs within the inlined skill should
            # be handled correctly with the proper skill context.
            self.assertEqual(result["errors"], [], (
                f"Internal refs within an inlined skill should not produce "
                f"errors. Errors: {result['errors']}"
            ))
            # No cross-skill warnings about internal references
            cross_warns = [w for w in result["warnings"] if "cross-skill" in w.lower()]
            self.assertEqual(len(cross_warns), 0, (
                f"Internal refs should not produce cross-skill warnings. "
                f"Warnings: {result['warnings']}"
            ))
            # The internal files should NOT appear as external files
            abs_guide = os.path.abspath(os.path.join(testing, "references", "guide.md"))
            abs_helpers = os.path.abspath(os.path.join(testing, "references", "helpers.md"))
            self.assertNotIn(abs_guide, result["external_files"])
            self.assertNotIn(abs_helpers, result["external_files"])


    def test_coordinator_back_reference_not_inlined(self) -> None:
        """If an inlined skill references back to the coordinator, the
        coordinator must NOT be collected for inlining into itself."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Testing skill references the coordinator back
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n"
                "See [coordinator](../coordinator/SKILL.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            # Only testing should be inlined, NOT the coordinator
            self.assertEqual(len(result["inlined_skills"]), 1, (
                f"Expected only 1 inlined skill (testing), not coordinator. "
                f"Inlined: {result['inlined_skills']}"
            ))
            # The inlined skill should be testing
            names = list(result["inlined_skills"].values())
            self.assertIn("testing", names)
            self.assertNotIn("coordinator", names)

    def test_symlinked_skill_reference_deduplicates(self) -> None:
        """When the same skill is referenced via a symlink and a direct
        path, it should only be collected once for inlining."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing, "doc.md"), "Test doc\n")

            # Create a symlink: skills/testing-alias -> skills/testing
            alias_path = os.path.join(system_root, "skills", "testing-alias")
            try:
                os.symlink(testing, alias_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # Two roles: one references via direct path, one via symlink
            role_a = os.path.join(system_root, "roles", "role-a.md")
            role_b = os.path.join(system_root, "roles", "role-b.md")
            write_text(
                role_a,
                "See [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                role_b,
                "See [skill](../skills/testing-alias/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [a](../../roles/role-a.md)\nSee [b](../../roles/role-b.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # Should only have 1 inlined skill (not 2)
            self.assertEqual(len(result["inlined_skills"]), 1, (
                f"Expected exactly 1 inlined skill after dedup. "
                f"Inlined: {result['inlined_skills']}"
            ))
            # The name should be the canonical directory name, not the alias
            names = list(result["inlined_skills"].values())
            self.assertIn("testing", names)
            self.assertNotIn("testing-alias", names)

    def test_alias_first_reference_uses_canonical_name(self) -> None:
        """When the first cross-skill reference is through a symlink alias,
        the capability name must still be the canonical (realpath-resolved)
        directory name, not the alias."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")

            # Create alias symlink
            alias_path = os.path.join(system_root, "skills", "testing-alias")
            try:
                os.symlink(testing, alias_path)
            except OSError:
                self.skipTest("symlink creation is not permitted in this environment")

            # Role references ONLY via alias — this is the first (and only)
            # reference, so it determines the inlined skill name.
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "See [skill](../skills/testing-alias/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            self.assertEqual(len(result["inlined_skills"]), 1)
            # Name must be canonical ("testing"), not the alias
            names = list(result["inlined_skills"].values())
            self.assertIn("testing", names, (
                f"Expected canonical name 'testing', got: {names}"
            ))
            self.assertNotIn("testing-alias", names, (
                f"Alias name should not appear: {names}"
            ))


    def test_alias_recorded_in_inlined_skill_aliases(self) -> None:
        """When a skill is referenced via both direct and alias paths,
        the alias is recorded in inlined_skill_aliases."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")

            alias_path = os.path.join(system_root, "skills", "testing-alias")
            try:
                os.symlink(testing, alias_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            # Two roles: direct + alias
            write_text(
                os.path.join(system_root, "roles", "role-a.md"),
                "See [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(system_root, "roles", "role-b.md"),
                "See [skill](../skills/testing-alias/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [a](../../roles/role-a.md)\nSee [b](../../roles/role-b.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(len(result["inlined_skills"]), 1)
            aliases = result["inlined_skill_aliases"]
            self.assertEqual(len(aliases), 1, (
                f"Expected 1 alias entry. Got: {aliases}"
            ))
            alias_abs, primary_abs = aliases[0]
            self.assertIn("testing-alias", alias_abs)
            # Primary should be the direct path entry
            self.assertEqual(
                primary_abs,
                list(result["inlined_skills"].keys())[0],
            )

    def test_text_detected_coordinator_back_ref_warns(self) -> None:
        """A text_detected reference back to the coordinator from an
        inlined skill emits a WARN (the path won't be rewritten)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")

            # Role references testing skill
            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            # Non-markdown file in testing references the coordinator
            write_text(
                os.path.join(testing, "config.yaml"),
                "coordinator: skills/coordinator/SKILL.md\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(result["errors"], [])
            warns = [w for w in result["warnings"]
                     if "coordinator" in w.lower() and "non-markdown" in w.lower()]
            self.assertGreaterEqual(len(warns), 1, (
                f"Expected WARN for text_detected coordinator back-ref. "
                f"Warnings: {result['warnings']}"
            ))

    def test_alias_dedup_in_cross_skill_collection(self) -> None:
        """Multiple references through the same alias path should not
        produce duplicate entries in inlined_skill_aliases."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(
                os.path.join(coordinator, "SKILL.md"),
                "---\nname: coordinator\n---\n",
            )
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n",
            )
            write_text(
                os.path.join(testing, "extra.md"),
                "Extra docs.\n",
            )

            alias_path = os.path.join(
                system_root, "skills", "testing-alias"
            )
            try:
                os.symlink(testing, alias_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            # Two roles that BOTH use the alias path
            write_text(
                os.path.join(system_root, "roles", "role-a.md"),
                "See [skill](../skills/testing-alias/SKILL.md)\n",
            )
            write_text(
                os.path.join(system_root, "roles", "role-b.md"),
                "See [extra](../skills/testing-alias/extra.md)\n",
            )

            # Direct reference too, so testing is the primary
            write_text(
                os.path.join(system_root, "roles", "role-c.md"),
                "See [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [a](../../roles/role-a.md)\n"
                "See [b](../../roles/role-b.md)\n"
                "See [c](../../roles/role-c.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            self.assertEqual(len(result["inlined_skills"]), 1)
            aliases = result["inlined_skill_aliases"]
            # Only ONE alias entry despite two references via the alias
            self.assertEqual(len(aliases), 1, (
                f"Expected exactly 1 alias entry (no duplicates). "
                f"Got: {aliases}"
            ))


    def test_alias_root_loop_does_not_escape_system_root(self) -> None:
        """The alias-root detection loop must not walk above system_root.

        If a SKILL.md exists in a directory above system_root, the loop
        should ignore it — the ``is_within_directory`` guard prevents
        the walk from escaping the intended boundary.
        """
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Place a decoy SKILL.md ABOVE the system root.  Without the
            # boundary guard this would be incorrectly recorded as an
            # alias root.
            system_root = os.path.join(tmpdir, "outer", "root")
            decoy_dir = os.path.join(tmpdir, "outer")
            write_text(
                os.path.join(decoy_dir, "SKILL.md"),
                "---\nname: decoy\n---\nDecoy skill above system root.\n",
            )

            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")

            write_text(
                os.path.join(coordinator, "SKILL.md"),
                "---\nname: coordinator\n---\n",
            )
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n",
            )

            # Create a symlink alias for the testing skill.
            alias_path = os.path.join(
                system_root, "skills", "testing-alias"
            )
            try:
                os.symlink(testing, alias_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            # Role that references via the alias.
            write_text(
                os.path.join(system_root, "roles", "role.md"),
                "See [skill](../skills/testing-alias/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [role](../../roles/role.md)\n",
            )

            result = scan_references(
                coordinator,
                system_root,
                inline_orchestrated_skills=True,
            )

            # The alias should be recorded normally.
            self.assertEqual(len(result["inlined_skills"]), 1)
            aliases = result["inlined_skill_aliases"]
            self.assertEqual(len(aliases), 1)
            alias_abs, primary_abs = aliases[0]
            self.assertIn("testing-alias", alias_abs)
            # Primary should be within system_root, not the decoy.
            self.assertTrue(
                os.path.realpath(primary_abs).startswith(
                    os.path.realpath(system_root)
                ),
                f"Primary {primary_abs} should be within system_root",
            )
            # No errors — the decoy SKILL.md above system_root was
            # never reached by the alias-root walk.
            self.assertEqual(result["errors"], [])


# ===================================================================
# is_within_directory
# ===================================================================


class IsWithinDirectoryTests(unittest.TestCase):
    """Tests for is_within_directory()."""

    def test_file_inside_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "sub", "file.md")
            self.assertTrue(is_within_directory(filepath, tmpdir))

    def test_file_outside_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "..", "outside.md")
            self.assertFalse(is_within_directory(filepath, tmpdir))

    def test_commonpath_value_error_returns_false(self) -> None:
        """ValueError from commonpath (e.g. different Windows drives) returns False."""
        with patch("lib.references.os.path.commonpath", side_effect=ValueError):
            result = is_within_directory("/some/path", "/other/path")
        self.assertFalse(result)

    def test_dangling_symlink_inside_directory_returns_true(self) -> None:
        """A dangling symlink inside *directory* is judged by its location.

        Pinned regression: ``os.path.realpath`` on Windows cannot fully
        canonicalise a path whose final component is a symlink to a
        non-existent target — Python falls back to a partially
        resolved string that retains the unexpanded short-name
        component (``RUNNER~1``) while ``realpath(directory)`` for an
        existing directory expands to the long-name form.  The two
        paths then diverge under ``normcase`` and the function would
        falsely classify a dangling symlink inside the directory as
        external.  This test exercises the dangling-link branch
        directly so the rule is locked in on every host.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ref_dir = os.path.join(tmpdir, "references")
            os.makedirs(ref_dir)
            link = os.path.join(ref_dir, "guide.md")
            target = os.path.join(tmpdir, "missing-target.md")
            write_text(target, "x")
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported on this host")
            os.unlink(target)
            self.assertTrue(is_within_directory(link, tmpdir))


# ===================================================================
# extract_references
# ===================================================================


class ExtractReferencesTests(unittest.TestCase):
    """Tests for extract_references()."""

    def test_markdown_backtick_refs_extracted(self) -> None:
        """Backtick-wrapped paths in markdown are extracted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = os.path.join(tmpdir, "doc.md")
            write_text(md_file, "Use `references/guide.md` for details.\n")
            refs = extract_references(md_file)
        paths = [r[1] for r in refs]
        self.assertIn("references/guide.md", paths)

    def test_markdown_backtick_dedup_with_link(self) -> None:
        """A path in both link and backtick on the same line is not duplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = os.path.join(tmpdir, "doc.md")
            write_text(
                md_file,
                "See [guide](references/guide.md) or `references/guide.md`.\n",
            )
            refs = extract_references(md_file)
        paths = [r[1] for r in refs]
        self.assertEqual(paths.count("references/guide.md"), 1)

    def test_binary_file_returns_empty(self) -> None:
        """Binary files return an empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "image.png")
            with open(png_file, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")
            refs = extract_references(png_file)
        self.assertEqual(refs, [])

    def test_non_markdown_text_detection(self) -> None:
        """Non-markdown text files use text-detection mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = os.path.join(tmpdir, "config.yaml")
            write_text(yaml_file, "path: references/guide.md\n")
            refs = extract_references(yaml_file)
        self.assertGreater(len(refs), 0)
        types = [r[3] for r in refs]
        self.assertTrue(all(t == "text_detected" for t in types))

    def test_skip_and_empty_clean_path_filtered(self) -> None:
        """URLs and empty-after-strip refs are filtered out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = os.path.join(tmpdir, "doc.md")
            write_text(
                md_file,
                "See [link](https://example.com) and [anchor](#top).\n",
            )
            refs = extract_references(md_file)
        self.assertEqual(refs, [])

    def test_query_only_ref_stripped_to_empty(self) -> None:
        """A ref like '?query' strips to empty and is filtered out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = os.path.join(tmpdir, "doc.md")
            write_text(md_file, "See [q](?query)\n")
            refs = extract_references(md_file)
        self.assertEqual(refs, [])


# ===================================================================
# resolve_reference / resolve_reference_with_reason
# ===================================================================


class ResolveReferenceTests(unittest.TestCase):
    """Tests for resolve_reference and resolve_reference_with_reason."""

    def test_resolve_reference_delegates(self) -> None:
        """resolve_reference returns the same path as the _with_reason variant."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = os.path.join(tmpdir, "doc.md")
            target = os.path.join(tmpdir, "ref.md")
            write_text(source, "")
            write_text(target, "")
            result = resolve_reference("ref.md", source)
            self.assertEqual(result, os.path.normpath(target))

    def test_absolute_path_rejected(self) -> None:
        _, reason = resolve_reference_with_reason("/absolute/path.md", "/some/doc.md")
        self.assertEqual(reason, "absolute_path")

    def test_escapes_system_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = os.path.join(tmpdir, "root", "skills", "demo", "doc.md")
            write_text(source, "")
            system_root = os.path.join(tmpdir, "root")
            os.makedirs(system_root, exist_ok=True)
            _, reason = resolve_reference_with_reason(
                "../../../../outside.md", source, system_root,
            )
        self.assertEqual(reason, "escapes_system_root")

    def test_is_directory_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = os.path.join(tmpdir, "doc.md")
            write_text(source, "")
            ref_dir = os.path.join(tmpdir, "somedir")
            os.makedirs(ref_dir)
            _, reason = resolve_reference_with_reason("somedir", source)
        self.assertEqual(reason, "is_directory")

    def test_system_root_fallback_resolves(self) -> None:
        """A ref not found relative to source but found relative to system_root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            source = os.path.join(system_root, "skills", "demo", "doc.md")
            write_text(source, "")
            target = os.path.join(system_root, "references", "guide.md")
            write_text(target, "")
            resolved, reason = resolve_reference_with_reason(
                "references/guide.md", source, system_root,
            )
        self.assertIsNotNone(resolved)
        self.assertIsNone(reason)

    def test_system_root_fallback_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            source = os.path.join(system_root, "skills", "demo", "doc.md")
            write_text(source, "")
            os.makedirs(system_root, exist_ok=True)
            _, reason = resolve_reference_with_reason(
                "../../../outside.md", source, system_root,
            )
        self.assertEqual(reason, "escapes_system_root")

    def test_system_root_fallback_is_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            source = os.path.join(system_root, "skills", "demo", "doc.md")
            write_text(source, "")
            # Create a directory at system_root/references (not a file)
            os.makedirs(os.path.join(system_root, "references"))
            _, reason = resolve_reference_with_reason(
                "references", source, system_root,
            )
        self.assertEqual(reason, "is_directory")

    def test_system_root_fallback_escapes_system_root(self) -> None:
        """A ref within boundary from source dir but escaping from system_root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            # Source deep enough that ../../nonexistent.md stays within root
            source = os.path.join(
                system_root, "skills", "demo", "deep", "doc.md",
            )
            write_text(source, "")
            os.makedirs(system_root, exist_ok=True)
            # From source dir: root/skills/demo/deep/../../nonexistent.md
            #   = root/skills/nonexistent.md → within root, not found as file
            # From system_root: root/../../nonexistent.md → escapes root
            _, reason = resolve_reference_with_reason(
                "../../nonexistent.md", source, system_root,
            )
        self.assertEqual(reason, "escapes_system_root")

    def test_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = os.path.join(tmpdir, "doc.md")
            write_text(source, "")
            _, reason = resolve_reference_with_reason("nonexistent.md", source)
        self.assertEqual(reason, "not_found")


# ===================================================================
# walk_skill_files
# ===================================================================


class WalkSkillFilesTests(unittest.TestCase):
    """Tests for walk_skill_files()."""

    def test_excluded_files_skipped(self) -> None:
        """Files matching exclude patterns are not yielded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\n---\n")
            write_text(os.path.join(tmpdir, ".git", "config"), "git")
            files = list(walk_skill_files(tmpdir, [".git"], tmpdir))
        filenames = [f for _, f in files]
        self.assertNotIn("config", filenames)

    def test_boundary_violations_recorded(self) -> None:
        """Symlink boundary violations are recorded in the list."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            outside = os.path.join(tmpdir, "outside")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\n---\n")
            write_text(os.path.join(outside, "secret.md"), "secret")
            link = os.path.join(skill_dir, "secret.md")
            try:
                os.symlink(os.path.join(outside, "secret.md"), link)
            except OSError:
                self.skipTest("symlink creation not permitted")
            violations: list[BoundaryViolation] = []
            files = list(walk_skill_files(skill_dir, [], skill_dir, violations))
            filenames = [f for _, f in files]
        self.assertNotIn("secret.md", filenames)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].kind, "file")

    def test_boundary_violation_raises_when_no_list(self) -> None:
        """When violations list is None, ValueError is raised."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            outside = os.path.join(tmpdir, "outside")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\n---\n")
            write_text(os.path.join(outside, "secret.md"), "secret")
            link = os.path.join(skill_dir, "secret.md")
            try:
                os.symlink(os.path.join(outside, "secret.md"), link)
            except OSError:
                self.skipTest("symlink creation not permitted")
            with self.assertRaises(ValueError):
                list(walk_skill_files(skill_dir, [], skill_dir, None))

    def test_directory_boundary_violation_recorded(self) -> None:
        """Symlinked directory escaping boundary is recorded."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            outside = os.path.join(tmpdir, "outside")
            os.makedirs(os.path.join(skill_dir))
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\n---\n")
            os.makedirs(outside)
            write_text(os.path.join(outside, "data.md"), "data")
            link = os.path.join(skill_dir, "linked-dir")
            try:
                os.symlink(outside, link)
            except OSError:
                self.skipTest("symlink creation not permitted")
            violations: list[BoundaryViolation] = []
            list(walk_skill_files(skill_dir, [], skill_dir, violations))
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].kind, "directory")

    def test_directory_boundary_violation_raises_when_no_list(self) -> None:
        """Symlinked directory escaping boundary raises ValueError when violations is None."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            outside = os.path.join(tmpdir, "outside")
            os.makedirs(skill_dir)
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\n---\n")
            os.makedirs(outside)
            write_text(os.path.join(outside, "data.md"), "data")
            link = os.path.join(skill_dir, "linked-dir")
            try:
                os.symlink(outside, link)
            except OSError:
                self.skipTest("symlink creation not permitted")
            with self.assertRaises(ValueError):
                list(walk_skill_files(skill_dir, [], skill_dir, None))

    def test_symlink_target_excluded_component_skipped(self) -> None:
        """A symlink whose real target path contains an excluded component is skipped."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            hidden_dir = os.path.join(tmpdir, ".hidden")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\n---\n")
            target = os.path.join(hidden_dir, "data.md")
            write_text(target, "hidden data")
            # Symlink to a file whose real path contains .hidden
            link = os.path.join(skill_dir, "data.md")
            try:
                os.symlink(target, link)
            except OSError:
                self.skipTest("symlink creation not permitted")
            # Use tmpdir as boundary so the symlink target is within boundary
            # but its path contains ".hidden" which we exclude
            files = list(walk_skill_files(skill_dir, [".hidden"], tmpdir))
        filenames = [f for _, f in files]
        self.assertNotIn("data.md", filenames)


# ===================================================================
# scan_references — Exception handling branches
# ===================================================================


class ScanReferencesExceptionHandlingTests(unittest.TestCase):
    """Tests for UnicodeDecodeError and OSError handling in scan_references."""

    def test_unicode_decode_error_markdown_produces_fail(self) -> None:
        """A markdown file with invalid UTF-8 produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            bad_file = os.path.join(skill_dir, "bad.md")
            with open(bad_file, "wb") as f:
                f.write(b"\x80\x81\x82 broken utf-8")
            result = scan_references(skill_dir, tmpdir)
        fails = [e for e in result["errors"] if "Cannot read" in e and "UTF-8" in e]
        self.assertGreaterEqual(len(fails), 1)

    def test_unicode_decode_error_non_markdown_produces_warn(self) -> None:
        """A non-markdown file with invalid UTF-8 produces a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            bad_file = os.path.join(skill_dir, "data.yaml")
            with open(bad_file, "wb") as f:
                f.write(b"\x80\x81\x82 broken utf-8")
            result = scan_references(skill_dir, tmpdir)
        warns = [w for w in result["warnings"] if "Cannot read" in w and "UTF-8" in w]
        self.assertGreaterEqual(len(warns), 1)

    def test_os_error_markdown_produces_fail(self) -> None:
        """An OSError when reading a markdown file produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(skill_dir, "doc.md"), "content")
            with patch(
                "lib.references.extract_references",
                side_effect=OSError("mocked read error"),
            ):
                result = scan_references(skill_dir, tmpdir)
        fails = [e for e in result["errors"] if "Cannot read" in e]
        self.assertGreaterEqual(len(fails), 1)

    def test_os_error_non_markdown_produces_warn(self) -> None:
        """An OSError when reading a non-markdown file produces a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(skill_dir, "config.yaml"), "key: value")

            original = extract_references

            def selective_oserror(filepath: str) -> list:
                if filepath.endswith(".yaml"):
                    raise OSError("mocked")
                return original(filepath)

            with patch(
                "lib.references.extract_references",
                side_effect=selective_oserror,
            ):
                result = scan_references(skill_dir, tmpdir)
        warns = [w for w in result["warnings"] if "Cannot read" in w]
        self.assertGreaterEqual(len(warns), 1)


# ===================================================================
# scan_references — Fail reason branches
# ===================================================================


class ScanReferencesFailReasonTests(unittest.TestCase):
    """Tests for absolute_path, escapes_system_root, is_directory failures in scan."""

    def test_absolute_reference_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [abs](/absolute/path.md)\n",
            )
            result = scan_references(skill_dir, system_root)
        fails = [e for e in result["errors"] if "absolute" in e.lower()]
        self.assertGreaterEqual(len(fails), 1)

    def test_escapes_system_root_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [out](../../../../outside.md)\n",
            )
            result = scan_references(skill_dir, system_root)
        fails = [e for e in result["errors"] if "escapes" in e.lower()]
        self.assertGreaterEqual(len(fails), 1)

    def test_is_directory_reference_produces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            os.makedirs(os.path.join(skill_dir, "somedir"))
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [dir](somedir)\n",
            )
            result = scan_references(skill_dir, system_root)
        fails = [e for e in result["errors"] if "directory" in e.lower()]
        self.assertGreaterEqual(len(fails), 1)


# ===================================================================
# classify_external_file
# ===================================================================


class ClassifyExternalFileTests(unittest.TestCase):
    """Tests for classify_external_file()."""

    def test_no_system_root_returns_references(self) -> None:
        self.assertEqual(classify_external_file("/any/path.md", None), "references")

    def test_roles_classification(self) -> None:
        result = classify_external_file("/root/roles/eng/release.md", "/root")
        self.assertEqual(result, "roles")

    def test_assets_classification(self) -> None:
        result = classify_external_file("/root/assets/template.md", "/root")
        self.assertEqual(result, "assets")

    def test_scripts_classification(self) -> None:
        result = classify_external_file("/root/scripts/validate.py", "/root")
        self.assertEqual(result, "scripts")

    def test_unknown_returns_references(self) -> None:
        result = classify_external_file("/root/other/misc.md", "/root")
        self.assertEqual(result, "references")


# ===================================================================
# compute_bundle_path
# ===================================================================


class ComputeBundlePathTests(unittest.TestCase):
    """Tests for compute_bundle_path()."""

    def test_role_preserves_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = tmpdir
            role_file = os.path.join(tmpdir, "roles", "eng", "release.md")
            write_text(role_file, "")
            result = compute_bundle_path(role_file, system_root)
        self.assertEqual(result, "roles/eng/release.md")

    def test_references_within_category_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = tmpdir
            ref_file = os.path.join(tmpdir, "references", "sub", "guide.md")
            write_text(ref_file, "")
            result = compute_bundle_path(ref_file, system_root)
        self.assertEqual(result, "references/sub/guide.md")

    def test_no_system_root_uses_basename(self) -> None:
        result = compute_bundle_path("/any/path/guide.md", None)
        self.assertEqual(result, "references/guide.md")

    def test_file_outside_category_uses_basename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = tmpdir
            misc_file = os.path.join(tmpdir, "other", "misc.md")
            write_text(misc_file, "")
            result = compute_bundle_path(misc_file, system_root)
        self.assertEqual(result, "references/misc.md")


# ===================================================================
# infer_system_root
# ===================================================================


class InferSystemRootTests(unittest.TestCase):
    """Tests for infer_system_root()."""

    def test_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "project")
            skill_dir = os.path.join(system_root, "skills", "demo")
            os.makedirs(skill_dir)
            write_text(os.path.join(system_root, "manifest.yaml"), "name: test\n")
            result = infer_system_root(skill_dir)
        self.assertEqual(os.path.realpath(result), os.path.realpath(system_root))

    def test_from_skills_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "project")
            skill_dir = os.path.join(system_root, "skills", "demo")
            os.makedirs(skill_dir)
            result = infer_system_root(skill_dir)
        self.assertEqual(os.path.realpath(result), os.path.realpath(system_root))

    def test_returns_none_when_no_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "isolated")
            os.makedirs(skill_dir)
            result = infer_system_root(skill_dir)
        self.assertIsNone(result)


# ===================================================================
# scan_references — commonpath ValueError branches
# ===================================================================


class ScanReferencesCommonpathValueErrorTests(unittest.TestCase):
    """Tests for commonpath ValueError fallback branches in scan_references."""

    def test_commonpath_valueerror_in_lexical_within_skill(self) -> None:
        """ValueError from commonpath at line 769 (lexical_within_skill) is handled."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_a = os.path.join(system_root, "skills", "alpha")
            skill_b = os.path.join(system_root, "skills", "beta")
            write_text(os.path.join(skill_a, "SKILL.md"), "---\nname: alpha\n---\n")
            write_text(os.path.join(skill_b, "SKILL.md"), "---\nname: beta\n---\n")
            target_file = os.path.join(skill_b, "notes.md")
            write_text(target_file, "Beta notes\n")

            link_path = os.path.join(skill_a, "borrowed.md")
            try:
                os.symlink(target_file, link_path)
            except OSError:
                self.skipTest("symlink creation not permitted")

            write_text(
                os.path.join(skill_a, "doc.md"),
                "See [borrowed](borrowed.md)\n",
            )

            original_commonpath = os.path.commonpath
            # Line 769: commonpath([lexical_path_norm, skill_norm])
            # lexical_path_norm = normcase(abspath(resolved)) = alpha/borrowed.md
            # skill_norm = normcase(current_skill) = alpha
            # We want to raise ValueError for this specific call.
            lexical_resolved = os.path.normcase(os.path.abspath(link_path))
            skill_a_norm = os.path.normcase(os.path.abspath(skill_a))

            def raise_for_lexical_check(paths: list[str]) -> str:
                normed = [os.path.normcase(p) for p in paths]
                if (
                    len(normed) == 2
                    and skill_a_norm in normed
                    and lexical_resolved in normed
                ):
                    raise ValueError("mocked different drives")
                return original_commonpath(paths)

            with patch("lib.references.os.path.commonpath", side_effect=raise_for_lexical_check):
                result = scan_references(skill_a, system_root)

            # ValueError means lexical_within_skill stays False, so the
            # symlink reference is treated as external and recorded in
            # external_files (by its resolved absolute path within alpha/).
            self.assertIn(
                os.path.abspath(link_path), result["external_files"],
            )

    def test_commonpath_valueerror_in_under_skills_root(self) -> None:
        """ValueError from commonpath at line 792 (under_skills_root) is handled."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_a = os.path.join(system_root, "skills", "alpha")
            skill_b = os.path.join(system_root, "skills", "beta")
            write_text(os.path.join(skill_a, "SKILL.md"), "---\nname: alpha\n---\n")
            write_text(os.path.join(skill_b, "SKILL.md"), "---\nname: beta\n---\n")
            target_file = os.path.join(skill_b, "notes.md")
            write_text(target_file, "Beta notes\n")

            link_path = os.path.join(skill_a, "borrowed.md")
            try:
                os.symlink(target_file, link_path)
            except OSError:
                self.skipTest("symlink creation not permitted")

            write_text(
                os.path.join(skill_a, "doc.md"),
                "See [borrowed](borrowed.md)\n",
            )

            original_commonpath = os.path.commonpath
            # Line 792: commonpath([resolved_real, skills_root_real])
            skills_root_real = os.path.normcase(os.path.realpath(
                os.path.join(system_root, "skills")
            ))
            resolved_real = os.path.normcase(os.path.realpath(target_file))

            def raise_for_under_skills_root(paths: list[str]) -> str:
                normed = [os.path.normcase(p) for p in paths]
                if (
                    len(normed) == 2
                    and skills_root_real in normed
                    and resolved_real in normed
                ):
                    raise ValueError("mocked different drives")
                return original_commonpath(paths)

            with patch("lib.references.os.path.commonpath", side_effect=raise_for_under_skills_root):
                result = scan_references(skill_a, system_root)

            # ValueError means under_skills_root = False, so the
            # cross-skill symlink check is bypassed.
            # Ensure we don't report a cross-skill symlink error in this case.
            self.assertIsInstance(result["errors"], list)
            self.assertFalse(
                any("Symlinked reference" in str(err) for err in result["errors"]),
                "cross-skill symlink error should be bypassed when under_skills_root "
                "check raises ValueError",
            )
            # And the symlinked file should not be treated as an external file.
            self.assertIn("external_files", result)
            self.assertFalse(
                result["external_files"],
                "symlink under skills root should not be classified as external "
                "when under_skills_root check fails",
            )

    def test_commonpath_valueerror_in_already_inlined_check(self) -> None:
        """ValueError from commonpath at line 692 (already-inlined lexical) is handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")
            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing, "notes.md"), "Testing notes\n")

            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            original_commonpath = os.path.commonpath
            testing_real = os.path.normcase(os.path.realpath(testing))

            def raise_for_already_inlined(paths: list[str]) -> str:
                # Line 692: commonpath([resolved_norm, matched_norm])
                # matched_norm is the inlined skill dir (testing).
                normed = [os.path.normcase(p) for p in paths]
                if len(normed) == 2 and testing_real in normed:
                    other = [p for p in normed if p != testing_real]
                    # Only raise when checking a file in testing against
                    # testing itself (the already-inlined check)
                    if other and "testing" in other[0] and other[0] != testing_real:
                        raise ValueError("mocked different drives")
                return original_commonpath(paths)

            with patch("lib.references.os.path.commonpath", side_effect=raise_for_already_inlined):
                result = scan_references(
                    coordinator, system_root,
                    inline_orchestrated_skills=True,
                )

            # The testing skill should still be collected
            self.assertEqual(len(result["inlined_skills"]), 1)


# ===================================================================
# scan_references — relpath ValueError
# ===================================================================


class ScanReferencesRelpathValueErrorTests(unittest.TestCase):
    """Tests for os.path.relpath ValueError in inlined skill collection."""

    def test_relpath_valueerror_falls_back_to_abs_skill_dir(self) -> None:
        """ValueError from relpath at line 908 falls back to abs_skill_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")
            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")

            role_file = os.path.join(system_root, "roles", "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../../roles/qa-role.md)\n",
            )

            original_relpath = os.path.relpath
            sr_real = os.path.normcase(os.path.realpath(system_root))

            def selective_valueerror(path: str, start: str | None = None) -> str:
                # Line 908: os.path.relpath(real_skill_dir, _sr_real)
                # Raise when computing relpath from system_root's realpath
                if start is not None:
                    start_norm = os.path.normcase(start)
                    if start_norm == sr_real:
                        path_norm = os.path.normcase(path)
                        if "testing" in path_norm:
                            raise ValueError("mocked cross-drive relpath")
                return original_relpath(path, start) if start is not None else original_relpath(path)

            with patch("lib.references.os.path.relpath", side_effect=selective_valueerror):
                result = scan_references(
                    coordinator, system_root,
                    inline_orchestrated_skills=True,
                )

            # The skill should still be collected despite the ValueError
            self.assertEqual(len(result["inlined_skills"]), 1)

    def test_no_system_root_uses_abs_skill_dir(self) -> None:
        """When system_root is None, primary_dir falls back to abs_skill_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Place skills directly under tmpdir without a skills/ parent
            # directory or manifest.yaml, so infer_system_root() returns None
            # and the primary_dir fallback at line 918-919 is exercised.
            coordinator = os.path.join(tmpdir, "coordinator")
            testing = os.path.join(tmpdir, "testing")
            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")

            role_file = os.path.join(tmpdir, "qa-role.md")
            write_text(
                role_file,
                "# QA Role\nSee [skill](./testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc.md"),
                "See [qa role](../qa-role.md)\n",
            )

            # system_root=None triggers inference; with no manifest or
            # skills/ directory markers, infer_system_root() returns None
            # so primary_dir falls back to abs_skill_dir (line 918-919).
            result = scan_references(
                coordinator, system_root=None,
                inline_orchestrated_skills=True,
            )

            # Without system root, cross-skill refs produce at least one error
            self.assertGreater(len(result["errors"]), 0)


# ===================================================================
# scan_references — already-collected alias dedup
# ===================================================================


class ScanReferencesAlreadyCollectedAliasDedupTests(unittest.TestCase):
    """Tests for the already-collected alias dedup path (lines 935-950)."""

    def test_same_skill_discovered_via_two_aliases(self) -> None:
        """A skill referenced twice via different aliases records both aliases."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            coordinator = os.path.join(system_root, "skills", "coordinator")
            testing = os.path.join(system_root, "skills", "testing")
            write_text(os.path.join(coordinator, "SKILL.md"), "---\nname: coordinator\n---\n")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing, "notes.md"), "Testing notes\n")

            # Two symlink aliases pointing to the same testing skill
            alias1 = os.path.join(system_root, "skills", "testing-alias1")
            alias2 = os.path.join(system_root, "skills", "testing-alias2")
            try:
                os.symlink(testing, alias1)
                os.symlink(testing, alias2)
            except OSError:
                self.skipTest("symlink creation not permitted")

            # Role references via first alias
            role1 = os.path.join(system_root, "roles", "role1.md")
            write_text(
                role1,
                "# Role 1\nSee [skill](../skills/testing-alias1/SKILL.md)\n",
            )
            # Second role references via second alias
            role2 = os.path.join(system_root, "roles", "role2.md")
            write_text(
                role2,
                "# Role 2\nSee [skill](../skills/testing-alias2/SKILL.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc1.md"),
                "See [role1](../../roles/role1.md)\n",
            )
            write_text(
                os.path.join(coordinator, "doc2.md"),
                "See [role2](../../roles/role2.md)\n",
            )

            result = scan_references(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )

            # The testing skill collected once, both aliases recorded
            self.assertEqual(len(result["inlined_skills"]), 1)
            self.assertEqual(len(result["inlined_skill_aliases"]), 2)


# ===================================================================
# scan_references — display path fallback
# ===================================================================


class ScanReferencesDisplayPathTests(unittest.TestCase):
    """Tests for the _rel display path fallback (line 1084)."""

    def test_display_path_outside_both_skill_and_system(self) -> None:
        """A reference escaping system root shows doc.md display path in error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            # Create an external file completely outside system_root
            outside = os.path.join(tmpdir, "outside", "ext.md")
            write_text(outside, "External\n")

            # Reference pointing outside system root
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [ext](../../../outside/ext.md)\n",
            )

            result = scan_references(skill_dir, system_root)

        # Should produce an escapes error with the referencing file's
        # display path (relative to skill dir since doc.md is inside the skill)
        fails = [e for e in result["errors"] if "escapes" in e.lower()]
        self.assertGreaterEqual(len(fails), 1)
        # The _rel() display path for doc.md is relative to skill_dir
        self.assertTrue(
            any("doc.md" in e for e in fails),
            f"Expected 'doc.md' in error messages, got: {fails}",
        )

    def test_display_path_no_system_root_outside_skill(self) -> None:
        """With system_root=None, a file outside the skill uses absolute path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "standalone")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            ext = os.path.join(tmpdir, "outside.md")
            write_text(ext, "External\n")
            write_text(
                os.path.join(skill_dir, "doc.md"),
                "See [ext](../outside.md)\n",
            )
            # No system_root markers, so inference returns None
            result = scan_references(skill_dir, system_root=None)
        # Should warn about no system root with the display path
        fails = [e for e in result["errors"] if "no system root" in e]
        self.assertGreaterEqual(len(fails), 1)


# ===================================================================
# scan_references — text_detected recursion
# ===================================================================


class ScanReferencesTextDetectedRecursionTests(unittest.TestCase):
    """Tests for non-markdown text_detected reference recursion."""

    def test_text_detected_ref_recurses(self) -> None:
        """A text-detected reference should recurse into the referenced file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            # YAML file referencing an external reference
            guide = os.path.join(system_root, "references", "guide.md")
            write_text(guide, "# Guide\n")
            write_text(
                os.path.join(skill_dir, "config.yaml"),
                "path: references/guide.md\n",
            )

            # The guide itself references another file
            deep = os.path.join(system_root, "references", "deep.md")
            write_text(deep, "# Deep\n")
            write_text(guide, "See [deep](deep.md)\n")

            result = scan_references(skill_dir, system_root)

        # Both guide.md and deep.md should be in external_files
        self.assertIn(os.path.abspath(guide), result["external_files"])
        self.assertIn(os.path.abspath(deep), result["external_files"])

    def test_text_detected_already_scanned_skips_rescan(self) -> None:
        """Two non-markdown files referencing the same external file — second skips rescan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            guide = os.path.join(system_root, "references", "guide.md")
            write_text(guide, "# Guide\n")

            # Two YAML files both text-detect the same external ref
            write_text(
                os.path.join(skill_dir, "config1.yaml"),
                "path: references/guide.md\n",
            )
            write_text(
                os.path.join(skill_dir, "config2.yaml"),
                "path: references/guide.md\n",
            )

            result = scan_references(skill_dir, system_root)

        # guide.md collected once, two warnings (one per yaml file)
        self.assertIn(os.path.abspath(guide), result["external_files"])
        text_warns = [w for w in result["warnings"] if "Non-markdown" in w]
        self.assertEqual(len(text_warns), 2)

    def test_already_scanned_external_not_rescanned(self) -> None:
        """An external file referenced from two internal files is scanned once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")

            shared = os.path.join(system_root, "references", "shared.md")
            write_text(shared, "Shared content\n")

            # Two files reference the same external file
            write_text(
                os.path.join(skill_dir, "doc1.md"),
                "See [shared](../../references/shared.md)\n",
            )
            write_text(
                os.path.join(skill_dir, "doc2.md"),
                "See [shared](../../references/shared.md)\n",
            )

            result = scan_references(skill_dir, system_root)

        # The file appears exactly once in external_files (set deduplication)
        self.assertIn(os.path.abspath(shared), result["external_files"])
        self.assertEqual(result["errors"], [])


class ResolveCaseExactTests(unittest.TestCase):
    """``resolve_case_exact`` enforces byte-exact case at every component."""

    def test_exact_case_returns_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "references"))
            target = os.path.join(tmpdir, "references", "foo.md")
            write_text(target, "x")
            ok, suggested = resolve_case_exact(tmpdir, target)
            self.assertTrue(ok)
            self.assertIsNone(suggested)

    def test_wrong_case_in_directory_component_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "references"))
            target = os.path.join(tmpdir, "references", "foo.md")
            write_text(target, "x")
            wrong = os.path.join(tmpdir, "References", "foo.md")
            ok, suggested = resolve_case_exact(tmpdir, wrong)
            self.assertFalse(ok)
            self.assertEqual(suggested, "references/foo.md")

    def test_wrong_case_in_filename_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "references"))
            target = os.path.join(tmpdir, "references", "foo.md")
            write_text(target, "x")
            wrong = os.path.join(tmpdir, "references", "FOO.md")
            ok, suggested = resolve_case_exact(tmpdir, wrong)
            # On case-sensitive Linux the file does not exist at all;
            # the helper returns (False, None) in that case.  On
            # case-insensitive macOS / NTFS the file exists under a
            # different case and the helper produces a suggestion.
            if suggested is None:
                self.assertFalse(ok)
            else:
                self.assertFalse(ok)
                self.assertEqual(suggested, "references/foo.md")

    def test_missing_file_returns_false_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "references"))
            wrong = os.path.join(tmpdir, "references", "missing.md")
            ok, suggested = resolve_case_exact(tmpdir, wrong)
            self.assertFalse(ok)
            self.assertIsNone(suggested)

    def test_path_outside_root_falls_back_to_existence(self) -> None:
        with tempfile.TemporaryDirectory() as outer:
            inner = os.path.join(outer, "skill")
            sibling = os.path.join(outer, "sibling")
            os.makedirs(inner)
            os.makedirs(sibling)
            target = os.path.join(sibling, "ref.md")
            write_text(target, "x")
            ok, suggested = resolve_case_exact(inner, target)
            # Outside the skill root, the helper defers to existence
            # without applying the case-exact rule.
            self.assertTrue(ok)
            self.assertIsNone(suggested)


class ResolveCaseExactCacheTests(unittest.TestCase):
    """``resolve_case_exact`` memoises listdir when given a cache."""

    def test_cache_amortises_listdir_across_resolutions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "references"))
            for name in ("a.md", "b.md", "c.md"):
                write_text(os.path.join(tmpdir, "references", name), "x")
            cache: dict[str, list[str]] = {}
            from unittest import mock
            with mock.patch(
                "lib.references.os.listdir",
                wraps=os.listdir,
            ) as spy:
                for name in ("a.md", "b.md", "c.md"):
                    target = os.path.join(tmpdir, "references", name)
                    ok, _ = resolve_case_exact(
                        tmpdir, target, listdir_cache=cache,
                    )
                    self.assertTrue(ok)
                # 3 resolutions, 2 components each = 6 listdir calls
                # without cache.  With the cache, only 2 unique
                # directories (root + references) are inspected.
                self.assertEqual(spy.call_count, 2)

    def test_no_cache_keeps_per_resolution_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "references"))
            for name in ("a.md", "b.md"):
                write_text(os.path.join(tmpdir, "references", name), "x")
            from unittest import mock
            with mock.patch(
                "lib.references.os.listdir",
                wraps=os.listdir,
            ) as spy:
                for name in ("a.md", "b.md"):
                    target = os.path.join(tmpdir, "references", name)
                    resolve_case_exact(tmpdir, target)
                # 2 resolutions * 2 components = 4 listdir calls
                # without the cache.
                self.assertEqual(spy.call_count, 4)


class LooksLikeDegradedSymlinkTests(unittest.TestCase):
    """The Windows-without-DevMode degraded-symlink heuristic.

    The heuristic has two stages: shape match (small file, single
    relative-path line) and broken-target confirmation (the captured
    path does not resolve to an existing file).  Both stages must
    pass for the helper to return True so a deliberate one-line
    note that points at a real file is not misclassified.
    """

    def test_shape_match_with_missing_target_returns_true(self) -> None:
        # shim.md content is "../../target/foo.md"; that target does
        # not exist, so the helper recognises the degraded shape.
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "shim.md")
            write_text(p, "../../target/foo.md")
            self.assertTrue(looks_like_degraded_symlink(p))

    def test_dot_relative_with_missing_target_returns_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "shim.md")
            # ``./target/foo.md`` resolves to ``<tmpdir>/target/foo.md``
            # which does not exist; the degraded shape applies.
            write_text(p, "./target/foo.md")
            self.assertTrue(looks_like_degraded_symlink(p))

    def test_one_line_note_pointing_at_real_file_does_not_match(self) -> None:
        # Real one-line markdown note whose body is a relative path
        # that DOES resolve.  This is the false-positive case the
        # broken-target stage protects against — the file is
        # deliberate content, not a degraded symlink.
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "full-content.md")
            write_text(target, "# Full content\n")
            note = os.path.join(tmpdir, "see-also.md")
            write_text(note, "./full-content.md")
            self.assertFalse(looks_like_degraded_symlink(note))

    def test_real_markdown_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "real.md")
            write_text(p, "# Heading\n\nSome body content here.\n")
            self.assertFalse(looks_like_degraded_symlink(p))

    def test_oversize_file_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "big.md")
            # 600-byte file with a path-shaped first line — still
            # rejected because the size exceeds the heuristic ceiling.
            write_text(p, ("../../target/foo.md\n" + "x" * 600))
            self.assertFalse(looks_like_degraded_symlink(p))

    def test_empty_file_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "empty.md")
            write_text(p, "")
            self.assertFalse(looks_like_degraded_symlink(p))

    def test_missing_file_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse(
                looks_like_degraded_symlink(
                    os.path.join(tmpdir, "missing.md")
                )
            )

    def test_multiline_path_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "shim.md")
            write_text(p, "../target/foo.md\n../target/bar.md\n")
            self.assertFalse(looks_like_degraded_symlink(p))

    def test_bare_name_with_missing_target_returns_true(self) -> None:
        # Git stores ``ln -s sibling.md link.md`` as the literal
        # string ``sibling.md`` with no leading slash or dot.  This
        # is the most common foundry shim shape (e.g.,
        # ``CLAUDE.md → AGENTS.md``); the regex must catch it.
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "shim.md")
            write_text(p, "missing-sibling.md")
            self.assertTrue(looks_like_degraded_symlink(p))

    def test_multi_component_bare_target_with_missing_target_returns_true(
        self,
    ) -> None:
        # ``ln -s sub/dir/foo.md link.md`` stores as
        # ``sub/dir/foo.md`` — multi-component, no leading dot or
        # slash.  Still a valid shim shape.
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "shim.md")
            write_text(p, "sub/dir/missing.md")
            self.assertTrue(looks_like_degraded_symlink(p))

    def test_bare_name_pointing_at_real_file_does_not_match(self) -> None:
        # The bare-name shape only triggers when the target is
        # missing.  A one-line note whose bare-name target resolves
        # to a real sibling is deliberate content.
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "real-target.md")
            write_text(target, "# Real\n")
            shim = os.path.join(tmpdir, "see.md")
            write_text(shim, "real-target.md")
            self.assertFalse(looks_like_degraded_symlink(shim))

    def test_non_foundry_extension_does_not_match(self) -> None:
        # The pattern restricts the trailing extension to file types
        # the foundry actually ships.  A one-line file ending in
        # ``.exe`` cannot accidentally trip the heuristic.
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "shim.md")
            write_text(p, "../target/payload.exe")
            self.assertFalse(looks_like_degraded_symlink(p))


class IsDanglingSymlinkTests(unittest.TestCase):
    """``is_dangling_symlink`` reports symlinks whose target is missing."""

    def test_link_to_existing_file_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            real = os.path.join(tmpdir, "real.md")
            write_text(real, "x")
            link = os.path.join(tmpdir, "link.md")
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported on this host")
            self.assertFalse(is_dangling_symlink(link))

    def test_link_to_missing_target_returns_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            link = os.path.join(tmpdir, "link.md")
            try:
                os.symlink(os.path.join(tmpdir, "missing.md"), link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported on this host")
            self.assertTrue(is_dangling_symlink(link))

    def test_plain_missing_file_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse(
                is_dangling_symlink(os.path.join(tmpdir, "missing.md"))
            )


if __name__ == "__main__":
    unittest.main()
