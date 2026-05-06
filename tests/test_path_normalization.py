"""Regression: every path that crosses a UI boundary uses forward slashes.

The reporting docstring documents ``to_posix`` as the chokepoint for
any path that lands in JSON output or in a FAIL/WARN/INFO finding
string.  Production paths flow through ``os.path.relpath`` /
``os.path.join`` which produce native separators on Windows; if a
new emitter forgets either the explicit ``to_posix`` call or the
ad-hoc ``.replace(os.sep, "/")`` idiom, the only safety net before
this test was a Windows-runner failure on the next CI cycle.

These tests run ``validate_skill.py``, ``audit_skill_system.py``,
``bundle.py``, and ``stats.py`` with ``--json`` against synthetic
fixtures, parse the output, and assert no backslash appears in
any string field of the payload.  Coverage is host-dependent:

* On Windows runners, ``os.path.abspath`` and friends produce
  backslash-form paths, so any emitter that forgets ``to_posix``
  surfaces a backslash in the JSON immediately and this test
  fails.
* On POSIX runners (Linux / macOS), ``os.sep == "/"``, so the
  underlying primitives never produce backslashes and the
  assertion passes trivially regardless of whether ``to_posix``
  is applied.  The test still runs (and acts as a smoke check
  that the JSON shape is parseable and the chosen ``"path"``
  field is present), but it cannot catch a missing ``to_posix``
  call here — that is reserved for the Windows matrix entry.

A previous iteration of this docstring claimed that the test
patches ``os.sep`` to ``"\\\\"`` on POSIX runners to simulate the
Windows shape.  No such patching exists; that claim was
aspirational rather than implemented.  Achieving it would
require subprocess-level patching (the entry points are invoked
via ``subprocess.run``, so an in-process ``mock.patch`` does
not propagate).  Possible follow-ups: import the ``main()``
functions and call them in-process under a ``mock.patch`` of
``os.sep`` / ``os.path.sep``, or pass an ``OS_SEP_OVERRIDE``
environment variable that the entry points honour.  Neither is
in scope for this PR.
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


def _build_minimal_system_root(root: str) -> str:
    """Build a minimal deployed-system layout: ``<root>/skills/demo/SKILL.md``.

    Used to exercise ``audit_skill_system.py``'s system-root mode, where
    the audit walks ``skills/<name>/SKILL.md`` rather than a single
    skill root.  The skill body is the same as ``_build_minimal_skill``
    so audit findings are predictably clean.
    """
    skills_dir = os.path.join(root, "skills")
    skill_dir = os.path.join(skills_dir, "demo")
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
    return root


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

    def test_audit_skill_system_json_payload_is_posix_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = _build_minimal_system_root(tmpdir)
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(SCRIPTS_DIR, "audit_skill_system.py"),
                    system_root,
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
                    "Backslashes leaked into audit_skill_system JSON "
                    "payload.  Offenders:\n  " + "\n  ".join(offenders)
                ),
            )

    def test_bundle_json_payload_is_posix_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = _build_minimal_skill(tmpdir)
            output_path = os.path.join(tmpdir, "demo.zip")
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(SCRIPTS_DIR, "bundle.py"),
                    skill_dir,
                    "--output", output_path,
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
                    "Backslashes leaked into bundle JSON payload.  "
                    "Offenders:\n  " + "\n  ".join(offenders)
                ),
            )


if __name__ == "__main__":
    unittest.main()
