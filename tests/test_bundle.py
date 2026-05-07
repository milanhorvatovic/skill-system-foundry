import os
import re
import sys
import tempfile
import unittest
from unittest import mock

from helpers import write_text


SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.bundling import (
    _build_rewrite_map,
    _compute_original_paths,
    _copy_external_files,
    _copy_inlined_skills,
    _copy_skill,
    _rewrite_markdown_content,
    _rewrite_markdown_paths,
    _rewrite_reference_target,
    check_external_arcnames,
    check_long_paths,
    check_reserved_path_components,
    create_bundle,
    postvalidate,
    prevalidate,
)
from lib.constants import BUNDLE_DESCRIPTION_MAX_LENGTH, LEVEL_FAIL, LEVEL_WARN
from lib.references import compute_bundle_path


class MarkdownRewriteTests(unittest.TestCase):
    def test_rewrite_matrix(self) -> None:
        rewrite_map = {
            "references/foo.md": "references/inlined/foo.md",
            "roles/reviewer.md": "roles/core/reviewer.md",
        }

        cases = {
            "See [doc](references/foo.md).": "See [doc](references/inlined/foo.md).",
            "See [doc](references/foo.md#overview).": "See [doc](references/inlined/foo.md#overview).",
            "See [doc](references/foo.md?mode=raw#overview).": "See [doc](references/inlined/foo.md?mode=raw#overview).",
            "See [doc](references/foo.md \"Guide\").": "See [doc](references/inlined/foo.md \"Guide\").",
            "See [doc](<references/foo.md#overview>).": "See [doc](<references/inlined/foo.md#overview>).",
            "See [doc](<references/foo.md?mode=raw#overview> \"Guide\").": "See [doc](<references/inlined/foo.md?mode=raw#overview> \"Guide\").",
            "Use `references/foo.md` and `roles/reviewer.md`.": "Use `references/inlined/foo.md` and `roles/core/reviewer.md`.",
            "Use `references/foo.md#overview`.": "Use `references/inlined/foo.md#overview`.",
            "Leave [doc](references/missing.md) unchanged.": "Leave [doc](references/missing.md) unchanged.",
            # Non-canonical paths: normpath fallback rewrites equivalent forms
            "See [doc](references/../references/foo.md).": "See [doc](references/inlined/foo.md).",
            "See [doc](./references/foo.md).": "See [doc](references/inlined/foo.md).",
            "Use `roles/../roles/reviewer.md`.": "Use `roles/core/reviewer.md`.",
        }

        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(_rewrite_markdown_content(source, rewrite_map), expected)

    def test_image_link_prefix_preserved(self) -> None:
        rewrite_map = {"references/foo.md": "references/inlined/foo.md"}
        source = "![image](references/foo.md)"
        expected = "![image](references/inlined/foo.md)"
        self.assertEqual(_rewrite_markdown_content(source, rewrite_map), expected)


class PostValidateTests(unittest.TestCase):
    def test_error_paths_use_forward_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(os.path.join(bundle_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(
                os.path.join(bundle_dir, "references", "guide.md"),
                "[Missing](missing.md)\n",
            )

            import lib.bundling as bundling_mod

            original_relpath = os.path.relpath

            def fake_relpath(path: str, start: str = "") -> str:
                rel = original_relpath(path, start) if start else original_relpath(path)
                return rel.replace("/", "\\")

            with mock.patch("lib.bundling.os.path.relpath", side_effect=fake_relpath), mock.patch.object(bundling_mod.os, "sep", "\\"):
                errors = postvalidate(bundle_dir)

            unresolved = [
                err for err in errors
                if "Unresolved markdown reference in bundle" in err
            ]
            self.assertEqual(len(unresolved), 1)
            self.assertIn("'references/guide.md' line 1", unresolved[0])
            self.assertNotIn("\\", unresolved[0])


class CopyExternalFilesCollisionTests(unittest.TestCase):
    def test_excluded_external_file_is_rejected(self) -> None:
        """An external file whose real path contains an excluded component."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)

            # Create a file inside a .git directory
            ext_file = os.path.join(system_root, ".git", "config")
            write_text(ext_file, "sensitive data")

            with self.assertRaises(ValueError) as cm:
                _copy_external_files(
                    {ext_file}, system_root, bundle_dir,
                    exclude_patterns=[".git"],
                )

            self.assertIn("excluded path", str(cm.exception))

    def test_external_vs_external_collision_is_rejected(self) -> None:
        """Two different external files mapping to the same bundle path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)

            # Create two files that will both classify to references/<same name>
            ext_a = os.path.join(system_root, "shared", "guide.md")
            ext_b = os.path.join(system_root, "docs", "guide.md")
            write_text(ext_a, "Guide A")
            write_text(ext_b, "Guide B")

            # Both should map to references/guide.md (non-standard dirs
            # fall back to references/<basename>).
            path_a = compute_bundle_path(ext_a, system_root)
            path_b = compute_bundle_path(ext_b, system_root)
            self.assertEqual(path_a, path_b)

            with self.assertRaises(ValueError) as cm:
                _copy_external_files({ext_a, ext_b}, system_root, bundle_dir)

            self.assertIn("Bundle path collision", str(cm.exception))

    def test_external_overwrites_internal_file_is_rejected(self) -> None:
        """An external file would overwrite a skill-internal file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            bundle_dir = os.path.join(tmpdir, "bundle")

            # Create a skill with references/guide.md
            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(skill_dir, "references", "guide.md"), "Internal")

            # Simulate _copy_skill: put the skill file in the bundle
            internal_target = os.path.join(bundle_dir, "references", "guide.md")
            write_text(internal_target, "Internal")

            # Create an external file that maps to references/guide.md
            ext_file = os.path.join(system_root, "references", "guide.md")
            write_text(ext_file, "External")
            self.assertEqual(
                compute_bundle_path(ext_file, system_root), "references/guide.md"
            )

            with self.assertRaises(ValueError) as cm:
                _copy_external_files({ext_file}, system_root, bundle_dir)

            self.assertIn("overwrite skill-internal file", str(cm.exception))


class CopySkillSymlinkBoundaryTests(unittest.TestCase):
    def test_symlink_escaping_boundary_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            outside_file = os.path.join(tmpdir, "outside", "secret.txt")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(outside_file, "secret content")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create a symlink inside the skill pointing outside the root
            link_path = os.path.join(skill_dir, "secret.txt")
            try:
                os.symlink(outside_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            with self.assertRaises(ValueError) as cm:
                _copy_skill(skill_dir, bundle_dir, [], system_root)

            self.assertIn("Symlinked file escapes allowed boundary", str(cm.exception))

    def test_symlink_within_boundary_is_allowed(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            internal_file = os.path.join(system_root, "shared", "allowed.txt")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(internal_file, "allowed content")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create a symlink inside the skill pointing within the root
            link_path = os.path.join(skill_dir, "allowed.txt")
            try:
                os.symlink(internal_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            # Should not raise
            _copy_skill(skill_dir, bundle_dir, [], system_root)

            copied = os.path.join(bundle_dir, "allowed.txt")
            self.assertTrue(os.path.exists(copied))
            with open(copied, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "allowed content")

    def test_symlinked_dir_escaping_boundary_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            outside_dir = os.path.join(tmpdir, "outside", "data")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(outside_dir, "secret.txt"), "secret")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create a symlinked directory inside the skill pointing outside
            link_path = os.path.join(skill_dir, "data")
            try:
                os.symlink(outside_dir, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            with self.assertRaises(ValueError) as cm:
                _copy_skill(skill_dir, bundle_dir, [], system_root)

            self.assertIn("Symlinked directory escapes allowed boundary", str(cm.exception))

    def test_symlinked_dir_within_boundary_is_traversed(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            internal_dir = os.path.join(system_root, "shared", "docs")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(internal_dir, "guide.txt"), "guide content")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create a symlinked directory inside the skill pointing within root
            link_path = os.path.join(skill_dir, "docs")
            try:
                os.symlink(internal_dir, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            # Should not raise and should traverse the symlinked directory
            _copy_skill(skill_dir, bundle_dir, [], system_root)

            copied = os.path.join(bundle_dir, "docs", "guide.txt")
            self.assertTrue(os.path.exists(copied))
            with open(copied, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "guide content")

    def test_symlinked_dir_to_excluded_target_is_skipped(self) -> None:
        """A symlink like docs -> .git should be excluded even though
        the symlink name itself does not match any exclude pattern."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo")
            git_dir = os.path.join(system_root, ".git")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(skill_dir, "SKILL.md"), "---\nname: demo\n---\n")
            write_text(os.path.join(git_dir, "config"), "secret")
            os.makedirs(bundle_dir, exist_ok=True)

            # Create symlink "docs" pointing to ".git" inside the root
            link_path = os.path.join(skill_dir, "docs")
            try:
                os.symlink(git_dir, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            _copy_skill(skill_dir, bundle_dir, [".git"], system_root)

            # The symlink target matches .git, so it must be excluded
            self.assertFalse(
                os.path.exists(os.path.join(bundle_dir, "docs", "config"))
            )
            # SKILL.md should still be copied
            self.assertTrue(
                os.path.exists(os.path.join(bundle_dir, "SKILL.md"))
            )


class CopyInlinedSkillsTests(unittest.TestCase):
    """Tests for _copy_inlined_skills() directory copying and renaming."""

    def test_skill_md_renamed_to_capability_md(self) -> None:
        """SKILL.md in inlined skills is renamed to capability.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            testing_skill = os.path.join(system_root, "skills", "testing")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)

            write_text(os.path.join(testing_skill, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(testing_skill, "references", "guide.md"), "Guide\n")

            inlined_skills = {os.path.abspath(testing_skill): "testing"}
            mapping, _per_root = _copy_inlined_skills(
                inlined_skills, bundle_dir, [], system_root,
            )

            # capability.md exists, SKILL.md does not
            self.assertTrue(
                os.path.exists(os.path.join(bundle_dir, "capabilities", "testing", "capability.md"))
            )
            self.assertFalse(
                os.path.exists(os.path.join(bundle_dir, "capabilities", "testing", "SKILL.md"))
            )
            # Sub-files are copied
            self.assertTrue(
                os.path.exists(os.path.join(bundle_dir, "capabilities", "testing", "references", "guide.md"))
            )
            # Mapping includes both files
            abs_skill_md = os.path.join(testing_skill, "SKILL.md")
            self.assertEqual(
                mapping[abs_skill_md], "capabilities/testing/capability.md"
            )

    def test_multiple_skills_inlined(self) -> None:
        """Multiple skills are inlined into separate capability directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            testing = os.path.join(system_root, "skills", "testing")
            deployment = os.path.join(system_root, "skills", "deployment")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)

            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(os.path.join(deployment, "SKILL.md"), "---\nname: deployment\n---\n")
            write_text(os.path.join(deployment, "scripts", "deploy.sh"), "#!/bin/bash\n")

            inlined_skills = {
                os.path.abspath(testing): "testing",
                os.path.abspath(deployment): "deployment",
            }
            mapping, _per_root = _copy_inlined_skills(
                inlined_skills, bundle_dir, [], system_root,
            )

            self.assertTrue(
                os.path.exists(os.path.join(bundle_dir, "capabilities", "testing", "capability.md"))
            )
            self.assertTrue(
                os.path.exists(os.path.join(bundle_dir, "capabilities", "deployment", "capability.md"))
            )
            self.assertTrue(
                os.path.exists(os.path.join(bundle_dir, "capabilities", "deployment", "scripts", "deploy.sh"))
            )

    def test_existing_capability_dir_raises(self) -> None:
        """Collision with existing capability directory raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            testing = os.path.join(system_root, "skills", "testing")
            bundle_dir = os.path.join(tmpdir, "bundle")

            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            # Pre-create the collision
            write_text(os.path.join(bundle_dir, "capabilities", "testing", "existing.md"), "exists\n")

            inlined_skills = {os.path.abspath(testing): "testing"}
            with self.assertRaises(ValueError):
                _copy_inlined_skills(
                    inlined_skills, bundle_dir, [], system_root,
                )

    def test_symlink_within_skill_boundary_allowed_without_system_root(self) -> None:
        """Symlinks within an inlined skill are allowed when system_root is None."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            testing = os.path.join(tmpdir, "skills", "testing")
            shared_file = os.path.join(testing, "shared", "data.txt")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)

            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            write_text(shared_file, "shared data")

            # Create a symlink within the skill pointing to another file
            # in the same skill directory tree.
            link_path = os.path.join(testing, "link.txt")
            try:
                os.symlink(shared_file, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            inlined_skills = {os.path.abspath(testing): "testing"}
            # system_root=None — boundary should be the skill dir itself
            mapping, _per_root = _copy_inlined_skills(
                inlined_skills, bundle_dir, [], None,
            )

            # Symlinked file should be copied
            self.assertTrue(
                os.path.exists(os.path.join(bundle_dir, "capabilities", "testing", "link.txt"))
            )

    def test_skill_with_existing_capability_md_raises_collision(self) -> None:
        """An inlined skill containing both SKILL.md and capability.md raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            testing = os.path.join(system_root, "skills", "testing")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)

            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\n---\n")
            # Pre-existing capability.md in the source skill
            write_text(os.path.join(testing, "capability.md"), "# Existing\n")

            inlined_skills = {os.path.abspath(testing): "testing"}
            with self.assertRaises(ValueError) as cm:
                _copy_inlined_skills(
                    inlined_skills, bundle_dir, [], system_root,
                )

            self.assertIn("destination collision", str(cm.exception))

    def test_deeply_nested_subdirectories_inlined(self) -> None:
        """Inlined skills with deeply nested subdirectories (3+ levels)
        preserve the full directory tree in capabilities/<name>/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            testing = os.path.join(system_root, "skills", "testing")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)

            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\n---\n",
            )
            write_text(
                os.path.join(testing, "a", "b", "c", "deep.md"),
                "# Deeply nested\n",
            )
            write_text(
                os.path.join(testing, "a", "top.md"),
                "# Top of a\n",
            )

            inlined_skills = {os.path.abspath(testing): "testing"}
            mapping, per_root = _copy_inlined_skills(
                inlined_skills, bundle_dir, [], system_root,
            )

            # All levels are created
            self.assertTrue(os.path.exists(
                os.path.join(bundle_dir, "capabilities", "testing", "capability.md")
            ))
            self.assertTrue(os.path.exists(
                os.path.join(bundle_dir, "capabilities", "testing", "a", "top.md")
            ))
            self.assertTrue(os.path.exists(
                os.path.join(bundle_dir, "capabilities", "testing", "a", "b", "c", "deep.md")
            ))

            # Mapping covers all files
            self.assertEqual(len(mapping), 3)
            bundle_rels = set(mapping.values())
            self.assertIn("capabilities/testing/capability.md", bundle_rels)
            self.assertIn("capabilities/testing/a/top.md", bundle_rels)
            self.assertIn("capabilities/testing/a/b/c/deep.md", bundle_rels)

            # per_root groups them correctly
            abs_testing = os.path.abspath(testing)
            self.assertIn(abs_testing, per_root)
            self.assertEqual(len(per_root[abs_testing]), 3)


