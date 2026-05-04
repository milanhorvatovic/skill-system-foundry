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
from .frontmatter import strip_frontmatter_for_scan
from .references import is_within_directory


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
    # Reject absolute and drive-qualified refs.  ``splitdrive`` catches
    # the Windows drive-relative form (``C:foo.md``) that
    # ``os.path.isabs`` misses — without it, ``os.path.join(skill_root,
    # 'C:foo.md')`` drops ``skill_root`` and the rewriter could probe
    # an out-of-skill file and emit an out-of-skill replacement.  Same
    # guard applies to the post-suffix-split path below.
    if (
        not ref_norm
        or os.path.isabs(ref_norm)
        or os.path.splitdrive(ref_norm)[0]
    ):
        return None

    # Separate the filesystem-relevant path from any anchor/query/title
    # suffix so existence checks work on the path alone but the
    # replacement keeps the suffix the author wrote.
    ref_path_only, suffix = _split_path_and_suffix(ref_norm)
    if not ref_path_only or os.path.splitdrive(ref_path_only)[0]:
        return None
    # Already file-relative if it starts with ../ or ./  — we trust
    # the author and don't second-guess the form.
    if ref_path_only.startswith("../") or ref_path_only.startswith("./"):
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

    # Resolution under the NEW file-relative rule.  If the link
    # already resolves under file-relative semantics — even to a
    # *different* file than the legacy resolution — the link is
    # already valid as written and the rewriter must not mutate it.
    # The classic trap: a capability-local
    # ``capabilities/<n>/references/foo.md`` link resolves
    # file-relative to its own ``references/foo.md``.  The skill root
    # may also have a ``references/foo.md`` (a different file).
    # Without this guard the rewriter would propose rewriting the
    # working capability-local link into ``../../references/foo.md``
    # — silently changing the link's target to the shared-root file.
    # Skip the rewrite whenever the existing form already lands on
    # an in-scope file under file-relative semantics.
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

    Files under ``scripts/`` and ``assets/`` are excluded — those
    trees are not part of the prose link graph.
    """
    fence_re = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
    skill_root = os.path.abspath(skill_root)
    rows: list[dict] = []

    for dirpath, dirs, names in os.walk(skill_root):
        rel = os.path.relpath(dirpath, skill_root).replace(os.sep, "/")
        top = rel.split("/", 1)[0] if rel != "." else ""
        if top in ("scripts", "assets"):
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

            seen: set[str] = set()
            for ref in captures:
                if ref in seen:
                    continue
                seen.add(ref)
                if "<" in ref or ">" in ref:
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
                    "file": filepath,
                    "file_rel": file_rel,
                    "original": ref,
                    "replacement": replacement,
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

        # Walk the document in alternating non-fence/fence segments
        # so substitutions never enter a fenced block.  ``finditer``
        # gives us span boundaries we can use as splice points.
        parts: list[str] = []
        cursor = 0
        for fence_match in _FENCE_RE.finditer(content):
            parts.append(_rewrite(content[cursor:fence_match.start()]))
            parts.append(fence_match.group(0))
            cursor = fence_match.end()
        parts.append(_rewrite(content[cursor:]))
        new_content = "".join(parts)

        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed += 1
    return changed
