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

Three classes of problem are intentionally **not** auto-fixed because
the correct resolution requires human judgement or because the safe
rewrite cannot preserve the source bytes:

* ``name`` does not match the directory name — the author must decide
  whether to rename the directory or change the field.
* the description exceeds the maximum length — truncating would lose
  meaning.
* the safe-fixer's computed candidate still violates the spec (e.g.,
  consecutive hyphens or an invalid leading/trailing hyphen after the
  transform), or the raw ``name:`` line carries quoted scalars or
  inline ``#`` comments that a minimal single-line rewrite would
  silently strip.

All three are reported as "manual fix needed" findings so a clean
``--fix`` run is never mistaken for "the skill conforms".

Name normalization is folded into the same ``validate_skill.py
--fix``/``--fix --apply`` preview/apply flow that drives the
path-resolution rewriter (``lib/path_rewriter.py``): ``compute_name_fix_plan``
computes the would-be change without touching disk (the preview the bare
``--fix`` reports), and ``write_name_fix`` performs the single-line
rewrite under ``--fix --apply``.

The plan also reports the exact ``validate_name`` / over-length-description
FAIL strings the fixer takes ownership of (``owned_fails``).  The
``validate_skill.py --fix`` driver suppresses *only* those strings from
the generic ``non_path_fails`` bucket — every other name-related FAIL
flows through unchanged so a partial-fix run cannot mask unresolved
spec violations.

