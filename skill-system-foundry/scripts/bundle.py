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
    python scripts/bundle.py <skill-path> --json
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
    check_external_arcnames,
    check_long_paths,
    check_reserved_path_components,
)
from lib.constants import (
    BUNDLE_DEFAULT_TARGET,
    BUNDLE_DESCRIPTION_MAX_LENGTH,
    BUNDLE_VALID_TARGETS,
    DIR_SKILLS,
    FILE_MANIFEST,
    FILE_SKILL_MD,
    BUNDLE_EXCLUDE_PATTERNS,
    SEPARATOR_WIDTH,
    LEVEL_FAIL,
    LEVEL_WARN,
)
from lib.references import (
    compute_bundle_path,
    infer_system_root,
    is_within_directory,
)
from lib.reporting import (
    categorize_errors,
    categorize_errors_for_json,
    print_error_line,
    print_summary,
    to_json_output,
    to_posix,
)


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
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as machine-readable JSON.",
    )
    parser.add_argument(
        "--target",
        choices=BUNDLE_VALID_TARGETS,
        default=BUNDLE_DEFAULT_TARGET,
        help=(
            "Validation target that controls description length enforcement. "
            f"Choices: claude (default, {BUNDLE_DESCRIPTION_MAX_LENGTH}-char "
            "limit enforced as error), "
            "gemini or generic (limit enforced as warning only)."
        ),
    )

    # Override parser.error() so that:
    # - In --json mode, parse failures emit a JSON blob (not stderr text).
    # - In human mode, exit code is 1 (not argparse's default 2) to
    #   match the repo convention used by all other CLI tools.
    json_mode = "--json" in sys.argv

    def _cli_aware_error(message: str) -> None:
        if json_mode:
            print(to_json_output({
                "tool": "bundle",
                "success": False,
                "error": message,
            }))
            sys.exit(1)
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)

    parser.error = _cli_aware_error  # type: ignore[assignment]

    args = parser.parse_args()

    bundle_target: str = args.target
    json_output: bool = args.json_output
    skill_path = os.path.abspath(args.skill_path)

    # Collect warnings that occur before prevalidation (e.g. missing
    # system root) so they can be included in JSON output.
    early_warnings: list[str] = []

    def _json_fail(error: str) -> None:
        """Print a JSON failure blob and exit 1."""
        print(to_json_output({
            "tool": "bundle",
            "path": to_posix(skill_path),
            "success": False,
            "error": error,
        }))
        sys.exit(1)

    # Validate input
    if not os.path.isdir(skill_path):
        if json_output:
            _json_fail(f"'{args.skill_path}' is not a directory.")
        print_error_line(f"{LEVEL_FAIL}: '{args.skill_path}' is not a directory.")
        sys.exit(1)

    skill_md = os.path.join(skill_path, FILE_SKILL_MD)
    if not os.path.exists(skill_md):
        if json_output:
            _json_fail(
                f"No {FILE_SKILL_MD} found in '{args.skill_path}'. "
                f"Only registered skills (not capabilities) can be bundled."
            )
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
            if json_output:
                _json_fail(f"System root '{args.system_root}' is not a directory.")
            print_error_line(
                f"{LEVEL_FAIL}: System root '{args.system_root}' is not a directory."
            )
            sys.exit(1)
        if not is_within_directory(skill_path, system_root):
            if json_output:
                _json_fail(
                    f"Skill directory '{skill_path}' is not within "
                    f"the system root '{system_root}'."
                )
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
            if not json_output:
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
            if json_output:
                _json_fail(
                    f"'{system_root}' does not look like a skill system root "
                    f"(no '{FILE_MANIFEST}' and no '{DIR_SKILLS}/' directory)."
                )
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
            if not json_output:
                print(f"Inferred system root: {to_posix(system_root)}")
        else:
            _no_root_warn = (
                f"{LEVEL_WARN}: Could not infer system root. Bundling will fail "
                f"if external references are detected, because safety "
                f"boundaries cannot be enforced. Use --system-root to "
                f"specify it explicitly."
            )
            early_warnings.append(_no_root_warn)
            # Print immediately in human mode only; the merged
            # warnings list is used exclusively for JSON output to
            # avoid duplicating this message in notices/failure blocks.
            if not json_output:
                print_error_line(_no_root_warn)

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

    if not json_output:
        print(f"Bundling: {to_posix(skill_path)}")
        print(f"Output:   {to_posix(output_path)}")
        print("=" * SEPARATOR_WIDTH)

    inline_skills = args.inline_orchestrated_skills

    # ---- Phase 1: Pre-validation ----
    if not json_output:
        print("\nPhase 1: Pre-validation")
        print("-" * SEPARATOR_WIDTH)
        print("  Running pre-validation checks...")
    errors, prevalidate_warnings, scan_result = prevalidate(
        skill_path, system_root,
        inline_orchestrated_skills=inline_skills,
        bundle_target=bundle_target,
    )
    # Long-path pre-flight: any arcname whose worst-case extracted
    # path on Windows would exceed MAX_PATH is a FAIL before we spend
    # time assembling the bundle.  Same rule fires from validate_skill
    # at WARN severity during authoring.  Pass *system_root* as the
    # walker boundary when one is available so symlinks targeting
    # files under ``roles/`` or sibling capabilities (which
    # ``_copy_skill`` includes in the archive) are inspected here
    # instead of slipping through to the post-flight only.
    long_path_errors, _ = check_long_paths(
        skill_path, boundary=system_root,
    )
    # Reserved-name pre-flight: every bundled path component's stem
    # must be legal on NTFS, not just the skill's frontmatter name.
    # validate_skill emits this at WARN; bundle FAILs because once
    # we ship a zip with ``references/con.md``, a Windows user can
    # never extract it.  Same boundary widening as the long-path
    # rule above.
    reserved_name_errors, _ = check_reserved_path_components(
        skill_path, boundary=system_root,
    )
    # External-arcname pre-flight: ``check_long_paths`` /
    # ``check_reserved_path_components`` walk the skill tree but
    # external files (referenced via ``../../shared/...`` and the
    # like) only land in the bundle after ``create_bundle``.  Their
    # arcnames are deterministic given ``compute_bundle_path``, so
    # check them up-front instead of waiting for post-flight to
    # walk the assembled tree.  Skill basename is the archive root
    # — ``create_bundle`` writes externals at
    # ``<bundle_dir>/<bundle_rel>`` and the zip's arcname is
    # ``<skill_basename>/<bundle_rel>``.
    skill_basename = os.path.basename(os.path.abspath(skill_path))
    external_arcnames: list[str] = []
    if scan_result is not None:
        for ext_file in sorted(scan_result.get("external_files", set())):
            try:
                bundle_rel = compute_bundle_path(ext_file, system_root)
            except Exception:  # pragma: no cover — defensive
                continue
            external_arcnames.append(f"{skill_basename}/{bundle_rel}")
    external_arcname_errors, _ = check_external_arcnames(external_arcnames)
    errors = (
        list(errors)
        + long_path_errors
        + reserved_name_errors
        + external_arcname_errors
    )
    # In JSON mode, merge early warnings (e.g. missing system root)
    # with prevalidation warnings so they appear in the JSON output.
    # In human mode, early warnings were already printed inline, so
    # only include prevalidation warnings to avoid duplication.
    if json_output:
        warnings = early_warnings + list(prevalidate_warnings)
    else:
        warnings = list(prevalidate_warnings)

    if errors:
        if json_output:
            all_issues = list(errors) + list(warnings)
            print(to_json_output({
                "tool": "bundle",
                "path": to_posix(skill_path),
                "success": False,
                "phase": "pre-validation",
                "errors": categorize_errors_for_json(all_issues),
            }))
            sys.exit(1)
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

    if warnings and not json_output:
        print("\n  Notices:")
        for warn in warnings:
            print(f"    {warn}")

    if scan_result is None:
        if json_output:
            _json_fail(
                "Internal error: pre-validation completed without "
                "producing a scan result."
            )
        print(
            f"{LEVEL_FAIL}: Internal error: pre-validation completed without "
            "producing a scan result. Check prevalidate() implementation "
            "and call site."
        )
        sys.exit(1)

    ext_count = len(scan_result["external_files"])
    if not json_output:
        print(f"  Pre-validation passed. {ext_count} external file(s) to include.")

    # ---- Phase 2: Bundle creation ----
    if not json_output:
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
        if not json_output:
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
        if not json_output:
            print(f"\nPhase 3: Post-validation")
            print("-" * SEPARATOR_WIDTH)
        post_errors = postvalidate(bundle_dir)

        # Long-path post-flight: the pre-flight covered the skill
        # tree itself, but ``create_bundle`` also inlines external
        # references and orchestrated skills under the bundle root.
        # Walk the assembled tree so a bundle whose externals push a
        # path past MAX_PATH FAILs here rather than at user-extract
        # time.  ``arcname_root`` is the bundle base directory so
        # arcnames are namespaced under the bundle's own basename
        # (the form the zip stores).
        long_path_post_errors, _ = check_long_paths(
            bundle_dir,
            arcname_root=os.path.dirname(bundle_dir),
        )
        # Reserved-name post-flight: same parity reason — externals
        # and inlined skills are added here, so a path component
        # like ``references/aux.md`` introduced through inlining
        # would slip past the pre-flight.
        reserved_name_post_errors, _ = check_reserved_path_components(
            bundle_dir,
        )
        post_errors = (
            list(post_errors)
            + long_path_post_errors
            + reserved_name_post_errors
        )

        if post_errors:
            if json_output:
                print(to_json_output({
                    "tool": "bundle",
                    "path": to_posix(skill_path),
                    "success": False,
                    "phase": "post-validation",
                    "errors": categorize_errors_for_json(post_errors),
                }))
                sys.exit(1)
            _print_failure_block("post-validation errors", post_errors)
            sys.exit(1)

        if not json_output:
            print("  Post-validation passed.")

        # ---- Create archive ----
        phase_name = "archive creation"
        if not json_output:
            print(f"\nCreating archive...")
        create_zip(bundle_dir, output_path)

    except ValueError as exc:
        if json_output:
            _json_fail(str(exc))
        _print_failure_block(
            f"{phase_name} error",
            [f"{LEVEL_FAIL}: {exc}"],
        )
        sys.exit(1)

    except Exception as exc:
        if json_output:
            _json_fail(
                f"Unexpected error during {phase_name}: "
                f"{exc.__class__.__name__}: {exc}."
            )
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

    if json_output:
        result: dict = {
            "tool": "bundle",
            "path": to_posix(skill_path),
            "success": True,
            "output": to_posix(output_path),
            "stats": {
                "skill_name": stats["skill_name"],
                "file_count": stats["file_count"],
                "total_size": stats["total_size"],
                "archive_size": zip_size,
                "external_count": stats["external_count"],
                "rewrite_count": stats["rewrite_count"],
                "inlined_skill_count": stats["inlined_skill_count"],
            },
        }
        if warnings:
            result["warnings"] = [
                w[len(LEVEL_WARN) + 2:] if w.startswith(LEVEL_WARN + ": ") else w
                for w in warnings
            ]
        print(to_json_output(result))
        sys.exit(0)

    print(f"\n{'=' * SEPARATOR_WIDTH}")
    print(f"\u2713 Bundle created: {to_posix(output_path)}")
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
