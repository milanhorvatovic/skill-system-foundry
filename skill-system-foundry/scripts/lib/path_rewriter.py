"""Mechanical rewrite of skill-root-form references to file-relative form.

When the redefined path-resolution rule
(``references/path-resolution.md``) flags a broken intra-skill link,
the validator can often suggest a mechanical replacement: the same
target file expressed in the canonical file-relative form for the
source's scope.  This module computes that suggestion.

The rewriter is deliberately conservative.  It only suggests a
replacement when:

1. The original ref is in the legacy skill-root form (e.g.
   ``references/foo.md`` from a capability).
2. The legacy form would resolve correctly under skill-root
   semantics (i.e. the target file exists under the skill root at
   the path the legacy reader would compute).
3. The new form resolves correctly under the source file's scope
   (file-relative).

If any of these checks fails, the rewriter returns ``None`` and the
human author has to decide what to do.  The validator surfaces the
broken link as a FAIL/WARN with no suggestion in that case.
"""

import os
import re

from .constants import (
    DIR_CAPABILITIES,
    EXT_MARKDOWN,
    RE_BACKTICK_REF,
    RE_MARKDOWN_LINK_REF,
)
from .frontmatter import split_frontmatter, strip_frontmatter_for_scan
from .references import is_drive_qualified, is_glob_path, is_within_directory
from .reporting import to_posix


# ===================================================================
# Public API
# ===================================================================


def _split_path_and_suffix(ref: str) -> tuple[str, str]:
    """Split *ref* into ``(filesystem_path, non_path_suffix)``.

    Mirrors the validator's use of ``strip_fragment`` in
    ``lib/references.py`` for resolution: anchors (``#section``),
    query strings (``?key=value``), and markdown link title
    annotations (``foo.md "Title"``) are not part of the resolved
    filesystem path, but they must survive a mechanical rewrite
    verbatim so the source link form is preserved end-to-end (e.g.
    a legacy ``[guide](references/guide.md#section)`` rewrites to
    ``[guide](../../references/guide.md#section)``, not
    ``[guide](../../references/guide.md)``).
    """
    path = ref
    suffix_parts: list[str] = []
    # Title suffix at the end first: ``path "title"`` or ``path 'title'``.
    title_match = re.search(r'''\s+["'][^"']*["']\s*$''', path)
    if title_match:
        suffix_parts.insert(0, path[title_match.start():])
        path = path[:title_match.start()]
    # Then the earliest of ?/# in the remaining path — strip_fragment
    # takes the path up to the first occurrence of either separator.
    earliest = -1
    for sep in ("?", "#"):
        idx = path.find(sep)
        if idx != -1 and (earliest == -1 or idx < earliest):
            earliest = idx
    if earliest != -1:
        suffix_parts.insert(0, path[earliest:])
        path = path[:earliest]
    return path, "".join(suffix_parts)