All functions return findings as ``(errors, passes)``-style tuples per
the repo convention; none raise for a validation outcome.
"""

import os
import re

from .constants import (
    LEVEL_FAIL,
    LEVEL_INFO,
    MAX_DESCRIPTION_CHARS,
)
from .frontmatter import split_frontmatter
from .validation import validate_name
from .yaml_parser import parse_yaml_subset


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


# Marker substring used to recognise the ``validate_name`` dir-mismatch
# FAIL.  Defined once so the ownership and refusal logic cannot drift
# from the exact wording in ``validation.validate_name``.
_DIR_MISMATCH_MARKER = "does not match directory name"


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
) -> tuple[str | None, list[str], list[str], list[str]]:
    """Compute the safe ``name`` fix and the findings for one skill.

    Returns ``(new_name, applied, manual, owned_fails)`` where:

    * ``new_name`` is the corrected ``name`` value when at least one
      safe fix changes it AND the computed candidate would pass
      ``validate_name`` (modulo a dir-mismatch, which is reported as a
      manual finding rather than a spec FAIL).  Otherwise ``None``.
    * ``applied`` is a list of ``INFO``-level finding strings describing
      each safe transformation that fired.
    * ``manual`` is a list of ``FAIL``-level finding strings for the
      ambiguous problems this fixer deliberately does not touch
      (directory mismatch, or a computed candidate that still violates
      the spec).  Description-length is reported by
      :func:`compute_description_manual_finding` because it needs the
      description value, not the name.
    * ``owned_fails`` is the list of exact ``validate_name`` FAIL
      strings the planner takes ownership of — the FAILs the fix
      *would* resolve when applied, plus any dir-mismatch FAIL that
      this plan surfaces as a manual finding instead.  The caller
      suppresses exactly these from its generic FAIL bucket so a name
      FAIL that the safe fixer does *not* resolve (empty name, length,
      Windows reserved name, etc.) is never silently swallowed.

    Directory mismatch is evaluated against the *fixed* name so a skill
    whose only divergence was casing/underscores does not report a
    spurious mismatch after the fix lands.  An empty or whitespace-only
    ``current_name`` yields no fix, no manual finding, and no owned
    FAILs — that is a spec FAIL the regular validator already reports
    on its own.
    """
    applied: list[str] = []
    manual: list[str] = []
    owned: list[str] = []

    if not current_name or not current_name.strip():
        return None, applied, manual, owned

    current_validation, _ = validate_name(current_name, dir_name)
    current_fails = [e for e in current_validation if e.startswith(LEVEL_FAIL)]

    fixed = compute_safe_name(current_name)

    fixed_validation, _ = validate_name(fixed, dir_name)
    fixed_fails = [e for e in fixed_validation if e.startswith(LEVEL_FAIL)]

    # Residual FAILs *after* applying the safe fix.  Exclude the
    # dir-mismatch FAIL because it is surfaced as a manual finding by
    # this planner, not as a regular spec FAIL — keeping it in the
    # residual would refuse safe fixes for any skill whose name happens
    # to differ from its directory.
    residual = [e for e in fixed_fails if _DIR_MISMATCH_MARKER not in e]

    transforms: list[str] = []
    if fixed != current_name:
        if current_name.lower() != current_name:
            transforms.append(
                f"{LEVEL_INFO}: [foundry] 'name' lowercased "
                f"from '{current_name}' to '{current_name.lower()}'"
            )
        if "_" in current_name:
            transforms.append(
                f"{LEVEL_INFO}: [foundry] 'name' underscores replaced "
                "with hyphens"
            )
        if " " in current_name or "\t" in current_name:
            transforms.append(
                f"{LEVEL_INFO}: [foundry] 'name' spaces replaced "
                "with hyphens"
            )

    if residual:
        # The safe-fix candidate would still violate the spec (e.g.,
        # ``my__skill`` → ``my--skill`` produces consecutive hyphens).
        # Refuse to propose a fix: every original ``validate_name`` FAIL
        # flows through the caller's generic bucket unchanged.  Emit a
        # manual finding so the user sees *why* the fixer stood down
        # without having to reverse-engineer it from the FAIL list.
        manual.append(
            f"{LEVEL_FAIL}: [spec] manual fix needed — 'name' "
            f"('{current_name}') cannot be safely normalized "
            f"(candidate '{fixed}' still violates the spec); rename "
            "the field by hand"
        )
        return None, [], manual, []

    effective_name = fixed if transforms else current_name
    if effective_name != dir_name:
        manual.append(
            f"{LEVEL_FAIL}: [spec] manual fix needed — 'name' "
            f"('{effective_name}') does not match directory name "
            f"('{dir_name}'); rename the directory or update the field "
            "by hand"
        )

    new_name = fixed if transforms else None
    applied = transforms

    fixed_fails_set = set(fixed_fails)
    owned = [e for e in current_fails if e not in fixed_fails_set]
    # The dir-mismatch FAIL is owned by this plan when it surfaces a
    # manual finding for it, even if the FAIL also survives the fix
    # (which happens when the fixed name still differs from dir_name).
    if any(_DIR_MISMATCH_MARKER in e for e in manual):
        for fail in current_fails:
            if _DIR_MISMATCH_MARKER in fail and fail not in owned:
                owned.append(fail)
    return new_name, applied, manual, owned


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
    closing delimiter, no ``name:`` key) **or** when the raw value
    carries a quoted scalar or an inline ``#`` comment that the
    minimal line rewriter would silently strip.  ``None`` signals the
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

    raw_matches = list(_RE_NAME_LINE.finditer(fm_text))
    if not raw_matches:
        return None
    if len(raw_matches) > 1:
        # Defense-in-depth: the planner already refuses duplicate-key
        # frontmatter, but the line rewriter is also called directly
        # from tests and any future caller.  Touching the first match
        # while ``parse_yaml_subset`` reads the last would silently
        # rewrite the wrong line.
        return None
    raw_value = raw_matches[0].group("value")
    if _raw_value_blocks_rewrite(raw_value):
        return None

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
) -> tuple[str | None, list[str], list[str], list[str], list[str]]:
    """Compute the safe ``name`` fix for *skill_md_path* without writing.

    Reads the SKILL.md, computes the safe name fix against the enclosing
    directory name, and reports the manual-fix-needed items — but never
    touches disk.  This is the *preview* half of the unified
    ``--fix``/``--fix --apply`` flow: ``validate_skill.py --fix`` calls
    this to report the would-be change, then calls :func:`write_name_fix`
    only when ``--apply`` is also passed.

    Returns ``(new_name, applied, manual, errors, owned_fails)``:

    * ``new_name`` — the corrected ``name`` value when at least one safe
      fix changes it AND the result would pass ``validate_name`` cleanly
      (a surviving dir-mismatch is surfaced as a manual finding, not as
      a refusal).  ``None`` otherwise.
    * ``applied`` — ``INFO`` findings for each safe transformation that
      the fix would perform.
    * ``manual`` — ``FAIL`` "manual fix needed" findings: directory
      mismatch, over-length description, the safe candidate still
      violates the spec, or the raw ``name:`` line carries a quote /
      inline ``#`` comment that a minimal line rewrite cannot preserve.
    * ``errors`` — ``FAIL`` findings for structural / I/O failures (file
      missing / unreadable, no parseable frontmatter, no ``name:`` key,
      ``name:`` value is not a string scalar).  These keep the function
      from raising for an I/O or structural problem, matching the
      repo's "validation never raises" convention.
    * ``owned_fails`` — the exact ``validate_name`` /
      validate-description FAIL strings this plan takes ownership of;
      the caller suppresses *only* these from its generic FAIL bucket
      so a name FAIL the fixer does not resolve (empty name, length,
      Windows reserved name, etc.) is never silently swallowed.

    The skill directory name is taken from the parent of *skill_md_path*.
    """
    applied: list[str] = []
    manual: list[str] = []
    errors: list[str] = []
    owned: list[str] = []

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
        return None, applied, manual, errors, owned

    frontmatter_raw, _body_raw = split_frontmatter(content)
    if frontmatter_raw is None:
        errors.append(
            f"{LEVEL_FAIL}: [spec] no YAML frontmatter found — "
            "cannot locate the 'name' field to fix"
        )
        return None, applied, manual, errors, owned

    try:
        parsed_fm = parse_yaml_subset(frontmatter_raw.strip())
    except (ValueError, KeyError) as exc:
        errors.append(
            f"{LEVEL_FAIL}: [foundry] cannot parse SKILL.md frontmatter "
            f"({exc.__class__.__name__}: {exc})"
        )
        return None, applied, manual, errors, owned

    if "name" not in parsed_fm:
        errors.append(
            f"{LEVEL_FAIL}: [spec] no 'name' field in frontmatter — "
            "nothing to fix"
        )
        return None, applied, manual, errors, owned

    raw_value_matches = list(_RE_NAME_LINE.finditer(frontmatter_raw))
    if not raw_value_matches:
        # The parser saw a ``name`` key (flow-style mapping, alias, or
        # similar) but the line-oriented rewriter cannot target a single
        # physical line.  Refuse rather than guess.
        errors.append(
            f"{LEVEL_FAIL}: [foundry] 'name:' is not on its own line — "
            "the minimal line rewriter cannot target it; normalize the "
            "frontmatter by hand"
        )
        return None, applied, manual, errors, owned
    if len(raw_value_matches) > 1:
        # Duplicate ``name:`` keys: ``parse_yaml_subset`` resolves to
        # the *last* mapping entry, but a line-targeted rewrite would
        # only update the *first* — applying the fix would leave the
        # effective value untouched while ownership-suppressing the
        # validator FAILs, so ``--fix --apply`` could report success on
        # a still-invalid skill.  The duplicate-key shape is itself a
        # frontmatter authoring error the user needs to resolve by hand.
        errors.append(
            f"{LEVEL_FAIL}: [foundry] multiple 'name:' keys in "
            f"frontmatter ({len(raw_value_matches)} found) — "
            "parse_yaml_subset would use the last and the line "
            "rewriter would touch the first; remove the duplicates by "
            "hand"
        )
        return None, applied, manual, errors, owned
    raw_value_match = raw_value_matches[0]

    current_name = parsed_fm["name"]
    if not isinstance(current_name, str):
        errors.append(
            f"{LEVEL_FAIL}: [foundry] 'name' value is not a string "
            f"scalar (got {type(current_name).__name__}) — cannot fix"
        )
        return None, applied, manual, errors, owned

    raw_value = raw_value_match.group("value")
    if _raw_value_blocks_rewrite(raw_value):
        manual.append(
            f"{LEVEL_FAIL}: [spec] manual fix needed — the 'name:' "
            "line carries a quoted scalar or an inline '#' comment; "
            "the minimal line rewriter would silently strip that "
            "syntax — normalize the value by hand"
        )
        return None, applied, manual, errors, owned

    new_name, applied, fix_manual, fix_owned = compute_name_fix(
        current_name, dir_name,
    )
    manual.extend(fix_manual)
    owned.extend(fix_owned)

    description = _extract_description_value(parsed_fm)
    desc_manual = compute_description_manual_finding(description)
    if desc_manual:
        manual.extend(desc_manual)
        # Own the exact FAIL string ``validate_skill`` emits so the
        # caller does not double-report it.  Mirrors the wording in
        # ``validate_skill.validate_frontmatter`` — the two strings
        # must stay in sync.  ``description`` is the *parsed* scalar
        # (quotes and inline comments already stripped) so its length
        # matches the value the validator measures.
        owned.append(
            f"{LEVEL_FAIL}: [spec] 'description' exceeds "
            f"{MAX_DESCRIPTION_CHARS} characters "
            f"({len(description)} chars)"
        )
    return new_name, applied, manual, errors, owned


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


def _raw_value_blocks_rewrite(raw_value: str) -> bool:
    """Return ``True`` when the raw ``name:`` line carries quote/comment syntax.

    The minimal line rewriter cannot preserve a quoted scalar wrapper or
    an inline ``# comment`` — applying it would silently strip both.
    Detect either form on the captured value span so the planner can
    refuse to rewrite rather than lose the source bytes.  ``#`` is only
    flagged when preceded by whitespace, matching the YAML subset
    parser's inline-comment recogniser; that keeps a ``#`` embedded in a
    plain scalar (``name: foo#bar`` → YAML value ``foo#bar``) from being
    misclassified.
    """
    trimmed = raw_value.strip()
    if (
        len(trimmed) >= 2
        and trimmed[0] in ('"', "'")
        and trimmed[-1] == trimmed[0]
    ):
        return True
    if trimmed[:1] in ('"', "'"):
        # Opened a quote but did not close on the same line — out of
        # scope for the minimal rewriter.
        return True
    for index in range(1, len(raw_value)):
        if raw_value[index] == "#" and raw_value[index - 1] in (" ", "\t"):
            return True
    return False


def _extract_description_value(parsed_fm: dict) -> str:
    """Return the parsed ``description`` scalar, regardless of style.

    Used to decide whether to emit the over-length manual finding.
    Returns the parsed value from ``parsed_fm`` — ``parse_yaml_subset``
    already handles every supported scalar style (plain, quoted, folded
    ``>``, literal ``|``, with chomping indicators) so a folded
    over-length description is detected the same way an inline one is,
    keeping the ``--fix`` help text's "manual fix needed" claim honest
    across scalar styles.  The validator measures length on the same
    parsed value, so the planner's owned FAIL string stays
    byte-identical with the validator's.

    Returns ``""`` when there is no ``description`` key or when the
    parsed value is not a string scalar.
    """
    value = parsed_fm.get("description", "")
    if not isinstance(value, str):
        return ""
    return value
