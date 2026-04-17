"""Tests for lib/codex_config.py.

Covers validation of the optional ``agents/openai.yaml`` Codex
configuration file: interface fields (display_name, short_description,
icon paths, brand_color, default_prompt), policy settings, dependency
tool entries, and integration with validate_skill.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

from helpers import write_text, write_skill_md

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.codex_config import (
    validate_codex_config,
    _validate_interface,
    _validate_tool_entry,
    _is_valid_relative_path,
)
from lib.constants import (
    CODEX_MAX_DISPLAY_NAME_LENGTH,
    CODEX_MAX_SHORT_DESCRIPTION_LENGTH,
    FILE_CODEX_CONFIG,
    LEVEL_FAIL,
    LEVEL_INFO,
    LEVEL_WARN,
)
from validate_skill import validate_skill


def _write_codex_config(skill_dir: str, content: str) -> None:
    """Write an ``agents/openai.yaml`` file inside *skill_dir*."""
    write_text(os.path.join(skill_dir, FILE_CODEX_CONFIG), content)


# ===================================================================
# File Absence / Presence
# ===================================================================


class CodexConfigAbsenceTests(unittest.TestCase):
    """Tests for skills without agents/openai.yaml."""

    def test_missing_file_returns_empty(self) -> None:
        """A skill without agents/openai.yaml produces no errors or passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            errors, passes = validate_codex_config(tmpdir)
        self.assertEqual(errors, [])
        self.assertEqual(passes, [])

    def test_empty_file_returns_warn(self) -> None:
        """An empty agents/openai.yaml produces a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, "")
            errors, passes = validate_codex_config(tmpdir)
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_WARN, errors[0])
        self.assertIn("empty", errors[0])

    def test_whitespace_only_file_returns_warn(self) -> None:
        """A whitespace-only agents/openai.yaml produces a WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, "   \n  \n")
            errors, passes = validate_codex_config(tmpdir)
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_WARN, errors[0])
        self.assertIn("empty", errors[0])

    def test_comment_only_file_returns_warn(self) -> None:
        """A comment-only agents/openai.yaml is treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, "# TODO: configure later\n# another comment\n")
            errors, passes = validate_codex_config(tmpdir)
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_WARN, errors[0])
        self.assertIn("empty", errors[0])
        self.assertIn("comments only", errors[0])


# ===================================================================
# Valid Configuration
# ===================================================================


class CodexConfigValidTests(unittest.TestCase):
    """Tests for valid agents/openai.yaml files."""

    def test_minimal_valid_config(self) -> None:
        """A minimal valid config with just interface section passes."""
        config = (
            "interface:\n"
            '  display_name: "My Skill"\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        display_pass = [p for p in passes if "display_name" in p]
        self.assertEqual(len(display_pass), 1)

    def test_full_valid_config(self) -> None:
        """A fully populated valid config produces no FAIL errors."""
        config = (
            "interface:\n"
            '  display_name: "Deploy Manager"\n'
            '  short_description: "Deploy applications to production"\n'
            '  icon_small: "./assets/deploy-icon.svg"\n'
            '  icon_large: "./assets/deploy-icon-large.svg"\n'
            '  brand_color: "#10B981"\n'
            '  default_prompt: "Deploy the application"\n'
            "policy:\n"
            "  allow_implicit_invocation: false\n"
            "dependencies:\n"
            "  tools:\n"
            "    - type: mcp\n"
            '      value: deploy-server\n'
            '      description: "Deployment orchestration"\n'
            "      transport: streamable_http\n"
            '      url: "http://localhost:3000/mcp"\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [], msg=f"errors={errors}")
        # Should have passes for display_name, short_description,
        # icon_small, icon_large, brand_color, default_prompt,
        # policy, tools, and overall valid
        self.assertGreaterEqual(len(passes), 5, msg=f"passes={passes}")

    def test_empty_sections_pass(self) -> None:
        """A config with empty optional sections produces no errors."""
        config = "interface:\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])


# ===================================================================
# Interface Validation
# ===================================================================


class CodexConfigInterfaceTests(unittest.TestCase):
    """Tests for interface section validation."""

    def test_display_name_exceeding_max_returns_warn(self) -> None:
        """A display_name exceeding the max length produces a WARN (platform)."""
        long_name = "x" * (CODEX_MAX_DISPLAY_NAME_LENGTH + 1)
        config = f"interface:\n  display_name: \"{long_name}\"\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "display_name" in e]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("exceeds", warn_errors[0])

    def test_display_name_at_max_passes(self) -> None:
        """A display_name at exactly the max length passes."""
        name = "a" * CODEX_MAX_DISPLAY_NAME_LENGTH
        config = f"interface:\n  display_name: \"{name}\"\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        display_pass = [p for p in passes if "display_name" in p]
        self.assertEqual(len(display_pass), 1)

    def test_short_description_exceeding_max_returns_warn(self) -> None:
        """A short_description exceeding the max length produces a WARN (platform)."""
        long_desc = "x" * (CODEX_MAX_SHORT_DESCRIPTION_LENGTH + 1)
        config = f"interface:\n  short_description: \"{long_desc}\"\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "short_description" in e]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("exceeds", warn_errors[0])

    def test_short_description_at_max_passes(self) -> None:
        """A short_description at exactly the max length passes."""
        desc = "a" * CODEX_MAX_SHORT_DESCRIPTION_LENGTH
        config = f"interface:\n  short_description: \"{desc}\"\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        desc_pass = [p for p in passes if "short_description" in p]
        self.assertEqual(len(desc_pass), 1)

    def test_invalid_hex_color_returns_warn(self) -> None:
        """An invalid hex color produces a WARN."""
        invalid_colors = ["red", "#GGG", "#12345", "10B981", "#10B98"]
        for color in invalid_colors:
            config = f"interface:\n  brand_color: \"{color}\"\n"
            with self.subTest(color=color):
                with tempfile.TemporaryDirectory() as tmpdir:
                    _write_codex_config(tmpdir, config)
                    errors, passes = validate_codex_config(tmpdir)
                warn_errors = [
                    e for e in errors
                    if e.startswith(LEVEL_WARN) and "brand_color" in e
                ]
                self.assertEqual(
                    len(warn_errors), 1,
                    f"Expected WARN for color '{color}', got errors={errors}",
                )

    def test_valid_hex_colors_pass(self) -> None:
        """Valid hex colors pass validation."""
        valid_colors = ["#10B981", "#000000", "#FFFFFF", "#abcdef", "#AbCdEf"]
        for color in valid_colors:
            config = f"interface:\n  brand_color: \"{color}\"\n"
            with self.subTest(color=color):
                with tempfile.TemporaryDirectory() as tmpdir:
                    _write_codex_config(tmpdir, config)
                    errors, passes = validate_codex_config(tmpdir)
                color_pass = [p for p in passes if "brand_color" in p]
                self.assertEqual(
                    len(color_pass), 1,
                    f"Expected pass for color '{color}', got passes={passes}",
                )

    def test_absolute_icon_path_returns_warn(self) -> None:
        """An absolute icon path produces a WARN."""
        config = "interface:\n  icon_small: \"/absolute/path/icon.svg\"\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "icon_small" in e
        ]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("relative path", warn_errors[0])

    def test_path_traversal_icon_returns_warn(self) -> None:
        """An icon path with path traversal produces a WARN."""
        config = "interface:\n  icon_small: \"../../etc/icon.svg\"\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "icon_small" in e
        ]
        self.assertEqual(len(warn_errors), 1)

    def test_windows_style_path_traversal_icon_returns_warn(self) -> None:
        """A Windows-style path traversal (backslash) produces a WARN."""
        config = 'interface:\n  icon_small: "..\\\\..\\\\etc\\\\icon.svg"\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "icon_small" in e
        ]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("relative path", warn_errors[0])

    def test_unc_path_icon_returns_warn(self) -> None:
        """A Windows UNC-style path (\\\\server\\share) produces a WARN."""
        config = 'interface:\n  icon_small: "\\\\\\\\server\\\\share\\\\icon.svg"\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "icon_small" in e
        ]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("relative path", warn_errors[0])

    def test_drive_letter_path_icon_returns_warn(self) -> None:
        """A Windows drive-letter path (C:/...) produces a WARN on any platform."""
        config = 'interface:\n  icon_small: "C:/icons/icon.svg"\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "icon_small" in e
        ]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("relative path", warn_errors[0])

    def test_valid_relative_icon_paths_pass(self) -> None:
        """Valid relative icon paths pass validation."""
        valid_paths = ["./assets/icon.svg", "assets/icon.png", "icon.svg"]
        for path in valid_paths:
            config = f"interface:\n  icon_small: \"{path}\"\n"
            with self.subTest(path=path):
                with tempfile.TemporaryDirectory() as tmpdir:
                    _write_codex_config(tmpdir, config)
                    errors, passes = validate_codex_config(tmpdir)
                icon_pass = [p for p in passes if "icon_small" in p]
                self.assertEqual(
                    len(icon_pass), 1,
                    f"Expected pass for path '{path}', got passes={passes}",
                )

    def test_unrecognised_interface_keys_returns_info(self) -> None:
        """Unrecognised keys in the interface section produce an INFO."""
        config = (
            "interface:\n"
            '  display_name: "Test"\n'
            '  unknown_key: "value"\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        info_errors = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "interface" in e
        ]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("unknown_key", info_errors[0])


# ===================================================================
# Policy Validation
# ===================================================================


class CodexConfigPolicyTests(unittest.TestCase):
    """Tests for policy section validation."""

    def test_valid_boolean_values_pass(self) -> None:
        """Valid boolean values (true/false) pass validation."""
        for val in ["true", "false"]:
            config = f"policy:\n  allow_implicit_invocation: {val}\n"
            with self.subTest(val=val):
                with tempfile.TemporaryDirectory() as tmpdir:
                    _write_codex_config(tmpdir, config)
                    errors, passes = validate_codex_config(tmpdir)
                policy_pass = [
                    p for p in passes
                    if "allow_implicit_invocation" in p
                ]
                self.assertEqual(
                    len(policy_pass), 1,
                    f"Expected pass for '{val}', got passes={passes}",
                )

    def test_invalid_boolean_value_returns_warn(self) -> None:
        """A non-boolean value for allow_implicit_invocation produces a WARN."""
        config = "policy:\n  allow_implicit_invocation: maybe\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "allow_implicit_invocation" in e
        ]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("boolean", warn_errors[0])

    def test_unrecognised_policy_keys_returns_info(self) -> None:
        """Unrecognised keys in the policy section produce an INFO."""
        config = (
            "policy:\n"
            "  allow_implicit_invocation: true\n"
            "  custom_policy: enabled\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        info_errors = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "policy" in e
        ]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("custom_policy", info_errors[0])


# ===================================================================
# Dependencies Validation
# ===================================================================


class CodexConfigDependenciesTests(unittest.TestCase):
    """Tests for dependencies section validation."""

    def test_valid_tool_entry_passes(self) -> None:
        """A valid tool entry with all fields passes."""
        config = (
            "dependencies:\n"
            "  tools:\n"
            "    - type: mcp\n"
            "      value: my-server\n"
            '      description: "My server"\n'
            "      transport: streamable_http\n"
            '      url: "http://localhost:3000"\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        tools_pass = [p for p in passes if "tools" in p]
        self.assertGreaterEqual(len(tools_pass), 1)

    def test_missing_type_returns_warn(self) -> None:
        """A tool entry without 'type' produces a WARN (platform)."""
        config = (
            "dependencies:\n"
            "  tools:\n"
            "    - value: my-server\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "type" in e]
        self.assertEqual(len(warn_errors), 1)

    def test_missing_value_returns_warn(self) -> None:
        """A tool entry without 'value' produces a WARN (platform)."""
        config = (
            "dependencies:\n"
            "  tools:\n"
            "    - type: mcp\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "value" in e]
        self.assertEqual(len(warn_errors), 1)

    def test_empty_type_returns_warn(self) -> None:
        """A tool entry with an empty 'type' string produces a WARN (platform)."""
        config = (
            "dependencies:\n"
            "  tools:\n"
            '    - type: ""\n'
            "      value: my-server\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "type" in e and "empty" in e]
        self.assertEqual(len(warn_errors), 1)

    def test_empty_value_returns_warn(self) -> None:
        """A tool entry with an empty 'value' string produces a WARN (platform)."""
        config = (
            "dependencies:\n"
            "  tools:\n"
            "    - type: mcp\n"
            '      value: ""\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "value" in e and "empty" in e]
        self.assertEqual(len(warn_errors), 1)

    def test_empty_section_no_warn(self) -> None:
        """An empty section (e.g., 'interface:' alone) produces no WARN."""
        config = "interface:\npolicy:\ndependencies:\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        type_warns = [e for e in warn_errors if "should be a mapping" in e]
        self.assertEqual(type_warns, [])

    def test_unknown_tool_type_returns_info(self) -> None:
        """An unrecognised tool type produces an INFO."""
        config = (
            "dependencies:\n"
            "  tools:\n"
            "    - type: custom\n"
            "      value: my-tool\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        info_errors = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "type" in e
        ]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("custom", info_errors[0])

    def test_unknown_transport_returns_info(self) -> None:
        """An unrecognised transport produces an INFO."""
        config = (
            "dependencies:\n"
            "  tools:\n"
            "    - type: mcp\n"
            "      value: my-server\n"
            "      transport: websocket\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        info_errors = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "transport" in e
        ]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("websocket", info_errors[0])

    def test_multiple_tools_validated(self) -> None:
        """Multiple tool entries are each validated independently."""
        config = (
            "dependencies:\n"
            "  tools:\n"
            "    - type: mcp\n"
            "      value: server-a\n"
            "    - type: mcp\n"
            "      value: server-b\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_tools_not_a_list_returns_warn(self) -> None:
        """A non-list tools value produces a WARN."""
        config = (
            "dependencies:\n"
            "  tools: not-a-list\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "tools" in e
        ]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("list", warn_errors[0])


# ===================================================================
# Malformed YAML
# ===================================================================


class CodexConfigMalformedTests(unittest.TestCase):
    """Tests for malformed agents/openai.yaml files."""

    def test_unrecognised_top_level_keys_returns_info(self) -> None:
        """Unrecognised top-level keys produce an INFO."""
        config = (
            "interface:\n"
            '  display_name: "Test"\n'
            "custom_section:\n"
            "  key: value\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        info_errors = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "top-level" in e
        ]
        self.assertEqual(len(info_errors), 1)
        self.assertIn("custom_section", info_errors[0])

    def test_top_level_sequence_returns_warn(self) -> None:
        """A top-level YAML sequence produces a WARN (platform)."""
        config = "- item-one\n- item-two\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "mapping" in e]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("sequence", warn_errors[0])

    def test_top_level_sequence_with_mappings_returns_warn(self) -> None:
        """A top-level list of mappings (not a mapping) produces a WARN (platform)."""
        config = (
            "- type: mcp\n"
            "  value: server\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "mapping" in e]
        self.assertEqual(len(warn_errors), 1)

    def test_bare_dash_sequence_returns_warn(self) -> None:
        """A top-level bare dash (content on following indented lines) produces a WARN (platform)."""
        config = (
            "-\n"
            "  type: mcp\n"
            "  value: server\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "mapping" in e]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("sequence", warn_errors[0])

    def test_indented_top_level_sequence_returns_warn(self) -> None:
        """An indented top-level YAML sequence produces a WARN (platform)."""
        config = " - item-one\n - item-two\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "mapping" in e]
        self.assertEqual(len(warn_errors), 1)
        self.assertIn("sequence", warn_errors[0])

    def test_malformed_content_coerced_to_empty_dict_returns_warn(self) -> None:
        """Content that the parser coerces to an empty dict produces a WARN (platform)."""
        # A bare key without a colon is not valid YAML mapping syntax;
        # parse_yaml_subset silently returns {} for such input.
        config = "not-a-mapping\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN) and "malformed" in e]
        self.assertEqual(len(warn_errors), 1)


# ===================================================================
# Integration with validate_skill
# ===================================================================


class CodexConfigIntegrationTests(unittest.TestCase):
    """Tests for Codex config validation integrated into validate_skill."""

    def test_valid_skill_with_codex_config_passes(self) -> None:
        """A valid skill with a valid agents/openai.yaml produces no FAIL errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            config = (
                "interface:\n"
                '  display_name: "Demo Skill"\n'
                '  brand_color: "#10B981"\n'
            )
            _write_codex_config(skill_dir, config)
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])
        # Should have codex-related passes
        codex_passes = [
            p for p in passes
            if "display_name" in p or "brand_color" in p
        ]
        self.assertGreaterEqual(len(codex_passes), 1)

    def test_valid_skill_without_codex_config_passes(self) -> None:
        """A valid skill without agents/openai.yaml still passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            errors, passes = validate_skill(skill_dir)
        fail_errors = [e for e in errors if e.startswith(LEVEL_FAIL)]
        self.assertEqual(fail_errors, [])

    def test_invalid_codex_config_reported_in_skill_validation(self) -> None:
        """An invalid agents/openai.yaml is reported during skill validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            config = (
                "interface:\n"
                '  brand_color: "not-a-color"\n'
            )
            _write_codex_config(skill_dir, config)
            errors, passes = validate_skill(skill_dir)
        warn_errors = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "brand_color" in e
        ]
        self.assertEqual(len(warn_errors), 1)

    def test_agents_directory_is_recognised(self) -> None:
        """The agents/ directory is recognised and does not produce a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo-skill")
            write_skill_md(skill_dir)
            config = (
                "interface:\n"
                '  display_name: "Demo"\n'
            )
            _write_codex_config(skill_dir, config)
            errors, passes = validate_skill(skill_dir)
        # The agents/ directory should be recognised
        dir_warns = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "agents" in e
            and "Non-standard" in e
        ]
        self.assertEqual(dir_warns, [])


# ===================================================================
# File Read Errors
# ===================================================================


class CodexConfigFileReadErrorTests(unittest.TestCase):
    """Tests for OSError and YAML parse failure paths."""

    def test_oserror_on_read_returns_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, "interface:\n  display_name: x\n")
            with mock.patch("lib.codex_config.open", side_effect=OSError("EIO")):
                errors, passes = validate_codex_config(tmpdir)
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_WARN, errors[0])
        self.assertIn("cannot read", errors[0])
        self.assertEqual(passes, [])

    def test_yaml_parse_valueerror_returns_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, "interface:\n  display_name: x\n")
            with mock.patch(
                "lib.codex_config.parse_yaml_subset",
                side_effect=ValueError("bad yaml"),
            ):
                errors, passes = validate_codex_config(tmpdir)
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_WARN, errors[0])
        self.assertIn("YAML parse error", errors[0])
        self.assertIn("bad yaml", errors[0])

    def test_top_level_non_mapping_returns_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, "interface:\n  display_name: x\n")
            with mock.patch(
                "lib.codex_config.parse_yaml_subset",
                return_value="a scalar",
            ):
                errors, passes = validate_codex_config(tmpdir)
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_WARN, errors[0])
        self.assertIn("top-level must be a mapping", errors[0])


# ===================================================================
# Section Type Errors (non-mapping for interface / policy / dependencies)
# ===================================================================


class CodexConfigSectionTypeTests(unittest.TestCase):
    """Tests for non-mapping values at the interface/policy/dependencies keys."""

    def test_interface_non_mapping_returns_warn(self) -> None:
        config = 'interface: "not-a-mapping"\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "'interface' should be a mapping" in e
        ]
        self.assertEqual(len(warn), 1)

    def test_policy_non_mapping_returns_warn(self) -> None:
        config = 'policy: "flat"\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "'policy' should be a mapping" in e
        ]
        self.assertEqual(len(warn), 1)

    def test_dependencies_non_mapping_returns_warn(self) -> None:
        config = 'dependencies: "x"\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        warn = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "'dependencies' should be a mapping" in e
        ]
        self.assertEqual(len(warn), 1)

    def test_policy_without_allow_implicit_invocation_skips_boolean_check(self) -> None:
        config = "policy:\n  unknown_key: value\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        boolean_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "allow_implicit_invocation" in e
        ]
        self.assertEqual(boolean_warns, [])

    def test_dependencies_without_tools_returns_no_warn(self) -> None:
        config = "dependencies:\n  other_key: value\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_codex_config(tmpdir, config)
            errors, passes = validate_codex_config(tmpdir)
        tools_warns = [
            e for e in errors
            if e.startswith(LEVEL_WARN) and "tools" in e
        ]
        self.assertEqual(tools_warns, [])


# ===================================================================
# Interface Non-String Field Values (direct _validate_interface calls)
# ===================================================================


class CodexConfigInterfaceNonStringTests(unittest.TestCase):
    """Non-string field values exercise the ``isinstance`` error branches.

    YAML scalar values always parse to strings, so these branches can only
    be hit by passing a pre-built mapping directly to ``_validate_interface``.
    """

    def test_display_name_non_string_returns_warn(self) -> None:
        errors, _ = _validate_interface({"display_name": 42})
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_WARN, errors[0])
        self.assertIn("display_name", errors[0])
        self.assertIn("should be a string", errors[0])

    def test_short_description_non_string_returns_warn(self) -> None:
        errors, _ = _validate_interface({"short_description": ["a", "b"]})
        self.assertEqual(len(errors), 1)
        self.assertIn("short_description", errors[0])
        self.assertIn("should be a string", errors[0])

    def test_icon_small_non_string_returns_warn(self) -> None:
        errors, _ = _validate_interface({"icon_small": 1})
        self.assertEqual(len(errors), 1)
        self.assertIn("icon_small", errors[0])
        self.assertIn("should be a string", errors[0])

    def test_icon_large_non_string_returns_warn(self) -> None:
        errors, _ = _validate_interface({"icon_large": ["x"]})
        self.assertEqual(len(errors), 1)
        self.assertIn("icon_large", errors[0])
        self.assertIn("should be a string", errors[0])

    def test_brand_color_non_string_returns_warn(self) -> None:
        errors, _ = _validate_interface({"brand_color": 0x10B981})
        self.assertEqual(len(errors), 1)
        self.assertIn("brand_color", errors[0])
        self.assertIn("should be a string", errors[0])

    def test_default_prompt_non_string_returns_warn(self) -> None:
        errors, _ = _validate_interface({"default_prompt": {"nested": "x"}})
        self.assertEqual(len(errors), 1)
        self.assertIn("default_prompt", errors[0])
        self.assertIn("should be a string", errors[0])


# ===================================================================
# Tool Entry Non-String / Non-Mapping Branches
# ===================================================================


class CodexConfigToolEntryTests(unittest.TestCase):
    """Tests for ``_validate_tool_entry`` error branches."""

    def test_tool_entry_non_mapping_returns_warn(self) -> None:
        errors, _ = _validate_tool_entry("plainstring", 0)
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_WARN, errors[0])
        self.assertIn("dependencies.tools[0]", errors[0])
        self.assertIn("should be a mapping", errors[0])

    def test_tool_unrecognized_keys_returns_info(self) -> None:
        errors, _ = _validate_tool_entry(
            {"type": "mcp", "value": "server", "wibble": "x"}, 2,
        )
        info_wibble = [
            e for e in errors
            if e.startswith(LEVEL_INFO) and "wibble" in e
        ]
        self.assertEqual(len(info_wibble), 1)
        self.assertIn("dependencies.tools[2]", info_wibble[0])

    def test_tool_type_non_string_returns_warn(self) -> None:
        errors, _ = _validate_tool_entry({"type": 42, "value": "x"}, 0)
        warns = [e for e in errors if "type" in e and "should be a string" in e]
        self.assertEqual(len(warns), 1)

    def test_tool_value_non_string_returns_warn(self) -> None:
        errors, _ = _validate_tool_entry({"type": "builtin", "value": 99}, 0)
        warns = [e for e in errors if ".value" in e and "should be a string" in e]
        self.assertEqual(len(warns), 1)

    def test_tool_description_non_string_returns_warn(self) -> None:
        errors, _ = _validate_tool_entry(
            {"type": "builtin", "value": "bash", "description": 1}, 0,
        )
        warns = [e for e in errors if "description" in e and "should be a string" in e]
        self.assertEqual(len(warns), 1)

    def test_tool_transport_non_string_returns_warn(self) -> None:
        errors, _ = _validate_tool_entry(
            {"type": "mcp", "value": "srv", "transport": 123}, 0,
        )
        warns = [e for e in errors if "transport" in e and "should be a string" in e]
        self.assertEqual(len(warns), 1)

    def test_tool_url_non_string_returns_warn(self) -> None:
        errors, _ = _validate_tool_entry(
            {"type": "mcp", "value": "srv", "url": 77}, 0,
        )
        warns = [e for e in errors if "url" in e and "should be a string" in e]
        self.assertEqual(len(warns), 1)


# ===================================================================
# _is_valid_relative_path edge cases
# ===================================================================


class IsValidRelativePathEdgeTests(unittest.TestCase):
    """Tests for ``_is_valid_relative_path`` boundary conditions."""

    def test_whitespace_only_path_rejected(self) -> None:
        self.assertFalse(_is_valid_relative_path("   "))

    def test_empty_string_rejected(self) -> None:
        self.assertFalse(_is_valid_relative_path(""))


if __name__ == "__main__":
    unittest.main()
