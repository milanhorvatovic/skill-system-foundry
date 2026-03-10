"""Tests for audit_skill_system.py.

Covers check_upward_references, audit_skill_system, and the main()
CLI entry point.
"""

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

from audit_skill_system import check_upward_references, audit_skill_system
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


if __name__ == "__main__":
    unittest.main()
