"""End-to-end integration smoke tests for the authoring and release pipelines.

Covers the scaffold -> validate -> bundle -> unzip -> validate flow across
bundle targets, and the `zip -r` release-artifact shape produced by
``.github/workflows/release.yml``. Runs on the ubuntu + windows matrix in
``python-tests.yaml`` without any workflow changes.
"""

import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

from helpers import safe_extractall


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "skill-system-foundry", "scripts")
SCAFFOLD_SCRIPT = os.path.join(SCRIPTS_DIR, "scaffold.py")
VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, "validate_skill.py")
BUNDLE_SCRIPT = os.path.join(SCRIPTS_DIR, "bundle.py")
FOUNDRY_DIR = os.path.join(REPO_ROOT, "skill-system-foundry")


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    # Enforce UTF-8 in the child so bundle.py's ✓/✗/⚠ and
    # validate_skill.py's → don't trip UnicodeEncodeError on the
    # Windows matrix cell's cp1252 default console encoding.
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        argv, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )


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
            safe_extractall(zf, extract_root)

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


# The exact folded-scalar description block that ``scaffold.py`` emits
# into SKILL.md, copied byte-for-byte from
# ``skill-system-foundry/assets/skill-standalone.md`` (lines 3-8).
#
# Duplication is deliberate: editing the asset template's placeholder
# description is expected to require a synchronized update here. The
# trade-off is explicit literal coupling (maintenance cost) in exchange
# for a loud, self-documenting failure when the template drifts — the
# surgical patch below raises ``assertIn`` with a pointer to this
# constant, rather than silently no-op'ing the replacement. A
# programmatic extraction from the asset file would avoid the
# duplication but would silently accept any new-shape placeholder,
# defeating the drift detector.
_TEMPLATE_DESCRIPTION_BLOCK = (
    "description: >\n"
    "  <Description of what this skill does and when to trigger it.\n"
    "  Max 1024 characters. Be specific about contexts, keywords, and use cases.\n"
    "  Include trigger phrases. Be slightly pushy to avoid under-triggering.\n"
    "  Third-person voice recommended (foundry convention).\n"
    "  Optionally include \"Don't use when...\" for disambiguation.>\n"
)

# Short replacement description that fits under every bundle target's
# limit (Claude's 200-char cap is the tightest). Known UX gap: the raw
# scaffold template ships a 317-char placeholder description that fails
# ``bundle.py --target claude`` out of the box — shortening the
# placeholder in ``skill-system-foundry/assets/skill-standalone.md`` is
# the real fix and belongs in a separate change. The companion test
# ``test_generic_target_accepts_raw_scaffold_output`` keeps the gap
# from hiding a regression on non-default targets.
_AUTHORED_DESCRIPTION_BLOCK = (
    "description: >\n"
    "  Processes integration smoke test inputs. Triggers when verifying the\n"
    "  scaffold to bundle pipeline end to end.\n"
)


def _patch_description(test: unittest.TestCase, skill_md_path: str) -> None:
    """Replace only the scaffolded description block, preserving everything else.

    Mirrors what a real author does — edit the description, leave the
    rest of the template untouched. Reading-and-patching (rather than
    overwriting the whole file) keeps this test honest: if
    ``scaffold.py`` starts emitting a new frontmatter field or body
    section, the test continues to exercise it.
    """
    with open(skill_md_path, "r", encoding="utf-8") as f:
        original = f.read()
    test.assertIn(
        _TEMPLATE_DESCRIPTION_BLOCK, original,
        msg=(
            "scaffold template's description block changed — update "
            "_TEMPLATE_DESCRIPTION_BLOCK to match the new emitted shape"
        ),
    )
    patched = original.replace(
        _TEMPLATE_DESCRIPTION_BLOCK, _AUTHORED_DESCRIPTION_BLOCK, 1,
    )
    with open(skill_md_path, "w", encoding="utf-8") as f:
        f.write(patched)


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

            # Simulate the author filling in the description placeholder
            # before distribution — see _AUTHORED_DESCRIPTION_BLOCK for
            # the UX-gap context.
            _patch_description(self, os.path.join(skill_dir, "SKILL.md"))

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
    the bundle pipeline case guards for user skills, plus the
    yaml-conformance exclusion that release.yml asserts inline.
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
                        # `zip -r` on the ubuntu release runner writes
                        # POSIX-separated entry names. Normalizing here
                        # keeps the Windows matrix cell faithful to the
                        # real release artifact shape.
                        arcname = os.path.relpath(abs_path, REPO_ROOT).replace(os.sep, "/")
                        zf.write(abs_path, arcname)

            # Mirror release.yml's "Verify bundle excludes yaml-conformance
            # corpus" step. The corpus currently lives outside the bundled
            # path, so this is a passive invariant — pin it here so a
            # future restructure that pulls the corpus into the bundle
            # fails the test before it ships.
            with zipfile.ZipFile(artifact) as zf:
                hits = [n for n in zf.namelist() if "yaml-conformance" in n]
            self.assertEqual(
                hits, [],
                msg=f"release bundle must not contain yaml-conformance entries: {hits}",
            )

            extract_root = os.path.join(tmpdir, "extracted")
            os.makedirs(extract_root)
            with zipfile.ZipFile(artifact) as zf:
                safe_extractall(zf, extract_root)

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