def compute_recommended_replacement(
    ref: str,
    source_abs_path: str,
    skill_root: str,
) -> str | None:
    """Return the canonical file-relative form of *ref*, or None.

    *ref* is the path string as written in the source.  *source_abs_path*
    is the absolute filesystem path of the file containing the link.
    *skill_root* is the absolute path of the skill root (the directory
    containing ``SKILL.md``).

    Returns:
        - The canonical replacement string when a mechanical rewrite
          exists and both the legacy resolution and the new resolution
          land on the same existing file.
        - ``None`` when no mechanical rewrite is safe.
    """
    skill_root = os.path.abspath(skill_root)
    source_abs_path = os.path.abspath(source_abs_path)
    source_dir = os.path.dirname(source_abs_path)

    ref_norm = ref.replace("\\", "/").strip()
    # Reject absolute and drive-qualified refs.  ``is_drive_qualified``
    # (lib/references) catches the Windows drive-relative form
    # (``C:foo.md``) that ``os.path.isabs`` misses — without the
    # extra check, ``os.path.join(skill_root, 'C:foo.md')`` drops
    # ``skill_root`` on Windows and the rewriter could probe an
    # out-of-skill file and emit an out-of-skill replacement.
    # ``os.path.splitdrive`` is host-dependent (returns empty drive
    # on POSIX), so the foundry uses its own helper to keep the
    # rejection identical on every platform.  Same guard applies to
    # the post-suffix-split path below.
    if (
        not ref_norm
        or os.path.isabs(ref_norm)
        or is_drive_qualified(ref_norm)
    ):
        return None

    # Separate the filesystem-relevant path from any anchor/query/title
    # suffix so existence checks work on the path alone but the
    # replacement keeps the suffix the author wrote.
    ref_path_only, suffix = _split_path_and_suffix(ref_norm)
    if not ref_path_only or is_drive_qualified(ref_path_only):
        return None
    # ``../``-prefixed refs are intentional file-relative form — the
    # author wrote a parent-traversal explicitly, so respect it and
    # do not propose a rewrite that would change the link.  ``./``
    # is *not* the same: a ``./``-prefixed legacy ref like
    # ``./references/foo.md`` from a capability still resolves to
    # ``capabilities/<n>/references/foo.md`` file-relative (broken
    # under the new rule) but lands on ``<skill_root>/references/
    # foo.md`` under legacy skill-root resolution — i.e. it is
    # exactly the kind of mechanically rewriteable legacy link the
    # rewriter exists to surface.  Let ``./``-prefixed refs flow
    # through the legacy/file-relative comparison below and only
    # short-circuit on ``../``.
    if ref_path_only.startswith("../"):
        return None

    # Resolution under the LEGACY skill-root rule.  Mid-path ``..``
    # segments (e.g. ``references/../../shared/foo.md``) can normalize
    # outside the skill root even though the leading-prefix guard
    # above didn't reject them — refuse to suggest a replacement
    # whose legacy target is out of skill, both to honor the
    # validator's "no existence checks for out-of-skill paths"
    # boundary and to avoid emitting a non-canonical relative path
    # that points outside the skill tree.
    legacy_target = os.path.normpath(os.path.join(skill_root, ref_path_only))
    if not is_within_directory(legacy_target, skill_root):
        return None
    if not os.path.isfile(legacy_target):
        # Legacy resolution doesn't land on a real file either —
        # there's no clear target to rewrite to.
        return None

    # Resolution under the NEW file-relative rule.  Two sub-cases
    # share the early-return:
    #
    # 1. Both legacy and file-relative resolve to the *same* file —
    #    the link is already canonical, no rewrite needed.
    # 2. File-relative resolves to a different in-scope file — the
    #    link is *already valid* under the new rule; rewriting it
    #    would silently re-target it.  The classic trap: a
    #    capability-local ``references/foo.md`` resolves file-
    #    relative to ``capabilities/<n>/references/foo.md``, but
    #    the skill root may also have a ``references/foo.md`` (a
    #    different file).
    #
    # Sub-case 2 is also the *ambiguous-migration* case the rewriter
    # cannot resolve safely — see ``find_ambiguous_legacy_refs`` for
    # the parallel scan that surfaces these as a separate finding.
    # The rewrite path returns None either way: ``--fix`` reports the
    # rewrite-eligible cases under ``fixes`` and the ambiguous cases
    # under ``ambiguous_findings``, never both.
    file_rel_target = os.path.normpath(os.path.join(source_dir, ref_path_only))
    if (
        os.path.isfile(file_rel_target)
        and is_within_directory(file_rel_target, skill_root)
    ):
        return None

    # Compute the canonical form: the relative path from source_dir
    # to legacy_target, in forward-slash POSIX form.
    new_path = os.path.relpath(legacy_target, source_dir).replace(
        os.sep, "/",
    )
    if new_path == ref_path_only:
        return None  # Identical — nothing to suggest.
    return new_path + suffix


