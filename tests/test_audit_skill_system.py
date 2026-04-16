"""Tests for audit_skill_system.py.

Covers check_upward_references, audit_skill_system, and the main()
CLI entry point.
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
AUDIT_SCRIPT = os.path.join(SCRIPTS_DIR, "audit_skill_system.py")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from audit_skill_system import (
    _build_parser,
    check_upward_references,
    check_role_composition,
    audit_skill_system,
    main,
)
from lib.constants import (
    LEVEL_FAIL,
    LEVEL_INFO,
    LEVEL_WARN,
    MAX_BODY_LINES,
    MAX_DESCRIPTION_CHARS,
)


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Run audit_skill_system.py with *args* in *cwd* and return the result."""
    return subprocess.run(
        [sys.executable, AUDIT_SCRIPT] + args,
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


def _write_role_md(
    role_path: str,
    *,
    skills_used_body: str = "",
) -> None:
    """Write a role markdown file at *role_path*.

    *skills_used_body* is inserted into the Skills Used section table.
    """
    content = (
        "# Test Role\n\n"
        "## Purpose\n\nTest role for auditing.\n\n"
        "## Responsibilities\n\n- Test\n\n"
        "## Allowed\n\n- Test\n\n"
        "## Forbidden\n\n- Nothing\n\n"
        "## Handoff\n\n- None\n\n"
        "## Workflow\n\nDo things.\n\n"
        "## Skills Used\n\n"
        "| Skill / Capability | Purpose in Workflow |\n"
        "|---|---|\n"
        f"{skills_used_body}\n"
        "## Interaction Pattern\n\nAsk questions.\n"
    )
    write_text(role_path, content)


def _create_valid_system(system_root: str) -> None:
    """Create a minimal valid skill system under *system_root*.

    The system contains one registered skill with valid frontmatter
    and a skills/ directory so the full audit path is exercised.
    """
    skill_dir = os.path.join(system_root, "skills", "demo-skill")
    write_skill_md(skill_dir)


def _create_system_with_manifest(
    system_root: str,
    manifest_content: str,
) -> None:
    """Create a valid skill system with a custom manifest.yaml."""
    _create_valid_system(system_root)
    write_text(os.path.join(system_root, "manifest.yaml"), manifest_content)


def _create_full_valid_system(system_root: str) -> None:
    """Create a complete valid skill system with all components.

    Includes a skill with a capability, a role composing 2+ skills,
    and a manifest — all checks pass with zero errors.
    """
    # Skill with capability
    skill_dir = os.path.join(system_root, "skills", "demo-skill")
    write_skill_md(skill_dir)
    cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
    _write_capability_md(cap_dir, body="# My Capability\n")

    # Second skill for role composition
    skill2_dir = os.path.join(system_root, "skills", "other-skill")
    write_skill_md(skill2_dir, name="other-skill", description="Another skill.")

    # Role composing 2 skills
    role_path = os.path.join(system_root, "roles", "test", "reviewer.md")
    _write_role_md(
        role_path,
        skills_used_body=(
            "| skills/demo-skill/SKILL.md | Demo skill |\n"
            "| skills/other-skill/SKILL.md | Other skill |\n"
        ),
    )

    # Manifest
    write_text(
        os.path.join(system_root, "manifest.yaml"),
        "skills:\n  demo-skill:\n    capabilities:\n      - my-cap\n"
        "  other-skill:\n",
    )


# ===================================================================
# check_upward_references
# ===================================================================


class CheckUpwardReferencesTests(unittest.TestCase):
    """Tests for the check_upward_references function."""

    def test_capability_no_upward_references_returns_empty(self) -> None:
        """A capability with no upward references returns an empty list."""
        content = "# My Capability\n\nSome instructions here.\n"
        issues = check_upward_references(content, "capability")
        self.assertEqual(issues, [])

    def test_capability_referencing_roles_returns_fail(self) -> None:
        """A capability referencing roles/ returns a FAIL."""
        content = "# My Capability\n\nSee roles/reviewer.md for details.\n"
        issues = check_upward_references(content, "capability")
        self.assertEqual(len(issues), 1)
        level, message = issues[0]
        self.assertEqual(level, LEVEL_FAIL)
        self.assertIn("roles", message)

    def test_capability_referencing_sibling_capability_returns_fail(self) -> None:
        """A capability referencing a sibling capability returns a FAIL."""
        content = "# My Capability\n\nSee ../other-cap/SKILL.md for details.\n"
        issues = check_upward_references(content, "capability")
        fail_issues = [i for i in issues if i[0] == LEVEL_FAIL]
        sibling_fails = [i for i in fail_issues if "sibling" in i[1]]
        self.assertGreaterEqual(len(sibling_fails), 1)

    def test_capability_referencing_both_roles_and_sibling_returns_two_fails(self) -> None:
        """A capability referencing both roles/ and a sibling returns two FAILs."""
        content = (
            "# My Capability\n\n"
            "See roles/reviewer.md and ../other-cap/SKILL.md for details.\n"
        )
        issues = check_upward_references(content, "capability")
        self.assertEqual(len(issues), 2)
        levels = [i[0] for i in issues]
        self.assertTrue(all(level == LEVEL_FAIL for level in levels))

    def test_skill_no_upward_references_returns_empty(self) -> None:
        """A skill with no upward references returns an empty list."""
        content = "# My Skill\n\nSome instructions here.\n"
        issues = check_upward_references(content, "skill")
        self.assertEqual(issues, [])

    def test_skill_referencing_roles_returns_fail(self) -> None:
        """A skill referencing roles/ returns a FAIL by default."""
        content = "# My Skill\n\nSee roles/reviewer.md for details.\n"
        issues = check_upward_references(content, "skill")
        self.assertEqual(len(issues), 1)
        level, message = issues[0]
        self.assertEqual(level, LEVEL_FAIL)
        self.assertIn("roles", message)

    def test_skill_referencing_roles_with_orchestration_returns_warn(self) -> None:
        """A skill referencing roles/ returns a WARN when allow_orchestration=True."""
        content = "# My Skill\n\nSee roles/reviewer.md for details.\n"
        issues = check_upward_references(
            content, "skill", allow_orchestration=True,
        )
        self.assertEqual(len(issues), 1)
        level, message = issues[0]
        self.assertEqual(level, LEVEL_WARN)
        self.assertIn("orchestration", message)

    def test_unknown_component_type_returns_empty(self) -> None:
        """An unknown component type returns an empty list."""
        content = "# Something\n\nSee roles/reviewer.md for details.\n"
        issues = check_upward_references(content, "unknown")
        self.assertEqual(issues, [])


# ===================================================================
# audit_skill_system
# ===================================================================


class AuditSkillSystemEmptyTests(unittest.TestCase):
    """Tests for audit_skill_system with empty or missing structures."""

    def test_no_skills_directory_returns_partial_audit_warning(self) -> None:
        """A system root without skills/ returns a partial audit WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        partial_warns = [e for e in warn_errors if "partial audit" in e]
        self.assertGreaterEqual(len(partial_warns), 1)

    def test_empty_skills_directory_passes(self) -> None:
        """A system root with an empty skills/ directory passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "skills"))
            errors = audit_skill_system(tmpdir, verbose=False)
        # Only expected issue: missing manifest.yaml
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])


