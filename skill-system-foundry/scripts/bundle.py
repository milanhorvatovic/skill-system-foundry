#!/usr/bin/env python3
"""
Bundle a skill into a self-contained zip bundle for distribution.

Resolves external references (roles, shared docs), copies them into
the bundle, rewrites markdown paths, and validates the result.

Usage:
    python scripts/bundle.py <skill-path>
    python scripts/bundle.py <skill-path> --system-root .agents
    python scripts/bundle.py <skill-path> --output /tmp/my-skill.zip
    python scripts/bundle.py <skill-path> --system-root .agents --output dist/
    python scripts/bundle.py <skill-path> --system-root .agents --inline-orchestrated-skills
    python scripts/bundle.py <skill-path> --target claude   # default
    python scripts/bundle.py <skill-path> --target gemini
    python scripts/bundle.py <skill-path> --target generic
"""

import argparse
import os
import shutil
import sys
import tempfile
import traceback

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.bundling import (
    prevalidate,
    create_bundle,
    postvalidate,
    create_zip,
)
from lib.constants import (
    BUNDLE_DESCRIPTION_MAX_LENGTH,
    DIR_SKILLS,
    FILE_MANIFEST,
    FILE_SKILL_MD,
    BUNDLE_EXCLUDE_PATTERNS,
    SEPARATOR_WIDTH,
    LEVEL_FAIL,
    LEVEL_WARN,
)
from lib.references import (
    infer_system_root,
    is_within_directory,
)
from lib.reporting import categorize_errors, print_error_line, print_summary


# ===================================================================
# CLI
# ===================================================================

def _format_size(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1048576:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes / 1048576:.1f} MB"


def _print_failure_block(
    title: str,
    errors: list[str],
    *,
    warnings: list[str] | None = None,
    guidance: str | None = None,
) -> None:
    """Print a standardized bundling failure section."""
    print(f"\n{'=' * SEPARATOR_WIDTH}")
    print(f"Bundling FAILED — {title}:\n")
    for err in errors:
        print_error_line(err)
    if warnings:
        print()
        for warn in warnings:
            print_error_line(warn)

    all_issues = list(errors)
    if warnings:
        all_issues.extend(warnings)
    fails, warns, infos = categorize_errors(all_issues)
    print("-" * SEPARATOR_WIDTH)
    print_summary(fails, warns, infos)
    if guidance:
        print(f"\n{guidance}")


