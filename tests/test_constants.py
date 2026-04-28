"""Tests for lib.constants module-load behaviour.

Covers the lazy divergence re-parse of ``configuration.yaml`` via
``get_config_findings``, verifies ``CONFIG_PATH`` is an absolute path
pointing at the expected file, and pins the ``prose_yaml`` opt-out
marker, in-scope globs, and the ``yaml_conformance`` construct-id
enumeration.  Missing-section fail-fast is exercised by
re-importing ``lib.constants`` against a synthetic config file with
the section removed.
"""

import importlib
import os
import sys
import unittest
import unittest.mock

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib import constants


class ConfigPathTests(unittest.TestCase):
    """``CONFIG_PATH`` exposes the absolute config file location."""

    def test_config_path_is_absolute(self) -> None:
        self.assertTrue(os.path.isabs(constants.CONFIG_PATH))

    def test_config_path_ends_with_configuration_yaml(self) -> None:
        self.assertTrue(
            constants.CONFIG_PATH.endswith(
                os.path.join("scripts", "lib", "configuration.yaml")
            )
        )

    def test_config_path_points_at_existing_file(self) -> None:
        self.assertTrue(os.path.isfile(constants.CONFIG_PATH))


class GetConfigFindingsTests(unittest.TestCase):
    """``get_config_findings`` lazily collects and caches findings."""

    def setUp(self) -> None:
        # Reset cache so each test exercises the first-call path.
        constants._CONFIG_FINDINGS = None

    def tearDown(self) -> None:
        # Restore cache to avoid leaking state into other test modules.
        constants._CONFIG_FINDINGS = None

    def test_returns_list(self) -> None:
        findings = constants.get_config_findings()
        self.assertIsInstance(findings, list)

    def test_returns_copy_not_internal_list(self) -> None:
        first = constants.get_config_findings()
        first.append("mutated")
        second = constants.get_config_findings()
        self.assertNotIn("mutated", second)

    def test_memoized_after_first_call(self) -> None:
        constants.get_config_findings()
        cached = constants._CONFIG_FINDINGS
        self.assertIsNotNone(cached)
        constants.get_config_findings()
        self.assertIs(constants._CONFIG_FINDINGS, cached)

    def test_current_configuration_has_no_divergences(self) -> None:
        """The shipped ``configuration.yaml`` must round-trip clean."""
        findings = constants.get_config_findings()
        self.assertEqual(findings, [])


class ProseYamlConfigTests(unittest.TestCase):
    """``prose_yaml`` keys are exposed by constants."""

    def test_opt_out_marker_value(self) -> None:
        self.assertEqual(
            constants.PROSE_YAML_OPT_OUT_MARKER,
            "<!-- yaml-ignore -->",
        )

    def test_in_scope_globs_value(self) -> None:
        self.assertEqual(
            constants.PROSE_YAML_IN_SCOPE_GLOBS,
            ("SKILL.md", "capabilities/**/*.md", "references/**/*.md"),
        )


class YamlConformanceConfigTests(unittest.TestCase):
    """``yaml_conformance.construct_ids`` enumeration is exposed."""

    def test_construct_ids_value(self) -> None:
        self.assertEqual(
            constants.YAML_CONFORMANCE_CONSTRUCT_IDS,
            (
                "anchor-with-trailing-in-key",
                "indent-indicator-block-scalar",
                "tag-in-mapping-key",
            ),
        )


