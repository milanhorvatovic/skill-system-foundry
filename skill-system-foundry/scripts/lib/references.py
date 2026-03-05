"""Reference scanning, resolution, and graph traversal for skill bundling.

Extracts file references from skill content, resolves them to absolute
paths, and traverses the reference graph to identify all external
dependencies.  Detects cross-skill references, cycles between external
documents, and broken links.
"""

import fnmatch
import os
import re
from typing import Literal, TypedDict

from .constants import (
    DIR_SKILLS, DIR_ROLES, DIR_REFERENCES, DIR_ASSETS, DIR_SCRIPTS,
    FILE_SKILL_MD, FILE_MANIFEST,
    BUNDLE_MAX_REFERENCE_DEPTH,
    BUNDLE_EXCLUDE_PATTERNS,
    BUNDLE_INFER_MAX_WALK_DEPTH,
    LEVEL_FAIL, LEVEL_WARN,
    EXT_MARKDOWN,
)

# ===================================================================
# Reference Detection Patterns (broader than validation patterns)
# ===================================================================

# Markdown links: [text](path) — captures the path portion.
# Post-filtered to exclude URLs, anchors, and template placeholders.
RE_BUNDLE_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

# Backtick file paths: `path/to/file` — requires at least one /
# to distinguish file paths from inline code snippets.
RE_BUNDLE_BACKTICK = re.compile(r"`([^`\s]*?/[^`\s]+)`")

# Markdown-wrapped local path, optionally followed by a title:
#   <path/to/file.md>
#   <path/to/file.md> "Title"
RE_WRAPPED_LOCAL_REF = re.compile(r'''^\s*<[^<>]+>\s*(?:["'][^"']*["'])?\s*$''')

# Best-effort path detection in non-markdown text files.
# Looks for paths starting with known directory prefixes.
RE_TEXT_FILE_REF = re.compile(
    r"(?:references|scripts|assets|roles|capabilities)"
    r"/[^\s'\"`,;:)}\]>]+"
)

# Binary file extensions — not scanned for references.
BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm",
    ".pyc", ".pyo", ".class", ".o", ".a",
})


# ===================================================================
# Utility Functions
# ===================================================================

def is_binary_file(filepath: str) -> bool:
    """Check if a file is likely binary based on its extension."""
    _, ext = os.path.splitext(filepath)
    return ext.lower() in BINARY_EXTENSIONS


def is_markdown_file(filepath: str) -> bool:
    """Check if a file is a markdown file."""
    return filepath.lower().endswith(EXT_MARKDOWN)


def is_within_directory(filepath: str, directory: str) -> bool:
    """Check whether *filepath* is inside (or equal to) *directory*.

    Resolves symlinks so that a symlink inside *directory* whose real
    target is outside will correctly return ``False``.  Normalises
    case so differing drive-letter casing on Windows doesn't cause
    false negatives.  Handles filesystem roots correctly (``/`` on
    POSIX, ``C:\\`` on Windows).
    """
    filepath_norm = os.path.normcase(os.path.realpath(filepath))
    directory_norm = os.path.normcase(os.path.realpath(directory))
    try:
        common = os.path.commonpath([filepath_norm, directory_norm])
    except ValueError:
        # Different drives on Windows or otherwise incomparable paths
        return False
    return common == directory_norm


# ===================================================================
# Reference Extraction
# ===================================================================

def strip_fragment(ref_path: str) -> str:
    """Strip query/anchor/title wrappers from a reference path.

    Returns the filesystem-resolvable path portion, removing:
      - ``<...>`` markdown path wrappers
      - ``?query`` suffixes
      - ``#fragment`` anchors (e.g. ``foo.md#section`` -> ``foo.md``)
      - ``"title"`` suffixes (e.g. ``foo.md "My Title"`` -> ``foo.md``)

    The caller keeps the original string for error messages and
    markdown rewriting.
    """
    # Strip title suffix: path "title" or path 'title'
    path = re.sub(r'''\s+["'][^"']*["']\s*$''', "", ref_path)
    path = path.strip()

    # Unwrap markdown angle-bracket path form: <path/to/file.md>
    if path.startswith("<") and path.endswith(">"):
        path = path[1:-1].strip()

    # Strip query first, then anchor fragment
    path = path.split("?", 1)[0]
    # Strip anchor fragment
    path = path.split("#", 1)[0]
    return path.strip()


