"""Reference scanning, resolution, and graph traversal for skill bundling.

Extracts file references from skill content, resolves them to absolute
paths, and traverses the reference graph to identify all external
dependencies.  Detects cross-skill references, cycles between external
documents, and broken links.

Consumers import the public functions:
    from lib.references import scan_references, compute_bundle_path
"""

import os
import re

from .constants import (
    DIR_SKILLS, DIR_ROLES, DIR_REFERENCES, DIR_ASSETS, DIR_SCRIPTS,
    FILE_SKILL_MD,
    BUNDLE_MAX_REFERENCE_DEPTH,
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

def is_binary_file(filepath):
    """Check if a file is likely binary based on its extension."""
    _, ext = os.path.splitext(filepath)
    return ext.lower() in BINARY_EXTENSIONS


def is_markdown_file(filepath):
    """Check if a file is a markdown file."""
    return filepath.lower().endswith(EXT_MARKDOWN)


def is_within_directory(filepath, directory):
    """Check whether *filepath* is inside (or equal to) *directory*."""
    filepath = os.path.abspath(filepath)
    directory = os.path.abspath(directory)
    # Trailing sep avoids false matches like /foo/bar vs /foo/barbaz
    return filepath == directory or filepath.startswith(directory + os.sep)


# ===================================================================
# Reference Extraction
# ===================================================================

def extract_references(filepath):
    """Extract file references from a single file.

    For markdown files, extracts markdown-link and backtick references.
    For other text files, performs best-effort detection of paths.

    Returns a list of tuples:
        (reference_path: str, line_number: int, ref_type: str)

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
            for match in RE_BUNDLE_MD_LINK.finditer(line):
                ref_path = match.group(2)
                refs.append((ref_path, line_num, "markdown_link"))
            # Backtick refs — avoid duplicating paths already captured
            seen_in_line = {r[0] for r in refs if r[1] == line_num}
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


def _filter_refs(refs):
    """Remove URLs, anchors, template placeholders, and obvious non-paths."""
    filtered = []
    for ref_path, line_num, ref_type in refs:
        # Skip URLs
        if ref_path.startswith(("http://", "https://", "mailto:", "ftp://")):
            continue
        # Skip anchors
        if ref_path.startswith("#"):
            continue
        # Skip template placeholders like <file>
        if "<" in ref_path or ">" in ref_path:
            continue
        # Skip empty
        if not ref_path.strip():
            continue
        filtered.append((ref_path, line_num, ref_type))
    return filtered


# ===================================================================
# Path Resolution
# ===================================================================

def resolve_reference(ref_path, source_file, system_root=None):
    """Resolve a reference path to an absolute filesystem path.

    Tries in order:
      1. Relative to the source file's directory
      2. Relative to the system root (if provided)

    Returns the absolute path if found, ``None`` otherwise.
    """
    source_dir = os.path.dirname(os.path.abspath(source_file))

    # Try relative to the source file
    candidate = os.path.normpath(os.path.join(source_dir, ref_path))
    if os.path.exists(candidate):
        return candidate

    # Try relative to the system root
    if system_root:
        candidate = os.path.normpath(os.path.join(system_root, ref_path))
        if os.path.exists(candidate):
            return candidate

    return None


def find_containing_skill(filepath, system_root):
    """Find which skill directory contains *filepath*.

    Walks up from the file looking for a ``SKILL.md``.  Returns the
    skill directory (absolute) or ``None`` if *filepath* is not inside
    any skill under *system_root*.
    """
    filepath = os.path.abspath(filepath)
    system_root = os.path.abspath(system_root)

    current = os.path.dirname(filepath)
    while current.startswith(system_root) and len(current) > len(system_root):
        if os.path.exists(os.path.join(current, FILE_SKILL_MD)):
            return current
        current = os.path.dirname(current)

    return None


# ===================================================================
# Reference Graph Traversal
# ===================================================================

def scan_references(skill_path, system_root=None, max_depth=None):
    """Scan a skill's full reference graph for external dependencies.

    Traverses all files in *skill_path*, finds external references,
    and recursively scans those files for further references.

    Args:
        skill_path:   Absolute path to the skill directory.
        system_root:  Optional system root (contains ``skills/``,
                      ``roles/``).  When omitted, inferred by walking
                      up from *skill_path*.
        max_depth:    Maximum transitive reference depth.  Defaults to
                      ``BUNDLE_MAX_REFERENCE_DEPTH`` from config.

    Returns a dict::

        {
            'external_files': set of absolute paths,
            'errors':         list of FAIL/WARN strings,
            'warnings':       list of WARN strings,
            'reference_map':  {source_path: [(ref, line, type, resolved), ...]},
        }
    """
    if max_depth is None:
        max_depth = BUNDLE_MAX_REFERENCE_DEPTH

    skill_path = os.path.abspath(skill_path)
    if system_root:
        system_root = os.path.abspath(system_root)
    else:
        system_root = infer_system_root(skill_path)

    external_files = set()
    errors = []
    warnings = []
    reference_map = {}

    # External files whose subtrees have been fully traversed.
    scanned_external = set()

    def _scan_file(filepath, depth, ancestor_externals):
        """Recursively scan *filepath* and classify its references."""
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

        resolved_refs = []

        for ref_path, line_num, ref_type in refs:
            resolved = resolve_reference(ref_path, filepath, system_root)
            resolved_refs.append((ref_path, line_num, ref_type, resolved))

            # ---- Broken reference ----
            if resolved is None:
                errors.append(
                    f"{LEVEL_FAIL}: Broken reference in "
                    f"'{_rel(filepath)}' line {line_num}: "
                    f"'{ref_path}' does not resolve to any existing file. "
                    f"Fix the reference path before bundling."
                )
                continue

            # ---- Internal (within the skill) ----
            if is_within_directory(resolved, skill_path):
                continue

            # ---- Non-markdown detected reference (warn only) ----
            if ref_type == "text_detected":
                warnings.append(
                    f"{LEVEL_WARN}: Non-markdown file reference detected in "
                    f"'{_rel(filepath)}' line {line_num}: '{ref_path}'. "
                    f"This reference will not be automatically rewritten "
                    f"in the bundle. You may need to update it manually."
                )
                external_files.add(resolved)
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
                        f"'{ref_path}' points to skill '{skill_name}'. "
                        f"A bundle must be self-contained — it cannot "
                        f"reference other skills. Remove this reference "
                        f"or inline the needed content."
                    )
                    continue

            # ---- Cycle between external documents ----
            if resolved in ancestor_externals:
                cycle_display = " -> ".join(
                    _rel(f)
                    for f in list(ancestor_externals) + [resolved]
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
                new_ancestors = ancestor_externals | frozenset({resolved})
                _scan_file(resolved, depth + 1, new_ancestors)

        if resolved_refs:
            reference_map[filepath] = resolved_refs

    def _rel(filepath):
        """Best-effort short display path."""
        filepath = os.path.abspath(filepath)
        if is_within_directory(filepath, skill_path):
            return os.path.relpath(filepath, skill_path)
        if system_root:
            return os.path.relpath(filepath, system_root)
        return filepath

    # Scan every file in the skill directory tree.
    for root, _dirs, files in os.walk(skill_path):
        for filename in files:
            filepath = os.path.join(root, filename)
            _scan_file(filepath, 0, frozenset())

    return {
        "external_files": external_files,
        "errors": errors,
        "warnings": warnings,
        "reference_map": reference_map,
    }


# ===================================================================
# System Root Inference
# ===================================================================

def infer_system_root(skill_path):
    """Attempt to locate the skill system root from *skill_path*.

    Walks up looking for ``manifest.yaml`` or a ``skills/`` parent
    directory.  Returns the inferred root (absolute) or ``None``.
    """
    skill_path = os.path.abspath(skill_path)
    current = os.path.dirname(skill_path)

    # Walk up at most 5 levels (avoid scanning to filesystem root).
    for _ in range(5):
        if not current or current == os.path.dirname(current):
            break

        # Check for manifest.yaml at this level
        if os.path.exists(os.path.join(current, "manifest.yaml")):
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

def classify_external_file(filepath, system_root):
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


def compute_bundle_path(external_file, system_root):
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
        return os.path.join(DIR_ROLES, rel)

    # For non-role files, place in the category directory with the
    # original filename.  If the source path has meaningful sub-structure
    # (e.g. assets/templates/foo.md), preserve one level.
    if system_root:
        system_root = os.path.abspath(system_root)
        category_dir = os.path.join(system_root, category)
        if is_within_directory(external_file, category_dir):
            rel = os.path.relpath(external_file, category_dir)
            return os.path.join(category, rel)

    filename = os.path.basename(external_file)
    return os.path.join(category, filename)