class DescriptionTriggerPhrasesTests(unittest.TestCase):
    """``DESCRIPTION_TRIGGER_PHRASES`` exposes the configured phrase list."""

    def test_is_tuple(self) -> None:
        # Stored as a tuple (not frozenset) so iteration order is
        # deterministic — --verbose pass-message phrase reporting must
        # not vary across processes / platforms.
        self.assertIsInstance(constants.DESCRIPTION_TRIGGER_PHRASES, tuple)

    def test_is_non_empty(self) -> None:
        self.assertGreater(len(constants.DESCRIPTION_TRIGGER_PHRASES), 0)

    def test_phrases_are_lowercased(self) -> None:
        for phrase in constants.DESCRIPTION_TRIGGER_PHRASES:
            self.assertEqual(phrase, phrase.lower())

    def test_phrases_are_sorted(self) -> None:
        # Sorted-tuple invariant — see ``test_is_tuple`` rationale.
        self.assertEqual(
            list(constants.DESCRIPTION_TRIGGER_PHRASES),
            sorted(constants.DESCRIPTION_TRIGGER_PHRASES),
        )

    def test_phrases_are_unique(self) -> None:
        phrases = list(constants.DESCRIPTION_TRIGGER_PHRASES)
        self.assertEqual(len(phrases), len(set(phrases)))

    def test_starter_phrases_present(self) -> None:
        # Pin the spec-derived starter set so accidental config edits
        # surface as a test failure rather than a silent rule weakening.
        # ``use for`` is intentionally excluded — too generic, collides
        # with incidental prose like ``use forensic`` / ``use for example``.
        for phrase in (
            "triggers on", "triggers when",
            "activates on", "activates when",
            "use when", "when to use",
            "invoked on", "invoked when",
        ):
            self.assertIn(phrase, constants.DESCRIPTION_TRIGGER_PHRASES)

    def test_starter_set_excludes_use_for(self) -> None:
        # Negative pin: ``use for`` was deliberately removed because
        # substring matching turned it into a false-negative source.
        self.assertNotIn("use for", constants.DESCRIPTION_TRIGGER_PHRASES)


class AllowedToolsCatalogTests(unittest.TestCase):
    """Per-harness catalog constants exposed by ``allowed_tools.catalogs``."""

    def test_harness_tools_includes_canonical_pascalcase_set(self) -> None:
        # Names listed in the Claude Code skills documentation.
        for tool in ("Bash", "Read", "Edit", "Write", "Grep", "Glob",
                     "WebFetch", "WebSearch", "NotebookEdit", "Task", "Skill"):
            self.assertIn(tool, constants.HARNESS_TOOLS_CLAUDE_CODE)

    def test_cli_tools_excludes_pascalcase_harness_names(self) -> None:
        for tool in ("Bash", "Read", "Edit"):
            self.assertNotIn(tool, constants.CLI_TOOLS_CLAUDE_CODE)

    def test_cli_tools_includes_lowercase_generic_set(self) -> None:
        for tool in ("bash", "python", "git", "gh", "docker"):
            self.assertIn(tool, constants.CLI_TOOLS_CLAUDE_CODE)

    def test_known_tools_is_union(self) -> None:
        self.assertEqual(
            constants.KNOWN_TOOLS,
            constants.HARNESS_TOOLS_CLAUDE_CODE
            | constants.CLI_TOOLS_CLAUDE_CODE,
        )

    def test_known_tools_recognises_lowercase_bash(self) -> None:
        # Backwards-compat: existing skills may list lowercase ``bash``.
        # Recognition INFO must continue to treat it as known.
        self.assertIn("bash", constants.KNOWN_TOOLS)

    def test_known_tools_recognises_pascalcase_bash(self) -> None:
        self.assertIn("Bash", constants.KNOWN_TOOLS)


class ToolShapeRegexTests(unittest.TestCase):
    """Token-shape regexes used by pattern-fallback recognition."""

    def test_mcp_regex_matches_canonical_form(self) -> None:
        self.assertTrue(
            constants.RE_MCP_TOOL_NAME.match("mcp__server__tool"),
        )

    def test_mcp_regex_matches_mixed_case(self) -> None:
        # Real MCP tool names mix case (e.g. Atlassian, addCommentToJiraIssue).
        self.assertTrue(
            constants.RE_MCP_TOOL_NAME.match(
                "mcp__claude_ai_Atlassian__addCommentToJiraIssue"
            ),
        )

    def test_mcp_regex_rejects_single_underscore(self) -> None:
        self.assertIsNone(
            constants.RE_MCP_TOOL_NAME.match("mcp_server__tool"),
        )

    def test_mcp_regex_rejects_missing_separator(self) -> None:
        self.assertIsNone(
            constants.RE_MCP_TOOL_NAME.match("mcp__servertool"),
        )

    def test_harness_shape_matches_pascalcase(self) -> None:
        self.assertTrue(constants.RE_HARNESS_TOOL_SHAPE.match("Bash"))
        self.assertTrue(constants.RE_HARNESS_TOOL_SHAPE.match("WebFetch"))

    def test_harness_shape_rejects_paren_suffix(self) -> None:
        # The regex matches bare PascalCase only.  Paren suffixes
        # (e.g. ``Bash(git add *)``) are stripped upstream by
        # ``_RE_PAREN_ARGS`` in ``validation`` before any token
        # reaches this regex, so the regex itself does not need
        # to model parens.
        self.assertIsNone(
            constants.RE_HARNESS_TOOL_SHAPE.match("Bash(git add *)"),
        )

    def test_harness_shape_rejects_lowercase(self) -> None:
        self.assertIsNone(constants.RE_HARNESS_TOOL_SHAPE.match("bash"))

    def test_harness_shape_rejects_dashed(self) -> None:
        self.assertIsNone(
            constants.RE_HARNESS_TOOL_SHAPE.match("Some-Tool"),
        )


