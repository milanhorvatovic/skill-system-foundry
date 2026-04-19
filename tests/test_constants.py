"""Tests for lib.constants module-load behaviour.

Covers the lazy divergence re-parse of ``configuration.yaml`` via
``get_config_findings``, verifies ``CONFIG_PATH`` is an absolute path
pointing at the expected file, and pins the new ``prose_yaml`` and
``prose_yaml`` keys.  Missing-section fail-fast is exercised by
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


if __name__ == "__main__":
    unittest.main()