class AuditSpecComplianceTests(unittest.TestCase):
    """Tests for spec compliance checks in audit_skill_system."""

    def test_valid_skill_passes_all_checks(self) -> None:
        """A valid skill system with one skill passes all checks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_skill_missing_frontmatter_returns_fail(self) -> None:
        """A skill without frontmatter returns a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "# Demo Skill\n\nNo frontmatter here.\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        fm_fails = [e for e in fail_errors if "frontmatter" in e]
        self.assertGreaterEqual(len(fm_fails), 1)

    def test_skill_parse_error_returns_single_fail(self) -> None:
        """A skill with a YAML parse error returns one FAIL, not cascading errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\ndescription: Demo.\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        parse_fails = [e for e in fail_errors if "parse error" in e.lower()]
        self.assertGreaterEqual(len(parse_fails), 1)
        # Must not cascade into missing-name / missing-description errors.
        name_fails = [e for e in fail_errors if "missing" in e.lower() and "name" in e.lower()]
        desc_fails = [e for e in fail_errors if "missing" in e.lower() and "description" in e.lower()]
        self.assertEqual(name_fails, [])
        self.assertEqual(desc_fails, [])

    def test_skill_missing_name_field_returns_fail(self) -> None:
        """A skill without a name field returns a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\ndescription: Validates data files.\n---\n\n# Skill\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        name_fails = [e for e in fail_errors if "name" in e.lower()]
        self.assertGreaterEqual(len(name_fails), 1)

    def test_skill_name_not_matching_directory_returns_fail(self) -> None:
        """A skill whose name does not match the directory returns a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "actual-dir")
            write_skill_md(skill_dir, name="different-name")
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        mismatch_fails = [e for e in fail_errors if "match" in e.lower()]
        self.assertGreaterEqual(len(mismatch_fails), 1)

    def test_skill_missing_description_returns_fail(self) -> None:
        """A skill without a description field returns a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n---\n\n# Skill\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        desc_fails = [e for e in fail_errors if "description" in e.lower()]
        self.assertGreaterEqual(len(desc_fails), 1)

    def test_skill_description_exceeding_max_chars_returns_fail(self) -> None:
        """A skill with a description exceeding MAX_DESCRIPTION_CHARS returns a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            long_desc = "x" * (MAX_DESCRIPTION_CHARS + 1)
            write_skill_md(skill_dir, description=long_desc)
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        desc_fails = [e for e in fail_errors if "description" in e.lower()]
        self.assertGreaterEqual(len(desc_fails), 1)
        self.assertIn(str(MAX_DESCRIPTION_CHARS), desc_fails[0])

    def test_skill_body_exceeding_max_lines_returns_warn(self) -> None:
        """A skill with a body exceeding MAX_BODY_LINES returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            long_body = "\n".join(
                f"Line {i}" for i in range(MAX_BODY_LINES + 10)
            )
            write_skill_md(skill_dir, body=long_body)
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        body_warns = [e for e in warn_errors if "body" in e.lower() or "lines" in e.lower()]
        self.assertGreaterEqual(len(body_warns), 1)


