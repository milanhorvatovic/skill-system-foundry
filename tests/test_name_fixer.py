"""Tests for ``lib/name_fixer.py`` — the safe name-frontmatter auto-fix
engine folded into ``validate_skill.py --fix`` / ``--fix --apply``.

Safe fixes: lowercase the ``name``, replace underscores with hyphens,
replace in-value whitespace (spaces and tabs) with hyphens.  Ambiguous
problems (directory mismatch, over-length description) are reported as
"manual fix needed" and never auto-applied.  The rewrite is a minimal,
line-targeted textual replacement of the single frontmatter ``name:``
line — the rest of the file is preserved byte-for-byte.

The module splits the work into a preview half (``compute_name_fix_plan``
— reads and computes, never writes) and an apply half (``write_name_fix``
— performs the single-line in-place rewrite), mirroring the
preview/apply structure of the path-resolution rewriter.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_REPO_ROOT, "skill-system-foundry", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from lib.name_fixer import (  # noqa: E402
    compute_description_manual_finding,
    compute_name_fix,
    compute_name_fix_plan,
    compute_safe_name,
    rewrite_name_line,
    write_name_fix,
)
from lib.constants import (  # noqa: E402
    LEVEL_FAIL,
    LEVEL_INFO,
    MAX_DESCRIPTION_CHARS,
)

from helpers import write_text  # noqa: E402


# ===================================================================
# compute_safe_name
# ===================================================================


class ComputeSafeNameTests(unittest.TestCase):
    """The pure transform applies the three safe fixes only."""

    def test_lowercases(self) -> None:
        self.assertEqual(compute_safe_name("MySkill"), "myskill")

    def test_underscores_to_hyphens(self) -> None:
        self.assertEqual(compute_safe_name("my_skill"), "my-skill")

    def test_spaces_to_hyphens(self) -> None:
        self.assertEqual(compute_safe_name("my skill"), "my-skill")

    def test_combined(self) -> None:
        self.assertEqual(compute_safe_name("My_Skill Name"), "my-skill-name")

    def test_tabs_to_hyphens(self) -> None:
        self.assertEqual(compute_safe_name("my\tskill"), "my-skill")

    def test_already_valid_unchanged(self) -> None:
        self.assertEqual(compute_safe_name("my-skill"), "my-skill")


# ===================================================================
# compute_name_fix
# ===================================================================


class ComputeNameFixTests(unittest.TestCase):
    """Findings and the corrected value for a single skill."""

    def test_lowercase_reported_and_applied(self) -> None:
        new_name, applied, manual, _owned = compute_name_fix("MySkill", "myskill")
        self.assertEqual(new_name, "myskill")
        self.assertTrue(any("lowercased" in f for f in applied))
        self.assertTrue(all(f.startswith(LEVEL_INFO) for f in applied))
        self.assertEqual(manual, [])

    def test_underscore_reported_and_applied(self) -> None:
        new_name, applied, manual, _owned = compute_name_fix("my_skill", "my-skill")
        self.assertEqual(new_name, "my-skill")
        self.assertTrue(any("underscores" in f for f in applied))
        self.assertEqual(manual, [])

    def test_space_reported_and_applied(self) -> None:
        new_name, applied, _manual, _owned = compute_name_fix("my skill", "my-skill")
        self.assertEqual(new_name, "my-skill")
        self.assertTrue(any("whitespace" in f for f in applied))

    def test_combined_reports_each_fix(self) -> None:
        new_name, applied, _manual, _owned = compute_name_fix(
            "My_Skill Name", "my-skill-name",
        )
        self.assertEqual(new_name, "my-skill-name")
        self.assertEqual(len(applied), 3)

    def test_noop_returns_none(self) -> None:
        new_name, applied, manual, _owned = compute_name_fix("my-skill", "my-skill")
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertEqual(manual, [])

    def test_dir_mismatch_is_manual_after_fix(self) -> None:
        # Fixing casing produces 'my-skill' but the directory is
        # 'other-dir' — the mismatch is reported against the FIXED name.
        new_name, applied, manual, _owned = compute_name_fix("My-Skill", "other-dir")
        self.assertEqual(new_name, "my-skill")
        self.assertTrue(applied)
        self.assertEqual(len(manual), 1)
        self.assertTrue(manual[0].startswith(LEVEL_FAIL))
        self.assertIn("manual fix needed", manual[0])
        self.assertIn("my-skill", manual[0])
        self.assertIn("other-dir", manual[0])

    def test_dir_mismatch_without_safe_fix_uses_current_name(self) -> None:
        # No safe fix applies, but the (already valid) name differs from
        # the directory — still a manual finding, against the live name.
        new_name, applied, manual, _owned = compute_name_fix("my-skill", "other-dir")
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertEqual(len(manual), 1)
        self.assertIn("my-skill", manual[0])

    def test_empty_name_no_fix_no_manual(self) -> None:
        new_name, applied, manual, _owned = compute_name_fix("", "demo")
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertEqual(manual, [])


# ===================================================================
# compute_description_manual_finding
# ===================================================================


class ComputeDescriptionManualFindingTests(unittest.TestCase):
    def test_within_limit_no_finding(self) -> None:
        self.assertEqual(compute_description_manual_finding("short"), [])

    def test_over_limit_is_manual_fail(self) -> None:
        long_desc = "x" * (MAX_DESCRIPTION_CHARS + 1)
        findings = compute_description_manual_finding(long_desc)
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith(LEVEL_FAIL))
        self.assertIn("manual fix needed", findings[0])
        self.assertIn("description", findings[0])

    def test_empty_no_finding(self) -> None:
        self.assertEqual(compute_description_manual_finding(""), [])


# ===================================================================
# rewrite_name_line
# ===================================================================


class RewriteNameLineTests(unittest.TestCase):
    """Only the frontmatter name: value changes; everything else is kept."""

    def test_rewrites_only_frontmatter_name(self) -> None:
        content = (
            "---\n"
            "name: My_Skill\n"
            "description: A demo.\n"
            "---\n"
            "\n"
            "# Body\n"
            "Prose mentioning name: keep-this verbatim.\n"
        )
        result = rewrite_name_line(content, "my-skill")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("name: my-skill\n", result)
        # Body mention untouched.
        self.assertIn("name: keep-this verbatim.", result)
        # Description untouched.
        self.assertIn("description: A demo.\n", result)

    def test_preserves_surrounding_bytes_exactly(self) -> None:
        content = (
            "---\n"
            "name: My_Skill\n"
            "description: A demo.\n"
            "metadata:\n"
            "  version: 1.0.0\n"
            "---\n"
            "\n"
            "# Body content stays.\n"
        )
        result = rewrite_name_line(content, "my-skill")
        assert result is not None
        # The only difference between input and output is the name value.
        self.assertEqual(result, content.replace("My_Skill", "my-skill", 1))

    def test_preserves_trailing_whitespace_and_spacing(self) -> None:
        content = "---\nname:    My_Skill   \ndescription: d\n---\n\nbody\n"
        result = rewrite_name_line(content, "my-skill")
        assert result is not None
        # Prefix spacing (4 spaces) and trailing spaces preserved.
        self.assertIn("name:    my-skill   \n", result)

    def test_returns_none_when_no_frontmatter(self) -> None:
        self.assertIsNone(rewrite_name_line("# No frontmatter\n", "x"))

    def test_returns_none_when_no_name_key(self) -> None:
        content = "---\ndescription: d\n---\n\nbody\n"
        self.assertIsNone(rewrite_name_line(content, "x"))

    def test_does_not_match_indented_name_in_block_scalar(self) -> None:
        # A folded description carrying an indented 'name:' must not be
        # mistaken for the frontmatter name field.
        content = (
            "---\n"
            "description: >\n"
            "  This mentions name: foo inside the description.\n"
            "name: My_Skill\n"
            "---\n"
            "\n"
            "body\n"
        )
        result = rewrite_name_line(content, "my-skill")
        assert result is not None
        self.assertIn("name: my-skill\n", result)
        self.assertIn("mentions name: foo inside", result)


# ===================================================================
# compute_name_fix_plan (preview half — reads, never writes)
# ===================================================================


def _write_skill(skill_dir: str, frontmatter: str, body: str = "# Body\n") -> str:
    """Write a SKILL.md with a raw *frontmatter* block; return its path."""
    content = f"---\n{frontmatter}\n---\n\n{body}"
    path = os.path.join(skill_dir, "SKILL.md")
    write_text(path, content)
    return path


class ComputeNameFixPlanTests(unittest.TestCase):
    """The preview half computes the plan and never touches disk."""

    def test_lowercase_planned_no_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "myskill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: MySkill\ndescription: A demo.")
            with open(path, "r", encoding="utf-8") as f:
                before = f.read()
            stat_before = os.stat(path)
            new_name, applied, manual, errors, _owned = compute_name_fix_plan(path)
            self.assertEqual(new_name, "myskill")
            self.assertTrue(applied)
            self.assertEqual(manual, [])
            self.assertEqual(errors, [])
            # Preview must not write — bytes and mtime unchanged.
            with open(path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), before)
            self.assertEqual(os.stat(path).st_mtime_ns, stat_before.st_mtime_ns)

    def test_combined_plans_each_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill-name")
            os.makedirs(sdir)
            path = _write_skill(
                sdir, "name: My_Skill Name\ndescription: A demo.",
            )
            new_name, applied, manual, _errors, _owned = compute_name_fix_plan(path)
            self.assertEqual(new_name, "my-skill-name")
            self.assertEqual(len(applied), 3)
            self.assertEqual(manual, [])

    def test_noop_returns_none_new_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: my-skill\ndescription: A demo.")
            new_name, applied, manual, errors, _owned = compute_name_fix_plan(path)
            self.assertIsNone(new_name)
            self.assertEqual(applied, [])
            self.assertEqual(manual, [])
            self.assertEqual(errors, [])

    def test_dir_mismatch_is_manual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "expected-dir")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: actual-name\ndescription: A demo.")
            new_name, applied, manual, errors, _owned = compute_name_fix_plan(path)
            self.assertIsNone(new_name)
            self.assertEqual(applied, [])
            self.assertEqual(len(manual), 1)
            self.assertIn("does not match directory", manual[0])
            self.assertEqual(errors, [])

    def test_over_length_description_is_manual(self) -> None:
        long_desc = "x" * (MAX_DESCRIPTION_CHARS + 5)
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(
                sdir, f"name: my-skill\ndescription: {long_desc}",
            )
            _new_name, _applied, manual, _errors, _owned = compute_name_fix_plan(path)
            self.assertTrue(any("description" in f for f in manual))

    def test_folded_description_block_over_length_is_manual(self) -> None:
        # A folded ``description: >`` block whose assembled text
        # exceeds the limit must surface as a manual finding the same
        # way an inline over-length description does — the planner
        # reads the parsed scalar, so style-of-write does not change
        # the contract.
        long_body = "x" * (MAX_DESCRIPTION_CHARS + 50)
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(
                sdir,
                f"name: my-skill\ndescription: >\n  {long_body}",
            )
            _new_name, _applied, manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertTrue(any("description" in f for f in manual))
        # The owned FAIL is the validator's exact wording so the
        # generic ``non_path_fails`` bucket does not double-report it.
        self.assertTrue(any(
            "'description' exceeds" in f for f in owned
        ))

    def test_missing_file_is_error_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")  # never created
            new_name, _applied, _manual, errors, _owned = compute_name_fix_plan(path)
            self.assertIsNone(new_name)
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith(LEVEL_FAIL))

    def test_no_frontmatter_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(path, "# No frontmatter here\n")
            new_name, _applied, _manual, errors, _owned = compute_name_fix_plan(path)
            self.assertIsNone(new_name)
            self.assertTrue(any("frontmatter" in f for f in errors))

    def test_no_name_key_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "description: A demo with no name key.")
            new_name, _applied, _manual, errors, _owned = compute_name_fix_plan(path)
            self.assertIsNone(new_name)
            self.assertTrue(any("'name'" in f for f in errors))


# ===================================================================
# write_name_fix (apply half — performs the in-place rewrite)
# ===================================================================


class WriteNameFixTests(unittest.TestCase):
    """The apply half writes the single ``name:`` line in place."""

    def test_writes_new_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "myskill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: MySkill\ndescription: A demo.")
            modified, errors = write_name_fix(path, "myskill")
            self.assertTrue(modified)
            self.assertEqual(errors, [])
            with open(path, "r", encoding="utf-8") as f:
                self.assertIn("name: myskill\n", f.read())

    def test_body_preserved_exactly(self) -> None:
        body = (
            "# Demo Skill\n\n"
            "This body has name: should-not-change and other prose.\n\n"
            "```yaml\nname: also_not_changed\n```\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(
                sdir, "name: My_Skill\ndescription: A demo.", body=body,
            )
            with open(path, "r", encoding="utf-8") as f:
                before = f.read()
            modified, _errors = write_name_fix(path, "my-skill")
            self.assertTrue(modified)
            with open(path, "r", encoding="utf-8") as f:
                after = f.read()
            # The only change is the single frontmatter name value.
            self.assertEqual(after, before.replace("My_Skill", "my-skill", 1))
            self.assertIn("name: should-not-change", after)
            self.assertIn("name: also_not_changed", after)

    def test_identical_value_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: my-skill\ndescription: A demo.")
            stat_before = os.stat(path)
            with open(path, "r", encoding="utf-8") as f:
                before = f.read()
            # Writing the value already on disk is a defensive no-op.
            modified, errors = write_name_fix(path, "my-skill")
            self.assertFalse(modified)
            self.assertEqual(errors, [])
            with open(path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), before)
            self.assertEqual(os.stat(path).st_mtime_ns, stat_before.st_mtime_ns)

    def test_unlocatable_name_line_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            # No name: key in the frontmatter — rewrite cannot locate it.
            path = _write_skill(sdir, "description: A demo with no name key.")
            modified, errors = write_name_fix(path, "my-skill")
            self.assertFalse(modified)
            self.assertTrue(any("name:" in f for f in errors))

    def test_read_error_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")  # never created
            modified, errors = write_name_fix(path, "my-skill")
            self.assertFalse(modified)
            self.assertTrue(any("cannot read" in f for f in errors))

    def test_write_error_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: My_Skill\ndescription: A demo.")
            real_open = open

            def _open(
                file: str,
                mode: str = "r",
                *args: object,
                **kwargs: object,
            ) -> object:
                if file == path and "w" in mode:
                    raise OSError("disk full")
                return real_open(file, mode, *args, **kwargs)

            with mock.patch("builtins.open", _open):
                modified, errors = write_name_fix(path, "my-skill")
            self.assertFalse(modified)
            self.assertTrue(any("cannot write" in f for f in errors))


# ===================================================================
# Ownership semantics — the planner must own exactly the validator
# FAIL strings its fix resolves, never the unrelated ones (Codex F-1
# / Copilot C-1).
# ===================================================================


class OwnedFailsTests(unittest.TestCase):
    """``compute_name_fix_plan`` returns the exact ``validate_name``
    FAIL strings it takes ownership of so the ``validate_skill.py``
    driver can suppress *only* those — never an unrelated name FAIL.
    """

    def test_owns_uppercase_underscore_and_format(self) -> None:
        # ``Demo_Skill`` FAILs on uppercase, underscore, and (because
        # both push the value off ``RE_NAME_FORMAT``) invalid format.
        # The fix produces ``demo-skill`` which passes — all three
        # FAILs are resolved and therefore owned.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "demo-skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: Demo_Skill\ndescription: A demo.")
            _new_name, _applied, _manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        owned_text = "\n".join(owned)
        self.assertIn("uppercase", owned_text)
        self.assertIn("underscores", owned_text)
        self.assertIn("invalid format", owned_text)

    def test_does_not_own_empty_name_fail(self) -> None:
        # ``name:`` empty → safe fixer cannot fix it.  The validator's
        # "field is empty" FAIL must flow through the caller's generic
        # bucket; the planner owns nothing.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "demo-skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: \ndescription: A demo.")
            new_name, _applied, _manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(owned, [])

    def test_does_not_own_consecutive_hyphen_fail(self) -> None:
        # ``my--skill`` is invalid (consecutive hyphens, invalid
        # format) and no safe transform produces a clean result —
        # the safe transforms are all no-ops on a lowercase
        # hyphen-only value, so the fix would be a no-op and the
        # planner takes no ownership.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my--skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: my--skill\ndescription: A demo.")
            new_name, _applied, _manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(owned, [])

    def test_does_not_own_overlong_name_fail(self) -> None:
        long_name = "a" * 200
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, long_name)
            os.makedirs(sdir)
            path = _write_skill(
                sdir, f"name: {long_name}\ndescription: A demo.",
            )
            new_name, _applied, _manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(owned, [])

    def test_owns_dir_mismatch_when_manual_surfaces_it(self) -> None:
        # The dir-mismatch FAIL is owned only when the planner emits a
        # manual finding for it (i.e. the planner is taking
        # responsibility for surfacing the issue).
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "expected-dir")
            os.makedirs(sdir)
            path = _write_skill(
                sdir, "name: Actual_Name\ndescription: A demo.",
            )
            _new_name, _applied, manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertTrue(any("does not match directory" in f for f in manual))
        self.assertTrue(
            any("does not match directory name" in f for f in owned)
        )

    def test_owns_inline_overlong_description_fail(self) -> None:
        long_desc = "x" * (MAX_DESCRIPTION_CHARS + 5)
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(
                sdir, f"name: my-skill\ndescription: {long_desc}",
            )
            _new_name, _applied, manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertTrue(any("description" in f for f in manual))
        self.assertTrue(
            any("'description' exceeds" in f for f in owned)
        )

    def test_consecutive_hyphen_residual_refuses_fix(self) -> None:
        # ``my__skill`` would normalize to ``my--skill`` (consecutive
        # hyphens) — the candidate still violates the spec, so the
        # planner refuses to propose the fix.  Original FAILs flow
        # through the caller.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my--skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: my__skill\ndescription: A demo.")
            new_name, applied, manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertTrue(any(
            "cannot be safely normalized" in f for f in manual
        ))
        self.assertEqual(owned, [])

    def test_compute_name_fix_returns_owned(self) -> None:
        # Direct check on the lower-level entry point: the same
        # ownership contract holds without reading from disk.
        new_name, _applied, _manual, owned = compute_name_fix(
            "My_Skill", "my-skill",
        )
        self.assertEqual(new_name, "my-skill")
        owned_text = "\n".join(owned)
        self.assertIn("uppercase", owned_text)
        self.assertIn("underscores", owned_text)


# ===================================================================
# YAML-aware value extraction — quoted scalars and inline comments
# (Codex F-2 / Copilot C-4).
# ===================================================================


class ParsedNameValueTests(unittest.TestCase):
    """The fixer uses the parsed YAML scalar so quoted values and
    inline comments are recognised without their syntax characters
    being treated as part of the value.
    """

    def test_quoted_value_is_extracted_via_parser(self) -> None:
        # ``name: "MySkill"`` — the validator sees ``MySkill`` (parser
        # unquotes), so the planner must too.  A naive raw extractor
        # would compute against ``"MySkill"`` (literal quotes) and
        # report a false directory mismatch against ``myskill``.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "myskill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname: \"MySkill\"\ndescription: A demo.\n---\n\n# Body\n",
            )
            new_name, _applied, manual, _errors, _owned = (
                compute_name_fix_plan(path)
            )
        # Manual finding fires because the line carries a quoted scalar
        # the minimal rewriter cannot preserve — but the *value*
        # extracted (for any other reasoning) is the parsed
        # ``MySkill``, not the literal ``"MySkill"``.  No false
        # dir-mismatch against ``myskill`` should appear.
        self.assertIsNone(new_name)
        self.assertTrue(any("quoted scalar" in f for f in manual))
        self.assertFalse(any(
            "does not match directory" in f for f in manual
        ))

    def test_inline_comment_blocks_rewrite(self) -> None:
        # ``name: MySkill  # legacy`` — value parses to ``MySkill`` but
        # the raw line carries an inline comment the minimal rewriter
        # would strip.  Refuse to propose a fix.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "myskill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname: MySkill  # legacy\ndescription: A demo.\n---\n\n# Body\n",
            )
            new_name, applied, manual, _errors, _owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertTrue(any("inline '#' comment" in f for f in manual))

    def test_hash_inside_plain_scalar_does_not_block_rewrite(self) -> None:
        # ``name: foo#bar`` — YAML parses this as the literal value
        # ``foo#bar`` (no space before ``#``), so the inline-comment
        # detector must NOT flag it.  The rewrite proceeds normally.
        # ``foo#bar`` itself FAILs RE_NAME_FORMAT, so the residual gate
        # refuses the fix — but that is the *content* failing, not the
        # rewrite block path.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "foobar")
            os.makedirs(sdir)
            path = _write_skill(
                sdir, "name: foo#bar\ndescription: A demo.",
            )
            _new_name, _applied, manual, _errors, _owned = (
                compute_name_fix_plan(path)
            )
        # No 'inline comment' manual finding — the ``#`` is inside the
        # plain scalar, not a comment marker.
        self.assertFalse(any("inline '#' comment" in f for f in manual))

    def test_rewrite_line_returns_none_on_quoted(self) -> None:
        # The line-level rewriter refuses to touch a quoted value
        # directly, defending the byte-for-byte contract even if the
        # planner ever delegated without its own gate.
        content = (
            "---\nname: \"MySkill\"\ndescription: A demo.\n---\n\nbody\n"
        )
        self.assertIsNone(rewrite_name_line(content, "myskill"))

    def test_rewrite_line_returns_none_on_inline_comment(self) -> None:
        content = (
            "---\nname: MySkill  # legacy\ndescription: A demo.\n---\n\nbody\n"
        )
        self.assertIsNone(rewrite_name_line(content, "myskill"))


# ===================================================================
# Duplicate ``name:`` keys — Codex + Copilot follow-up.
# ``parse_yaml_subset`` resolves to the *last* mapping entry but a
# line-targeted rewrite would touch the *first*, so the planner refuses
# the fix outright rather than rewrite the wrong line and exit clean.
# ===================================================================


class DuplicateNameKeyTests(unittest.TestCase):
    """Frontmatter with duplicate ``name:`` keys is refused by both the
    planner and the line rewriter — the parser and the rewriter would
    target different lines, which would leave the effective ``name``
    unchanged while the planner owned the validator FAILs.
    """

    def test_plan_refuses_duplicate_name_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            # parse_yaml_subset reads the last ``name:`` value
            # (``Last_Name``), but ``_RE_NAME_LINE.search`` would
            # target the first physical line (``First_Name``) — the
            # planner must refuse instead of rewriting the wrong line.
            write_text(
                path,
                "---\nname: First_Name\nname: Last_Name\ndescription: A demo.\n---\n\n# Body\n",
            )
            with open(path, encoding="utf-8") as f:
                before = f.read()
            new_name, applied, _manual, errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertTrue(any(
            "multiple 'name:' keys" in f for f in errors
        ), msg=f"errors={errors!r}")
        # No ownership — the validator FAILs flow through unchanged so
        # the caller's exit gate fires.
        self.assertEqual(owned, [])

    def test_rewrite_line_returns_none_on_duplicate_keys(self) -> None:
        # Defense-in-depth: the line rewriter itself refuses to touch a
        # frontmatter block carrying duplicate ``name:`` lines.
        content = (
            "---\nname: First_Name\nname: Last_Name\ndescription: d\n---\n\nbody\n"
        )
        self.assertIsNone(rewrite_name_line(content, "any-value"))


# ===================================================================
# Folded / literal block scalar descriptions — Copilot follow-up.
# The planner uses the parsed scalar so the over-length manual finding
# fires regardless of scalar style, keeping the ``--fix`` help text's
# "manual fix needed" claim honest.
# ===================================================================


class FoldedDescriptionTests(unittest.TestCase):
    def test_literal_block_overlong_description_is_manual(self) -> None:
        # ``description: |-`` literal-style block scalar over the limit
        # must surface as manual the same as inline / folded forms.
        long_body = "x" * (MAX_DESCRIPTION_CHARS + 5)
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(
                sdir,
                f"name: my-skill\ndescription: |-\n  {long_body}",
            )
            _new_name, _applied, manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertTrue(any(
            "manual fix needed" in f and "description" in f for f in manual
        ))
        self.assertTrue(any(
            "'description' exceeds" in f for f in owned
        ))

    def test_folded_description_within_limit_no_manual(self) -> None:
        # Folded but within the limit — no manual finding, planner is
        # silent on description.
        short_body = "x" * 50
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(
                sdir,
                f"name: my-skill\ndescription: >\n  {short_body}",
            )
            _new_name, _applied, manual, _errors, _owned = (
                compute_name_fix_plan(path)
            )
        self.assertFalse(any("description" in f for f in manual))


# ===================================================================
# Quoted / inline-comment name lines that are *already valid* must
# not fail the fix run — the refusal is only meaningful when the
# planner would actually try to rewrite (Codex follow-up F-5).
# ===================================================================


class QuotedValidNameTests(unittest.TestCase):
    def test_quoted_already_valid_name_is_silent(self) -> None:
        # ``name: "my-skill"`` in dir ``my-skill`` — the parsed value
        # is valid, no rewrite is needed, so the quote-syntax guard
        # must not fire.  ``manual`` stays empty and the planner
        # silently reports nothing to do.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname: \"my-skill\"\ndescription: A demo.\n---\n\n# Body\n",
            )
            new_name, applied, manual, errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertEqual(manual, [])
        self.assertEqual(errors, [])
        self.assertEqual(owned, [])

    def test_inline_comment_already_valid_name_is_silent(self) -> None:
        # ``name: my-skill  # note`` — same scenario via inline comment.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname: my-skill  # note\ndescription: A demo.\n---\n\n# Body\n",
            )
            new_name, applied, manual, errors, _owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertEqual(manual, [])
        self.assertEqual(errors, [])

    def test_quoted_invalid_name_still_refuses(self) -> None:
        # ``name: "My_Skill"`` — quoted but the parsed value FAILs
        # validate_name; the planner refuses to propose a write,
        # surrenders ownership, and the validator FAILs flow through.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname: \"My_Skill\"\ndescription: A demo.\n---\n\n# Body\n",
            )
            new_name, applied, manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertTrue(any("quoted scalar" in f for f in manual))
        self.assertEqual(owned, [])


# ===================================================================
# CRLF normalization — write_name_fix writes with newline="\n", so a
# CRLF-on-disk SKILL.md is normalized to LF when any safe fix lands.
# The contract is documented in the module docstring; this test pins
# the behavior so it cannot silently drift (Copilot follow-up C-6).
# ===================================================================


class WriteCRLFNormalizationTests(unittest.TestCase):
    def test_crlf_file_is_normalized_to_lf_on_write(self) -> None:
        # Write SKILL.md with CRLF terminators, run the apply, and
        # expect the on-disk file to come back with LF terminators
        # everywhere (no surviving \r\n pairs).
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "myskill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            # Bypass write_text (which writes LF) by writing in binary
            # mode with CRLF terminators on every line.
            content_lf = (
                "---\nname: MySkill\ndescription: A demo.\n---\n\n"
                "# Body\nProse stays.\n"
            )
            with open(path, "wb") as f:
                f.write(content_lf.replace("\n", "\r\n").encode("utf-8"))
            modified, errors = write_name_fix(path, "myskill")
            with open(path, "rb") as f:
                raw = f.read()
        self.assertTrue(modified)
        self.assertEqual(errors, [])
        # The name was rewritten.
        self.assertIn(b"name: myskill\n", raw)
        # And every CRLF terminator is gone — documented LF
        # normalization per the repo-wide newline="\n" convention.
        self.assertNotIn(b"\r\n", raw)

    def test_rewrite_name_line_preserves_crlf_for_direct_callers(self) -> None:
        # ``rewrite_name_line`` operates on the supplied string —
        # direct callers must see the rewritten line's CRLF terminator
        # preserved (the regex captures ``\r?`` and the substitution
        # re-emits it).  Without that, the rewritten line would drop
        # its ``\r`` while every other line kept CRLF, producing mixed
        # line endings in the returned content even though the helper
        # documents the file's line-ending shape as preserved.  The
        # end-to-end ``write_name_fix`` path still normalizes to LF
        # via the text-mode I/O; this contract is for the line
        # rewriter in isolation (Codex follow-up F-18).
        content = (
            "---\r\nname: My_Skill\r\ndescription: A demo.\r\n"
            "---\r\n\r\n# Body\r\nProse stays.\r\n"
        )
        result = rewrite_name_line(content, "my-skill")
        self.assertIsNotNone(result)
        assert result is not None
        # The rewritten line keeps its ``\r\n`` terminator.
        self.assertIn("name: my-skill\r\n", result)
        # No bare-LF line endings were introduced — every CRLF in the
        # source survives in the output.
        bare_lf = [
            i for i, ch in enumerate(result)
            if ch == "\n" and (i == 0 or result[i - 1] != "\r")
        ]
        self.assertEqual(bare_lf, [], msg=f"bare LF at indices {bare_lf}")
        # And the rest of the file is byte-identical to the input.
        self.assertEqual(
            result, content.replace("My_Skill", "my-skill", 1),
        )


# ===================================================================
# Missing closing ``---`` delimiter — Codex follow-up F-8.  The planner
# and line rewriter must treat ``split_frontmatter`` returning
# ``(frontmatter, None)`` as a structural failure and refuse rather
# than rewrite a SKILL.md the parser cannot bound.
# ===================================================================


class MissingClosingDelimiterTests(unittest.TestCase):
    def test_plan_refuses_missing_closing_delimiter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            # Opening delimiter only — no closing ``---`` line.
            write_text(path, "---\nname: My_Skill\ndescription: d\n# body\n")
            new_name, applied, manual, errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertEqual(manual, [])
        self.assertEqual(owned, [])
        self.assertTrue(any(
            "no closing '---' delimiter" in f for f in errors
        ), msg=f"errors={errors!r}")

    def test_rewrite_line_returns_none_on_missing_closing_delimiter(self) -> None:
        # The line rewriter itself enforces the same guard so a direct
        # ``write_name_fix`` call on a malformed SKILL.md is a no-op.
        content = "---\nname: My_Skill\ndescription: d\n# body without closer\n"
        self.assertIsNone(rewrite_name_line(content, "my-skill"))


# ===================================================================
# Inline-# alignment with yaml_parser — Copilot follow-up C-8.
# ``yaml_parser._strip_inline_comment`` only flags ``#`` when preceded
# by a *space*; the detector must match so the rewriter is not
# stricter than the parser.
# ===================================================================


class InlineCommentAlignmentTests(unittest.TestCase):
    def test_tab_before_hash_is_not_a_comment_marker(self) -> None:
        # ``name: invalid\t#bar`` — yaml_parser treats the value as
        # ``invalid\t#bar`` (no comment stripped because the rule is
        # space-only).  The detector must agree, leaving the
        # comment-syntax refusal silent.  The candidate is invalid
        # regardless, so the planner refuses via the residual gate
        # (with a different manual message), but the rewriter's
        # quote/comment guard does not fire.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "invalid-bar")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname: invalid\t#bar\ndescription: d\n---\n\n# Body\n",
            )
            _new_name, _applied, manual, _errors, _owned = (
                compute_name_fix_plan(path)
            )
        # The comment-syntax manual finding must NOT fire on tab-#.
        self.assertFalse(any("inline '#' comment" in f for f in manual))


# ===================================================================
# Unusual-but-valid YAML formatting (whitespace before ``:``) must not
# fail the run when no rewrite is needed — Copilot follow-up C-10.
# Rewrite-mechanics guards only fire when ``new_name is not None``.
# ===================================================================


class UnusualButValidYAMLTests(unittest.TestCase):
    def test_space_before_colon_valid_name_is_silent(self) -> None:
        # ``name : my-skill`` (with space before colon) — valid YAML
        # mapping that ``parse_yaml_subset`` accepts, but the line
        # regex requires ``name:`` with no leading whitespace.  When
        # the parsed value is already valid (no rewrite needed) the
        # planner must stay silent rather than emit a "not on its own
        # line" error that would fail ``--fix``.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname : my-skill\ndescription: A demo.\n---\n\n# Body\n",
            )
            new_name, applied, manual, errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertEqual(manual, [])
        self.assertEqual(errors, [])
        self.assertEqual(owned, [])

    def test_space_before_colon_invalid_name_refuses_with_error(self) -> None:
        # ``name : MySkill`` — parser sees ``MySkill``, validate_name
        # FAILs.  compute_name_fix would propose ``myskill``, but the
        # line regex cannot target ``name : MySkill`` for rewrite, so
        # the planner refuses and surrenders ownership; the regular
        # validator's FAILs flow through.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "myskill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname : MySkill\ndescription: A demo.\n---\n\n# Body\n",
            )
            new_name, applied, _manual, errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertTrue(any(
            "not on its own line" in e for e in errors
        ), msg=f"errors={errors!r}")
        self.assertEqual(owned, [])


# ===================================================================
# Block scalar name values — Codex follow-up F-12.  The rewriter only
# touches the ``name:`` header line; a block-scalar value (``>`` /
# ``|`` and chomping variants) carries its content on subsequent
# indented lines and would be corrupted by a header-only rewrite.
# ===================================================================


class BlockScalarNameTests(unittest.TestCase):
    def test_folded_name_value_refuses_apply(self) -> None:
        # ``name: >`` with an indented folded body — parse_yaml_subset
        # assembles "MySkill", planner would propose "myskill", but
        # rewriting only the header line would leave the indented body
        # behind as stray YAML.  The block-scalar guard refuses.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "myskill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname: >\n  MySkill\ndescription: A demo.\n---\n\n# Body\n",
            )
            new_name, applied, manual, errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertTrue(any(
            "block-scalar header" in f for f in manual
        ), msg=f"manual={manual!r}")
        self.assertEqual(owned, [])

    def test_literal_name_value_refuses_apply(self) -> None:
        # ``name: |-`` literal-style block scalar — same refusal.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "myskill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname: |-\n  My_Skill\ndescription: A demo.\n---\n\n# Body\n",
            )
            new_name, _applied, manual, _errors, _owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertTrue(any(
            "block-scalar header" in f for f in manual
        ))

    def test_rewrite_line_returns_none_on_block_scalar_header(self) -> None:
        # The line rewriter itself refuses to touch a block-scalar
        # header line — defense-in-depth for any future caller.
        content = (
            "---\nname: >\n  MySkill\ndescription: d\n---\n\nbody\n"
        )
        self.assertIsNone(rewrite_name_line(content, "myskill"))


# ===================================================================
# Mixed-form duplicate name keys — Codex follow-up F-13.
# parse_yaml_subset accepts both ``name:`` and ``name :`` (whitespace
# before the colon), so the duplicate guard must count both forms or
# a mixed-form pair would let the planner read the *last* parsed key
# while the rewriter touches the *first* strict-form key.
# ===================================================================


class MixedFormDuplicateTests(unittest.TestCase):
    def test_strict_plus_spaced_colon_is_duplicate(self) -> None:
        # ``name: First`` then ``name : Last`` — the strict regex only
        # matches the first line, so the previous guard would miss the
        # duplicate.  The relaxed-form guard catches both.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname: First_Name\nname : Last_Name\ndescription: d\n---\n\n# Body\n",
            )
            new_name, _applied, _manual, errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertTrue(any(
            "multiple 'name:' keys" in f for f in errors
        ), msg=f"errors={errors!r}")
        self.assertEqual(owned, [])

    def test_spaced_plus_strict_colon_is_duplicate(self) -> None:
        # And the reverse ordering — the parser would use ``Strict_Name``
        # but the strict regex would target ``Spaced_Name`` if the
        # duplicate check only saw the strict form.
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                "---\nname : Spaced_Name\nname: Strict_Name\ndescription: d\n---\n\n# Body\n",
            )
            new_name, _applied, _manual, errors, _owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertTrue(any(
            "multiple 'name:' keys" in f for f in errors
        ))

    def test_rewrite_line_returns_none_on_mixed_form_duplicate(self) -> None:
        content = (
            "---\nname: First_Name\nname : Last_Name\ndescription: d\n---\n\nbody\n"
        )
        self.assertIsNone(rewrite_name_line(content, "any-value"))


# ===================================================================
# Description manual on refusal paths — Codex follow-up F-17.
# Refusing a quoted / commented / block-scalar name rewrite must not
# suppress reporting of an independent over-length description; both
# are manual-fix conditions and both belong under name_fix.manual_fix_needed.
# ===================================================================


class DescriptionOnRefusalTests(unittest.TestCase):
    def test_quoted_name_refusal_still_reports_overlong_description(self) -> None:
        # ``name: "My_Skill"`` triggers the quoted-scalar refusal; the
        # description is also over-length.  Both findings must surface
        # under ``manual`` and the description FAIL must be owned so
        # the validator's copy is suppressed from ``non_path_fails``.
        long_desc = "x" * (MAX_DESCRIPTION_CHARS + 5)
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                f"---\nname: \"My_Skill\"\ndescription: {long_desc}\n---\n\n# Body\n",
            )
            new_name, applied, manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        # Both manual findings present.
        self.assertTrue(any("quoted scalar" in f for f in manual))
        self.assertTrue(any(
            "'description' exceeds" in f or "description" in f and "manual fix needed" in f
            for f in manual
        ), msg=f"manual={manual!r}")
        # Description FAIL owned (so non_path_fails does not double-report).
        self.assertTrue(any(
            "'description' exceeds" in f for f in owned
        ), msg=f"owned={owned!r}")
        # Name FAILs not owned — they flow through to non_path_fails.
        self.assertFalse(any("'name'" in f for f in owned))

    def test_block_scalar_name_refusal_still_reports_overlong_description(self) -> None:
        # Same contract for the block-scalar refusal path.
        long_desc = "x" * (MAX_DESCRIPTION_CHARS + 5)
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(
                path,
                f"---\nname: >\n  My_Skill\ndescription: {long_desc}\n---\n\n# Body\n",
            )
            _new_name, _applied, manual, _errors, owned = (
                compute_name_fix_plan(path)
            )
        self.assertTrue(any("block-scalar header" in f for f in manual))
        self.assertTrue(any(
            "'description' exceeds" in f for f in owned
        ))


if __name__ == "__main__":
    unittest.main()
