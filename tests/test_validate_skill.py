"""Tests for validate_skill.py.

Covers validate_description, validate_body, validate_directories,
validate_skill, optional frontmatter field validation, and the
main() CLI entry point.
"""

import contextlib
import difflib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from helpers import write_capability_md, write_text, write_skill_md

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
    FRONTMATTER_SUGGEST_CUTOFF,
    FRONTMATTER_SUGGEST_MAX_MATCHES,
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

    def test_whitespace_only_description_returns_fail(self) -> None:
        """A whitespace-only description is a spec violation and must
        FAIL exactly like the empty case — the trigger heuristic
        short-circuits on whitespace, so a falsy-only test would let
        ``"   "`` slip through with no diagnostic."""
        for value in ("   ", "\n\n\t  ", " "):
            with self.subTest(value=repr(value)):
                errors, passes = validate_description(value)
                fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
                empty_fails = [e for e in fail_errors if "empty" in e]
                self.assertEqual(len(empty_fails), 1)
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

    def test_description_with_trigger_phrase_emits_no_trigger_warn(self) -> None:
        """A description containing a configured trigger phrase emits no
        trigger-clause WARN through the end-to-end validate_description."""
        desc = (
            "Manages project timelines and tracks milestones. Triggers when "
            "a milestone changes."
        )
        errors, passes = validate_description(desc)
        trigger_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "when the skill activates" in e
        ]
        self.assertEqual(trigger_warns, [])
        trigger_passes = [p for p in passes if "trigger phrase" in p]
        self.assertEqual(len(trigger_passes), 1)

    def test_description_without_trigger_phrase_emits_warn(self) -> None:
        """A description missing every configured trigger phrase emits a
        single [spec] WARN through validate_description."""
        desc = "Manages project timelines and tracks milestones."
        errors, _ = validate_description(desc)
        trigger_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "when the skill activates" in e
        ]
        self.assertEqual(len(trigger_warns), 1)
        self.assertIn("[spec]", trigger_warns[0])


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

    def test_capability_ref_in_body_detected(self) -> None:
        """References to capabilities/<name>/capability.md are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            cap_file = os.path.join(
                tmpdir, "capabilities", "design", "capability.md"
            )
            write_text(cap_file, "# Design\n\nCapability body.\n")
            body = (
                "# Skill\n\nSee [design](capabilities/design/capability.md).\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        # Capability ref must resolve — no broken-link WARN
        broken_warns = [e for e in errors if "does not exist" in e]
        self.assertEqual(broken_warns, [])

    def test_capability_chain_warns_when_capability_refs_have_nested_refs(self) -> None:
        """SKILL.md → capability.md → references/a.md → b.md must
        produce a nested-ref WARN attributed to the capability.
        capability.md is treated as its own entry-point boundary, so
        its referenced files are checked for nesting just as SKILL.md's
        are.  Pins the gap that opened when we exempted capability
        targets from the parent's own check.

        Under the redefined path-resolution rule, the capability
        reaches the shared skill root via ``../../`` and references
        within shared ``references/`` use bare-sibling form.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(
                os.path.join(
                    tmpdir, "capabilities", "design", "capability.md"
                ),
                "# Design\n\n"
                "See [primer](../../references/a.md) for details.\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "a.md"),
                "# A\n\n"
                "Then see [more](b.md) for follow-up.\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "b.md"),
                "# B\n\nLeaf.\n",
            )
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(
                skill_md,
                "# Skill\n\n"
                "See [design](capabilities/design/capability.md).\n",
            )
            errors, _passes = validate_skill_references(
                tmpdir, tmpdir, skill_md, allow_nested_refs=False,
            )
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(
            len(nested_warns), 1,
            "capability.md's body refs must be checked for nesting "
            f"because capability.md is itself an entry point; got: {nested_warns}",
        )
        self.assertIn("capabilities/design/capability.md", nested_warns[0])

    def test_capability_chain_silent_with_allow_nested_refs(self) -> None:
        """When --allow-nested-references is on, the capability-as-
        entry-point check is suppressed too — pins the existing
        opt-out semantics so the meta-skill's own self-check (which
        uses --allow-nested-references) keeps working."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(
                os.path.join(
                    tmpdir, "capabilities", "design", "capability.md"
                ),
                "# Design\n\nSee [primer](references/a.md).\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "a.md"),
                "# A\n\nThen see [more](references/b.md).\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "b.md"),
                "# B\n",
            )
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(
                skill_md,
                "# Skill\n\n"
                "See [design](capabilities/design/capability.md).\n",
            )
            errors, _passes = validate_skill_references(
                tmpdir, tmpdir, skill_md, allow_nested_refs=True,
            )
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(nested_warns, [])

    def test_unrelated_file_named_capability_md_still_nested_checked(self) -> None:
        """An unrelated reference file that happens to be named
        capability.md (e.g., references/capability.md) is NOT a spec
        entry point — its own links must still be checked for nesting.
        Pins the canonical-shape narrowing of the entry-point
        exemption."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(
                os.path.join(tmpdir, "references", "capability.md"),
                "# Misnamed reference\n\n"
                "See [deeper](references/deeper.md) for more.\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "deeper.md"),
                "# Deeper\n",
            )
            body = (
                "# Skill\n\n"
                "See [misnamed](references/capability.md).\n"
            )
            write_text(skill_md, body)
            errors, _passes = validate_body(
                body, skill_md, os.path.dirname(skill_md),
            )
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(
            len(nested_warns), 1,
            "references/capability.md is not a spec entry point; its "
            "nested references must still be flagged when "
            "--allow-nested-references is off",
        )
        self.assertIn("references/capability.md", nested_warns[0])

    def test_capability_link_not_treated_as_nested_ref(self) -> None:
        """capability.md is its own entry point per the spec — links
        from a capability into references/ are first-level under that
        entry point, not nested under the parent SKILL.md.  When
        --allow-nested-references is OFF, a SKILL.md → capability.md →
        references/foo.md chain must NOT trigger a nested-ref WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(
                os.path.join(
                    tmpdir, "capabilities", "design", "capability.md"
                ),
                "# Design\n\n"
                "See [guide](references/authoring.md) for details.\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "authoring.md"),
                "# Authoring\n",
            )
            body = (
                "# Skill\n\n"
                "See [design](capabilities/design/capability.md).\n"
            )
            write_text(skill_md, body)
            errors, _passes = validate_body(
                body, skill_md, os.path.dirname(skill_md),
            )
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(
            nested_warns, [],
            "capability.md is its own entry point and must not trigger "
            "the nested-references WARN when its body links to references/",
        )

    def test_broken_capability_ref_detected(self) -> None:
        """A broken capabilities/ link produces a WARN like other categories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = (
                "# Skill\n\nSee [missing](capabilities/missing/capability.md).\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        broken_warns = [e for e in errors if "does not exist" in e]
        self.assertEqual(len(broken_warns), 1)
        self.assertIn("capabilities/missing/capability.md", broken_warns[0])

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

    def test_non_markdown_target_skips_nested_scan(self) -> None:
        """Non-markdown targets (``.py``, ``.yaml``, etc.) must not be
        scanned for nested references.

        ``path_resolution.reference_extensions`` legitimately covers
        scripts and configs.  Their content is not markdown, so
        feeding it to ``extract_body_references`` would surface
        spurious nested-reference WARNs whenever a docstring or
        comment happens to contain a ``[link](path.md)`` snippet.
        Existence is still checked via the broken-link branch above
        — this test pins that the read-and-scan stage is skipped
        once the target's extension is not ``.md``.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            scripts_dir = os.path.join(tmpdir, "scripts")
            # A Python file whose docstring looks like markdown — if
            # the validator scans it for nested refs, both
            # ``[guide](references/guide.md)`` and
            # ``[other](references/other.md)`` would surface.
            write_text(
                os.path.join(scripts_dir, "tool.py"),
                "\"\"\"Helper.\n\n"
                "See [guide](references/guide.md) and "
                "[other](references/other.md).\n\"\"\"\n",
            )
            body = (
                "# Skill\n\n"
                "Run [tool](scripts/tool.py) for details.\n"
            )
            write_text(skill_md, body)
            errors, _passes = validate_body(
                body, skill_md, os.path.dirname(skill_md),
            )
        nested_warns = [e for e in errors if "nested references" in e]
        self.assertEqual(nested_warns, [])

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
        """A reference escaping the skill directory produces an INFO
        tagged with the path-resolution rule (per
        ``references/path-resolution.md``)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [escape](../../shared/file.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        escape_infos = [e for e in info_errors if "outside the skill directory" in e]
        self.assertEqual(len(escape_infos), 1)
        self.assertIn("[path-resolution]", escape_infos[0])
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_all_external_refs_no_misleading_pass(self) -> None:
        """When all refs are external, 'one level deep' pass does not fire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = (
                "# Skill\n\n"
                "See [a](../../shared/a.md) and "
                "[b](../../shared/b.md) for details.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        nesting_passes = [p for p in passes if "one level deep" in p]
        self.assertEqual(nesting_passes, [])
        external_passes = [p for p in passes if "external" in p.lower()]
        self.assertEqual(len(external_passes), 1)
        broken_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "does not exist" in e
        ]
        self.assertEqual(broken_warns, [])

    def test_external_ref_skips_filesystem_checks(self) -> None:
        """External refs skip all filesystem checks to avoid existence oracle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = (
                "# Skill\n\n"
                "See [a](../../shared/a.md) for details.\n"
            )
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        info_errors = [e for e in errors if "outside the skill directory" in e]
        self.assertEqual(len(info_errors), 1)
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

    def test_binary_ref_file_does_not_emit_cannot_be_read(self) -> None:
        """A reference to a binary file under a recognized directory
        (e.g. ``references/image.png``) is treated as a valid file
        reference: existence + non-directory checks pass, and the
        UTF-8 read + nested-reference scan is skipped because the
        target is not markdown.

        The ``cannot be read`` WARN belongs to markdown targets
        whose body the validator must scan for nested references —
        binary asset links are not a decode-error class of finding,
        and the existence branch already covers the broken-link
        surface.
        """
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
        self.assertEqual(read_warns, [])
        # No FAIL errors and no broken-link finding either — the
        # file exists and is a regular file.
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        broken = [e for e in warn_errors if "does not exist" in e]
        self.assertEqual(broken, [])

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
        """A reference whose ``..`` chain escapes the skill dir
        produces an INFO under the redefined path-resolution rule."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [escape](../../../assets/elsewhere.md) for details.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, os.path.dirname(skill_md))
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        escape_infos = [e for e in info_errors if "outside the skill directory" in e]
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
    """Tests for file-relative reference resolution in validate_body
    under the redefined path-resolution rule
    (``references/path-resolution.md``).  Two scopes own their own
    subgraphs (skill root, capability root); refs resolve from the
    source file's directory using standard markdown semantics."""

    def test_capability_link_to_capability_local_reference_resolves(self) -> None:
        """A capability writing ``references/guide.md`` resolves to its
        own capability-local reference (file-relative under the
        capability scope)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            cap_dir = os.path.join(tmpdir, "capabilities", "validation")
            write_text(
                os.path.join(cap_dir, "references", "guide.md"),
                "# Guide\n\nContent.\n",
            )
            cap_md = os.path.join(cap_dir, "capability.md")
            body = "# Validation\n\nSee [guide](references/guide.md) for details.\n"
            write_text(cap_md, body)
            errors, passes = validate_body(body, cap_md, tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])
        ref_pass = [p for p in passes if "one level deep" in p]
        self.assertEqual(len(ref_pass), 1)

    def test_capability_link_to_shared_root_via_external_form(self) -> None:
        """A capability reaches the shared skill root via ``../../`` —
        the canonical external-reference form per
        ``references/path-resolution.md``."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            write_text(
                os.path.join(tmpdir, "references", "shared.md"),
                "# Shared\n",
            )
            cap_dir = os.path.join(tmpdir, "capabilities", "validation")
            cap_md = os.path.join(cap_dir, "capability.md")
            body = (
                "# Validation\n\n"
                "See [shared](../../references/shared.md).\n"
            )
            write_text(cap_md, body)
            errors, passes = validate_body(body, cap_md, tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])

    def test_role_references_are_not_captured(self) -> None:
        """An orchestration ``SKILL.md`` that links a role file uses
        system-root-relative paths (``roles/<group>/<name>.md``) per
        the role exception in the path-resolution rule.  The new
        multi-segment regex captures any path through unrecognized
        directories, so without an extraction-time filter ``roles/``
        links would be resolved file-relative under skill_root and
        surface as broken in-skill paths.  ``extract_body_references``
        drops them so the path-resolution surface stays focused on
        in-skill cross-file references; the audit's
        ``check_upward_references`` rule (``--allow-orchestration``)
        validates role links separately.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(
                skill_md,
                "---\nname: test\n---\n# Skill\n"
                "\n"
                "Role: [reviewer](roles/release/reviewer.md)\n"
                "Dotted: [r2](./roles/release/reviewer.md)\n",
            )
            errors, _passes = validate_skill(tmpdir)
        broken = [e for e in errors if e.startswith(LEVEL_WARN)]
        targets = " ".join(broken)
        # Neither role link should produce a broken-link finding —
        # both are out-of-scope for the path-resolution rule.
        self.assertNotIn("roles/release/reviewer.md", targets)

    def test_uri_scheme_links_are_not_captured(self) -> None:
        """URI-scheme markdown links like ``mailto:guide.md`` end in
        a recognized extension but are external destinations, not
        internal file references.  The bare-sibling alternative used
        to allow ``:`` in its body — ``mailto:guide.md`` slipped
        through and the validator reported it as a broken file
        reference.  The fix excludes ``:`` from the bare-sibling
        character class (matching the multi-segment branch's
        no-``:`` rule that already keeps ``https://`` URLs out).
        Pin that the link is dropped and produces no broken-link
        finding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(
                skill_md,
                "---\nname: test\n---\n# Skill\n"
                "\n"
                "Email: [contact](mailto:guide.md)\n"
                "Custom: [proto](myproto:foo.md)\n",
            )
            errors, _passes = validate_skill(tmpdir)
        broken = [e for e in errors if e.startswith(LEVEL_WARN)]
        targets = " ".join(broken)
        self.assertNotIn("mailto:guide.md", targets)
        self.assertNotIn("myproto:foo.md", targets)

    def test_dot_slash_prefixed_multi_segment_links_are_extracted(self) -> None:
        """Standard markdown allows the explicit-relative ``./``
        prefix on every form of relative link, including multi-
        segment paths through unrecognized child directories
        (``./guides/setup.md``).  Without ``./`` support on the
        4th regex alternative, that shape slips past the extractor
        and a broken ``./guides/setup.md`` link silently passes the
        conformance gate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(
                skill_md,
                "---\nname: test\n---\n# Skill\n"
                "\n"
                "See [g](./guides/setup.md).\n",
            )
            errors, _passes = validate_skill(tmpdir)
        broken = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "does not exist" in e
        ]
        targets = " ".join(broken)
        self.assertIn("./guides/setup.md", targets)

    def test_multi_segment_relative_links_are_extracted(self) -> None:
        """Standard markdown file-relative links can travel through
        unrecognized child directories — ``guides/setup.md`` from a
        reference file is a valid link even though ``guides`` is not
        in the recognized top-level dir list.  Without a fourth
        regex alternative, those links would slip past validation,
        stats, reachability, and the conformance report, and a
        broken ``guides/setup.md`` link would silently pass CI even
        though a standard markdown reader sees it as broken.

        URLs are kept out by the no-``:`` rule in the new branch
        — ``https://example.com/foo.md`` contains a ``:`` and so
        cannot match the multi-segment pattern.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(
                skill_md,
                "---\nname: test\n---\n# Skill\n"
                "\n"
                "See [g](guides/setup.md).\n"
                "URL: [up](https://example.com/foo.md)\n",
            )
            errors, _passes = validate_skill(tmpdir)
        broken = [
            e for e in errors
            if e.startswith(LEVEL_WARN)
            and "does not exist" in e
        ]
        targets = " ".join(broken)
        # The unrecognized-dir relative link must be flagged.
        self.assertIn("guides/setup.md", targets)
        # The URL must NOT be flagged — the no-``:`` rule keeps it
        # out of the regex.
        self.assertNotIn("https://example.com/foo.md", targets)

    def test_dot_slash_prefixed_links_are_extracted(self) -> None:
        """Standard markdown treats ``./foo.md`` as equivalent to
        ``foo.md`` — a valid file-relative link.  The body reference
        regex must accept the ``./`` prefix in both directory-anchored
        and bare-sibling forms; without it, a broken anchored sibling
        like ``./missing.md#section`` would silently slip past
        validation, stats, reachability, and the conformance report.
        Pin the explicit-relative-prefix coverage with a missing
        target so the validator fails the run.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(
                skill_md,
                "---\nname: test\n---\n# Skill\n"
                "\n"
                "See [bare-sibling](./missing-sibling.md).\n"
                "See [anchored](./references/missing-anchored.md).\n",
            )
            errors, _passes = validate_skill(tmpdir)
        broken = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "does not exist" in e
        ]
        targets = " ".join(broken)
        self.assertIn("./missing-sibling.md", targets)
        self.assertIn("./references/missing-anchored.md", targets)

    def test_capability_to_other_capability_is_not_classified_as_external(self) -> None:
        """A capability reaching into a sibling capability is an
        architecture concern, not a lift-rewrite candidate.  After
        lift, the sibling capability is gone — the link cannot be
        mechanically inlined as shared content.  The path-resolution
        rule emits a distinct INFO that names the target capability
        and points at the audit's capability-isolation rule, so a
        single-skill ``validate_skill`` run does not silently absorb
        the architecture violation as a generic ``external reference
        — recorded for the capability-lift tool``.

        Both the canonical ``../../capabilities/<other>/...`` and the
        natural file-relative ``../<other>/...`` forms must be caught
        — the body reference regex has a third alternative that
        captures any ``(\\.\\./)+`` path ending in a recognized
        extension, so neither shape can slip past validation.
        """
        for body_link, label in (
            ("../../capabilities/beta/capability.md",
             "directory-anchored"),
            ("../beta/capability.md",
             "natural file-relative sibling"),
        ):
            with self.subTest(form=label):
                with tempfile.TemporaryDirectory() as tmpdir:
                    write_text(
                        os.path.join(tmpdir, "SKILL.md"),
                        "---\nname: test\n---\n",
                    )
                    cap_a = os.path.join(tmpdir, "capabilities", "alpha")
                    cap_b = os.path.join(tmpdir, "capabilities", "beta")
                    write_text(
                        os.path.join(cap_b, "capability.md"), "# Beta\n",
                    )
                    cap_a_md = os.path.join(cap_a, "capability.md")
                    body = f"# Alpha\n\nSee [beta]({body_link}).\n"
                    write_text(cap_a_md, body)
                    errors, _passes = validate_body(body, cap_a_md, tmpdir)
                info_errors = [
                    e for e in errors if e.startswith(LEVEL_INFO)
                ]
                # Must NOT carry the lift-tool external-reference
                # message.
                lift_external = [
                    e for e in info_errors
                    if (
                        "external reference — recorded for the "
                        "capability-lift tool"
                    ) in e
                ]
                self.assertEqual(lift_external, [])
                # Must surface a distinct INFO that names the target
                # capability and points at the capability-isolation
                # rule.
                cross_cap = [
                    e for e in info_errors
                    if "crosses into capability 'beta'" in e
                    and "capability-isolation" in e
                ]
                self.assertEqual(
                    len(cross_cap), 1,
                    msg=f"{label}: expected one cross-cap INFO; got "
                    f"{info_errors!r}",
                )

    def test_capability_link_to_missing_local_reference_fails(self) -> None:
        """A capability link to a non-existent local reference fails —
        the broken-link finding names the (capability:<n>) scope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            cap_dir = os.path.join(tmpdir, "capabilities", "validation")
            cap_md = os.path.join(cap_dir, "capability.md")
            body = "# Validation\n\nSee [missing](references/missing.md).\n"
            write_text(cap_md, body)
            errors, passes = validate_body(body, cap_md, tmpdir)
        broken = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "does not exist" in e
        ]
        self.assertEqual(len(broken), 1)
        self.assertIn("scope: capability:validation", broken[0])

    def test_parent_traversal_inside_skill_root_is_legal(self) -> None:
        """Under the redefined rule, ``..`` segments are legal — they
        are how a capability reaches the shared skill root.  A ref
        that uses ``..`` and lands on an existing file inside the
        skill root produces no findings."""
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
        self.assertEqual(warn_errors, [])

    def test_parent_traversal_missing_file_produces_broken_warn(self) -> None:
        """A ``..`` traversal to a missing file inside the skill root
        produces a broken-link WARN — ``..`` itself is no longer
        flagged, but the resolved path still must exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [t](references/../assets/missing.md) for info.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, tmpdir)
        broken_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "does not exist" in e
        ]
        self.assertEqual(len(broken_warns), 1)

    def test_reference_file_sibling_link_resolves_file_relative(self) -> None:
        """A reference file linking a sibling uses bare-filename form
        under the redefined rule — file-relative resolution from the
        file's directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_text(os.path.join(tmpdir, "SKILL.md"), "---\nname: test\n---\n")
            write_text(
                os.path.join(tmpdir, "references", "other.md"),
                "# Other\n\nContent.\n",
            )
            ref_file = os.path.join(tmpdir, "references", "guide.md")
            body = "# Guide\n\nSee also [other](other.md).\n"
            write_text(ref_file, body)
            errors, passes = validate_body(body, ref_file, tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])

    def test_external_path_escaping_skill_root_stays_info(self) -> None:
        """A reference whose ``..`` chain lands outside the skill root
        is by definition out of scope — surfaced as INFO, no broken-
        link WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            body = "# Skill\n\nSee [shared](../../shared/guide.md) for info.\n"
            write_text(skill_md, body)
            errors, passes = validate_body(body, skill_md, tmpdir)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        external_infos = [
            e for e in info_errors if "outside the skill directory" in e
        ]
        self.assertEqual(len(external_infos), 1)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])


# ===================================================================
# validate_skill — capability skill-root auto-detection
# ===================================================================


class ValidateSkillCapabilityRootTests(unittest.TestCase):
    """Tests for validate_skill with is_capability=True auto-detecting the root."""

    def test_capability_auto_detects_skill_root(self) -> None:
        """validate_skill with is_capability=True walks up to find SKILL.md
        and resolves references file-relative.  A capability reaching
        a shared skill-root resource uses the ``../../`` external form."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_skill_md(tmpdir, body="# Router Skill\n")
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nContent.\n",
            )
            cap_dir = os.path.join(tmpdir, "capabilities", "validation")
            body = (
                "# Validation\n\n"
                "See [guide](../../references/guide.md) for details.\n"
            )
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
            # Broken sibling ref in a reference file at the skill root
            # (outside capability dir).  Under the redefined rule,
            # ``[missing](missing.md)`` from a file in references/
            # resolves to references/missing.md (file-relative sibling).
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nSee [missing](missing.md).\n",
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
        self.assertIn("missing.md", broken[0])


