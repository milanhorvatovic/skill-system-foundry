"""Tests for validate_skill.py.

Covers validate_description, validate_body, validate_directories,
validate_skill, and the main() CLI entry point.
"""

import os
import subprocess
import sys
import tempfile
import unittest

from helpers import write_text, write_skill_md

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, "validate_skill.py")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from validate_skill import (
    validate_body,
    validate_description,
    validate_directories,
    validate_skill,
)
from lib.constants import (
    LEVEL_FAIL,
    LEVEL_INFO,
    LEVEL_WARN,
    MAX_BODY_LINES,
    MAX_COMPATIBILITY_CHARS,
    MAX_DESCRIPTION_CHARS,
    RECOGNIZED_DIRS,
)


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Run validate_skill.py with *args* in *cwd* and return the result."""
    return subprocess.run(
        [sys.executable, VALIDATE_SCRIPT] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _write_capability_md(
    cap_dir: str,
    *,
    frontmatter: str | None = None,
    body: str = "# Capability\n",
) -> None:
    """Write a capability.md file into *cap_dir*."""
    body_text = body if body.endswith("\n") else f"{body}\n"
    if frontmatter is not None:
        content = f"---\n{frontmatter}\n---\n\n{body_text}"
    else:
        content = body_text
    write_text(os.path.join(cap_dir, "capability.md"), content)


# ===================================================================
# validate_description
# ===================================================================


class ValidateDescriptionTests(unittest.TestCase):
    """Tests for the validate_description function."""

    def test_empty_description_returns_fail(self) -> None:
        """An empty description produces a FAIL error."""
        errors, passes = validate_description("")
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_FAIL, errors[0])
        self.assertIn("empty", errors[0])
        self.assertEqual(passes, [])

    def test_valid_third_person_description(self) -> None:
        """A valid third-person description within limits produces passes."""
        desc = "Processes data files and generates summary reports."
        errors, passes = validate_description(desc)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        self.assertTrue(len(passes) >= 2)
        # Should have a char-count pass and a voice pass
        char_pass = [p for p in passes if "chars" in p]
        voice_pass = [p for p in passes if "third-person" in p]
        self.assertEqual(len(char_pass), 1)
        self.assertEqual(len(voice_pass), 1)

    def test_description_exceeding_max_chars_returns_fail(self) -> None:
        """A description exceeding MAX_DESCRIPTION_CHARS produces a FAIL."""
        desc = "x" * (MAX_DESCRIPTION_CHARS + 1)
        errors, passes = validate_description(desc)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn("exceeds", fail_errors[0])
        self.assertIn(str(MAX_DESCRIPTION_CHARS), fail_errors[0])

    def test_description_at_max_chars_passes(self) -> None:
        """A description exactly at MAX_DESCRIPTION_CHARS passes the length check."""
        desc = "a" * MAX_DESCRIPTION_CHARS
        errors, passes = validate_description(desc)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        char_pass = [p for p in passes if "chars" in p]
        self.assertEqual(len(char_pass), 1)

    def test_description_with_xml_tags_returns_warn(self) -> None:
        """A description containing XML tags produces a WARN."""
        desc = "Provides <tool>data</tool> processing capabilities."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        xml_warns = [e for e in warn_errors if "XML" in e]
        self.assertEqual(len(xml_warns), 1)

    def test_description_with_first_person_returns_warn(self) -> None:
        """A description using first person (I can, I will, etc.) produces a WARN."""
        desc = "I can process data files and generate reports."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        first_person_warns = [e for e in warn_errors if "first person" in e]
        self.assertEqual(len(first_person_warns), 1)

    def test_description_with_first_person_plural_returns_warn(self) -> None:
        """A description using first-person plural (we, our) produces a WARN."""
        desc = "We can help with data processing tasks."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        plural_warns = [e for e in warn_errors if "first-person plural" in e]
        self.assertEqual(len(plural_warns), 1)

    def test_description_with_second_person_returns_warn(self) -> None:
        """A description using second person (you, your) produces a WARN."""
        desc = "You can use this to process your data files."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        second_person_warns = [e for e in warn_errors if "second person" in e]
        self.assertEqual(len(second_person_warns), 1)

    def test_description_with_imperative_start_returns_warn(self) -> None:
        """A description starting with an imperative verb produces a WARN."""
        desc = "Process data files and generate summary reports."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        imperative_warns = [e for e in warn_errors if "imperative" in e]
        self.assertEqual(len(imperative_warns), 1)

    def test_imperative_multi_word_set_up_returns_warn(self) -> None:
        """The multi-word imperative verb 'Set up' is detected."""
        desc = "Set up CI pipelines for containerized deployments."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        imperative_warns = [e for e in warn_errors if "imperative" in e]
        self.assertEqual(len(imperative_warns), 1)

    def test_imperative_verbs_representative_sample(self) -> None:
        """A representative sample of imperative verbs are all detected."""
        verbs = [
            "Create", "Build", "Deploy", "Execute", "Generate",
            "Scaffold", "Orchestrate", "Audit", "Migrate", "Provision",
        ]
        for verb in verbs:
            desc = f"{verb} robust infrastructure for the project."
            errors, passes = validate_description(desc)
            imperative_warns = [
                e for e in errors
                if e.startswith(LEVEL_WARN) and "imperative" in e
            ]
            with self.subTest(verb=verb):
                self.assertEqual(
                    len(imperative_warns), 1,
                    f"Expected imperative WARN for verb '{verb}', "
                    f"got errors={errors}, passes={passes}",
                )

    def test_imperative_detection_is_case_insensitive(self) -> None:
        """Imperative detection works regardless of case."""
        for desc in [
            "create robust infrastructure for the project.",
            "CREATE robust infrastructure for the project.",
        ]:
            errors, passes = validate_description(desc)
            imperative_warns = [
                e for e in errors
                if e.startswith(LEVEL_WARN) and "imperative" in e
            ]
            with self.subTest(desc=desc):
                self.assertEqual(len(imperative_warns), 1)

    def test_first_person_all_variants_detected(self) -> None:
        """All first-person singular variants (I can, I will, I help, I am) are detected."""
        phrases = ["I can do it.", "I will help.", "I help teams.", "I am a tool."]
        for phrase in phrases:
            desc = f"Sometimes {phrase}"
            errors, passes = validate_description(desc)
            first_warns = [
                e for e in errors
                if e.startswith(LEVEL_WARN) and "first person" in e
            ]
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    len(first_warns), 1,
                    f"Expected first-person WARN for '{phrase}', got errors={errors}",
                )

    def test_voice_cascade_first_person_takes_priority(self) -> None:
        """When both first-person and second-person are present, only first-person fires."""
        desc = "I can help you manage your data files effectively."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        first_warns = [e for e in warn_errors if "first person" in e]
        second_warns = [e for e in warn_errors if "second person" in e]
        # Only first-person should fire due to elif chain
        self.assertEqual(len(first_warns), 1)
        self.assertEqual(len(second_warns), 0)

    def test_voice_cascade_first_plural_before_second(self) -> None:
        """When first-person plural and second-person are present, only plural fires."""
        desc = "We can help you manage your data files effectively."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        plural_warns = [e for e in warn_errors if "first-person plural" in e]
        second_warns = [e for e in warn_errors if "second person" in e]
        self.assertEqual(len(plural_warns), 1)
        self.assertEqual(len(second_warns), 0)

    def test_description_third_person_no_voice_warnings(self) -> None:
        """A proper third-person description produces no voice warnings."""
        desc = "Manages project timelines and tracks milestones."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        voice_warns = [
            e for e in warn_errors
            if "person" in e or "imperative" in e
        ]
        self.assertEqual(voice_warns, [])
        voice_pass = [p for p in passes if "third-person" in p]
        self.assertEqual(len(voice_pass), 1)


# ===================================================================
# validate_body
# ===================================================================


class ValidateBodyTests(unittest.TestCase):
    """Tests for the validate_body function."""

    def test_body_within_max_lines_passes(self) -> None:
        """A body within MAX_BODY_LINES produces a pass."""
        body = "\n".join(f"Line {i}" for i in range(10))
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        line_pass = [p for p in passes if "lines" in p]
        self.assertEqual(len(line_pass), 1)
        fail_errors = [e for e in errors if "lines" in e]
        self.assertEqual(fail_errors, [])

    def test_body_at_exactly_max_lines_passes(self) -> None:
        """A body at exactly MAX_BODY_LINES produces a pass, not a WARN."""
        body = "\n".join(f"Line {i}" for i in range(MAX_BODY_LINES))
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        line_pass = [p for p in passes if "lines" in p]
        self.assertEqual(len(line_pass), 1)
        line_warns = [e for e in errors if "lines" in e]
        self.assertEqual(line_warns, [])

    def test_body_one_over_max_lines_returns_warn(self) -> None:
        """A body at MAX_BODY_LINES + 1 produces a WARN."""
        body = "\n".join(f"Line {i}" for i in range(MAX_BODY_LINES + 1))
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        line_warns = [e for e in warn_errors if "lines" in e]
        self.assertEqual(len(line_warns), 1)
        self.assertIn(str(MAX_BODY_LINES + 1), line_warns[0])

    def test_body_exceeding_max_lines_returns_warn(self) -> None:
        """A body well above MAX_BODY_LINES produces a WARN."""
        body = "\n".join(f"Line {i}" for i in range(MAX_BODY_LINES + 10))
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        line_warns = [e for e in warn_errors if "lines" in e]
        self.assertEqual(len(line_warns), 1)

    def test_empty_body_passes_line_check(self) -> None:
        """An empty body (0 lines) passes the line count check."""
        body = ""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        line_pass = [p for p in passes if "lines" in p]
        self.assertEqual(len(line_pass), 1)
        self.assertIn("0 lines", line_pass[0])
        line_warns = [e for e in errors if "lines" in e]
        self.assertEqual(line_warns, [])

    def test_whitespace_only_body_passes_line_check(self) -> None:
        """A whitespace-only body counts as 0 lines and passes."""
        body = "   \n  \n  "
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        line_pass = [p for p in passes if "lines" in p]
        self.assertEqual(len(line_pass), 1)
        self.assertIn("0 lines", line_pass[0])
        line_warns = [e for e in errors if "lines" in e]
        self.assertEqual(line_warns, [])

    def test_body_with_single_level_refs_passes(self) -> None:
        """A body with references to files that contain no further refs passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_file = os.path.join(tmpdir, "references", "guide.md")
            write_text(ref_file, "# Guide\n\nSome content without references.\n")
            body = "# Skill\n\nSee [guide](references/guide.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        ref_pass = [p for p in passes if "one level deep" in p]
        self.assertEqual(len(ref_pass), 1)
        nested_warns = [e for e in errors if "nested" in e.lower()]
        self.assertEqual(nested_warns, [])

    def test_body_with_nested_refs_returns_warn(self) -> None:
        """A body with nested references (ref file contains refs) produces a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            # Create a reference file that itself contains a reference
            write_text(
                os.path.join(ref_dir, "guide.md"),
                "# Guide\n\nSee [details](references/details.md) for more.\n",
            )
            write_text(os.path.join(ref_dir, "details.md"), "# Details\n")
            body = "# Skill\n\nSee [guide](references/guide.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(len(nested_warns), 1)

    def test_allow_nested_refs_skips_check(self) -> None:
        """With allow_nested_refs=True, nested reference check is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            write_text(
                os.path.join(ref_dir, "guide.md"),
                "# Guide\n\nSee [details](references/details.md) for more.\n",
            )
            write_text(os.path.join(ref_dir, "details.md"), "# Details\n")
            body = "# Skill\n\nSee [guide](references/guide.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, allow_nested_refs=True)
        nested_warns = [e for e in errors if "nested" in e.lower()]
        self.assertEqual(nested_warns, [])
        skip_pass = [p for p in passes if "skipped" in p]
        self.assertEqual(len(skip_pass), 1)

    def test_broken_ref_detected_with_allow_nested_refs(self) -> None:
        """Broken references are detected even when allow_nested_refs=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [guide](references/missing.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, allow_nested_refs=True)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken_warns = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken_warns), 1)
        self.assertIn("references/missing.md", broken_warns[0])
        self.assertIn("SKILL.md", broken_warns[0])
        # No FAIL errors for broken refs
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        # No "skipped" pass when a broken ref exists
        skip_pass = [p for p in passes if "skipped" in p]
        self.assertEqual(skip_pass, [])

    def test_template_placeholders_excluded_from_ref_checks(self) -> None:
        """Template placeholders with < > are excluded from reference checks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = (
                "# Skill\n\n"
                "See [file](references/<file>.md) for details.\n"
                "Also `references/<other>.md` is useful.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        # No nested ref warnings since template placeholders are excluded
        nested_warns = [e for e in errors if "nested" in e.lower()]
        self.assertEqual(nested_warns, [])

    def test_backtick_refs_detected(self) -> None:
        """Backtick-style references are also checked for nesting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            write_text(
                os.path.join(ref_dir, "guide.md"),
                "# Guide\n\nSee `references/nested.md` for more.\n",
            )
            write_text(os.path.join(ref_dir, "nested.md"), "# Nested\n")
            body = '# Skill\n\nSee `references/guide.md` for details.\n'
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(len(nested_warns), 1)

    def test_nonexistent_ref_file_returns_warn(self) -> None:
        """A reference to a nonexistent file produces a WARN error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [guide](references/missing.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken_warns = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken_warns), 1)
        self.assertIn("references/missing.md", broken_warns[0])
        self.assertIn("SKILL.md", broken_warns[0])
        # No FAIL errors for broken refs
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        # No "one level deep" pass when a broken ref exists
        ref_passes = [p for p in passes if "one level deep" in p]
        self.assertEqual(ref_passes, [])

    def test_multiple_broken_refs_each_reported(self) -> None:
        """Multiple broken references each produce a separate WARN error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = (
                "# Skill\n\n"
                "See [guide](references/missing-a.md) for details.\n"
                "Also see [other](references/missing-b.md) for more.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken_warns = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken_warns), 2)
        warn_text = " ".join(broken_warns)
        self.assertIn("missing-a.md", warn_text)
        self.assertIn("missing-b.md", warn_text)
        # No FAIL errors for broken refs
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        ref_passes = [p for p in passes if "one level deep" in p]
        self.assertEqual(ref_passes, [])

    def test_broken_and_valid_refs_mixed(self) -> None:
        """A mix of broken and valid refs reports WARN only for the broken one."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            write_text(
                os.path.join(ref_dir, "valid.md"),
                "# Valid\n\nNo nested references here.\n",
            )
            body = (
                "# Skill\n\n"
                "See [valid](references/valid.md) for details.\n"
                "Also see [missing](references/missing.md) for more.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken_warns = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken_warns), 1)
        self.assertIn("references/missing.md", broken_warns[0])
        self.assertIn("SKILL.md", broken_warns[0])
        # No FAIL errors for broken refs
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        # No "one level deep" pass because a broken ref exists
        ref_passes = [p for p in passes if "one level deep" in p]
        self.assertEqual(ref_passes, [])

    def test_broken_and_nested_refs_both_reported(self) -> None:
        """Both broken refs and nested refs are reported when both exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            # Create a reference file that itself contains a nested reference
            write_text(
                os.path.join(ref_dir, "nesting.md"),
                "# Nesting\n\nSee [deep](references/deep.md) for more.\n",
            )
            write_text(os.path.join(ref_dir, "deep.md"), "# Deep\n")
            body = (
                "# Skill\n\n"
                "See [nesting](references/nesting.md) for details.\n"
                "Also see [gone](references/gone.md) for more.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken_warns = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken_warns), 1)
        self.assertIn("references/gone.md", broken_warns[0])
        self.assertIn("SKILL.md", broken_warns[0])
        nested_warns = [e for e in warn_errors if "nested references" in e]
        self.assertEqual(len(nested_warns), 1)
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        ref_passes = [p for p in passes if "one level deep" in p]
        self.assertEqual(ref_passes, [])

    def test_ref_with_fragment_to_existing_file_no_warn(self) -> None:
        """References with URL fragments to existing files don't trigger false WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            # Create the referenced file
            write_text(
                os.path.join(ref_dir, "guide.md"),
                "# Guide\n\nSome content here.\n",
            )
            # Reference with fragment
            body = "# Skill\n\nSee [guide](references/guide.md#section) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        # Should NOT warn about "does not exist"
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken_warns = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(broken_warns, [])
        # Should get "one level deep" pass since file exists and has no nested refs
        ref_passes = [p for p in passes if "one level deep" in p]
        self.assertEqual(len(ref_passes), 1)

    def test_body_with_no_refs_produces_no_ref_pass(self) -> None:
        """A body with no references produces no reference-related pass."""
        body = "# Skill\n\nJust plain content, no refs.\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        ref_passes = [p for p in passes if "reference" in p.lower()]
        self.assertEqual(ref_passes, [])
        nested_warns = [e for e in errors if "nested" in e.lower()]
        self.assertEqual(nested_warns, [])

    def test_directory_reference_returns_warn(self) -> None:
        """A reference pointing to a directory produces a WARN, not a crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            # Create a subdirectory at the referenced path
            os.makedirs(os.path.join(tmpdir, "references", "subdir"))
            body = "# Skill\n\nSee [refs](references/subdir) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        non_file_warns = [e for e in warn_errors if "non-file" in e]
        self.assertEqual(len(non_file_warns), 1)
        self.assertIn("references/subdir", non_file_warns[0])
        self.assertIn("SKILL.md", non_file_warns[0])
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_path_traversal_returns_warn(self) -> None:
        """A reference escaping the skill directory produces a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [escape](references/../../somewhere) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        escape_warns = [e for e in warn_errors if "escapes skill directory" in e]
        self.assertEqual(len(escape_warns), 1)
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_markdown_link_title_handled(self) -> None:
        """A markdown link with a title suffix resolves correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            write_text(
                os.path.join(ref_dir, "foo.md"),
                "# Foo\n\nSome content.\n",
            )
            # The regex captures the full (path "title") as the ref
            body = '# Skill\n\nSee [foo](references/foo.md "Title") for details.\n'
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        # Should NOT warn about "does not exist" — strip_fragment handles the title
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken_warns = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(broken_warns, [])

    @unittest.skipIf(os.name == "nt", "Permission-denied behavior is not reliable on Windows")
    def test_unreadable_ref_file_returns_warn(self) -> None:
        """A reference to an unreadable file produces a WARN, not a crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            ref_file = os.path.join(ref_dir, "locked.md")
            write_text(ref_file, "# Locked\n")
            # Remove read permission (POSIX only)
            os.chmod(ref_file, 0o000)
            body = "# Skill\n\nSee [locked](references/locked.md) for details.\n"
            write_text(skill_md, body)
            try:
                errors, passes = validate_body(body, skill_md)
            finally:
                # Restore permissions for cleanup
                os.chmod(ref_file, 0o644)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        read_warns = [e for e in warn_errors if "cannot be read" in e]
        self.assertEqual(len(read_warns), 1)
        self.assertIn("references/locked.md", read_warns[0])
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_path_traversal_via_references_dotdot_returns_warn(self) -> None:
        """A reference using references/../.. to escape the skill dir produces a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [escape](references/../../../etc/passwd) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        escape_warns = [e for e in warn_errors if "escapes skill directory" in e]
        self.assertEqual(len(escape_warns), 1)

    def test_directory_ref_with_allow_nested_refs_returns_warn(self) -> None:
        """Directory references are caught even with allow_nested_refs=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            os.makedirs(os.path.join(tmpdir, "references", "subdir"))
            body = "# Skill\n\nSee [refs](references/subdir) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, allow_nested_refs=True)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        non_file_warns = [e for e in warn_errors if "non-file" in e]
        self.assertEqual(len(non_file_warns), 1)


# ===================================================================
# validate_directories
# ===================================================================


class ValidateDirectoriesTests(unittest.TestCase):
    """Tests for the validate_directories function."""

    def test_all_recognized_directories_pass(self) -> None:
        """A skill with all 5 recognized directories produces no warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for d in sorted(RECOGNIZED_DIRS):
                os.makedirs(os.path.join(tmpdir, d))
            warnings, passes = validate_directories(tmpdir)
        self.assertEqual(warnings, [])
        dir_pass = [p for p in passes if "recognized" in p]
        self.assertEqual(len(dir_pass), 1)

    def test_non_standard_directory_returns_info(self) -> None:
        """A non-standard directory produces an INFO warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "custom-dir"))
            warnings, passes = validate_directories(tmpdir)
        self.assertEqual(len(warnings), 1)
        self.assertIn(LEVEL_INFO, warnings[0])
        self.assertIn("custom-dir", warnings[0])
        # Should list recognized dirs
        for d in sorted(RECOGNIZED_DIRS):
            self.assertIn(d, warnings[0])

    def test_empty_directory_passes(self) -> None:
        """A skill directory with no subdirectories passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Only files, no subdirectories
            write_text(os.path.join(tmpdir, "SKILL.md"), "# Skill\n")
            warnings, passes = validate_directories(tmpdir)
        self.assertEqual(warnings, [])
        dir_pass = [p for p in passes if "recognized" in p]
        self.assertEqual(len(dir_pass), 1)

    def test_capabilities_directory_is_recognized(self) -> None:
        """The capabilities directory is recognized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "capabilities"))
            warnings, passes = validate_directories(tmpdir)
        self.assertEqual(warnings, [])

    def test_multiple_non_standard_directories(self) -> None:
        """Multiple non-standard directories each produce a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "foo"))
            os.makedirs(os.path.join(tmpdir, "bar"))
            warnings, passes = validate_directories(tmpdir)
        self.assertEqual(len(warnings), 2)
        warning_text = " ".join(warnings)
        self.assertIn("foo", warning_text)
        self.assertIn("bar", warning_text)


# ===================================================================
# validate_skill (regular skills)
# ===================================================================


class ValidateSkillTests(unittest.TestCase):
    """Tests for validate_skill with regular (non-capability) skills."""

    def test_valid_skill_passes(self) -> None:
        """A valid skill with all required fields produces no FAIL errors.

        A valid skill should produce passes for at least: name length,
        name format, name matches directory, description length,
        description voice, body line count, and directory check.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        # Expect 7 passes: name chars, name format, name matches dir,
        # description chars, description voice, body lines, directories
        self.assertGreaterEqual(len(passes), 7, msg=f"passes={passes}")

    def test_missing_skill_md_returns_fail(self) -> None:
        """A skill directory without SKILL.md produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            os.makedirs(skill_dir)
            errors, passes = validate_skill(skill_dir)
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_FAIL, errors[0])
        self.assertIn("SKILL.md", errors[0])

    def test_missing_frontmatter_returns_fail(self) -> None:
        """A SKILL.md without frontmatter produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "# Demo Skill\n\nNo frontmatter here.\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(len(fail_errors), 1)
        self.assertIn("frontmatter", fail_errors[0])

    def test_yaml_parse_error_returns_fail(self) -> None:
        """A SKILL.md with unclosed frontmatter delimiter produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            # Missing closing --- triggers a parse error
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        parse_errors = [e for e in fail_errors if "parse error" in e.lower() or "YAML" in e]
        self.assertGreaterEqual(len(parse_errors), 1)

    def test_missing_name_field_returns_fail(self) -> None:
        """A SKILL.md without a name field produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\ndescription: Validates data files.\n---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        name_errors = [e for e in fail_errors if "name" in e.lower()]
        self.assertGreaterEqual(len(name_errors), 1)

    def test_missing_description_field_returns_fail(self) -> None:
        """A SKILL.md without a description field produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        desc_errors = [e for e in fail_errors if "description" in e.lower()]
        self.assertGreaterEqual(len(desc_errors), 1)

    def test_invalid_name_returns_fail(self) -> None:
        """A SKILL.md with an invalid name (uppercase) produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "Demo-Skill")
            write_skill_md(skill_dir, name="Demo-Skill")
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertGreater(len(fail_errors), 0)

    def test_invalid_description_returns_warn(self) -> None:
        """A SKILL.md with an imperative description produces a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(
                skill_dir,
                description="Process data files and generate reports.",
            )
            errors, passes = validate_skill(skill_dir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        imperative_warns = [e for e in warn_errors if "imperative" in e]
        self.assertGreaterEqual(len(imperative_warns), 1)

    def test_compatibility_exceeding_limit_returns_fail(self) -> None:
        """A compatibility field exceeding MAX_COMPATIBILITY_CHARS produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            long_compat = "x" * (MAX_COMPATIBILITY_CHARS + 1)
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                f"---\nname: demo-skill\n"
                f"description: Validates data files and generates reports.\n"
                f"compatibility: {long_compat}\n"
                f"---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        compat_errors = [e for e in fail_errors if "compatibility" in e.lower()]
        self.assertEqual(len(compat_errors), 1)
        self.assertIn(str(MAX_COMPATIBILITY_CHARS), compat_errors[0])

    def test_valid_compatibility_field_passes(self) -> None:
        """A valid compatibility field produces a pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "compatibility: Requires Python 3.12 or later.\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        compat_pass = [p for p in passes if "compatibility" in p]
        self.assertEqual(len(compat_pass), 1)

    def test_compatibility_at_exactly_max_chars_passes(self) -> None:
        """A compatibility field at exactly MAX_COMPATIBILITY_CHARS passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            exact_compat = "a" * MAX_COMPATIBILITY_CHARS
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                f"---\nname: demo-skill\n"
                f"description: Validates data files and generates reports.\n"
                f"compatibility: {exact_compat}\n"
                f"---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        compat_fails = [e for e in fail_errors if "compatibility" in e.lower()]
        self.assertEqual(compat_fails, [])
        compat_pass = [p for p in passes if "compatibility" in p]
        self.assertEqual(len(compat_pass), 1)
        self.assertIn(str(MAX_COMPATIBILITY_CHARS), compat_pass[0])

    def test_empty_frontmatter_returns_missing_fields(self) -> None:
        """A SKILL.md with empty frontmatter (---\\n---) fails on missing fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\n---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        name_errors = [e for e in fail_errors if "name" in e.lower()]
        desc_errors = [e for e in fail_errors if "description" in e.lower()]
        self.assertGreaterEqual(len(name_errors), 1)
        self.assertGreaterEqual(len(desc_errors), 1)

    def test_non_standard_directory_returns_info(self) -> None:
        """A skill with a non-standard directory produces an INFO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            os.makedirs(os.path.join(skill_dir, "custom-stuff"))
            errors, passes = validate_skill(skill_dir)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertGreaterEqual(len(info_errors), 1)
        self.assertIn("custom-stuff", info_errors[0])

    def test_name_directory_mismatch_returns_fail(self) -> None:
        """A name that does not match the directory name produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "actual-dir")
            write_skill_md(skill_dir, name="different-name")
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        mismatch_errors = [e for e in fail_errors if "match" in e.lower()]
        self.assertGreaterEqual(len(mismatch_errors), 1)


# ===================================================================
# validate_skill (capabilities)
# ===================================================================


class ValidateCapabilityTests(unittest.TestCase):
    """Tests for validate_skill with is_capability=True."""

    def test_valid_capability_passes(self) -> None:
        """A valid capability with capability.md passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            errors, passes = validate_skill(cap_dir, is_capability=True)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_capability_without_frontmatter_passes(self) -> None:
        """A capability without frontmatter passes (not required)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n\nSome content.\n")
            errors, passes = validate_skill(cap_dir, is_capability=True)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_capability_with_name_in_frontmatter_returns_info(self) -> None:
        """A capability with name in frontmatter produces an INFO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(
                cap_dir,
                frontmatter="name: my-cap",
                body="# My Capability\n",
            )
            errors, passes = validate_skill(cap_dir, is_capability=True)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        name_infos = [e for e in info_errors if "name" in e.lower()]
        self.assertGreaterEqual(len(name_infos), 1)
        self.assertIn("discovery", name_infos[0].lower())

    def test_missing_capability_md_returns_fail(self) -> None:
        """A capability directory without capability.md produces a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            os.makedirs(cap_dir)
            errors, passes = validate_skill(cap_dir, is_capability=True)
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_FAIL, errors[0])
        self.assertIn("capability.md", errors[0])

    def test_capability_with_frontmatter_and_description(self) -> None:
        """A capability with frontmatter (no name) passes without INFO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(
                cap_dir,
                frontmatter="description: Handles gate checks.",
                body="# My Capability\n",
            )
            errors, passes = validate_skill(cap_dir, is_capability=True)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        # No INFO about name since there is no name field
        name_infos = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "name" in e.lower()
        ]
        self.assertEqual(name_infos, [])


