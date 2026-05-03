"""Tests for lib.constants module-load behaviour.

Covers the lazy divergence re-parse of ``configuration.yaml`` via
``get_config_findings``, verifies ``CONFIG_PATH`` is an absolute path
pointing at the expected file, and pins the ``prose_yaml`` opt-out
marker, in-scope globs, and the ``yaml_conformance`` construct-id
enumeration.  Missing-section fail-fast is exercised by
re-importing ``lib.constants`` against a synthetic config file with
the section removed.
"""

import datetime
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

from lib import constants, yaml_parser


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


class AllowedOrphansConfigTests(unittest.TestCase):
    """``orphan_references.allowed_orphans`` exposes a tuple of strings."""

    def test_default_is_empty_tuple(self) -> None:
        self.assertEqual(constants.ALLOWED_ORPHANS, ())

    def test_loads_normalized_entries(self) -> None:
        config_text = (
            "skill:\n"
            "  name:\n"
            "    max_length: 64\n"
            "    min_length: 2\n"
            "    format_pattern: ^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$\n"
            "    reserved_words:\n"
            "      - anthropic\n"
            "  description:\n"
            "    max_length: 1024\n"
            "    xml_tag_pattern: <[^>]+>\n"
            "    trigger_phrases:\n"
            "      - triggers on\n"
            "    voice_patterns:\n"
            "      first_person: x\n"
            "      first_person_plural: x\n"
            "      second_person: x\n"
            "      imperative_start: x\n"
            "  body:\n"
            "    max_lines: 500\n"
            "    reference_patterns:\n"
            "      markdown_link: x\n"
            "      backtick: x\n"
            "  compatibility:\n"
            "    max_length: 500\n"
            "  known_frontmatter_keys:\n"
            "    - name\n"
            "  frontmatter_suggestions:\n"
            "    max_matches: 3\n"
            "    cutoff: 0.6\n"
            "  allowed_tools:\n"
            "    max_tools: 20\n"
            "    mcp_tool_pattern: ^mcp$\n"
            "    harness_tool_shape_pattern: ^[A-Z]\n"
            "    catalogs:\n"
            "      claude_code:\n"
            "        harness_tools:\n"
            "          - Bash\n"
            "        cli_tools:\n"
            "          - bash\n"
            "    fence_languages:\n"
            "      Bash:\n"
            "        languages:\n"
            "          - bash\n"
            "        scripts_dir_indicator: true\n"
            "  metadata:\n"
            "    version:\n"
            "      pattern: ^x$\n"
            "    author:\n"
            "      max_length: 128\n"
            "  license:\n"
            "    known_spdx:\n"
            "      - MIT\n"
            "  recognized_subdirectories:\n"
            "    - scripts\n"
            "  capability_frontmatter:\n"
            "    skill_only_fields:\n"
            "      - license\n"
            "plain_scalar:\n"
            "  indicators:\n"
            "    flow: x\n"
            "    alias: x\n"
            "    reserved: x\n"
            "    directive: x\n"
            "    block_entry: x\n"
            "    mapping_key: x\n"
            "    anchor: x\n"
            "    block_scalar: x\n"
            "    quote_single: \"'\"\n"
            "    quote_double: '\"'\n"
            "    tag: x\n"
            "  context_whitespace:\n"
            "    - ' '\n"
            "prose_yaml:\n"
            "  opt_out_marker: <!-- yaml-ignore -->\n"
            "  in_scope_globs:\n"
            "    - SKILL.md\n"
            "yaml_conformance:\n"
            "  construct_ids:\n"
            "    - x\n"
            "codex_config:\n"
            "  known_top_level_keys:\n"
            "    - interface\n"
            "  known_interface_keys:\n"
            "    - display_name\n"
            "  known_policy_keys:\n"
            "    - allow_implicit_invocation\n"
            "  known_dependencies_keys:\n"
            "    - tools\n"
            "  known_tool_keys:\n"
            "    - type\n"
            "  interface:\n"
            "    max_display_name_length: 64\n"
            "    max_short_description_length: 200\n"
            "    hex_color_pattern: ^#$\n"
            "  dependencies:\n"
            "    known_tool_types:\n"
            "      - mcp\n"
            "    known_transports:\n"
            "      - x\n"
            "dependency_direction:\n"
            "  roles_ref_pattern: roles/\n"
            "  sibling_capability_ref_pattern: x\n"
            "role_composition:\n"
            "  min_skills: 2\n"
            "  skill_ref_pattern: x\n"
            "  capability_ref_pattern: x\n"
            "orphan_references:\n"
            "  allowed_orphans:\n"
            "    - references/staged.md\n"
            "    - ./references/dotted.md\n"
            "    - skills/foo/references/audit.md\n"
            "bundle:\n"
            "  max_reference_depth: 25\n"
            "  description_max_length: 200\n"
            "  infer_max_walk_depth: 5\n"
            "  valid_targets:\n"
            "    - claude\n"
            "  default_target: claude\n"
            "  exclude_patterns:\n"
            "    - .git\n"
        )

        import builtins
        import io

        real_open = builtins.open
        target = constants.CONFIG_PATH

        def fake_open(file: object, *args: object, **kwargs: object) -> object:
            if file == target:
                return io.StringIO(config_text)
            return real_open(file, *args, **kwargs)

        try:
            with unittest.mock.patch("builtins.open", new=fake_open):
                importlib.reload(constants)
            self.assertEqual(
                constants.ALLOWED_ORPHANS,
                (
                    "references/staged.md",
                    "references/dotted.md",
                    "skills/foo/references/audit.md",
                ),
            )
        finally:
            importlib.reload(constants)


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


