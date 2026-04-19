"""Tests for validate_skill.py.

Covers validate_description, validate_body, validate_directories,
validate_skill, optional frontmatter field validation, and the
main() CLI entry point.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from helpers import write_text, write_skill_md

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, "validate_skill.py")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from validate_skill import (
    _build_parser,
    find_skill_root,
    validate_body,
    validate_description,
    validate_directories,
    validate_skill,
    validate_skill_references,
)
from lib.constants import collect_foundry_config_findings
from lib.validation import (
    validate_allowed_tools,
    validate_metadata,
    validate_license,
    validate_known_keys,
)
from lib.constants import (
    KNOWN_FRONTMATTER_KEYS,
    KNOWN_SPDX_LICENSES,
    KNOWN_TOOLS,
    LEVEL_FAIL,
    LEVEL_INFO,
    LEVEL_WARN,
    MAX_ALLOWED_TOOLS,
    MAX_AUTHOR_LENGTH,
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
        """A description containing XML tags produces a WARN (platform: Anthropic)."""
        desc = "Provides <tool>data</tool> processing capabilities."
        errors, passes = validate_description(desc)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        xml_warns = [e for e in warn_errors if "XML" in e]
        self.assertEqual(len(xml_warns), 1)
        self.assertIn("platform: Anthropic", xml_warns[0])

    def test_description_with_first_person_returns_info(self) -> None:
        """A description using first person (I can, I will, etc.) produces an INFO (foundry)."""
        desc = "I can process data files and generate reports."
        errors, passes = validate_description(desc)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        first_person_infos = [e for e in info_errors if "first person" in e]
        self.assertEqual(len(first_person_infos), 1)
        self.assertIn("[foundry]", first_person_infos[0])

    def test_description_with_first_person_plural_returns_info(self) -> None:
        """A description using first-person plural (we, our) produces an INFO (foundry)."""
        desc = "We can help with data processing tasks."
        errors, passes = validate_description(desc)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        plural_infos = [e for e in info_errors if "first-person plural" in e]
        self.assertEqual(len(plural_infos), 1)
        self.assertIn("[foundry]", plural_infos[0])

    def test_description_with_second_person_returns_info(self) -> None:
        """A description using second person (you, your) produces an INFO (foundry)."""
        desc = "You can use this to process your data files."
        errors, passes = validate_description(desc)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        second_person_infos = [e for e in info_errors if "second person" in e]
        self.assertEqual(len(second_person_infos), 1)
        self.assertIn("[foundry]", second_person_infos[0])

    def test_description_with_imperative_start_returns_info(self) -> None:
        """A description starting with an imperative verb produces an INFO (foundry)."""
        desc = "Process data files and generate summary reports."
        errors, passes = validate_description(desc)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        imperative_infos = [e for e in info_errors if "imperative" in e]
        self.assertEqual(len(imperative_infos), 1)
        self.assertIn("[foundry]", imperative_infos[0])

    def test_imperative_multi_word_set_up_returns_info(self) -> None:
        """The multi-word imperative verb 'Set up' is detected."""
        desc = "Set up CI pipelines for containerized deployments."
        errors, passes = validate_description(desc)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        imperative_infos = [e for e in info_errors if "imperative" in e]
        self.assertEqual(len(imperative_infos), 1)

    def test_imperative_verbs_representative_sample(self) -> None:
        """A representative sample of imperative verbs are all detected."""
        verbs = [
            "Create", "Build", "Deploy", "Execute", "Generate",
            "Scaffold", "Orchestrate", "Audit", "Migrate", "Provision",
        ]
        for verb in verbs:
            desc = f"{verb} robust infrastructure for the project."
            errors, passes = validate_description(desc)
            imperative_infos = [
                e for e in errors
                if e.startswith(LEVEL_INFO) and "imperative" in e
            ]
            with self.subTest(verb=verb):
                self.assertEqual(
                    len(imperative_infos), 1,
                    f"Expected imperative INFO for verb '{verb}', "
                    f"got errors={errors}, passes={passes}",
                )

    def test_imperative_detection_is_case_insensitive(self) -> None:
        """Imperative detection works regardless of case."""
        for desc in [
            "create robust infrastructure for the project.",
            "CREATE robust infrastructure for the project.",
        ]:
            errors, passes = validate_description(desc)
            imperative_infos = [
                e for e in errors
                if e.startswith(LEVEL_INFO) and "imperative" in e
            ]
            with self.subTest(desc=desc):
                self.assertEqual(len(imperative_infos), 1)

    def test_first_person_all_variants_detected(self) -> None:
        """All first-person singular variants (I can, I will, I help, I am) are detected."""
        phrases = ["I can do it.", "I will help.", "I help teams.", "I am a tool."]
        for phrase in phrases:
            desc = f"Sometimes {phrase}"
            errors, passes = validate_description(desc)
            first_infos = [
                e for e in errors
                if e.startswith(LEVEL_INFO) and "first person" in e
            ]
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    len(first_infos), 1,
                    f"Expected first-person INFO for '{phrase}', got errors={errors}",
                )

    def test_voice_cascade_first_person_takes_priority(self) -> None:
        """When both first-person and second-person are present, only first-person fires."""
        desc = "I can help you manage your data files effectively."
        errors, passes = validate_description(desc)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        first_infos = [e for e in info_errors if "first person" in e]
        second_infos = [e for e in info_errors if "second person" in e]
        # Only first-person should fire due to elif chain
        self.assertEqual(len(first_infos), 1)
        self.assertEqual(len(second_infos), 0)

    def test_voice_cascade_first_plural_before_second(self) -> None:
        """When first-person plural and second-person are present, only plural fires."""
        desc = "We can help you manage your data files effectively."
        errors, passes = validate_description(desc)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        plural_infos = [e for e in info_errors if "first-person plural" in e]
        second_infos = [e for e in info_errors if "second person" in e]
        self.assertEqual(len(plural_infos), 1)
        self.assertEqual(len(second_infos), 0)

    def test_description_third_person_no_voice_warnings(self) -> None:
        """A proper third-person description produces no voice warnings."""
        desc = "Manages project timelines and tracks milestones."
        errors, passes = validate_description(desc)
        voice_msgs = [
            e for e in errors
            if "person" in e or "imperative" in e
        ]
        self.assertEqual(voice_msgs, [])
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        line_warns = [e for e in warn_errors if "lines" in e]
        self.assertEqual(len(line_warns), 1)

    def test_empty_body_passes_line_check(self) -> None:
        """An empty body (0 lines) passes the line count check."""
        body = ""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md), allow_nested_refs=True)
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md), allow_nested_refs=True)
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

    def test_nested_ref_check_ignores_fenced_code_blocks(self) -> None:
        """Nested-reference detection strips fenced code blocks from the
        referenced file so example links inside ``` don't trigger a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            # Reference file has a link only inside a fenced code block
            write_text(
                os.path.join(ref_dir, "guide.md"),
                "# Guide\n\n"
                "```markdown\n"
                "See [example](references/example.md) for details.\n"
                "```\n",
            )
            body = "# Skill\n\nSee [guide](references/guide.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(nested_warns, [])

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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(len(nested_warns), 1)

    def test_nonexistent_ref_file_returns_warn(self) -> None:
        """A reference to a nonexistent file produces a WARN error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [guide](references/missing.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        # Should NOT warn about "does not exist"
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken_warns = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(broken_warns, [])
        # Should get "one level deep" pass since file exists and has no nested refs
        ref_passes = [p for p in passes if "one level deep" in p]
        self.assertEqual(len(ref_passes), 1)

    def test_duplicate_fragment_refs_to_existing_file_checked_once(self) -> None:
        """Multiple fragment refs to the same file produce a single nested-ref check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            # Create a file that contains nested references
            write_text(
                os.path.join(ref_dir, "guide.md"),
                "# Guide\n\nSee [deep](references/deep.md) for more.\n",
            )
            write_text(os.path.join(ref_dir, "deep.md"), "# Deep\n")
            # Two links to the same file with different fragments
            body = (
                "# Skill\n\n"
                "See [intro](references/guide.md#intro) for details.\n"
                "See [setup](references/guide.md#setup) for more.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        # Should produce exactly one nested-ref WARN, not two
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(len(nested_warns), 1)

    def test_duplicate_fragment_refs_to_missing_file_warned_once(self) -> None:
        """Multiple fragment refs to the same missing file produce a single WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            # Two links to the same missing file with different fragments
            body = (
                "# Skill\n\n"
                "See [intro](references/missing.md#intro) for details.\n"
                "See [setup](references/missing.md#setup) for more.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        # Should produce exactly one "does not exist" WARN, not two
        broken_warns = [e for e in errors if "does not exist" in e]
        self.assertEqual(len(broken_warns), 1)
        self.assertIn("references/missing.md", broken_warns[0])

    def test_body_with_no_refs_produces_no_ref_pass(self) -> None:
        """A body with no references produces no reference-related pass."""
        body = "# Skill\n\nJust plain content, no refs.\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        non_file_warns = [e for e in warn_errors if "non-file" in e]
        self.assertEqual(len(non_file_warns), 1)
        self.assertIn("references/subdir", non_file_warns[0])
        self.assertIn("SKILL.md", non_file_warns[0])
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_path_traversal_returns_info(self) -> None:
        """A reference escaping the skill directory produces an INFO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [escape](references/../../somewhere) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        escape_infos = [e for e in info_errors if "outside skill directory" in e]
        self.assertEqual(len(escape_infos), 1)
        self.assertIn("[foundry]", escape_infos[0])
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_all_external_refs_no_misleading_pass(self) -> None:
        """When all refs are external, 'one level deep' pass does not fire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            # Use references/../../ paths so the regex matches but they escape the dir
            body = (
                "# Skill\n\n"
                "See [a](references/../../shared/a.md) and "
                "[b](references/../../shared/b.md) for details.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        # Should NOT have the "one level deep" pass since no internal refs were checked
        nesting_passes = [p for p in passes if "one level deep" in p]
        self.assertEqual(nesting_passes, [])
        # Should have the external-only pass instead
        external_passes = [p for p in passes if "external" in p.lower()]
        self.assertEqual(len(external_passes), 1)
        # External refs skip all filesystem checks (no existence oracle)
        broken_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "does not exist" in e
        ]
        self.assertEqual(broken_warns, [])

    def test_external_ref_skips_filesystem_checks(self) -> None:
        """External refs skip all filesystem checks to avoid existence oracle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            # External ref to a nonexistent path — should NOT produce
            # any broken-ref warning (no filesystem oracle)
            body = (
                "# Skill\n\n"
                "See [a](references/../../shared/a.md) for details.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        # Should have the INFO for external ref
        info_errors = [e for e in errors if "outside skill directory" in e]
        self.assertEqual(len(info_errors), 1)
        # Should NOT have any broken-ref warning
        broken_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "does not exist" in e
        ]
        self.assertEqual(broken_warns, [])

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
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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

            # Guard: Skip if file is still readable (e.g., running as root)
            try:
                with open(ref_file, "r", encoding="utf-8") as f:
                    f.read()
                self.skipTest("File remains readable after chmod (running as root?)")
            except PermissionError:
                pass  # Expected, continue with test

            body = "# Skill\n\nSee [locked](references/locked.md) for details.\n"
            write_text(skill_md, body)
            try:
                errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
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

    @unittest.skipIf(os.name == "nt", "Permission-denied behavior is not reliable on Windows")
    def test_unreadable_ref_file_with_allow_nested_refs_returns_warn(self) -> None:
        """Unreadable files are caught even with allow_nested_refs=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            ref_file = os.path.join(ref_dir, "locked.md")
            write_text(ref_file, "# Locked\n")
            os.chmod(ref_file, 0o000)

            # Guard: Skip if file is still readable (e.g., running as root)
            try:
                with open(ref_file, "r", encoding="utf-8") as f:
                    f.read()
                self.skipTest("File remains readable after chmod (running as root?)")
            except PermissionError:
                pass  # Expected, continue with test

            body = "# Skill\n\nSee [locked](references/locked.md) for details.\n"
            write_text(skill_md, body)
            try:
                errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md), allow_nested_refs=True)
            finally:
                os.chmod(ref_file, 0o644)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        read_warns = [e for e in warn_errors if "cannot be read" in e]
        self.assertEqual(len(read_warns), 1)
        self.assertIn("references/locked.md", read_warns[0])
        # No "skipped" pass when ref is unreadable
        skip_passes = [p for p in passes if "skipped" in p]
        self.assertEqual(skip_passes, [])

    def test_binary_ref_file_returns_warn(self) -> None:
        """A reference to a binary file produces a WARN, not a crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            os.makedirs(ref_dir, exist_ok=True)
            ref_file = os.path.join(ref_dir, "image.png")
            # Write raw bytes that are invalid UTF-8
            with open(ref_file, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\xfd")
            body = "# Skill\n\nSee [image](references/image.png) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        read_warns = [e for e in warn_errors if "cannot be read" in e]
        self.assertEqual(len(read_warns), 1)
        self.assertIn("references/image.png", read_warns[0])
        self.assertIn("UnicodeDecodeError", read_warns[0])
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_non_utf8_ref_file_returns_warn(self) -> None:
        """A reference to a non-UTF8 text file produces a WARN, not a crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            ref_dir = os.path.join(tmpdir, "references")
            os.makedirs(ref_dir, exist_ok=True)
            ref_file = os.path.join(ref_dir, "latin1.md")
            # Write Latin-1 encoded text with bytes invalid in UTF-8
            with open(ref_file, "wb") as f:
                f.write("# Résumé\n\nCafé crème à côté".encode("latin-1"))
            body = "# Skill\n\nSee [latin1](references/latin1.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        read_warns = [e for e in warn_errors if "cannot be read" in e]
        self.assertEqual(len(read_warns), 1)
        self.assertIn("references/latin1.md", read_warns[0])
        self.assertIn("UnicodeDecodeError", read_warns[0])
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_path_traversal_via_references_dotdot_returns_info(self) -> None:
        """A reference using references/../.. to escape the skill dir produces an INFO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [escape](references/../../../etc/passwd) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        escape_infos = [e for e in info_errors if "outside skill directory" in e]
        self.assertEqual(len(escape_infos), 1)

    def test_directory_ref_with_allow_nested_refs_returns_warn(self) -> None:
        """Directory references are caught even with allow_nested_refs=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            os.makedirs(os.path.join(tmpdir, "references", "subdir"))
            body = "# Skill\n\nSee [refs](references/subdir) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md), allow_nested_refs=True)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        non_file_warns = [e for e in warn_errors if "non-file" in e]
        self.assertEqual(len(non_file_warns), 1)


# ===================================================================
# find_skill_root
# ===================================================================


class FindSkillRootTests(unittest.TestCase):
    """Tests for the find_skill_root function."""

    def test_finds_root_one_level_up(self) -> None:
        """Finds SKILL.md one directory above start_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            cap_dir = os.path.join(tmpdir, "capabilities", "my-cap")
            os.makedirs(cap_dir)
            result = find_skill_root(cap_dir)
        self.assertEqual(result, os.path.abspath(tmpdir))

    def test_finds_root_two_levels_up(self) -> None:
        """Finds SKILL.md two directories above start_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            deep_dir = os.path.join(tmpdir, "capabilities", "validation")
            os.makedirs(deep_dir)
            result = find_skill_root(deep_dir)
        self.assertEqual(result, os.path.abspath(tmpdir))

    def test_returns_none_when_no_skill_md(self) -> None:
        """Returns None when no SKILL.md is found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "some", "deep", "path")
            os.makedirs(cap_dir)
            result = find_skill_root(cap_dir)
        self.assertIsNone(result)

    def test_finds_root_at_start_dir(self) -> None:
        """Finds SKILL.md in start_dir itself."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            result = find_skill_root(tmpdir)
        self.assertEqual(result, os.path.abspath(tmpdir))

    def test_ignores_directory_named_skill_md(self) -> None:
        """A directory named SKILL.md is not treated as a valid skill root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "SKILL.md"))
            result = find_skill_root(tmpdir)
        self.assertIsNone(result)


