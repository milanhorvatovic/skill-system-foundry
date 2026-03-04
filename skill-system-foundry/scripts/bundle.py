#!/usr/bin/env python3
"""
Bundle a skill into a self-contained zip archive for distribution.

Resolves external references (roles, shared docs), copies them into
the bundle, rewrites markdown paths, and validates the result.

Usage:
    python scripts/bundle.py <skill-path>
    python scripts/bundle.py <skill-path> --system-root .agents
    python scripts/bundle.py <skill-path> --output /tmp/my-skill.zip
    python scripts/bundle.py <skill-path> --system-root .agents --output dist/
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
    FILE_SKILL_MD,
    BUNDLE_EXCLUDE_PATTERNS,
    SEPARATOR_WIDTH,
    LEVEL_FAIL,
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
    # Unicode symbols like ✓, ✗, ⚠.  Reconfigure stdout to replace
    # unencodable characters rather than crashing.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    if len(sys.argv) == 1:
        if __doc__:
            print(__doc__.strip())
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Bundle a skill into a self-contained zip archive.",
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
            "Output path for the zip file. Can be a directory or a file "
            "path. Defaults to <skill-name>.zip in the current directory."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print traceback details when unexpected errors occur.",
    )

    args = parser.parse_args()
    skill_path = os.path.abspath(args.skill_path)

    # Validate input
    if not os.path.isdir(skill_path):
        print(f"Error: '{args.skill_path}' is not a directory.")
        sys.exit(1)

    skill_md = os.path.join(skill_path, FILE_SKILL_MD)
    if not os.path.exists(skill_md):
        print(
            f"Error: No {FILE_SKILL_MD} found in '{args.skill_path}'. "
            f"Only registered skills (not capabilities) can be bundled."
        )
        sys.exit(1)

    skill_name = os.path.basename(skill_path)

    # Resolve system root
    system_root = None
    if args.system_root:
        system_root = os.path.abspath(args.system_root)
        if not os.path.isdir(system_root):
            print(f"Error: System root '{args.system_root}' is not a directory.")
            sys.exit(1)
        if not is_within_directory(skill_path, system_root):
            print(
                f"Error: Skill directory '{skill_path}' is not within "
                f"the system root '{system_root}'. Provide a "
                f"--system-root that is an ancestor of the skill "
                f"directory, or omit it to infer automatically."
            )
            sys.exit(1)
    else:
        system_root = infer_system_root(skill_path)
        if system_root:
            print(f"Inferred system root: {system_root}")
        else:
            print(
                "Warning: Could not infer system root. Bundling will fail "
                "if external references are detected, because safety "
                "boundaries cannot be enforced. Use --system-root to "
                "specify it explicitly."
            )

    # Resolve output path
    if args.output:
        output_path = os.path.abspath(args.output)
        if os.path.isdir(output_path):
            output_path = os.path.join(output_path, f"{skill_name}.zip")
    else:
        output_path = os.path.join(os.getcwd(), f"{skill_name}.zip")

    # Ensure the output parent directory exists
    output_parent = os.path.dirname(output_path)
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)

    print(f"Bundling: {skill_path}")
    print(f"Output:   {output_path}")
    print("=" * SEPARATOR_WIDTH)

    # ---- Phase 1: Pre-validation ----
    print("\nPhase 1: Pre-validation")
    print("-" * SEPARATOR_WIDTH)
    print("  Running pre-validation checks...")
    errors, warnings, scan_result = prevalidate(skill_path, system_root)

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
        print("\n  Warnings:")
        for warn in warnings:
            print(f"    {warn}")

    if scan_result is None:
        print(
            "Error: pre-validation did not produce a scan result. "
            "Re-run with --system-root and inspect validation output."
        )
        sys.exit(1)

    ext_count = len(scan_result["external_files"])
    print(f"  Pre-validation passed. {ext_count} external file(s) to include.")

    # ---- Phase 2: Bundle creation ----
    print(f"\nPhase 2: Bundle creation")
    print("-" * SEPARATOR_WIDTH)
    print("  Assembling bundle...")
    bundle_base = tempfile.mkdtemp(prefix="skill_bundle_")
    phase_name = "bundle creation"
    try:
        bundle_dir, file_mapping, stats = create_bundle(
            skill_path, system_root, scan_result, BUNDLE_EXCLUDE_PATTERNS,
            bundle_base=bundle_base,
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


if __name__ == "__main__":
    main()
