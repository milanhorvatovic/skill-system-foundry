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

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import sys
import tempfile
import zipfile
from typing import Dict, List, Mapping, Optional, Set, Tuple, TypedDict

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.constants import (
    FILE_SKILL_MD,
    BUNDLE_DESCRIPTION_MAX_LENGTH,
    BUNDLE_EXCLUDE_PATTERNS,
    SEPARATOR_WIDTH,
    LEVEL_FAIL, LEVEL_WARN,
)
from lib.frontmatter import load_frontmatter
from lib.references import (
    scan_references,
    ScanResult,
    compute_bundle_path,
    infer_system_root,
    is_markdown_file,
    strip_fragment,
    should_skip_reference,
    RE_BUNDLE_MD_LINK,
    RE_BUNDLE_BACKTICK,
)
from lib.reporting import categorize_errors, print_error_line, print_summary

# Import validate_skill from sibling script
from validate_skill import validate_skill


class BundleStats(TypedDict):
    """Bundle creation statistics used in summary output."""

    file_count: int
    total_size: int
    external_count: int
    skill_name: str
    bundle_dir: str
    bundle_base: str


# ===================================================================
# Phase 1: Pre-validation
# ===================================================================

def prevalidate(
    skill_path: str,
    system_root: Optional[str],
) -> Tuple[List[str], List[str], Optional[ScanResult]]:
    """Run all pre-validation checks.

    Returns (errors: list, warnings: list, scan_result: dict).
    *scan_result* is the output of ``scan_references()`` (contains
    external_files, reference_map, etc.).
    """
    errors = []
    warnings = []

    # 1. Spec validation via validate_skill()
    print("  Validating skill against Agent Skills specification...")
    spec_errors, _passes = validate_skill(skill_path)
    fails_in_spec = [e for e in spec_errors if e.startswith(LEVEL_FAIL)]
    if fails_in_spec:
        errors.append(
            f"{LEVEL_FAIL}: Skill has spec validation failures. "
            f"Fix these before bundling:"
        )
        for err in spec_errors:
            errors.append(err)
        return errors, warnings, None

    # 2. Description length check (Claude.ai 200-char limit)
    print("  Checking description length for Claude.ai compatibility...")
    skill_md = os.path.join(skill_path, FILE_SKILL_MD)
    frontmatter, _body = load_frontmatter(skill_md)
    if frontmatter and "description" in frontmatter:
        desc = str(frontmatter["description"])
        if len(desc) > BUNDLE_DESCRIPTION_MAX_LENGTH:
            errors.append(
                f"{LEVEL_FAIL}: Description is {len(desc)} characters "
                f"(max {BUNDLE_DESCRIPTION_MAX_LENGTH} for Claude.ai). "
                f"Shorten the description to fit the Claude.ai consumer "
                f"platform limit. The Agent Skills spec allows 1024, but "
                f"Claude.ai zip uploads enforce {BUNDLE_DESCRIPTION_MAX_LENGTH}."
            )
            return errors, warnings, None

    # 3–7. Reference scanning
    print("  Scanning references...")
    scan_result = scan_references(skill_path, system_root)
    errors.extend(scan_result["errors"])
    warnings.extend(scan_result["warnings"])

    return errors, warnings, scan_result


# ===================================================================
# Phase 2: Bundle Creation
# ===================================================================

def _should_exclude(path: str, exclude_patterns: List[str]) -> bool:
    """Check if a path component matches any exclude pattern."""
    basename = os.path.basename(path)
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(basename, pattern):
            return True
    return False


def _copy_skill(skill_path: str, bundle_dir: str, exclude_patterns: List[str]) -> None:
    """Copy the skill directory into the bundle, excluding unwanted files."""
    for root, dirs, files in os.walk(skill_path):
        # Filter excluded directories in-place so os.walk skips them
        dirs[:] = [
            d for d in dirs
            if not _should_exclude(d, exclude_patterns)
        ]

        rel_root = os.path.relpath(root, skill_path)
        target_root = os.path.join(bundle_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)

        for filename in files:
            if _should_exclude(filename, exclude_patterns):
                continue
            src = os.path.join(root, filename)
            dst = os.path.join(target_root, filename)
            shutil.copy2(src, dst)