def detect_ambiguous_legacy_target(
    ref: str,
    source_abs_path: str,
    skill_root: str,
) -> tuple[str, str] | None:
    """Return ``(legacy_target, file_rel_target)`` when *ref* is ambiguous.

    A reference is *ambiguous* when both the legacy skill-root
    resolution and the file-relative resolution land on existing
    in-scope files that are **different**.  Pre-migration the
    legacy form was authoritative; post-migration the file-relative
    form is.  When both resolve, the link's target silently changes
    meaning during migration without any tooling diagnostic — a
    real hazard for skills that grow capability-local references
    sharing names with shared-root files.

    Returns ``None`` for every other case (no rewrite needed,
    rewrite eligible, or no clear target).  Callers use this in
    parallel with :func:`compute_recommended_replacement` to surface
    the ambiguous bucket separately from the rewrite bucket.
    """
    skill_root = os.path.abspath(skill_root)
    source_abs_path = os.path.abspath(source_abs_path)
    source_dir = os.path.dirname(source_abs_path)

    ref_norm = ref.replace("\\", "/").strip()
    if (
        not ref_norm
        or os.path.isabs(ref_norm)
        or is_drive_qualified(ref_norm)
    ):
        return None
    ref_path_only, _suffix = _split_path_and_suffix(ref_norm)
    if not ref_path_only or is_drive_qualified(ref_path_only):
        return None
    # Only short-circuit on ``../`` — see ``compute_recommended_replacement``
    # for why ``./``-prefixed refs need to flow through the
    # legacy/file-relative comparison below.
    if ref_path_only.startswith("../"):
        return None

    legacy_target = os.path.normpath(os.path.join(skill_root, ref_path_only))
    if not is_within_directory(legacy_target, skill_root):
        return None
    if not os.path.isfile(legacy_target):
        return None
    file_rel_target = os.path.normpath(os.path.join(source_dir, ref_path_only))
    if not is_within_directory(file_rel_target, skill_root):
        return None
    if not os.path.isfile(file_rel_target):
        return None
    if os.path.samefile(legacy_target, file_rel_target):
        return None
    return (legacy_target, file_rel_target)


# ===================================================================
# Source-scope helpers (used by --fix output)
# ===================================================================


def detect_source_scope(source_rel_path: str) -> tuple[str, str]:
    """Return ``(scope_kind, scope_name)`` for a skill-root-relative path.

    ``("skill", "")`` for files at the skill root or under its shared
    directories; ``("capability", "<name>")`` for any file under
    ``capabilities/<name>/``.
    """
    parts = source_rel_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == DIR_CAPABILITIES:
        return ("capability", parts[1])
    return ("skill", "")


# ===================================================================
# Skill-wide rewrite collection
# ===================================================================


