"""End-to-end integration smoke tests for the authoring and release pipelines.

Two cases live here:

- ``ScaffoldBundlePipelineTests`` — scaffold a standalone skill, validate it,
  patch its frontmatter the way a real author would, bundle it, unzip the
  bundle into a clean temp dir, and revalidate. Guards the user-facing
  authoring flow driven by ``scaffold.py`` and ``bundle.py``.

- ``ReleaseArtifactPipelineTests`` — mirror what ``.github/workflows/release.yml``
  actually ships (a raw zip of ``skill-system-foundry/``), unzip on a clean
  path, and validate with the same flags the foundry uses to validate
  itself. Guards the release artifact, which is produced by ``zip -r`` and
  is not covered by the ``bundle.py`` path.

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


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "skill-system-foundry", "scripts")
SCAFFOLD_SCRIPT = os.path.join(SCRIPTS_DIR, "scaffold.py")
VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, "validate_skill.py")
BUNDLE_SCRIPT = os.path.join(SCRIPTS_DIR, "bundle.py")
FOUNDRY_DIR = os.path.join(REPO_ROOT, "skill-system-foundry")


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _assert_ok(test: unittest.TestCase, proc: subprocess.CompletedProcess) -> None:
    test.assertEqual(
        proc.returncode,
        0,
        msg=f"exit={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
    )


# Short, realistic SKILL.md that a downstream author would produce
# after editing the scaffold output. Must fit under the Claude bundle
# description limit (200 chars) so bundle.py --target claude passes.
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
    """scaffold -> validate -> (edit frontmatter) -> bundle -> unzip -> validate."""

    def test_standalone_skill_round_trip(self) -> None:
        skill_name = "pipeline-demo"

        with tempfile.TemporaryDirectory() as system_root:
            scaffold = _run([
                sys.executable, SCAFFOLD_SCRIPT,
                "skill", skill_name,
                "--root", system_root,
                "--update-manifest",
            ])
            _assert_ok(self, scaffold)

            skill_dir = os.path.join(system_root, "skills", skill_name)
            self.assertTrue(os.path.isdir(skill_dir))
            self.assertTrue(
                os.path.isfile(os.path.join(system_root, "manifest.yaml")),
                msg="--update-manifest should have produced manifest.yaml",
            )

            validate_scaffolded = _run([
                sys.executable, VALIDATE_SCRIPT, skill_dir,
            ])
            _assert_ok(self, validate_scaffolded)

            # Simulate the author filling in the template placeholders
            # before distribution. The raw scaffold output carries a
            # 317-char placeholder description that fails bundle.py's
            # Claude 200-char limit — real users always edit before
            # bundling, and this is the minimal patch that mirrors that.
            skill_md_path = os.path.join(skill_dir, "SKILL.md")
            with open(skill_md_path, "w", encoding="utf-8") as f:
                f.write(_PATCHED_SKILL_MD.format(
                    name=skill_name,
                    title=skill_name.replace("-", " ").title(),
                ))

            validate_edited = _run([
                sys.executable, VALIDATE_SCRIPT, skill_dir,
            ])
            _assert_ok(self, validate_edited)

            bundle_zip = os.path.join(system_root, f"{skill_name}.zip")
            bundle = _run([
                sys.executable, BUNDLE_SCRIPT, skill_dir,
                "--output", bundle_zip,
            ])
            _assert_ok(self, bundle)
            self.assertTrue(os.path.isfile(bundle_zip))

            with tempfile.TemporaryDirectory() as extract_root:
                with zipfile.ZipFile(bundle_zip) as zf:
                    zf.extractall(extract_root)

                entries = os.listdir(extract_root)
                self.assertEqual(
                    len(entries), 1,
                    msg=f"expected single top-level entry, got {entries}",
                )
                extracted_skill = os.path.join(extract_root, entries[0])
                self.assertTrue(
                    os.path.isfile(os.path.join(extracted_skill, "SKILL.md")),
                    msg=f"extracted bundle missing SKILL.md: {extracted_skill}",
                )

                validate_extracted = _run([
                    sys.executable, VALIDATE_SCRIPT, extracted_skill,
                ])
                _assert_ok(self, validate_extracted)


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
            with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as zf:
                for dirpath, _dirnames, filenames in os.walk(FOUNDRY_DIR):
                    for filename in filenames:
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