# ===================================================================
# validate_body — skill-root-relative resolution
# ===================================================================


class ValidateBodySkillRootTests(unittest.TestCase):
    """Tests for skill-root-relative reference resolution in validate_body."""

    def test_capability_ref_resolves_from_skill_root(self) -> None:
        """A capability entry referencing references/guide.md resolves from
        the skill root, not the capability directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up skill root with SKILL.md and a reference file
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nContent.\n",
            )
            # Capability lives in a subdirectory
            cap_dir = os.path.join(tmpdir, "capabilities", "validation")
            cap_md = os.path.join(cap_dir, "capability.md")
            body = "# Validation\n\nSee [guide](references/guide.md) for details.\n"
            write_text(cap_md, body)
            # skill_root is the skill root, not the capability dir
            errors, passes = validate_body(body, cap_md, tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])
        ref_pass = [p for p in passes if "one level deep" in p]
        self.assertEqual(len(ref_pass), 1)

    def test_capability_ref_without_skill_root_fails(self) -> None:
        """When skill_root is the capability dir (no SKILL.md found),
        a skill-root-relative reference is reported as broken."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nContent.\n",
            )
            cap_dir = os.path.join(tmpdir, "capabilities", "validation")
            cap_md = os.path.join(cap_dir, "capability.md")
            body = "# Validation\n\nSee [guide](references/guide.md) for details.\n"
            write_text(cap_md, body)
            # Pass cap_dir as skill_root (fallback when no SKILL.md found)
            errors, passes = validate_body(body, cap_md, cap_dir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken), 1)

    def test_parent_traversal_leading_intra_skill_produces_warn(self) -> None:
        """A references/../.. style path that still resolves inside the skill
        root produces a WARN for using parent traversal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            write_text(
                os.path.join(tmpdir, "assets", "template.md"),
                "# Template\n",
            )
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [t](references/../assets/template.md) for info.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        traversal_warns = [e for e in warn_errors if "parent traversal" in e]
        self.assertEqual(len(traversal_warns), 1)

    def test_parent_traversal_midpath_intra_skill_produces_warn(self) -> None:
        """A mid-path ../ in a reference produces WARN even though normpath
        would collapse it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n",
            )
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [guide](references/../references/guide.md) for info.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        traversal_warns = [e for e in warn_errors if "parent traversal" in e]
        self.assertEqual(len(traversal_warns), 1)

    def test_parent_traversal_missing_file_produces_both_warns(self) -> None:
        """A ../ traversal to a missing file produces both the traversal WARN
        and the broken-link WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [t](references/../assets/missing.md) for info.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        traversal_warns = [e for e in warn_errors if "parent traversal" in e]
        self.assertEqual(len(traversal_warns), 1)
        broken_warns = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken_warns), 1)

    def test_reference_file_body_resolves_from_skill_root(self) -> None:
        """When validate_body() is called with a reference file's body and
        the correct skill_root, root-relative links resolve from the skill
        root — the same resolution logic applies regardless of file origin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Skill root with another reference file
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            write_text(
                os.path.join(tmpdir, "references", "other.md"),
                "# Other\n\nContent.\n",
            )
            # A reference file that links to a sibling via root-relative path
            ref_file = os.path.join(tmpdir, "references", "guide.md")
            body = "# Guide\n\nSee also [other](references/other.md).\n"
            write_text(ref_file, body)
            errors, passes = validate_body(body, ref_file, tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])
        ref_pass = [p for p in passes if "one level deep" in p]
        self.assertEqual(len(ref_pass), 1)

    def test_external_parent_traversal_stays_info(self) -> None:
        """A references/../../ reference escaping the skill root produces
        INFO (external), not a parent-traversal WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [shared](references/../../shared/guide.md) for info.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, tmpdir)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        external_infos = [e for e in info_errors if "outside skill directory" in e]
        self.assertEqual(len(external_infos), 1)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        traversal_warns = [e for e in warn_errors if "parent traversal" in e]
        self.assertEqual(traversal_warns, [])


# ===================================================================
# validate_skill — capability skill-root auto-detection
# ===================================================================


class ValidateSkillCapabilityRootTests(unittest.TestCase):
    """Tests for validate_skill with is_capability=True auto-detecting the root."""

    def test_capability_auto_detects_skill_root(self) -> None:
        """validate_skill with is_capability=True walks up to find SKILL.md
        and resolves references from that root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Skill root
            write_skill_md(tmpdir, body="# Router Skill\n")
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nContent.\n",
            )
            # Capability references a file at the skill root
            cap_dir = os.path.join(tmpdir, "capabilities", "validation")
            body = "# Validation\n\nSee [guide](references/guide.md) for details.\n"
            write_text(os.path.join(cap_dir, "capability.md"), body)
            errors, passes = validate_skill(cap_dir, is_capability=True)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(broken, [])

    def test_capability_mode_scans_entire_skill_tree(self) -> None:
        """In --capability mode, skill-wide scanning walks the skill root,
        not just the capability subtree, catching broken refs elsewhere."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir, body="# Router Skill\n")
            # Broken ref in a reference file at the skill root (outside capability dir)
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nSee [missing](references/missing.md).\n",
            )
            cap_dir = os.path.join(tmpdir, "capabilities", "validation")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Validation\n\nSome content.\n",
            )
            errors, passes = validate_skill(cap_dir, is_capability=True)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken), 1)
        self.assertIn("references/missing.md", broken[0])


# ===================================================================
# validate_skill_references
# ===================================================================


class ValidateSkillReferencesTests(unittest.TestCase):
    """Tests for validate_skill_references — skill-wide .md file scanning."""

    def test_valid_refs_in_reference_file_passes(self) -> None:
        """A reference file with valid root-relative links produces no warns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, "---\nname: test\n---\n# Skill\n")
            write_text(
                os.path.join(tmpdir, "references", "other.md"),
                "# Other\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nSee also [other](references/other.md).\n",
            )
            errors, passes = validate_skill_references(
                tmpdir, tmpdir, skill_md,
            )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])
        summary = [p for p in passes if "skill-wide references" in p]
        self.assertEqual(len(summary), 1)

    def test_broken_ref_in_reference_file_returns_warn(self) -> None:
        """A reference file linking to a nonexistent file produces a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, "---\nname: test\n---\n# Skill\n")
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nSee [missing](references/missing.md).\n",
            )
            errors, passes = validate_skill_references(
                tmpdir, tmpdir, skill_md,
            )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken), 1)
        self.assertIn("references/missing.md", broken[0])

    def test_parent_traversal_in_reference_file_returns_warn(self) -> None:
        """A reference file using ../ produces a parent-traversal WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, "---\nname: test\n---\n# Skill\n")
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nSee [t](references/../assets/other.md).\n",
            )
            write_text(
                os.path.join(tmpdir, "assets", "other.md"),
                "# Other\n",
            )
            errors, passes = validate_skill_references(
                tmpdir, tmpdir, skill_md,
            )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        traversal = [e for e in warn_errors if "parent traversal" in e]
        self.assertEqual(len(traversal), 1)

    def test_skips_entry_file(self) -> None:
        """The entry file is skipped (already validated by validate_body)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            # Entry file has a broken ref — should NOT appear in results
            write_text(
                skill_md,
                "---\nname: test\n---\n# Skill\n\nSee [x](references/nope.md).\n",
            )
            errors, passes = validate_skill_references(
                tmpdir, tmpdir, skill_md,
            )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])

    def test_no_extra_md_files_produces_no_summary(self) -> None:
        """When the only .md file is the entry file, no summary pass is added."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, "---\nname: test\n---\n# Skill\n")
            errors, passes = validate_skill_references(
                tmpdir, tmpdir, skill_md,
            )
        self.assertEqual(errors, [])
        summary = [p for p in passes if "skill-wide references" in p]
        self.assertEqual(summary, [])

    def test_validate_skill_includes_skill_wide_refs(self) -> None:
        """validate_skill() includes reference checks from non-entry .md files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir, body="# Router Skill\n")
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nSee [missing](references/missing.md).\n",
            )
            errors, passes = validate_skill(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        broken = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(len(broken), 1)
        self.assertIn("references/missing.md", broken[0])

    def test_unreadable_md_file_produces_warn(self) -> None:
        """An unreadable .md file produces a WARN instead of being skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, "---\nname: test\n---\n# Skill\n")
            # Write a file with invalid encoding
            bad_file = os.path.join(tmpdir, "references", "bad.md")
            os.makedirs(os.path.dirname(bad_file), exist_ok=True)
            with open(bad_file, "wb") as f:
                f.write(b"\x80\x81\x82\x83")
            errors, passes = validate_skill_references(
                tmpdir, tmpdir, skill_md,
            )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        read_warns = [e for e in warn_errors if "cannot be read" in e]
        self.assertEqual(len(read_warns), 1)
        self.assertIn("bad.md", read_warns[0])

    def test_refs_inside_fenced_code_blocks_are_ignored(self) -> None:
        """References inside fenced code blocks are not treated as real links."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, "---\nname: test\n---\n# Skill\n")
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\n"
                "```markdown\n"
                "See [example](references/FAKE.md) for details.\n"
                "```\n",
            )
            errors, passes = validate_skill_references(
                tmpdir, tmpdir, skill_md,
            )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])


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
        """A non-standard directory produces an INFO warning with foundry attribution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "custom-dir"))
            warnings, passes = validate_directories(tmpdir)
        self.assertEqual(len(warnings), 1)
        self.assertIn(LEVEL_INFO, warnings[0])
        self.assertIn("[foundry]", warnings[0])
        self.assertIn("custom-dir", warnings[0])
        self.assertIn("spec allows arbitrary directories", warnings[0])
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

    def test_imperative_description_returns_info(self) -> None:
        """A SKILL.md with an imperative description produces an INFO (foundry)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(
                skill_dir,
                description="Process data files and generate reports.",
            )
            errors, passes = validate_skill(skill_dir)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        imperative_infos = [e for e in info_errors if "imperative" in e]
        self.assertGreaterEqual(len(imperative_infos), 1)

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


class BuildParserTests(unittest.TestCase):
    """Direct unit tests for the argparse parser builder."""

    def test_parser_returns_argument_parser(self) -> None:
        """_build_parser returns an ArgumentParser instance."""
        import argparse

        parser = _build_parser()
        self.assertIsInstance(parser, argparse.ArgumentParser)

    def test_parser_accepts_positional_skill_path(self) -> None:
        """Parser accepts a single positional skill_path argument."""
        parser = _build_parser()
        args = parser.parse_args(["skills/demo"])
        self.assertEqual(args.skill_path, "skills/demo")

    def test_parser_defaults_are_false(self) -> None:
        """All optional flags default to False."""
        parser = _build_parser()
        args = parser.parse_args(["skills/demo"])
        self.assertFalse(args.capability)
        self.assertFalse(args.verbose)
        self.assertFalse(args.allow_nested_refs)
        self.assertFalse(args.json_output)

    def test_parser_accepts_all_flags(self) -> None:
        """Parser accepts all optional flags together."""
        parser = _build_parser()
        args = parser.parse_args([
            "skills/demo",
            "--capability",
            "--verbose",
            "--allow-nested-references",
            "--json",
        ])
        self.assertTrue(args.capability)
        self.assertTrue(args.verbose)
        self.assertTrue(args.allow_nested_refs)
        self.assertTrue(args.json_output)

    def test_parser_rejects_unknown_flag(self) -> None:
        """Parser exits on unrecognised flags."""
        parser = _build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["skills/demo", "--bogus"])

    def test_parser_rejects_missing_positional(self) -> None:
        """Parser exits when no positional argument is provided."""
        parser = _build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])


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

    def test_info_only_exits_zero(self) -> None:
        """A skill with only INFO errors (no FAIL/WARN) exits with code 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            # Imperative description triggers INFO (foundry convention), not FAIL
            write_skill_md(
                skill_dir,
                description="Process data files and generate reports.",
            )
            proc = _run([skill_dir], cwd=REPO_ROOT)
        # INFO-only should exit 0 (only FAIL causes exit 1)
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

    def test_verbose_with_info_prints_passes_and_errors(self) -> None:
        """--verbose with INFO messages still prints both passes and error lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            # Imperative description triggers INFO (foundry convention)
            write_skill_md(
                skill_dir,
                description="Process data files and generate reports.",
            )
            proc = _run([skill_dir, "--verbose"], cwd=REPO_ROOT)
        # Should exit 0 (INFO only)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        # Verbose output includes pass marks
        self.assertIn("\u2713", proc.stdout)
        # Should include the info symbol
        self.assertIn("\u2139", proc.stdout)
        # Should include summary line
        self.assertIn("Results:", proc.stdout)
        self.assertIn("info", proc.stdout.lower())

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


# ===================================================================
# _check_references tail branches
# ===================================================================


class CheckReferencesTailTests(unittest.TestCase):
    """Tests for rarely-hit branches in the reference checker."""

    def test_pure_fragment_reference_produces_no_broken_warning(self) -> None:
        """A pure ``[text](#anchor)`` reference is skipped, not reported as broken."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            os.makedirs(skill_dir)
            skill_md = os.path.join(skill_dir, "SKILL.md")
            body = "# Skill\n\nJump to [top](#overview) for details.\n"
            errors, passes = validate_body(body, skill_md, skill_dir)
        broken = [e for e in errors if "does not exist" in e]
        self.assertEqual(broken, [])

    def test_internal_plus_external_refs_emit_combined_pass(self) -> None:
        """A mix of valid intra-skill refs and an external ref emits the combined pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "references", "guide.md"),
                "# Guide\n",
            )
            # External ref: resolves outside skill_dir after normalization.
            # The regex only captures paths starting with references/,
            # scripts/, or assets/ — so we use a path that begins with
            # references/ but escapes via ../../
            write_text(os.path.join(tmpdir, "shared.md"), "# Shared\n")
            skill_md = os.path.join(skill_dir, "SKILL.md")
            body = (
                "# Skill\n\n"
                "See [guide](references/guide.md) for details.\n"
                "Also see [shared](references/../../shared.md).\n"
            )
            errors, passes = validate_body(body, skill_md, skill_dir)
        combined = [
            p for p in passes
            if "external refs excluded from nesting checks" in p
            and "internal refs one level deep" in p
        ]
        self.assertEqual(len(combined), 1)


# ===================================================================
# main() in-process — covers CLI-entry branches for coverage
# ===================================================================


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    """Invoke validate_skill.main() in-process and capture streams.

    Returns ``(exit_code, stdout, stderr)``.  Subprocess-based CLI tests
    cannot contribute to coverage because the coverage session does not
    span child Python processes.
    """
    import validate_skill as vs

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with (
        mock.patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        try:
            vs.main()
        except SystemExit as exc:
            if exc.code is None:
                code = 0
            elif isinstance(exc.code, int):
                code = exc.code
            else:
                code = 1
    return code, stdout.getvalue(), stderr.getvalue()


class MainInProcessTests(unittest.TestCase):
    """In-process coverage for the ``main()`` CLI entry point."""

    def test_no_args_prints_docstring_and_exits_1(self) -> None:
        code, out, _ = _run_main(["validate_skill.py"])
        self.assertEqual(code, 1)
        self.assertIn("Usage:", out)

    def test_non_directory_path_text_mode_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            f_path = os.path.join(tmpdir, "not-a-dir.txt")
            write_text(f_path, "x")
            code, out, _ = _run_main(["validate_skill.py", f_path])
        self.assertEqual(code, 1)
        self.assertIn("not a directory", out.lower())

    def test_non_directory_path_json_mode_emits_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            f_path = os.path.join(tmpdir, "not-a-dir.txt")
            write_text(f_path, "x")
            code, out, _ = _run_main(["validate_skill.py", f_path, "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["tool"], "validate_skill")
        self.assertFalse(payload["success"])
        self.assertIn("is not a directory", payload["error"])

    def test_valid_skill_text_mode_prints_all_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            code, out, _ = _run_main(["validate_skill.py", skill_dir])
        self.assertEqual(code, 0)
        self.assertIn("All checks passed", out)

    def test_valid_skill_verbose_prints_pass_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            code, out, _ = _run_main(["validate_skill.py", skill_dir, "--verbose"])
        self.assertEqual(code, 0)
        self.assertIn("\u2713", out)
        self.assertIn("All checks passed", out)
        self.assertIn("checks", out)

    def test_valid_skill_json_non_verbose_omits_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            code, out, _ = _run_main(["validate_skill.py", skill_dir, "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["type"], "registered skill")
        self.assertIn("summary", payload)
        self.assertNotIn("passes", payload)

    def test_valid_skill_json_verbose_includes_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            code, out, _ = _run_main(
                ["validate_skill.py", skill_dir, "--json", "--verbose"],
            )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["success"])
        self.assertIn("passes", payload)
        self.assertIsInstance(payload["passes"], list)

    def test_failing_skill_text_mode_exits_1_with_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n---\n\n# Skill\n",
            )
            code, out, _ = _run_main(["validate_skill.py", skill_dir])
        self.assertEqual(code, 1)
        self.assertIn("Results:", out)
        self.assertIn("failure", out.lower())

    def test_failing_skill_json_mode_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n---\n\n# Skill\n",
            )
            code, out, _ = _run_main(["validate_skill.py", skill_dir, "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertFalse(payload["success"])
        self.assertGreaterEqual(payload["summary"]["failures"], 1)

    def test_warn_only_skill_json_mode_exits_0(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(
                skill_dir,
                body="# Skill\n\nSee [gone](references/missing.md) for details.\n",
            )
            code, out, _ = _run_main(["validate_skill.py", skill_dir, "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["success"])
        self.assertGreaterEqual(payload["summary"]["warnings"], 1)

    def test_argparse_failure_text_mode_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            code, _out, err = _run_main(
                ["validate_skill.py", skill_dir, "--bogus"],
            )
        self.assertEqual(code, 1)
        self.assertIn("unrecognized arguments", err)

    def test_argparse_failure_json_mode_emits_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            code, out, _err = _run_main(
                ["validate_skill.py", skill_dir, "--bogus", "--json"],
            )
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["tool"], "validate_skill")
        self.assertFalse(payload["success"])
        self.assertIn("error", payload)

    def test_missing_positional_json_mode_emits_envelope(self) -> None:
        code, out, _err = _run_main(["validate_skill.py", "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertFalse(payload["success"])
        self.assertIn("error", payload)

    def test_capability_mode_json_reports_capability_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(cap_dir, body="# Cap\n")
            code, out, _ = _run_main(
                ["validate_skill.py", cap_dir, "--capability", "--json"],
            )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["type"], "capability")


# ===================================================================
# validate_allowed_tools
# ===================================================================


class ValidateAllowedToolsTests(unittest.TestCase):
    """Tests for the validate_allowed_tools function."""

    def test_valid_known_tools_pass(self) -> None:
        """A space-separated list of known tools produces passes."""
        errors, passes = validate_allowed_tools("bash git python")
        self.assertEqual(errors, [])
        tool_pass = [p for p in passes if "tools recognized" in p]
        self.assertEqual(len(tool_pass), 1)
        count_pass = [p for p in passes if "3 tools" in p]
        self.assertEqual(len(count_pass), 1)

    def test_single_known_tool_passes(self) -> None:
        """A single known tool passes."""
        errors, passes = validate_allowed_tools("bash")
        self.assertEqual(errors, [])
        self.assertTrue(len(passes) >= 2)

    def test_unknown_tool_returns_info(self) -> None:
        """An unrecognized tool produces an INFO warning."""
        errors, passes = validate_allowed_tools("bash unknowntool git")
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("unknowntool", info_errors[0])

    def test_multiple_unknown_tools_listed(self) -> None:
        """Multiple unrecognized tools are all listed in the INFO message."""
        errors, passes = validate_allowed_tools("foo bar bash baz")
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        for tool in ("bar", "baz", "foo"):
            self.assertIn(tool, info_errors[0])

    def test_duplicate_unknown_tools_deduplicated(self) -> None:
        """Duplicate unrecognized tools appear only once in the INFO message."""
        errors, passes = validate_allowed_tools("foo foo bash foo")
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        # "foo" should appear exactly once in the comma-separated list
        tools_part = info_errors[0].split("unrecognized tools: ")[1].split(" —")[0]
        self.assertEqual(tools_part, "foo")

    def test_empty_value_returns_warn(self) -> None:
        """An empty allowed-tools value produces a WARN."""
        errors, passes = validate_allowed_tools("")
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("empty", warn_errors[0])

    def test_whitespace_only_returns_warn(self) -> None:
        """A whitespace-only allowed-tools value produces a WARN."""
        errors, passes = validate_allowed_tools("   ")
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)

    def test_exceeding_max_tools_returns_warn(self) -> None:
        """Exceeding MAX_ALLOWED_TOOLS produces a WARN."""
        tools = " ".join(f"tool{i}" for i in range(MAX_ALLOWED_TOOLS + 1))
        errors, passes = validate_allowed_tools(tools)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        count_warns = [e for e in warn_errors if "max" in e.lower()]
        self.assertEqual(len(count_warns), 1)
        self.assertIn(str(MAX_ALLOWED_TOOLS), count_warns[0])

    def test_at_max_tools_passes(self) -> None:
        """Exactly MAX_ALLOWED_TOOLS tools passes the count check."""
        # Use known tools repeated to fill up to max, then pad with unknowns
        tools = " ".join(f"tool{i}" for i in range(MAX_ALLOWED_TOOLS))
        errors, passes = validate_allowed_tools(tools)
        count_warns = [e for e in errors if "max" in e.lower() and e.startswith(LEVEL_WARN)]
        self.assertEqual(count_warns, [])
        count_pass = [p for p in passes if str(MAX_ALLOWED_TOOLS) in p]
        self.assertEqual(len(count_pass), 1)

    def test_all_known_tools_pass(self) -> None:
        """All tools in KNOWN_TOOLS are recognized without INFO."""
        # Test a representative subset to avoid exceeding max_tools
        sample = list(KNOWN_TOOLS)[:MAX_ALLOWED_TOOLS]
        errors, passes = validate_allowed_tools(" ".join(sample))
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(info_errors, [])

    def test_list_value_returns_warn(self) -> None:
        """A list value for allowed-tools produces a WARN about type."""
        errors, passes = validate_allowed_tools(["bash", "python"])
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("space-separated string", warn_errors[0])
        self.assertIn("list", warn_errors[0])
        self.assertEqual(passes, [])

    def test_int_value_returns_warn(self) -> None:
        """An integer value for allowed-tools produces a WARN about type."""
        errors, passes = validate_allowed_tools(42)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("space-separated string", warn_errors[0])
        self.assertIn("int", warn_errors[0])
        self.assertEqual(passes, [])

    def test_none_value_returns_warn(self) -> None:
        """A None value for allowed-tools produces a WARN about type."""
        errors, passes = validate_allowed_tools(None)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("space-separated string", warn_errors[0])
        self.assertIn("NoneType", warn_errors[0])
        self.assertEqual(passes, [])


# ===================================================================
# validate_metadata
# ===================================================================


class ValidateMetadataTests(unittest.TestCase):
    """Tests for the validate_metadata function."""

    def test_valid_version_passes(self) -> None:
        """A valid semver version produces a pass."""
        errors, passes = validate_metadata({"version": "1.2.3"})
        self.assertEqual(errors, [])
        version_pass = [p for p in passes if "version" in p]
        self.assertEqual(len(version_pass), 1)
        self.assertIn("1.2.3", version_pass[0])

    def test_version_with_prerelease_passes(self) -> None:
        """A semver version with pre-release suffix passes."""
        errors, passes = validate_metadata({"version": "2.0.0-beta.1"})
        self.assertEqual(errors, [])
        version_pass = [p for p in passes if "version" in p]
        self.assertEqual(len(version_pass), 1)

    def test_invalid_version_returns_info(self) -> None:
        """An invalid version format produces an INFO (foundry recommendation)."""
        errors, passes = validate_metadata({"version": "1.2"})
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("version", info_errors[0])
        self.assertIn("semver", info_errors[0])
        self.assertIn("[foundry]", info_errors[0])

    def test_version_with_v_prefix_returns_info(self) -> None:
        """A version with 'v' prefix does not match recommended semver pattern."""
        errors, passes = validate_metadata({"version": "v1.0.0"})
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("[foundry]", info_errors[0])

    def test_spec_string_passes(self) -> None:
        """Any string spec value produces a pass (spec allows arbitrary metadata)."""
        errors, passes = validate_metadata({"spec": "1.0"})
        self.assertEqual(errors, [])
        spec_pass = [p for p in passes if "spec" in p]
        self.assertEqual(len(spec_pass), 1)

    def test_spec_arbitrary_string_passes(self) -> None:
        """Any arbitrary string spec value passes (no version list enforced)."""
        errors, passes = validate_metadata({"spec": "2.0"})
        self.assertEqual(errors, [])
        spec_pass = [p for p in passes if "spec" in p]
        self.assertEqual(len(spec_pass), 1)
        self.assertIn("2.0", spec_pass[0])

    def test_valid_author_passes(self) -> None:
        """A valid author string produces a pass."""
        errors, passes = validate_metadata({"author": "Jane Doe"})
        self.assertEqual(errors, [])
        author_pass = [p for p in passes if "author" in p]
        self.assertEqual(len(author_pass), 1)

    def test_empty_author_returns_warn(self) -> None:
        """An empty author string produces a WARN."""
        errors, passes = validate_metadata({"author": ""})
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("author", warn_errors[0])
        self.assertIn("empty", warn_errors[0])

    def test_whitespace_only_author_returns_warn(self) -> None:
        """A whitespace-only author produces a WARN."""
        errors, passes = validate_metadata({"author": "   "})
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("empty", warn_errors[0])

    def test_author_exceeding_max_length_returns_warn(self) -> None:
        """An author exceeding MAX_AUTHOR_LENGTH produces a WARN."""
        long_author = "a" * (MAX_AUTHOR_LENGTH + 1)
        errors, passes = validate_metadata({"author": long_author})
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn(str(MAX_AUTHOR_LENGTH), warn_errors[0])

    def test_author_at_max_length_passes(self) -> None:
        """An author at exactly MAX_AUTHOR_LENGTH passes."""
        exact_author = "a" * MAX_AUTHOR_LENGTH
        errors, passes = validate_metadata({"author": exact_author})
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])
        author_pass = [p for p in passes if "author" in p]
        self.assertEqual(len(author_pass), 1)

    def test_non_dict_metadata_returns_warn(self) -> None:
        """A non-dict metadata value produces a WARN."""
        errors, passes = validate_metadata("not a dict")
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("key-value map", warn_errors[0])

    def test_multiple_valid_fields_all_pass(self) -> None:
        """Multiple valid metadata fields each produce a pass."""
        metadata = {"version": "1.0.0", "spec": "1.0", "author": "Test Author"}
        errors, passes = validate_metadata(metadata)
        self.assertEqual(errors, [])
        self.assertEqual(len(passes), 3)

    def test_empty_metadata_dict_passes(self) -> None:
        """An empty metadata dict produces no errors or passes."""
        errors, passes = validate_metadata({})
        self.assertEqual(errors, [])
        self.assertEqual(passes, [])

    def test_non_string_version_returns_warn(self) -> None:
        """A non-string version value produces a WARN about type."""
        errors, passes = validate_metadata({"version": 123})
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("version", warn_errors[0])
        self.assertIn("should be a string", warn_errors[0])
        self.assertIn("int", warn_errors[0])

    def test_non_string_spec_returns_warn(self) -> None:
        """A non-string spec value produces a WARN about type."""
        errors, passes = validate_metadata({"spec": 1.0})
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("spec", warn_errors[0])
        self.assertIn("should be a string", warn_errors[0])

    def test_non_string_author_returns_warn(self) -> None:
        """A non-string author value produces a WARN about type."""
        errors, passes = validate_metadata({"author": 42})
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("author", warn_errors[0])
        self.assertIn("should be a string", warn_errors[0])
        self.assertIn("int", warn_errors[0])

    def test_none_author_returns_warn(self) -> None:
        """A None author value produces a WARN about type."""
        errors, passes = validate_metadata({"author": None})
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("author", warn_errors[0])
        self.assertIn("NoneType", warn_errors[0])

    def test_prefixed_spec_version_passes(self) -> None:
        """A spec value with agentskills.io/ prefix passes as a valid string."""
        errors, passes = validate_metadata({"spec": "agentskills.io/1.0"})
        self.assertEqual(errors, [])
        spec_pass = [p for p in passes if "spec" in p]
        self.assertEqual(len(spec_pass), 1)
        self.assertIn("agentskills.io/1.0", spec_pass[0])

    def test_prefixed_spec_any_version_passes(self) -> None:
        """Any prefixed spec value passes (no version list enforced)."""
        errors, passes = validate_metadata({"spec": "agentskills.io/9.9"})
        self.assertEqual(errors, [])
        spec_pass = [p for p in passes if "spec" in p]
        self.assertEqual(len(spec_pass), 1)
        self.assertIn("agentskills.io/9.9", spec_pass[0])

    def test_list_metadata_returns_warn(self) -> None:
        """A list value for metadata produces a WARN about type."""
        errors, passes = validate_metadata(["version", "1.0.0"])
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("key-value map", warn_errors[0])
        self.assertIn("list", warn_errors[0])

    def test_int_metadata_returns_warn(self) -> None:
        """An integer value for metadata produces a WARN about type."""
        errors, passes = validate_metadata(42)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("key-value map", warn_errors[0])
        self.assertIn("int", warn_errors[0])


# ===================================================================
# validate_license
# ===================================================================


class ValidateLicenseTests(unittest.TestCase):
    """Tests for the validate_license function."""

    def test_known_spdx_license_passes(self) -> None:
        """A known SPDX identifier produces a pass."""
        errors, passes = validate_license("MIT")
        self.assertEqual(errors, [])
        license_pass = [p for p in passes if "SPDX" in p]
        self.assertEqual(len(license_pass), 1)
        self.assertIn("MIT", license_pass[0])

    def test_apache_license_passes(self) -> None:
        """Apache-2.0 is recognized as a known SPDX identifier."""
        errors, passes = validate_license("Apache-2.0")
        self.assertEqual(errors, [])
        license_pass = [p for p in passes if "SPDX" in p]
        self.assertEqual(len(license_pass), 1)

    def test_unknown_license_returns_info(self) -> None:
        """An unrecognized license produces an INFO."""
        errors, passes = validate_license("CustomLicense-1.0")
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("CustomLicense-1.0", info_errors[0])
        self.assertIn("SPDX", info_errors[0])

    def test_empty_license_returns_warn(self) -> None:
        """An empty license value produces a WARN."""
        errors, passes = validate_license("")
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("empty", warn_errors[0])

    def test_whitespace_only_license_returns_warn(self) -> None:
        """A whitespace-only license produces a WARN."""
        errors, passes = validate_license("   ")
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)

    def test_all_known_spdx_licenses_pass(self) -> None:
        """Every license in KNOWN_SPDX_LICENSES is recognized."""
        for lic in sorted(KNOWN_SPDX_LICENSES):
            errors, passes = validate_license(lic)
            with self.subTest(license=lic):
                self.assertEqual(errors, [])
                license_pass = [p for p in passes if "SPDX" in p]
                self.assertEqual(len(license_pass), 1)

    def test_int_value_returns_warn(self) -> None:
        """An integer value for license produces a WARN about type."""
        errors, passes = validate_license(42)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("should be a string", warn_errors[0])
        self.assertIn("int", warn_errors[0])
        self.assertEqual(passes, [])

    def test_list_value_returns_warn(self) -> None:
        """A list value for license produces a WARN about type."""
        errors, passes = validate_license(["MIT", "Apache-2.0"])
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("should be a string", warn_errors[0])
        self.assertIn("list", warn_errors[0])
        self.assertEqual(passes, [])

    def test_none_value_returns_warn(self) -> None:
        """A None value for license produces a WARN about type."""
        errors, passes = validate_license(None)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("should be a string", warn_errors[0])
        self.assertIn("NoneType", warn_errors[0])
        self.assertEqual(passes, [])

    def test_bool_value_returns_warn(self) -> None:
        """A boolean value for license produces a WARN about type."""
        errors, passes = validate_license(True)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("should be a string", warn_errors[0])
        self.assertIn("bool", warn_errors[0])
        self.assertEqual(passes, [])


# ===================================================================
# validate_known_keys
# ===================================================================


class ValidateKnownKeysTests(unittest.TestCase):
    """Tests for the validate_known_keys function."""

    def test_all_known_keys_pass(self) -> None:
        """A frontmatter with only known keys produces a pass."""
        fm = {k: "value" for k in KNOWN_FRONTMATTER_KEYS}
        errors, passes = validate_known_keys(fm)
        self.assertEqual(errors, [])
        key_pass = [p for p in passes if "all keys recognized" in p]
        self.assertEqual(len(key_pass), 1)

    def test_misspelled_key_returns_info(self) -> None:
        """A misspelled key like 'compatability' produces an INFO."""
        fm = {"name": "test", "description": "Test.", "compatability": "Python 3.12"}
        errors, passes = validate_known_keys(fm)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("compatability", info_errors[0])

    def test_multiple_unrecognized_keys_listed(self) -> None:
        """Multiple unrecognized keys are all listed in the INFO message."""
        fm = {"name": "test", "descrption": "oops", "namee": "typo"}
        errors, passes = validate_known_keys(fm)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("descrption", info_errors[0])
        self.assertIn("namee", info_errors[0])

    def test_empty_frontmatter_passes(self) -> None:
        """An empty frontmatter dict produces a pass (no unknown keys)."""
        errors, passes = validate_known_keys({})
        self.assertEqual(errors, [])
        key_pass = [p for p in passes if "all keys recognized" in p]
        self.assertEqual(len(key_pass), 1)

    def test_non_dict_returns_empty(self) -> None:
        """A non-dict input returns empty errors and passes."""
        errors, passes = validate_known_keys("not a dict")
        self.assertEqual(errors, [])
        self.assertEqual(passes, [])

    def test_known_keys_listed_in_info_message(self) -> None:
        """The INFO message includes the list of known keys."""
        fm = {"typo-key": "value"}
        errors, passes = validate_known_keys(fm)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        # Verify at least some known keys are mentioned
        for key in ("name", "description", "compatibility"):
            self.assertIn(key, info_errors[0])


# ===================================================================
# validate_skill — optional frontmatter integration
# ===================================================================


class ValidateSkillOptionalFieldsTests(unittest.TestCase):
    """Tests for optional frontmatter field validation in validate_skill."""

    def test_allowed_tools_validated_in_skill(self) -> None:
        """allowed-tools field is validated when present in frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "allowed-tools: bash git\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        tools_pass = [p for p in passes if "allowed-tools" in p]
        self.assertGreaterEqual(len(tools_pass), 1)

    def test_unknown_allowed_tool_returns_info(self) -> None:
        """An unknown tool in allowed-tools produces an INFO in validate_skill."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "allowed-tools: bash unknowntool\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        tool_infos = [e for e in info_errors if "unknowntool" in e]
        self.assertEqual(len(tool_infos), 1)

    def test_metadata_validated_in_skill(self) -> None:
        """metadata field is validated when present in frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "metadata:\n"
                "  version: 1.0.0\n"
                "  spec: \"1.0\"\n"
                "  author: Test Author\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        meta_passes = [p for p in passes if "metadata" in p]
        self.assertGreaterEqual(len(meta_passes), 1)

    def test_invalid_metadata_version_returns_info(self) -> None:
        """An invalid metadata version produces an INFO in validate_skill (foundry)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "metadata:\n"
                "  version: bad\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        version_infos = [e for e in info_errors if "version" in e]
        self.assertEqual(len(version_infos), 1)

    def test_license_validated_in_skill(self) -> None:
        """license field is validated when present in frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "license: MIT\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        license_pass = [p for p in passes if "license" in p]
        self.assertEqual(len(license_pass), 1)

    def test_unknown_license_returns_info_in_skill(self) -> None:
        """An unrecognized license produces an INFO in validate_skill."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "license: Proprietary\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        license_infos = [e for e in info_errors if "Proprietary" in e]
        self.assertEqual(len(license_infos), 1)

    def test_unrecognized_key_returns_info_in_skill(self) -> None:
        """An unrecognized frontmatter key produces an INFO in validate_skill."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "compatability: Python 3.12\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        key_infos = [e for e in info_errors if "compatability" in e]
        self.assertEqual(len(key_infos), 1)

    def test_valid_skill_with_all_optional_fields_passes(self) -> None:
        """A skill with all optional fields correctly set produces no FAIL/WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "compatibility: Requires Python 3.12 or later.\n"
                "allowed-tools: bash git python\n"
                "license: MIT\n"
                "metadata:\n"
                "  version: 1.0.0\n"
                "  spec: \"1.0\"\n"
                "  author: Test Author\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(fail_errors, [])
        self.assertEqual(warn_errors, [])

    def test_known_keys_pass_reported_for_valid_skill(self) -> None:
        """A valid skill reports 'all keys recognized' pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            errors, passes = validate_skill(skill_dir)
        key_pass = [p for p in passes if "all keys recognized" in p]
        self.assertEqual(len(key_pass), 1)

    def test_spec_string_passes_in_skill(self) -> None:
        """Any spec string value passes in validate_skill (arbitrary metadata)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n"
                "description: Validates data files and generates reports.\n"
                "metadata:\n"
                "  spec: agentskills.io\n"
                "---\n\n# Skill\n",
            )
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        spec_pass = [p for p in passes if "spec" in p and "agentskills.io" in p]
        self.assertEqual(len(spec_pass), 1)

    def test_optional_fields_not_checked_for_capabilities(self) -> None:
        """Capabilities skip optional frontmatter field validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(
                cap_dir,
                frontmatter="name: my-cap\ntypo-field: oops",
                body="# My Capability\n",
            )
            errors, passes = validate_skill(cap_dir, is_capability=True)
        # Should only have the INFO about name in frontmatter, not about typo-field
        key_infos = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "typo-field" in e
        ]
        self.assertEqual(key_infos, [])


