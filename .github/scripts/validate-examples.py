"""Validate every reference skill under ``examples/skills/``.

Walks the immediate children of ``examples/skills/`` and runs
``skill-system-foundry/scripts/validate_skill.py --json`` against each.
Aggregates per-skill verdicts and exits non-zero when any example reports
any FAIL, WARN, or INFO finding — examples must validate fully clean.

Roles under ``examples/roles/`` are intentionally skipped — the foundry
validator does not currently target role files. A dedicated role
validator is tracked as a follow-up issue.

Designed for CI: stdlib-only, runs identically on Linux and Windows, no
third-party dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


REPO_RELATIVE_EXAMPLES_ROOT = os.path.join("examples", "skills")
REPO_RELATIVE_VALIDATOR = os.path.join(
    "skill-system-foundry", "scripts", "validate_skill.py",
)
SEPARATOR_WIDTH = 60


def discover_skill_dirs(skills_root: str) -> list[str]:
    """Return absolute paths of immediate subdirectories that look like skills.

    A directory qualifies when it contains a ``SKILL.md`` file at its top
    level. Other entries (loose files, hidden directories, directories
    without ``SKILL.md``) are silently skipped — they may exist for
    documentation or future expansion.
    """
    if not os.path.isdir(skills_root):
        return []
    found: list[str] = []
    for name in sorted(os.listdir(skills_root)):
        if name.startswith("."):
            continue
        candidate = os.path.join(skills_root, name)
        if not os.path.isdir(candidate):
            continue
        if os.path.isfile(os.path.join(candidate, "SKILL.md")):
            found.append(os.path.abspath(candidate))
    return found


def validate_one(
    skill_path: str, validator_path: str,
) -> tuple[bool, dict | None, str, str]:
    """Run ``validate_skill.py --json`` against *skill_path*.

    Returns a tuple of ``(success, parsed_json, raw_stdout, raw_stderr)``.
    *success* is True only when the subprocess returned exit 0, the
    parsed payload reports ``success: true``, and the summary reports
    zero failures, warnings, and info findings — examples must validate
    fully clean. *parsed_json* is None when stdout could not be parsed
    as JSON.
    """
    completed = subprocess.run(
        [sys.executable, validator_path, skill_path, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    raw = completed.stdout
    stderr = completed.stderr
    parsed: dict | None
    try:
        parsed = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        parsed = None
    if parsed is None:
        return False, None, raw, stderr
    summary = parsed.get("summary") or {}
    success = (
        bool(parsed.get("success"))
        and completed.returncode == 0
        and summary.get("failures", 0) == 0
        and summary.get("warnings", 0) == 0
        and summary.get("info", 0) == 0
    )
    return success, parsed, raw, stderr


def format_verdict(
    skill_path: str, parsed: dict | None, success: bool,
) -> str:
    """Render a single one-line verdict for *skill_path*.

    *success* is the authoritative pass/fail flag computed by
    :func:`validate_one`. The mark is derived from it so the line never
    contradicts the aggregate exit code. When the validator early-exits
    with a top-level ``error`` field (no ``summary``), the verdict
    surfaces the message instead of misleading zero counts.
    """
    label = os.path.basename(skill_path.rstrip(os.sep))
    if parsed is None:
        return f"  ✗ {label}: validator emitted no valid JSON output"
    top_level_error = parsed.get("error")
    if top_level_error:
        return f"  ✗ {label}: validator error: {top_level_error}"
    summary = parsed.get("summary") or {}
    failures = summary.get("failures", 0)
    warnings = summary.get("warnings", 0)
    info = summary.get("info", 0)
    mark = "✓" if success else "✗"
    return (
        f"  {mark} {label}: "
        f"{failures} fail / {warnings} warn / {info} info"
    )


def run_validation(
    skills_root: str, validator_path: str,
) -> tuple[list[tuple[str, bool, dict | None, str, str]], bool]:
    """Validate every skill under *skills_root*.

    Returns ``(results, all_success)`` where *results* is a list of
    ``(skill_path, success, parsed, raw_stdout, raw_stderr)`` tuples in
    walk order.
    """
    results: list[tuple[str, bool, dict | None, str, str]] = []
    all_success = True
    for skill_path in discover_skill_dirs(skills_root):
        success, parsed, raw, stderr = validate_one(
            skill_path, validator_path,
        )
        results.append((skill_path, success, parsed, raw, stderr))
        if not success:
            all_success = False
    return results, all_success


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate every reference skill under examples/skills/."
        ),
    )
    parser.add_argument(
        "--skills-root",
        default=REPO_RELATIVE_EXAMPLES_ROOT,
        help=(
            "Path to the directory holding example skills. "
            "Defaults to %(default)s relative to the working directory."
        ),
    )
    parser.add_argument(
        "--validator",
        default=REPO_RELATIVE_VALIDATOR,
        help=(
            "Path to the validate_skill.py entry point. "
            "Defaults to %(default)s relative to the working directory."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the exit code."""
    # On Windows the default console encoding (cp1252) cannot represent
    # the ✓/✗ Unicode marks the verdict lines use. Reconfigure
    # stdout/stderr to replace unencodable characters rather than
    # raising UnicodeEncodeError on local runs outside CI.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")

    parser = _build_parser()
    args = parser.parse_args(argv)
    skills_root = os.path.abspath(args.skills_root)
    validator_path = os.path.abspath(args.validator)

    if not os.path.isfile(validator_path):
        print(
            f"Error: validator not found at {validator_path}",
            file=sys.stderr,
        )
        return 1

    results, all_success = run_validation(skills_root, validator_path)
    if not results:
        print(
            f"Error: no example skills found under {skills_root}",
            file=sys.stderr,
        )
        return 1

    print(f"Validating {len(results)} example skill(s) under {skills_root}")
    print("-" * SEPARATOR_WIDTH)

    for skill_path, success, parsed, raw, stderr in results:
        print(format_verdict(skill_path, parsed, success))
        if not success:
            errors = (parsed or {}).get("errors", {}) or {}
            for error in errors.get("failures", []):
                print(f"      FAIL: {error}")
            for warning in errors.get("warnings", []):
                print(f"      WARN: {warning}")
            for info in errors.get("info", []):
                print(f"      INFO: {info}")
            top_level_error = (parsed or {}).get("error")
            if top_level_error:
                print(f"      FAIL: {top_level_error}")
            if parsed is None and raw.strip():
                print(f"      raw stdout: {raw.strip()}")
            if stderr.strip():
                print(f"      raw stderr: {stderr.strip()}")

    print("-" * SEPARATOR_WIDTH)
    if all_success:
        print(f"✓ All {len(results)} example(s) validated cleanly")
        return 0
    failed = sum(1 for _, success, _, _, _ in results if not success)
    print(f"✗ {failed} of {len(results)} example(s) failed validation")
    return 1


if __name__ == "__main__":
    sys.exit(main())
