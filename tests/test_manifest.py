"""Unit tests for lib/manifest.py.

Tests cover manifest reading, conflict detection, entry appending,
and scaffolding an empty manifest.
"""

import os
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.manifest import (
    ManifestParseError,
    read_manifest,
    has_skill_conflict,
    has_role_conflict,
    append_skill_entry,
    append_role_entry,
    scaffold_empty_manifest,
    update_manifest_for_skill,
    update_manifest_for_role,
)


SAMPLE_MANIFEST = """\
# Skill System Manifest

skills:
  existing-skill:
    canonical: skills/existing-skill/SKILL.md
    type: standalone

roles:
  dev-group:
    - name: existing-role
      path: roles/dev-group/existing-role.md
"""


class ReadManifestTests(unittest.TestCase):
    """Test reading and parsing a manifest file."""

    def test_read_existing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            result = read_manifest(path)
        self.assertIsInstance(result, dict)
        self.assertIn("skills", result)
        self.assertIn("roles", result)

    def test_read_nonexistent_returns_empty(self) -> None:
        result = read_manifest("/nonexistent/path/manifest.yaml")
        self.assertEqual(result, {})

    def test_read_empty_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
            result = read_manifest(path)
        self.assertEqual(result, {})

    def test_parsed_skill_has_expected_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            result = read_manifest(path)
        skills = result["skills"]
        self.assertIn("existing-skill", skills)
        self.assertEqual(skills["existing-skill"]["type"], "standalone")


