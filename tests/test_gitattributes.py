"""Repository gitattributes contract tests."""

import os
import subprocess
import unittest


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class YamlConformanceAttributesTests(unittest.TestCase):
    """Byte-exact YAML corpus fixtures must not inherit text conversion."""

    def test_yaml_conformance_fixtures_unset_text_and_eol(self) -> None:
        fixture_paths = (
            "tests/fixtures/yaml-conformance/supported/block-folded.lf.yaml",
            "tests/fixtures/yaml-conformance/supported/block-folded.crlf.yaml",
            "tests/fixtures/yaml-conformance/supported/block-folded.mixed.yaml",
        )
        result = subprocess.run(
            ["git", "check-attr", "text", "eol", "--", *fixture_paths],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            self.skipTest(f"git check-attr unavailable: {result.stderr.strip()}")

        attributes: dict[str, dict[str, str]] = {}
        for line in result.stdout.splitlines():
            path, attr, value = line.split(": ", 2)
            attributes.setdefault(path, {})[attr] = value

        for path in fixture_paths:
            with self.subTest(path=path):
                self.assertEqual(attributes[path]["text"], "unset")
                self.assertEqual(attributes[path]["eol"], "unset")


if __name__ == "__main__":
    unittest.main()
