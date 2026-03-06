"""Core bundling logic for skill packaging.

Pre-validates, assembles, post-validates, and zips a skill directory
into a self-contained archive.  This module is pure library code with
no CLI concerns — see ``bundle.py`` for the command-line entry point.
"""

import os
import re
import shutil
import zipfile
from collections.abc import Mapping
from typing import TypedDict

from .constants import (
    FILE_SKILL_MD,
    BUNDLE_DESCRIPTION_MAX_LENGTH,
    BUNDLE_EXCLUDE_PATTERNS,
    LEVEL_FAIL,
    LEVEL_WARN,
)
from .frontmatter import load_frontmatter
from .references import (
    scan_references,
    ScanResult,
    compute_bundle_path,
    infer_system_root,
    is_markdown_file,
    is_within_directory,
    strip_fragment,
    should_skip_reference,
    walk_skill_files,
    should_exclude,
    RE_BUNDLE_MD_LINK,
    RE_BUNDLE_BACKTICK,
)

class BundleStats(TypedDict):
    """Bundle creation statistics used in summary output."""

    file_count: int
    total_size: int
    external_count: int
    rewrite_count: int
    skill_name: str


# ===================================================================
# Phase 1: Pre-validation
# ===================================================================

def prevalidate(
    skill_path: str,
    system_root: str | None,
) -> tuple[list[str], list[str], ScanResult | None]:
    """Run all pre-validation checks.

    Returns (errors: list, warnings: list, scan_result: dict).
    *scan_result* is the output of ``scan_references()`` (contains
    external_files, reference_map, etc.).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Spec validation via validate_skill()
    # Lazy import: validate_skill lives as a sibling script, not inside
    # lib/.  Importing at call time avoids a module-level dependency on
    # the scripts/ directory being on sys.path (the CLI ensures this).
    from validate_skill import validate_skill

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
    else:
        # Surface non-failing validate_skill() messages (e.g., WARN/INFO)
        # so callers can display them during the bundling phase.
        for msg in spec_errors:
            warnings.append(msg)

    # 2. Description length check
    # Default target is Claude.ai to preserve existing behavior; callers
    # can override via SKILL_BUNDLE_TARGET environment variable for other
    # consumers (e.g., Gemini CLI, offline sharing).
    skill_md = os.path.join(skill_path, FILE_SKILL_MD)
    frontmatter, _body = load_frontmatter(skill_md)
    if frontmatter and "description" in frontmatter:
        desc = str(frontmatter["description"])
        target = os.environ.get("SKILL_BUNDLE_TARGET", "claude").lower()
        if len(desc) > BUNDLE_DESCRIPTION_MAX_LENGTH:
            if target == "claude":
                errors.append(
                    f"{LEVEL_FAIL}: Description is {len(desc)} characters "
                    f"(max {BUNDLE_DESCRIPTION_MAX_LENGTH} for Claude.ai). "
                    f"Shorten the description to fit the Claude.ai consumer "
                    f"platform limit. The Agent Skills spec allows 1024, but "
                    f"Claude.ai zip uploads enforce {BUNDLE_DESCRIPTION_MAX_LENGTH}."
                )
                return errors, warnings, None
            else:
                warnings.append(
                    f"{LEVEL_WARN}: Description is {len(desc)} characters, which "
                    f"exceeds the bundler default of {BUNDLE_DESCRIPTION_MAX_LENGTH}. "
                    f"This limit mirrors Claude.ai zip uploads; for generic targets, "
                    f"ensure the consumer supports longer descriptions."
                )

    # 3–7. Reference scanning
    # Resolve the effective root once so that prevalidate() and
    # scan_references() agree on the same value.
    if system_root is None:
        effective_root = infer_system_root(skill_path)
    else:
        effective_root = system_root
    scan_result = scan_references(skill_path, effective_root)
    errors.extend(scan_result["errors"])
    warnings.extend(scan_result["warnings"])

    return errors, warnings, scan_result


# ===================================================================
# Phase 2: Bundle Creation
# ===================================================================

def _copy_skill(
    skill_path: str,
    bundle_dir: str,
    exclude_patterns: list[str],
    system_root: str | None,
) -> None:
    """Copy the skill directory into the bundle, excluding unwanted files.

    Delegates directory traversal, symlink boundary enforcement, cycle
    detection, and exclude-pattern filtering to ``walk_skill_files()``.
    Boundary violations raise ``ValueError`` (prevalidation has already
    cleared the tree, so any violation here is unexpected).
    """
    boundary = skill_path if system_root is None else system_root

    for root, filename in walk_skill_files(
        skill_path, exclude_patterns, boundary
    ):
        rel_root = os.path.relpath(root, skill_path)
        target_root = os.path.join(bundle_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)

        src = os.path.join(root, filename)
        dst = os.path.join(target_root, filename)
        try:
            shutil.copy2(src, dst)
        except OSError as e:
            rel_src = os.path.relpath(src, skill_path).replace(os.sep, "/")
            raise ValueError(
                f"Failed to copy bundled file '{rel_src}'"
            ) from e


def _copy_external_files(
    external_files: set[str],
    system_root: str | None,
    bundle_dir: str,
    exclude_patterns: list[str] | None = None,
) -> dict[str, str]:
    """Copy external files into the bundle at their classified locations.

    Returns a mapping {absolute_source_path: relative_bundle_path}.
    Raises ``ValueError`` if two external source files would map to the
    same bundle path, if an external file would overwrite a
    skill-internal file already in the bundle, if a reference points
    to a directory instead of a regular file, or if a file's real path
    contains an excluded component.
    """
    if exclude_patterns is None:
        exclude_patterns = BUNDLE_EXCLUDE_PATTERNS
    file_mapping: dict[str, str] = {}
    # Reverse lookup: normcase(bundle_rel) -> source path (for collision
    # detection).  Using normcase ensures case-insensitive filesystems
    # (Windows, macOS default) catch collisions that differ only by casing.
    dest_to_source: dict[str, str] = {}

    for ext_file in sorted(external_files):
        if not os.path.isfile(ext_file):
            raise ValueError(
                f"External reference is not a regular file: '{ext_file}'. "
                f"Only files can be bundled — remove or replace the "
                f"directory reference."
            )

        # Enforce exclude patterns on the real (symlink-resolved) path
        # so that references to excluded paths (e.g. .git/config) cannot
        # leak sensitive files into the bundle.
        real_path = os.path.realpath(ext_file)
        parts = os.path.normpath(real_path).split(os.sep)
        if any(should_exclude(p, exclude_patterns) for p in parts):
            raise ValueError(
                f"External reference '{ext_file}' resolves to an "
                f"excluded path. Files matching bundle.exclude_patterns "
                f"cannot be included in the bundle."
            )

        bundle_rel = compute_bundle_path(ext_file, system_root)
        collision_key = os.path.normcase(bundle_rel)

        existing = dest_to_source.get(collision_key)
        if existing and existing != ext_file:
            raise ValueError(
                f"Bundle path collision: '{bundle_rel}' is the target "
                f"for both '{existing}' and '{ext_file}'. "
                f"Rename or relocate one of the source files to avoid "
                f"the conflict."
            )

        dest_to_source[collision_key] = ext_file
        target = os.path.join(bundle_dir, bundle_rel)

        # Detect collisions with files already in the bundle (copied
        # from the skill directory).  Without this check an external
        # file could silently overwrite a skill-internal file.
        if os.path.exists(target):
            raise ValueError(
                f"External file would overwrite skill-internal file at "
                f"'{bundle_rel}' (source: '{ext_file}'). "
                f"Rename or relocate the external file to avoid the "
                f"conflict."
            )

        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            shutil.copy2(ext_file, target)
        except OSError as e:
            rel_ext = os.path.relpath(ext_file, system_root).replace(os.sep, "/") if system_root else ext_file
            raise ValueError(
                f"Failed to copy external file '{rel_ext}' into bundle"
            ) from e
        file_mapping[ext_file] = bundle_rel

    return file_mapping


def _split_query_and_fragment(path: str) -> tuple[str, str]:
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
    # Fallback: normalise the path to handle semantically equivalent
    # forms like "../../roles/../roles/foo.md" -> "../../roles/foo.md".
    if new_base is None:
        normalised = os.path.normpath(base_path).replace(os.sep, "/")
        new_base = rewrite_map.get(normalised)
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
    system_root: str | None,
    file_mapping: dict[str, str],
    reverse_mapping: dict[str, str],
    skill_files: dict[str, str],
) -> dict[str, str]:
    """Build the old-path -> new-path map used for rewriting one file.

    *skill_files* maps ``{abs_original_skill_file: bundle_relative_path}``
    for files that originated from the skill directory.  This allows
    system-root-relative references to skill-internal files (e.g.
    ``skills/<name>/SKILL.md`` in inlined roles) to be rewritten.
    """
    bundle_file_dir = os.path.dirname(bundle_file)
    rewrite_map: dict[str, str] = {}

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

    # Add system-root-relative paths for skill-internal files so that
    # inlined external docs referencing e.g. "skills/<name>/SKILL.md"
    # get rewritten to the correct bundle-relative path.
    if system_root:
        for abs_skill_file, skill_bundle_rel in sorted(skill_files.items()):
            abs_target = os.path.join(bundle_dir, skill_bundle_rel)
            new_rel = os.path.relpath(abs_target, bundle_file_dir).replace(os.sep, "/")
            try:
                system_rel = os.path.relpath(abs_skill_file, system_root)
                rewrite_map.setdefault(system_rel, new_rel)
                rewrite_map.setdefault(system_rel.replace(os.sep, "/"), new_rel)
            except ValueError:
                pass

    return rewrite_map


def _rewrite_markdown_paths(
    bundle_dir: str,
    skill_path: str,
    system_root: str | None,
    file_mapping: dict[str, str],
) -> int:
    """Rewrite file references in all markdown files within the bundle."""
    rewrite_count = 0
    reverse_mapping = {
        bundle_rel: abs_source for abs_source, bundle_rel in file_mapping.items()
    }

    # Map skill-internal files: {abs_original_path: bundle_relative_path}.
    # These are files copied from the skill directory (not external), used
    # to rewrite system-root-relative references in inlined external docs.
    skill_files: dict[str, str] = {}
    for root, _dirs, files in os.walk(bundle_dir):
        for filename in files:
            filepath = os.path.join(root, filename)
            bundle_rel = os.path.relpath(filepath, bundle_dir).replace(os.sep, "/")
            if bundle_rel not in reverse_mapping:
                abs_original = os.path.join(skill_path, bundle_rel)
                skill_files[abs_original] = bundle_rel

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
                skill_files,
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
    system_root: str | None,
    reverse_mapping: dict[str, str],
) -> set[str]:
    """Compute all path forms a markdown file might use to reference a source.

    Given that *bundle_file* is the file in the bundle (copied from somewhere
    in skill_path), figure out what the original reference strings might
    have been before the bundle was created.
    """
    paths: set[str] = set()

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
    system_root: str | None,
    scan_result: ScanResult,
    exclude_patterns: list[str],
    *,
    bundle_base: str,
) -> tuple[str, dict[str, str], BundleStats]:
    """Create the bundle directory.

    *bundle_base* is a caller-owned temporary directory.  The caller
    is responsible for cleaning it up (e.g. via ``try/finally``).

    Returns (bundle_dir: str, file_mapping: dict, stats: dict).
    """
    skill_name = os.path.basename(os.path.abspath(skill_path))
    bundle_dir = os.path.join(bundle_base, skill_name)
    os.makedirs(bundle_dir)

    # Step 1: Copy skill as-is
    _copy_skill(skill_path, bundle_dir, exclude_patterns, system_root)

    # Step 2: Copy external files
    external_files = scan_result["external_files"]
    file_mapping: dict[str, str] = {}
    if external_files:
        file_mapping = _copy_external_files(
            external_files, system_root, bundle_dir, exclude_patterns
        )

    # Step 3: Rewrite markdown paths
    rewrite_count = 0
    if file_mapping:
        rewrite_count = _rewrite_markdown_paths(
            bundle_dir, skill_path, system_root, file_mapping
        )

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
        "rewrite_count": rewrite_count,
        "skill_name": skill_name,
    }
    return bundle_dir, file_mapping, stats


# ===================================================================
# Phase 3: Post-validation
# ===================================================================

def postvalidate(bundle_dir: str) -> list[str]:
    """Verify the bundle is self-contained and well-formed.

    Returns a list of error strings (empty if all checks pass).
    """
    errors: list[str] = []

    # 1. SKILL.md uniqueness (case-insensitive)
    skill_md_files: list[str] = []
    for root, _dirs, files in os.walk(bundle_dir):
        for filename in files:
            if filename.lower() == FILE_SKILL_MD.lower():
                rel = os.path.relpath(
                    os.path.join(root, filename), bundle_dir
                ).replace(os.sep, "/")
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
                    rel_source = os.path.relpath(filepath, bundle_dir).replace(os.sep, "/")
                    if not is_within_directory(target, bundle_dir):
                        errors.append(
                            f"{LEVEL_FAIL}: Markdown reference escapes bundle: "
                            f"'{rel_source}' line {line_num}: "
                            f"'{ref_path}' resolves outside the bundle directory."
                        )
                    elif not os.path.exists(target):
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
                    rel_source = os.path.relpath(filepath, bundle_dir).replace(os.sep, "/")
                    if not is_within_directory(target, bundle_dir):
                        errors.append(
                            f"{LEVEL_FAIL}: Backtick reference escapes bundle: "
                            f"'{rel_source}' line {line_num}: "
                            f"'{ref_path}' resolves outside the bundle directory."
                        )
                    elif not os.path.exists(target):
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

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(bundle_dir):
            dirs.sort()
            for filename in sorted(files):
                filepath = os.path.join(root, filename)
                arcname = os.path.relpath(filepath, bundle_base).replace(os.sep, "/")
                zf.write(filepath, arcname)

    return output_path
