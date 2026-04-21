"""End-to-end integration smoke tests for the authoring and release pipelines.

Three cases live here:

- ``ScaffoldBundlePipelineTests.test_standalone_skill_round_trip`` —
  scaffold a standalone skill, validate it, patch its frontmatter the way
  a real author would, bundle it with the default ``--target claude``,
  unzip the bundle into a clean temp dir, and revalidate. Guards the
  user-facing authoring flow driven by ``scaffold.py`` and ``bundle.py``
  for the platform with the tightest limit.

- ``ScaffoldBundlePipelineTests.test_generic_target_accepts_raw_scaffold_output`` —
  same pipeline without the frontmatter patch, bundled with
  ``--target generic``. Proves that at least one supported target path
  works end-to-end on the unmodified scaffold output and keeps the
  known ``--target claude`` UX gap from hiding a generic-target
  regression.

- ``ReleaseArtifactPipelineTests`` — mirror what
  ``.github/workflows/release.yml`` actually ships (a raw zip of
  ``skill-system-foundry/``), unzip on a clean path, and validate with
  the same flags the foundry uses to validate itself. Guards the
  release artifact, which is produced by ``zip -r`` and is not covered
  by the ``bundle.py`` path.

Subprocess + ``tempfile.TemporaryDirectory`` + stdlib ``zipfile`` —
matches the conventions in ``test_scaffold_cli.py`` and
``test_bundle_cli.py``. Runs on the ubuntu + windows matrix in
``python-tests.yaml`` without any workflow changes.
"""

import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

from helpers import run_script


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "skill-system-foundry", "scripts")
SCAFFOLD_SCRIPT = os.path.join(SCRIPTS_DIR, "scaffold.py")
VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, "validate_skill.py")
BUNDLE_SCRIPT = os.path.join(SCRIPTS_DIR, "bundle.py")
FOUNDRY_DIR = os.path.join(REPO_ROOT, "skill-system-foundry")


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return run_script(argv, cwd=REPO_ROOT)


def _assert_ok(test: unittest.TestCase, proc: subprocess.CompletedProcess) -> None:
    test.assertEqual(
        proc.returncode,
        0,
        msg=f"exit={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
    )


def _scaffold_standalone(
    test: unittest.TestCase, system_root: str, skill_name: str,
) -> str:
    """Scaffold a standalone skill into *system_root* and return its directory."""
    proc = _run([
        sys.executable, SCAFFOLD_SCRIPT,
        "skill", skill_name,
        "--root", system_root,
        "--update-manifest",
    ])
    _assert_ok(test, proc)
    return os.path.join(system_root, "skills", skill_name)


def _bundle_and_extract(
    test: unittest.TestCase,
    skill_dir: str,
    skill_name: str,
    system_root: str,
    target: str,
) -> None:
    """Bundle *skill_dir* with *target* and revalidate the extracted copy."""
    bundle_zip = os.path.join(system_root, f"{skill_name}-{target}.zip")
    bundle = _run([
        sys.executable, BUNDLE_SCRIPT, skill_dir,
        "--output", bundle_zip,
        "--target", target,
    ])
    _assert_ok(test, bundle)
    test.assertTrue(os.path.isfile(bundle_zip))

    with tempfile.TemporaryDirectory() as extract_root:
        with zipfile.ZipFile(bundle_zip) as zf:
            zf.extractall(extract_root)

        entries = os.listdir(extract_root)
        test.assertIn(
            skill_name, entries,
            msg=f"extracted bundle missing top-level {skill_name}/ dir; got {entries}",
        )
        extracted_skill = os.path.join(extract_root, skill_name)
        test.assertTrue(
            os.path.isfile(os.path.join(extracted_skill, "SKILL.md")),
            msg=f"extracted bundle missing SKILL.md: {extracted_skill}",
        )

        validate_extracted = _run([
            sys.executable, VALIDATE_SCRIPT, extracted_skill,
        ])
        _assert_ok(test, validate_extracted)


# Short, realistic SKILL.md that a downstream author would produce
# after editing the scaffold output. Must fit under the Claude bundle
# description limit (200 chars) so bundle.py --target claude passes.
#
# Known UX gap: the raw scaffold template ships a 317-char placeholder
# description that fails `bundle.py --target claude` out of the box. A
# first-time user running scaffold -> bundle with the default target
# hits the 200-char failure with no guidance. This test patches around
# it to exercise the full default-target pipeline; shortening the
# placeholder in ``skill-system-foundry/assets/skill-standalone.md``
# is the real fix and belongs in a separate change. The companion test
# ``test_generic_target_accepts_raw_scaffold_output`` below proves the
# non-default target paths do not hit this wall, scoping the gap.
_PATCHED_SKILL_MD = """---
name: {name}
description: >
  Processes integration smoke test inputs. Triggers when verifying the
  scaffold to bundle pipeline end to end.
license: MIT
metadata:
  author: Integration Test
  version: 1.0.0
---

# {title}

## Purpose

Minimal standalone skill used by the integration pipeline smoke test.

## Instructions

Follow the normal skill lifecycle: scaffold, edit, validate, bundle.
"""