class AuditCapabilityIsolationTests(unittest.TestCase):
    """Tests for capability isolation checks in audit_skill_system."""

    def test_capability_with_full_frontmatter_returns_info(self) -> None:
        """A capability with name + description in frontmatter returns an INFO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            _write_capability_md(
                cap_dir,
                frontmatter="name: my-cap\ndescription: A capability.",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        isolation_infos = [e for e in info_errors if "frontmatter" in e.lower()]
        self.assertGreaterEqual(len(isolation_infos), 1)

    def test_capability_without_full_frontmatter_passes(self) -> None:
        """A capability without full frontmatter passes isolation check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            errors = audit_skill_system(tmpdir, verbose=False)
        info_errors = [e for e in errors if e.startswith(LEVEL_INFO)]
        isolation_infos = [e for e in info_errors if "frontmatter" in e.lower()]
        self.assertEqual(isolation_infos, [])


class AuditDependencyDirectionTests(unittest.TestCase):
    """Tests for dependency direction checks in audit_skill_system."""

    def test_capability_referencing_roles_returns_fail(self) -> None:
        """A capability referencing roles/ returns a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            _write_capability_md(
                cap_dir,
                body="# My Capability\n\nSee roles/reviewer.md for details.\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        roles_fails = [e for e in fail_errors if "roles" in e.lower()]
        self.assertGreaterEqual(len(roles_fails), 1)

    def test_skill_referencing_roles_returns_fail(self) -> None:
        """A skill referencing roles/ returns a FAIL by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(
                skill_dir,
                body="# Demo Skill\n\nSee roles/reviewer.md for details.\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        roles_fails = [e for e in fail_errors if "roles" in e.lower()]
        self.assertGreaterEqual(len(roles_fails), 1)

    def test_skill_referencing_roles_with_orchestration_returns_warn(self) -> None:
        """A skill referencing roles/ returns a WARN with allow_orchestration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(
                skill_dir,
                body="# Demo Skill\n\nSee roles/reviewer.md for details.\n",
            )
            errors = audit_skill_system(
                tmpdir, verbose=False, allow_orchestration=True,
            )
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        roles_fails = [e for e in fail_errors if "roles" in e.lower()]
        self.assertEqual(roles_fails, [])
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        roles_warns = [e for e in warn_errors if "roles" in e.lower()]
        self.assertGreaterEqual(len(roles_warns), 1)


# ===================================================================
# check_role_composition
# ===================================================================


class CheckRoleCompositionTests(unittest.TestCase):
    """Tests for the check_role_composition function."""

    def test_role_with_zero_skills_returns_warn(self) -> None:
        """A role with 0 skill references returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "empty.md")
            _write_role_md(role_path, skills_used_body="")
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 0)
        self.assertEqual(len(issues), 1)
        level, message = issues[0]
        self.assertEqual(level, LEVEL_WARN)
        self.assertIn("0", message)

    def test_role_with_one_skill_returns_warn(self) -> None:
        """A role with 1 skill reference returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "single.md")
            _write_role_md(
                role_path,
                skills_used_body="| skills/alpha/SKILL.md | Alpha skill |\n",
            )
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 1)
        self.assertEqual(len(issues), 1)
        level, message = issues[0]
        self.assertEqual(level, LEVEL_WARN)
        self.assertIn("1", message)

    def test_role_with_two_skills_passes(self) -> None:
        """A role with 2 skill references passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "two.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| skills/alpha/SKILL.md | Alpha skill |\n"
                    "| skills/beta/SKILL.md | Beta skill |\n"
                ),
            )
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 2)
        self.assertEqual(issues, [])

    def test_role_with_three_skills_passes(self) -> None:
        """A role with 3 skill references passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "three.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| skills/alpha/SKILL.md | Alpha skill |\n"
                    "| skills/beta/SKILL.md | Beta skill |\n"
                    "| skills/gamma/SKILL.md | Gamma skill |\n"
                ),
            )
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 3)
        self.assertEqual(issues, [])

    def test_role_with_capabilities_only_passes(self) -> None:
        """A role referencing 2 capabilities (no skills) passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "caps.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| skills/alpha/capabilities/cap-one/capability.md | Cap one |\n"
                    "| skills/alpha/capabilities/cap-two/capability.md | Cap two |\n"
                ),
            )
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 2)
        self.assertEqual(issues, [])

    def test_role_with_mix_of_skills_and_capabilities_passes(self) -> None:
        """A role referencing 1 skill + 1 capability passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "mixed.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| skills/alpha/SKILL.md | Alpha skill |\n"
                    "| skills/beta/capabilities/cap-one/capability.md | Cap one |\n"
                ),
            )
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 2)
        self.assertEqual(issues, [])

    def test_role_with_duplicate_references_counts_unique(self) -> None:
        """A role with duplicate references counts only unique entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "dupes.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| skills/alpha/SKILL.md | First use |\n"
                    "| skills/alpha/SKILL.md | Second use |\n"
                ),
            )
            issues, ref_count = check_role_composition(role_path)
        # Duplicate should count as 1 unique reference
        self.assertEqual(ref_count, 1)
        self.assertEqual(len(issues), 1)
        level, _ = issues[0]
        self.assertEqual(level, LEVEL_WARN)

    def test_role_with_backtick_wrapped_refs(self) -> None:
        """A role with backtick-wrapped skill paths is detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "backtick.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| `skills/alpha/SKILL.md` | Alpha skill |\n"
                    "| `skills/beta/SKILL.md` | Beta skill |\n"
                ),
            )
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 2)
        self.assertEqual(issues, [])

    def test_role_with_suffixed_filenames_not_counted(self) -> None:
        """Suffixed filenames like SKILL.mdx or capability.md.bak are not counted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "suffixed.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| skills/alpha/SKILL.mdx | Not a skill |\n"
                    "| skills/beta/SKILL.md.bak | Not a skill |\n"
                    "| skills/gamma/capabilities/cap/capability.md.bak"
                    " | Not a cap |\n"
                ),
            )
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 0)
        self.assertEqual(len(issues), 1)
        level, _ = issues[0]
        self.assertEqual(level, LEVEL_WARN)

    def test_role_without_skills_used_section_returns_warn(self) -> None:
        """A role without a Skills Used section returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "no-section.md")
            write_text(
                role_path,
                "# Test Role\n\n## Purpose\n\nTest role.\n",
            )
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 0)
        self.assertEqual(len(issues), 1)
        level, message = issues[0]
        self.assertEqual(level, LEVEL_WARN)
        self.assertIn("Skills Used", message)

    def test_template_placeholders_not_counted(self) -> None:
        """Template placeholders like skills/<domain>/SKILL.md are not counted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "roles", "test", "template.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| skills/<domain>/SKILL.md | Placeholder |\n"
                    "| skills/<other>/capabilities/<cap>/capability.md"
                    " | Placeholder |\n"
                ),
            )
            issues, ref_count = check_role_composition(role_path)
        self.assertEqual(ref_count, 0)
        self.assertEqual(len(issues), 1)
        level, _ = issues[0]
        self.assertEqual(level, LEVEL_WARN)


