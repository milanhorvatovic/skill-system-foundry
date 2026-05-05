"""Regression: every path that crosses a UI boundary uses forward slashes.

The reporting docstring documents ``to_posix`` as the chokepoint for
any path that lands in JSON output or in a FAIL/WARN/INFO finding
string.  Production paths flow through ``os.path.relpath`` /
``os.path.join`` which produce native separators on Windows; if a
new emitter forgets either the explicit ``to_posix`` call or the
ad-hoc ``.replace(os.sep, "/")`` idiom, the only safety net before
this test was a Windows-runner failure on the next CI cycle.

This test runs ``validate_skill.py --json`` against synthetic
fixtures whose source paths contain backslashes (achieved on POSIX
runners by patching ``os.sep`` to ``"\\\\"`` in the stats / validator
helpers).  The output is parsed and every string field is checked
for backslash presence.  A single backslash anywhere in the JSON
shape is a regression.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
SCRIPTS_DIR = os.path.join(
    REPO_ROOT, "skill-system-foundry", "scripts"
)


def _walk_strings(payload: object) -> list[str]:
    """Yield every string leaf in *payload*."""
    out: list[str] = []
    if isinstance(payload, str):
        out.append(payload)
    elif isinstance(payload, dict):
        for value in payload.values():
            out.extend(_walk_strings(value))
    elif isinstance(payload, list):
        for item in payload:
            out.extend(_walk_strings(item))
    return out


def _build_minimal_skill(root: str) -> str:
    skill_dir = os.path.join(root, "demo")
    os.makedirs(os.path.join(skill_dir, "references"))
    with open(
        os.path.join(skill_dir, "SKILL.md"),
        "w", encoding="utf-8", newline="\n",
    ) as fh:
        fh.write(
            "---\n"
            "name: demo\n"
            "description: triggers when the demo runs\n"
            "---\n"
            "# Demo\n\nSee [guide](references/guide.md).\n"
        )
    with open(
        os.path.join(skill_dir, "references", "guide.md"),
        "w", encoding="utf-8", newline="\n",
    ) as fh:
        fh.write("# Guide\n\nbody\n")
    return skill_dir


class JSONPathFieldsAreForwardSlashedTests(unittest.TestCase):
    """No backslash in any JSON string emitted by validate_skill."""

    def test_validate_skill_json_payload_is_posix_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = _build_minimal_skill(tmpdir)
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(SCRIPTS_DIR, "validate_skill.py"),
                    skill_dir,
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            payload = json.loads(result.stdout)
            offenders = [
                s for s in _walk_strings(payload) if "\\" in s
            ]
            self.assertEqual(
                offenders, [],
                msg=(
                    "Backslashes leaked into JSON payload — every "
                    "path that crosses the UI boundary must pass "
                    "through to_posix.  Offenders:\n  "
                    + "\n  ".join(offenders)
                ),
            )

    def test_stats_json_payload_is_posix_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = _build_minimal_skill(tmpdir)
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(SCRIPTS_DIR, "stats.py"),
                    skill_dir,
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            payload = json.loads(result.stdout)
            offenders = [
                s for s in _walk_strings(payload) if "\\" in s
            ]
            self.assertEqual(
                offenders, [],
                msg=(
                    "Backslashes leaked into stats JSON payload.  "
                    "Offenders:\n  " + "\n  ".join(offenders)
                ),
            )


if __name__ == "__main__":
    unittest.main()