def should_skip_reference(ref_path: str) -> bool:
    """Return True when a reference should not be treated as a local file."""
    if not ref_path:
        return True

    path = ref_path.strip()
    if not path:
        return True

    # Check URL schemes on the raw path first.
    if path.startswith(("http://", "https://", "#", "mailto:", "ftp://")):
        return True

    if "<" in path or ">" in path:
        # Allow markdown-wrapped local paths: <path/to/file.md> "Title"
        if RE_WRAPPED_LOCAL_REF.match(path):
            # Unwrap and re-check for URL schemes inside the brackets
            # so that autolinks like <https://example.com> are skipped.
            inner = path.split("<", 1)[1].split(">", 1)[0].strip()
            if inner.startswith(("http://", "https://", "mailto:", "ftp://")):
                return True
            return False
        return True

    return False


# Type aliases for reference tuples
ReferenceType = Literal["markdown_link", "backtick", "text_detected"]
ResolveFailReason = Literal["absolute_path", "escapes_system_root", "not_found"]
RawRef = tuple[str, int, ReferenceType]  # (ref_path, line_num, ref_type)
FilteredRef = tuple[str, str, int, ReferenceType]  # (raw_ref, clean_path, line_num, ref_type)
ResolvedRef = tuple[str, int, ReferenceType, str | None]  # (raw_ref, line_num, ref_type, resolved)


class ScanResult(TypedDict):
    """Structured output of ``scan_references()``."""

    external_files: set[str]
    errors: list[str]
    warnings: list[str]
    reference_map: dict[str, list[ResolvedRef]]


def extract_references(filepath: str) -> list[FilteredRef]:
    """Extract file references from a single file.

    For markdown files, extracts markdown-link and backtick references.
    For other text files, performs best-effort detection of paths.

    Returns a list of tuples:
        (raw_ref: str, clean_path: str, line_number: int, ref_type: str)

    *raw_ref* is the original reference string (including any anchor
    or title).  *clean_path* is the filesystem-resolvable portion
    with fragments and titles stripped.

    *ref_type* is one of ``'markdown_link'``, ``'backtick'``, or
    ``'text_detected'``.
    """
    if is_binary_file(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, OSError):
        return []

    refs = []
    lines = content.split("\n")

    if is_markdown_file(filepath):
        for line_num, line in enumerate(lines, 1):
            seen_in_line = set()
            for match in RE_BUNDLE_MD_LINK.finditer(line):
                ref_path = match.group(2)
                refs.append((ref_path, line_num, "markdown_link"))
                seen_in_line.add(ref_path)
            # Backtick refs — avoid duplicating paths already captured
            for match in RE_BUNDLE_BACKTICK.finditer(line):
                ref_path = match.group(1)
                if ref_path not in seen_in_line:
                    refs.append((ref_path, line_num, "backtick"))
                    seen_in_line.add(ref_path)
    else:
        for line_num, line in enumerate(lines, 1):
            for match in RE_TEXT_FILE_REF.finditer(line):
                ref_path = match.group(0)
                refs.append((ref_path, line_num, "text_detected"))

    return _filter_refs(refs)


def _filter_refs(refs: list[RawRef]) -> list[FilteredRef]:
    """Remove URLs, anchors, template placeholders, and obvious non-paths.

    Returns 4-tuples: ``(raw_ref, clean_path, line_num, ref_type)``.
    *clean_path* has anchor fragments and title suffixes stripped.
    """
    filtered = []
    for ref_path, line_num, ref_type in refs:
        if should_skip_reference(ref_path):
            continue
        clean_path = strip_fragment(ref_path)
        if not clean_path:
            continue
        filtered.append((ref_path, clean_path, line_num, ref_type))
    return filtered


# ===================================================================
# Path Resolution
# ===================================================================

def resolve_reference(ref_path: str, source_file: str, system_root: str | None = None) -> str | None:
    """Resolve a reference path to an absolute filesystem path.

    Tries in order:
      1. Relative to the source file's directory
      2. Relative to the system root (if provided)

    Rejects absolute references and any resolved path that escapes
    the system root (when provided) to prevent accidentally bundling
    arbitrary files from outside the project.

    Returns the absolute path if found, ``None`` otherwise.
    """
    resolved, _ = resolve_reference_with_reason(ref_path, source_file, system_root)
    return resolved


