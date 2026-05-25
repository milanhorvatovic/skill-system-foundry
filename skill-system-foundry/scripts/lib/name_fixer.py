"""Safe, deterministic auto-fixes for the SKILL.md ``name`` frontmatter.

When ``validate_name`` FAILs because the ``name`` field carries
uppercase characters, underscores, or spaces, the corrected value is
unambiguous: lowercase the letters, and replace ``_`` / `` `` with
``-``.  This module computes that correction and applies it as a
*minimal, targeted textual replacement* of the single ``name:`` value
line in the on-disk ``SKILL.md`` — the rest of the file (the remaining
frontmatter and the entire body) is preserved byte-for-byte.

The foundry's stdlib-only YAML subset parser does **not** round-trip
(comments, quoting style, key order, and block-scalar layout are lost on
re-serialisation), so this module never re-serialises the frontmatter.
It rewrites exactly one line.

Two classes of problem are intentionally **not** auto-fixed because the
correct resolution requires human judgement:

* ``name`` does not match the directory name — the author must decide
  whether to rename the directory or change the field.
* the description exceeds the maximum length — truncating would lose
  meaning.

Both are reported as "manual fix needed" findings so a clean ``--fix``
run is never mistaken for "the skill conforms".

Name normalization is folded into the same ``validate_skill.py
--fix``/``--fix --apply`` preview/apply flow that drives the
path-resolution rewriter (``lib/path_rewriter.py``): ``compute_name_fix_plan``
computes the would-be change without touching disk (the preview the bare
``--fix`` reports), and ``write_name_fix`` performs the single-line
rewrite under ``--fix --apply``.

All functions return findings as ``(errors, passes)``-style tuples per
the repo convention; none raise for a validation outcome.
"""

import os
import re

from .constants import (
    LEVEL_FAIL,
    LEVEL_INFO,
    MAX_DESCRIPTION_CHARS,
    RE_NAME_FORMAT,
)
from .frontmatter import split_frontmatter


# Matches a frontmatter ``name:`` line and captures the three spans the
# rewriter must preserve around the value: the ``name:`` key plus the
# whitespace after the colon (group ``prefix``), the value itself
# (group ``value``), and any trailing whitespace before the line
# terminator (group ``trailing``).  Anchored at line start so a ``name:``
# appearing inside a folded ``description`` block (which would be
# indented) is never matched.  ``re.MULTILINE`` lets ``^``/``$`` bind to
# physical line boundaries within the frontmatter text.
_RE_NAME_LINE = re.compile(
    r"^(?P<prefix>name:[ \t]*)(?P<value>.*?)(?P<trailing>[ \t]*)$",
    re.MULTILINE,
)


def compute_safe_name(name: str) -> str:
    """Return *name* with the three safe, deterministic fixes applied.

    Lowercases every character and replaces underscores and spaces with
    hyphens.  Tabs in a value are treated like spaces.  This is a pure
    string transform — it does not consult the directory name, the
    length limit, or the format regex; the caller decides whether the
    result is worth writing.
    """
    fixed = name.lower()
    fixed = fixed.replace("_", "-")
    fixed = fixed.replace(" ", "-")
    fixed = fixed.replace("\t", "-")
    return fixed


def compute_name_fix(
    current_name: str, dir_name: str,
) -> tuple[str | None, list[str], list[str]]:
    """Compute the safe ``name`` fix and the findings for one skill.

    Returns ``(new_name, applied, manual)`` where:

    * ``new_name`` is the corrected ``name`` value when at least one
      safe fix changes it, else ``None`` (nothing to write).
    * ``applied`` is a list of ``INFO``-level finding strings describing
      each safe transformation that fired.
    * ``manual`` is a list of ``FAIL``-level finding strings for the
      ambiguous problems this fixer deliberately does not touch
      (directory mismatch).  Description-length is reported by
      :func:`compute_description_manual_finding` because it needs the
      description value, not the name.

    Directory mismatch is evaluated against the *fixed* name so a skill
    whose only divergence was casing/underscores does not report a
    spurious mismatch after the fix lands.  An empty or whitespace-only
    ``current_name`` yields no fix and no manual finding — that is a
    spec FAIL the regular validator already reports, and inventing a
    name here would be exactly the kind of judgement call this fixer
    avoids.
    """
    applied: list[str] = []
    manual: list[str] = []

    if not current_name or not current_name.strip():
        return None, applied, manual

    fixed = compute_safe_name(current_name)

    if fixed != current_name:
        if current_name.lower() != current_name:
            applied.append(
                f"{LEVEL_INFO}: [foundry] 'name' lowercased "
                f"from '{current_name}' to '{current_name.lower()}'"
            )
        if "_" in current_name:
            applied.append(
                f"{LEVEL_INFO}: [foundry] 'name' underscores replaced "
                "with hyphens"
            )
        if " " in current_name or "\t" in current_name:
            applied.append(
                f"{LEVEL_INFO}: [foundry] 'name' spaces replaced "
                "with hyphens"
            )

    effective_name = fixed if applied else current_name

    if effective_name != dir_name:
        manual.append(
            f"{LEVEL_FAIL}: [spec] manual fix needed — 'name' "
            f"('{effective_name}') does not match directory name "
            f"('{dir_name}'); rename the directory or update the field "
            "by hand"
        )

    new_name = fixed if applied else None
    return new_name, applied, manual


