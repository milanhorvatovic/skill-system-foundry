"""Validate every reference skill under ``examples/skills/``.

Walks the immediate children of ``examples/skills/`` and runs
``skill-system-foundry/scripts/validate_skill.py --json`` against each
skill root. For router examples, every ``capabilities/<name>/`` subdir
is also validated with ``--capability --json`` so a broken capability
(frontmatter parse error, body line cap, etc.) cannot slip past CI when
the parent skill still passes. Aggregates verdicts and exits non-zero
when any example reports any FAIL, WARN, or INFO finding — examples
must validate fully clean.

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
    level. Hidden entries and loose files are silently skipped. Non-hidden
    directories without ``SKILL.md`` are *not* treated as skills here —
    use :func:`find_malformed_skill_dirs` to surface them as failures.
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


def discover_capability_dirs(skill_dir: str) -> list[str]:
    """Return absolute paths of capability dirs nested under *skill_dir*.

    A capability qualifies when ``<skill_dir>/capabilities/<name>/`` is a
    directory containing a ``capability.md`` file. Skills without a
    ``capabilities/`` subtree (standalone pattern) yield an empty list.
    Other entries (loose files, hidden directories, non-conforming
    subdirectories) are silently skipped.
    """
    capabilities_root = os.path.join(skill_dir, "capabilities")
    if not os.path.isdir(capabilities_root):
        return []
    found: list[str] = []
    for name in sorted(os.listdir(capabilities_root)):
        if name.startswith("."):
            continue
        candidate = os.path.join(capabilities_root, name)
        if not os.path.isdir(candidate):
            continue
        if os.path.isfile(os.path.join(candidate, "capability.md")):
            found.append(os.path.abspath(candidate))
    return found


def find_malformed_capability_dirs(skill_dir: str) -> list[str]:
    """Return non-hidden ``capabilities/<name>/`` dirs missing ``capability.md``.

    Mirrors :func:`find_malformed_skill_dirs` one level deeper. Each
    non-hidden child of a skill's ``capabilities/`` subtree is expected
    to be a capability root containing ``capability.md``. Silently
    skipping such directories would let a broken or newly added
    capability slip past CI as long as the parent skill still validates,
    so callers should fail fast with a clear diagnostic instead.
    """
    capabilities_root = os.path.join(skill_dir, "capabilities")
    if not os.path.isdir(capabilities_root):
        return []
    malformed: list[str] = []
    for name in sorted(os.listdir(capabilities_root)):
        if name.startswith("."):
            continue
        candidate = os.path.join(capabilities_root, name)
        if not os.path.isdir(candidate):
            continue
        if not os.path.isfile(os.path.join(candidate, "capability.md")):
            malformed.append(os.path.abspath(candidate))
    return malformed


def find_malformed_skill_dirs(skills_root: str) -> list[str]:
    """Return absolute paths of non-hidden child directories without ``SKILL.md``.

    Each immediate non-hidden child directory under *skills_root* is
    expected to be a skill root (matching a deployed-style ``skills/``
    tree). Missing ``SKILL.md`` indicates an accidental rename, deletion,
    or scaffolding mistake — silently skipping such directories would let
    a broken example slip past CI as long as another example remains, so
    callers should fail with a clear diagnostic instead.
    """
    if not os.path.isdir(skills_root):
        return []
    malformed: list[str] = []
    for name in sorted(os.listdir(skills_root)):
        if name.startswith("."):
            continue
        candidate = os.path.join(skills_root, name)
        if not os.path.isdir(candidate):
            continue
        if not os.path.isfile(os.path.join(candidate, "SKILL.md")):
            malformed.append(os.path.abspath(candidate))
    return malformed


def validate_one(
    skill_path: str,
    validator_path: str,
    *,
    capability: bool = False,
) -> tuple[bool, dict | None, str, str]:
    """Run ``validate_skill.py --json`` against *skill_path*.

    When *capability* is True, the ``--capability`` flag is added so the
    validator looks for ``capability.md`` instead of ``SKILL.md``.

    Returns a tuple of ``(success, parsed_json, raw_stdout, raw_stderr)``.
    *success* is True only when the subprocess returned exit 0, the
    parsed payload reports ``success: true``, and the summary reports
    zero failures, warnings, and info findings — examples must validate
    fully clean. *parsed_json* is None when stdout could not be parsed
    as JSON.
    """
    cmd = [sys.executable, validator_path, skill_path, "--json"]
    if capability:
        cmd.append("--capability")
    completed = subprocess.run(
        cmd,
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
    target_path: str,
    parsed: dict | None,
    success: bool,
    *,
    kind: str = "skill",
) -> str:
    """Render a single one-line verdict for *target_path*.

    *kind* is ``"skill"`` for skill-root verdicts and ``"capability"`` for
    capability verdicts; capability lines are indented one level deeper
    than the parent skill so the relationship reads at a glance.

    *success* is the authoritative pass/fail flag computed by
    :func:`validate_one`. The mark is derived from it so the line never
    contradicts the aggregate exit code. When the validator early-exits
    with a top-level ``error`` field (no ``summary``), the verdict
    surfaces the message instead of misleading zero counts.
    """
    indent = "    └─ " if kind == "capability" else "  "
    label = os.path.basename(target_path.rstrip(os.sep))
    if kind == "capability":
        label = f"capabilities/{label}"
    if parsed is None:
        return f"{indent}✗ {label}: validator emitted no valid JSON output"
    top_level_error = parsed.get("error")
    if top_level_error:
        return f"{indent}✗ {label}: validator error: {top_level_error}"
    summary = parsed.get("summary") or {}
    failures = summary.get("failures", 0)
    warnings = summary.get("warnings", 0)
    info = summary.get("info", 0)
    mark = "✓" if success else "✗"
    return (
        f"{indent}{mark} {label}: "
        f"{failures} fail / {warnings} warn / {info} info"
    )


def run_validation(
    skills_root: str, validator_path: str,
) -> tuple[list[tuple[str, str, bool, dict | None, str, str]], bool]:
    """Validate every skill (and its capabilities) under *skills_root*.

    Returns ``(results, all_success)`` where *results* is a list of
    ``(target_path, kind, success, parsed, raw_stdout, raw_stderr)``
    tuples in walk order. *kind* is ``"skill"`` or ``"capability"``;
    capability rows always immediately follow their parent skill row.
    """
    results: list[tuple[str, str, bool, dict | None, str, str]] = []
    all_success = True
    for skill_path in discover_skill_dirs(skills_root):
        success, parsed, raw, stderr = validate_one(
            skill_path, validator_path,
        )
        results.append((skill_path, "skill", success, parsed, raw, stderr))
        if not success:
            all_success = False
        for cap_path in discover_capability_dirs(skill_path):
            cap_success, cap_parsed, cap_raw, cap_stderr = validate_one(
                cap_path, validator_path, capability=True,
            )
            results.append(
                (cap_path, "capability", cap_success, cap_parsed, cap_raw, cap_stderr),
            )
            if not cap_success:
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

    malformed = find_malformed_skill_dirs(skills_root)
    if malformed:
        print(
            f"Error: malformed example skill directories under {skills_root}",
            file=sys.stderr,
        )
        for path in malformed:
            print(f"  - {path} is missing SKILL.md", file=sys.stderr)
        return 1

    malformed_caps: list[str] = []
    for skill_path in discover_skill_dirs(skills_root):
        malformed_caps.extend(find_malformed_capability_dirs(skill_path))
    if malformed_caps:
        print(
            f"Error: malformed example capability directories under {skills_root}",
            file=sys.stderr,
        )
        for path in malformed_caps:
            print(f"  - {path} is missing capability.md", file=sys.stderr)
        return 1

    results, all_success = run_validation(skills_root, validator_path)
    if not results:
        print(
            f"Error: no example skills found under {skills_root}",
            file=sys.stderr,
        )
        return 1

    skill_count = sum(1 for _, kind, _, _, _, _ in results if kind == "skill")
    cap_count = sum(
        1 for _, kind, _, _, _, _ in results if kind == "capability"
    )
    summary_root = (
        f"Validating {skill_count} example skill(s) "
        f"and {cap_count} capabilit{'y' if cap_count == 1 else 'ies'} "
        f"under {skills_root}"
    )
    print(summary_root)
    print("-" * SEPARATOR_WIDTH)

    for target_path, kind, success, parsed, raw, stderr in results:
        print(format_verdict(target_path, parsed, success, kind=kind))
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
        print(
            f"✓ All {len(results)} example target(s) validated cleanly "
            f"({skill_count} skill / {cap_count} capability)"
        )
        return 0
    failed = sum(1 for _, _, success, _, _, _ in results if not success)
    print(
        f"✗ {failed} of {len(results)} example target(s) failed validation"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