class ConflictDetectionTests(unittest.TestCase):
    """Test name conflict detection for skills and roles."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "manifest.yaml")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_MANIFEST)
        self.manifest = read_manifest(self.path)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_skill_conflict_detected(self) -> None:
        self.assertTrue(has_skill_conflict(self.manifest, "existing-skill"))

    def test_no_skill_conflict_for_new_name(self) -> None:
        self.assertFalse(has_skill_conflict(self.manifest, "new-skill"))

    def test_skill_conflict_empty_manifest(self) -> None:
        self.assertFalse(has_skill_conflict({}, "any-name"))

    def test_role_conflict_detected(self) -> None:
        self.assertTrue(has_role_conflict(self.manifest, "dev-group", "existing-role"))

    def test_no_role_conflict_for_new_name(self) -> None:
        self.assertFalse(has_role_conflict(self.manifest, "dev-group", "new-role"))

    def test_no_role_conflict_for_new_group(self) -> None:
        self.assertFalse(has_role_conflict(self.manifest, "other-group", "existing-role"))

    def test_role_conflict_empty_manifest(self) -> None:
        self.assertFalse(has_role_conflict({}, "any-group", "any-name"))


class AppendSkillEntryTests(unittest.TestCase):
    """Test appending skill entries to a manifest."""

    def test_append_standalone_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            append_skill_entry(path, "new-skill")
            result = read_manifest(path)
        self.assertIn("new-skill", result["skills"])
        self.assertEqual(result["skills"]["new-skill"]["type"], "standalone")
        self.assertEqual(
            result["skills"]["new-skill"]["canonical"],
            "skills/new-skill/SKILL.md",
        )

    def test_append_router_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            append_skill_entry(path, "my-router", router=True)
            result = read_manifest(path)
        self.assertIn("my-router", result["skills"])
        self.assertEqual(result["skills"]["my-router"]["type"], "router")

    def test_append_to_empty_skills_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            append_skill_entry(path, "first-skill")
            result = read_manifest(path)
        self.assertIn("first-skill", result["skills"])

    def test_append_preserves_existing_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            append_skill_entry(path, "new-skill")
            result = read_manifest(path)
        self.assertIn("existing-skill", result["skills"])
        self.assertIn("new-skill", result["skills"])


class AppendRoleEntryTests(unittest.TestCase):
    """Test appending role entries to a manifest."""

    def test_append_role_to_existing_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            append_role_entry(path, "dev-group", "new-role")
            result = read_manifest(path)
        roles = result["roles"]["dev-group"]
        names = [r["name"] for r in roles if isinstance(r, dict)]
        self.assertIn("new-role", names)

    def test_append_role_to_new_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            append_role_entry(path, "ops-group", "ops-role")
            result = read_manifest(path)
        self.assertIn("ops-group", result["roles"])
        roles = result["roles"]["ops-group"]
        names = [r["name"] for r in roles if isinstance(r, dict)]
        self.assertIn("ops-role", names)

    def test_append_role_preserves_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            append_role_entry(path, "dev-group", "new-role")
            result = read_manifest(path)
        roles = result["roles"]["dev-group"]
        names = [r["name"] for r in roles if isinstance(r, dict)]
        self.assertIn("existing-role", names)
        self.assertIn("new-role", names)

    def test_append_role_to_group_with_inline_comment(self) -> None:
        """Group headers with inline comments are recognized and not duplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "roles:\n"
                    "  dev-group:  # development roles\n"
                    "    - name: existing-role\n"
                    "      path: roles/dev-group/existing-role.md\n"
                )
            append_role_entry(path, "dev-group", "new-role")
            result = read_manifest(path)
            # Should have only one dev-group, not a duplicate
            roles = result["roles"]["dev-group"]
            names = [r["name"] for r in roles if isinstance(r, dict)]
            self.assertIn("existing-role", names)
            self.assertIn("new-role", names)
            # Verify no duplicate group was created
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # Count occurrences of "dev-group:" - should be exactly 1
            group_count = text.count("dev-group:")
            self.assertEqual(group_count, 1, "Group header should not be duplicated")

    def test_find_group_with_four_space_indent(self) -> None:
        """Group headers with 4-space indentation are recognized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "roles:\n"
                    "    dev-group:\n"
                    "        - name: existing-role\n"
                    "          path: roles/dev-group/existing-role.md\n"
                )
            append_role_entry(path, "dev-group", "new-role")
            result = read_manifest(path)
        # Should have only one dev-group, not a duplicate
        roles = result["roles"]["dev-group"]
        names = [r["name"] for r in roles if isinstance(r, dict)]
        self.assertIn("existing-role", names)
        self.assertIn("new-role", names)

    def test_append_role_to_empty_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            append_role_entry(path, "my-group", "my-role")
            result = read_manifest(path)
        self.assertIn("my-group", result["roles"])


class ScaffoldEmptyManifestTests(unittest.TestCase):
    """Test scaffolding a new empty manifest."""

    def test_creates_manifest_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            self.assertTrue(os.path.isfile(path))

    def test_manifest_has_skills_and_roles_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        self.assertIn("skills:", text)
        self.assertIn("roles:", text)

    def test_manifest_is_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            result = read_manifest(path)
        self.assertIsInstance(result, dict)

    def test_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "dir", "manifest.yaml")
            scaffold_empty_manifest(path)
            self.assertTrue(os.path.isfile(path))


class SequentialAppendTests(unittest.TestCase):
    """Test multiple sequential appends produce valid YAML."""

    def test_two_skill_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            append_skill_entry(path, "skill-a")
            append_skill_entry(path, "skill-b", router=True)
            result = read_manifest(path)
        self.assertIn("existing-skill", result["skills"])
        self.assertIn("skill-a", result["skills"])
        self.assertIn("skill-b", result["skills"])
        self.assertEqual(result["skills"]["skill-a"]["type"], "standalone")
        self.assertEqual(result["skills"]["skill-b"]["type"], "router")

    def test_two_role_appends_same_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            append_role_entry(path, "dev-group", "role-a")
            append_role_entry(path, "dev-group", "role-b")
            result = read_manifest(path)
        roles = result["roles"]["dev-group"]
        names = [r["name"] for r in roles if isinstance(r, dict)]
        self.assertIn("existing-role", names)
        self.assertIn("role-a", names)
        self.assertIn("role-b", names)

    def test_two_role_appends_different_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            append_role_entry(path, "ops-group", "ops-role")
            append_role_entry(path, "qa-group", "qa-role")
            result = read_manifest(path)
        self.assertIn("ops-group", result["roles"])
        self.assertIn("qa-group", result["roles"])
        ops_names = [r["name"] for r in result["roles"]["ops-group"] if isinstance(r, dict)]
        qa_names = [r["name"] for r in result["roles"]["qa-group"] if isinstance(r, dict)]
        self.assertIn("ops-role", ops_names)
        self.assertIn("qa-role", qa_names)

    def test_mixed_skill_and_role_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            append_skill_entry(path, "first-skill")
            append_role_entry(path, "my-group", "first-role")
            append_skill_entry(path, "second-skill")
            result = read_manifest(path)
        self.assertIn("first-skill", result["skills"])
        self.assertIn("second-skill", result["skills"])
        self.assertIn("my-group", result["roles"])


class NoTrailingNewlineTests(unittest.TestCase):
    """Test appending to manifests without a trailing newline."""

    def test_skill_append_no_trailing_newline(self) -> None:
        manifest_text = "skills:\n  old:\n    canonical: skills/old/SKILL.md\n    type: standalone"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(manifest_text)
            append_skill_entry(path, "new-skill")
            result = read_manifest(path)
        self.assertIn("old", result["skills"])
        self.assertIn("new-skill", result["skills"])

    def test_role_append_no_trailing_newline(self) -> None:
        manifest_text = "roles:\n  grp:\n    - name: old-role\n      path: roles/grp/old-role.md"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(manifest_text)
            append_role_entry(path, "grp", "new-role")
            result = read_manifest(path)
        roles = result["roles"]["grp"]
        names = [r["name"] for r in roles if isinstance(r, dict)]
        self.assertIn("old-role", names)
        self.assertIn("new-role", names)

    def test_skill_append_no_skills_section_no_newline(self) -> None:
        manifest_text = "roles:"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(manifest_text)
            append_skill_entry(path, "added-skill")
            result = read_manifest(path)
        self.assertIn("added-skill", result["skills"])


class ManifestParseErrorTests(unittest.TestCase):
    """Test error handling for malformed manifests."""

    def test_value_error_wrapped_as_manifest_parse_error(self) -> None:
        """read_manifest wraps ValueError from the parser into ManifestParseError."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n  some: value\n")
            with patch(
                "lib.manifest.parse_yaml_subset",
                side_effect=ValueError("mock parse failure"),
            ):
                with self.assertRaises(ManifestParseError) as ctx:
                    read_manifest(path)
                self.assertIn("mock parse failure", str(ctx.exception))

    def test_valid_yaml_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            result = read_manifest(path)
        self.assertIsInstance(result, dict)

    def test_skills_as_list_raises_manifest_parse_error(self) -> None:
        """A manifest where skills is a list (not a mapping) raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n  - item1\n  - item2\n")
            with self.assertRaises(ManifestParseError) as ctx:
                read_manifest(path)
            self.assertIn("'skills' must be a mapping", str(ctx.exception))

    def test_roles_as_scalar_raises_manifest_parse_error(self) -> None:
        """A manifest where roles is a scalar string raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n\nroles: not-a-mapping\n")
            with self.assertRaises(ManifestParseError) as ctx:
                read_manifest(path)
            self.assertIn("'roles' must be a mapping", str(ctx.exception))

    def test_top_level_not_mapping_raises_manifest_parse_error(self) -> None:
        """A manifest where top-level is not a mapping raises."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n  some: value\n")
            with patch(
                "lib.manifest.parse_yaml_subset",
                return_value=["not", "a", "dict"],
            ):
                with self.assertRaises(ManifestParseError) as ctx:
                    read_manifest(path)
                self.assertIn(
                    "top-level YAML must be a mapping", str(ctx.exception)
                )

    def test_top_level_list_raises_manifest_parse_error(self) -> None:
        """A manifest that is a top-level list (not a mapping) raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("- item1\n- item2\n")
            with self.assertRaises(ManifestParseError) as ctx:
                read_manifest(path)
            self.assertIn("top-level YAML must be a mapping", str(ctx.exception))

    def test_skills_as_empty_list_raises_manifest_parse_error(self) -> None:
        """A manifest where skills parses as a list rejects even if falsey."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n  - standalone-item\nroles:\n")
            with self.assertRaises(ManifestParseError) as ctx:
                read_manifest(path)
            self.assertIn("'skills' must be a mapping", str(ctx.exception))

    def test_role_group_as_scalar_raises_manifest_parse_error(self) -> None:
        """A manifest where a role group is a scalar (not a list) raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n\nroles:\n  my-group: not-a-list\n")
            with self.assertRaises(ManifestParseError) as ctx:
                read_manifest(path)
            self.assertIn("role group 'my-group' must be a list", str(ctx.exception))

    def test_role_group_as_mapping_raises_manifest_parse_error(self) -> None:
        """A manifest where a role group is a mapping (not a list) raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n\n"
                    "roles:\n"
                    "  bad-group:\n"
                    "    nested-key: value\n"
                )
            with self.assertRaises(ManifestParseError) as ctx:
                read_manifest(path)
            self.assertIn("role group 'bad-group' must be a list", str(ctx.exception))

    def test_valid_role_group_does_not_raise(self) -> None:
        """A manifest where role groups are lists passes validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            result = read_manifest(path)
        self.assertIsInstance(result["roles"]["dev-group"], list)

    def test_empty_role_group_does_not_raise(self) -> None:
        """A manifest where a role group is empty (None/empty string) passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n\nroles:\n  empty-group:\n")
            result = read_manifest(path)
        self.assertIsInstance(result, dict)

    def test_top_level_list_after_section_raises_error(self) -> None:
        """Top-level list items after a valid section are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n  some: value\n- item\n")
            with self.assertRaises(ManifestParseError) as ctx:
                read_manifest(path)
            self.assertIn("top-level YAML must be a mapping", str(ctx.exception))

    def test_malformed_content_parsing_to_empty_dict_raises(self) -> None:
        """Malformed content that parses to empty dict is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("not_a_valid_yaml_structure\n")
            with self.assertRaises(ManifestParseError) as ctx:
                read_manifest(path)
            self.assertIn("malformed YAML content", str(ctx.exception))


class AppendSkillSectionOrderTests(unittest.TestCase):
    """Test that append_skill_entry preserves canonical section order."""

    def test_skills_inserted_before_roles_when_missing(self) -> None:
        """When skills: is missing but roles: exists, skills: is inserted before roles:."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("roles:\n  dev:\n    - name: r\n      path: roles/dev/r.md\n")
            append_skill_entry(path, "new-skill")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            skills_pos = text.index("skills:")
            roles_pos = text.index("roles:")
            self.assertLess(skills_pos, roles_pos)
            result = read_manifest(path)
            self.assertIn("new-skill", result["skills"])
            # Roles should still be intact.
            self.assertIn("dev", result["roles"])


