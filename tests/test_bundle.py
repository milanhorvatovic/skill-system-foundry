import os
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
    _copy_external_files,
    _copy_inlined_skills,
    _copy_skill,
    _rewrite_markdown_content,
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


if __name__ == "__main__":
    unittest.main()