# ===================================================================
# audit_skill_system — Role Composition integration
# ===================================================================


class AuditRoleCompositionTests(unittest.TestCase):
    """Tests for role composition checks in audit_skill_system."""

    def test_role_with_insufficient_skills_returns_warn(self) -> None:
        """A role composing fewer than the minimum returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            role_path = os.path.join(tmpdir, "roles", "test", "bad-role.md")
            _write_role_md(
                role_path,
                skills_used_body="| skills/alpha/SKILL.md | Alpha skill |\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        composition_warns = [
            e for e in warn_errors if "composes" in e.lower()
        ]
        self.assertGreaterEqual(len(composition_warns), 1)

    def test_role_with_sufficient_skills_passes(self) -> None:
        """A role composing 2+ skills/capabilities passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            role_path = os.path.join(tmpdir, "roles", "test", "good-role.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| skills/alpha/SKILL.md | Alpha skill |\n"
                    "| skills/beta/SKILL.md | Beta skill |\n"
                ),
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        composition_warns = [
            e for e in warn_errors if "composes" in e.lower()
        ]
        self.assertEqual(composition_warns, [])

    def test_verbose_output_includes_role_composition_section(self) -> None:
        """Verbose output includes the Role Composition section header."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            role_path = os.path.join(tmpdir, "roles", "test", "good-role.md")
            _write_role_md(
                role_path,
                skills_used_body=(
                    "| skills/alpha/SKILL.md | Alpha skill |\n"
                    "| skills/beta/SKILL.md | Beta skill |\n"
                ),
            )
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            proc = _run([tmpdir, "--verbose"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("Role Composition", proc.stdout)


class AuditNestingDepthTests(unittest.TestCase):
    """Tests for nesting depth checks in audit_skill_system."""

    def test_capability_with_nested_capabilities_returns_fail(self) -> None:
        """A capability with a nested capabilities/ directory returns a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            # Create nested capabilities/ inside the capability
            nested_cap = os.path.join(cap_dir, "capabilities", "sub-cap")
            os.makedirs(nested_cap)
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        nesting_fails = [e for e in fail_errors if "nested" in e.lower()]
        self.assertGreaterEqual(len(nesting_fails), 1)

    def test_capability_without_nested_capabilities_passes(self) -> None:
        """A capability without nested capabilities/ passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        nesting_fails = [e for e in fail_errors if "nested" in e.lower()]
        self.assertEqual(nesting_fails, [])


class AuditSharedResourcesTests(unittest.TestCase):
    """Tests for shared resource usage checks in audit_skill_system."""

    def test_shared_without_capabilities_returns_warn(self) -> None:
        """A skill with shared/ but no capabilities/ returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            shared_dir = os.path.join(skill_dir, "shared")
            write_text(os.path.join(shared_dir, "data.txt"), "shared data")
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        shared_warns = [
            e for e in warn_errors
            if "shared" in e.lower() and "capabilities" in e.lower()
        ]
        self.assertGreaterEqual(len(shared_warns), 1)

    def test_shared_resource_used_by_one_capability_returns_warn(self) -> None:
        """A shared resource used by only 1 capability returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            # Create shared resource
            shared_dir = os.path.join(skill_dir, "shared")
            write_text(os.path.join(shared_dir, "data.txt"), "shared data")
            # Create two capabilities, only one references the shared file
            cap1_dir = os.path.join(skill_dir, "capabilities", "cap-one")
            _write_capability_md(
                cap1_dir,
                body="# Cap One\n\nUses shared/data.txt for processing.\n",
            )
            cap2_dir = os.path.join(skill_dir, "capabilities", "cap-two")
            _write_capability_md(
                cap2_dir,
                body="# Cap Two\n\nDoes not use shared resources.\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        shared_warns = [
            e for e in warn_errors
            if "shared" in e.lower() and "1 capabilities" in e
        ]
        self.assertGreaterEqual(len(shared_warns), 1)

    def test_shared_resource_used_by_two_capabilities_passes(self) -> None:
        """A shared resource used by 2+ capabilities passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            # Create shared resource
            shared_dir = os.path.join(skill_dir, "shared")
            write_text(os.path.join(shared_dir, "data.txt"), "shared data")
            # Create two capabilities, both reference the shared file
            cap1_dir = os.path.join(skill_dir, "capabilities", "cap-one")
            _write_capability_md(
                cap1_dir,
                body="# Cap One\n\nUses shared/data.txt for processing.\n",
            )
            cap2_dir = os.path.join(skill_dir, "capabilities", "cap-two")
            _write_capability_md(
                cap2_dir,
                body="# Cap Two\n\nAlso uses shared/data.txt here.\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        shared_warns = [
            e for e in warn_errors
            if "data.txt" in e and "shared" in e.lower()
        ]
        self.assertEqual(shared_warns, [])

    def test_shared_resource_used_by_zero_capabilities_returns_warn(self) -> None:
        """A shared resource used by 0 capabilities returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            shared_dir = os.path.join(skill_dir, "shared")
            write_text(os.path.join(shared_dir, "unused.txt"), "unused data")
            # Create a capability that does not reference the shared file
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            _write_capability_md(
                cap_dir,
                body="# My Capability\n\nNo shared references.\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        shared_warns = [
            e for e in warn_errors
            if "unused.txt" in e and "0 capabilities" in e
        ]
        self.assertGreaterEqual(len(shared_warns), 1)


class AuditCapabilityEntryNamingTests(unittest.TestCase):
    """Tests for capability entry naming checks in audit_skill_system."""

    def test_capability_with_skill_md_instead_of_capability_md_returns_fail(self) -> None:
        """A capability using SKILL.md instead of capability.md returns a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            os.makedirs(cap_dir)
            # Write SKILL.md instead of capability.md
            write_text(
                os.path.join(cap_dir, "SKILL.md"),
                "# My Capability\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        naming_fails = [
            e for e in fail_errors
            if "SKILL.md" in e and "capability.md" in e
        ]
        self.assertGreaterEqual(len(naming_fails), 1)

    def test_capability_without_capability_md_returns_warn(self) -> None:
        """A capability directory without capability.md returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            os.makedirs(cap_dir)
            # Write some other file, but not capability.md or SKILL.md
            write_text(os.path.join(cap_dir, "notes.md"), "# Notes\n")
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        naming_warns = [
            e for e in warn_errors
            if "capability.md" in e and "entry file" in e.lower()
        ]
        self.assertGreaterEqual(len(naming_warns), 1)

    def test_capability_with_correct_capability_md_passes(self) -> None:
        """A capability with capability.md passes the naming check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            errors = audit_skill_system(tmpdir, verbose=False)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        naming_fails = [
            e for e in fail_errors
            if "capability.md" in e or "SKILL.md" in e
        ]
        self.assertEqual(naming_fails, [])