class ScaffoldBundlePipelineTests(unittest.TestCase):
    """scaffold -> validate -> bundle -> unzip -> validate, across targets."""

    def test_standalone_skill_round_trip(self) -> None:
        """Default --target claude, with the realistic author-edit step."""
        skill_name = "pipeline-demo"

        with tempfile.TemporaryDirectory() as system_root:
            skill_dir = _scaffold_standalone(self, system_root, skill_name)
            self.assertTrue(os.path.isdir(skill_dir))
            self.assertTrue(
                os.path.isfile(os.path.join(system_root, "manifest.yaml")),
                msg="--update-manifest should have produced manifest.yaml",
            )

            _assert_ok(self, _run([
                sys.executable, VALIDATE_SCRIPT, skill_dir,
            ]))

            # Simulate the author filling in the template placeholders
            # before distribution — see _PATCHED_SKILL_MD module-level
            # comment for the UX-gap context.
            skill_md_path = os.path.join(skill_dir, "SKILL.md")
            with open(skill_md_path, "w", encoding="utf-8") as f:
                f.write(_PATCHED_SKILL_MD.format(
                    name=skill_name,
                    title=skill_name.replace("-", " ").title(),
                ))

            _assert_ok(self, _run([
                sys.executable, VALIDATE_SCRIPT, skill_dir,
            ]))

            _bundle_and_extract(
                self, skill_dir, skill_name, system_root, target="claude",
            )

    def test_generic_target_accepts_raw_scaffold_output(self) -> None:
        """--target generic must bundle the unmodified scaffold output.

        Scopes the default-target UX gap and guards against a regression
        that would flip the 200-char limit from warning to error on the
        non-default targets.
        """
        skill_name = "pipeline-demo-generic"

        with tempfile.TemporaryDirectory() as system_root:
            skill_dir = _scaffold_standalone(self, system_root, skill_name)

            _assert_ok(self, _run([
                sys.executable, VALIDATE_SCRIPT, skill_dir,
            ]))

            _bundle_and_extract(
                self, skill_dir, skill_name, system_root, target="generic",
            )


class ReleaseArtifactPipelineTests(unittest.TestCase):
    """Mirror release.yml's `zip -r skill-system-foundry/` artifact.

    release.yml does not run bundle.py — it ships a raw zip of the
    skill directory. This test guards that specific artifact shape
    against the same "unzip and validate on a clean machine" regression
    the bundle pipeline case guards for user skills.
    """

    def test_released_artifact_unzips_and_validates(self) -> None:
        self.assertTrue(
            os.path.isdir(FOUNDRY_DIR),
            msg=f"expected foundry dir at {FOUNDRY_DIR}",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = os.path.join(tmpdir, "skill-system-foundry.zip")

            # Stdlib zipfile mirrors `zip -r` semantics and works on
            # Windows matrix cells where the `zip` CLI is absent.
            # Bytecode (__pycache__/, *.pyc) is pruned so the local run
            # matches release.yml's fresh-checkout shape; otherwise a
            # developer's stale bytecode would diverge from the real
            # release artifact and could mask a regression. IDE / OS
            # scratch files (.DS_Store, Thumbs.db, .idea/, .vscode/)
            # are not filtered — release.yml's `zip -r` would include
            # them too, so the test stays faithful to that behaviour.
            with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as zf:
                for dirpath, dirnames, filenames in os.walk(FOUNDRY_DIR):
                    if "__pycache__" in dirnames:
                        dirnames.remove("__pycache__")
                    for filename in filenames:
                        if filename.endswith(".pyc"):
                            continue
                        abs_path = os.path.join(dirpath, filename)
                        arcname = os.path.relpath(abs_path, REPO_ROOT)
                        zf.write(abs_path, arcname)

            extract_root = os.path.join(tmpdir, "extracted")
            os.makedirs(extract_root)
            with zipfile.ZipFile(artifact) as zf:
                zf.extractall(extract_root)

            extracted_skill = os.path.join(extract_root, "skill-system-foundry")
            self.assertTrue(
                os.path.isfile(os.path.join(extracted_skill, "SKILL.md")),
                msg=f"extracted release artifact missing SKILL.md at {extracted_skill}",
            )

            validate = _run([
                sys.executable, VALIDATE_SCRIPT, extracted_skill,
                "--allow-nested-references",
                "--foundry-self",
            ])
            _assert_ok(self, validate)


if __name__ == "__main__":
    unittest.main()
