"""Repository gitattributes contract tests."""

import os
import subprocess
import unittest


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _parse_check_attr_output(stdout: str) -> dict[str, dict[str, str]]:
    """Parse ``git check-attr`` output into a nested dict.

    Each output line has the form ``path: attribute: value``.  Splitting
    from the left with a limit of 3 handles all real fixture paths —
    none contain ``: `` in this repository.
    """
    attributes: dict[str, dict[str, str]] = {}
    for line in stdout.splitlines():
        path, attr, value = line.split(": ", 2)
        attributes.setdefault(path, {})[attr] = value
    return attributes


def _check_attrs_unset(
    test: unittest.TestCase,
    fixture_paths: tuple[str, ...],
) -> None:
    """Assert ``text`` and ``eol`` are ``unset`` for each *fixture_paths*."""
    result = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *fixture_paths],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        test.skipTest(f"git check-attr unavailable: {result.stderr.strip()}")

    attributes = _parse_check_attr_output(result.stdout)

    for path in fixture_paths:
        with test.subTest(path=path):
            test.assertEqual(attributes[path]["text"], "unset")
            test.assertEqual(attributes[path]["eol"], "unset")


class YamlConformanceAttributesTests(unittest.TestCase):
    """Byte-exact YAML corpus fixtures must not inherit text conversion."""

    def test_yaml_conformance_fixtures_unset_text_and_eol(self) -> None:
        fixture_paths = (
            "tests/fixtures/yaml-conformance/supported/block-folded.lf.yaml",
            "tests/fixtures/yaml-conformance/supported/block-folded.crlf.yaml",
            "tests/fixtures/yaml-conformance/supported/block-folded.mixed.yaml",
        )
        _check_attrs_unset(self, fixture_paths)


class BinaryAttributesTests(unittest.TestCase):
    """Binary patterns must not inherit repository-wide eol policy."""

    def test_common_binary_patterns_unset_text_and_eol(self) -> None:
        fixture_paths = (
            "example.png",
            "example.jpg",
            "example.jpeg",
            "example.gif",
            "example.zip",
            "example.gz",
        )
        _check_attrs_unset(self, fixture_paths)


if __name__ == "__main__":
    unittest.main()