class InlinedBundleIntegrationTests(unittest.TestCase):
    """End-to-end tests for bundling with --inline-orchestrated-skills."""

    def _create_path1_layout(self, tmpdir: str) -> tuple[str, str]:
        """Create a Path 1 coordination skill layout.

        Returns (system_root, coordinator_skill_path).
        """
        system_root = os.path.join(tmpdir, "root")

        # Coordinator skill
        coordinator = os.path.join(system_root, "skills", "release-coordinator")
        write_text(
            os.path.join(coordinator, "SKILL.md"),
            "---\n"
            "name: release-coordinator\n"
            "description: Coordinates release workflows across domains.\n"
            "---\n\n"
            "# Release Coordinator\n\n"
            "Delegate to roles:\n"
            "- [QA Role](../../roles/qa-role.md)\n"
            "- [Release Role](../../roles/release-role.md)\n",
        )

        # Domain skills
        testing = os.path.join(system_root, "skills", "testing")
        write_text(
            os.path.join(testing, "SKILL.md"),
            "---\nname: testing\ndescription: Testing domain skill.\n---\n\n# Testing\n",
        )
        write_text(
            os.path.join(testing, "references", "test-guide.md"),
            "# Test Guide\n\nHow to run tests.\n",
        )

        deployment = os.path.join(system_root, "skills", "deployment")
        write_text(
            os.path.join(deployment, "SKILL.md"),
            "---\nname: deployment\ndescription: Deployment domain skill.\n---\n\n# Deployment\n",
        )
        write_text(
            os.path.join(deployment, "scripts", "deploy.sh"),
            "#!/bin/bash\necho deploy\n",
        )

        # Roles that reference domain skills
        write_text(
            os.path.join(system_root, "roles", "qa-role.md"),
            "# QA Role\n\n"
            "Follow the testing skill: [Testing](../skills/testing/SKILL.md)\n"
            "See [guide](../skills/testing/references/test-guide.md)\n",
        )
        write_text(
            os.path.join(system_root, "roles", "release-role.md"),
            "# Release Role\n\n"
            "Follow the deployment skill: [Deployment](../skills/deployment/SKILL.md)\n",
        )

        # Manifest
        write_text(os.path.join(system_root, "manifest.yaml"), "name: test-system\n")

        return system_root, coordinator

    def test_successful_path1_bundle(self) -> None:
        """Full Path 1 bundle produces correct structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, coordinator = self._create_path1_layout(tmpdir)

            # Pre-validate with inline flag
            errors, warnings, scan_result = prevalidate(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )
            self.assertEqual(errors, [], f"Unexpected errors: {errors}")
            self.assertIsNotNone(scan_result)

            # Create bundle
            bundle_base = os.path.join(tmpdir, "bundle_base")
            os.makedirs(bundle_base)
            bundle_dir, file_mapping, stats = create_bundle(
                coordinator, system_root, scan_result, [],
                bundle_base=bundle_base,
                inline_orchestrated_skills=True,
            )

            # Verify structure: capabilities/testing/capability.md
            cap_testing = os.path.join(bundle_dir, "capabilities", "testing")
            self.assertTrue(os.path.exists(os.path.join(cap_testing, "capability.md")))
            self.assertFalse(os.path.exists(os.path.join(cap_testing, "SKILL.md")))
            self.assertTrue(os.path.exists(os.path.join(cap_testing, "references", "test-guide.md")))

            # Verify structure: capabilities/deployment/capability.md
            cap_deployment = os.path.join(bundle_dir, "capabilities", "deployment")
            self.assertTrue(os.path.exists(os.path.join(cap_deployment, "capability.md")))
            self.assertTrue(os.path.exists(os.path.join(cap_deployment, "scripts", "deploy.sh")))

            # Verify roles are included
            self.assertTrue(os.path.exists(os.path.join(bundle_dir, "roles", "qa-role.md")))
            self.assertTrue(os.path.exists(os.path.join(bundle_dir, "roles", "release-role.md")))

            # Verify stats
            self.assertEqual(stats["inlined_skill_count"], 2)

    def test_role_references_rewritten_to_capabilities(self) -> None:
        """Role references to skills are rewritten to capability paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, coordinator = self._create_path1_layout(tmpdir)

            errors, warnings, scan_result = prevalidate(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )
            self.assertEqual(errors, [])

            bundle_base = os.path.join(tmpdir, "bundle_base")
            os.makedirs(bundle_base)
            bundle_dir, _, _ = create_bundle(
                coordinator, system_root, scan_result, [],
                bundle_base=bundle_base,
                inline_orchestrated_skills=True,
            )

            # Read the rewritten qa-role.md
            qa_role_path = os.path.join(bundle_dir, "roles", "qa-role.md")
            with open(qa_role_path, "r", encoding="utf-8") as f:
                qa_content = f.read()

            # References should point to capabilities, not skills
            self.assertIn("capabilities/testing/capability.md", qa_content)
            self.assertIn("capabilities/testing/references/test-guide.md", qa_content)
            self.assertNotIn("skills/testing/SKILL.md", qa_content)

            # Read the rewritten release-role.md
            release_role_path = os.path.join(bundle_dir, "roles", "release-role.md")
            with open(release_role_path, "r", encoding="utf-8") as f:
                release_content = f.read()

            self.assertIn("capabilities/deployment/capability.md", release_content)
            self.assertNotIn("skills/deployment/SKILL.md", release_content)

    def test_postvalidation_passes(self) -> None:
        """The resulting bundle passes post-validation (single SKILL.md, no broken refs)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, coordinator = self._create_path1_layout(tmpdir)

            errors, _, scan_result = prevalidate(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )
            self.assertEqual(errors, [])

            bundle_base = os.path.join(tmpdir, "bundle_base")
            os.makedirs(bundle_base)
            bundle_dir, _, _ = create_bundle(
                coordinator, system_root, scan_result, [],
                bundle_base=bundle_base,
                inline_orchestrated_skills=True,
            )

            post_errors = postvalidate(bundle_dir)
            self.assertEqual(post_errors, [], f"Post-validation errors: {post_errors}")

    def test_without_flag_cross_skill_fails(self) -> None:
        """Without --inline-orchestrated-skills, the bundle fails pre-validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, coordinator = self._create_path1_layout(tmpdir)

            errors, _, scan_result = prevalidate(
                coordinator, system_root,
                inline_orchestrated_skills=False,
            )

            cross_skill_fails = [e for e in errors if "Cross-skill reference" in e]
            self.assertGreater(len(cross_skill_fails), 0)

    def test_role_referencing_multiple_inlined_skills(self) -> None:
        """A role that references multiple inlined skills rewrites all of them."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")

            # Coordinator
            coordinator = os.path.join(system_root, "skills", "coordinator")
            write_text(
                os.path.join(coordinator, "SKILL.md"),
                "---\n"
                "name: coordinator\n"
                "description: Coordinates across domains.\n"
                "---\n\n"
                "# Coordinator\n\n"
                "See [qa](../../roles/qa-role.md)\n",
            )

            # Two domain skills
            testing = os.path.join(system_root, "skills", "testing")
            write_text(os.path.join(testing, "SKILL.md"), "---\nname: testing\ndescription: Testing.\n---\n")

            deployment = os.path.join(system_root, "skills", "deployment")
            write_text(os.path.join(deployment, "SKILL.md"), "---\nname: deployment\ndescription: Deploy.\n---\n")

            # Role references both skills
            write_text(
                os.path.join(system_root, "roles", "qa-role.md"),
                "# QA\n"
                "See [testing](../skills/testing/SKILL.md) and "
                "[deployment](../skills/deployment/SKILL.md)\n",
            )

            write_text(os.path.join(system_root, "manifest.yaml"), "name: test\n")

            errors, _, scan_result = prevalidate(
                coordinator, system_root, inline_orchestrated_skills=True,
            )
            self.assertEqual(errors, [])

            bundle_base = os.path.join(tmpdir, "bundle_base")
            os.makedirs(bundle_base)
            bundle_dir, _, _ = create_bundle(
                coordinator, system_root, scan_result, [],
                bundle_base=bundle_base, inline_orchestrated_skills=True,
            )

            qa_path = os.path.join(bundle_dir, "roles", "qa-role.md")
            with open(qa_path, "r", encoding="utf-8") as f:
                qa_content = f.read()

            self.assertIn("capabilities/testing/capability.md", qa_content)
            self.assertIn("capabilities/deployment/capability.md", qa_content)
            self.assertNotIn("skills/testing/SKILL.md", qa_content)
            self.assertNotIn("skills/deployment/SKILL.md", qa_content)

            post_errors = postvalidate(bundle_dir)
            self.assertEqual(post_errors, [], f"Post-validation errors: {post_errors}")

    def test_inlined_skill_transitive_deps_included(self) -> None:
        """External references from inlined skills are discovered and bundled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")

            coordinator = os.path.join(system_root, "skills", "coordinator")
            write_text(
                os.path.join(coordinator, "SKILL.md"),
                "---\n"
                "name: coordinator\n"
                "description: Coordinates across domains.\n"
                "---\n\n"
                "# Coordinator\n\n"
                "See [qa](../../roles/qa-role.md)\n",
            )

            # Domain skill references a shared external reference
            testing = os.path.join(system_root, "skills", "testing")
            shared_ref = os.path.join(system_root, "references", "shared-guide.md")
            write_text(shared_ref, "# Shared Guide\n")
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\ndescription: Testing.\n---\n"
                "See [shared](../../references/shared-guide.md)\n",
            )

            write_text(
                os.path.join(system_root, "roles", "qa-role.md"),
                "# QA\nSee [testing](../skills/testing/SKILL.md)\n",
            )
            write_text(os.path.join(system_root, "manifest.yaml"), "name: test\n")

            errors, _, scan_result = prevalidate(
                coordinator, system_root, inline_orchestrated_skills=True,
            )
            self.assertEqual(errors, [], f"Unexpected errors: {errors}")
            # The shared guide must have been discovered as an external file
            self.assertIn(
                os.path.abspath(shared_ref), scan_result["external_files"],
            )

            bundle_base = os.path.join(tmpdir, "bundle_base")
            os.makedirs(bundle_base)
            bundle_dir, _, _ = create_bundle(
                coordinator, system_root, scan_result, [],
                bundle_base=bundle_base, inline_orchestrated_skills=True,
            )

            # The shared guide should be in the bundle
            self.assertTrue(
                os.path.exists(os.path.join(bundle_dir, "references", "shared-guide.md"))
            )

            post_errors = postvalidate(bundle_dir)
            self.assertEqual(post_errors, [], f"Post-validation errors: {post_errors}")


    def test_alias_references_rewritten_in_bundle(self) -> None:
        """When a role references an inlined skill via a symlink alias,
        the alias path is still rewritten to the capability path."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")

            coordinator = os.path.join(system_root, "skills", "coordinator")
            write_text(
                os.path.join(coordinator, "SKILL.md"),
                "---\nname: coordinator\ndescription: Coord.\n---\n\n"
                "See [qa](../../roles/qa-role.md)\n",
            )

            testing = os.path.join(system_root, "skills", "testing")
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\ndescription: Testing.\n---\n",
            )

            # Symlink alias
            alias_path = os.path.join(system_root, "skills", "testing-alias")
            try:
                os.symlink(testing, alias_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            # Role uses the ALIAS path
            write_text(
                os.path.join(system_root, "roles", "qa-role.md"),
                "# QA\nSee [testing](../skills/testing-alias/SKILL.md)\n",
            )

            write_text(os.path.join(system_root, "manifest.yaml"), "name: test\n")

            errors, _, scan_result = prevalidate(
                coordinator, system_root, inline_orchestrated_skills=True,
            )
            self.assertEqual(errors, [])

            bundle_base = os.path.join(tmpdir, "bundle_base")
            os.makedirs(bundle_base)
            bundle_dir, _, _ = create_bundle(
                coordinator, system_root, scan_result, [],
                bundle_base=bundle_base, inline_orchestrated_skills=True,
            )

            qa_path = os.path.join(bundle_dir, "roles", "qa-role.md")
            with open(qa_path, "r", encoding="utf-8") as f:
                qa_content = f.read()

            # The alias reference should be rewritten
            self.assertIn("capabilities/testing/capability.md", qa_content, (
                f"Alias reference should be rewritten. Content: {qa_content}"
            ))
            self.assertNotIn("testing-alias", qa_content, (
                f"Alias name should not remain. Content: {qa_content}"
            ))

            post_errors = postvalidate(bundle_dir)
            self.assertEqual(post_errors, [], f"Post-validation errors: {post_errors}")

    def test_coordinator_back_reference_rewritten_in_bundle(self) -> None:
        """When an inlined skill references back to the coordinator,
        the reference is rewritten to the correct bundle-relative path
        and postvalidation passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")

            coordinator = os.path.join(system_root, "skills", "coordinator")
            write_text(
                os.path.join(coordinator, "SKILL.md"),
                "---\nname: coordinator\ndescription: Coord.\n---\n\n"
                "See [qa](../../roles/qa-role.md)\n",
            )

            testing = os.path.join(system_root, "skills", "testing")
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\ndescription: Testing.\n---\n\n"
                "Back to [coord](../coordinator/SKILL.md)\n",
            )

            write_text(
                os.path.join(system_root, "roles", "qa-role.md"),
                "# QA\nSee [testing](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(system_root, "manifest.yaml"),
                "name: test\n",
            )

            errors, _, scan_result = prevalidate(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )
            self.assertEqual(errors, [])

            bundle_base = os.path.join(tmpdir, "bundle_base")
            os.makedirs(bundle_base)
            bundle_dir, _, _ = create_bundle(
                coordinator, system_root, scan_result, [],
                bundle_base=bundle_base, inline_orchestrated_skills=True,
            )

            # The inlined capability should have its coordinator
            # back-reference rewritten to the bundle-root SKILL.md.
            cap_path = os.path.join(
                bundle_dir, "capabilities", "testing", "capability.md"
            )
            with open(cap_path, "r", encoding="utf-8") as f:
                cap_content = f.read()

            self.assertIn("../../SKILL.md", cap_content, (
                f"Coordinator back-reference should be rewritten. "
                f"Content: {cap_content}"
            ))
            self.assertNotIn("../coordinator/SKILL.md", cap_content, (
                f"Original coordinator path should not remain. "
                f"Content: {cap_content}"
            ))

            post_errors = postvalidate(bundle_dir)
            self.assertEqual(
                post_errors, [],
                f"Post-validation errors: {post_errors}",
            )

    def test_inlined_skill_symlink_with_inferred_root(self) -> None:
        """When system_root is None, create_bundle should infer the
        root so that inlined skill symlinks within the inferable root
        are accepted (matching prevalidate's behavior)."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not supported on this platform")

        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")

            coordinator = os.path.join(system_root, "skills", "coordinator")
            write_text(
                os.path.join(coordinator, "SKILL.md"),
                "---\nname: coordinator\ndescription: Coord.\n---\n\n"
                "See [qa](../../roles/qa-role.md)\n",
            )

            testing = os.path.join(system_root, "skills", "testing")
            write_text(
                os.path.join(testing, "SKILL.md"),
                "---\nname: testing\ndescription: Testing.\n---\n",
            )

            # Shared reference outside the skill but within system root
            shared_ref = os.path.join(
                system_root, "references", "shared.md"
            )
            write_text(shared_ref, "# Shared reference\n")

            # Symlink inside the inlined skill pointing to the shared ref
            link_path = os.path.join(testing, "shared-link.md")
            try:
                os.symlink(shared_ref, link_path)
            except OSError:
                self.skipTest("symlink creation is not permitted")

            write_text(
                os.path.join(system_root, "roles", "qa-role.md"),
                "# QA\nSee [testing](../skills/testing/SKILL.md)\n",
            )
            write_text(
                os.path.join(system_root, "manifest.yaml"),
                "name: test\n",
            )

            # Use system_root=None so both prevalidate and create_bundle
            # must infer it.  Before the fix, create_bundle would reject
            # the symlink because _copy_inlined_skills fell back to
            # boundary = abs_skill_dir.
            errors, _, scan_result = prevalidate(
                coordinator, None,
                inline_orchestrated_skills=True,
            )
            self.assertEqual(errors, [], (
                f"Prevalidation should pass. Errors: {errors}"
            ))

            bundle_base = os.path.join(tmpdir, "bundle_base")
            os.makedirs(bundle_base)
            # This should NOT raise — create_bundle infers the root.
            bundle_dir, _, _ = create_bundle(
                coordinator, None, scan_result, [],
                bundle_base=bundle_base,
                inline_orchestrated_skills=True,
            )

            # Verify the inlined skill was copied
            cap_skill = os.path.join(
                bundle_dir, "capabilities", "testing", "capability.md"
            )
            self.assertTrue(
                os.path.exists(cap_skill),
                "Inlined capability should exist in bundle.",
            )


    def test_inlined_skills_ignored_when_flag_false(self) -> None:
        """create_bundle ignores inlined_skills data when flag is False.

        Even if scan_result contains populated inlined_skills (e.g.
        from a prevalidation with the flag enabled), passing
        inline_orchestrated_skills=False to create_bundle should
        produce a bundle with no capabilities/ directory and
        inlined_skill_count == 0.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root, coordinator = self._create_path1_layout(tmpdir)

            # Prevalidate WITH the flag so scan_result has inlined_skills
            errors, warnings, scan_result = prevalidate(
                coordinator, system_root,
                inline_orchestrated_skills=True,
            )
            self.assertEqual(errors, [])
            self.assertIsNotNone(scan_result)
            self.assertTrue(len(scan_result["inlined_skills"]) > 0)

            # Create bundle WITHOUT the flag
            bundle_base = os.path.join(tmpdir, "bundle_base")
            os.makedirs(bundle_base)
            bundle_dir, file_mapping, stats = create_bundle(
                coordinator, system_root, scan_result, [],
                bundle_base=bundle_base,
                inline_orchestrated_skills=False,
            )

            # No capabilities directory
            cap_dir = os.path.join(bundle_dir, "capabilities")
            self.assertFalse(
                os.path.exists(cap_dir),
                "capabilities/ should not exist when flag is False",
            )
            # Stat reports zero
            self.assertEqual(stats["inlined_skill_count"], 0)

    def test_postvalidate_catches_missing_capability_md(self) -> None:
        """postvalidate detects a capability directory missing capability.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "my-skill")
            os.makedirs(bundle_dir)
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: my-skill\n---\n# Skill\n",
            )
            # Create a capability directory WITHOUT capability.md
            cap_dir = os.path.join(bundle_dir, "capabilities", "broken")
            os.makedirs(cap_dir)
            write_text(os.path.join(cap_dir, "notes.md"), "# Notes\n")

            errors = postvalidate(bundle_dir)
            cap_errors = [e for e in errors if "missing" in e.lower() and "capability.md" in e.lower()]
            self.assertGreaterEqual(
                len(cap_errors), 1,
                f"Expected error about missing capability.md. Errors: {errors}",
            )


class PrevalidateTargetTests(unittest.TestCase):
    """Unit tests for the bundle_target parameter in prevalidate()."""

    def _make_skill(self, tmpdir: str, desc: str) -> tuple[str, str]:
        """Create a minimal skill with the given description.

        Returns (system_root, skill_path).
        """
        system_root = os.path.join(tmpdir, "root")
        skill_dir = os.path.join(system_root, "skills", "demo-skill")
        write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
        write_text(
            os.path.join(skill_dir, "SKILL.md"),
            f"---\nname: demo-skill\ndescription: {desc}\n---\n# Demo\n",
        )
        return system_root, skill_dir

    def test_claude_target_long_desc_is_error(self) -> None:
        """bundle_target='claude' turns a long description into a FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            long_desc = "A" * (BUNDLE_DESCRIPTION_MAX_LENGTH + 1)
            system_root, skill_dir = self._make_skill(tmpdir, long_desc)
            errors, warnings, result = prevalidate(
                skill_dir, system_root, bundle_target="claude"
            )
            self.assertTrue(any(e.startswith(LEVEL_FAIL) for e in errors))
            self.assertIsNone(result)

    def test_gemini_target_long_desc_is_warning(self) -> None:
        """bundle_target='gemini' turns a long description into a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            long_desc = "A" * (BUNDLE_DESCRIPTION_MAX_LENGTH + 1)
            system_root, skill_dir = self._make_skill(tmpdir, long_desc)
            errors, warnings, result = prevalidate(
                skill_dir, system_root, bundle_target="gemini"
            )
            self.assertEqual(errors, [])
            self.assertTrue(any(w.startswith(LEVEL_WARN) for w in warnings))
            self.assertIsNotNone(result)

    def test_generic_target_long_desc_is_warning(self) -> None:
        """bundle_target='generic' turns a long description into a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            long_desc = "A" * (BUNDLE_DESCRIPTION_MAX_LENGTH + 1)
            system_root, skill_dir = self._make_skill(tmpdir, long_desc)
            errors, warnings, result = prevalidate(
                skill_dir, system_root, bundle_target="generic"
            )
            self.assertEqual(errors, [])
            self.assertTrue(any(w.startswith(LEVEL_WARN) for w in warnings))
            self.assertIsNotNone(result)

    def test_default_target_is_claude(self) -> None:
        """Default bundle_target is 'claude' (long desc is a FAIL)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            long_desc = "A" * (BUNDLE_DESCRIPTION_MAX_LENGTH + 1)
            system_root, skill_dir = self._make_skill(tmpdir, long_desc)
            errors, warnings, result = prevalidate(skill_dir, system_root)
            self.assertTrue(any(e.startswith(LEVEL_FAIL) for e in errors))
            self.assertIsNone(result)


# ===================================================================
# Prevalidate Guards
# ===================================================================


class PrevalidateGuardTests(unittest.TestCase):
    """Tests for prevalidate's argument-guard branches."""

    def test_invalid_bundle_target_returns_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\ndescription: x\n---\n",
            )
            errors, warnings, result = prevalidate(
                skill_dir, None, bundle_target="martian",
            )
        self.assertTrue(any(e.startswith(LEVEL_FAIL) and "Invalid bundle_target" in e for e in errors))
        self.assertIsNone(result)

    def test_skill_without_description_skips_length_check(self) -> None:
        """Frontmatter without ``description`` skips the length-enforcement branch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\n---\n",
            )
            # Skip the spec check so the description-length branch is
            # reached.  Normally validate_skill would FAIL on missing
            # description and prevalidate would exit earlier.
            with mock.patch(
                "validate_skill.validate_skill", return_value=([], []),
            ):
                errors, warnings, result = prevalidate(skill_dir, None)
        # No description-length FAIL/WARN should appear since there is
        # nothing to measure.
        self.assertEqual(
            [e for e in errors + warnings if "Description is" in e],
            [],
        )

    def test_non_fail_spec_messages_surfaced_as_warnings(self) -> None:
        """WARN/INFO from validate_skill flow into prevalidate warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            skill_dir = os.path.join(system_root, "skills", "demo-skill")
            write_text(os.path.join(system_root, "manifest.yaml"), "name: demo\n")
            # A broken reference is a WARN, not a FAIL — exercises the
            # else-branch at bundling.py:107 where spec_errors are copied
            # into warnings.
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\ndescription: x\n---\n\n"
                "See [g](references/missing.md).\n",
            )
            errors, warnings, result = prevalidate(skill_dir, system_root)
        # Broken intra-skill refs are WARNs surfaced from validate_skill.
        self.assertTrue(
            any("does not exist" in w for w in warnings),
            msg=f"warnings={warnings}",
        )

    def test_spec_failures_aggregated_in_prevalidate(self) -> None:
        """Missing SKILL.md yields spec FAILs that prevalidate surfaces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            os.makedirs(skill_dir)
            # No SKILL.md: validate_skill returns a FAIL
            errors, warnings, result = prevalidate(skill_dir, None)
        fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertGreaterEqual(len(fails), 2)  # header + at least one spec err
        self.assertTrue(
            any("spec validation failures" in e for e in fails)
        )
        self.assertIsNone(result)


# ===================================================================
# Markdown Rewrite Fast-Path
# ===================================================================


class RewriteMarkdownPathsEmptyMapTests(unittest.TestCase):
    """Ensure the empty-rewrite-map fast-path in ``_rewrite_markdown_paths``."""

    def test_empty_rewrite_map_skips_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(os.path.join(bundle_dir, "SKILL.md"), "# x\n")
            file_mapping = {
                "/unused/ext.md": "references/ext.md",
            }
            with mock.patch(
                "lib.bundling._build_rewrite_map", return_value={},
            ):
                count = _rewrite_markdown_paths(
                    bundle_dir, tmpdir, None, file_mapping,
                )
        self.assertEqual(count, 0)


# ===================================================================
# Copy OSError Wrapping
# ===================================================================


class CopyOSErrorTests(unittest.TestCase):
    """OSError during file copy must be wrapped as ValueError."""

    def test_copy_skill_oserror_wrapped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)
            write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo-skill\ndescription: x\n---\n",
            )
            with mock.patch(
                "lib.bundling.shutil.copy2", side_effect=OSError("disk full"),
            ):
                with self.assertRaises(ValueError) as cm:
                    _copy_skill(skill_dir, bundle_dir, [], None)
            self.assertIn("Failed to copy bundled file", str(cm.exception))

    def test_copy_external_files_oserror_wrapped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)
            ext_file = os.path.join(system_root, "references", "note.md")
            write_text(ext_file, "# Note\n")

            with mock.patch(
                "lib.bundling.shutil.copy2", side_effect=OSError("EACCES"),
            ):
                with self.assertRaises(ValueError) as cm:
                    _copy_external_files({ext_file}, system_root, bundle_dir)
            self.assertIn("Failed to copy external file", str(cm.exception))

    def test_copy_inlined_skill_oserror_wrapped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inlined = os.path.join(tmpdir, "other-skill")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)
            write_text(
                os.path.join(inlined, "SKILL.md"),
                "---\nname: other-skill\ndescription: x\n---\n",
            )
            with mock.patch(
                "lib.bundling.shutil.copy2", side_effect=OSError("EIO"),
            ):
                with self.assertRaises(ValueError) as cm:
                    _copy_inlined_skills(
                        {inlined: "other-skill"}, bundle_dir, [], None,
                    )
            self.assertIn("Failed to copy inlined skill file", str(cm.exception))


class CopyExternalFilesEdgeTests(unittest.TestCase):
    """Edge cases for ``_copy_external_files``."""

    def test_external_reference_is_directory_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = os.path.join(tmpdir, "root")
            bundle_dir = os.path.join(tmpdir, "bundle")
            ext_dir = os.path.join(system_root, "references", "sub")
            os.makedirs(ext_dir)
            os.makedirs(bundle_dir)

            with self.assertRaises(ValueError) as cm:
                _copy_external_files({ext_dir}, system_root, bundle_dir)
            self.assertIn("is not a regular file", str(cm.exception))


# ===================================================================
# _rewrite_reference_target Edge Cases
# ===================================================================


class RewriteReferenceTargetEdgeTests(unittest.TestCase):
    """Edge-case inputs for ``_rewrite_reference_target``."""

    def test_empty_target_returned_unchanged(self) -> None:
        self.assertEqual(_rewrite_reference_target("", {}, allow_title=True), "")

    def test_backtick_target_unchanged_when_no_match(self) -> None:
        source = "Use `path/unknown.md` here."
        self.assertEqual(_rewrite_markdown_content(source, {"other.md": "x.md"}), source)


# ===================================================================
# relpath ValueError Fallback (cross-drive paths on Windows)
# ===================================================================


class RelpathValueErrorFallbackTests(unittest.TestCase):
    """Confirm that ValueError from os.path.relpath is swallowed."""

    def test_compute_original_paths_swallows_valueerror(self) -> None:
        """Inner relpath() calls raise → the except ValueError: pass path runs."""
        original_relpath = os.path.relpath
        call_count = {"n": 0}

        def selective_relpath(path: str, start: str | None = None) -> str:
            call_count["n"] += 1
            # Let the initial header call succeed, then raise on the
            # two inner try/except blocks at lines 517 and 526.
            if call_count["n"] == 1:
                return original_relpath(path, start) if start else original_relpath(path)
            raise ValueError("cross-drive")

        with mock.patch(
            "lib.bundling.os.path.relpath", side_effect=selective_relpath,
        ):
            result = _compute_original_paths(
                abs_source="/a/b/roles/r.md",
                bundle_file="/bundle/skill/SKILL.md",
                skill_path="/a/b/skill",
                bundle_dir="/bundle",
                system_root="/a/b",
                reverse_mapping={},
            )
        self.assertEqual(result, set())

    def test_compute_original_paths_without_system_root(self) -> None:
        """Without a system_root, only the source-dir-relative form is emitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_path = os.path.join(tmpdir, "skill")
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(skill_path)
            os.makedirs(bundle_dir)
            abs_source = os.path.join(tmpdir, "roles", "reviewer.md")
            bundle_file = os.path.join(bundle_dir, "SKILL.md")
            write_text(bundle_file, "# x\n")

            result = _compute_original_paths(
                abs_source=abs_source,
                bundle_file=bundle_file,
                skill_path=skill_path,
                bundle_dir=bundle_dir,
                system_root=None,
                reverse_mapping={},
            )
        self.assertTrue(result)

    def test_build_rewrite_map_with_empty_skill_files(self) -> None:
        """The ``if skill_files:`` False branch skips the alias-map block."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            bundle_file = os.path.join(bundle_dir, "SKILL.md")
            skill_path = os.path.join(tmpdir, "skill")
            os.makedirs(bundle_dir)
            os.makedirs(skill_path)
            write_text(bundle_file, "# x\n")

            result = _build_rewrite_map(
                bundle_file=bundle_file,
                bundle_dir=bundle_dir,
                skill_path=skill_path,
                system_root=None,
                file_mapping={},
                reverse_mapping={},
                skill_files={},
            )
        self.assertEqual(result, {})

    def test_build_rewrite_map_with_skill_files_no_system_root(self) -> None:
        """With skill_files present but no system_root, the system-rel block is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            bundle_file = os.path.join(bundle_dir, "SKILL.md")
            skill_path = os.path.join(tmpdir, "skill")
            os.makedirs(bundle_dir)
            os.makedirs(skill_path)
            write_text(bundle_file, "# x\n")
            skill_files = {
                os.path.join(skill_path, "nested", "f.md"): "nested/f.md",
            }
            result = _build_rewrite_map(
                bundle_file=bundle_file,
                bundle_dir=bundle_dir,
                skill_path=skill_path,
                system_root=None,
                file_mapping={},
                reverse_mapping={},
                skill_files=skill_files,
            )
        self.assertNotEqual(result, {})

    def test_build_rewrite_map_swallows_valueerror_in_alias_block(self) -> None:
        """Skill-internal alias relpath ValueErrors must be swallowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            bundle_file = os.path.join(bundle_dir, "SKILL.md")
            skill_path = os.path.join(tmpdir, "skill")
            os.makedirs(bundle_dir)
            os.makedirs(skill_path)
            write_text(bundle_file, "# x\n")

            skill_files = {os.path.join(skill_path, "nested", "f.md"): "nested/f.md"}

            original_relpath = os.path.relpath
            call_count = {"n": 0}

            def selective_relpath(path: str, start: str | None = None) -> str:
                call_count["n"] += 1
                # Raise on skill-internal alias block calls (calls 3+),
                # let the earlier ones succeed so we reach the alias block.
                if call_count["n"] >= 3:
                    raise ValueError("cross-drive")
                if start is None:
                    return original_relpath(path)
                return original_relpath(path, start)

            with mock.patch(
                "lib.bundling.os.path.relpath", side_effect=selective_relpath,
            ):
                result = _build_rewrite_map(
                    bundle_file=bundle_file,
                    bundle_dir=bundle_dir,
                    skill_path=skill_path,
                    system_root=tmpdir,
                    file_mapping={},
                    reverse_mapping={},
                    skill_files=skill_files,
                )
        self.assertIsInstance(result, dict)


# ===================================================================
# Postvalidate Coverage
# ===================================================================


class PostValidateCoverageTests(unittest.TestCase):
    """Tests for each uncovered branch in ``postvalidate``."""

    def test_zero_skill_md_reports_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_dir)
            errors = postvalidate(bundle_dir)
        no_skill = [e for e in errors if "No SKILL.md found" in e]
        self.assertEqual(len(no_skill), 1)
        self.assertIn(LEVEL_FAIL, no_skill[0])

    def test_multiple_skill_md_case_insensitive_reports_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(os.path.join(bundle_dir, "SKILL.md"), "---\nname: a\n---\n")
            write_text(
                os.path.join(bundle_dir, "nested", "skill.md"),
                "---\nname: b\n---\n",
            )
            errors = postvalidate(bundle_dir)
        multi = [e for e in errors if "Multiple SKILL.md" in e]
        self.assertTrue(
            multi,
            f"Expected a multiple SKILL.md validation error for "
            f"case-insensitive detection, got: {errors}",
        )
        self.assertIn(LEVEL_FAIL, multi[0])
        self.assertIn("SKILL.md", multi[0])
        self.assertIn("skill.md", multi[0])

    def test_capability_dir_missing_capability_md_reports_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(os.path.join(bundle_dir, "SKILL.md"), "---\nname: a\n---\n")
            os.makedirs(os.path.join(bundle_dir, "capabilities", "orphan"))
            errors = postvalidate(bundle_dir)
        missing = [
            e for e in errors
            if "missing" in e and "capability.md" in e
        ]
        self.assertEqual(len(missing), 1)
        self.assertIn(LEVEL_FAIL, missing[0])
        self.assertIn("orphan", missing[0])

    def test_markdown_reference_escapes_bundle_reports_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\n[x](../../outside.md)\n",
            )
            errors = postvalidate(bundle_dir)
        escape = [
            e for e in errors
            if "Markdown reference escapes bundle" in e
        ]
        self.assertEqual(len(escape), 1)
        self.assertIn(LEVEL_FAIL, escape[0])

    def test_backtick_reference_escapes_bundle_reports_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\nUse `../../etc/passwd` config.\n",
            )
            errors = postvalidate(bundle_dir)
        escape = [
            e for e in errors
            if "Backtick reference escapes bundle" in e
        ]
        self.assertEqual(len(escape), 1)
        self.assertIn(LEVEL_FAIL, escape[0])

    def test_capabilities_non_directory_entry_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(os.path.join(bundle_dir, "SKILL.md"), "---\nname: a\n---\n")
            write_text(
                os.path.join(bundle_dir, "capabilities", "NOTES.txt"),
                "file, not a cap dir",
            )
            errors = postvalidate(bundle_dir)
        self.assertEqual(
            [e for e in errors if "capability.md" in e and "missing" in e],
            [],
        )

    def test_markdown_link_with_url_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\n[home](https://example.com/page)\n",
            )
            errors = postvalidate(bundle_dir)
        self.assertEqual(errors, [])

    def test_pure_fragment_markdown_link_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\n[top](#heading)\n",
            )
            errors = postvalidate(bundle_dir)
        self.assertEqual(errors, [])

    def test_markdown_ref_with_query_only_path_is_skipped(self) -> None:
        """``[x](?q=1)`` passes should_skip, strip_fragment returns empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\n[x](?q=1)\n",
            )
            errors = postvalidate(bundle_dir)
        # Neither escape nor unresolved errors — the empty ref_clean path exits early.
        self.assertEqual(
            [e for e in errors if "?q=1" in e or "Markdown reference" in e],
            [],
        )

    def test_backtick_url_is_skipped(self) -> None:
        """A backtick containing a URL with a ``/`` is skipped before resolution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\nVisit `https://example.com/page` today.\n",
            )
            errors = postvalidate(bundle_dir)
        self.assertEqual(errors, [])

    def test_backtick_reference_to_existing_file_is_accepted(self) -> None:
        """A backtick pointing to an existing in-bundle file produces no error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\nSee `refs/guide.md` for details.\n",
            )
            write_text(
                os.path.join(bundle_dir, "refs", "guide.md"), "# Guide\n",
            )
            errors = postvalidate(bundle_dir)
        self.assertEqual(errors, [])

    def test_multiple_backticks_on_same_line_each_checked(self) -> None:
        """Multiple backtick references on one line each iterate the inner loop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\n"
                "See `refs/missing-a.md` and `refs/missing-b.md` today.\n",
            )
            errors = postvalidate(bundle_dir)
        unresolved = [e for e in errors if "Unresolved backtick reference" in e]
        self.assertEqual(len(unresolved), 2)

    def test_backtick_query_only_path_is_skipped(self) -> None:
        """A backtick whose clean path strips to empty exits early."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\nSee `?q=1/foo` here.\n",
            )
            errors = postvalidate(bundle_dir)
        self.assertEqual(
            [e for e in errors if "?q=1" in e],
            [],
        )

    def test_backtick_reference_unresolved_reports_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            write_text(
                os.path.join(bundle_dir, "SKILL.md"),
                "---\nname: a\n---\n\nUse `refs/missing.md` somewhere.\n",
            )
            errors = postvalidate(bundle_dir)
        unresolved = [
            e for e in errors
            if "Unresolved backtick reference" in e
        ]
        self.assertEqual(len(unresolved), 1)
        self.assertIn(LEVEL_FAIL, unresolved[0])


