"""Tests for lib.reporting helpers.

Covers:
- ``to_posix`` — separator replacement on POSIX-style and
  Windows-style inputs.
- ``parse_finding_string`` — parser-finding-string round-trip and
  malformed-input rejection.  Tag-agnostic handling is exercised with
  a synthetic unrecognized tag.
"""

import os
import sys
import unittest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib import reporting  # noqa: E402
from lib.yaml_parser import parse_yaml_subset  # noqa: E402


class ToPosixTests(unittest.TestCase):
    """``to_posix`` rewrites the platform separator."""

    def test_posix_input_unchanged(self) -> None:
        self.assertEqual(
            reporting.to_posix("a/b/c"),
            "a/b/c",
        )

    def test_native_separator_replaced(self) -> None:
        native = "a" + os.sep + "b" + os.sep + "c"
        self.assertEqual(reporting.to_posix(native), "a/b/c")

    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(reporting.to_posix(""), "")


class ParseFindingStringTests(unittest.TestCase):
    """``parse_finding_string`` covers spec-tagged, untagged, and bad input."""

    def test_fail_with_spec_tag(self) -> None:
        raw = "FAIL: [spec] 'name': bad value; wrap value in single quotes"
        result = reporting.parse_finding_string(raw)
        self.assertEqual(result["severity"], "fail")
        self.assertEqual(result["tag"], "[spec]")
        self.assertEqual(
            result["message"],
            "'name': bad value; wrap value in single quotes",
        )

    def test_warn_with_spec_tag(self) -> None:
        result = reporting.parse_finding_string(
            "WARN: [spec] 'k': value warns"
        )
        self.assertEqual(result["severity"], "warn")
        self.assertEqual(result["tag"], "[spec]")

    def test_info_lowercased(self) -> None:
        result = reporting.parse_finding_string("INFO: [spec] something")
        self.assertEqual(result["severity"], "info")

    def test_untagged_body_yields_empty_tag(self) -> None:
        result = reporting.parse_finding_string("FAIL: plain message body")
        self.assertEqual(result["tag"], "")
        self.assertEqual(result["message"], "plain message body")

    def test_unknown_tag_preserved_verbatim(self) -> None:
        # The helper is tag-agnostic; any bracketed token survives.
        result = reporting.parse_finding_string(
            "FAIL: [platform] something happened"
        )
        self.assertEqual(result["tag"], "[platform]")
        self.assertEqual(result["message"], "something happened")

    def test_missing_separator_raises(self) -> None:
        with self.assertRaises(ValueError):
            reporting.parse_finding_string("no colon")

    def test_unknown_severity_raises(self) -> None:
        with self.assertRaises(ValueError):
            reporting.parse_finding_string("BAD: [spec] body")

    def test_empty_string_raises(self) -> None:
        with self.assertRaises(ValueError):
            reporting.parse_finding_string("")


class ParseFindingStringRoundTripTests(unittest.TestCase):
    """Round-trip parser findings through ``parse_finding_string``."""

    def test_known_divergent_input_round_trips(self) -> None:
        # Input crafted to trip multiple plain-scalar branches in
        # _check_plain_scalar so the findings list has several
        # FAIL/WARN entries for the round-trip pass.
        text = "a: [bad\nb: '\nc: ! tagged\n"
        findings: list[str] = []
        parse_yaml_subset(text, findings)
        self.assertGreater(len(findings), 0)
        for raw in findings:
            parsed = reporting.parse_finding_string(raw)
            # Severity reconstructs to the original token.
            severity_upper = parsed["severity"].upper()
            tag_chunk = (parsed["tag"] + " ") if parsed["tag"] else ""
            reconstructed = f"{severity_upper}: {tag_chunk}{parsed['message']}"
            self.assertEqual(reconstructed, raw)


if __name__ == "__main__":
    unittest.main()