def _copy_external_files(external_files: Set[str], system_root: Optional[str], bundle_dir: str) -> Dict[str, str]:
    """Copy external files into the bundle at their classified locations.

    Returns a mapping {absolute_source_path: relative_bundle_path}.
    """
    file_mapping = {}

    for ext_file in external_files:
        bundle_rel = compute_bundle_path(ext_file, system_root)
        target = os.path.join(bundle_dir, bundle_rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(ext_file, target)
        file_mapping[ext_file] = bundle_rel

    return file_mapping


def _split_query_and_fragment(path: str) -> Tuple[str, str]:
    """Split *path* into base path and optional query/fragment suffix."""
    query_index = path.find("?")
    fragment_index = path.find("#")
    indexes = [idx for idx in (query_index, fragment_index) if idx >= 0]
    if not indexes:
        return path, ""

    split_index = min(indexes)
    return path[:split_index], path[split_index:]


def _rewrite_reference_target(
    raw_target: str,
    rewrite_map: Mapping[str, str],
    *,
    allow_title: bool,
) -> str:
    """Rewrite a markdown target while preserving wrappers and suffixes."""
    if not raw_target:
        return raw_target

    leading_len = len(raw_target) - len(raw_target.lstrip())
    trailing_len = len(raw_target) - len(raw_target.rstrip())
    leading = raw_target[:leading_len]
    trailing = raw_target[len(raw_target) - trailing_len:] if trailing_len else ""

    target = raw_target.strip()
    title_suffix = ""
    if allow_title:
        title_match = re.search(r'''\s+["'][^"']*["']\s*$''', target)
        if title_match:
            title_suffix = target[title_match.start():]
            target = target[:title_match.start()].strip()

    wrapped = False
    if target.startswith("<") and target.endswith(">"):
        wrapped = True
        target = target[1:-1].strip()

    base_path, suffix = _split_query_and_fragment(target)
    new_base = rewrite_map.get(base_path)
    if new_base is None:
        return raw_target

    rewritten_target = new_base + suffix
    if wrapped:
        rewritten_target = f"<{rewritten_target}>"

    return f"{leading}{rewritten_target}{title_suffix}{trailing}"


def _rewrite_markdown_content(content: str, rewrite_map: Mapping[str, str]) -> str:
    """Rewrite markdown links and backticks using a path rewrite map."""

    def _replace_markdown_link(match: re.Match[str]) -> str:
        label = match.group(1)
        target = match.group(2)
        new_target = _rewrite_reference_target(target, rewrite_map, allow_title=True)
        if new_target == target:
            return match.group(0)
        return f"[{label}]({new_target})"

    def _replace_backtick(match: re.Match[str]) -> str:
        target = match.group(1)
        new_target = _rewrite_reference_target(target, rewrite_map, allow_title=False)
        if new_target == target:
            return match.group(0)
        return f"`{new_target}`"

    updated = RE_BUNDLE_MD_LINK.sub(_replace_markdown_link, content)
    return RE_BUNDLE_BACKTICK.sub(_replace_backtick, updated)


def _build_rewrite_map(
    bundle_file: str,
    bundle_dir: str,
    skill_path: str,
    system_root: Optional[str],
    file_mapping: Dict[str, str],
    reverse_mapping: Dict[str, str],
) -> Dict[str, str]:
    """Build the old-path -> new-path map used for rewriting one file."""
    bundle_file_dir = os.path.dirname(bundle_file)
    rewrite_map: Dict[str, str] = {}

    for abs_source, bundle_rel in sorted(file_mapping.items(), key=lambda item: item[1]):
        abs_target = os.path.join(bundle_dir, bundle_rel)
        new_rel = os.path.relpath(abs_target, bundle_file_dir).replace(os.sep, "/")
        original_paths = _compute_original_paths(
            abs_source,
            bundle_file,
            skill_path,
            bundle_dir,
            system_root,
            reverse_mapping,
        )

        for orig_path in sorted(original_paths):
            if not orig_path:
                continue
            rewrite_map.setdefault(orig_path, new_rel)
            rewrite_map.setdefault(orig_path.replace(os.sep, "/"), new_rel)

    return rewrite_map


def _rewrite_markdown_paths(
    bundle_dir: str,
    skill_path: str,
    system_root: Optional[str],
    file_mapping: Dict[str, str],
) -> int:
    """Rewrite file references in all markdown files within the bundle."""
    rewrite_count = 0
    reverse_mapping = {
        bundle_rel: abs_source for abs_source, bundle_rel in file_mapping.items()
    }

    for root, _dirs, files in os.walk(bundle_dir):
        for filename in files:
            if not is_markdown_file(filename):
                continue

            filepath = os.path.join(root, filename)
            rewrite_map = _build_rewrite_map(
                filepath,
                bundle_dir,
                skill_path,
                system_root,
                file_mapping,
                reverse_mapping,
            )
            if not rewrite_map:
                continue

            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            updated = _rewrite_markdown_content(content, rewrite_map)
            if updated == content:
                continue

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(updated)
            rewrite_count += 1

    return rewrite_count


def _compute_original_paths(
    abs_source: str,
    bundle_file: str,
    skill_path: str,
    bundle_dir: str,
    system_root: Optional[str],
    reverse_mapping: Dict[str, str],
) -> Set[str]:
    """Compute all path forms a markdown file might use to reference a source.

    Given that *bundle_file* is the file in the bundle (copied from somewhere
    in skill_path), figure out what the original reference strings might
    have been before the bundle was created.
    """
    paths = set()

    # Resolve the original source file path for this bundled markdown file.
    # Normalize to forward slashes so the lookup matches keys from
    # compute_bundle_path(), which always uses forward slashes.
    bundle_rel = os.path.relpath(bundle_file, bundle_dir).replace(os.sep, "/")
    original_file = reverse_mapping.get(bundle_rel)
    if not original_file:
        original_file = os.path.join(skill_path, bundle_rel)
    original_dir = os.path.dirname(original_file)

    # Original relative path from the source file's location
    try:
        rel_from_original = os.path.relpath(abs_source, original_dir)
        paths.add(rel_from_original)
        paths.add(rel_from_original.replace(os.sep, "/"))
    except ValueError:
        pass

    # System-root-relative form (e.g., roles/eng/reviewer.md)
    if system_root:
        try:
            from_system_root = os.path.relpath(abs_source, system_root)
            paths.add(from_system_root)
            paths.add(from_system_root.replace(os.sep, "/"))
        except ValueError:
            pass

    return paths


def create_bundle(
    skill_path: str,
    system_root: Optional[str],
    scan_result: ScanResult,
    exclude_patterns: List[str],
) -> Tuple[str, Dict[str, str], BundleStats]:
    """Create the bundle directory.

    Returns (bundle_dir: str, file_mapping: dict, stats: dict).
    """
    skill_name = os.path.basename(os.path.abspath(skill_path))
    bundle_base = tempfile.mkdtemp(prefix="skill_bundle_")
    bundle_dir = os.path.join(bundle_base, skill_name)
    os.makedirs(bundle_dir)

    # Step 1: Copy skill as-is
    print("  Copying skill directory...")
    _copy_skill(skill_path, bundle_dir, exclude_patterns)

    # Step 2: Copy external files
    external_files = scan_result["external_files"]
    file_mapping: Dict[str, str] = {}
    if external_files:
        print(f"  Copying {len(external_files)} external file(s)...")
        file_mapping = _copy_external_files(
            external_files, system_root, bundle_dir
        )

    # Step 3: Rewrite markdown paths
    if file_mapping:
        print("  Rewriting markdown references...")
        rewrite_count = _rewrite_markdown_paths(
            bundle_dir, skill_path, system_root, file_mapping
        )
        print(f"  Rewrote references in {rewrite_count} file(s).")

    # Compute stats
    file_count = 0
    total_size = 0
    for root, _dirs, files in os.walk(bundle_dir):
        for filename in files:
            filepath = os.path.join(root, filename)
            file_count += 1
            total_size += os.path.getsize(filepath)

    stats: BundleStats = {
        "file_count": file_count,
        "total_size": total_size,
        "external_count": len(external_files),
        "skill_name": skill_name,
        "bundle_dir": bundle_dir,
        "bundle_base": bundle_base,
    }
    return bundle_dir, file_mapping, stats


# ===================================================================
# Phase 3: Post-validation
# ===================================================================

def postvalidate(bundle_dir: str) -> List[str]:
    """Verify the bundle is self-contained and well-formed.

    Returns a list of error strings (empty if all checks pass).
    """
    errors = []

    # 1. SKILL.md uniqueness (case-insensitive)
    skill_md_files = []
    for root, _dirs, files in os.walk(bundle_dir):
        for filename in files:
            if filename.lower() == FILE_SKILL_MD.lower():
                rel = os.path.relpath(os.path.join(root, filename), bundle_dir)
                skill_md_files.append(rel)

    if len(skill_md_files) == 0:
        errors.append(
            f"{LEVEL_FAIL}: No {FILE_SKILL_MD} found in the bundle."
        )
    elif len(skill_md_files) > 1:
        locations = ", ".join(skill_md_files)
        errors.append(
            f"{LEVEL_FAIL}: Multiple SKILL.md files found (case-insensitive): "
            f"{locations}. Claude requires exactly one SKILL.md in the "
            f"archive. Capability entry points should use capability.md."
        )

    # 2. Reference integrity — every markdown link should resolve
    for root, _dirs, files in os.walk(bundle_dir):
        for filename in files:
            if not is_markdown_file(filename):
                continue
            filepath = os.path.join(root, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            for line_num, line in enumerate(content.split("\n"), 1):
                # Markdown links
                for match in RE_BUNDLE_MD_LINK.finditer(line):
                    ref_path = match.group(2)
                    if should_skip_reference(ref_path):
                        continue

                    ref_clean = strip_fragment(ref_path)
                    if not ref_clean:
                        continue

                    target = os.path.normpath(
                        os.path.join(os.path.dirname(filepath), ref_clean)
                    )
                    if not os.path.exists(target):
                        rel_source = os.path.relpath(filepath, bundle_dir)
                        errors.append(
                            f"{LEVEL_FAIL}: Unresolved markdown reference in bundle: "
                            f"'{rel_source}' line {line_num}: "
                            f"'{ref_path}' does not exist in the bundle."
                        )

                # Backtick path references
                for match in RE_BUNDLE_BACKTICK.finditer(line):
                    ref_path = match.group(1)
                    if should_skip_reference(ref_path):
                        continue

                    ref_clean = strip_fragment(ref_path)
                    if not ref_clean:
                        continue

                    target = os.path.normpath(
                        os.path.join(os.path.dirname(filepath), ref_clean)
                    )
                    if not os.path.exists(target):
                        rel_source = os.path.relpath(filepath, bundle_dir)
                        errors.append(
                            f"{LEVEL_FAIL}: Unresolved backtick reference in bundle: "
                            f"'{rel_source}' line {line_num}: "
                            f"'{ref_path}' does not exist in the bundle."
                        )

    return errors

# ===================================================================
# Archive Creation
# ===================================================================

def create_zip(bundle_dir: str, output_path: str) -> str:
    """Create a zip archive from the bundle directory.

    The archive contains the skill folder at its root, per Claude.ai
    requirements.
    """
    # bundle_dir is like /tmp/.../my-skill/
    # We want the zip to contain my-skill/ at the root.
    bundle_base = os.path.dirname(bundle_dir)
    skill_name = os.path.basename(bundle_dir)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(bundle_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                arcname = os.path.relpath(filepath, bundle_base).replace(os.sep, "/")
                zf.write(filepath, arcname)

    return output_path


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


def main() -> None:
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
    else:
        system_root = infer_system_root(skill_path)
        if system_root:
            print(f"Inferred system root: {system_root}")
        else:
            print(
                "Warning: Could not infer system root. External references "
                "outside the skill directory may not resolve. Use "
                "--system-root to specify it explicitly."
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
    errors, warnings, scan_result = prevalidate(skill_path, system_root)

    if errors:
        print(f"\n{'=' * SEPARATOR_WIDTH}")
        print("Bundling FAILED — pre-validation errors:\n")
        for err in errors:
            print_error_line(err)
        if warnings:
            print()
            for warn in warnings:
                print_error_line(warn)
        fails, warns, infos = categorize_errors(errors)
        print("-" * SEPARATOR_WIDTH)
        print_summary(fails, warns, infos)
        print(
            "\nFix the issues above and re-run. This skill system can help "
            "you resolve structural and reference problems."
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
    bundle_dir, file_mapping, stats = create_bundle(
        skill_path, system_root, scan_result, BUNDLE_EXCLUDE_PATTERNS
    )

    try:
        # ---- Phase 3: Post-validation ----
        print(f"\nPhase 3: Post-validation")
        print("-" * SEPARATOR_WIDTH)
        post_errors = postvalidate(bundle_dir)

        if post_errors:
            print(f"\n{'=' * SEPARATOR_WIDTH}")
            print("Bundling FAILED — post-validation errors:\n")
            for err in post_errors:
                print_error_line(err)
            fails, warns, infos = categorize_errors(post_errors)
            print("-" * SEPARATOR_WIDTH)
            print_summary(fails, warns, infos)
            sys.exit(1)

        print("  Post-validation passed.")

        # ---- Create archive ----
        print(f"\nCreating archive...")
        create_zip(bundle_dir, output_path)

    finally:
        # Clean up temp directory — always, even on unexpected errors
        shutil.rmtree(stats["bundle_base"], ignore_errors=True)

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