class SafeExtractAllTests(unittest.TestCase):
    """``safe_extractall`` refuses members that escape the destination."""

    def test_extracts_well_behaved_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = os.path.join(tmpdir, "ok.zip")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("a.txt", "alpha")
                zf.writestr("sub/b.txt", "beta")
            dest = os.path.join(tmpdir, "out")
            os.makedirs(dest)
            with zipfile.ZipFile(archive) as zf:
                safe_extractall(zf, dest)
            self.assertTrue(os.path.isfile(os.path.join(dest, "a.txt")))
            self.assertTrue(os.path.isfile(os.path.join(dest, "sub", "b.txt")))

    def test_rejects_parent_traversal_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = os.path.join(tmpdir, "evil.zip")
            # Write the traversal name into the central directory directly so
            # ZipFile does not normalise it away on creation.
            info = zipfile.ZipInfo("../escape.txt")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(info, "pwned")
            dest = os.path.join(tmpdir, "out")
            os.makedirs(dest)
            sentinel = os.path.join(tmpdir, "escape.txt")  # sibling of dest
            with zipfile.ZipFile(archive) as zf:
                from helpers import UnsafeArchiveMember
                with self.assertRaises(UnsafeArchiveMember):
                    safe_extractall(zf, dest)
            # The escaping member must not have been written anywhere outside dest.
            self.assertFalse(os.path.exists(sentinel))

    def test_rejects_archive_when_later_member_escapes(self) -> None:
        # Two-phase guarantee: a benign member ordered BEFORE an escaping
        # member must not be written to disk.  The whole member list is
        # validated before any extraction begins, so the escape is detected
        # while the destination is still empty.
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = os.path.join(tmpdir, "mixed.zip")
            evil = zipfile.ZipInfo("../escape.txt")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("benign.txt", "safe")  # first member: benign
                zf.writestr(evil, "pwned")          # second member: escapes
            dest = os.path.join(tmpdir, "out")
            os.makedirs(dest)
            sentinel = os.path.join(tmpdir, "escape.txt")  # sibling of dest
            from helpers import UnsafeArchiveMember
            with zipfile.ZipFile(archive) as zf:
                with self.assertRaises(UnsafeArchiveMember):
                    safe_extractall(zf, dest)
            # The benign member must NOT have been extracted, and the
            # escaping member must NOT have been written outside dest.
            self.assertFalse(os.path.exists(os.path.join(dest, "benign.txt")))
            self.assertFalse(os.path.exists(sentinel))

    def test_containment_allows_member_under_filesystem_root(self) -> None:
        # Regression: a filesystem-root destination ("/" on POSIX, a drive
        # root on Windows) made the old ``startswith(dest_real + os.sep)``
        # prefix check compute "//" / "C:\\\\" and wrongly reject every
        # well-behaved member.  The commonpath-based containment check
        # treats a normal member under root as contained.  Exercised on the
        # predicate directly so the test does not have to write to root.
        from helpers import _is_within_destination
        root = os.path.realpath(os.sep)
        member = os.path.realpath(os.path.join(root, "extracted", "file.txt"))
        self.assertTrue(_is_within_destination(member, root))

    def test_containment_rejects_sibling_prefix(self) -> None:
        # A sibling whose path merely shares a string prefix with dest
        # (``/tmp/out`` vs ``/tmp/out-evil``) must still be rejected — the
        # commonpath check compares whole path components, not substrings.
        from helpers import _is_within_destination
        base = os.path.realpath(os.path.join(os.sep, "tmp", "out"))
        sibling = os.path.realpath(
            os.path.join(os.sep, "tmp", "out-evil", "file.txt")
        )
        self.assertFalse(_is_within_destination(sibling, base))

    def test_rejects_absolute_path_member(self) -> None:
        # ``safe_extractall``'s docstring claims to reject absolute member
        # paths.  An absolute member resets ``os.path.join``, so it lands
        # outside dest and must raise — guard against a future containment
        # change silently reintroducing this zip-slip vector.
        from helpers import UnsafeArchiveMember
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = os.path.join(tmpdir, "abs.zip")
            # Absolute member name written via ZipInfo so ZipFile does not
            # normalise the leading separator away on creation.
            evil = zipfile.ZipInfo(f"{os.sep}abs-escape.txt")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(evil, "pwned")
            dest = os.path.join(tmpdir, "out")
            os.makedirs(dest)
            with zipfile.ZipFile(archive) as zf:
                with self.assertRaises(UnsafeArchiveMember):
                    safe_extractall(zf, dest)
            # Two-phase: nothing extracted into dest.
            self.assertEqual(os.listdir(dest), [])

    @unittest.skipUnless(
        os.name == "nt", "drive-prefix escape only applies on Windows"
    )
    def test_rejects_drive_prefixed_member(self) -> None:
        # On Windows a drive-prefixed member (``C:\\evil.txt``) is an
        # absolute path that escapes dest; the docstring claims to reject
        # it.  Skipped off-Windows, where a drive prefix is an ordinary
        # relative path component and not an escape vector.
        from helpers import UnsafeArchiveMember
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = os.path.join(tmpdir, "drive.zip")
            drive = os.path.splitdrive(os.path.realpath(tmpdir))[0] or "C:"
            evil = zipfile.ZipInfo(f"{drive}\\drive-escape.txt")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(evil, "pwned")
            dest = os.path.join(tmpdir, "out")
            os.makedirs(dest)
            with zipfile.ZipFile(archive) as zf:
                with self.assertRaises(UnsafeArchiveMember):
                    safe_extractall(zf, dest)
            self.assertEqual(os.listdir(dest), [])


if __name__ == "__main__":
    unittest.main()
