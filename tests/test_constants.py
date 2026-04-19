"""Tests for lib.constants module-load behaviour.

Covers the lazy divergence re-parse of ``configuration.yaml`` via
``get_config_findings`` and verifies ``CONFIG_PATH`` is an absolute
path pointing at the expected file.
"""

import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