class AuditManifestTests(unittest.TestCase):
    """Tests for manifest checks in audit_skill_system."""

    def test_missing_manifest_returns_warn(self) -> None:
        """Missing manifest.yaml returns a WARN when skills/ exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            # No manifest.yaml created
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        manifest_warns = [e for e in warn_errors if "manifest" in e.lower()]
        self.assertGreaterEqual(len(manifest_warns), 1)

    def test_manifest_with_nonexistent_skill_returns_warn(self) -> None:
        """A manifest declaring a non-existent skill returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_system_with_manifest(
                tmpdir,
                "skills:\n  nonexistent-skill:\n    capabilities:\n      - cap-one\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        skill_warns = [
            e for e in warn_errors
            if "nonexistent-skill" in e and "not exist" in e.lower()
        ]
        self.assertGreaterEqual(len(skill_warns), 1)

    def test_manifest_with_nonexistent_capability_returns_warn(self) -> None:
        """A manifest declaring a non-existent capability returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_system_with_manifest(
                tmpdir,
                "skills:\n  demo-skill:\n    capabilities:\n      - nonexistent-cap\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        cap_warns = [
            e for e in warn_errors
            if "nonexistent-cap" in e and "not exist" in e.lower()
        ]
        self.assertGreaterEqual(len(cap_warns), 1)

    def test_invalid_manifest_yaml_returns_warn(self) -> None:
        """A manifest that triggers a parse exception returns a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "skills:\n  demo-skill:\n",
            )
            # Mock parse_yaml_subset to raise ValueError, simulating
            # a parse failure in the manifest processing path.
            with mock.patch(
                "audit_skill_system.parse_yaml_subset",
                side_effect=ValueError("mock parse error"),
            ):
                errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        parse_warns = [
            e for e in warn_errors
            if "manifest" in e.lower() and "parse" in e.lower()
        ]
        self.assertGreaterEqual(len(parse_warns), 1)

    def test_valid_manifest_passes(self) -> None:
        """A valid manifest with existing skills passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_system_with_manifest(
                tmpdir,
                "skills:\n  demo-skill:\n    capabilities:\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        manifest_warns = [e for e in warn_errors if "manifest" in e.lower()]
        self.assertEqual(manifest_warns, [])

    def test_manifest_skipped_without_skills_directory(self) -> None:
        """Manifest check is skipped when there is no skills/ directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # No skills/ directory, but manifest exists
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "skills:\n  nonexistent:\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        # Should have partial audit warning but no manifest-specific warnings
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        manifest_warns = [
            e for e in warn_errors
            if "manifest" in e.lower() and "not exist" in e.lower()
        ]
        self.assertEqual(manifest_warns, [])


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

    def test_parser_accepts_positional_system_root(self) -> None:
        """Parser accepts a single positional system_root argument."""
        parser = _build_parser()
        args = parser.parse_args(["/path/to/system"])
        self.assertEqual(args.system_root, "/path/to/system")

    def test_parser_defaults_are_false(self) -> None:
        """All optional flags default to False."""
        parser = _build_parser()
        args = parser.parse_args(["/path"])
        self.assertFalse(args.verbose)
        self.assertFalse(args.allow_orchestration)
        self.assertFalse(args.json_output)

    def test_parser_accepts_all_flags(self) -> None:
        """Parser accepts all optional flags together."""
        parser = _build_parser()
        args = parser.parse_args([
            "/path", "--verbose", "--allow-orchestration", "--json",
        ])
        self.assertTrue(args.verbose)
        self.assertTrue(args.allow_orchestration)
        self.assertTrue(args.json_output)

    def test_parser_rejects_unknown_flag(self) -> None:
        """Parser exits on unrecognised flags."""
        parser = _build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["/path", "--bogus"])

    def test_parser_rejects_missing_positional(self) -> None:
        """Parser exits when no positional argument is provided."""
        parser = _build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_audit_returns_errors_list(self) -> None:
        """audit_skill_system returns a list of error strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        self.assertIsInstance(errors, list)


class MainCLITests(unittest.TestCase):
    """Tests for the main() CLI entry point via subprocess."""

    def test_valid_system_exits_zero(self) -> None:
        """A valid skill system exits with code 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            # Create manifest so no warnings about missing manifest
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            proc = _run([tmpdir], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("passed", proc.stdout.lower())

    def test_invalid_system_exits_one(self) -> None:
        """A system with FAIL errors exits with code 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a skill without frontmatter — triggers FAIL
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "# Demo Skill\n\nNo frontmatter.\n",
            )
            proc = _run([tmpdir], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)

    def test_verbose_flag_prints_detailed_output(self) -> None:
        """The --verbose flag prints detailed output with section headers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            proc = _run([tmpdir, "--verbose"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        # Verbose output should include section headers
        self.assertIn("Spec Compliance", proc.stdout)
        self.assertIn("Dependency Direction", proc.stdout)

    def test_allow_orchestration_flag_downgrades_role_refs(self) -> None:
        """The --allow-orchestration flag downgrades skill->role refs to WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(
                skill_dir,
                body="# Demo Skill\n\nSee roles/reviewer.md for details.\n",
            )
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            # Without --allow-orchestration, should FAIL (exit 1)
            proc_fail = _run([tmpdir], cwd=REPO_ROOT)
            self.assertEqual(
                proc_fail.returncode, 1,
                msg=proc_fail.stdout + proc_fail.stderr,
            )
            # With --allow-orchestration, should WARN only (exit 0)
            proc_warn = _run(
                [tmpdir, "--allow-orchestration"], cwd=REPO_ROOT,
            )
            self.assertEqual(
                proc_warn.returncode, 0,
                msg=proc_warn.stdout + proc_warn.stderr,
            )

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

    def test_nonexistent_path_prints_error_and_exits_one(self) -> None:
        """A nonexistent path prints an error and exits with code 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gone = os.path.join(tmpdir, "does-not-exist")
        proc = _run([gone], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not a directory", proc.stdout.lower())

    def test_warns_only_exits_zero(self) -> None:
        """A system with only WARN errors (no FAIL) exits with code 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            # Missing manifest triggers WARN, not FAIL
            proc = _run([tmpdir], cwd=REPO_ROOT)
        # WARN-only should exit 0
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

    def test_orchestration_mode_message_printed(self) -> None:
        """The --allow-orchestration flag prints an orchestration mode message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            proc = _run(
                [tmpdir, "--allow-orchestration"], cwd=REPO_ROOT,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("orchestration", proc.stdout.lower())


# ===================================================================
# audit_skill_system — Verbose branch coverage
# ===================================================================


class AuditVerboseBranchTests(unittest.TestCase):
    """Tests for verbose=True branches in audit_skill_system()."""

    def test_verbose_valid_system_prints_all_sections_and_passes(self) -> None:
        """A fully valid system with verbose=True prints all section headers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_full_valid_system(tmpdir)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                errors = audit_skill_system(tmpdir, verbose=True)
        output = stdout.getvalue()
        # All section headers must appear
        for section in [
            "Spec Compliance",
            "Capability Isolation",
            "Dependency Direction",
            "Nesting Depth",
            "Shared Resources",
            "Capability Entry Naming",
            "Manifest",
        ]:
            self.assertIn(section, output)
        # Checkmark pass lines
        self.assertIn("\u2713", output)
        # Found counts
        self.assertIn("Found:", output)
        # No FAIL errors
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_verbose_no_skills_dir_prints_manifest_skipped(self) -> None:
        """With no skills/ directory, verbose manifest section prints skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                audit_skill_system(tmpdir, verbose=True)
        self.assertIn("skipped", stdout.getvalue())

    def test_verbose_manifest_no_skills_section(self) -> None:
        """A manifest without a skills key prints 'no skills section'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            write_text(
                os.path.join(tmpdir, "manifest.yaml"),
                "name: test-system\n",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                audit_skill_system(tmpdir, verbose=True)
        self.assertIn("no skills section", stdout.getvalue())

    def test_verbose_manifest_content_validated(self) -> None:
        """A valid manifest with skills section prints 'content validated'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_full_valid_system(tmpdir)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                audit_skill_system(tmpdir, verbose=True)
        self.assertIn("content validated", stdout.getvalue())


# ===================================================================
# audit_skill_system — Additional branch coverage
# ===================================================================


class AuditAdditionalBranchTests(unittest.TestCase):
    """Tests for specific untested branches in audit_skill_system()."""

    def test_non_directory_in_capabilities_is_skipped(self) -> None:
        """A file (not directory) inside capabilities/ is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            cap_base = os.path.join(skill_dir, "capabilities")
            os.makedirs(cap_base, exist_ok=True)
            # Create a file (not a directory) inside capabilities/
            write_text(os.path.join(cap_base, "stray-file.txt"), "not a cap")
            # Also a valid capability so the loop runs
            cap_dir = os.path.join(cap_base, "my-cap")
            _write_capability_md(cap_dir, body="# My Capability\n")
            errors = audit_skill_system(tmpdir, verbose=False)
        # No error about the stray file — it is silently skipped
        stray_errors = [e for e in errors if "stray-file" in e]
        self.assertEqual(stray_errors, [])

    def test_shared_resource_in_nested_subdirectory(self) -> None:
        """Shared resources in nested subdirectories are walked and checked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_skill_md(skill_dir)
            # Nested shared directory
            nested_shared = os.path.join(skill_dir, "shared", "sub")
            write_text(
                os.path.join(nested_shared, "deep.txt"), "deep data",
            )
            cap_dir = os.path.join(skill_dir, "capabilities", "my-cap")
            _write_capability_md(
                cap_dir,
                body="# My Capability\n\nUses shared/sub/deep.txt here.\n",
            )
            cap2_dir = os.path.join(skill_dir, "capabilities", "other")
            _write_capability_md(
                cap2_dir, body="# Other\n\nNo shared refs.\n",
            )
            errors = audit_skill_system(tmpdir, verbose=False)
        # deep.txt used by 1 capability → WARN
        deep_warns = [e for e in errors if "deep.txt" in e and "WARN" in e]
        self.assertGreaterEqual(len(deep_warns), 1)
        # Check that the warning reflects a single user count (trailing space
        # prevents false matches on "10", "12", etc.)
        self.assertIn("used by 1 ", deep_warns[0])


# ===================================================================
# main() — In-process tests
# ===================================================================


class MainFunctionInProcessTests(unittest.TestCase):
    """In-process tests for main() to contribute to coverage."""

    def test_no_args_prints_docstring_and_exits_1(self) -> None:
        """No arguments prints the module docstring and exits 1."""
        stdout = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["audit_skill_system.py"]),
            contextlib.redirect_stdout(stdout),
        ):
            with self.assertRaises(SystemExit) as cm:
                main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("Usage:", stdout.getvalue())

    def test_invalid_dir_human_mode(self) -> None:
        """Non-directory path in human mode prints error and exits 1."""
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_path = os.path.join(tmpdir, "does-not-exist")
            with (
                mock.patch.object(
                    sys, "argv",
                    ["audit_skill_system.py", invalid_path],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                with self.assertRaises(SystemExit) as cm:
                    main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("not a directory", stdout.getvalue())

    def test_invalid_dir_json_mode(self) -> None:
        """Non-directory path with --json outputs JSON error and exits 1."""
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_path = os.path.join(tmpdir, "does-not-exist")
            with (
                mock.patch.object(
                    sys, "argv",
                    ["audit_skill_system.py", invalid_path, "--json"],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                with self.assertRaises(SystemExit) as cm:
                    main()
        self.assertEqual(cm.exception.code, 1)
        data = json.loads(stdout.getvalue())
        self.assertFalse(data["success"])
        self.assertIn("not a directory", data["error"])

    def test_json_aware_error_non_json_mode(self) -> None:
        """Argparse error without --json prints to stderr and exits 1."""
        stderr = io.StringIO()
        with (
            mock.patch.object(
                sys, "argv",
                ["audit_skill_system.py", "/some/path", "--bogus"],
            ),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as cm:
                main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("error:", stderr.getvalue())

    def test_json_aware_error_json_mode(self) -> None:
        """Argparse error with --json outputs JSON error and exits 1."""
        stdout = io.StringIO()
        with (
            mock.patch.object(
                sys, "argv",
                ["audit_skill_system.py", "--json", "--bogus"],
            ),
            contextlib.redirect_stdout(stdout),
        ):
            with self.assertRaises(SystemExit) as cm:
                main()
        self.assertEqual(cm.exception.code, 1)
        data = json.loads(stdout.getvalue())
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_valid_system_json_output(self) -> None:
        """Valid system with --json outputs structured JSON and exits 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_full_valid_system(tmpdir)
            stdout = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["audit_skill_system.py", tmpdir, "--json"],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                with self.assertRaises(SystemExit) as cm:
                    main()
            self.assertEqual(cm.exception.code, 0)
            data = json.loads(stdout.getvalue())
            self.assertTrue(data["success"])
            self.assertIn("counts", data)
            self.assertIn("summary", data)
            self.assertIn("errors", data)

    def test_json_output_with_failures_exits_1(self) -> None:
        """System with FAIL errors and --json outputs success=False, exits 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skills", "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "# Demo Skill\n\nNo frontmatter.\n",
            )
            stdout = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["audit_skill_system.py", tmpdir, "--json"],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                with self.assertRaises(SystemExit) as cm:
                    main()
            self.assertEqual(cm.exception.code, 1)
            data = json.loads(stdout.getvalue())
            self.assertFalse(data["success"])

    def test_valid_system_human_with_errors_prints_summary(self) -> None:
        """System with warnings prints 'Issues found' and summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_valid_system(tmpdir)
            # No manifest → WARN
            stdout = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["audit_skill_system.py", tmpdir],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                with self.assertRaises(SystemExit) as cm:
                    main()
            self.assertEqual(cm.exception.code, 0)
            output = stdout.getvalue()
            self.assertIn("Issues found", output)

    def test_valid_system_no_errors_prints_passed(self) -> None:
        """A clean system prints 'passed' and exits 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_full_valid_system(tmpdir)
            stdout = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    ["audit_skill_system.py", tmpdir],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                with self.assertRaises(SystemExit) as cm:
                    main()
            self.assertEqual(cm.exception.code, 0)
            self.assertIn("passed", stdout.getvalue().lower())

    def test_verbose_and_orchestration_banners(self) -> None:
        """Verbose + orchestration flags print banners."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_full_valid_system(tmpdir)
            stdout = io.StringIO()
            with (
                mock.patch.object(
                    sys, "argv",
                    [
                        "audit_skill_system.py", tmpdir,
                        "--verbose", "--allow-orchestration",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                with self.assertRaises(SystemExit) as cm:
                    main()
            self.assertEqual(cm.exception.code, 0)
            output = stdout.getvalue()
            self.assertIn("Orchestration mode", output)
            self.assertIn("===", output)


if __name__ == "__main__":
    unittest.main()