def main() -> None:
    # On Windows the default console encoding (cp1252) cannot represent
    # Unicode symbols like ✓, ✗, ⚠.  Reconfigure stdout/stderr to replace
    # unencodable characters rather than crashing.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")

    if len(sys.argv) == 1:
        if __doc__:
            print(__doc__.strip())
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Bundle a skill into a self-contained zip bundle.",
        epilog=(
            "Examples:\n"
            "  python scripts/bundle.py skills/my-skill\n"
            "  python scripts/bundle.py skills/my-skill "
            "--system-root .agents\n"
            "  python scripts/bundle.py skills/my-skill "
            "--output dist/my-skill.zip\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "skill_path",
        help="Path to the skill directory to bundle.",
    )
    parser.add_argument(
        "--system-root",
        default=None,
        help=(
            "Path to the skill system root (contains skills/, roles/). "
            "If omitted, inferred by walking up from the skill path."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output file path for the zip bundle, or an existing "
            "directory (or path ending with a separator) in which to "
            "place <skill-name>.zip. A non-existent path without a "
            "trailing separator is treated as a file path. "
            "Defaults to <skill-name>.zip in the current directory."
        ),
    )
    parser.add_argument(
        "--inline-orchestrated-skills",
        action="store_true",
        help=(
            "When bundling a Path 1 coordination skill, inline "
            "referenced domain skills as capabilities instead of "
            "rejecting cross-skill references. The result is a "
            "self-contained Path 2 router bundle."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print traceback details when unexpected errors occur.",
    )
    parser.add_argument(
        "--target",
        choices=["claude", "gemini", "generic"],
        default=None,
        help=(
            "Validation target that controls description length enforcement. "
            f"Choices: claude (default, {BUNDLE_DESCRIPTION_MAX_LENGTH}-char "
            "limit enforced as error), "
            "gemini or generic (limit enforced as warning only). "
            "Falls back to SKILL_BUNDLE_TARGET env var if set."
        ),
    )

    args = parser.parse_args()

    # Resolve target: explicit --target flag > SKILL_BUNDLE_TARGET env var > "claude"
    if args.target is not None:
        bundle_target: str = args.target
    else:
        _env_target = os.environ.get("SKILL_BUNDLE_TARGET", "").strip().lower()
        if _env_target:
            if _env_target not in {"claude", "gemini", "generic"}:
                print_error_line(
                    f"{LEVEL_FAIL}: Invalid SKILL_BUNDLE_TARGET "
                    f"'{os.environ['SKILL_BUNDLE_TARGET']}'. "
                    "Use one of: claude, gemini, generic."
                )
                sys.exit(1)
            bundle_target = _env_target
        else:
            bundle_target = "claude"
    skill_path = os.path.abspath(args.skill_path)

    # Validate input
    if not os.path.isdir(skill_path):
        print_error_line(f"{LEVEL_FAIL}: '{args.skill_path}' is not a directory.")
        sys.exit(1)

    skill_md = os.path.join(skill_path, FILE_SKILL_MD)
    if not os.path.exists(skill_md):
        print_error_line(
            f"{LEVEL_FAIL}: No {FILE_SKILL_MD} found in '{args.skill_path}'. "
            f"Only registered skills (not capabilities) can be bundled."
        )
        sys.exit(1)

    skill_name = os.path.basename(skill_path)

    # Resolve system root
    system_root = None
    if args.system_root:
        system_root = os.path.abspath(args.system_root)
        if not os.path.isdir(system_root):
            print_error_line(
                f"{LEVEL_FAIL}: System root '{args.system_root}' is not a directory."
            )
            sys.exit(1)
        if not is_within_directory(skill_path, system_root):
            print_error_line(
                f"{LEVEL_FAIL}: Skill directory '{skill_path}' is not within "
                f"the system root '{system_root}'. Provide a "
                f"--system-root that is an ancestor of the skill "
                f"directory, or omit it to infer automatically."
            )
            sys.exit(1)

        # Auto-correct if the user passed the skills/ directory itself
        # rather than the system root that contains it.
        skills_dir = os.path.join(system_root, DIR_SKILLS)
        if (
            os.path.basename(system_root) == DIR_SKILLS
            and is_within_directory(skill_path, system_root)
            and not os.path.isdir(skills_dir)
        ):
            corrected = os.path.dirname(system_root)
            print(
                f"Note: '{args.system_root}' appears to be a "
                f"'{DIR_SKILLS}/' directory, not the system root. "
                f"Using parent '{corrected}' as system root."
            )
            system_root = corrected

        # Validate the root has expected structure markers.
        has_manifest = os.path.exists(
            os.path.join(system_root, FILE_MANIFEST)
        )
        has_skills_dir = os.path.isdir(
            os.path.join(system_root, DIR_SKILLS)
        )
        if not has_manifest and not has_skills_dir:
            print_error_line(
                f"{LEVEL_FAIL}: '{system_root}' does not look like a skill "
                f"system root (no '{FILE_MANIFEST}' and no "
                f"'{DIR_SKILLS}/' directory). Expected layout:\n"
                f"  {system_root}/\n"
                f"    {FILE_MANIFEST}\n"
                f"    {DIR_SKILLS}/\n"
                f"      <your-skill>/\n"
                f"Provide a valid --system-root that contains your skill."
            )
            sys.exit(1)
    else:
        system_root = infer_system_root(skill_path)
        if system_root:
            print(f"Inferred system root: {system_root}")
        else:
            print_error_line(
                f"{LEVEL_WARN}: Could not infer system root. Bundling will fail "
                f"if external references are detected, because safety "
                f"boundaries cannot be enforced. Use --system-root to "
                f"specify it explicitly."
            )

    # Resolve output path
    if args.output:
        raw_output = args.output
        output_root = os.path.abspath(raw_output)

        # Treat --output as a directory when:
        #   - it already exists as a directory, or
        #   - the raw argument ends with a path separator.
        # Otherwise treat it as a file path (any extension is valid,
        # e.g. .zip, .skill).
        has_trailing_sep = raw_output.endswith(os.sep) or (
            os.altsep is not None and raw_output.endswith(os.altsep)
        )
        is_directory_intent = os.path.isdir(output_root) or has_trailing_sep

        if is_directory_intent:
            os.makedirs(output_root, exist_ok=True)
            output_path = os.path.join(output_root, f"{skill_name}.zip")
        else:
            output_path = output_root
    else:
        output_path = os.path.join(os.getcwd(), f"{skill_name}.zip")

    # Ensure the output parent directory exists
    output_parent = os.path.dirname(output_path)
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)

    print(f"Bundling: {skill_path}")
    print(f"Output:   {output_path}")
    print("=" * SEPARATOR_WIDTH)

    inline_skills = args.inline_orchestrated_skills

    # ---- Phase 1: Pre-validation ----
    print("\nPhase 1: Pre-validation")
    print("-" * SEPARATOR_WIDTH)
    print("  Running pre-validation checks...")
    errors, warnings, scan_result = prevalidate(
        skill_path, system_root,
        inline_orchestrated_skills=inline_skills,
        bundle_target=bundle_target,
    )

    if errors:
        _print_failure_block(
            "pre-validation errors",
            errors,
            warnings=warnings,
            guidance=(
                "Fix the issues above and re-run. This skill system can "
                "help you resolve structural and reference problems."
            ),
        )
        sys.exit(1)

    if warnings:
        print("\n  Notices:")
        for warn in warnings:
            print(f"    {warn}")

    if scan_result is None:
        print(
            f"{LEVEL_FAIL}: Internal error: pre-validation completed without "
            "producing a scan result. Check prevalidate() implementation "
            "and call site."
        )
        sys.exit(1)

    ext_count = len(scan_result["external_files"])
    print(f"  Pre-validation passed. {ext_count} external file(s) to include.")

    # ---- Phase 2: Bundle creation ----
    print(f"\nPhase 2: Bundle creation")
    print("-" * SEPARATOR_WIDTH)
    print("  Assembling bundle...")
    bundle_base: str | None = None
    phase_name = "bundle creation"
    try:
        bundle_base = tempfile.mkdtemp(prefix="skill_bundle_")
        bundle_dir, file_mapping, stats = create_bundle(
            skill_path, system_root, scan_result, BUNDLE_EXCLUDE_PATTERNS,
            bundle_base=bundle_base,
            inline_orchestrated_skills=inline_skills,
        )
        print(
            f"  Assembled {stats['file_count']} files"
            f" ({stats['external_count']} external)."
        )
        if stats["rewrite_count"] > 0:
            print(
                f"  Rewrote references in"
                f" {stats['rewrite_count']} file(s)."
            )

        # ---- Phase 3: Post-validation ----
        phase_name = "post-validation"
        print(f"\nPhase 3: Post-validation")
        print("-" * SEPARATOR_WIDTH)
        post_errors = postvalidate(bundle_dir)

        if post_errors:
            _print_failure_block("post-validation errors", post_errors)
            sys.exit(1)

        print("  Post-validation passed.")

        # ---- Create archive ----
        phase_name = "archive creation"
        print(f"\nCreating archive...")
        create_zip(bundle_dir, output_path)

    except ValueError as exc:
        _print_failure_block(
            f"{phase_name} error",
            [f"{LEVEL_FAIL}: {exc}"],
        )
        sys.exit(1)

    except Exception as exc:
        failure = (
            f"{LEVEL_FAIL}: Unexpected error during {phase_name}: "
            f"{exc.__class__.__name__}: {exc}. "
            f"Check file permissions, symlinks, and output path settings."
        )
        _print_failure_block("unexpected error", [failure])
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)

    finally:
        # Clean up temp directory — always, even on unexpected errors.
        if bundle_base:
            shutil.rmtree(bundle_base, ignore_errors=True)

    # ---- Summary ----
    zip_size = os.path.getsize(output_path)
    print(f"\n{'=' * SEPARATOR_WIDTH}")
    print(f"\u2713 Bundle created: {output_path}")
    print(f"  Skill:          {stats['skill_name']}")
    print(f"  Files:          {stats['file_count']}")
    print(f"  Uncompressed:   {_format_size(stats['total_size'])}")
    print(f"  Archive size:   {_format_size(zip_size)}")
    if stats["external_count"] > 0:
        print(f"  External files: {stats['external_count']} (inlined)")
    if stats["inlined_skill_count"] > 0:
        print(f"  Inlined skills: {stats['inlined_skill_count']} (as capabilities)")


if __name__ == "__main__":
    main()