class CodexFindingsJsonSchemaTests(unittest.TestCase):
    """``validate_skill --json`` surfaces Codex findings in the errors array."""

    def test_divergent_codex_config_appears_in_json_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(skill_dir, "agents", "openai.yaml"),
                "interface:\n"
                "  display_name: Demo\n"
                "  default_prompt: runs tasks: quickly\n",
            )
            proc = _run([skill_dir, "--json"], cwd=REPO_ROOT)
            data = json.loads(proc.stdout)
        self.assertFalse(data["success"])
        self.assertIn("errors", data)
        # Schema preserved: known top-level keys plus the additive
        # ``yaml_conformance`` slot from #93 (always present, zero
        # sentinel when checks did not run).
        self.assertEqual(
            set(data.keys()),
            {
                "tool", "path", "type", "success", "summary",
                "errors", "version", "yaml_conformance",
            },
        )
        codex_fails = [
            entry for entry in data["errors"].get("failures", [])
            if "[platform: OpenAI]" in entry and "': '" in entry
        ]
        self.assertEqual(len(codex_fails), 1)


class CodexConfigFindingsPropagationTests(unittest.TestCase):
    """Codex plain-scalar findings reach ``validate_skill`` output."""

    def test_divergent_codex_config_surfaces_in_validate_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(skill_dir, "agents", "openai.yaml"),
                "interface:\n"
                "  display_name: Demo\n"
                "  default_prompt: runs tasks: quickly\n",
            )
            errors, _ = validate_skill(skill_dir)
        tagged = [
            e for e in errors
            if e.startswith("FAIL: [platform: OpenAI]") and "': '" in e
        ]
        self.assertEqual(len(tagged), 1)