def resolve_reference_with_reason(
    ref_path: str,
    source_file: str,
    system_root: str | None = None,
) -> tuple[str | None, ResolveFailReason | None]:
    """Resolve a reference and return both path and failure reason.

    Returns a tuple:
        (resolved_path_or_none, reason_or_none)

    *reason_or_none* is one of:
      - ``"absolute_path"``
      - ``"escapes_system_root"``
      - ``"not_found"``
    """
    # Reject absolute paths — references must be relative.
    if os.path.isabs(ref_path):
        return None, "absolute_path"

    source_dir = os.path.dirname(os.path.abspath(source_file))
    source_candidate = os.path.normpath(os.path.join(source_dir, ref_path))

    if system_root and not is_within_directory(source_candidate, system_root):
        return None, "escapes_system_root"

    # Try relative to the source file
    candidate = source_candidate
    if os.path.exists(candidate):
        return candidate, None

    # Try relative to the system root
    if system_root:
        candidate = os.path.normpath(os.path.join(system_root, ref_path))
        if not is_within_directory(candidate, system_root):
            return None, "escapes_system_root"

        if os.path.exists(candidate):
            return candidate, None

    return None, "not_found"


def find_containing_skill(filepath: str, system_root: str) -> str | None:
    """Find which skill directory contains *filepath*.

    Walks up from the file looking for a ``SKILL.md``.  Returns the
    skill directory (absolute) or ``None`` if *filepath* is not inside
    any skill under *system_root*.
    """
    filepath = os.path.abspath(filepath)
    system_root = os.path.abspath(system_root)

    current = os.path.dirname(filepath)
    while is_within_directory(current, system_root) and current != system_root:
        if os.path.exists(os.path.join(current, FILE_SKILL_MD)):
            return current
        current = os.path.dirname(current)

    return None


# ===================================================================
# Reference Graph Traversal
# ===================================================================

