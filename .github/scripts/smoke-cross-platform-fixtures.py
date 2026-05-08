#!/usr/bin/env python3
"""Exercise cross-platform failure fixtures in the smoke CI job.

The bundle-extract-smoke workflow proves the happy path by
scaffolding, bundling, extracting, and validating a synthetic skill on
Ubuntu and Windows.  This companion script adds two small negative
fixtures that target the cross-platform regressions called out in the
PR summary without making the happy-path bundle step fail:

* a wrong-cased markdown reference, which must fail validation on
  every host (including case-insensitive filesystems);
* a long archive arcname, checked with a deliberately tiny threshold
  so the test exercises the MAX_PATH arithmetic without creating a
  path that is itself too long for Windows to materialize.
"""

import os
import shutil
import sys


REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
SCRIPTS_DIR = os.path.join(REPO_ROOT, "skill-system-foundry", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from lib.bundling import check_long_paths
from lib.constants import LEVEL_FAIL
from validate_skill import validate_skill


def write_text(path: str, content: str) -> None:
    """Write UTF-8 text with LF newlines, creating parents first."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def skill_frontmatter(name: str) -> str:
    """Return minimal valid SKILL.md frontmatter for *name*."""
    return (
        "---\n"
        f"name: {name}\n"
        "description: triggers when cross-platform smoke validation runs\n"
        "---\n"
        "\n"
    )


def assert_case_exact_failure(work_root: str) -> None:
    """Verify wrong-cased references fail regardless of host casing."""
    skill_dir = os.path.join(work_root, "skills", "case-demo")
    write_text(
        os.path.join(skill_dir, "SKILL.md"),
        skill_frontmatter("case-demo")
        + "Use [the guide](References/guide.md).\n",
    )
    write_text(
        os.path.join(skill_dir, "references", "guide.md"),
        "# Guide\n",
    )

    errors, _passes = validate_skill(skill_dir)
    if not any(
        finding.startswith(LEVEL_FAIL)
        and "differs from the on-disk casing" in finding
        for finding in errors
    ):
        raise AssertionError(
            "wrong-cased reference did not fail validation; findings were: "
            + repr(errors)
        )


def assert_long_path_failure(work_root: str) -> None:
    """Verify long archive arcnames trip the MAX_PATH budget helper."""
    skill_dir = os.path.join(work_root, "skills", "long-demo")
    write_text(
        os.path.join(skill_dir, "SKILL.md"),
        skill_frontmatter("long-demo"),
    )
    write_text(
        os.path.join(
            skill_dir,
            "references",
            "nested",
            "path",
            "with-a-name-that-is-long-enough-for-the-smoke-budget.md",
        ),
        "# Long path\n",
    )

    errors, _passes = check_long_paths(
        skill_dir,
        threshold=60,
        user_prefix_budget=5,
    )
    if not any(
        finding.startswith(LEVEL_FAIL)
        and "exceeds the long-path budget" in finding
        for finding in errors
    ):
        raise AssertionError(
            "long-path fixture did not fail the archive budget; "
            f"findings were: {errors!r}"
        )


def main() -> int:
    """Run negative smoke fixtures and return a process exit code."""
    work_root = os.path.abspath("smoke-cross-platform-fixtures")
    shutil.rmtree(work_root, ignore_errors=True)
    os.makedirs(work_root, exist_ok=True)
    try:
        assert_case_exact_failure(work_root)
        assert_long_path_failure(work_root)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
    print("Cross-platform negative smoke fixtures passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