class ToolFenceLanguagesTests(unittest.TestCase):
    """``TOOL_FENCE_LANGUAGES`` mapping shape and contents."""

    def test_keyed_by_harness_tool_name(self) -> None:
        self.assertIn("Bash", constants.TOOL_FENCE_LANGUAGES)

    def test_bash_languages_starter_set(self) -> None:
        self.assertEqual(
            constants.TOOL_FENCE_LANGUAGES["Bash"],
            frozenset({"bash", "sh", "shell", "zsh"}),
        )

    def test_values_are_frozensets(self) -> None:
        for languages in constants.TOOL_FENCE_LANGUAGES.values():
            self.assertIsInstance(languages, frozenset)

    def test_keys_are_harness_tools(self) -> None:
        # Every fence-language mapping must point at a recognised harness tool.
        for tool_name in constants.TOOL_FENCE_LANGUAGES.keys():
            self.assertIn(tool_name, constants.HARNESS_TOOLS_CLAUDE_CODE)

    def test_tools_indicating_scripts_includes_bash(self) -> None:
        # ``Bash`` is the only tool today with ``scripts_dir_indicator: true``;
        # the set must include it so the WARN check fires.
        self.assertIn("Bash", constants.TOOLS_INDICATING_SCRIPTS)

    def test_tools_indicating_scripts_subset_of_harness_tools(self) -> None:
        for tool_name in constants.TOOLS_INDICATING_SCRIPTS:
            self.assertIn(tool_name, constants.HARNESS_TOOLS_CLAUDE_CODE)

    def test_tools_indicating_scripts_is_frozenset(self) -> None:
        self.assertIsInstance(constants.TOOLS_INDICATING_SCRIPTS, frozenset)