class InlineCommentTests(unittest.TestCase):
    """Test that inline comments on section/group headers don't cause duplicates."""

    MANIFEST_WITH_COMMENTS = (
        "# Manifest\n"
        "\n"
        "skills: # all skills\n"
        "  existing:\n"
        "    canonical: skills/existing/SKILL.md\n"
        "    type: standalone\n"
        "\n"
        "roles: # all roles\n"
        "  dev-group: # developers\n"
        "    - name: existing-role\n"
        "      path: roles/dev-group/existing-role.md\n"
    )

    def test_skill_appended_to_section_with_inline_comment(self) -> None:
        """append_skill_entry finds skills: even with an inline comment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_WITH_COMMENTS)
            append_skill_entry(path, "new-skill")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # Must NOT have a duplicate skills: section.
            self.assertEqual(text.count("skills:"), 1)
            result = read_manifest(path)
            self.assertIn("existing", result["skills"])
            self.assertIn("new-skill", result["skills"])

    def test_role_appended_to_section_with_inline_comment(self) -> None:
        """append_role_entry finds roles: even with an inline comment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_WITH_COMMENTS)
            append_role_entry(path, "ops-group", "ops-role")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # Must NOT have a duplicate roles: section.
            self.assertEqual(text.count("roles:"), 1)
            result = read_manifest(path)
            self.assertIn("dev-group", result["roles"])
            self.assertIn("ops-group", result["roles"])

    def test_role_appended_to_group_with_inline_comment(self) -> None:
        """append_role_entry finds existing group even with an inline comment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_WITH_COMMENTS)
            append_role_entry(path, "dev-group", "new-role")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # Must NOT have a duplicate dev-group: key.
            self.assertEqual(text.count("dev-group:"), 1)
            result = read_manifest(path)
            roles = result["roles"]["dev-group"]
            names = [r["name"] for r in roles if isinstance(r, dict)]
            self.assertIn("existing-role", names)
            self.assertIn("new-role", names)

    def test_skill_section_order_preserved_with_inline_comments(self) -> None:
        """When skills: has inline comment, new skill still goes into correct section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_WITH_COMMENTS)
            append_skill_entry(path, "second-skill")
            append_skill_entry(path, "third-skill", router=True)
            result = read_manifest(path)
            self.assertIn("existing", result["skills"])
            self.assertIn("second-skill", result["skills"])
            self.assertIn("third-skill", result["skills"])
            self.assertEqual(result["skills"]["third-skill"]["type"], "router")

    def test_update_manifest_for_skill_with_inline_comments(self) -> None:
        """End-to-end: update_manifest_for_skill works on manifest with inline comments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_WITH_COMMENTS)
            updated, warning, created = update_manifest_for_skill(path, "added")
            self.assertTrue(updated)
            self.assertIsNone(warning)
            self.assertFalse(created)
            result = read_manifest(path)
            self.assertIn("added", result["skills"])

    def test_update_manifest_for_role_with_inline_comments(self) -> None:
        """End-to-end: update_manifest_for_role works on manifest with inline comments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_WITH_COMMENTS)
            updated, warning, created = update_manifest_for_role(
                path, "dev-group", "added-role",
            )
            self.assertTrue(updated)
            self.assertIsNone(warning)
            self.assertFalse(created)
            result = read_manifest(path)
            names = [r["name"] for r in result["roles"]["dev-group"] if isinstance(r, dict)]
            self.assertIn("added-role", names)

    def test_conflict_detected_with_inline_comments(self) -> None:
        """Conflict detection works when sections have inline comments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_WITH_COMMENTS)
            updated, warning, _ = update_manifest_for_skill(path, "existing")
            self.assertFalse(updated)
            self.assertIn("already exists", warning)


class CommentIndentInferenceTests(unittest.TestCase):
    """Test that indented comments don't corrupt indent inference."""

    def test_group_found_after_indented_comment(self) -> None:
        """Indented comment before group header doesn't prevent finding the group."""
        manifest = (
            "roles:\n"
            "  # a comment\n"
            "    dev-group:\n"
            "        - name: existing\n"
            "            path: roles/dev-group/existing.md\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(manifest)
            append_role_entry(path, "dev-group", "new-role")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # Must NOT have a duplicate dev-group: key.
            self.assertEqual(text.count("dev-group:"), 1)

    def test_skill_indent_inferred_past_comment(self) -> None:
        """Indented comment under skills: doesn't drive indent inference."""
        manifest = (
            "skills:\n"
            "  # skill section comment\n"
            "    existing:\n"
            "        canonical: skills/existing/SKILL.md\n"
            "        type: standalone\n"
            "\n"
            "roles:\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(manifest)
            append_skill_entry(path, "new-skill")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # New skill key should be at 4-space indent (matching existing), not 2-space.
            self.assertIn("    new-skill:", text)


class IndentationInferenceTests(unittest.TestCase):
    """Test that appended entries match the indentation of existing entries."""

    MANIFEST_4SPACE_SKILLS = (
        "skills:\n"
        "    existing:\n"
        "        canonical: skills/existing/SKILL.md\n"
        "        type: standalone\n"
        "\n"
        "roles:\n"
    )

    MANIFEST_4SPACE_ROLES = (
        "skills:\n"
        "\n"
        "roles:\n"
        "    dev-group:\n"
        "        - name: existing-role\n"
        "            path: roles/dev-group/existing-role.md\n"
    )

    def test_skill_entry_matches_existing_indent(self) -> None:
        """New skill key uses the same indent as existing skill keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_4SPACE_SKILLS)
            append_skill_entry(path, "new-skill")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # The new skill key should be at 4-space indent.
            self.assertIn("    new-skill:", text)
            # Its children should be at 8-space indent (matching existing).
            self.assertIn("        canonical:", text)
            self.assertIn("        type:", text)

    def test_role_group_matches_existing_indent(self) -> None:
        """New role group uses the same indent as existing groups."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_4SPACE_ROLES)
            append_role_entry(path, "ops-group", "ops-role")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # New group should be at 4-space indent (matching dev-group).
            self.assertIn("    ops-group:", text)

    def test_role_entry_in_existing_group_matches_indent(self) -> None:
        """New role entry in existing group uses the same indent as siblings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_4SPACE_ROLES)
            append_role_entry(path, "dev-group", "new-role")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # Entry should be at 8-space indent (matching existing entries).
            self.assertIn("        - name: new-role", text)

    def test_default_indent_when_section_empty(self) -> None:
        """Falls back to 2-space indent when section has no existing children."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            append_skill_entry(path, "first-skill")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # Default 2-space indent for skill key.
            self.assertIn("  first-skill:", text)
            result = read_manifest(path)
            self.assertIn("first-skill", result["skills"])

    def test_roundtrip_with_nonstandard_indent(self) -> None:
        """Full roundtrip: write 4-space manifest, append, read back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.MANIFEST_4SPACE_SKILLS)
            append_skill_entry(path, "added", router=True)
            result = read_manifest(path)
            self.assertIn("existing", result["skills"])
            self.assertIn("added", result["skills"])
            self.assertEqual(result["skills"]["added"]["type"], "router")


class SpaceBeforeColonTests(unittest.TestCase):
    """Test that space-before-colon YAML syntax is handled correctly."""

    def test_find_section_with_space_before_colon(self) -> None:
        """Section headers with space before colon are recognized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills :\n  existing:\n    canonical: skills/existing/SKILL.md\n    type: standalone\n")
            append_skill_entry(path, "new-skill")
            result = read_manifest(path)
        self.assertIn("new-skill", result["skills"])

    def test_find_group_with_space_before_colon(self) -> None:
        """Group headers with space before colon are recognized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "roles:\n"
                    "  dev-group :\n"  # Space before colon
                    "    - name: existing-role\n"
                    "      path: roles/dev-group/existing-role.md\n"
                )
            append_role_entry(path, "dev-group", "new-role")
            result = read_manifest(path)
        # Should have only one dev-group
        roles = result["roles"]["dev-group"]
        names = [r["name"] for r in roles if isinstance(r, dict)]
        self.assertIn("existing-role", names)
        self.assertIn("new-role", names)


class TopLevelCommentTests(unittest.TestCase):
    """Test that top-level comments don't prematurely end section scanning."""

    def test_section_end_with_top_level_comment(self) -> None:
        """Top-level comments don't prematurely end section scanning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "  existing-skill:\n"
                    "    canonical: skills/existing-skill/SKILL.md\n"
                    "    type: standalone\n"
                    "# This is a comment\n"
                    "roles:\n"
                )
            append_skill_entry(path, "new-skill")
            result = read_manifest(path)
        # Both skills should be present
        self.assertIn("existing-skill", result["skills"])
        self.assertIn("new-skill", result["skills"])

    def test_find_group_with_top_level_comment(self) -> None:
        """Top-level comments don't stop group scanning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "roles:\n"
                    "  dev-group:\n"
                    "    - name: existing-role\n"
                    "      path: roles/dev-group/existing-role.md\n"
                    "# This is a comment\n"
                    "  ops-group:\n"
                    "    - name: ops-role\n"
                    "      path: roles/ops-group/ops-role.md\n"
                )
            append_role_entry(path, "ops-group", "new-role")
            result = read_manifest(path)
        # Should append to ops-group, not create duplicate
        roles = result["roles"]["ops-group"]
        names = [r["name"] for r in roles if isinstance(r, dict)]
        self.assertIn("ops-role", names)
        self.assertIn("new-role", names)

    def test_append_skill_with_four_space_indent(self) -> None:
        """Skill entries match 4-space indentation of existing entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "skills:\n"
                    "    existing-skill:\n"
                    "        canonical: skills/existing-skill/SKILL.md\n"
                    "        type: standalone\n"
                )
            append_skill_entry(path, "new-skill")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # Verify new skill uses 4-space indent
            self.assertIn("    new-skill:", text)
            self.assertIn("        canonical: skills/new-skill/SKILL.md", text)


class UpdateManifestForSkillTests(unittest.TestCase):
    """Test the update_manifest_for_skill library function."""

    def test_creates_manifest_and_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            updated, warning, created = update_manifest_for_skill(path, "my-skill")
            self.assertTrue(updated)
            self.assertIsNone(warning)
            self.assertTrue(created)
            result = read_manifest(path)
            self.assertIn("my-skill", result["skills"])

    def test_appends_to_existing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            updated, warning, created = update_manifest_for_skill(path, "my-skill")
            self.assertTrue(updated)
            self.assertIsNone(warning)
            self.assertFalse(created)

    def test_conflict_returns_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            updated, warning, created = update_manifest_for_skill(
                path, "existing-skill",
            )
            self.assertFalse(updated)
            self.assertIsNotNone(warning)
            self.assertIn("already exists", warning)
            self.assertFalse(created)

    def test_malformed_manifest_returns_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n  - item1\n  - item2\n")
            updated, warning, created = update_manifest_for_skill(path, "x")
            self.assertFalse(updated)
            self.assertIsNotNone(warning)
            self.assertIn("skipping manifest update", warning)
            self.assertFalse(created)

    def test_router_flag_passed_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            updated, warning, created = update_manifest_for_skill(
                path, "my-router", router=True,
            )
            self.assertTrue(updated)
            result = read_manifest(path)
            self.assertEqual(result["skills"]["my-router"]["type"], "router")

    def test_update_manifest_for_skill_empty_file(self) -> None:
        """Empty manifest files are treated as missing and scaffolded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            # Create empty file
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
            updated, warning, created = update_manifest_for_skill(path, "my-skill")
            self.assertTrue(updated)
            self.assertIsNone(warning)
            self.assertTrue(created)  # Should report created_manifest=True
            # Verify it has the standard structure
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            self.assertIn("# Skill System Manifest", text)
            self.assertIn("skills:", text)
            self.assertIn("roles:", text)


class UpdateManifestForRoleTests(unittest.TestCase):
    """Test the update_manifest_for_role library function."""

    def test_creates_manifest_and_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            updated, warning, created = update_manifest_for_role(
                path, "my-group", "my-role",
            )
            self.assertTrue(updated)
            self.assertIsNone(warning)
            self.assertTrue(created)
            result = read_manifest(path)
            self.assertIn("my-group", result["roles"])

    def test_appends_to_existing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            scaffold_empty_manifest(path)
            updated, warning, created = update_manifest_for_role(
                path, "grp", "new-role",
            )
            self.assertTrue(updated)
            self.assertIsNone(warning)
            self.assertFalse(created)

    def test_conflict_returns_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MANIFEST)
            updated, warning, created = update_manifest_for_role(
                path, "dev-group", "existing-role",
            )
            self.assertFalse(updated)
            self.assertIsNotNone(warning)
            self.assertIn("already exists", warning)
            self.assertFalse(created)

    def test_malformed_manifest_returns_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("roles: not-a-mapping\n")
            updated, warning, created = update_manifest_for_role(
                path, "grp", "r",
            )
            self.assertFalse(updated)
            self.assertIsNotNone(warning)
            self.assertIn("skipping manifest update", warning)
            self.assertFalse(created)

    def test_non_list_role_group_returns_warning(self) -> None:
        """A role group that is a scalar triggers a warning and skips update."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("skills:\n\nroles:\n  my-group: not-a-list\n")
            updated, warning, created = update_manifest_for_role(
                path, "my-group", "new-role",
            )
            self.assertFalse(updated)
            self.assertIsNotNone(warning)
            self.assertIn("skipping manifest update", warning)
            self.assertFalse(created)

    def test_update_manifest_for_role_empty_file(self) -> None:
        """Empty manifest files are treated as missing and scaffolded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "manifest.yaml")
            # Create empty file
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
            updated, warning, created = update_manifest_for_role(path, "my-group", "my-role")
            self.assertTrue(updated)
            self.assertIsNone(warning)
            self.assertTrue(created)  # Should report created_manifest=True
            # Verify it has the standard structure
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            self.assertIn("# Skill System Manifest", text)
            self.assertIn("skills:", text)
            self.assertIn("roles:", text)


if __name__ == "__main__":
    unittest.main()