def scan_references(
    skill_path: str,
    system_root: str | None = None,
    max_depth: int | None = None,
    exclude_patterns: list[str] | None = None,
) -> ScanResult:
    """Scan a skill's full reference graph for external dependencies.

    Traverses all files in *skill_path*, finds external references,
    and recursively scans those files for further references.

    Args:
        skill_path:       Absolute path to the skill directory.
        system_root:      Optional system root (contains ``skills/``,
                          ``roles/``).  When omitted, inferred by walking
                          up from *skill_path*.
        max_depth:        Maximum transitive reference depth.  Defaults to
                          ``BUNDLE_MAX_REFERENCE_DEPTH`` from config.
        exclude_patterns: Glob patterns for files/directories to skip
                          during the skill walk.  Defaults to
                          ``BUNDLE_EXCLUDE_PATTERNS`` from config.

    Returns a dict::

        {
            'external_files': set of absolute paths,
            'errors':         list of FAIL strings,
            'warnings':       list of WARN strings,
            'reference_map':  {source_path: [(raw_ref, line, type, resolved), ...]},
        }
    """
    if max_depth is None:
        max_depth = BUNDLE_MAX_REFERENCE_DEPTH
    if exclude_patterns is None:
        exclude_patterns = BUNDLE_EXCLUDE_PATTERNS

    skill_path = os.path.abspath(skill_path)
    if system_root is not None:
        system_root = os.path.abspath(system_root)
    else:
        system_root = infer_system_root(skill_path)

    external_files: set[str] = set()
    errors: list[str] = []
    warnings: list[str] = []
    reference_map: dict[str, list[ResolvedRef]] = {}

    # External files whose subtrees have been fully traversed.
    scanned_external: set[str] = set()

    def _scan_file(
        filepath: str,
        depth: int,
        ancestor_set: frozenset[str],
        ancestor_path: tuple[str, ...],
    ) -> None:
        """Recursively scan *filepath* and classify its references.

        *ancestor_set* is a frozenset for O(1) cycle membership checks.
        *ancestor_path* is an ordered tuple for deterministic cycle display.
        """
        filepath = os.path.abspath(filepath)

        if depth > max_depth:
            errors.append(
                f"{LEVEL_FAIL}: Reference depth limit ({max_depth}) exceeded "
                f"while scanning '{_rel(filepath)}'. "
                f"Check for excessive nesting or increase "
                f"bundle.max_reference_depth in configuration.yaml."
            )
            return

        refs = extract_references(filepath)
        if not refs:
            return

        resolved_refs: list[ResolvedRef] = []

        for raw_ref, clean_path, line_num, ref_type in refs:
            resolved, fail_reason = resolve_reference_with_reason(
                clean_path, filepath, system_root
            )
            resolved_refs.append((raw_ref, line_num, ref_type, resolved))

            # ---- Broken reference ----
            if resolved is None:
                if fail_reason == "absolute_path":
                    errors.append(
                        f"{LEVEL_FAIL}: Invalid absolute reference in "
                        f"'{_rel(filepath)}' line {line_num}: '{raw_ref}'. "
                        f"Bundle references must use relative paths within "
                        f"the skill system root."
                    )
                elif fail_reason == "escapes_system_root":
                    errors.append(
                        f"{LEVEL_FAIL}: Reference escapes system root in "
                        f"'{_rel(filepath)}' line {line_num}: '{raw_ref}'. "
                        f"Bundling files outside the skill system root is "
                        f"not allowed."
                    )
                else:
                    errors.append(
                        f"{LEVEL_FAIL}: Broken reference in "
                        f"'{_rel(filepath)}' line {line_num}: "
                        f"'{raw_ref}' does not resolve to any existing file. "
                        f"Fix the reference path before bundling."
                    )
                continue

            # ---- Internal (within the skill) ----
            if is_within_directory(resolved, skill_path):
                continue

            # ---- No system root — refuse to traverse outside the skill ----
            if not system_root:
                errors.append(
                    f"{LEVEL_FAIL}: External reference in "
                    f"'{_rel(filepath)}' line {line_num}: '{raw_ref}' "
                    f"resolves outside the skill directory but no system "
                    f"root is available to enforce safety boundaries. "
                    f"Use --system-root to specify the skill system root."
                )
                continue

            # ---- Non-markdown detected reference (warn only) ----
            if ref_type == "text_detected":
                warnings.append(
                    f"{LEVEL_WARN}: Non-markdown file reference detected in "
                    f"'{_rel(filepath)}' line {line_num}: '{raw_ref}'. "
                    f"This reference will not be automatically rewritten "
                    f"in the bundle. You may need to update it manually."
                )
                external_files.add(resolved)
                # Still recurse so transitive dependencies of the
                # referenced file are discovered (the warning above
                # only concerns the originating non-markdown reference).
                if resolved not in scanned_external:
                    scanned_external.add(resolved)
                    new_set = ancestor_set | frozenset({resolved})
                    new_path = ancestor_path + (resolved,)
                    _scan_file(resolved, depth + 1, new_set, new_path)
                continue

            # ---- Cross-skill reference ----
            if system_root:
                containing_skill = find_containing_skill(resolved, system_root)
                if (
                    containing_skill
                    and os.path.abspath(containing_skill) != skill_path
                ):
                    skill_name = os.path.basename(containing_skill)
                    errors.append(
                        f"{LEVEL_FAIL}: Cross-skill reference in "
                        f"'{_rel(filepath)}' line {line_num}: "
                        f"'{raw_ref}' points to skill '{skill_name}'. "
                        f"A bundle must be self-contained — it cannot "
                        f"reference other skills. Remove this reference "
                        f"or inline the needed content."
                    )
                    continue

            # ---- Cycle between external documents ----
            if resolved in ancestor_set:
                cycle_display = " -> ".join(
                    _rel(f) for f in ancestor_path + (resolved,)
                    if not is_within_directory(f, skill_path)
                )
                errors.append(
                    f"{LEVEL_FAIL}: Circular reference detected between "
                    f"external files: {cycle_display}. This is likely a "
                    f"bug — external documents should not form reference "
                    f"cycles."
                )
                continue

            # ---- Valid external dependency ----
            external_files.add(resolved)

            if resolved not in scanned_external:
                scanned_external.add(resolved)
                new_set = ancestor_set | frozenset({resolved})
                new_path = ancestor_path + (resolved,)
                _scan_file(resolved, depth + 1, new_set, new_path)

        if resolved_refs:
            reference_map[filepath] = resolved_refs

    def _rel(filepath: str) -> str:
        """Best-effort short display path with forward-slash separators."""
        filepath = os.path.abspath(filepath)
        if is_within_directory(filepath, skill_path):
            display = os.path.relpath(filepath, skill_path)
        elif system_root:
            display = os.path.relpath(filepath, system_root)
        else:
            display = filepath
        # Normalize separators for stable cross-platform diagnostics.
        return display.replace(os.sep, "/")

    # Scan every file in the skill directory tree, applying the same
    # exclude patterns and symlink traversal used during bundle copying
    # so that the set of scanned files matches what ends up in the bundle.
    boundary = skill_path if system_root is None else system_root
    visited_dirs: set[str] = set()

    for root, dirs, files in os.walk(skill_path, followlinks=True):
        real_root = os.path.realpath(root)
        if real_root in visited_dirs:
            # Already visited via another path; prevent descent but
            # still scan files under this alias.
            dirs[:] = []
        else:
            visited_dirs.add(real_root)

            dirs[:] = [
                d for d in dirs
                if not any(fnmatch.fnmatch(d, p) for p in exclude_patterns)
            ]

            # Skip symlinked directories that escape the allowed
            # boundary or whose resolved target has any path component
            # matching an exclude pattern (e.g. "docs -> .git").  This
            # mirrors _copy_skill() so the scanned file set matches
            # what ends up in the bundle.
            kept_dirs: list[str] = []
            for d in dirs:
                dir_path = os.path.join(root, d)
                if os.path.islink(dir_path):
                    real_target = os.path.realpath(dir_path)
                    if not is_within_directory(real_target, boundary):
                        continue
                    parts = os.path.normpath(real_target).split(os.sep)
                    if any(
                        any(fnmatch.fnmatch(part, p) for p in exclude_patterns)
                        for part in parts
                    ):
                        continue
                kept_dirs.append(d)
            dirs[:] = kept_dirs

        for filename in files:
            if any(fnmatch.fnmatch(filename, p) for p in exclude_patterns):
                continue
            filepath = os.path.join(root, filename)
            _scan_file(filepath, 0, frozenset(), ())

    return {
        "external_files": external_files,
        "errors": errors,
        "warnings": warnings,
        "reference_map": reference_map,
    }