# ===================================================================
# main() CLI
# ===================================================================


class MainCLITests(unittest.TestCase):
    """Tests for the main() CLI entry point via subprocess."""

    def test_valid_skill_exits_zero(self) -> None:
        """A valid skill exits with code 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            proc = _run([skill_dir], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("passed", proc.stdout.lower())

    def test_invalid_skill_exits_one(self) -> None:
        """A skill with FAIL errors exits with code 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            os.makedirs(skill_dir)
            # No SKILL.md — should fail
            proc = _run([skill_dir], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)

    def test_broken_reference_exits_zero(self) -> None:
        """A skill with a broken reference exits with code 0 (WARN only)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(
                skill_dir,
                body="# Skill\n\nSee [guide](references/missing.md) for details.",
            )
            proc = _run([skill_dir], cwd=REPO_ROOT)
        # Broken refs are WARN, not FAIL — should exit 0
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("does not exist", proc.stdout)

    def test_verbose_flag_prints_passes(self) -> None:
        """The --verbose flag causes passes to be printed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            proc = _run([skill_dir, "--verbose"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        # Verbose output should include check marks for passes
        self.assertIn("\u2713", proc.stdout)
        # Should mention number of checks
        self.assertIn("checks", proc.stdout.lower())

    def test_capability_flag_validates_as_capability(self) -> None:
        """The --capability flag validates using capability.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            proc = _run([cap_dir, "--capability"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("capability", proc.stdout.lower())

    def test_allow_nested_references_flag(self) -> None:
        """The --allow-nested-references flag allows nested refs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            ref_dir = os.path.join(skill_dir, "references")
            write_text(
                os.path.join(ref_dir, "guide.md"),
                "# Guide\n\nSee [details](references/details.md) for more.\n",
            )
            write_text(os.path.join(ref_dir, "details.md"), "# Details\n")
            write_skill_md(
                skill_dir,
                body="# Skill\n\nSee [guide](references/guide.md) for details.",
            )
            proc = _run(
                [skill_dir, "--allow-nested-references"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

    def test_no_arguments_prints_usage_and_exits_one(self) -> None:
        """Running without arguments prints usage and exits with code 1."""
        proc = _run([], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Usage:", proc.stdout)

    def test_non_directory_path_prints_error_and_exits_one(self) -> None:
        """A non-directory path prints an error and exits with code 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "not-a-dir.txt")
            write_text(file_path, "content")
            proc = _run([file_path], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not a directory", proc.stdout.lower())

    def test_warns_only_exits_zero(self) -> None:
        """A skill with only WARN errors (no FAIL) exits with code 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            # Imperative description triggers WARN, not FAIL
            write_skill_md(
                skill_dir,
                description="Process data files and generate reports.",
            )
            proc = _run([skill_dir], cwd=REPO_ROOT)
        # WARN-only should exit 0 (only FAIL causes exit 1)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

    def test_type_label_for_registered_skill(self) -> None:
        """Output shows 'registered skill' type for non-capability."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            proc = _run([skill_dir], cwd=REPO_ROOT)
        self.assertIn("registered skill", proc.stdout)

    def test_type_label_for_capability(self) -> None:
        """Output shows 'capability' type for --capability flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            proc = _run([cap_dir, "--capability"], cwd=REPO_ROOT)
        self.assertIn("capability", proc.stdout)

    def test_verbose_with_warnings_prints_passes_and_errors(self) -> None:
        """--verbose with warnings still prints both passes and error lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            # Imperative description triggers WARN but not FAIL
            write_skill_md(
                skill_dir,
                description="Process data files and generate reports.",
            )
            proc = _run([skill_dir, "--verbose"], cwd=REPO_ROOT)
        # Should exit 0 (WARN only)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        # Verbose output includes pass marks
        self.assertIn("\u2713", proc.stdout)
        # Should include the warning symbol
        self.assertIn("\u26a0", proc.stdout)
        # Should include summary line
        self.assertIn("Results:", proc.stdout)
        self.assertIn("warnings", proc.stdout.lower())

    def test_verbose_with_fails_prints_passes_and_errors(self) -> None:
        """--verbose with FAIL errors prints both passes and error lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            # Missing description triggers FAIL
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n---\n\n# Skill\n",
            )
            proc = _run([skill_dir, "--verbose"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        # Should have the fail symbol
        self.assertIn("\u2717", proc.stdout)
        # Summary should mention failures
        self.assertIn("Results:", proc.stdout)
        self.assertIn("failure", proc.stdout.lower())

    def test_nonexistent_path_prints_error_and_exits_one(self) -> None:
        """A nonexistent path prints an error and exits with code 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gone = os.path.join(tmpdir, "does-not-exist")
        # tmpdir is now deleted, so gone definitely does not exist
        proc = _run([gone], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not a directory", proc.stdout.lower())

    def test_capability_verbose_flag_combination(self) -> None:
        """--capability --verbose works together correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            proc = _run([cap_dir, "--capability", "--verbose"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("capability", proc.stdout.lower())
        self.assertIn("\u2713", proc.stdout)
        self.assertIn("checks", proc.stdout.lower())

    def test_capability_allow_nested_refs_combination(self) -> None:
        """--capability --allow-nested-references works together."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            ref_dir = os.path.join(cap_dir, "references")
            write_text(
                os.path.join(ref_dir, "guide.md"),
                "# Guide\n\nSee [details](references/details.md) for more.\n",
            )
            write_text(os.path.join(ref_dir, "details.md"), "# Details\n")
            _write_capability_md(
                cap_dir,
                body="# Cap\n\nSee [guide](references/guide.md) for details.\n",
            )
            proc = _run(
                [cap_dir, "--capability", "--allow-nested-references"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