class CollectFoundryConfigFindingsTests(unittest.TestCase):
    """``collect_foundry_config_findings`` fires only for foundry targets."""

    def test_non_foundry_path_returns_empty(self) -> None:
        """Arbitrary skill paths never surface configuration.yaml findings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            findings = collect_foundry_config_findings(tmpdir)
        self.assertEqual(findings, [])

    def test_foundry_path_with_clean_config_returns_empty(self) -> None:
        """The real foundry config has no divergences today."""
        foundry_path = os.path.join(REPO_ROOT, "skill-system-foundry")
        findings = collect_foundry_config_findings(foundry_path)
        self.assertEqual(findings, [])

    def test_foundry_path_retags_findings_with_foundry_prefix(self) -> None:
        """When divergences exist, messages are retagged ``[foundry]``."""
        foundry_path = os.path.join(REPO_ROOT, "skill-system-foundry")
        sample = [
            "FAIL: [spec] 'skill.name': unquoted value starts with '-' …",
            "WARN: [spec] 'skill.description': unquoted anchor …",
        ]
        with mock.patch(
            "lib.constants.get_config_findings", return_value=sample,
        ):
            retagged = collect_foundry_config_findings(foundry_path)
        self.assertEqual(len(retagged), 2)
        for line in retagged:
            self.assertIn("[foundry] scripts/lib/configuration.yaml", line)
        self.assertTrue(retagged[0].startswith("FAIL: "))
        self.assertTrue(retagged[1].startswith("WARN: "))

    def test_non_foundry_path_ignores_patched_findings(self) -> None:
        """Detection gates on path equality, not on findings content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "lib.constants.get_config_findings",
                return_value=["FAIL: [spec] 'x': bad"],
            ):
                findings = collect_foundry_config_findings(tmpdir)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