class DescriptionTriggerExamplePhrasesTests(unittest.TestCase):
    """``DESCRIPTION_TRIGGER_EXAMPLE_PHRASES`` is the curated subset
    rendered in the WARN message.  First-word distinct so examples
    cover different root verbs, capped at three entries."""

    def test_is_tuple(self) -> None:
        self.assertIsInstance(
            constants.DESCRIPTION_TRIGGER_EXAMPLE_PHRASES, tuple,
        )

    def test_is_non_empty(self) -> None:
        self.assertGreater(
            len(constants.DESCRIPTION_TRIGGER_EXAMPLE_PHRASES), 0,
        )

    def test_capped_at_three(self) -> None:
        self.assertLessEqual(
            len(constants.DESCRIPTION_TRIGGER_EXAMPLE_PHRASES), 3,
        )

    def test_first_words_are_distinct(self) -> None:
        # Core invariant: each example uses a different root verb so
        # the user sees varied guidance, not two flavors of one verb.
        first_words = [
            phrase.split(" ", 1)[0]
            for phrase in constants.DESCRIPTION_TRIGGER_EXAMPLE_PHRASES
        ]
        self.assertEqual(len(first_words), len(set(first_words)))

    def test_examples_are_subset_of_full_list(self) -> None:
        for phrase in constants.DESCRIPTION_TRIGGER_EXAMPLE_PHRASES:
            self.assertIn(phrase, constants.DESCRIPTION_TRIGGER_PHRASES)

    def test_examples_include_triggers_root(self) -> None:
        # Pin: "triggers" is the most natural English activation root
        # and must appear in the rendered examples.  If the curation
        # ever drops it, fail loudly so the WARN's user value is
        # not silently degraded.
        first_words = {
            phrase.split(" ", 1)[0]
            for phrase in constants.DESCRIPTION_TRIGGER_EXAMPLE_PHRASES
        }
        self.assertIn("triggers", first_words)