# ===================================================================
# System Root Inference
# ===================================================================

def infer_system_root(skill_path: str) -> str | None:
    """Attempt to locate the skill system root from *skill_path*.

    Walks up looking for ``manifest.yaml`` or a ``skills/`` parent
    directory.  Returns the inferred root (absolute) or ``None``.
    """
    skill_path = os.path.abspath(skill_path)
    current = os.path.dirname(skill_path)

    for _ in range(BUNDLE_INFER_MAX_WALK_DEPTH):
        if not current or current == os.path.dirname(current):
            break

        # Check for manifest file at this level
        if os.path.exists(os.path.join(current, FILE_MANIFEST)):
            return current

        # Check if this directory contains a skills/ subdirectory
        # and our skill is under it
        skills_dir = os.path.join(current, DIR_SKILLS)
        if os.path.isdir(skills_dir) and is_within_directory(skill_path, skills_dir):
            return current

        current = os.path.dirname(current)

    return None


# ===================================================================
# Bundle Path Computation
# ===================================================================

def classify_external_file(filepath: str, system_root: str | None) -> str:
    """Determine the bundle subdirectory for an external file.

    Returns one of the standard directory names: ``'roles'``,
    ``'references'``, ``'assets'``, or ``'scripts'``.
    """
    if not system_root:
        return DIR_REFERENCES

    filepath = os.path.abspath(filepath)
    system_root = os.path.abspath(system_root)
    rel = os.path.relpath(filepath, system_root)
    parts = rel.split(os.sep)

    if parts[0] == DIR_ROLES:
        return DIR_ROLES
    if parts[0] == DIR_ASSETS:
        return DIR_ASSETS
    if parts[0] == DIR_SCRIPTS:
        return DIR_SCRIPTS

    return DIR_REFERENCES


def compute_bundle_path(external_file: str, system_root: str | None) -> str:
    """Compute the target path for an external file within the bundle.

    Roles preserve their full group structure under ``roles/``.
    Other files are placed in the appropriate standard directory.

    Returns a relative path (e.g. ``roles/engineering/release-manager.md``).
    """
    external_file = os.path.abspath(external_file)
    category = classify_external_file(external_file, system_root)

    if system_root and category == DIR_ROLES:
        roles_dir = os.path.join(os.path.abspath(system_root), DIR_ROLES)
        rel = os.path.relpath(external_file, roles_dir)
        return os.path.join(DIR_ROLES, rel).replace(os.sep, "/")

    # For non-role files, place in the category directory.  If the source
    # path has meaningful sub-structure (e.g. assets/templates/foo.md),
    # preserve the full relative path under the category directory.
    if system_root:
        system_root = os.path.abspath(system_root)
        category_dir = os.path.join(system_root, category)
        if is_within_directory(external_file, category_dir):
            rel = os.path.relpath(external_file, category_dir)
            return os.path.join(category, rel).replace(os.sep, "/")

    filename = os.path.basename(external_file)
    return os.path.join(category, filename).replace(os.sep, "/")