# ===================================================================
# validate_skill_references
# ===================================================================


class ValidateSkillReferencesTests(unittest.TestCase):
    """Tests for validate_skill_references — skill-wide .md file scanning."""

    def test_valid_refs_in_reference_file_passes(self) -> None:
        """A reference file with valid file-relative links produces no warns.

        Under the redefined path-resolution rule
        (``references/path-resolution.md``), a sibling reference uses
        bare-filename form (``[other](other.md)``), not the redundant
        ``references/other.md`` form that the old skill-root rule used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, "---\nname: test\n---\n# Skill\n")
            write_text(
                os.path.join(tmpdir, "references", "other.md"),
                "# Other\n",
            )
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nSee also [other](other.md).\n",
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

    def test_parent_traversal_in_reference_file_resolves_legally(self) -> None:
        """Under the redefined rule (``references/path-resolution.md``),
        ``..`` segments are legal — a reference file linking
        ``../assets/other.md`` resolves to a sibling-of-references
        directory and produces no findings when the target exists.

        The assertion checks the *full* warning list, not just the
        broken-link subset.  The previous form filtered on
        ``"does not exist"`` and would have silently passed if a
        regression reintroduced the legacy ``parent traversal`` WARN —
        that finding does not contain ``"does not exist"`` and would
        slip past a narrower filter.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            write_text(skill_md, "---\nname: test\n---\n# Skill\n")
            write_text(
                os.path.join(tmpdir, "references", "guide.md"),
                "# Guide\n\nSee [t](../assets/other.md).\n",
            )
            write_text(
                os.path.join(tmpdir, "assets", "other.md"),
                "# Other\n",
            )
            errors, passes = validate_skill_references(
                tmpdir, tmpdir, skill_md,
            )
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(warn_errors, [])

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

    def test_capability_mode_emits_tool_coherence_skip_pass(self) -> None:
        """Capability-mode validation emits an explicit tool-coherence skip pass.

        The whole-skill coherence rule deliberately does not run in
        capability mode (its scope is the entire skill tree, not a
        single capability), so ``validate_skill`` appends a
        ``tool-coherence: skipped`` pass to surface the deliberate
        skip in JSON output.  Pinning the message text keeps a future
        refactor from silently dropping or renaming the line.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            _, passes = validate_skill(cap_dir, is_capability=True)
        skip_passes = [p for p in passes if "tool-coherence: skipped" in p]
        self.assertEqual(
            len(skip_passes), 1,
            f"expected exactly one tool-coherence skip pass, got {passes!r}",
        )
        self.assertIn("capability mode", skip_passes[0])

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
# --fix mode (mechanical rewrites + unfixable findings)
# ===================================================================


class FixModeTests(unittest.TestCase):
    """``--fix`` surfaces both mechanical rewrites and unfixable
    path-resolution findings, per ``references/path-resolution.md``."""

    def test_fix_dry_run_lists_rewrites_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(skill_dir, "references", "guide.md"), "# Guide\n",
            )
            cap_md = os.path.join(cap_dir, "capability.md")
            write_text(
                cap_md,
                "# Demo\n\nSee [g](references/guide.md).\n",
            )
            proc = _run([skill_dir, "--fix"], cwd=REPO_ROOT)
            with open(cap_md, "r", encoding="utf-8") as f:
                contents_after = f.read()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("Would apply", proc.stdout)
        self.assertIn("references/guide.md", proc.stdout)
        # Dry-run must not modify the source.
        self.assertIn("[g](references/guide.md)", contents_after)

    def test_fix_apply_writes_rewrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(skill_dir, "references", "guide.md"), "# Guide\n",
            )
            cap_md = os.path.join(cap_dir, "capability.md")
            write_text(
                cap_md,
                "# Demo\n\nSee [g](references/guide.md).\n",
            )
            proc = _run([skill_dir, "--fix", "--apply"], cwd=REPO_ROOT)
            with open(cap_md, "r", encoding="utf-8") as f:
                contents_after = f.read()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        # ``--apply`` now runs the rewrite *before* printing, so the
        # human banner is past tense ("Applied") rather than "Applying".
        # The change exists so an I/O failure during apply can be
        # reflected in the JSON payload instead of arriving after a
        # success-looking line on stdout.
        self.assertIn("Applied", proc.stdout)
        self.assertIn("[g](../../references/guide.md)", contents_after)

    def test_fix_surfaces_unfixable_broken_ref_and_exits_one(self) -> None:
        """A broken intra-skill ref the rewriter cannot resolve must
        appear in the ``--fix`` output and force a non-zero exit so
        CI / scripts gate on it.  Pins the contract documented in
        ``references/path-resolution.md`` (lines describing
        ``--fix``: non-mechanical broken paths surface as findings).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(
                skill_dir,
                body="# Skill\n\nSee [m](references/missing.md).\n",
            )
            proc = _run([skill_dir, "--fix"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        self.assertIn("references/missing.md", proc.stdout)
        self.assertIn("path-resolution", proc.stdout)

    def test_fix_json_payload_includes_unfixable_and_doc_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(
                skill_dir,
                body="# Skill\n\nSee [m](references/missing.md).\n",
            )
            proc = _run([skill_dir, "--fix", "--json"], cwd=REPO_ROOT)
            payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        self.assertEqual(payload["mode"], "fix")
        self.assertEqual(payload["fixes"], [])
        self.assertTrue(any(
            "references/missing.md" in f for f in payload["unfixable_findings"]
        ))
        # The non-path FAIL gate is exposed in JSON so consumers can
        # see why the run is failing without re-parsing finding text.
        self.assertIn("non_path_fails", payload)
        # ``success`` mirrors the exit code so JSON consumers do not
        # have to inspect the process status.  An unfixable finding
        # must surface as ``success: false``.
        self.assertIn("success", payload)
        self.assertFalse(payload["success"])
        self.assertEqual(
            payload["path_resolution"]["rule_name"], "path-resolution",
        )
        self.assertIn(
            "path-resolution.md",
            payload["path_resolution"]["documentation_path"],
        )

    def test_fix_json_success_true_on_clean_skill(self) -> None:
        """A skill with no path-resolution findings, no FAILs, and no
        ambiguous legacy links must surface ``success: true`` and
        exit 0 in fix mode.  Pins the success-predicate alignment
        between the JSON payload and the exit code.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, body="# Skill\n")
            proc = _run([skill_dir, "--fix", "--json"], cwd=REPO_ROOT)
            payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["fixes"], [])
        self.assertEqual(payload["unfixable_findings"], [])
        self.assertEqual(payload["non_path_fails"], [])

    def test_fix_capability_mode_walks_enclosing_skill_root(self) -> None:
        """``--fix --capability`` must rewrite the whole skill tree, not
        just the capability subtree.  Otherwise legacy refs in the
        parent SKILL.md and sibling capabilities would be invisible to
        the rewriter, and ``file_rel`` labels would be capability-
        relative instead of skill-root-relative."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(skill_dir, "references", "guide.md"), "# Guide\n",
            )
            # Two legacy refs — one in the capability under target,
            # one in a *sibling* capability outside the supplied path.
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [g](references/guide.md).\n",
            )
            sibling_md = os.path.join(
                skill_dir, "capabilities", "other", "capability.md",
            )
            write_text(
                sibling_md,
                "# Other\n\nSee [g](references/guide.md).\n",
            )
            proc = _run(
                [cap_dir, "--capability", "--fix", "--json"],
                cwd=REPO_ROOT,
            )
            # Pin the happy-path exit code.  The contract is "fix
            # mode rewrites the whole skill tree from a capability
            # subtarget"; that contract includes the CLI returning
            # success.  Without this assertion a regression that
            # produced both rewrite rows but exited non-zero (e.g.,
            # success-predicate drift, an unrelated capability-mode
            # validation FAIL, an apply error) would still satisfy
            # the ``files`` assertion below and leave the bug
            # invisible.
            self.assertEqual(
                proc.returncode, 0, msg=proc.stdout + proc.stderr,
            )
            payload = json.loads(proc.stdout)
        files = {row["file"] for row in payload["fixes"]}
        # Both capabilities must have rewrite rows — proving the
        # rewriter walked the enclosing skill root, not the capability
        # subtree alone.
        self.assertIn("capabilities/demo/capability.md", files)
        self.assertIn("capabilities/other/capability.md", files)

    def test_fix_surfaces_ambiguous_legacy_links(self) -> None:
        """An ambiguous legacy link is one whose pre-migration form
        and post-migration form both resolve to existing in-scope
        files — but to *different* files.  The link's target
        silently changes meaning during migration unless reviewed.
        ``--fix`` must surface it under ``ambiguous_findings`` (not
        silently treat it as already-valid) and gate the exit code
        so CI cannot accept the retargeting without manual review.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            write_skill_md(skill_dir)
            # Shared-root foo.md — what the legacy resolution would pick.
            write_text(
                os.path.join(skill_dir, "references", "foo.md"),
                "# Shared-root foo\n",
            )
            # Capability-local foo.md — what file-relative picks now.
            write_text(
                os.path.join(cap_dir, "references", "foo.md"),
                "# Capability-local foo\n",
            )
            # Capability links references/foo.md — resolves to the
            # capability-local file under the new rule, but the
            # legacy form would have selected the shared-root file.
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [f](references/foo.md).\n",
            )
            proc = _run([skill_dir, "--fix", "--json"], cwd=REPO_ROOT)
            payload = json.loads(proc.stdout)
        # Exit code: 1 — ambiguous findings gate the run.
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        # No rewrite proposed — the rewriter never auto-fixes
        # ambiguous links.
        self.assertEqual(payload["fixes"], [])
        # The ambiguous bucket carries one row with both targets.
        self.assertEqual(len(payload["ambiguous_findings"]), 1)
        amb = payload["ambiguous_findings"][0]
        self.assertEqual(amb["file"], "capabilities/demo/capability.md")
        self.assertEqual(amb["original"], "references/foo.md")
        self.assertEqual(amb["legacy_target"], "references/foo.md")
        self.assertEqual(
            amb["file_rel_target"],
            "capabilities/demo/references/foo.md",
        )

    def test_fix_anchored_legacy_link_is_not_double_reported(self) -> None:
        """An anchored legacy capability link such as
        ``[g](references/guide.md#section)`` is mechanically fixable —
        the rewriter produces a row that preserves the anchor.  The
        ``--fix`` coverage filter must recognize the same link in
        ``_check_references`` finding text (which carries the
        ``strip_fragment``-applied form) so the link does not appear
        under both ``fixes`` *and* ``unfixable_findings``.  Without
        this, the run would exit non-zero on a link the rewriter
        already handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(skill_dir, "references", "guide.md"),
                "# Guide\n",
            )
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [g](references/guide.md#section).\n",
            )
            proc = _run([skill_dir, "--fix", "--json"], cwd=REPO_ROOT)
            payload = json.loads(proc.stdout)
        # The rewriter must have produced a row for the anchored link.
        self.assertEqual(len(payload["fixes"]), 1)
        self.assertEqual(
            payload["fixes"][0]["original"],
            "references/guide.md#section",
        )
        # And the same link must NOT also appear under
        # unfixable_findings — the coverage filter must match through
        # the strip_fragment normalization.
        self.assertEqual(
            payload["unfixable_findings"], [],
            msg=str(payload),
        )
        # Exit clean: a covered fix is the only finding.
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

    def test_fix_apply_json_no_rows_marks_applied_false(self) -> None:
        """When ``--apply`` is passed on a skill with no legacy refs
        to rewrite, ``applied`` must be false because nothing was
        actually written.  The user's intent is preserved in
        ``apply_requested`` so consumers can still distinguish
        ``--fix --apply`` against a clean skill from ``--fix``
        without ``--apply``."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            # Clean skill — nothing for the rewriter to find.
            write_skill_md(skill_dir)
            proc = _run([skill_dir, "--fix", "--apply", "--json"], cwd=REPO_ROOT)
            payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse(payload["applied"])
        self.assertTrue(payload["apply_requested"])
        self.assertEqual(payload["modified"], 0)
        self.assertEqual(payload["fixes"], [])

    def test_fix_apply_json_emits_modified_count_after_write(self) -> None:
        """``--fix --apply --json`` runs the rewrite *before* printing
        the JSON payload so the result reflects what actually
        happened: ``modified`` carries the file count, ``applied``
        is true only on a successful write, and any I/O failure
        surfaces under ``error`` instead of as a traceback after a
        success-looking payload on stdout.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(skill_dir, "references", "guide.md"), "# Guide\n",
            )
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [g](references/guide.md).\n",
            )
            proc = _run([skill_dir, "--fix", "--apply", "--json"], cwd=REPO_ROOT)
            payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertTrue(payload["applied"])
        self.assertEqual(payload["modified"], 1)
        self.assertNotIn("error", payload)

    def test_fix_in_process_covers_main_branch(self) -> None:
        """Run ``validate_skill.main()`` with ``--fix`` in-process so
        the fix-mode block contributes to coverage measurement.  The
        existing FixMode tests use a subprocess via ``_run`` and
        therefore do not feed the parent's coverage session — the
        whole fix branch shows up as uncovered even though it is
        exercised end-to-end.  Pin one happy-path and one error-path
        invocation here so the per-file branch coverage threshold
        catches future drift."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(skill_dir, "references", "guide.md"), "# Guide\n",
            )
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [g](references/guide.md).\n",
            )
            # Happy path — dry run, JSON.
            code, out, _err = _run_main(
                ["validate_skill.py", skill_dir, "--fix", "--json"],
            )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["fixes"]), 1)
        self.assertEqual(payload["unfixable_findings"], [])
        # Cover the human-output branch and the apply path.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(skill_dir, "references", "guide.md"), "# Guide\n",
            )
            cap_md = os.path.join(cap_dir, "capability.md")
            write_text(
                cap_md,
                "# Demo\n\nSee [g](references/guide.md).\n",
            )
            code, out, _err = _run_main(
                ["validate_skill.py", skill_dir, "--fix", "--apply"],
            )
        self.assertEqual(code, 0)
        self.assertIn("Applied", out)

    def test_fix_with_foundry_self_runs_prose_yaml_check(self) -> None:
        """``--foundry-self`` is documented to imply the prose-YAML
        check.  Before this fix the ``--fix`` branch exited from
        ``main()`` before the prose-YAML block ran, so
        ``--foundry-self --fix`` silently skipped that gate while
        the same command without ``--fix`` would surface the
        finding.  Build a skill with a prose-YAML fence the
        validator flags (an unquoted value that starts with a flow
        indicator — strict parsers misread it as a flow
        collection) and pin that ``--fix --foundry-self`` exits
        non-zero with the finding visible in ``non_path_fails``.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            ref_md = os.path.join(skill_dir, "references", "y.md")
            # ``a: [unclosed`` is a strict-parser hazard the
            # prose-YAML check surfaces as a FAIL.
            write_text(
                ref_md,
                "# Y\n\n```yaml\na: [unclosed\n```\n",
            )
            proc = _run(
                [skill_dir, "--fix", "--foundry-self", "--json"],
                cwd=REPO_ROOT,
            )
            payload = json.loads(proc.stdout)
        # The flagged YAML must surface in non_path_fails — the
        # broader-validity gate that ``--fix`` reads for its exit
        # decision.
        prose_fails = [
            f for f in payload["non_path_fails"]
            if "flow" in f.lower() or "[spec]" in f
        ]
        self.assertGreater(
            len(prose_fails), 0,
            msg=f"expected prose-YAML failure in non_path_fails; "
                f"got: {payload['non_path_fails']!r}",
        )
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)

    def test_fix_capability_mode_validates_enclosing_skill_root(self) -> None:
        """When ``--fix --capability`` rewrites the parent skill tree,
        it must also *validate* that same tree.  Otherwise unfixable
        findings or FAILs in SKILL.md or sibling capabilities would not
        show up in ``unfixable_findings`` / ``non_path_fails`` and the
        command could exit 0 after applying whole-tree rewrites while
        the skill remains non-conformant."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            # Parent SKILL.md has a broken intra-skill ref the rewriter
            # cannot resolve mechanically — the supplied --capability
            # path is the *capability*, not the skill, so the previous
            # behavior would never see this finding.
            write_skill_md(
                skill_dir,
                body="# Skill\n\nSee [m](references/missing.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n",
            )
            proc = _run(
                [cap_dir, "--capability", "--fix", "--json"],
                cwd=REPO_ROOT,
            )
            payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        self.assertTrue(any(
            "references/missing.md" in f
            for f in payload["unfixable_findings"]
        ), msg=str(payload))

    def test_fix_capability_mode_without_skill_root_errors(self) -> None:
        """When ``--capability`` is given but no SKILL.md sits above
        the supplied directory, ``--fix`` must refuse rather than
        silently scan only the capability subtree.  The error JSON
        carries the same ``path_resolution`` block as the success
        payload so consumers can navigate to the canonical rule
        without special-casing the failure schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # No SKILL.md anywhere — just a bare capability.md.
            cap_dir = os.path.join(tmpdir, "lonely")
            write_text(
                os.path.join(cap_dir, "capability.md"), "# Lonely\n",
            )
            proc = _run(
                [cap_dir, "--capability", "--fix", "--json"],
                cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload.get("success", True))
        self.assertIn("skill root", payload["error"])
        self.assertEqual(
            payload["path_resolution"]["rule_name"], "path-resolution",
        )
        self.assertIn(
            "path-resolution.md",
            payload["path_resolution"]["documentation_path"],
        )

    def test_fix_exits_one_on_non_path_fail(self) -> None:
        """A skill missing SKILL.md is not conformant; ``--fix`` must
        not exit 0 just because there are no path-resolution
        findings.  The broader-validity gate carries that signal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = os.path.join(tmpdir, "not-a-skill")
            os.makedirs(empty_dir)
            proc = _run([empty_dir, "--fix", "--json"], cwd=REPO_ROOT)
            payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        self.assertIn("non_path_fails", payload)
        self.assertTrue(len(payload["non_path_fails"]) >= 1)

    def test_fix_lists_fixable_and_unfixable_independently(self) -> None:
        """Fixable rewrites and unfixable findings surface in their
        own respective output slots without interfering.

        Pins the contract that a rewriter row covering its own source's
        finding does not leak into the unfixable bucket, and that an
        unrelated unfixable broken ref survives the filter even when
        the two source paths share a substring (one path is a prefix
        of the other under POSIX form).

        Concrete setup: a fixable rewrite originates from
        ``references/sibling.md`` (links ``references/peer.md``,
        rewriteable to ``peer.md``).  Independently a capability-local
        file at ``capabilities/demo/references/sibling.md`` links a
        broken intra-scope path the rewriter cannot resolve.  Note:
        this exercises the *integration* — the unfixable finding's
        ``original`` ref differs from the rewriter row's, so the
        coverage predicate short-circuits on the original-ref check
        and never reaches the position-bounded source-path branch.
        That branch is exercised separately by
        ``test_fix_filter_marker_matches_check_references_output``.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            # Fixable: shared-root ``references/sibling.md`` carries a
            # link to ``references/peer.md``; the legacy form resolves
            # to ``<skill>/references/peer.md`` (which exists), so the
            # rewriter offers ``peer.md``.
            write_text(
                os.path.join(skill_dir, "references", "peer.md"),
                "# Peer\n",
            )
            write_text(
                os.path.join(skill_dir, "references", "sibling.md"),
                "# Sibling\n\nSee [p](references/peer.md).\n",
            )
            # Unfixable: capability-local file with a broken intra-scope
            # link the rewriter cannot resolve (no target exists under
            # the legacy skill-root form either).
            cap_local = os.path.join(
                skill_dir, "capabilities", "demo", "references", "sibling.md",
            )
            write_text(
                cap_local,
                "# Cap-local Sibling\n\nSee [m](references/missing.md).\n",
            )
            # Capability entry — required for the audit walker to enter
            # the capability scope.
            write_text(
                os.path.join(
                    skill_dir, "capabilities", "demo", "capability.md",
                ),
                "# Demo\n",
            )
            proc = _run([skill_dir, "--fix", "--json"], cwd=REPO_ROOT)
            payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        # The fixable rewrite is reported.
        fixable_originals = {f["original"] for f in payload["fixes"]}
        self.assertIn("references/peer.md", fixable_originals)
        # The capability-local unfixable finding survives the filter.
        self.assertTrue(
            any(
                "references/missing.md" in f
                and "capabilities/demo/references/sibling.md" in f
                for f in payload["unfixable_findings"]
            ),
            msg=(
                "Unfixable finding for the longer-pathed capability-local "
                "file was wrongly filtered as covered by the rewriter "
                f"row whose file_rel is a substring. Payload: {payload}"
            ),
        )

    def test_fix_filter_marker_matches_check_references_output(self) -> None:
        """The ``--fix`` coverage filter constructs a position-bounded
        marker (``" referenced in <file_rel> (scope:"``) that must
        match the actual finding text emitted by ``_check_references``.
        Pin the contract: emit a real broken-reference finding, then
        assert the marker substring appears in it.

        Without this contract test, a future rephrase of the
        ``_check_references`` finding text (e.g. changing "referenced
        in" to "referenced by", or dropping the parenthetical scope
        tag) would silently break ``--fix`` coverage — every finding
        would leak to ``unfixable_findings`` and the run would exit 1
        on conformant skills.
        """
        from validate_skill import _check_references  # noqa: E402
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            cap_md = os.path.join(
                skill_dir, "capabilities", "demo", "capability.md",
            )
            body = "# Demo\n\nSee [m](references/missing.md).\n"
            write_text(cap_md, body)
            errors, _passes = _check_references(
                body, cap_md, skill_dir, allow_nested_refs=True,
                source_label="capabilities/demo/capability.md",
            )
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "[path-resolution]" in e
            and "does not exist" in e
        ]
        self.assertEqual(len(warn_errors), 1, msg=str(errors))
        # The marker the --fix filter constructs from a rewriter row
        # must appear verbatim in the emitted finding text.
        marker = " referenced in capabilities/demo/capability.md (scope:"
        self.assertIn(
            marker,
            warn_errors[0],
            msg=(
                "validate_skill --fix's _is_covered_by_rewriter "
                "constructs this marker; if _check_references rephrases "
                "its output, the filter silently stops covering "
                "rewriter rows. Update both call sites in lockstep."
            ),
        )


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
        # Every --json exit must include the path_resolution block
        # so consumers can navigate to the canonical rule from any
        # output stream — success, failure, or early exit.
        self.assertEqual(
            payload["path_resolution"]["rule_name"], "path-resolution",
        )
        self.assertIn(
            "path-resolution.md",
            payload["path_resolution"]["documentation_path"],
        )

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

    def test_empty_string_silently_declares_no_tools(self) -> None:
        """``allowed-tools: ""`` is a deliberate "no tools" declaration."""
        errors, passes = validate_allowed_tools("")
        self.assertEqual(errors, [])
        self.assertIn(
            "allowed-tools: explicitly declares no tools",
            passes,
        )

    def test_whitespace_only_silently_declares_no_tools(self) -> None:
        """Whitespace-only is treated the same as the empty string."""
        errors, passes = validate_allowed_tools("   ")
        self.assertEqual(errors, [])
        self.assertIn(
            "allowed-tools: explicitly declares no tools",
            passes,
        )

    def test_empty_list_silently_declares_no_tools(self) -> None:
        """An empty Python list passes silently at the API level.

        The foundry's YAML subset parser does not recognise inline
        flow sequences, so ``allowed-tools: []`` written in YAML
        frontmatter does **not** reach this branch — that spelling
        parses as the literal string ``"[]"``.  This test pins the
        defensive API-level behaviour for non-foundry callers passing
        a Python list directly.  Non-empty lists still produce the
        spec-conformance WARN — see ``test_non_empty_list_still_warns``.
        """
        errors, passes = validate_allowed_tools([])
        self.assertEqual(errors, [])
        self.assertIn(
            "allowed-tools: explicitly declares no tools",
            passes,
        )

    def test_non_empty_list_still_warns(self) -> None:
        """Non-empty list-form declarations keep the existing spec WARN."""
        errors, _ = validate_allowed_tools(["Bash", "Read"])
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("got list", warn_errors[0])

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

    def test_mcp_pattern_token_recognised_silently(self) -> None:
        """MCP-pattern tokens produce no INFO message."""
        errors, passes = validate_allowed_tools(
            "Bash mcp__server__tool"
        )
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(info_errors, [])

    def test_mcp_mixed_case_recognised_silently(self) -> None:
        """MCP names with mixed case (real Atlassian-style) recognised."""
        errors, passes = validate_allowed_tools(
            "Bash mcp__claude_ai_Atlassian__addCommentToJiraIssue"
        )
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(info_errors, [])

    def test_pascalcase_unknown_emits_harness_shaped_info(self) -> None:
        """PascalCase tokens not in the catalog emit the harness-shaped INFO."""
        errors, passes = validate_allowed_tools("Bash MadeUpTool")
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("harness-shaped", info_errors[0])
        self.assertIn("MadeUpTool", info_errors[0])
        self.assertIn(
            "allowed_tools.catalogs.claude_code.harness_tools",
            info_errors[0],
        )

    def test_pascalcase_with_args_treated_as_harness_shape(self) -> None:
        """PascalCase tokens with ``(...)`` args follow the same tier."""
        errors, passes = validate_allowed_tools(
            "Bash(git add *) MadeUp(arg)"
        )
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        # ``Bash(git add *)`` strips to ``Bash`` which is in the catalog,
        # so only ``MadeUp(arg)`` should be flagged as harness-shaped.
        # No fully-unrecognized INFO should fire — ``add``, ``*)`` etc.
        # never appear because the paren-strip happens before split().
        self.assertEqual(len(info_errors), 1)
        self.assertIn("harness-shaped", info_errors[0])
        self.assertIn("MadeUp", info_errors[0])

    def test_restricted_arg_form_recognised_as_single_tool(self) -> None:
        """Bare ``Bash(git add *)`` survives whitespace tokenization.

        Regression: previously ``value.split()`` ran before the
        paren-strip, shredding the input into ``Bash(git``, ``add``,
        ``*)`` and emitting a noisy "unrecognized tools" INFO.  After
        the fix, the entire restricted form collapses to one ``Bash``
        token and recognition is silent.
        """
        errors, passes = validate_allowed_tools("Bash(git add *)")
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(info_errors, [])
        # Should also count as 1 tool, not 3.
        count_passes = [p for p in passes if "1 tools" in p]
        self.assertEqual(len(count_passes), 1)

    def test_multiple_restricted_forms_silent(self) -> None:
        """``Bash(git:*) Bash(jq:*) Read`` is silent — all paren-stripped."""
        errors, passes = validate_allowed_tools(
            "Bash(git:*) Bash(jq:*) Read"
        )
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(info_errors, [])

    def test_paren_only_value_warns(self) -> None:
        """Paren-only inputs (``(Bash)``, ``(garbage)``) emit a WARN.

        Regression: the pre-split paren-strip can collapse a non-empty
        value to zero tokens — without this guard the function would
        silently report "0 tools recognized" for an obviously broken
        input.
        """
        for value in ("(Bash)", "(garbage)", "()"):
            with self.subTest(value=value):
                errors, passes = validate_allowed_tools(value)
                warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
                self.assertEqual(len(warn_errors), 1)
                self.assertIn("no tool names", warn_errors[0])
                self.assertEqual(passes, [])

    def test_fully_unknown_garbage_emits_unrecognized_info(self) -> None:
        """Lowercase/dashed tokens not in any catalog emit the bare INFO."""
        errors, passes = validate_allowed_tools("Bash some-garbage")
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        unrecognized = [
            e for e in info_errors if "unrecognized" in e
        ]
        self.assertEqual(len(unrecognized), 1)
        self.assertIn("some-garbage", unrecognized[0])

    def test_harness_and_unknown_buckets_emit_separate_info(self) -> None:
        """Mixed unknowns split into the two tiers, one INFO each."""
        errors, passes = validate_allowed_tools(
            "Bash MadeUpTool some-garbage"
        )
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 2)
        harness_shaped = [
            e for e in info_errors if "harness-shaped" in e
        ]
        unrecognized = [
            e for e in info_errors if "unrecognized" in e
        ]
        self.assertEqual(len(harness_shaped), 1)
        self.assertEqual(len(unrecognized), 1)
        self.assertIn("MadeUpTool", harness_shaped[0])
        self.assertIn("some-garbage", unrecognized[0])

    def test_known_pascalcase_does_not_trigger_harness_shaped(self) -> None:
        """Tokens already in harness_tools stay silent."""
        errors, passes = validate_allowed_tools("Bash Read Write")
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(info_errors, [])


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

    def _build_no_close_match_key(self) -> str:
        """Return a deterministic key that yields no close matches.

        Starts from a long sentinel (whose ``difflib.SequenceMatcher``
        similarity ratio against any short known key is well below
        ``cutoff``) and extends it if a future ``KNOWN_FRONTMATTER_KEYS``
        expansion ever causes a hit, so the no-match test paths always
        execute instead of being silently skipped when the fixture
        drifts.
        """
        candidate = "frontmatter-no-close-match-sentinel"
        known_keys = sorted(KNOWN_FRONTMATTER_KEYS)
        for attempt in range(128):
            if not difflib.get_close_matches(
                candidate,
                known_keys,
                n=FRONTMATTER_SUGGEST_MAX_MATCHES,
                cutoff=FRONTMATTER_SUGGEST_CUTOFF,
            ):
                return candidate
            candidate = f"{candidate}-{attempt}"
        self.fail(
            "Could not derive a frontmatter key with no close matches; "
            "adjust the sentinel used by _build_no_close_match_key()."
        )

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

    def test_close_match_suggests_known_key(self) -> None:
        """A near-miss like 'descripton' suggests 'description'."""
        fm = {"descripton": "oops"}
        errors, passes = validate_known_keys(fm)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("descripton (did you mean: description?)", info_errors[0])

    def test_no_close_match_omits_suggestion(self) -> None:
        """An unrecognized key with no close match has no suggestion text."""
        no_match_key = self._build_no_close_match_key()
        fm = {no_match_key: "value"}
        errors, passes = validate_known_keys(fm)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertNotIn("did you mean", info_errors[0])

    def test_multiple_close_matches_listed(self) -> None:
        """Up to three close matches appear in the suggestion.

        The expected list is re-computed via the live ``difflib`` using
        the same pinned parameters as ``validate_known_keys()`` rather
        than hardcoding any particular score — if a future Python tweaks
        the ratio math, the test still checks the same contract.
        """
        fm = {"nam": "value"}
        errors, passes = validate_known_keys(fm)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        expected = difflib.get_close_matches(
            "nam",
            sorted(KNOWN_FRONTMATTER_KEYS),
            n=FRONTMATTER_SUGGEST_MAX_MATCHES,
            cutoff=FRONTMATTER_SUGGEST_CUTOFF,
        )
        self.assertGreaterEqual(len(expected), 1)
        self.assertIn(
            f"nam (did you mean: {', '.join(expected)}?)", info_errors[0]
        )

    def test_mixed_hit_and_miss_keys(self) -> None:
        """Unknown keys render with suggestions only where matches exist."""
        no_match_key = self._build_no_close_match_key()
        fm = {"descripton": "oops", no_match_key: "value"}
        errors, passes = validate_known_keys(fm)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("descripton (did you mean: description?)", info_errors[0])
        # Intent: the no-match key must not carry a "(did you mean"
        # parenthetical — assert on that intent directly rather than
        # on positional context within the sorted list.
        self.assertNotIn(f"{no_match_key} (did you mean", info_errors[0])
        self.assertIn(no_match_key, info_errors[0])


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
                "description: Validates data files and generates reports. "
                "Triggers when a data file is touched.\n"
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
        # ``yaml_conformance`` slot (always present, zero sentinel when
        # checks did not run) and ``path_resolution`` block (rule_name
        # + documentation_path so consumers can navigate to the rule).
        self.assertEqual(
            set(data.keys()),
            {
                "tool", "path", "type", "success", "summary",
                "errors", "version", "yaml_conformance",
                "path_resolution",
            },
        )
        # Block contents must be populated — guards against silently
        # degrading to ``{}`` if a future loader stops threading the
        # constants into the JSON shape.
        self.assertEqual(
            data["path_resolution"]["rule_name"], "path-resolution",
        )
        self.assertIn(
            "path-resolution.md",
            data["path_resolution"]["documentation_path"],
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


class CheckProseYamlIntegrationTests(unittest.TestCase):
    """End-to-end behaviour of ``--check-prose-yaml`` and ``--foundry-self``."""

    def _make_skill(self, tmpdir: str, *, body: str = "") -> str:
        skill = os.path.join(tmpdir, "demo")
        os.makedirs(skill)
        from helpers import write_skill_md
        write_skill_md(
            skill,
            name="demo",
            description="Demo skill for prose-YAML integration tests.",
            body=f"# Demo\n{body}",
        )
        return skill

    def test_flag_off_ignores_divergent_fence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill = self._make_skill(
                tmpdir, body="\n```yaml\nbad: *alias\n```\n"
            )
            proc = _run([skill], cwd=REPO_ROOT)
        # With the flag off the divergent fence does not surface.
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("alias indicator", proc.stdout)

    def test_flag_on_surfaces_divergent_fence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill = self._make_skill(
                tmpdir, body="\n```yaml\nbad: *alias\n```\n"
            )
            proc = _run([skill, "--check-prose-yaml"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("alias indicator", proc.stdout)
        self.assertIn("block 1", proc.stdout)

    def test_foundry_self_implies_prose_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill = self._make_skill(
                tmpdir, body="\n```yaml\nbad: *alias\n```\n"
            )
            proc = _run([skill, "--foundry-self"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("alias indicator", proc.stdout)

    def test_warn_only_fence_is_zero_exit(self) -> None:
        # Anchor in value position is WARN, not FAIL — exit code stays 0.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill = self._make_skill(
                tmpdir, body="\n```yaml\nkey: &alias trailing\n```\n"
            )
            proc = _run([skill, "--check-prose-yaml"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("anchor name consumed", proc.stdout)

    def test_scope_excludes_top_level_extras(self) -> None:
        # CLAUDE.md, CHANGELOG.md, and assets/* are out of scope; a
        # divergent fence in those files must not surface.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill = self._make_skill(tmpdir, body="\n# clean body\n")
            for rel in ("CLAUDE.md", "CHANGELOG.md", "assets/note.md"):
                path = os.path.join(skill, rel)
                os.makedirs(os.path.dirname(path) or skill, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("```yaml\nout: *alias\n```\n")
            proc = _run(
                [skill, "--check-prose-yaml", "--json"], cwd=REPO_ROOT
            )
            data = json.loads(proc.stdout)
        slot = data["yaml_conformance"]["doc_snippets"]
        self.assertEqual(slot["checked"], 0)
        self.assertEqual(slot["findings"], [])

    def test_capability_mode_surfaces_noop_info(self) -> None:
        # --check-prose-yaml under --capability is a no-op by scope,
        # but the caller must be told instead of silently dropping the
        # request.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill = self._make_skill(tmpdir)
            cap_dir = os.path.join(skill, "capabilities", "foo")
            os.makedirs(cap_dir)
            with open(os.path.join(cap_dir, "capability.md"), "w", encoding="utf-8") as fh:
                fh.write("# Foo\n")
            proc = _run(
                [cap_dir, "--capability", "--check-prose-yaml"],
                cwd=REPO_ROOT,
            )
        self.assertIn("--check-prose-yaml has no effect", proc.stdout)

    def test_scope_includes_capabilities_and_references(self) -> None:
        # The three globs are SKILL.md + capabilities/**/*.md +
        # references/**/*.md.  Plant a fence in each of the latter two.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill = self._make_skill(tmpdir)
            for rel in (
                "capabilities/foo/capability.md",
                "references/bar.md",
            ):
                path = os.path.join(skill, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("```yaml\nbad: *alias\n```\n")
            proc = _run(
                [skill, "--check-prose-yaml", "--json"], cwd=REPO_ROOT
            )
            data = json.loads(proc.stdout)
        files = {
            f["file"]
            for f in data["yaml_conformance"]["doc_snippets"]["findings"]
        }
        self.assertEqual(
            files,
            {"capabilities/foo/capability.md", "references/bar.md"},
        )


# ===================================================================
# Integration: validate_skill + tool coherence rule wiring
# ===================================================================


class ValidateSkillToolCoherenceIntegrationTests(unittest.TestCase):
    """End-to-end tests for the coherence rule wired through validate_skill."""

    def test_skill_with_bash_fence_and_no_bash_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(
                skill_dir,
                body="# Demo\n\n```bash\necho hi\n```\n",
            )
            errors, _ = validate_skill(skill_dir)
            fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
            bash_fails = [e for e in fail_errors if "Bash" in e]
            self.assertEqual(len(bash_fails), 1)

    def test_skill_with_scripts_dir_and_no_bash_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(skill_dir, body="# Demo\n")
            write_text(
                os.path.join(skill_dir, "scripts", "noop.sh"),
                "#!/usr/bin/env bash\n",
            )
            errors, _ = validate_skill(skill_dir)
            warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
            bash_warns = [
                e for e in warn_errors
                if "scripts/" in e and "Bash" in e
            ]
            self.assertEqual(len(bash_warns), 1)

    def test_skill_declaring_bash_passes_coherence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(
                skill_dir,
                allowed_tools="Bash",
                body="# Demo\n\n```bash\necho hi\n```\n",
            )
            write_text(
                os.path.join(skill_dir, "scripts", "noop.sh"),
                "#!/usr/bin/env bash\n",
            )
            errors, _ = validate_skill(skill_dir)
            bash_findings = [
                e for e in errors
                if e.startswith(LEVEL_FAIL) and "Bash" in e
            ]
            self.assertEqual(bash_findings, [])
            warn_bash = [
                e for e in errors
                if e.startswith(LEVEL_WARN)
                and "scripts/" in e and "Bash" in e
            ]
            self.assertEqual(warn_bash, [])

    def test_capability_mode_skips_coherence_rule(self) -> None:
        # Coherence is owned by the skill-level invocation — running
        # ``validate_skill`` against a single capability must not emit
        # tool-coherence findings even when the capability body has
        # a bash fence and the parent skill does not declare Bash.
        # Otherwise auditing one capability would surface findings
        # scoped to the whole sibling tree.
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(skill_dir, body="# Skill\n")
            write_capability_md(
                skill_dir, "demo",
                body="# Capability\n\n```bash\necho hi\n```\n",
            )
            cap_dir = os.path.join(skill_dir, "capabilities", "demo")
            errors, _ = validate_skill(cap_dir, is_capability=True)
            coherence_findings = [
                e for e in errors
                if "Bash" in e and (
                    "fence" in e or "scripts/" in e
                )
            ]
            self.assertEqual(coherence_findings, [])

    def test_skill_level_invocation_catches_capability_fence(self) -> None:
        # The complement to the test above: the skill-level run is
        # the one that owns coherence, so it must surface a FAIL when
        # a capability body has a bash fence and Bash is undeclared.
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(skill_dir, body="# Skill\n")
            write_capability_md(
                skill_dir, "demo",
                body="# Capability\n\n```bash\necho hi\n```\n",
            )
            errors, _ = validate_skill(skill_dir)
            bash_fails = [
                e for e in errors
                if e.startswith(LEVEL_FAIL) and "Bash" in e
                and "fence" in e
            ]
            self.assertEqual(len(bash_fails), 1)
            # Coherence FAIL paths are normalized to forward slashes
            # for cross-platform deterministic output, so assert
            # against the POSIX form rather than os.path.join (which
            # produces backslashes on Windows).
            self.assertIn(
                "capabilities/demo/capability.md",
                bash_fails[0],
            )

    def test_yaml_list_form_in_frontmatter_works_through_pipeline(self) -> None:
        # The wider validator currently expects a string and will WARN
        # via validate_allowed_tools, but the coherence rule must still
        # honour the list form for satisfaction lookup.
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            content = (
                "---\n"
                "name: demo-skill\n"
                "description: A skill that lists tools as a YAML list.\n"
                "allowed-tools:\n"
                "  - Bash\n"
                "  - Read\n"
                "---\n\n"
                "# Demo\n\n```bash\necho hi\n```\n"
            )
            write_text(os.path.join(skill_dir, "SKILL.md"), content)
            errors, _ = validate_skill(skill_dir)
            bash_fails = [
                e for e in errors
                if e.startswith(LEVEL_FAIL) and "Bash" in e
                and "fence" in e
            ]
            self.assertEqual(bash_fails, [])

    def test_explicit_empty_allowed_tools_skips_coherence_end_to_end(self) -> None:
        # Docs-only skill: ``allowed-tools: ""`` plus a bash fence in
        # the body must produce no FAIL/WARN from either
        # ``validate_allowed_tools`` or ``validate_tool_coherence``
        # when the full ``validate_skill`` pipeline runs.
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(
                skill_dir,
                allowed_tools='""',
                body="# Demo\n\n```bash\necho example\n```\n",
            )
            errors, _ = validate_skill(skill_dir)
            offenders = [
                e for e in errors
                if (e.startswith(LEVEL_FAIL) or e.startswith(LEVEL_WARN))
                and ("Bash" in e or "allowed-tools" in e)
            ]
            self.assertEqual(offenders, [])


class ValidateSkillOrphanReferencesIntegrationTests(unittest.TestCase):
    """End-to-end tests for the orphan-reference rule wired through validate_skill."""

    def test_orphan_under_references_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(skill_dir, body="# Demo\n")
            write_text(
                os.path.join(skill_dir, "references", "stale.md"),
                "# Stale\n",
            )
            errors, _ = validate_skill(skill_dir)
            orphan = [e for e in errors if "is unreferenced" in e]
            self.assertEqual(len(orphan), 1)
            self.assertIn("references/stale.md", orphan[0])

    def test_capability_mode_skips_orphan_check(self) -> None:
        # Running --capability targets a single capability.md, not a
        # full skill tree.  The orphan rule's scope is the whole
        # skill, so the capability invocation must not emit the
        # finding (the parent SKILL.md invocation owns the check).
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(skill_dir, body="# Demo\n")
            cap_dir = os.path.join(skill_dir, "capabilities", "deploy")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Deploy\n",
            )
            write_text(
                os.path.join(skill_dir, "references", "stale.md"),
                "# Stale\n",
            )
            errors, _ = validate_skill(cap_dir, is_capability=True)
            orphan = [e for e in errors if "is unreferenced" in e]
            self.assertEqual(orphan, [])

    def test_capability_mode_does_not_flag_capability_local_references(self) -> None:
        # Pin against the regression Codex flagged: in capability mode,
        # ``skill_path`` is the capability directory, not the skill
        # root.  If the orphan rule were run against the capability
        # directory it would treat ``capabilities/<name>/references/``
        # as a top-level ``references/`` tree without an entry point
        # and emit false orphan WARNs for every legitimate capability-
        # local reference file.  Guard: the rule must be skipped
        # entirely in capability mode.
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(
                skill_dir,
                body="See [deploy](capabilities/deploy/capability.md).\n",
            )
            cap_dir = os.path.join(skill_dir, "capabilities", "deploy")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Deploy\n\nSee [steps](references/steps.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "references", "steps.md"),
                "# Steps\n",
            )
            errors, _ = validate_skill(cap_dir, is_capability=True)
            orphan = [e for e in errors if "is unreferenced" in e]
            self.assertEqual(
                orphan, [],
                "capability-mode validation must not run the orphan "
                "rule — running it against the capability directory "
                f"falsely flags legitimate capability-local references; got: {orphan!r}",
            )

    def test_orphan_prefix_uses_absolute_basename(self) -> None:
        # When validate_skill is invoked with ``.`` (or a path that
        # ends in a separator), ``os.path.basename`` would otherwise
        # return ``"."`` / ``""`` and the orphan WARN would render
        # ``./references/stale.md`` instead of ``demo-skill/references/stale.md``.
        # Pin the abspath-normalization fix that makes the CLI label
        # stable, mirroring the same fix in audit_skill_system.
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(skill_dir, body="# Demo\n")
            write_text(
                os.path.join(skill_dir, "references", "stale.md"),
                "# Stale\n",
            )
            cwd = os.getcwd()
            try:
                os.chdir(skill_dir)
                errors, _ = validate_skill(".")
            finally:
                os.chdir(cwd)
            orphan = [e for e in errors if "is unreferenced" in e]
            self.assertEqual(len(orphan), 1)
            self.assertIn("demo-skill/references/stale.md", orphan[0])
            self.assertNotIn(
                "./references/stale.md", orphan[0],
                "prefix must use the abspath basename, not the literal "
                f"'.' from the input path; got: {orphan[0]!r}",
            )

    def test_clean_skill_passes_orphan_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(
                skill_dir,
                body="See [guide](references/guide.md).\n",
            )
            write_text(
                os.path.join(skill_dir, "references", "guide.md"),
                "# Guide\n",
            )
            errors, passes = validate_skill(skill_dir)
            orphan = [e for e in errors if "is unreferenced" in e]
            self.assertEqual(orphan, [])
            self.assertTrue(
                any("orphan references" in p for p in passes),
                f"expected an orphan-references pass, got {passes!r}",
            )

    def test_router_table_cell_typo_is_caught_by_check_references(self) -> None:
        # Router-table cells are bare paths, not markdown links, so
        # the body reference regex misses them.  validate_body must
        # plumb include_router_table=True into _check_references when
        # validating SKILL.md so a misspelled router-table cell
        # surfaces as a [spec] broken-link WARN — without this, the
        # reachability walker would be the only signal, forcing the
        # orphan rule to surface walk warnings to remain trustworthy.
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(
                skill_dir,
                body=(
                    "# Demo\n\n"
                    "## Capabilities\n\n"
                    "| Capability | Trigger | Path |\n"
                    "|---|---|---|\n"
                    "| deploy | when deploying | "
                    "capabilities/typo/capability.md |\n"
                ),
            )
            cap_dir = os.path.join(skill_dir, "capabilities", "deploy")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Deploy\n",
            )
            errors, _ = validate_skill(skill_dir)
            broken = [
                e for e in errors
                if "does not exist" in e
                and "capabilities/typo/capability.md" in e
            ]
            self.assertEqual(
                len(broken), 1,
                "misspelled router-table cell must produce a "
                f"[path-resolution] broken-link WARN; got: {errors!r}",
            )
            self.assertIn("[path-resolution]", broken[0])

    def test_broken_link_is_not_double_reported(self) -> None:
        # validate_skill_references already emits broken-reference
        # findings against the per-skill graph.  find_orphan_references
        # walks the same graph, so without gating it would re-emit
        # equivalent diagnostics and double the WARN count.  Pin the
        # gating: a single broken intra-skill link produces exactly
        # one "does not exist" finding from the path-resolution rule,
        # and zero from the orphan rule's reachability walk.
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = os.path.join(tmp, "demo-skill")
            write_skill_md(
                skill_dir,
                body="See [missing](references/missing.md).\n",
            )
            errors, _ = validate_skill(skill_dir)
            broken = [e for e in errors if "does not exist" in e]
            self.assertEqual(
                len(broken), 1,
                f"expected exactly one broken-link finding, got {broken!r}",
            )
            self.assertIn("[path-resolution]", broken[0])


class CapabilityAggregationIntegrationTests(unittest.TestCase):
    """End-to-end checks that validate_skill wires the bottom-up
    aggregation rule and the skill-only-fields INFO redirect."""

    def test_aggregation_fails_when_capability_declares_unparented_tool(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, allowed_tools="Read")
            write_capability_md(
                skill_dir, "alpha", allowed_tools="Bash Read",
            )
            errors, _ = validate_skill(skill_dir)
        agg_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL)
            and "capabilities/alpha/capability.md" in e
        ]
        self.assertEqual(len(agg_fails), 1)
        self.assertIn("Bash", agg_fails[0])

    def test_skill_only_field_in_capability_emits_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, allowed_tools="Read")
            write_capability_md(
                skill_dir, "alpha",
                extra_frontmatter="license: MIT\n",
            )
            errors, _ = validate_skill(skill_dir)
        infos = [
            e for e in errors
            if e.startswith(LEVEL_INFO)
            and "'license'" in e
            and "capabilities/alpha/capability.md" in e
        ]
        self.assertEqual(len(infos), 1)

    def test_capability_mode_runs_skill_only_fields_check(self) -> None:
        # ``--capability`` invocation should still emit the INFO
        # redirect when the capability frontmatter declares a
        # skill-only field.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, allowed_tools="Read")
            write_capability_md(
                skill_dir, "alpha",
                extra_frontmatter="metadata:\n  version: 1.0.0\n",
            )
            cap_dir = os.path.join(skill_dir, "capabilities", "alpha")
            errors, _ = validate_skill(cap_dir, is_capability=True)
        infos = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "'metadata.version'" in e
        ]
        self.assertEqual(len(infos), 1)

    def test_capability_mode_skips_aggregation(self) -> None:
        # In --capability mode, aggregation is owned by the parent
        # invocation; running on a single capability must not emit
        # aggregation FAILs.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, allowed_tools="Read")
            write_capability_md(
                skill_dir, "alpha", allowed_tools="Bash",
            )
            cap_dir = os.path.join(skill_dir, "capabilities", "alpha")
            errors, _ = validate_skill(cap_dir, is_capability=True)
        agg_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL)
            and "missing from SKILL.md 'allowed-tools'" in e
        ]
        self.assertEqual(agg_fails, [])

    def test_skill_only_field_in_nested_capability_emits_info(self) -> None:
        # The skill-only-fields walk must be recursive — matches the
        # aggregation rule and the audit's discovery walk.  A nested
        # capability declaring license still triggers the redirect.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            nested = os.path.join(
                skill_dir,
                "capabilities", "outer", "capabilities", "inner",
            )
            os.makedirs(nested)
            with open(
                os.path.join(nested, "capability.md"), "w", encoding="utf-8",
            ) as fh:
                fh.write("---\nlicense: MIT\n---\n\n# Inner\n")
            errors, _ = validate_skill(skill_dir)
        infos = [
            e for e in errors
            if e.startswith(LEVEL_INFO)
            and "'license'" in e
            and "capabilities/outer/capabilities/inner/capability.md" in e
        ]
        self.assertEqual(len(infos), 1)

    def test_clean_aggregation_passes_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, allowed_tools="Bash Read Write")
            write_capability_md(
                skill_dir, "alpha", allowed_tools="Bash Read",
            )
            write_capability_md(
                skill_dir, "beta", allowed_tools="Read Write",
            )
            errors, _ = validate_skill(skill_dir)
        agg_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL)
            and "missing from SKILL.md 'allowed-tools'" in e
        ]
        agg_infos = [
            e for e in errors
            if e.startswith(LEVEL_INFO)
            and "is not declared by any capability" in e
        ]
        self.assertEqual(agg_fails, [])
        self.assertEqual(agg_infos, [])

    def test_capability_malformed_allowed_tools_value_emits_warn(
        self,
    ) -> None:
        # Capability ``allowed-tools`` is now authoritative input for
        # aggregation/coherence; the parent run must surface
        # type/catalog diagnostics on it (e.g., a mapping value)
        # instead of silently treating it as zero tokens.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, allowed_tools="Bash")
            write_capability_md(
                skill_dir, "alpha",
                extra_frontmatter="allowed-tools:\n  bash: true\n",
            )
            errors, _ = validate_skill(skill_dir)
        type_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN)
            and "allowed-tools" in e
            and "should be a space-separated string" in e
            and "capabilities/alpha/capability.md" in e
        ]
        self.assertEqual(len(type_warns), 1)

    def test_unreadable_capability_frontmatter_emits_fail(self) -> None:
        # ``validate_skill.py <parent>`` is the canonical skill-level
        # validator; an unreadable capability frontmatter must surface
        # as a FAIL there, not silently disappear into the aggregation
        # / skill-only-fields rules' "no contribution" handling.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir, allowed_tools="Read")
            cap_dir = os.path.join(skill_dir, "capabilities", "broken")
            os.makedirs(cap_dir)
            cap_md = os.path.join(cap_dir, "capability.md")
            with open(cap_md, "wb") as fh:
                # Invalid UTF-8 forces UnicodeDecodeError on read.
                fh.write(b"---\n\xff\xfe\n---\n# Cap\n")
            errors, _ = validate_skill(skill_dir)
        parse_fails = [
            e for e in errors
            if e.startswith(LEVEL_FAIL)
            and "frontmatter parse error" in e
            and "capabilities/broken/capability.md" in e
        ]
        self.assertEqual(len(parse_fails), 1)


if __name__ == "__main__":
    unittest.main()