class AllowedToolsCatalogTests(unittest.TestCase):
    """Per-harness catalog constants exposed by ``allowed_tools.catalogs``."""

    # Harnesses currently tracked by the tool-catalog drift helper.
    # ``configuration.yaml`` documents that future harnesses may use
    # their own bucket shape under ``catalogs.<harness>``, so the
    # strict schema canaries below scope to this set rather than
    # iterating every harness in the loaded YAML.  Today only
    # ``claude_code`` is drift-managed (the helper at
    # ``.github/scripts/tool-catalog-drift.py`` hardcodes the harness
    # rather than iterating ``HARNESS_NAMES``); add new entries here
    # in lockstep with teaching the drift helper a new harness.
    _DRIFT_MANAGED_HARNESSES = frozenset({"claude_code"})

    def _load_allowed_tools_section(self, key: str) -> dict:
        """Load ``configuration.yaml`` and return ``allowed_tools.<key>``.

        Asserts presence of every level above ``key`` so a missing or
        misspelled top-level mapping produces a targeted assertion
        message instead of a raw ``KeyError`` traceback.  Used by the
        schema canaries so future regressions stay actionable.
        """
        with open(constants.CONFIG_PATH, "r", encoding="utf-8") as fh:
            loaded = yaml_parser.parse_yaml_subset(fh.read())
        self.assertIn(
            "skill", loaded,
            msg="configuration.yaml must define top-level `skill`",
        )
        skill = loaded["skill"]
        self.assertIn(
            "allowed_tools", skill,
            msg="configuration.yaml must define `skill.allowed_tools`",
        )
        allowed_tools = skill["allowed_tools"]
        self.assertIn(
            key, allowed_tools,
            msg=(
                f"configuration.yaml must define "
                f"`skill.allowed_tools.{key}`"
            ),
        )
        return allowed_tools[key]

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

    def test_provenance_metadata_does_not_pollute_catalog_sets(self) -> None:
        # Defensive regression: ``provenance`` is a sibling mapping
        # under ``catalogs.claude_code`` (added in #118 to give the
        # drift helper a single source of truth for the upstream URL
        # and last-checked date).  The constants loader subscripts
        # ``harness_tools`` and ``cli_tools`` explicitly rather than
        # iterating bucket children, but if a future code edit ever
        # iterates and pollutes these sets, this test catches it.
        polluters = {
            "provenance", "source_url", "last_checked",
        }
        for polluter in polluters:
            self.assertNotIn(polluter, constants.HARNESS_TOOLS_CLAUDE_CODE)
            self.assertNotIn(polluter, constants.CLI_TOOLS_CLAUDE_CODE)
            self.assertNotIn(polluter, constants.KNOWN_TOOLS)

    def test_known_tools_recognises_lowercase_bash(self) -> None:
        # Backwards-compat: existing skills may list lowercase ``bash``.
        # Recognition INFO must continue to treat it as known.
        self.assertIn("bash", constants.KNOWN_TOOLS)

    def test_known_tools_recognises_pascalcase_bash(self) -> None:
        self.assertIn("Bash", constants.KNOWN_TOOLS)

    def test_catalogs_harness_children_are_tool_lists(self) -> None:
        # Schema invariant for drift-managed harnesses: every direct
        # child of ``skill.allowed_tools.catalogs.<harness>`` is a
        # list of tool names.  ``provenance`` lives under a sibling
        # top-level key ``catalog_provenance.<harness>`` so a reader
        # iterating the catalog bucket does not need to special-case
        # a non-list child.  This canary scopes to
        # ``_DRIFT_MANAGED_HARNESSES`` so a future non-drift-managed
        # harness with its own bucket shape (allowed by the
        # ``configuration.yaml`` comment under ``catalogs:``) does
        # not trip the test.  The canary fails loudly if a YAML edit
        # re-introduces a ``provenance`` key under any drift-managed
        # harness bucket or any other non-list child.  The
        # provenance-specific check runs first so the most-likely
        # regression (re-introducing ``provenance``) produces the
        # most-informative error message; an unrelated non-list
        # field trips the second check.
        catalogs = self._load_allowed_tools_section("catalogs")
        for harness_name in self._DRIFT_MANAGED_HARNESSES:
            self.assertIn(
                harness_name, catalogs,
                msg=(
                    f"drift-managed harness {harness_name!r} must "
                    "have a `catalogs` bucket"
                ),
            )
            bucket = catalogs[harness_name]
            # Defensive: a future YAML edit that turns the harness
            # bucket itself into a scalar or list would otherwise
            # raise ``AttributeError`` at ``bucket.items()`` below
            # and produce an opaque traceback instead of an
            # actionable assertion failure.  Mirrors the
            # provenance canary's upfront ``dict`` check.
            self.assertIsInstance(
                bucket, dict,
                msg=(
                    f"catalogs.{harness_name} must be a mapping; "
                    f"got {type(bucket).__name__}"
                ),
            )
            for child_key, child_value in bucket.items():
                self.assertNotEqual(
                    child_key, "provenance",
                    msg=(
                        f"`provenance` must not be a child of "
                        f"catalogs.{harness_name}; use top-level "
                        "`catalog_provenance.<harness>` instead"
                    ),
                )
                self.assertIsInstance(
                    child_value, list,
                    msg=(
                        f"catalogs.{harness_name}.{child_key} must be "
                        f"a tool-name list under the schema; "
                        f"got {type(child_value).__name__}"
                    ),
                )
                # Each item must be a non-empty string.  Without this
                # check a malformed edit (a stray ``-`` producing a
                # ``None`` item, an empty quoted string, or a non-string
                # scalar like a bare integer) would still satisfy the
                # is-a-list guard above and only fail later in
                # downstream consumers.
                for item_index, item in enumerate(child_value):
                    self.assertIsInstance(
                        item, str,
                        msg=(
                            f"catalogs.{harness_name}.{child_key}"
                            f"[{item_index}] must be a string; "
                            f"got {type(item).__name__}"
                        ),
                    )
                    self.assertNotEqual(
                        item.strip(), "",
                        msg=(
                            f"catalogs.{harness_name}.{child_key}"
                            f"[{item_index}] must be non-empty"
                        ),
                    )

    def test_catalog_provenance_harness_shape_is_uniform(self) -> None:
        # Symmetric canary to ``test_catalogs_harness_children_are_tool_lists``:
        # that one protects the catalog half of the schema, this one
        # protects the provenance half.  Schema invariant for
        # drift-managed harnesses: every direct child of
        # ``skill.allowed_tools.catalog_provenance`` is a mapping with
        # exactly ``source_url`` and ``last_checked`` non-empty scalar
        # children, with ``last_checked`` in the canonical
        # ``YYYY-MM-DD`` form.  Without this canary, a typo, extra
        # key, or wrong date format under a drift-managed harness
        # bucket would only be caught at drift-run time when the
        # helper hardcodes the harness lookup and parses the bucket.
        catalog_provenance = self._load_allowed_tools_section(
            "catalog_provenance"
        )
        expected_keys = {"source_url", "last_checked"}
        for harness_name in self._DRIFT_MANAGED_HARNESSES:
            self.assertIn(
                harness_name, catalog_provenance,
                msg=(
                    f"drift-managed harness {harness_name!r} must "
                    "have a `catalog_provenance` bucket"
                ),
            )
            bucket = catalog_provenance[harness_name]
            self.assertIsInstance(
                bucket, dict,
                msg=(
                    f"catalog_provenance.{harness_name} must be a "
                    f"mapping; got {type(bucket).__name__}"
                ),
            )
            self.assertEqual(
                set(bucket.keys()), expected_keys,
                msg=(
                    f"catalog_provenance.{harness_name} must have "
                    f"exactly {sorted(expected_keys)} as children; "
                    f"got {sorted(bucket.keys())}"
                ),
            )
            for key, value in bucket.items():
                self.assertIsInstance(
                    value, str,
                    msg=(
                        f"catalog_provenance.{harness_name}.{key} "
                        f"must be a scalar string; got "
                        f"{type(value).__name__}"
                    ),
                )
                self.assertNotEqual(
                    value.strip(), "",
                    msg=(
                        f"catalog_provenance.{harness_name}.{key} "
                        "must be non-empty"
                    ),
                )
            # ``last_checked`` must parse as ISO-8601 ``YYYY-MM-DD`` —
            # the same contract ``parse_catalog`` enforces at runtime.
            # Without this pin a future harness bucket could ship
            # ``last_checked: yesterday`` and pass the canary even
            # though the drift helper would reject it.  The explicit
            # shape pre-check matters because
            # ``datetime.date.fromisoformat`` alone accepts the compact
            # ISO form (e.g. ``20260501``) since Python 3.11; the
            # helper documents and writes only the extended form, so
            # the canary pins that form here too.
            self.assertRegex(
                bucket["last_checked"], r"^\d{4}-\d{2}-\d{2}$",
                msg=(
                    f"catalog_provenance.{harness_name}.last_checked "
                    f"must be ISO-8601 YYYY-MM-DD (extended form with "
                    f"hyphen separators); got "
                    f"{bucket['last_checked']!r}"
                ),
            )
            try:
                datetime.date.fromisoformat(bucket["last_checked"])
            except ValueError as exc:
                self.fail(
                    f"catalog_provenance.{harness_name}.last_checked "
                    f"must be a valid date; got "
                    f"{bucket['last_checked']!r} ({exc})"
                )

    def test_drift_managed_harnesses_present_in_both_maps(self) -> None:
        # Cross-canary check: every drift-managed harness must have a
        # bucket under both ``catalogs`` and ``catalog_provenance``.
        # The two earlier canaries validate each half independently,
        # so a future edit could land a new drift-managed harness in
        # one map without the matching bucket in the other and both
        # per-half canaries would still pass; the mismatch would only
        # surface at drift-run time when the helper hard-fails on the
        # missing lookup.  Scope is the same drift-managed set as the
        # per-half canaries — non-drift-managed harnesses (allowed by
        # the ``configuration.yaml`` comment under ``catalogs:`` to
        # use their own bucket shape) are not required to appear in
        # both maps.
        catalog_keys = set(
            self._load_allowed_tools_section("catalogs").keys()
        )
        provenance_keys = set(
            self._load_allowed_tools_section("catalog_provenance").keys()
        )
        missing_in_catalogs = self._DRIFT_MANAGED_HARNESSES - catalog_keys
        missing_in_provenance = (
            self._DRIFT_MANAGED_HARNESSES - provenance_keys
        )
        self.assertFalse(
            missing_in_catalogs or missing_in_provenance,
            msg=(
                f"every drift-managed harness must appear in both "
                f"`catalogs` and `catalog_provenance`; missing from "
                f"catalogs: {sorted(missing_in_catalogs)}; missing "
                f"from catalog_provenance: "
                f"{sorted(missing_in_provenance)}"
            ),
        )


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


