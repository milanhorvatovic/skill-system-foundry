"""Tests for ``lib/name_fixer.py`` — the safe name-frontmatter auto-fix
engine folded into ``validate_skill.py --fix`` / ``--fix --apply``.

Safe fixes: lowercase the ``name``, replace underscores with hyphens,
replace spaces with hyphens.  Ambiguous problems (directory mismatch,
over-length description) are reported as "manual fix needed" and never
auto-applied.  The rewrite is a minimal, line-targeted textual
replacement of the single frontmatter ``name:`` line — the rest of the
file is preserved byte-for-byte.

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
        new_name, applied, manual = compute_name_fix("MySkill", "myskill")
        self.assertEqual(new_name, "myskill")
        self.assertTrue(any("lowercased" in f for f in applied))
        self.assertTrue(all(f.startswith(LEVEL_INFO) for f in applied))
        self.assertEqual(manual, [])

    def test_underscore_reported_and_applied(self) -> None:
        new_name, applied, manual = compute_name_fix("my_skill", "my-skill")
        self.assertEqual(new_name, "my-skill")
        self.assertTrue(any("underscores" in f for f in applied))
        self.assertEqual(manual, [])

    def test_space_reported_and_applied(self) -> None:
        new_name, applied, _manual = compute_name_fix("my skill", "my-skill")
        self.assertEqual(new_name, "my-skill")
        self.assertTrue(any("spaces" in f for f in applied))

    def test_combined_reports_each_fix(self) -> None:
        new_name, applied, _manual = compute_name_fix(
            "My_Skill Name", "my-skill-name",
        )
        self.assertEqual(new_name, "my-skill-name")
        self.assertEqual(len(applied), 3)

    def test_noop_returns_none(self) -> None:
        new_name, applied, manual = compute_name_fix("my-skill", "my-skill")
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertEqual(manual, [])

    def test_dir_mismatch_is_manual_after_fix(self) -> None:
        # Fixing casing produces 'my-skill' but the directory is
        # 'other-dir' — the mismatch is reported against the FIXED name.
        new_name, applied, manual = compute_name_fix("My-Skill", "other-dir")
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
        new_name, applied, manual = compute_name_fix("my-skill", "other-dir")
        self.assertIsNone(new_name)
        self.assertEqual(applied, [])
        self.assertEqual(len(manual), 1)
        self.assertIn("my-skill", manual[0])

    def test_empty_name_no_fix_no_manual(self) -> None:
        new_name, applied, manual = compute_name_fix("", "demo")
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
            new_name, applied, manual, errors = compute_name_fix_plan(path)
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
            new_name, applied, manual, _errors = compute_name_fix_plan(path)
            self.assertEqual(new_name, "my-skill-name")
            self.assertEqual(len(applied), 3)
            self.assertEqual(manual, [])

    def test_noop_returns_none_new_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: my-skill\ndescription: A demo.")
            new_name, applied, manual, errors = compute_name_fix_plan(path)
            self.assertIsNone(new_name)
            self.assertEqual(applied, [])
            self.assertEqual(manual, [])
            self.assertEqual(errors, [])

    def test_dir_mismatch_is_manual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "expected-dir")
            os.makedirs(sdir)
            path = _write_skill(sdir, "name: actual-name\ndescription: A demo.")
            new_name, applied, manual, errors = compute_name_fix_plan(path)
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
            _new_name, _applied, manual, _errors = compute_name_fix_plan(path)
            self.assertTrue(any("description" in f for f in manual))

    def test_folded_description_block_no_false_over_length(self) -> None:
        # A folded ``description: >`` block must not be flagged as
        # over-length by the inline extractor — the marker line itself
        # is short, and the fixer leaves folded blocks to the validator.
        long_body = "x" * (MAX_DESCRIPTION_CHARS + 50)
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(
                sdir,
                f"name: my-skill\ndescription: >\n  {long_body}",
            )
            _new_name, _applied, manual, _errors = compute_name_fix_plan(path)
            self.assertEqual(manual, [])

    def test_missing_file_is_error_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")  # never created
            new_name, _applied, _manual, errors = compute_name_fix_plan(path)
            self.assertIsNone(new_name)
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith(LEVEL_FAIL))

    def test_no_frontmatter_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = os.path.join(sdir, "SKILL.md")
            write_text(path, "# No frontmatter here\n")
            new_name, _applied, _manual, errors = compute_name_fix_plan(path)
            self.assertIsNone(new_name)
            self.assertTrue(any("frontmatter" in f for f in errors))

    def test_no_name_key_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdir = os.path.join(tmp, "my-skill")
            os.makedirs(sdir)
            path = _write_skill(sdir, "description: A demo with no name key.")
            new_name, _applied, _manual, errors = compute_name_fix_plan(path)
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

            def _open(file, mode="r", *args, **kwargs):
                if file == path and "w" in mode:
                    raise OSError("disk full")
                return real_open(file, mode, *args, **kwargs)

            with mock.patch("builtins.open", _open):
                modified, errors = write_name_fix(path, "my-skill")
            self.assertFalse(modified)
            self.assertTrue(any("cannot write" in f for f in errors))


if __name__ == "__main__":
    unittest.main()