def compute_description_manual_finding(description: str) -> list[str]:
    """Return a manual-fix finding when *description* is over the limit.

    Truncating a description loses meaning, so the fixer never edits it;
    it surfaces a ``FAIL``-level "manual fix needed" string instead.
    Returns an empty list when the description is within the limit (or
    empty — the regular validator already FAILs an empty description).
    """
    if description and len(description) > MAX_DESCRIPTION_CHARS:
        return [
            f"{LEVEL_FAIL}: [spec] manual fix needed — 'description' "
            f"exceeds {MAX_DESCRIPTION_CHARS} characters "
            f"({len(description)} chars); shorten it by hand"
        ]
    return []


def rewrite_name_line(content: str, new_name: str) -> str | None:
    """Return *content* with only the frontmatter ``name:`` value replaced.

    The replacement is line-targeted: the ``name:`` key, the spacing
    after the colon, and any trailing whitespace are preserved exactly;
    only the value token changes.  Everything outside that one line —
    the rest of the frontmatter and the entire body — is returned
    byte-for-byte.

    Returns the rewritten text, or ``None`` when the ``name:`` line
    cannot be located inside the frontmatter block (no frontmatter, no
    closing delimiter, or no ``name:`` key).  ``None`` signals the
    caller to leave the file untouched rather than guess.
    """
    frontmatter_raw, _body_raw = split_frontmatter(content)
    if frontmatter_raw is None:
        return None

    # Resolve the span of the frontmatter text inside *content* so the
    # substitution is confined to it — a ``name:`` literal in the body
    # (e.g. inside a fenced YAML example) must never be touched.  The
    # opening delimiter is the first line; the frontmatter text follows
    # it.  ``split_frontmatter`` returns the inner block verbatim, so
    # locating it by ``find`` from just past the opener is exact.
    open_end = content.find("\n")
    if open_end == -1:
        return None
    fm_start = open_end + 1
    fm_end = fm_start + len(frontmatter_raw)
    fm_text = content[fm_start:fm_end]

    replaced = False

    def _sub(match: re.Match) -> str:
        nonlocal replaced
        if replaced:
            return match.group(0)
        replaced = True
        return f"{match.group('prefix')}{new_name}{match.group('trailing')}"

    new_fm = _RE_NAME_LINE.sub(_sub, fm_text, count=1)
    if not replaced:
        return None
    return content[:fm_start] + new_fm + content[fm_end:]


def compute_name_fix_plan(
    skill_md_path: str,
) -> tuple[str | None, list[str], list[str], list[str]]:
    """Compute the safe ``name`` fix for *skill_md_path* without writing.

    Reads the SKILL.md, computes the safe name fix against the enclosing
    directory name, and reports the manual-fix-needed items — but never
    touches disk.  This is the *preview* half of the unified
    ``--fix``/``--fix --apply`` flow: ``validate_skill.py --fix`` calls
    this to report the would-be change, then calls :func:`write_name_fix`
    only when ``--apply`` is also passed.

    Returns ``(new_name, applied, manual, errors)``:

    * ``new_name`` — the corrected ``name`` value when at least one safe
      fix changes it, else ``None`` (nothing to apply).
    * ``applied`` — ``INFO`` findings for each safe transformation that
      the fix would perform.
    * ``manual`` — ``FAIL`` "manual fix needed" findings (directory
      mismatch, over-length description).
    * ``errors`` — ``FAIL`` findings for structural / I/O failures (file
      missing / unreadable, no parseable frontmatter, no ``name:`` key).
      These keep the function from raising for an I/O or structural
      problem, matching the repo's "validation never raises" convention.

    The skill directory name is taken from the parent of *skill_md_path*.
    """
    applied: list[str] = []
    manual: list[str] = []
    errors: list[str] = []

    skill_dir = os.path.dirname(os.path.abspath(skill_md_path))
    dir_name = os.path.basename(skill_dir)

    try:
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeError) as exc:
        errors.append(
            f"{LEVEL_FAIL}: [foundry] cannot read SKILL.md "
            f"({exc.__class__.__name__}: {exc})"
        )
        return None, applied, manual, errors

    frontmatter_raw, _body_raw = split_frontmatter(content)
    if frontmatter_raw is None:
        errors.append(
            f"{LEVEL_FAIL}: [spec] no YAML frontmatter found — "
            "cannot locate the 'name' field to fix"
        )
        return None, applied, manual, errors

    current_name = _extract_name_value(content)
    if current_name is None:
        errors.append(
            f"{LEVEL_FAIL}: [spec] no 'name' field in frontmatter — "
            "nothing to fix"
        )
        return None, applied, manual, errors

    new_name, applied, manual = compute_name_fix(current_name, dir_name)
    manual.extend(
        compute_description_manual_finding(_extract_description_value(content))
    )
    return new_name, applied, manual, errors