class CapabilitySkillOnlyFieldsTests(unittest.TestCase):
    """``CAPABILITY_SKILL_ONLY_FIELDS`` shape and contents."""

    def test_is_tuple(self) -> None:
        self.assertIsInstance(constants.CAPABILITY_SKILL_ONLY_FIELDS, tuple)

    def test_includes_top_level_fields(self) -> None:
        self.assertIn("license", constants.CAPABILITY_SKILL_ONLY_FIELDS)
        self.assertIn("compatibility", constants.CAPABILITY_SKILL_ONLY_FIELDS)

    def test_includes_metadata_subfields(self) -> None:
        self.assertIn(
            "metadata.author", constants.CAPABILITY_SKILL_ONLY_FIELDS
        )
        self.assertIn(
            "metadata.version", constants.CAPABILITY_SKILL_ONLY_FIELDS
        )
        self.assertIn(
            "metadata.spec", constants.CAPABILITY_SKILL_ONLY_FIELDS
        )

    def test_entries_are_strings(self) -> None:
        for field in constants.CAPABILITY_SKILL_ONLY_FIELDS:
            self.assertIsInstance(field, str)


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

        def fake_open(file: object, *args: object, **kwargs: object) -> object:
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

    def test_missing_orphan_references_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus("orphan_references")
            )
        self.assertIn("orphan_references", str(ctx.exception))

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

    def test_missing_capability_frontmatter_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus_nested("skill", "capability_frontmatter")
            )
        self.assertIn("capability_frontmatter", str(ctx.exception))

    def test_missing_skill_only_fields_raises(self) -> None:
        # Removing the only child leaf below ``capability_frontmatter:``
        # leaves the YAML key dangling, which the foundry's stdlib-only
        # parser surfaces as a non-mapping value.  The shape check
        # added in this branch fires first with a more actionable
        # message naming the offending parent — that is the canonical
        # failure mode for "skill_only_fields is missing" because the
        # parent shape itself is the discriminator.
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_minus_nested(
                    "capability_frontmatter", "skill_only_fields",
                )
            )
        self.assertIn("capability_frontmatter", str(ctx.exception))

    def test_capability_frontmatter_non_mapping_raises(self) -> None:
        # A typo like ``capability_frontmatter: []`` would otherwise
        # pass the ``"skill_only_fields" in _capability_frontmatter``
        # check (lists support ``in`` for elements) and crash with a
        # bare TypeError on the next subscript.  The shape check must
        # raise a clear RuntimeError naming the offending key so the
        # fail-fast contract holds for malformed scalars and lists.
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_with_substitution(
                    "capability_frontmatter:\n    skill_only_fields:\n      - license\n      - compatibility\n      - metadata.author\n      - metadata.version\n      - metadata.spec",
                    "capability_frontmatter: []",
                )
            )
        self.assertIn("capability_frontmatter", str(ctx.exception))
        self.assertIn("expected a mapping", str(ctx.exception))

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

    def test_duplicate_entry_in_trigger_phrases_raises(self) -> None:
        # Duplicate entries indicate a config edit accident.  The
        # loader fails fast (symmetric with the empty-entry guard)
        # rather than silently deduplicating.
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_with_substitution(
                    "      - triggers on\n",
                    "      - triggers on\n      - triggers on\n",
                )
            )
        self.assertIn("trigger_phrases", str(ctx.exception))
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_allowed_orphans_absolute_path_raises(self) -> None:
        # Absolute / UNC entries would only match on a specific
        # machine's filesystem, silently failing to suppress the rule
        # everywhere else.  Loader must refuse loudly.
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_with_substitution(
                    "orphan_references:\n  allowed_orphans:\n",
                    "orphan_references:\n  allowed_orphans:\n"
                    "    - /absolute/path.md\n",
                )
            )
        message = str(ctx.exception)
        self.assertIn("allowed_orphans", message)
        self.assertIn("/absolute/path.md", message)

    def test_allowed_orphans_parent_traversal_raises(self) -> None:
        # ``..`` segments could escape the intended root.  They never
        # match a candidate orphan inside the skill, so silently
        # accepting them would make the entry inert.  Refuse loudly.
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_with_substitution(
                    "orphan_references:\n  allowed_orphans:\n",
                    "orphan_references:\n  allowed_orphans:\n"
                    "    - references/../escape.md\n",
                )
            )
        message = str(ctx.exception)
        self.assertIn("allowed_orphans", message)
        self.assertIn("'..'", message)

    def test_duplicate_error_surfaces_raw_and_normalized_forms(self) -> None:
        # Author writes 'Triggers When' (mixed case) and again as
        # 'triggers when' — both normalize to the same value.  The
        # error must surface the raw value the author actually wrote
        # so they can find the offending line in the YAML, plus the
        # normalized form so they understand why it collided.
        with self.assertRaises(RuntimeError) as ctx:
            self._reimport_with_config(
                self._full_config_with_substitution(
                    "      - triggers on\n",
                    "      - triggers on\n      - Triggers On\n",
                )
            )
        message = str(ctx.exception)
        self.assertIn("Triggers On", message)
        self.assertIn("triggers on", message)
        self.assertIn("normalized", message)


if __name__ == "__main__":
    unittest.main()