class MissingSectionFailFastTests(unittest.TestCase):
    """Re-importing ``lib.constants`` against a config missing a
    required section raises ``RuntimeError`` at import time."""

    def _full_config_minus(self, section: str) -> str:
        """Return the real configuration file text with *section* removed."""
        with open(constants.CONFIG_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
        out_lines: list[str] = []
        skipping = False
        for line in text.splitlines(keepends=True):
            if line.startswith(f"{section}:"):
                skipping = True
                continue
            if skipping:
                if line.strip() == "" or line.startswith("#"):
                    continue
                if not line.startswith((" ", "\t")):
                    skipping = False
                else:
                    continue
            out_lines.append(line)
        return "".join(out_lines)

    def _reimport_with_config(self, config_text: str) -> None:
        """Re-import ``lib.constants`` against a synthetic config text.

        Patches ``builtins.open`` so the module's two reads of
        ``CONFIG_PATH`` see *config_text* instead of the on-disk file.
        Reloads the real module afterwards so subsequent tests get the
        canonical state back.
        """
        import builtins
        import io

        real_open = builtins.open
        target = constants.CONFIG_PATH

        def fake_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
            if file == target:
                return io.StringIO(config_text)
            return real_open(file, *args, **kwargs)

        try:
            with unittest.mock.patch("builtins.open", new=fake_open):
                importlib.reload(constants)
        finally:
            importlib.reload(constants)

    def test_missing_prose_yaml_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(self._full_config_minus("prose_yaml"))
        self.assertIn("prose_yaml", str(ctx.exception))

    def test_missing_yaml_conformance_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus("yaml_conformance")
            )
        self.assertIn("yaml_conformance", str(ctx.exception))

    def test_missing_allowed_tools_fence_languages_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus_nested(
                    "allowed_tools", "fence_languages",
                )
            )
        self.assertIn("fence_languages", str(ctx.exception))

    def test_missing_allowed_tools_catalogs_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus_nested("allowed_tools", "catalogs")
            )
        self.assertIn("catalogs", str(ctx.exception))

    def test_missing_mcp_tool_pattern_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus_scalar_under(
                    "allowed_tools", "mcp_tool_pattern",
                )
            )
        self.assertIn("mcp_tool_pattern", str(ctx.exception))

    def test_missing_harness_tool_shape_pattern_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus_scalar_under(
                    "allowed_tools", "harness_tool_shape_pattern",
                )
            )
        self.assertIn("harness_tool_shape_pattern", str(ctx.exception))

    def _full_config_minus_scalar_under(
        self, parent: str, child: str,
    ) -> str:
        """Return configuration text with the scalar ``parent.child:``
        line removed.

        Sibling helper to :meth:`_full_config_minus_nested` for keys
        whose value is a scalar (e.g. ``foo: pattern``) rather than a
        nested mapping — the original helper only matches lines whose
        ``bare`` form is exactly ``child:`` and so cannot reach scalar
        leaves.
        """
        with open(constants.CONFIG_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
        out_lines: list[str] = []
        in_parent = False
        parent_indent = 0
        for line in text.splitlines(keepends=True):
            stripped = line.lstrip(" \t")
            indent = len(line) - len(stripped)
            bare = line.strip()
            if not in_parent and bare == f"{parent}:":
                in_parent = True
                parent_indent = indent
                out_lines.append(line)
                continue
            if (
                in_parent
                and indent <= parent_indent
                and bare
                and not bare.startswith("#")
            ):
                in_parent = False
            if in_parent and (
                bare == f"{child}:" or bare.startswith(f"{child}:")
            ):
                continue
            out_lines.append(line)
        return "".join(out_lines)

    def _full_config_minus_nested(self, parent: str, child: str) -> str:
        """Return configuration text with *parent.child* stripped out.

        Walks the YAML line-by-line: the ``child:`` line under
        ``parent:`` and all lines at deeper indentation are dropped.
        """
        with open(constants.CONFIG_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
        out_lines: list[str] = []
        in_parent = False
        parent_indent = 0
        skipping = False
        skip_indent = 0
        for line in text.splitlines(keepends=True):
            stripped = line.lstrip(" \t")
            indent = len(line) - len(stripped)
            bare = line.strip()
            if not in_parent and bare == f"{parent}:":
                in_parent = True
                parent_indent = indent
                out_lines.append(line)
                continue
            if in_parent and indent <= parent_indent and bare and not bare.startswith("#"):
                in_parent = False
            if in_parent and bare == f"{child}:":
                skipping = True
                skip_indent = indent
                continue
            if skipping:
                if bare == "" or bare.startswith("#") or indent > skip_indent:
                    continue
                skipping = False
            out_lines.append(line)
        return "".join(out_lines)

    def test_missing_frontmatter_suggestions_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus_nested("skill", "frontmatter_suggestions")
            )
        self.assertIn("frontmatter_suggestions", str(ctx.exception))

    def _full_config_with_substitution(self, old: str, new: str) -> str:
        """Return configuration text with *old* replaced by *new* exactly once."""
        with open(constants.CONFIG_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
        if text.count(old) != 1:
            self.fail(
                f"Expected exactly one occurrence of {old!r} in configuration.yaml"
            )
        return text.replace(old, new, 1)

    def test_invalid_frontmatter_suggest_max_matches_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_with_substitution(
                    "max_matches: 3", "max_matches: 0"
                )
            )
        self.assertIn("max_matches", str(ctx.exception))

    def test_invalid_frontmatter_suggest_cutoff_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_with_substitution(
                    "cutoff: 0.6", "cutoff: 1.5"
                )
            )
        self.assertIn("cutoff", str(ctx.exception))

    def test_missing_description_trigger_phrases_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus_nested(
                    "description", "trigger_phrases",
                )
            )
        self.assertIn("trigger_phrases", str(ctx.exception))

    def test_empty_string_entry_in_trigger_phrases_raises(self) -> None:
        # An empty / whitespace-only entry would silently disable the
        # rule — substring-match against "" is always True.  Loader
        # must refuse it loudly.
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_with_substitution(
                    "      - triggers on\n",
                    "      - triggers on\n      - \"\"\n",
                )
            )
        self.assertIn("trigger_phrases", str(ctx.exception))
        self.assertIn("empty", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