def find_fixable_references(skill_root: str) -> list[dict]:
    """Walk *skill_root* and return mechanically rewritable references.

    Each row is a dict with keys:

    * ``file`` — absolute path to the source file.
    * ``file_rel`` — skill-root-relative form for display.
    * ``original`` — the ref string as written in the file.
    * ``replacement`` — the canonical file-relative form.
    * ``line`` — 1-based line number of the source line that contains
      the original ref (the first match per file is used).

    Files under ``scripts/`` and ``assets/`` at *any* depth are
    excluded — capability-local ``capabilities/<name>/scripts/`` and
    ``capabilities/<name>/assets/`` count too.  Those trees are not
    part of the prose link graph and ``--fix --apply`` would
    otherwise mutate template/asset markdown content during a
    routine rewrite run.
    """
    fence_re = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
    skill_root = os.path.abspath(skill_root)
    rows: list[dict] = []

    for dirpath, dirs, names in os.walk(skill_root):
        rel = os.path.relpath(dirpath, skill_root).replace(os.sep, "/")
        # Prune scripts/ and assets/ subtrees at any scope depth —
        # check every component, not just the first, so capability-
        # local trees are excluded too.
        rel_parts = [] if rel == "." else rel.split("/")
        if any(part in ("scripts", "assets") for part in rel_parts):
            dirs[:] = []
            continue
        for name in sorted(names):
            if not name.endswith(EXT_MARKDOWN):
                continue
            filepath = os.path.abspath(os.path.join(dirpath, name))
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeError):
                continue
            file_rel = os.path.relpath(filepath, skill_root).replace(
                os.sep, "/",
            )
            body = strip_frontmatter_for_scan(content)
            stripped = fence_re.sub("", body)

            # Collect every captured ref string (markdown links + backticks)
            # — duplicates included; rewrite-time replacement applies to
            # all occurrences with the same source string.
            captures: list[str] = []
            captures.extend(RE_MARKDOWN_LINK_REF.findall(stripped))
            captures.extend(RE_BACKTICK_REF.findall(stripped))

            # Pre-compute the 1-based line numbers that fall inside a
            # fenced code block in *content*.  ``apply_fixes`` skips
            # those regions during rewrite, so the displayed line
            # number must skip them too — otherwise ``--fix`` could
            # report a fenced example line that the eventual write
            # never touches, sending the author or automation to the
            # wrong place.
            fenced_lines: set[int] = set()
            for fm in fence_re.finditer(content):
                start_line = content.count("\n", 0, fm.start()) + 1
                end_line = content.count("\n", 0, fm.end()) + 1
                for ln in range(start_line, end_line + 1):
                    fenced_lines.add(ln)

            # Apply the same skip to lines occupied by a leading YAML
            # frontmatter block.  ``apply_fixes`` skips frontmatter
            # during rewrite (the body extractor already does too),
            # but the line search below walks the *raw* content
            # including frontmatter — so a legacy ref string that
            # happens to appear in a folded ``description`` would
            # report a frontmatter line that the rewrite never
            # touches, sending consumers to the wrong place.
            # ``split_frontmatter`` returns a non-``None`` tuple only
            # for a well-formed open + close pair; the closing
            # delimiter is the first standalone ``---`` after line 1,
            # so the frontmatter span is lines ``1..close_line``.
            frontmatter_raw, body_raw = split_frontmatter(content)
            if frontmatter_raw is not None and body_raw is not None:
                # ``frontmatter_raw`` is the content between the two
                # delimiters.  The opening ``---`` is line 1; each
                # ``\n`` in the inner content represents one
                # frontmatter-content line; the closing ``---`` is
                # the next line after that.  ``--apply`` writes from
                # ``body_raw`` onward, so any line ``<= close_line``
                # is untouched and must be excluded from the search.
                fm_close_line = frontmatter_raw.count("\n") + 2
                for ln in range(1, fm_close_line + 1):
                    fenced_lines.add(ln)

            seen: set[str] = set()
            for ref in captures:
                if ref in seen:
                    continue
                seen.add(ref)
                # Skip template placeholders (``<...>``) and
                # glob-style inline-code mentions.  ``is_glob_path``
                # discriminates between a query-suffix ``?``
                # (``foo.md?v=2`` — preserved through the rewrite)
                # and a glob-inside-path ``?`` (``references/?ref.md``
                # — must be filtered) by looking only at the path
                # portion before any extension-anchored
                # query/anchor boundary.
                if "<" in ref or ">" in ref:
                    continue
                if is_glob_path(ref):
                    continue
                replacement = compute_recommended_replacement(
                    ref, filepath, skill_root,
                )
                if replacement is None:
                    continue
                # Find the first non-fenced line containing the
                # original ref — that's the one ``apply_fixes`` will
                # actually modify, and the only line worth reporting.
                line_no = 0
                for idx, line in enumerate(content.split("\n"), start=1):
                    if idx in fenced_lines:
                        continue
                    if ref in line:
                        line_no = idx
                        break
                rows.append({
                    "file": to_posix(filepath),
                    "file_rel": file_rel,
                    "original": ref,
                    "replacement": replacement,
                    "line": line_no,
                })
    return rows


