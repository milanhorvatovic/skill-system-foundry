"""Reference scanning, resolution, and graph traversal for skill bundling.

Extracts file references from skill content, resolves them to absolute
paths, and traverses the reference graph to identify all external
dependencies.  Detects cross-skill references, cycles between external
documents, and broken links.
"""

import fnmatch
import os
import re
from collections.abc import Generator
from typing import Literal, TypedDict

from .constants import (
    DIR_SKILLS, DIR_ROLES, DIR_REFERENCES, DIR_ASSETS, DIR_SCRIPTS,
    DIR_CAPABILITIES,
    FILE_SKILL_MD, FILE_MANIFEST,
    BUNDLE_MAX_REFERENCE_DEPTH,
    BUNDLE_EXCLUDE_PATTERNS,
    BUNDLE_INFER_MAX_WALK_DEPTH,
    DEGRADED_SYMLINK_MAX_BYTES,
    LEVEL_FAIL, LEVEL_WARN,
    EXT_MARKDOWN,
    RE_DEGRADED_SYMLINK,
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
# Built from DIR_* constants so new prefixes are picked up automatically.
# Uses re.escape so prefix values are never interpreted as metacharacters,
# and a lookbehind so that "myreferences/foo.md" does not falsely match
# as "references/foo.md".
_TEXT_REF_PREFIXES = "|".join([
    re.escape(DIR_REFERENCES), re.escape(DIR_SCRIPTS),
    re.escape(DIR_ASSETS), re.escape(DIR_ROLES),
    re.escape(DIR_CAPABILITIES), re.escape(DIR_SKILLS),
])
RE_TEXT_FILE_REF = re.compile(
    r"(?:(?<=^)|(?<=[^\w/]))"    # start-of-line or preceded by non-word, non-path char
    r"(?:" + _TEXT_REF_PREFIXES + r")"
    r"/[^\s'\"`,;:)}\]>]+",
    re.MULTILINE,
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

    Dangling-symlink note: on Windows, ``os.path.realpath`` cannot
    fully canonicalise a path whose final component is a symlink to
    a non-existent target — Python falls back to a partially
    resolved string that still contains the unexpanded short-name
    component (e.g. ``RUNNER~1``), while ``realpath(directory)`` for
    an existing directory expands to the long-name form
    (``runneradmin``).  The two paths then diverge under
    ``normcase`` and ``commonpath`` returns a shallow parent, so the
    function would falsely classify a dangling symlink inside the
    directory as external.  Detect that case explicitly: a path
    that is a dangling symlink is judged by its own literal
    abspath, not its (unreachable) target — both *filepath* and
    *directory* are compared in ``abspath`` form so they share the
    same level of canonicalisation.
    """
    if os.path.islink(filepath) and not os.path.exists(filepath):
        # Dangling symlink — judge by the link's literal location
        # rather than the partially-resolved target.  Use
        # ``abspath`` on both sides so neither side is more
        # canonicalised than the other.
        filepath_norm = os.path.normcase(os.path.abspath(filepath))
        directory_norm = os.path.normcase(os.path.abspath(directory))
    else:
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

_GLOB_METACHARS = "*?[]{}"
# The boundary regex must recognize ANY extension-shaped suffix —
# not just the ones configured in
# ``path_resolution.reference_extensions``.  Directory-anchored
# captures from ``markdown_link`` (and every ``backtick`` capture)
# legitimately accept arbitrary extensions for asset and shared-
# resource links (``assets/logo.svg?v=2``, ``shared/photo.png``).
# If the boundary regex restricted itself to the configured list,
# such a link would have no extension match — ``path_part`` would
# fall back to the whole reference and a query/title ``?`` would
# be misclassified as a glob, dropping the link from validation,
# conformance, and ``--fix``.  Match ``.<word-chars>`` followed by
# the actual suffix boundary (``?``, ``#``, whitespace, or end of
# string) so the discriminator works on every shape the extractors
# capture.  ``[A-Za-z0-9_]+`` is broad enough for every realistic
# extension while still guaranteeing at least one char between the
# leading ``.`` and the boundary, which prevents matching the bare
# ``.`` in path segments like ``./foo``.
_EXT_FRAGMENT_BOUNDARY_RE = re.compile(r"\.[A-Za-z0-9_]+([?#\s]|$)")


def is_glob_path(ref: str) -> bool:
    """Return True when *ref* contains glob metacharacters in its
    filesystem-path portion.

    Glob metacharacters are ``*``, ``?``, ``[``, ``]``, ``{``, ``}``.
    ``?`` is the tricky one: it is also a markdown link query
    separator (``foo.md?v=2``) and can appear inside a markdown link
    title (``foo.md "Why?"``), both of which the rewriter and the
    extractor explicitly preserve.  A simple "any ``?`` is glob"
    rule rejects all three legitimate forms.

    Discriminator: a markdown link's path ends at the first ``?``,
    ``#``, or whitespace that follows a recognized file extension,
    or at end of string.  Anything before that boundary is the path;
    anything after is the suffix (query, anchor, or title
    annotation).  Glob metachars inside the path portion register;
    the same characters in the suffix are part of the query/anchor/
    title and stay benign.

    Examples:
    - ``references/?ref.md`` — the ``?`` is *before* the extension,
      so the path portion is the whole string and the ``?`` counts
      as glob.
    - ``guide.md?v=2`` — boundary at ``?`` after ``.md``, path is
      ``guide.md``, no glob metachars.
    - ``guide.md "Why?"`` — boundary at the space after ``.md``,
      path is ``guide.md``, no glob metachars (the ``?`` lives in
      the title and is irrelevant).
    - ``capabilities/**/*.md`` — extension at end with no boundary
      character, whole string is path, ``*`` flags as glob.
    """
    m = _EXT_FRAGMENT_BOUNDARY_RE.search(ref)
    path_part = ref[: m.start(1)] if m else ref
    return any(c in path_part for c in _GLOB_METACHARS)


def is_drive_qualified(path: str) -> bool:
    """Return True when *path* is a Windows drive-qualified path.

    Catches forms like ``C:foo.md``, ``C:/foo.md``, and ``C:\\foo.md``
    on every platform — ``os.path.splitdrive`` is platform-dependent
    (returns ``('', '...')`` on POSIX), so a check that relies on it
    silently misclassifies these references as ordinary relative
    filenames when validation runs on Linux CI.  The foundry runs on
    both Ubuntu and Windows in CI, so the drive-qualified check must
    be platform-independent to keep the validation surface
    consistent.
    """
    if len(path) < 2:
        return False
    # Restrict to ASCII ``[A-Za-z]`` to match the markdown-link
    # extractor's drive-qualified alternative (``[A-Za-z]:...``) and
    # the Windows drive-letter convention itself.  ``str.isalpha``
    # accepts non-ASCII letters (``Ω``, ``Ä``, hundreds of Unicode
    # code points), which would misclassify legitimate relative
    # filenames like ``Ω:notes.md`` as drive-qualified and emit a
    # spurious WARN / silent skip.  Drive letters are ASCII only.
    first = path[0]
    is_ascii_letter = ("A" <= first <= "Z") or ("a" <= first <= "z")
    return is_ascii_letter and path[1] == ":"


def is_dangling_symlink(path: str) -> bool:
    """Return True when *path* is a symlink whose target does not exist.

    On Linux/macOS a real symlink whose target was deleted falls
    here.  ``os.path.islink`` returns True for the link, but
    ``os.path.exists`` follows the link and reports False — the
    classic dangling-symlink shape.  The companion existence check
    keeps a live link (target present) out of the True branch.
    """
    return os.path.islink(path) and not os.path.exists(path)


# Windows-without-Developer-Mode degraded-symlink heuristic.  A git
# checkout on Windows that lacks symlink support stores the would-be
# symlink as a small plain text file whose entire body is the
# relative target the link would have resolved to.  The validator
# cannot use ``os.path.islink`` to detect this — the file is a real
# regular file by then.  Instead, we recognise the shape: small file,
# valid UTF-8, content is a single relative-looking path ending in
# one of the foundry's reference extensions.  Recognised forms
# produce the same actionable WARN as a true dangling symlink so the
# integrator is pointed at the right fix (Developer Mode or
# core.symlinks=true) instead of the generic "file does not exist"
# diagnostic.
#
# The pattern accepts three shim shapes git produces:
#   1. Bare-name target — ``ln -s sibling.md link.md`` stores
#      ``sibling.md`` verbatim (no leading slash or dot).  This is
#      the most common foundry shape (e.g., ``CLAUDE.md → AGENTS.md``).
#   2. Dot-relative target — ``ln -s ./bar.md`` and
#      ``ln -s ../bar.md`` store with the explicit dot prefix.
#   3. Multi-component relative target — ``ln -s sub/dir/foo.md``
#      stores as ``sub/dir/foo.md`` (forward or back slashes).
#
# Absolute-looking paths (``/foo.md``) are intentionally NOT
# accepted: git symlinks are stored as relative targets, so a
# leading slash with no dots indicates a non-shim file.  The
# optional prefix therefore requires 1-2 dots before the slash, not
# 0-2 — a path like ``/missing.md`` that happens to live in a
# small file is left to the existing broken-link diagnostic.
#
# Tunables (``max_bytes`` and the trailing extension allow-list)
# live in ``configuration.yaml`` under
# ``path_resolution.degraded_symlink``; ``constants.py`` validates
# and exposes them as ``DEGRADED_SYMLINK_MAX_BYTES`` and
# ``RE_DEGRADED_SYMLINK``.  The pattern shape (optional dot-relative
# prefix, multi-component, single-line) stays in code because it is
# structural rather than tunable.


def looks_like_degraded_symlink(path: str) -> bool:
    """Return True when *path* looks like a Windows-without-DevMode shim.

    Two-stage heuristic:

    1. Shape match — *path* must be a small file (<=
       ``DEGRADED_SYMLINK_MAX_BYTES``), valid UTF-8, with single-line
       content matching ``RE_DEGRADED_SYMLINK`` (see the
       constant for the recognised shim shapes and the foundry
       extension allow-list).
    2. Broken-target confirmation — the captured path, resolved
       relative to *path*'s parent directory, must NOT point to an
       existing file.

    The second stage is what distinguishes a Windows-without-DevMode
    shim (where git stored the would-be link's target as a small text
    file because the underlying symlink could not be created, so the
    target is not actually present) from a deliberate one-line
    markdown note (where the captured path resolves to a real file
    the author wanted to point at).  Without it, a stub
    ``references/see-also.md`` containing nothing but
    ``./full-content.md`` would be misclassified as a degraded
    symlink even though the pointer is intact.

    Trade-off: a Windows-without-DevMode shim whose target is also
    present on disk (e.g. ``CLAUDE.md`` whose body is ``AGENTS.md``
    when ``AGENTS.md`` exists alongside) flows through the
    "deliberate one-line note" branch and is NOT flagged.  This is
    a deliberate choice — without an external signal (git history,
    a per-file ``core.symlinks`` flag) there is no way to tell a
    real degraded shim apart from a one-line content reference.
    Reviewers have surfaced the case (e.g. PR #139, Codex Review on
    ``references.py:327``); the current verdict is that
    false-positives on deliberate one-line references would be
    worse than false-negatives on a narrow degraded-shim shape that
    the validator's other rules (broken-link, case-exact, long-
    path) already handle when the integrator edits the shim's
    content or moves files.

    Returns False on read failures, on files larger than the size
    cap, on files whose body is not valid UTF-8, on files whose
    content does not match the single-relative-path shape, and on
    files where the captured path resolves to an existing file
    (i.e., real one-line markdown notes — see the trade-off above).

    The companion ``looks_like_ambiguous_one_line_shim`` returns
    True for the inverse case (shape match + target exists), so
    the validator can surface an INFO inviting the author to
    verify on a fresh Windows-without-DevMode clone.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size == 0 or size > DEGRADED_SYMLINK_MAX_BYTES:
        return False
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    body = text.strip()
    if not body or "\n" in body or "\r" in body:
        return False
    # Reject drive-qualified absolute paths (``C:foo.md``,
    # ``C:\foo.md``) before the shape regex.  Git symlinks are
    # stored as relative targets, so a Windows-absolute path is
    # never a real shim — but the regex's first-component class
    # accepts ``:`` and treats ``\`` as a separator, so a small
    # file containing ``C:\missing.md`` would otherwise pass the
    # shape gate and produce a misleading WARN.
    if is_drive_qualified(body):
        return False
    if not RE_DEGRADED_SYMLINK.match(body):
        return False
    # Broken-target confirmation: a real degraded symlink's captured
    # path does not resolve to an existing file (the symlink was
    # never materialised).  A deliberate one-line note's captured
    # path does resolve — keep that case out of the True branch.
    parent = os.path.dirname(os.path.abspath(path))
    candidate = os.path.normpath(
        os.path.join(parent, body.replace("\\", "/"))
    )
    if os.path.exists(candidate):
        return False
    return True


def looks_like_ambiguous_one_line_shim(path: str) -> bool:
    """Return True when *path* matches a shim shape AND target exists.

    The companion to ``looks_like_degraded_symlink``: same shape
    gate (small file, valid UTF-8, single-line content matching
    ``RE_DEGRADED_SYMLINK``), but the captured target *does*
    resolve to an existing file.  Two causes are byte-identical:

    1. A Git-degraded symlink shim where the target also happens
       to exist on disk (e.g. ``CLAUDE.md`` shim containing
       ``AGENTS.md`` when ``AGENTS.md`` is a sibling).  The
       checkout has a regular file where a symlink was expected.
    2. A deliberate one-line content reference (e.g.
       ``references/see-also.md`` whose body is
       ``./full-content.md``).  Authored content, not a shim.

    Without an out-of-band signal (git history, a
    ``core.symlinks`` per-file marker) the validator cannot
    distinguish (1) from (2).  Surface the case at INFO severity
    so the author investigates without the validator forcing a
    false-positive WARN on legitimate one-line references.

    Returns False on the same conditions as
    ``looks_like_degraded_symlink`` (read failure, oversize, bad
    UTF-8, multi-line, non-shim shape) AND on files whose
    captured target does NOT exist (those are handled by the
    "broken-target" branch of the degraded check).
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size == 0 or size > DEGRADED_SYMLINK_MAX_BYTES:
        return False
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    body = text.strip()
    if not body or "\n" in body or "\r" in body:
        return False
    # Reject drive-qualified absolute paths for the same reason as
    # ``looks_like_degraded_symlink`` — see that helper for the
    # rationale.
    if is_drive_qualified(body):
        return False
    if not RE_DEGRADED_SYMLINK.match(body):
        return False
    parent = os.path.dirname(os.path.abspath(path))
    candidate = os.path.normpath(
        os.path.join(parent, body.replace("\\", "/"))
    )
    return os.path.exists(candidate)


def resolve_case_exact(
    skill_root: str,
    ref_path: str,
    *,
    listdir_cache: dict[str, list[str]] | None = None,
) -> tuple[bool, str | None, list[str] | None]:
    """Resolve *ref_path* against *skill_root* with byte-exact case.

    On case-insensitive filesystems (NTFS, default macOS HFS+/APFS)
    ``os.path.exists`` returns True for any case match — a markdown
    link that points to ``References/foo.md`` resolves on Windows and
    on macOS, but 404s on Linux.  This helper walks the path
    component-by-component, listing each parent directory and
    requiring an exact match against the on-disk basename so the
    case-divergence bug is caught at validation time on every host.

    Parameters:

    - *skill_root* — absolute path to the skill root the reference is
      anchored against.  Must already exist.
    - *ref_path* — absolute path produced by joining the source file
      directory with the reference target and normpath-ing the
      result.  The helper does not normalise here; callers pass the
      same path they would otherwise pass to ``os.path.exists``.
    - *listdir_cache* — optional dict that callers can pass in to
      amortise ``os.listdir`` calls across many resolutions in the
      same validation pass.  When supplied, the helper consults the
      cache (keyed by absolute directory path) before issuing a
      syscall and stores the result for subsequent lookups.  A skill
      with N references M components deep without the cache costs
      N·M listdirs; with the cache it costs at most one listdir per
      unique directory the reference graph touches.  The cache is
      not read concurrently; safe to share within a single pass.
      Cache keys are absolute path strings as composed by
      ``os.path.join``; aliases reached via different symlink paths
      produce different cache entries even when they resolve to the
      same physical directory.  The redundancy does not affect
      correctness — both keys list the same content — but the cache
      is less effective on skills that lean on internal-symlink
      aliases for naming.

    Returns a ``(case_ok, suggested, collisions)`` triple:

    * ``(True, None, None)`` — path resolves with byte-exact case at
      every component.
    * ``(False, suggested_path, None)`` — basename matches
      case-insensitively at every component and there is exactly
      one on-disk candidate per component; *suggested_path* is the
      on-disk-correct form so the finding can name the fix.
    * ``(False, None, candidates)`` — at some component, multiple
      on-disk entries match case-insensitively (legal on Linux,
      impossible on Windows/macOS default).  The previous
      implementation kept an arbitrary survivor by overwriting a
      ``{e.lower(): e}`` map during iteration; the resulting
      "actual path is …" suggestion was nondeterministic and could
      point at the wrong file.  Surface the collision instead by
      returning the candidate list (sorted, slash-joined to that
      component) so the caller can render a deterministic finding.
    * ``(False, None, None)`` — path does not exist under any
      casing.

    Symlinks are treated as case-significant for their own basename
    (the link itself must match exactly) and the helper does not
    follow them; the caller's existence check decides whether a
    matching link with a missing target is reported as dangling.
    """
    abs_root = os.path.abspath(skill_root)
    abs_ref = os.path.abspath(ref_path)
    try:
        rel = os.path.relpath(abs_ref, abs_root)
    except ValueError:
        # Different drives on Windows — not under skill_root, so we
        # cannot apply the case rule meaningfully; defer to existence.
        return os.path.exists(abs_ref), None, None
    parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
    # Out-of-root check: only treat the path as escaping when the
    # FIRST segment is exactly ``..`` — a string-prefix
    # ``rel.startswith("..")`` test would falsely reject in-tree
    # paths whose first component happens to start with the two
    # characters (``..hidden/guide.md``).
    if parts and parts[0] == "..":
        return os.path.exists(abs_ref), None, None
    if not parts:
        return True, None, None
    cursor = abs_root
    suggested_parts: list[str] = []
    case_diverged = False
    for part in parts:
        if listdir_cache is not None and cursor in listdir_cache:
            entries = listdir_cache[cursor]
        else:
            try:
                entries = os.listdir(cursor)
            except OSError:
                return False, None, None
            if listdir_cache is not None:
                listdir_cache[cursor] = entries
        # Collect every entry that matches case-insensitively.  Done
        # BEFORE the exact-match fast path because an exact match
        # alongside a case-different sibling (legal on Linux) is
        # still a collision the bundle cannot represent on
        # Windows/macOS — accepting the exact spelling here would
        # let an unrepresentable tree pass validation.  A
        # case-insensitive filesystem (Windows, macOS default) by
        # definition cannot have multiple matches, so this branch
        # only fires on case-sensitive Linux when the author has
        # written sibling files differing only in case.
        actual_matches = [
            e for e in entries if e.lower() == part.lower()
        ]
        if len(actual_matches) > 1:
            # Surface the collision as a separate return shape so
            # the caller can render a deterministic finding rather
            # than an arbitrary "actual path is …" suggestion.
            collision_prefix = "/".join(suggested_parts)
            collision_candidates = sorted(
                f"{collision_prefix}/{m}" if collision_prefix else m
                for m in actual_matches
            )
            return False, None, collision_candidates
        if part in entries:
            # Exact match with no case-different siblings — fast path.
            suggested_parts.append(part)
            cursor = os.path.join(cursor, part)
            continue
        if not actual_matches:
            return False, None, None
        actual = actual_matches[0]
        suggested_parts.append(actual)
        cursor = os.path.join(cursor, actual)
        case_diverged = True
    if not case_diverged:
        return True, None, None
    return False, "/".join(suggested_parts), None


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
    if path.startswith(("http://", "https://", "#", "mailto:", "ftp://", "file://")):
        return True

    if "<" in path or ">" in path:
        # Allow markdown-wrapped local paths: <path/to/file.md> "Title"
        if RE_WRAPPED_LOCAL_REF.match(path):
            # Unwrap and re-check for URL schemes inside the brackets
            # so that autolinks like <https://example.com> are skipped.
            inner = path.split("<", 1)[1].split(">", 1)[0].strip()
            if inner.startswith(("http://", "https://", "mailto:", "ftp://", "file://")):
                return True
            return False
        return True

    return False


# Type aliases for reference tuples
ReferenceType = Literal["markdown_link", "backtick", "text_detected"]
ResolveFailReason = Literal["absolute_path", "escapes_system_root", "is_directory", "not_found"]
RawRef = tuple[str, int, ReferenceType]  # (ref_path, line_num, ref_type)
FilteredRef = tuple[str, str, int, ReferenceType]  # (raw_ref, clean_path, line_num, ref_type)
ResolvedRef = tuple[str, int, ReferenceType, str | None]  # (raw_ref, line_num, ref_type, resolved)


class ScanResult(TypedDict):
    """Structured output of ``scan_references()``."""

    external_files: set[str]
    errors: list[str]
    warnings: list[str]
    reference_map: dict[str, list[ResolvedRef]]
    # Skill directories to inline as capabilities.  Always present;
    # empty when ``inline_orchestrated_skills`` is ``False``.
    # Keys are absolute path directories on the lexical system_root
    # basis (i.e. realpath re-expressed through the user-supplied
    # system_root so they share the same path basis as the coordinator
    # and external files — not necessarily realpath).
    inlined_skills: dict[str, str]  # {abs_skill_dir: skill_name}
    # Alias roots observed for inlined skills.  Each entry maps an
    # alias directory (e.g. a symlink) to the primary skill directory
    # already recorded in ``inlined_skills``, expressed on the same
    # system_root-based absolute path basis (not necessarily realpath).
    # Consumers use this to add rewrite-map entries for alias-path
    # references.
    inlined_skill_aliases: list[tuple[str, str]]  # [(alias_abs, primary_abs)]


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

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

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
      1. Relative to the source file's directory (the canonical
         file-relative form per ``references/path-resolution.md``)
      2. Relative to the system root (transitional fallback for
         skills that have not yet migrated to file-relative paths;
         documented as ``--fix``-eligible so the validator can
         rewrite them to the canonical form)

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
      - ``"is_directory"``
      - ``"not_found"``

    Resolution order is source-relative first, then system-root-relative
    as a transitional fallback.  The two coincide under the redefined
    path-resolution rule for any file that uses the canonical form;
    the fallback only exercises for legacy skill-root-relative paths
    that the bundle should still handle gracefully during integrator
    migration.

    TODO(post-migration): drop the system-root fallback once integrator
    skills run ``validate_skill.py --fix`` and pass
    ``reference_conformance_report.py``.  At that point bundle and
    validator share a single resolution rule and the fallback below
    becomes vestigial.
    """
    # Reject absolute and drive-qualified paths — references must be
    # relative.  On Windows, ``C:foo/bar`` is drive-relative and is
    # *not* caught by ``os.path.isabs()``, but ``os.path.join()``
    # treats it as rooted on that drive, effectively bypassing the
    # relative-only rule.  ``is_drive_qualified`` provides
    # platform-independent detection of the ``C:...`` form;
    # ``os.path.splitdrive`` would only catch it on Windows because
    # ``os.path`` is host-dependent.
    if os.path.isabs(ref_path) or is_drive_qualified(ref_path):
        return None, "absolute_path"

    source_dir = os.path.dirname(os.path.abspath(source_file))
    source_candidate = os.path.normpath(os.path.join(source_dir, ref_path))

    if system_root and not is_within_directory(source_candidate, system_root):
        return None, "escapes_system_root"

    # Try relative to the source file
    candidate = source_candidate
    if os.path.isfile(candidate):
        return candidate, None
    if os.path.isdir(candidate):
        return None, "is_directory"

    # Try relative to the system root
    if system_root:
        candidate = os.path.normpath(os.path.join(system_root, ref_path))
        if not is_within_directory(candidate, system_root):
            return None, "escapes_system_root"

        if os.path.isfile(candidate):
            return candidate, None
        if os.path.isdir(candidate):
            return None, "is_directory"

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
# Skill Directory Traversal
# ===================================================================

def should_exclude(name: str, exclude_patterns: list[str]) -> bool:
    """Check if a filename or directory name matches any exclude pattern."""
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


class BoundaryViolation:
    """A symlink that escapes the allowed boundary."""

    def __init__(self, link_path: str, real_target: str, kind: str) -> None:
        self.link_path = link_path
        self.real_target = real_target
        self.kind = kind


def walk_skill_files(
    skill_path: str,
    exclude_patterns: list[str],
    boundary: str,
    boundary_violations: list[BoundaryViolation] | None = None,
) -> Generator[tuple[str, str], None, None]:
    """Yield ``(root, filename)`` pairs for eligible files in a skill tree.

    Walks *skill_path* with ``followlinks=True``, applying:
    - exclude-pattern filtering on directory and file names
    - symlink cycle detection via ancestry tracking
    - symlink boundary enforcement (targets must stay within *boundary*)
    - exclude-pattern filtering on symlink target path components

    When *boundary_violations* is a list, symlink violations are recorded
    there and the offending entry is silently skipped.  When it is ``None``,
    a ``ValueError`` is raised on the first violation (suitable for the
    copy phase where prevalidation has already cleared the tree).
    """

    root_ancestors: dict[str, frozenset[str]] = {
        skill_path: frozenset({os.path.realpath(skill_path)})
    }

    for root, dirs, files in os.walk(skill_path, followlinks=True):
        ancestors = root_ancestors.get(
            root, frozenset({os.path.realpath(root)})
        )

        # Filter excluded directory names in-place
        dirs[:] = [
            d for d in dirs
            if not should_exclude(d, exclude_patterns)
        ]

        # Filter symlinked directories: cycle, boundary, excluded targets
        kept_dirs: list[str] = []
        for d in dirs:
            dir_path = os.path.join(root, d)
            real_target = os.path.realpath(dir_path)
            if os.path.islink(dir_path):
                if real_target in ancestors:
                    continue
                if not is_within_directory(real_target, boundary):
                    if boundary_violations is not None:
                        boundary_violations.append(
                            BoundaryViolation(dir_path, real_target, "directory")
                        )
                    else:
                        rel = os.path.relpath(dir_path, skill_path).replace(os.sep, "/")
                        raise ValueError(
                            f"Symlinked directory escapes allowed boundary "
                            f"rooted at '{boundary}': "
                            f"'{rel}' -> '{real_target}'. "
                            f"Remove or replace the symlink before bundling."
                        )
                    continue
                parts = os.path.normpath(real_target).split(os.sep)
                if any(should_exclude(p, exclude_patterns) for p in parts):
                    continue
            root_ancestors[dir_path] = ancestors | frozenset({real_target})
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for filename in files:
            if should_exclude(filename, exclude_patterns):
                continue
            filepath = os.path.join(root, filename)

            if os.path.islink(filepath):
                real_target = os.path.realpath(filepath)
                if not is_within_directory(real_target, boundary):
                    if boundary_violations is not None:
                        boundary_violations.append(
                            BoundaryViolation(filepath, real_target, "file")
                        )
                    else:
                        rel = os.path.relpath(filepath, skill_path).replace(os.sep, "/")
                        raise ValueError(
                            f"Symlinked file escapes allowed boundary "
                            f"rooted at '{boundary}': "
                            f"'{rel}' -> '{real_target}'. "
                            f"Remove or replace the symlink before bundling."
                        )
                    continue
                parts = os.path.normpath(real_target).split(os.sep)
                if any(should_exclude(p, exclude_patterns) for p in parts):
                    continue

            yield root, filename


# ===================================================================
# Reference Graph Traversal
# ===================================================================

def scan_references(
    skill_path: str,
    system_root: str | None = None,
    max_depth: int | None = None,
    exclude_patterns: list[str] | None = None,
    *,
    inline_orchestrated_skills: bool = False,
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
        inline_orchestrated_skills:
                          When ``True``, cross-skill references are
                          collected for inlining as capabilities instead
                          of being rejected.

    Returns a dict::

        {
            'external_files': set of absolute paths,
            'errors':         list of FAIL strings,
            'warnings':       list of WARN strings,
            'reference_map':  {source_path: [(raw_ref, line, type, resolved), ...]},
            'inlined_skills': {abs_skill_dir: skill_name} (always present;
                              empty when ``inline_orchestrated_skills`` is
                              False; keys are canonical abspath directories),
            'inlined_skill_aliases': [(alias_abs, primary_abs), ...] alias
                              roots for skills referenced via symlinks
                              (primary is system_root-basis, not realpath),
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
    # Skill directories collected for inlining (only when flag is set).
    # Keys are canonical abspath directories, re-expressed through the
    # lexical system_root so they share the same path basis as the
    # coordinator and external files.
    inlined_skills: dict[str, str] = {}  # {abs_skill_dir: skill_name}
    # Alias roots: (alias_abs_dir, primary_abs_dir) for symlink paths
    # that resolve to an already-collected inlined skill.  The primary
    # dir is on the system_root path basis (not realpath).  Used to
    # add rewrite-map entries for alias-path references.
    inlined_skill_aliases: list[tuple[str, str]] = []
    # Canonical set (normcase + realpath) for deduplication — ensures
    # the same skill referenced via symlinks or different case is not
    # collected twice.  Also used for O(path_depth) containment checks
    # so the already-inlined lookup avoids O(refs × skills) scanning.
    _inlined_canonical: set[str] = set()
    # Maps canonical_skill_dir -> primary_dir (system_root-basis) for lookups.
    _canonical_to_primary: dict[str, str] = {}
    # Canonical form of the coordinator (top-level skill being bundled)
    # so we can avoid collecting it for inlining when an inlined skill
    # references it back.
    coordinator_canonical = os.path.normcase(os.path.realpath(skill_path))

    # External files whose subtrees have been fully traversed.
    scanned_external: set[str] = set()

    def _scan_file(
        filepath: str,
        depth: int,
        ancestor_set: frozenset[str],
        ancestor_path: tuple[str, ...],
        current_skill: str | None = None,
    ) -> None:
        """Recursively scan *filepath* and classify its references.

        *ancestor_set* is a frozenset for O(1) cycle membership checks.
        *ancestor_path* is an ordered tuple for deterministic cycle display.
        *current_skill* is the skill directory context for internal/
        cross-skill checks (defaults to the top-level *skill_path*).
        """
        if current_skill is None:
            current_skill = skill_path
        filepath = os.path.abspath(filepath)

        if depth > max_depth:
            errors.append(
                f"{LEVEL_FAIL}: Reference depth limit ({max_depth}) exceeded "
                f"while scanning '{_rel(filepath)}'. "
                f"Check for excessive nesting or increase "
                f"bundle.max_reference_depth in configuration.yaml."
            )
            return

        try:
            refs = extract_references(filepath)
        except UnicodeDecodeError:
            rel = _rel(filepath)
            if is_markdown_file(filepath):
                errors.append(
                    f"{LEVEL_FAIL}: Cannot read '{rel}' as UTF-8. "
                    f"Markdown files must be valid UTF-8 for reference "
                    f"scanning and path rewriting."
                )
            else:
                warnings.append(
                    f"{LEVEL_WARN}: Cannot read '{rel}' as UTF-8. "
                    f"Skipping reference detection for this file."
                )
            return
        except OSError as exc:
            rel = _rel(filepath)
            if is_markdown_file(filepath):
                errors.append(
                    f"{LEVEL_FAIL}: Cannot read '{rel}': {exc}. "
                    f"Ensure the file is accessible before bundling."
                )
            else:
                warnings.append(
                    f"{LEVEL_WARN}: Cannot read '{rel}': {exc}. "
                    f"Skipping reference detection for this file."
                )
            return
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
                elif fail_reason == "is_directory":
                    errors.append(
                        f"{LEVEL_FAIL}: Reference points to a directory in "
                        f"'{_rel(filepath)}' line {line_num}: '{raw_ref}'. "
                        f"Only file references can be bundled — point to a "
                        f"specific file instead."
                    )
                else:
                    errors.append(
                        f"{LEVEL_FAIL}: Broken reference in "
                        f"'{_rel(filepath)}' line {line_num}: "
                        f"'{raw_ref}' does not resolve to any existing file. "
                        f"Fix the reference path before bundling."
                    )
                continue

            # ---- Internal (within the skill or an already-collected
            #      inlined skill) ----
            # Treat files whose real path is within the skill as internal.
            if is_within_directory(resolved, current_skill):
                continue
            # When inlining, files inside an already-collected inlined
            # skill are also internal — they will be copied as part of
            # the full skill directory, not as external files.
            # Use an O(path_depth) walk up the realpath of resolved
            # checking the canonical set, instead of iterating all
            # inlined_skills with is_within_directory on each.
            if inline_orchestrated_skills:
                real_resolved = os.path.normcase(
                    os.path.realpath(resolved)
                )
                containing_canonical = None
                _check_dir = os.path.dirname(real_resolved)
                while True:
                    if _check_dir in _inlined_canonical:
                        containing_canonical = _check_dir
                        break
                    _parent = os.path.dirname(_check_dir)
                    if _parent == _check_dir:
                        break
                    _check_dir = _parent
                if containing_canonical is not None:
                    matched_isd = _canonical_to_primary[
                        containing_canonical
                    ]
                    containing_inlined = inlined_skills[matched_isd]
                    # Check whether the lexical (normpath) resolved
                    # path reaches the skill through an alias — i.e.
                    # a symlink directory that differs from the primary
                    # inlined skill directory.  ``is_within_directory``
                    # matched via realpath, but the lexical path may go
                    # through a different root.
                    resolved_norm = os.path.normcase(
                        os.path.abspath(resolved)
                    )
                    matched_norm = os.path.normcase(matched_isd)
                    lexically_within = False
                    try:
                        lexically_within = (
                            os.path.commonpath(
                                [resolved_norm, matched_norm]
                            )
                            == matched_norm
                        )
                    except ValueError:
                        pass
                    if (
                        not lexically_within
                        and system_root is not None
                    ):
                        # Derive the alias skill root from the
                        # lexical resolved path by walking up to
                        # find a SKILL.md, staying strictly within
                        # system_root.  Use ``is_within_directory``
                        # (realpath + commonpath) as the loop guard
                        # so that platform path aliases (e.g. macOS
                        # /tmp -> /private/tmp) and unusual mount
                        # structures can never cause the walk to
                        # escape the intended boundary and
                        # accidentally match a SKILL.md above
                        # system_root.
                        alias_candidate = os.path.dirname(
                            os.path.abspath(resolved)
                        )
                        while True:
                            # Stop when we've reached or escaped
                            # system_root — there is no valid skill
                            # root at or above the system root.
                            if not is_within_directory(
                                alias_candidate, system_root
                            ) or os.path.normcase(
                                os.path.realpath(alias_candidate)
                            ) == os.path.normcase(
                                os.path.realpath(system_root)
                            ):
                                break
                            if os.path.exists(
                                os.path.join(
                                    alias_candidate, FILE_SKILL_MD
                                )
                            ):
                                if os.path.normcase(alias_candidate) != os.path.normcase(matched_isd) and (
                                    alias_candidate, matched_isd
                                ) not in inlined_skill_aliases:
                                    inlined_skill_aliases.append(
                                        (alias_candidate, matched_isd)
                                    )
                                break
                            parent = os.path.dirname(alias_candidate)
                            if parent == alias_candidate:
                                break
                            alias_candidate = parent
                    # text_detected references are not rewritten in the
                    # bundle, so warn about stale paths.
                    if ref_type == "text_detected":
                        warnings.append(
                            f"{LEVEL_WARN}: Non-markdown cross-skill "
                            f"reference detected in "
                            f"'{_rel(filepath)}' line {line_num}: "
                            f"'{raw_ref}'. This reference points to "
                            f"inlined skill '{containing_inlined}' but "
                            f"cannot be automatically rewritten in "
                            f"the bundle. You may need to update it "
                            f"manually."
                        )
                    continue

            # For entries that are only lexically within the skill (i.e.
            # a symlink living inside the skill pointing elsewhere),
            # allow them as internal unless they actually target another
            # skill under system_root/skills/ (cross-skill symlink bypass).
            lexical_path_norm = os.path.normcase(os.path.abspath(resolved))
            skill_norm = os.path.normcase(current_skill)
            lexical_within_skill = False
            try:
                lexical_within_skill = (
                    os.path.commonpath([lexical_path_norm, skill_norm])
                    == skill_norm
                )
            except ValueError:
                # Different drives on Windows — cannot be within the skill.
                pass

            if lexical_within_skill:
                if system_root:
                    # Use realpath consistently so /tmp vs /private/tmp
                    # (macOS) and similar platform symlinks don't cause
                    # false negatives.
                    skills_root_real = os.path.normcase(os.path.realpath(
                        os.path.join(system_root, DIR_SKILLS)
                    ))
                    resolved_real = os.path.normcase(
                        os.path.realpath(resolved)
                    )
                    skill_real = os.path.normcase(
                        os.path.realpath(current_skill)
                    )
                    try:
                        under_skills_root = (
                            os.path.commonpath(
                                [resolved_real, skills_root_real]
                            )
                            == skills_root_real
                        )
                    except ValueError:
                        # Different drives on Windows — cannot be under skills.
                        under_skills_root = False

                    if under_skills_root:
                        rel_to_skills = os.path.relpath(
                            resolved_real, skills_root_real
                        )
                        parts = rel_to_skills.split(os.sep)
                        owning_skill_dir = None
                        if parts and parts[0] not in (".", os.pardir):
                            owning_skill_dir = os.path.join(
                                skills_root_real, parts[0]
                            )

                        if owning_skill_dir and owning_skill_dir != skill_real:
                            errors.append(
                                f"{LEVEL_FAIL}: Symlinked reference in "
                                f"'{_rel(filepath)}' line {line_num}: "
                                f"'{raw_ref}' targets another skill under "
                                f"'{DIR_SKILLS}'. Cross-skill references via "
                                f"symlinks are not allowed."
                            )
                            continue

                # Either no system_root (cannot classify) or the target is not
                # under a different skill; treat as internal/shared.
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

            # ---- Cross-skill reference (checked before text_detected
            #      so that cross-skill violations are always a hard
            #      FAIL regardless of reference type) ----
            if system_root:
                containing_skill = find_containing_skill(resolved, system_root)
                if containing_skill:
                    containing_norm = os.path.normcase(
                        os.path.realpath(os.path.abspath(containing_skill))
                    )
                    current_skill_norm = os.path.normcase(
                        os.path.realpath(current_skill)
                    )
                    if containing_norm != current_skill_norm:
                        other_skill_name = os.path.basename(containing_skill)
                        if inline_orchestrated_skills:
                            # Collect for inlining instead of rejecting.
                            abs_skill_dir = os.path.abspath(containing_skill)
                            # Canonical form for deduplication — ensures
                            # symlinks and case differences don't cause
                            # the same skill to be collected twice.
                            real_skill_dir = os.path.realpath(abs_skill_dir)
                            canonical_skill_dir = os.path.normcase(
                                real_skill_dir
                            )
                            # Never inline the coordinator itself —
                            # a back-reference from an inlined skill to
                            # the coordinator is a reference to the
                            # bundle root, not a new skill to inline.
                            if canonical_skill_dir == coordinator_canonical:
                                # text_detected references are not
                                # rewritten; warn about the stale path.
                                if ref_type == "text_detected":
                                    warnings.append(
                                        f"{LEVEL_WARN}: Non-markdown "
                                        f"reference to coordinator skill "
                                        f"detected in "
                                        f"'{_rel(filepath)}' line "
                                        f"{line_num}: '{raw_ref}'. This "
                                        f"reference cannot be "
                                        f"automatically rewritten in "
                                        f"the bundle. You may need to "
                                        f"update it manually."
                                    )
                                continue
                            # Derive the skill name from the resolved
                            # real path so aliases don't produce
                            # inconsistent capability directory names.
                            canonical_name = os.path.basename(
                                real_skill_dir
                            )
                            already_collected = (
                                canonical_skill_dir in _inlined_canonical
                            )
                            # Derive the primary directory on the same
                            # path basis as system_root so the bundling
                            # pipeline can compute consistent relative
                            # paths.  Convert the realpath back through
                            # the lexical system_root to avoid platform
                            # path aliases (e.g. macOS /var -> /private/
                            # var) leaking into the key.
                            #
                            # This ensures the primary is always the
                            # canonical real directory regardless of
                            # whether the first reference arrived via a
                            # symlink alias — alias-first discovery
                            # still produces the same primary_dir
                            # because the derivation is from realpath,
                            # not from the discovered abs_skill_dir.
                            if system_root is not None:
                                _sr_real = os.path.realpath(system_root)
                                try:
                                    _rel_from_sr = os.path.relpath(
                                        real_skill_dir, _sr_real
                                    )
                                    primary_dir = os.path.normpath(
                                        os.path.join(
                                            system_root, _rel_from_sr
                                        )
                                    )
                                except ValueError:
                                    primary_dir = abs_skill_dir
                            else:
                                primary_dir = abs_skill_dir
                            if not already_collected:
                                _inlined_canonical.add(canonical_skill_dir)
                                _canonical_to_primary[canonical_skill_dir] = primary_dir
                                inlined_skills[primary_dir] = canonical_name
                                # If discovered via a symlink alias,
                                # record it immediately.  Use normcase
                                # so case-insensitive filesystems
                                # (macOS, Windows) don't produce
                                # spurious alias entries when the only
                                # difference is letter case.
                                if os.path.normcase(abs_skill_dir) != os.path.normcase(primary_dir):
                                    inlined_skill_aliases.append(
                                        (abs_skill_dir, primary_dir)
                                    )
                            else:
                                primary_dir = _canonical_to_primary[
                                    canonical_skill_dir
                                ]
                                # Record the alias so the rewrite map
                                # covers both path forms.  Use normcase
                                # for the guard (case-insensitive FS
                                # safety) and for the dedup check.
                                if os.path.normcase(abs_skill_dir) != os.path.normcase(primary_dir):
                                    alias_pair = (
                                        abs_skill_dir, primary_dir
                                    )
                                    if (
                                        alias_pair
                                        not in inlined_skill_aliases
                                    ):
                                        inlined_skill_aliases.append(
                                            alias_pair
                                        )
                            # The resolved file is inside the skill being
                            # inlined — do NOT add it to external_files
                            # (it will be copied as part of the full skill
                            # directory during inlining).
                            #
                            # When a skill is first collected, scan ALL
                            # files in its directory tree so that every
                            # external dependency and validation issue is
                            # discovered — not just those reachable from
                            # the single referenced entry point.
                            if not already_collected:
                                inlined_boundary = (
                                    primary_dir if system_root is None
                                    else system_root
                                )
                                inlined_violations: list[BoundaryViolation] = []
                                for iroot, ifilename in walk_skill_files(
                                    primary_dir,
                                    exclude_patterns,
                                    inlined_boundary,
                                    inlined_violations,
                                ):
                                    ifile = os.path.join(iroot, ifilename)
                                    if ifile not in scanned_external:
                                        scanned_external.add(ifile)
                                        _scan_file(
                                            ifile, 0,
                                            frozenset(), (),
                                            current_skill=primary_dir,
                                        )
                                # Convert boundary violations from the
                                # inlined skill walk into FAIL entries.
                                for iv in inlined_violations:
                                    iv_rel = os.path.relpath(
                                        iv.link_path, primary_dir
                                    ).replace(os.sep, "/")
                                    errors.append(
                                         f"{LEVEL_FAIL}: Symlinked {iv.kind} "
                                        f"in inlined skill "
                                        f"'{canonical_name}' escapes "
                                        f"allowed boundary rooted at "
                                        f"'{inlined_boundary}': "
                                        f"'{iv_rel}' -> '{iv.real_target}'. "
                                        f"Symlink targets must stay within "
                                        f"this boundary."
                                    )
                            # text_detected references (from non-markdown
                            # files) are not rewritten in the bundle.
                            # Warn the user so they know the stale path
                            # needs manual attention.
                            if ref_type == "text_detected":
                                warnings.append(
                                    f"{LEVEL_WARN}: Non-markdown cross-skill "
                                    f"reference detected in "
                                    f"'{_rel(filepath)}' line {line_num}: "
                                    f"'{raw_ref}'. This reference points to "
                                    f"inlined skill '{canonical_name}' but "
                                    f"cannot be automatically rewritten in "
                                    f"the bundle. You may need to update it "
                                    f"manually."
                                )
                            continue
                        errors.append(
                            f"{LEVEL_FAIL}: Cross-skill reference in "
                            f"'{_rel(filepath)}' line {line_num}: "
                            f"'{raw_ref}' points to skill '{other_skill_name}'. "
                            f"A bundle must be self-contained — it cannot "
                            f"reference other skills. Remove this reference "
                            f"or inline the needed content."
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
                    _scan_file(
                        resolved, depth + 1, new_set, new_path,
                        current_skill=current_skill,
                    )
                continue

            # ---- Cycle between external documents ----
            if resolved in ancestor_set:
                cycle_display = " -> ".join(
                    _rel(f) for f in ancestor_path + (resolved,)
                    if not is_within_directory(f, current_skill)
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
                _scan_file(
                    resolved, depth + 1, new_set, new_path,
                    current_skill=current_skill,
                )

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

    # Scan every file in the skill directory tree using the shared
    # traversal helper so the scanned file set matches what
    # _copy_skill() puts in the bundle.
    boundary = skill_path if system_root is None else system_root
    violations: list[BoundaryViolation] = []

    for root, filename in walk_skill_files(
        skill_path, exclude_patterns, boundary, violations
    ):
        _scan_file(os.path.join(root, filename), 0, frozenset(), ())

    boundary_display = boundary
    for v in violations:
        rel = _rel(v.link_path)
        errors.append(
            f"{LEVEL_FAIL}: Symlinked {v.kind} escapes allowed boundary "
            f"rooted at '{boundary_display}': '{rel}' -> "
            f"'{v.real_target}'. Symlink targets must stay within "
            f"this boundary."
        )

    return {
        "external_files": external_files,
        "errors": errors,
        "warnings": warnings,
        "reference_map": reference_map,
        "inlined_skills": inlined_skills,
        "inlined_skill_aliases": inlined_skill_aliases,
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
