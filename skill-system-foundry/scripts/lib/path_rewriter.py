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


# ===================================================================
# Public API
# ===================================================================


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
    source_rel = os.path.relpath(source_abs_path, skill_root).replace(
        os.sep, "/",
    )

    ref_norm = ref.replace("\\", "/").strip()
    if not ref_norm or os.path.isabs(ref_norm):
        return None
    # Already file-relative if it starts with ../ or ./  — we trust
    # the author and don't second-guess the form.
    if ref_norm.startswith("../") or ref_norm.startswith("./"):
        return None

    # Resolution under the LEGACY skill-root rule.
    legacy_target = os.path.normpath(os.path.join(skill_root, ref_norm))
    if not os.path.isfile(legacy_target):
        # Legacy resolution doesn't land on a real file either —
        # there's no clear target to rewrite to.
        return None

    # Resolution under the NEW file-relative rule.
    file_rel_target = os.path.normpath(os.path.join(source_dir, ref_norm))
    if (
        os.path.isfile(file_rel_target)
        and os.path.samefile(file_rel_target, legacy_target)
    ):
        # Already correct under both rules — no rewrite needed.
        return None

    # Compute the canonical form: the relative path from source_dir
    # to legacy_target, in forward-slash POSIX form.
    new_form = os.path.relpath(legacy_target, source_dir).replace(
        os.sep, "/",
    )
    if new_form == ref_norm:
        return None  # Identical — nothing to suggest.
    return new_form


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
                # Find the first line containing the original ref — used
                # for human-readable diff output.
                line_no = 0
                for idx, line in enumerate(content.split("\n"), start=1):
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

        new_content = re.sub(
            r"(\[[^\]]*\])\(([^)]+)\)", _md_sub, content,
        )
        new_content = re.sub(
            r"`([^`\n]+)`", _bt_sub, new_content,
        )

        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed += 1
    return changed