class CheckLongPathsTests(unittest.TestCase):
    """``check_long_paths`` flags arcnames that exceed the budget.

    Arcname measurement includes the skill's own basename as the
    top-level component (matching ``create_bundle``'s zip layout),
    so each test builds the skill inside a known-name subdirectory
    and accounts for ``len(skill_name) + 1`` in the threshold maths.
    """

    SKILL_NAME = "demo-skill"  # 10 chars; +1 for the slash → +11

    def _build_skill_with_arcname(
        self, skill_dir: str, arcname: str
    ) -> None:
        full = os.path.join(skill_dir, *arcname.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("body")

    def _make_skill_dir(self, root: str) -> str:
        skill_dir = os.path.join(root, self.SKILL_NAME)
        os.makedirs(skill_dir)
        return skill_dir

    def test_under_threshold_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = self._make_skill_dir(tmpdir)
            self._build_skill_with_arcname(skill_dir, "SKILL.md")
            errors, passes = check_long_paths(
                skill_dir, threshold=260, user_prefix_budget=80,
            )
            self.assertEqual(errors, [])
            self.assertEqual(len(passes), 1)
            self.assertIn("long-path", passes[0])
            # Pass message names the on-disk arcname including the
            # skill basename (verifies the prefix is part of the
            # measurement).
            self.assertIn(f"{self.SKILL_NAME}/SKILL.md", passes[0])

    def test_arcname_at_threshold_passes(self) -> None:
        # threshold(60) - prefix(10) = 50.  The arcname is
        # ``demo-skill/<file>`` (11 chars + filename).  Pick a
        # filename that brings the total to <= 50.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = self._make_skill_dir(tmpdir)
            # 50 - len("demo-skill/") = 39; "a"*36 + ".md" = 39 chars.
            arcname = "a" * 36 + ".md"
            self._build_skill_with_arcname(skill_dir, arcname)
            errors, _ = check_long_paths(
                skill_dir, threshold=60, user_prefix_budget=10,
            )
            self.assertEqual(errors, [])

    def test_arcname_over_threshold_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = self._make_skill_dir(tmpdir)
            arcname = "a" * 50 + ".md"  # 53 chars; +11 prefix = 64
            self._build_skill_with_arcname(skill_dir, arcname)
            errors, _ = check_long_paths(
                skill_dir, threshold=60, user_prefix_budget=10,
            )
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith(LEVEL_FAIL))
            self.assertIn(arcname, errors[0])
            # Error names the basename-prefixed form too.
            self.assertIn(f"{self.SKILL_NAME}/", errors[0])

    def test_severity_override_emits_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = self._make_skill_dir(tmpdir)
            arcname = "a" * 50 + ".md"
            self._build_skill_with_arcname(skill_dir, arcname)
            errors, _ = check_long_paths(
                skill_dir,
                threshold=60,
                user_prefix_budget=10,
                severity=LEVEL_WARN,
            )
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith(LEVEL_WARN))

    def test_excluded_pattern_not_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = self._make_skill_dir(tmpdir)
            self._build_skill_with_arcname(skill_dir, "SKILL.md")
            self._build_skill_with_arcname(
                skill_dir, ".git/" + "x" * 200,
            )
            errors, _ = check_long_paths(
                skill_dir, threshold=100, user_prefix_budget=10,
            )
            # The .git/ entry would exceed the threshold but is
            # excluded from the walk by the bundler's exclude
            # patterns, so no FAIL fires.
            self.assertEqual(errors, [])

    def test_finding_uses_forward_slashes(self) -> None:
        # The reported path must always be POSIX-form so the message
        # is identical on every runner.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = self._make_skill_dir(tmpdir)
            arcname = "deeply/nested/" + "x" * 50 + ".md"
            self._build_skill_with_arcname(skill_dir, arcname)
            errors, _ = check_long_paths(
                skill_dir, threshold=60, user_prefix_budget=5,
            )
            self.assertEqual(len(errors), 1)
            self.assertNotIn("\\", errors[0])
            self.assertIn("deeply/nested/", errors[0])

    def test_symlink_aliases_to_same_dir_are_each_walked(self) -> None:
        """Two symlinks pointing at the same directory both get checked.

        Pinned regression: an earlier ``check_long_paths`` used a
        single realpath visited-set as cycle protection, so the
        second symlink alias to a directory was silently skipped.
        ``walk_skill_files`` (the bundler's actual walker) copies
        both aliases into the archive under their lexical names —
        skipping one here would let a long path under that alias
        pass the pre-flight and only fail at user-extract time.
        Switch to ancestry-based cycle protection so the helper
        walks every alias while still cutting off true cycles.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = self._make_skill_dir(tmpdir)
            shared_dir = os.path.join(skill_dir, "shared")
            os.makedirs(shared_dir)
            # arcname budget = threshold(60) - prefix(5) = 55.
            # Skill basename "demo-skill/" = 11 chars, then
            # ``shared/`` = 7 chars, then the filename.  40 x's +
            # ``.md`` (43) → ``demo-skill/shared/<40-x>.md`` is 61
            # chars, comfortably over the budget for every alias.
            self._build_skill_with_arcname(
                skill_dir, "shared/" + "x" * 40 + ".md",
            )
            # Create two sibling symlinks pointing at the same
            # ``shared/`` directory under different names.  Skip
            # the test if the host can't make symlinks (Windows
            # without DevMode etc.).
            try:
                os.symlink(
                    shared_dir, os.path.join(skill_dir, "alias-a"),
                    target_is_directory=True,
                )
                os.symlink(
                    shared_dir, os.path.join(skill_dir, "alias-b"),
                    target_is_directory=True,
                )
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported on this host")
            # threshold/budget chosen so the bare ``shared/x...md``
            # arcname fits but the alias-prefixed forms don't.
            errors, _ = check_long_paths(
                skill_dir, threshold=60, user_prefix_budget=5,
            )
            # The actual file appears at three lexical locations:
            # ``shared/<file>``, ``alias-a/<file>``, ``alias-b/<file>``.
            # All three must be reported (not deduped to one).
            shared_errors = [e for e in errors if "shared/" in e]
            alias_a_errors = [e for e in errors if "alias-a/" in e]
            alias_b_errors = [e for e in errors if "alias-b/" in e]
            self.assertGreaterEqual(len(shared_errors), 1)
            self.assertGreaterEqual(len(alias_a_errors), 1)
            self.assertGreaterEqual(len(alias_b_errors), 1)

    def test_arcname_includes_skill_basename(self) -> None:
        """Pinned regression: the basename must be counted.

        Reviewer finding: the previous implementation measured paths
        relative to the skill root only, so a path that exactly fit
        the budget would still exceed Windows MAX_PATH after
        extraction once the skill basename was prepended.  Verify
        that the basename does count toward the measured length.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = self._make_skill_dir(tmpdir)
            # File whose path-from-skill-root is short enough to fit
            # the budget if the basename were *not* counted, but
            # exceeds it once the basename prefix is added.
            #
            # threshold=20, prefix=2 → available=18.
            # bare arcname "x.md" = 4 chars (would pass).
            # with basename: "demo-skill/x.md" = 15 chars (still fits!).
            # We need a file that fits w/o basename but exceeds with.
            # threshold=14, prefix=2 → available=12.
            # bare arcname "x.md" = 4 chars (would pass).
            # with basename: "demo-skill/x.md" = 15 chars (FAILs).
            self._build_skill_with_arcname(skill_dir, "x.md")
            errors, _ = check_long_paths(
                skill_dir, threshold=14, user_prefix_budget=2,
            )
            self.assertEqual(len(errors), 1)
            # Error message names the prefixed arcname, not the
            # bare-from-skill-root form.
            self.assertIn(f"{self.SKILL_NAME}/x.md", errors[0])

    def test_findings_emitted_in_lexicographic_order(self) -> None:
        """Pinned regression: findings are sorted by POSIX rel-path.

        ``walk_skill_files`` inherits ``os.walk`` / ``os.listdir``
        ordering, which varies across filesystems and runners.  The
        helper sorts candidate rel-paths before emitting findings so
        finding text is byte-identical across hosts and downstream
        tests can assert full error lists without flaking.  Without
        this invariant, a future refactor that reverts to walker
        order would silently regress on the ubuntu-only matrix
        entry, since ext4 happens to yield in alphabetical-ish order
        on many trees.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = self._make_skill_dir(tmpdir)
            # Build over-budget files across multiple subdirectories;
            # the basenames are intentionally a mix so the sort
            # must compare across siblings, not just within a
            # single directory.
            arcnames = (
                "z_subdir/" + "a" * 50 + ".md",
                "a_subdir/" + "z" * 50 + ".md",
                "m_subdir/" + "m" * 50 + ".md",
                "z_subdir/" + "b" * 50 + ".md",
                "a_subdir/" + "y" * 50 + ".md",
            )
            for arcname in arcnames:
                self._build_skill_with_arcname(skill_dir, arcname)
            errors, _ = check_long_paths(
                skill_dir, threshold=60, user_prefix_budget=5,
            )
            self.assertEqual(len(errors), 5)
            # Extract the rel-path each finding names; the format is
            # ``LEVEL_FAIL: '<rel>' exceeds...`` so the rel sits
            # between the first pair of single quotes.
            rels = [re.search(r"'([^']+)'", e).group(1) for e in errors]
            self.assertEqual(
                rels,
                sorted(rels),
                msg=(
                    "check_long_paths must emit findings in "
                    "lexicographic POSIX-rel order — order observed "
                    "was " + repr(rels)
                ),
            )


@unittest.skipIf(
    sys.platform == "win32",
    "Cannot create reserved-name files (CON/AUX/NUL/...) on Windows; "
    "the rule under test is OS-independent and is verified on the "
    "ubuntu-latest matrix runner instead.",
)
class CheckReservedPathComponentsTests(unittest.TestCase):
    """``check_reserved_path_components`` flags reserved NTFS names.

    The frontmatter ``name`` rule (``validate_name``) catches the
    skill's own basename, but Windows reserves device names for
    every path component.  This helper walks the tree and FAILs when
    any directory or file name's stem matches one of the reserved
    names case-insensitively.

    Windows-runner skip note: Windows itself rejects creating
    ``CON``/``AUX``/``NUL`` files at the filesystem layer, so the
    fixture-construction calls below would error out before
    ``check_reserved_path_components`` is invoked.  The rule's
    logic does not depend on the host OS — it walks names against
    a configured list — so the matrix's ubuntu-latest run covers
    the behaviour, and the Windows skip avoids a false
    test failure that has nothing to do with the rule itself.
    """

    def _build(self, root: str, arcname: str) -> None:
        full = os.path.join(root, *arcname.split("/"))
        os.makedirs(os.path.dirname(full) or root, exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("body")

    def test_clean_skill_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo")
            os.makedirs(skill_dir)
            self._build(skill_dir, "SKILL.md")
            self._build(skill_dir, "references/guide.md")
            errors, passes = check_reserved_path_components(skill_dir)
            self.assertEqual(errors, [])
            self.assertEqual(len(passes), 1)

    def test_reserved_basename_fails(self) -> None:
        # A bundled file named ``con.md`` has stem ``CON`` —
        # illegal on NTFS regardless of host.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo")
            os.makedirs(skill_dir)
            self._build(skill_dir, "SKILL.md")
            self._build(skill_dir, "references/con.md")
            errors, _ = check_reserved_path_components(skill_dir)
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith(LEVEL_FAIL))
            self.assertIn("references/con.md", errors[0])
            self.assertIn("CON", errors[0])

    def test_reserved_directory_component_fails(self) -> None:
        # A directory named ``aux`` is illegal on NTFS too.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo")
            os.makedirs(skill_dir)
            self._build(skill_dir, "SKILL.md")
            self._build(skill_dir, "capabilities/aux/capability.md")
            errors, _ = check_reserved_path_components(skill_dir)
            # One FAIL for the ``aux`` directory; the file's own
            # stem (``capability``) is legal.
            aux_errors = [e for e in errors if "AUX" in e]
            self.assertEqual(len(aux_errors), 1)
            self.assertIn("capabilities/aux", aux_errors[0])

    def test_case_insensitive_match(self) -> None:
        # The match is case-insensitive — ``Nul.md`` is just as
        # illegal as ``nul.md`` or ``NUL.md``.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo")
            os.makedirs(skill_dir)
            self._build(skill_dir, "SKILL.md")
            self._build(skill_dir, "references/Nul.md")
            errors, _ = check_reserved_path_components(skill_dir)
            self.assertEqual(len(errors), 1)
            self.assertIn("NUL", errors[0])

    def test_severity_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo")
            os.makedirs(skill_dir)
            self._build(skill_dir, "SKILL.md")
            self._build(skill_dir, "references/con.md")
            errors, _ = check_reserved_path_components(
                skill_dir, severity=LEVEL_WARN,
            )
            self.assertTrue(errors[0].startswith(LEVEL_WARN))

    def test_skill_basename_is_checked(self) -> None:
        """A skill directory named ``con`` fails the rule.

        Pinned regression: the previous implementation measured
        components relative to the skill root, which stripped the
        skill basename before splitting.  A skill directory named
        ``con`` (with a legal frontmatter ``name``) would slip past
        the reserved-name check even though its basename becomes the
        archive's top-level entry — and Windows refuses to extract
        a zip whose root directory is a reserved device name.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "con")
            os.makedirs(skill_dir)
            self._build(skill_dir, "SKILL.md")
            errors, _ = check_reserved_path_components(skill_dir)
            con_errors = [e for e in errors if "CON" in e]
            self.assertGreaterEqual(len(con_errors), 1)
            # The error names the directory by its archive form
            # (the skill basename is now component 0 of the
            # measured rel-path).
            self.assertIn("'con'", con_errors[0])

    def test_com0_and_lpt0_are_legal(self) -> None:
        # Pinned regression: only COM1-COM9 / LPT1-LPT9 are
        # reserved on Windows.  ``com0.md`` / ``lpt0.md`` must NOT
        # fire.
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo")
            os.makedirs(skill_dir)
            self._build(skill_dir, "SKILL.md")
            self._build(skill_dir, "references/com0.md")
            self._build(skill_dir, "references/lpt0.md")
            errors, _ = check_reserved_path_components(skill_dir)
            self.assertEqual(errors, [])

    def test_trailing_space_or_dot_is_flagged(self) -> None:
        """Components like ``con `` / ``aux.`` are reserved on Windows.

        Windows trims trailing spaces and dots from path components
        before comparing against the device-name list, so a zip that
        carries ``con `` (legal on POSIX) cannot be extracted on
        Windows — it materialises as ``CON``.  The reserved-name
        check normalises components the same way so the pre-flight
        catches the shape on every host.
        """
        cases = (
            ("references/con .md", "CON"),
            ("references/aux..md", "AUX"),
            ("references/nul . .md", "NUL"),
        )
        for relpath, stem in cases:
            with self.subTest(relpath=relpath, stem=stem):
                with tempfile.TemporaryDirectory() as tmpdir:
                    skill_dir = os.path.join(tmpdir, "demo")
                    os.makedirs(skill_dir)
                    self._build(skill_dir, "SKILL.md")
                    self._build(skill_dir, relpath)
                    errors, _ = check_reserved_path_components(skill_dir)
                    matched = [e for e in errors if stem in e]
                    self.assertEqual(
                        len(matched), 1,
                        msg=(
                            f"expected one {stem} finding for {relpath}; "
                            f"got errors={errors}"
                        ),
                    )

    def test_findings_emitted_in_lexicographic_order(self) -> None:
        """Pinned regression: findings are sorted by POSIX rel-path.

        Same invariant as ``CheckLongPathsTests``: collecting and
        sorting candidate rel-paths before emitting findings makes
        the output byte-identical across runners.  The dedup ``seen``
        set folds duplicate (component, stem) pairs so reported
        findings still match between hosts even when the underlying
        walk order differs.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo")
            os.makedirs(skill_dir)
            self._build(skill_dir, "SKILL.md")
            # Three reserved-name files in distinct sibling
            # directories so dedup does not collapse the findings.
            # Lexicographic order is determined by the POSIX rel
            # path (with the skill basename prefix), so the expected
            # order is ``demo/a/...``, ``demo/m/...``, ``demo/z/...``.
            self._build(skill_dir, "z_subdir/nul.md")
            self._build(skill_dir, "a_subdir/con.md")
            self._build(skill_dir, "m_subdir/aux.md")
            errors, _ = check_reserved_path_components(skill_dir)
            self.assertEqual(len(errors), 3)
            # Each finding text contains the offending POSIX rel
            # path between the first pair of single quotes.
            rels = [re.search(r"'([^']+)'", e).group(1) for e in errors]
            self.assertEqual(
                rels,
                sorted(rels),
                msg=(
                    "check_reserved_path_components must emit "
                    "findings in lexicographic POSIX-rel order — "
                    "order observed was " + repr(rels)
                ),
            )


class CheckExternalArcnamesTests(unittest.TestCase):
    """``check_external_arcnames`` runs the long-path and reserved-name
    rules against pre-computed arcname strings so the bundle pre-flight
    can verify externals BEFORE ``create_bundle`` copies them.
    """

    def test_empty_input_is_clean(self) -> None:
        errors, passes = check_external_arcnames([])
        self.assertEqual(errors, [])
        self.assertEqual(passes, [])

    def test_under_threshold_passes(self) -> None:
        errors, _ = check_external_arcnames(
            ["demo/SKILL.md", "demo/references/guide.md"],
            threshold=260,
            user_prefix_budget=80,
        )
        self.assertEqual(errors, [])

    def test_over_threshold_fails(self) -> None:
        long_arcname = "demo/" + ("x" * 80) + ".md"
        errors, _ = check_external_arcnames(
            [long_arcname], threshold=60, user_prefix_budget=10,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn(long_arcname, errors[0])

    def test_reserved_basename_fails(self) -> None:
        errors, _ = check_external_arcnames(
            ["demo/references/con.md"],
        )
        con_errors = [e for e in errors if "CON" in e]
        self.assertEqual(len(con_errors), 1)

    def test_reserved_directory_fails(self) -> None:
        errors, _ = check_external_arcnames(
            ["demo/aux/inner/file.md"],
        )
        aux_errors = [e for e in errors if "AUX" in e]
        self.assertEqual(len(aux_errors), 1)

    def test_severity_override(self) -> None:
        errors, _ = check_external_arcnames(
            ["demo/" + ("x" * 80) + ".md"],
            threshold=60,
            user_prefix_budget=10,
            severity=LEVEL_WARN,
        )
        self.assertTrue(errors[0].startswith(LEVEL_WARN))

    def test_trailing_space_or_dot_is_flagged(self) -> None:
        """External arcnames with trailing spaces/dots are also flagged.

        Mirrors the same NTFS normalisation as
        ``check_reserved_path_components`` — Windows trims trailing
        spaces and dots before comparing path components against the
        device-name list, so a bundled external named ``con `` becomes
        ``CON`` on extraction.  Both pre-flight helpers must agree so
        an external arcname slipped past the directory walk does not
        bypass the check.
        """
        cases = (
            ("demo/references/con .md", "CON"),
            ("demo/references/aux..md", "AUX"),
            ("demo/nul ./inner/file.md", "NUL"),
        )
        for arcname, stem in cases:
            with self.subTest(arcname=arcname, stem=stem):
                errors, _ = check_external_arcnames([arcname])
                matched = [e for e in errors if stem in e]
                self.assertEqual(
                    len(matched), 1,
                    msg=(
                        f"expected one {stem} finding for {arcname}; "
                        f"got errors={errors}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
