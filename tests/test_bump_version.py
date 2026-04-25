"""Tests for scripts/bump_version.py.

Most tests operate on a scratch directory that mirrors the three manifest
files the bump script touches.  A fake ``generate_changelog.py`` stub is
installed at ``scripts/generate_changelog.py`` within the scratch repo so
the subprocess path is exercised without pulling in git history or the
real generator.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_BUMP_PATH = os.path.join(REPO_ROOT, "scripts", "bump_version.py")
_spec = importlib.util.spec_from_file_location(
    "repo_infra_bump_version", _BUMP_PATH
)
assert _spec is not None and _spec.loader is not None
bump_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_version)


SKILL_MD = """\
---
name: demo
description: >
  Demo skill.
metadata:
  author: Test
  version: {version}
  spec: agentskills.io
---

# Demo
"""

PLUGIN_JSON = """\
{{
  "name": "demo",
  "description": "Demo plugin.",
  "version": "{version}"
}}
"""

MARKETPLACE_JSON = """\
{{
  "name": "demo",
  "plugins": [
    {{
      "name": "demo",
      "description": "Demo plugin.",
      "version": "{version}"
    }}
  ]
}}
"""


# A generator stub that always succeeds.  Prints the arguments on stdout so
# tests can confirm the invocation shape.
GENERATOR_STUB_OK = """\
#!/usr/bin/env python3
import sys
print("generator ok:", " ".join(sys.argv[1:]))
sys.exit(0)
"""

# A stub that simulates the real generator's exit-3 path (unmapped commits).
GENERATOR_STUB_FAIL = """\
#!/usr/bin/env python3
import sys
print("unmapped — review manually: deadbeef Stub failure", file=sys.stderr)
sys.exit(3)
"""


def _build_fake_repo(
    tmp: str,
    *,
    skill: str = "1.1.0",
    plugin: str = "1.1.0",
    market: str = "1.1.0",
    with_changelog: bool = True,
    generator_stub: str | None = GENERATOR_STUB_OK,
) -> str:
    """Plant a minimal repo layout under *tmp* and return the repo root."""
    os.makedirs(os.path.join(tmp, ".git"))  # Minimum marker for find_repo_root.
    os.makedirs(os.path.join(tmp, "skill-system-foundry"))
    os.makedirs(os.path.join(tmp, ".claude-plugin"))
    os.makedirs(os.path.join(tmp, "scripts"))
    with open(
        os.path.join(tmp, "skill-system-foundry", "SKILL.md"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(SKILL_MD.format(version=skill))
    with open(
        os.path.join(tmp, ".claude-plugin", "plugin.json"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(PLUGIN_JSON.format(version=plugin))
    with open(
        os.path.join(tmp, ".claude-plugin", "marketplace.json"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(MARKETPLACE_JSON.format(version=market))
    if with_changelog:
        with open(
            os.path.join(tmp, "CHANGELOG.md"), "w", encoding="utf-8"
        ) as fh:
            fh.write("# Changelog\n\n## [1.1.0] - 2026-04-01\n\n- seed\n")
    if generator_stub is not None:
        stub_path = os.path.join(tmp, "scripts", "generate_changelog.py")
        with open(stub_path, "w", encoding="utf-8") as fh:
            fh.write(generator_stub)
    return tmp


def _invoke(
    argv: list[str], *, cwd: str, generator_stub_path: str | None = None
) -> tuple[int, str, str]:
    """Invoke ``main(argv)`` with ``os.getcwd`` patched and optional generator override."""
    patches = [mock.patch("os.getcwd", return_value=cwd)]
    if generator_stub_path is not None:
        patches.append(
            mock.patch.object(
                bump_version, "GENERATOR_SCRIPT", generator_stub_path
            )
        )
    out = _CapturedIO()
    with out.capture():
        with patches[0]:
            if len(patches) > 1:
                with patches[1]:
                    rc = bump_version.main(argv)
            else:
                rc = bump_version.main(argv)
    return rc, out.stdout, out.stderr


class _CapturedIO:
    """Capture stdout+stderr around a block of code."""

    def __init__(self) -> None:
        self.stdout = ""
        self.stderr = ""

    def capture(self) -> contextlib.AbstractContextManager[None]:
        out, err = io.StringIO(), io.StringIO()
        owner = self

        @contextlib.contextmanager
        def _ctx() -> Iterator[None]:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                yield
            owner.stdout = out.getvalue()
            owner.stderr = err.getvalue()

        return _ctx()


# ===================================================================
# Semver and CLI input validation
# ===================================================================


class InputValidationTests(unittest.TestCase):
    def test_rejects_v_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(["v1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_INVALID_INPUT)
            # The targeted v/+build check runs first so the operator
            # sees the specific mistake rather than the generic shape
            # error.
            self.assertIn("'v' prefix", err)

    def test_rejects_build_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(
                ["1.2.0+build"], cwd=repo, generator_stub_path=gen
            )
            self.assertEqual(rc, bump_version.EXIT_INVALID_INPUT)
            self.assertIn("'+build'", err)

    def test_rejects_unparseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, _ = _invoke(["garbage"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_INVALID_INPUT)


class RepoDetectionTests(unittest.TestCase):
    def test_outside_git_repo_exits_invalid_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc, _, err = _invoke(["1.2.0"], cwd=tmp)
            self.assertEqual(rc, bump_version.EXIT_INVALID_INPUT)
            self.assertIn("not inside a git repository", err)

    def test_worktree_style_git_file_is_accepted(self) -> None:
        """A ``.git`` file (as used by git worktrees) is treated as a repo root."""
        with tempfile.TemporaryDirectory() as tmp:
            # Build the normal layout but replace .git/ with a .git file.
            repo = _build_fake_repo(tmp)
            os.rmdir(os.path.join(repo, ".git"))
            with open(os.path.join(repo, ".git"), "w", encoding="utf-8") as fh:
                fh.write("gitdir: /tmp/fake\n")
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, out, _ = _invoke(
                ["1.2.0", "--dry-run"], cwd=repo, generator_stub_path=gen
            )
            self.assertEqual(rc, bump_version.EXIT_OK)
            self.assertIn("Planned bump: 1.1.0 → 1.2.0", out)


# ===================================================================
# Precondition / drift
# ===================================================================


class DriftPreconditionTests(unittest.TestCase):
    def test_rejects_when_files_already_disagree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp, skill="1.1.0", plugin="1.2.0")
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(["1.3.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_DRIFT)
            self.assertIn("version drift detected", err)

    def test_rejects_when_skill_md_version_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            # Corrupt SKILL.md frontmatter.
            with open(
                os.path.join(repo, "skill-system-foundry", "SKILL.md"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("no frontmatter here\n")
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(["1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_DRIFT)
            self.assertIn("could not read current version", err)


# ===================================================================
# Equal / downgrade guard
# ===================================================================


class EqualAndDowngradeTests(unittest.TestCase):
    def test_equal_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(["1.1.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_INVALID_INPUT)
            self.assertIn("equals the current version", err)

    def test_downgrade_rejected_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(["1.0.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_INVALID_INPUT)
            self.assertIn("lower than the current version", err)

    def test_downgrade_allowed_with_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, out, _ = _invoke(
                ["1.0.0", "--allow-downgrade", "--dry-run"],
                cwd=repo,
                generator_stub_path=gen,
            )
            self.assertEqual(rc, bump_version.EXIT_OK)
            self.assertIn("Planned bump: 1.1.0 → 1.0.0", out)


# ===================================================================
# Happy paths (dry-run and real write)
# ===================================================================


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, out, _ = _invoke(
                ["1.2.0", "--dry-run"], cwd=repo, generator_stub_path=gen
            )
            self.assertEqual(rc, bump_version.EXIT_OK)
            # Files are untouched.
            with open(
                os.path.join(repo, "skill-system-foundry", "SKILL.md"),
                encoding="utf-8",
            ) as fh:
                self.assertIn("version: 1.1.0", fh.read())
            with open(
                os.path.join(repo, ".claude-plugin", "plugin.json"),
                encoding="utf-8",
            ) as fh:
                self.assertIn('"version": "1.1.0"', fh.read())
            # Output names the planned edits.
            self.assertIn("would update skill-system-foundry/SKILL.md", out)
            self.assertIn("would update .claude-plugin/plugin.json", out)
            self.assertIn("would update .claude-plugin/marketplace.json", out)

    def test_dry_run_without_changelog_notes_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp, with_changelog=False)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, out, _ = _invoke(
                ["1.2.0", "--dry-run"], cwd=repo, generator_stub_path=gen
            )
            self.assertEqual(rc, bump_version.EXIT_OK)
            self.assertIn("CHANGELOG.md absent", out)


class HappyPathWriteTests(unittest.TestCase):
    def test_writes_all_three_files_and_invokes_generator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, out, _ = _invoke(
                ["1.2.0"], cwd=repo, generator_stub_path=gen
            )
            self.assertEqual(rc, bump_version.EXIT_OK)
            with open(
                os.path.join(repo, "skill-system-foundry", "SKILL.md"),
                encoding="utf-8",
            ) as fh:
                self.assertIn("version: 1.2.0", fh.read())
            with open(
                os.path.join(repo, ".claude-plugin", "plugin.json"),
                encoding="utf-8",
            ) as fh:
                plugin = json.load(fh)
            self.assertEqual(plugin["version"], "1.2.0")
            with open(
                os.path.join(repo, ".claude-plugin", "marketplace.json"),
                encoding="utf-8",
            ) as fh:
                market = json.load(fh)
            self.assertEqual(market["plugins"][0]["version"], "1.2.0")
            self.assertIn("Bumped version: 1.1.0 → 1.2.0", out)

    def test_skips_generator_when_changelog_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp, with_changelog=False)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, out, _ = _invoke(["1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_OK)
            self.assertNotIn("updated CHANGELOG.md", out)


# ===================================================================
# Changelog probe failure
# ===================================================================


class ChangelogProbeFailureTests(unittest.TestCase):
    def test_probe_failure_aborts_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp, generator_stub=GENERATOR_STUB_FAIL)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(
                ["1.2.0"], cwd=repo, generator_stub_path=gen
            )
            self.assertEqual(rc, bump_version.EXIT_CHANGELOG_FAILED)
            self.assertIn("changelog probe failed", err)
            # Files are untouched.
            with open(
                os.path.join(repo, "skill-system-foundry", "SKILL.md"),
                encoding="utf-8",
            ) as fh:
                self.assertIn("version: 1.1.0", fh.read())


# ===================================================================
# Plan failure (anchored regex matched != 1 time)
# ===================================================================


class PlanFailureTests(unittest.TestCase):
    def test_duplicate_version_line_fails_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            # Inject a second matching line inside plugin.json via a nested
            # object so the anchored regex matches twice.
            with open(
                os.path.join(repo, ".claude-plugin", "plugin.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(
                    '{\n'
                    '  "name": "demo",\n'
                    '  "version": "1.1.0",\n'
                    '  "sidecar": {\n'
                    '    "version": "1.1.0"\n'
                    '  }\n'
                    '}\n'
                )
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(
                ["1.2.0"], cwd=repo, generator_stub_path=gen
            )
            self.assertEqual(rc, bump_version.EXIT_PLAN_FAILED)
            self.assertIn("plan failed", err)


# ===================================================================
# Partial write (phase 2 failure introduces drift; caller must report)
# ===================================================================


class PartialWriteTests(unittest.TestCase):
    def test_phase2_failure_reports_swapped_and_remaining(self) -> None:
        """When ``os.replace`` fails partway, the operator sees which files drifted."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")

            real_replace = os.replace
            call_count = {"n": 0}

            def fail_on_second(src: str, dst: str) -> None:
                call_count["n"] += 1
                if call_count["n"] == 2:
                    raise OSError(13, "simulated phase-2 failure")
                real_replace(src, dst)

            with mock.patch.object(bump_version.os, "replace", side_effect=fail_on_second):
                rc, _, err = _invoke(
                    ["1.2.0"], cwd=repo, generator_stub_path=gen
                )
            self.assertEqual(rc, bump_version.EXIT_PARTIAL_WRITE)
            self.assertIn("partial write", err)
            self.assertIn("swapped to 1.2.0", err)
            self.assertIn("still at  1.1.0", err)

    def test_first_write_failure_is_not_partial(self) -> None:
        """A failure before any swap is a plain write failure — no drift."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")

            def fail_every_call(src: str, dst: str) -> None:
                raise OSError(13, "simulated phase-2 failure")

            with mock.patch.object(bump_version.os, "replace", side_effect=fail_every_call):
                rc, _, err = _invoke(
                    ["1.2.0"], cwd=repo, generator_stub_path=gen
                )
            self.assertEqual(rc, bump_version.EXIT_PLAN_FAILED)
            self.assertIn("write failed", err)
            self.assertNotIn("partial write", err)
            self.assertNotIn("drift is now present", err)


# ===================================================================
# Helper units (head_sha returns None outside git)
# ===================================================================


class MalformedManifestTests(unittest.TestCase):
    """Malformed manifests must surface as EXIT_DRIFT, not as tracebacks."""

    def test_invalid_plugin_json_returns_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            with open(
                os.path.join(repo, ".claude-plugin", "plugin.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("{not valid json")
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(["1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_DRIFT)
            self.assertIn("plugin.json", err)
            self.assertIn("cannot read manifest", err)

    def test_missing_marketplace_json_returns_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            os.remove(os.path.join(repo, ".claude-plugin", "marketplace.json"))
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(["1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_DRIFT)
            self.assertIn("marketplace.json", err)

    def test_missing_plugin_name_surfaces_as_precondition(self) -> None:
        """An empty/missing plugin name must surface as plugin.json error.

        Previously the marketplace read was silently skipped when
        ``plugin_name`` was falsy, which then surfaced as a misleading
        "could not read marketplace.json" finding.  The real precondition
        failure is the missing name in plugin.json.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            with open(
                os.path.join(repo, ".claude-plugin", "plugin.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write('{\n  "version": "1.1.0"\n}\n')
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(["1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_DRIFT)
            self.assertIn("plugin.json", err)
            self.assertIn(
                "missing, empty, or whitespace-only 'name'", err
            )

    def test_whitespace_only_plugin_name_is_rejected(self) -> None:
        """Whitespace-only ``name`` must be treated as missing."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            with open(
                os.path.join(repo, ".claude-plugin", "plugin.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write('{\n  "name": "   ",\n  "version": "1.1.0"\n}\n')
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, err = _invoke(["1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_DRIFT)
            self.assertIn(
                "missing, empty, or whitespace-only 'name'", err
            )


class ArgparseExitTests(unittest.TestCase):
    """``main()`` must return an int even when argparse exits."""

    def test_missing_required_arg_returns_invalid_input(self) -> None:
        rc, _, _ = _invoke([], cwd=os.getcwd())
        self.assertEqual(rc, bump_version.EXIT_INVALID_INPUT)

    def test_help_flag_returns_ok(self) -> None:
        rc, _, _ = _invoke(["--help"], cwd=os.getcwd())
        self.assertEqual(rc, bump_version.EXIT_OK)


class NewlineHandlingTests(unittest.TestCase):
    """``commit_writes`` pins LF newlines on disk for cross-platform reproducibility."""

    def test_writes_lf_newlines_regardless_of_platform_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, _ = _invoke(["1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_OK)
            # Open in binary so we see the on-disk bytes verbatim.
            for rel in (
                "skill-system-foundry/SKILL.md",
                ".claude-plugin/plugin.json",
                ".claude-plugin/marketplace.json",
            ):
                with self.subTest(file=rel):
                    with open(
                        os.path.join(repo, *rel.split("/")), "rb"
                    ) as fh:
                        raw = fh.read()
                    self.assertNotIn(
                        b"\r\n",
                        raw,
                        f"expected LF-only on disk for {rel}",
                    )


class TempFileSafetyTests(unittest.TestCase):
    """``commit_writes`` must not clobber pre-existing sibling files."""

    def test_pre_existing_dot_tmp_is_preserved(self) -> None:
        """A maintainer's adjacent ``.tmp`` artifact must survive a bump.

        Earlier versions of ``commit_writes`` staged through a
        deterministic ``<target>.tmp`` path, which would truncate any
        pre-existing file at that name and then remove it during
        cleanup.  Use ``tempfile.mkstemp`` for unique sibling names.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            # Plant a file at the deterministic name an earlier version
            # would have used; it must still exist with its original
            # content after the bump.
            sentinel = os.path.join(
                repo, ".claude-plugin", "plugin.json.tmp"
            )
            with open(sentinel, "w", encoding="utf-8") as fh:
                fh.write("MAINTAINER ARTIFACT — DO NOT TOUCH")
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, _ = _invoke(["1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_OK)
            self.assertTrue(os.path.exists(sentinel))
            with open(sentinel, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "MAINTAINER ARTIFACT — DO NOT TOUCH")


class PermissionPreservationTests(unittest.TestCase):
    """``commit_writes`` must restore the target's mode on the staged file.

    ``tempfile.mkstemp`` creates files with mode ``0o600``; without an
    explicit ``chmod`` step a successful bump would silently downgrade
    the manifests to owner-only.  Skipped on Windows where POSIX mode
    bits do not survive the round trip.
    """

    @unittest.skipIf(os.name == "nt", "POSIX mode bits not meaningful on Windows")
    def test_target_mode_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _build_fake_repo(tmp)
            plugin_path = os.path.join(repo, ".claude-plugin", "plugin.json")
            os.chmod(plugin_path, 0o644)
            before_mode = os.stat(plugin_path).st_mode & 0o777
            gen = os.path.join(repo, "scripts", "generate_changelog.py")
            rc, _, _ = _invoke(["1.2.0"], cwd=repo, generator_stub_path=gen)
            self.assertEqual(rc, bump_version.EXIT_OK)
            after_mode = os.stat(plugin_path).st_mode & 0o777
            self.assertEqual(after_mode, before_mode)


class HeadShaTests(unittest.TestCase):
    def test_returns_none_outside_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(bump_version.head_sha(tmp))

    def test_returns_none_when_git_missing(self) -> None:
        with mock.patch(
            "subprocess.run", side_effect=FileNotFoundError()
        ):
            self.assertIsNone(bump_version.head_sha("/anywhere"))


if __name__ == "__main__":
    unittest.main()