def find_ambiguous_legacy_refs(skill_root: str) -> list[dict]:
    """Walk *skill_root* and return ambiguous-migration references.

    Each row is a dict with keys:

    * ``file`` — absolute path to the source file.
    * ``file_rel`` — skill-root-relative form for display.
    * ``original`` — the ref string as written in the file.
    * ``legacy_target`` — skill-root-relative path of the file the
      legacy resolution would have selected.
    * ``file_rel_target`` — skill-root-relative path of the file the
      file-relative resolution selects under the new rule.
    * ``line`` — 1-based line number of the source line that contains
      the original ref.

    A reference appears here when both the legacy skill-root
    resolution and the file-relative resolution land on existing
    in-scope files that are *different*.  See
    :func:`detect_ambiguous_legacy_target` for the detection
    semantics; ``--fix`` surfaces these under
    ``ambiguous_findings`` so a migration cannot silently retarget a
    link from the shared-root file to a capability-local one (or
    vice versa) without explicit author review.

    Walks the same tree as :func:`find_fixable_references`, with
    the same scripts/assets pruning at any scope depth.
    """
    fence_re = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
    skill_root = os.path.abspath(skill_root)
    rows: list[dict] = []

    for dirpath, dirs, names in os.walk(skill_root):
        rel = os.path.relpath(dirpath, skill_root).replace(os.sep, "/")
        rel_parts = [] if rel == "." else rel.split("/")
        if any(part in ("scripts", "assets") for part in rel_parts):
            dirs[:] = []
            continue
        for name in sorted(names):
            if not name.endswith(EXT_MARKDOWN):
                continue
            filepath = os.path.abspath(os.path.join(dirpath, name))
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeError):
                continue
            file_rel = os.path.relpath(filepath, skill_root).replace(
                os.sep, "/",
            )
            body = strip_frontmatter_for_scan(content)
            stripped = fence_re.sub("", body)

            captures: list[str] = []
            captures.extend(RE_MARKDOWN_LINK_REF.findall(stripped))
            captures.extend(RE_BACKTICK_REF.findall(stripped))

            fenced_lines: set[int] = set()
            for fm in fence_re.finditer(content):
                start_line = content.count("\n", 0, fm.start()) + 1
                end_line = content.count("\n", 0, fm.end()) + 1
                for ln in range(start_line, end_line + 1):
                    fenced_lines.add(ln)

            seen: set[str] = set()
            for ref in captures:
                if ref in seen:
                    continue
                seen.add(ref)
                # Skip template placeholders (``<...>``) and
                # glob-style inline-code mentions.  ``is_glob_path``
                # discriminates between a query-suffix ``?``
                # (``foo.md?v=2`` — preserved through the rewrite)
                # and a glob-inside-path ``?`` (``references/?ref.md``
                # — must be filtered) by looking only at the path
                # portion before any extension-anchored
                # query/anchor boundary.
                if "<" in ref or ">" in ref:
                    continue
                if is_glob_path(ref):
                    continue
                ambiguous = detect_ambiguous_legacy_target(
                    ref, filepath, skill_root,
                )
                if ambiguous is None:
                    continue
                legacy_target, file_rel_target = ambiguous
                line_no = 0
                for idx, line in enumerate(content.split("\n"), start=1):
                    if idx in fenced_lines:
                        continue
                    if ref in line:
                        line_no = idx
                        break
                rows.append({
                    "file": to_posix(filepath),
                    "file_rel": file_rel,
                    "original": ref,
                    "legacy_target": to_posix(
                        os.path.relpath(legacy_target, skill_root)
                    ),
                    "file_rel_target": to_posix(
                        os.path.relpath(file_rel_target, skill_root)
                    ),
                    "line": line_no,
                })
    return rows


_FENCE_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