def write_name_fix(
    skill_md_path: str, new_name: str,
) -> tuple[bool, list[str]]:
    """Write *new_name* into the SKILL.md ``name:`` line at *skill_md_path*.

    The *apply* half of the unified flow — called only under
    ``--fix --apply`` with a *new_name* already computed by
    :func:`compute_name_fix_plan`.  Rewrites the single ``name:`` line in
    place (preserving the rest of the file byte-for-byte, written with
    ``newline="\\n"``) and returns ``(modified, errors)``:

    * ``modified`` — ``True`` only when the file was actually rewritten.
    * ``errors`` — ``FAIL`` findings for an unreadable file, a
      non-locatable ``name:`` line, or a write error.  Never raises for
      an I/O or structural problem.

    A computed value that already matches the on-disk bytes leaves the
    file untouched (``modified`` is ``False``) — no read-modify-write of
    identical bytes.
    """
    errors: list[str] = []

    try:
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeError) as exc:
        errors.append(
            f"{LEVEL_FAIL}: [foundry] cannot read SKILL.md "
            f"({exc.__class__.__name__}: {exc})"
        )
        return False, errors

    rewritten = rewrite_name_line(content, new_name)
    if rewritten is None:
        errors.append(
            f"{LEVEL_FAIL}: [foundry] could not locate the 'name:' line "
            "for in-place rewrite — leaving the file untouched"
        )
        return False, errors

    if rewritten == content:
        # Defensive: the computed value matched what is already on disk.
        return False, errors

    try:
        with open(skill_md_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(rewritten)
    except (OSError, UnicodeError) as exc:
        errors.append(
            f"{LEVEL_FAIL}: [foundry] cannot write SKILL.md "
            f"({exc.__class__.__name__}: {exc})"
        )
        return False, errors

    return True, errors


def _extract_name_value(content: str) -> str | None:
    """Return the raw ``name:`` value from the frontmatter, or ``None``.

    Reads only the frontmatter block so a ``name:`` literal in the body
    is never picked up.  Returns the trimmed value (which may be an
    empty string when the field is present but blank), or ``None`` when
    no ``name:`` key exists in the frontmatter.
    """
    frontmatter_raw, _body_raw = split_frontmatter(content)
    if frontmatter_raw is None:
        return None
    match = _RE_NAME_LINE.search(frontmatter_raw)
    if match is None:
        return None
    return match.group("value").strip()


def _extract_description_value(content: str) -> str:
    """Return a best-effort single-line ``description:`` value.

    Used only to decide whether to emit the over-length manual finding,
    so it does not need to reconstruct folded block scalars — it reads
    the inline value on the ``description:`` line.  Returns an empty
    string when no inline ``description:`` value is present (a folded
    ``description: >`` block yields the empty marker line, which cannot
    exceed the limit on its own and is left to the regular validator).
    """
    frontmatter_raw, _body_raw = split_frontmatter(content)
    if frontmatter_raw is None:
        return ""
    desc_re = re.compile(
        r"^description:[ \t]*(?P<value>.*?)[ \t]*$", re.MULTILINE,
    )
    match = desc_re.search(frontmatter_raw)
    if match is None:
        return ""
    value = match.group("value").strip()
    # A folded/literal block scalar marker (``>`` / ``|`` possibly with
    # a chomping indicator) is not the description text itself.
    if value in (">", "|", ">-", "|-", ">+", "|+"):
        return ""
    return value