def apply_fixes(rows: list[dict]) -> int:
    """Write the proposed replacements to disk.

    Rewrites are link-aware: each row's ``original`` string is replaced
    by its ``replacement`` only when it appears inside a recognized
    reference span — a markdown link target ``[...](path)`` or an
    inline-code span ```path```.  Prose mentions of the same
    string elsewhere in the document are left alone.  This is the
    behavior an author expects from a "fix references" command — raw
    string replacement would silently mutate explanatory text that
    happens to quote the legacy path.

    Fenced code blocks are also left alone — ``find_fixable_references``
    strips them before scanning, so a path that only appears inside a
    fence is not in *rows* by definition.  Mirroring the strip during
    rewrite preserves example links inside ```` ```yaml ```` /
    ```` ```markdown ```` fences when the same legacy path also
    appears as a real link elsewhere in the file.

    Multiple rows targeting the same file are coalesced — the file is
    read and rewritten once per unique path.  Returns the number of
    files modified.
    """
    by_file: dict[str, list[dict]] = {}
    for row in rows:
        by_file.setdefault(row["file"], []).append(row)

    changed = 0
    for filepath, file_rows in by_file.items():
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Build a per-file mapping from original → replacement so a
        # single regex pass can substitute every legacy path inside a
        # link span.  A missing mapping means "leave the captured
        # span unchanged".
        mapping = {row["original"]: row["replacement"] for row in file_rows}

        def _md_sub(m: re.Match) -> str:
            label, path = m.group(1), m.group(2)
            return f"{label}({mapping.get(path, path)})"

        def _bt_sub(m: re.Match) -> str:
            path = m.group(1)
            return f"`{mapping.get(path, path)}`"

        def _rewrite(segment: str) -> str:
            segment = re.sub(
                r"(\[[^\]]*\])\(([^)]+)\)", _md_sub, segment,
            )
            segment = re.sub(
                r"`([^`\n]+)`", _bt_sub, segment,
            )
            return segment

        # Split the file into the YAML frontmatter block (if any)
        # and the body.  ``find_fixable_references`` strips
        # frontmatter via ``strip_frontmatter_for_scan`` before
        # scanning, so a path that only appears inside frontmatter
        # is by construction not in *rows*.  But a path that appears
        # both as a real link in the body *and* as a string in the
        # frontmatter (e.g. quoted in a folded ``description`` block)
        # would otherwise be rewritten in *both* places when
        # ``apply_fixes`` walks the whole file.  Mirror the scan's
        # frontmatter-skip during write-back so an ostensibly
        # body-link-only ``--fix --apply`` cannot mutate metadata
        # that the scan deliberately excluded.
        if content.startswith("---\n") or content.startswith("---\r\n"):
            after_first = content.split("\n", 1)
            # Find the closing ``---`` line.  Walk line by line so we
            # match only delimiter-on-its-own lines (not ``---`` that
            # happens to appear inside a YAML scalar).
            close_idx: int | None = None
            offset = len(after_first[0]) + 1
            for line in after_first[1].split("\n"):
                if line.strip() == "---":
                    close_idx = offset + len(line)
                    break
                offset += len(line) + 1
            if close_idx is not None:
                frontmatter = content[:close_idx + 1]
                body = content[close_idx + 1:]
            else:
                frontmatter = ""
                body = content
        else:
            frontmatter = ""
            body = content

        # Walk the body in alternating non-fence/fence segments so
        # substitutions never enter a fenced block.  ``finditer``
        # gives us span boundaries we can use as splice points.
        parts: list[str] = [frontmatter]
        cursor = 0
        for fence_match in _FENCE_RE.finditer(body):
            parts.append(_rewrite(body[cursor:fence_match.start()]))
            parts.append(fence_match.group(0))
            cursor = fence_match.end()
        parts.append(_rewrite(body[cursor:]))
        new_content = "".join(parts)

        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed += 1
    return changed
