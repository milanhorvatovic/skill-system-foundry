"""Safe, deterministic auto-fixes for the SKILL.md ``name`` frontmatter.

When ``validate_name`` FAILs because the ``name`` field carries
uppercase characters, underscores, or in-value whitespace, the
corrected value is unambiguous: lowercase the letters, and replace
``_``, space, and tab with ``-``.  This module computes that
correction and applies it as a *minimal, targeted textual replacement*
of the single ``name:`` value line in the on-disk ``SKILL.md`` — the
rest of the file (the remaining frontmatter and the entire body) is
preserved verbatim, with one caveat for CRLF checkouts (below).

The foundry's stdlib-only YAML subset parser does **not** round-trip
(comments, quoting style, key order, and block-scalar layout are lost on
re-serialisation), so this module never re-serialises the frontmatter.
It rewrites exactly one line.

**Line-ending normalization.** ``write_name_fix`` reads SKILL.md in
text mode (universal-newline translation collapses ``\\r\\n`` to
``\\n`` on input) and writes back with ``newline="\\n"`` per the
repo-wide LF-on-write convention (see ``CLAUDE.md``).  A CRLF-on-disk
SKILL.md is therefore normalized to LF when any safe fix lands; the
"preserve the rest of the file" guarantee holds at the *content* level
(every body byte and every untouched frontmatter byte is preserved
verbatim) but not at the *line-ending* level on a CRLF checkout.  The
``--apply`` path is otherwise a no-op when the computed value already
matches the on-disk bytes, so an LF-only checkout is touched only when
the safe fix actually changes the ``name:`` value.

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

Public function shapes:

* :func:`compute_safe_name` — ``str → str`` (pure transform).
* :func:`compute_name_fix` — ``(new_name, applied, manual, owned_fails)``.
* :func:`compute_description_manual_finding` — ``str → list[str]``.
* :func:`compute_name_fix_plan` — ``(new_name, applied, manual, errors,
  owned_fails)``.
* :func:`rewrite_name_line` — ``(content, new_name) → str | None``.
* :func:`write_name_fix` — ``(modified, errors)``.

None of them raise for a validation, structural, or I/O outcome —
errors are reported through the relevant tuple slot per the repo's
"validation never raises" convention.
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
# physical line boundaries within the frontmatter text.  The colon must
# be flush against ``name`` (no leading whitespace) because the
# rewriter does an exact line replacement — see ``_RE_NAME_KEY_ANY``
# below for the relaxed regex used by the duplicate-key guard.
_RE_NAME_LINE = re.compile(
    r"^(?P<prefix>name:[ \t]*)(?P<value>.*?)(?P<trailing>[ \t]*)$",
    re.MULTILINE,
)

# Matches *any* top-level ``name`` mapping key the parser would
# accept, including ``name :`` with whitespace before the colon.  Used
# only by the duplicate-key guard so a mixed-form pair (``name: First``
# + ``name : Last``) cannot bypass detection — ``parse_yaml_subset``
# would silently pick the last entry while the line rewriter would
# touch the first, producing a false successful fix.  This regex is
# not used for the rewrite span because the rewrite must preserve the
# exact ``name:`` line shape, which the strict ``_RE_NAME_LINE`` above
# captures.
_RE_NAME_KEY_ANY = re.compile(r"^name[ \t]*:", re.MULTILINE)


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
            # Tabs and spaces are both replaced by hyphens; the
            # message uses "whitespace" so the wording does not
            # imply only space characters triggered the rewrite.
            transforms.append(
                f"{LEVEL_INFO}: [foundry] 'name' whitespace replaced "
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
    closing ``---`` delimiter, more than one ``name:`` line, no
    ``name:`` key) **or** when the raw value carries a quoted scalar
    or an inline ``#`` comment that the minimal line rewriter would
    silently strip.  ``None`` signals the caller to leave the file
    untouched rather than guess.
    """
    frontmatter_raw, body_raw = split_frontmatter(content)
    if frontmatter_raw is None:
        return None
    if body_raw is None:
        # ``split_frontmatter`` returns ``(frontmatter, None)`` when an
        # opening ``---`` is found but no closing ``---`` exists.  The
        # file is structurally malformed; refuse to rewrite rather than
        # touch a SKILL.md the parser cannot even bound.
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

    # Defense-in-depth duplicate-key guard.  The planner already
    # refuses duplicate-key frontmatter (and uses ``_RE_NAME_KEY_ANY``
    # to catch mixed-form pairs like ``name: First`` + ``name : Last``
    # that the strict regex would miss), but ``rewrite_name_line`` is
    # also called directly from tests and any future caller, so it
    # repeats the same relaxed check here.  Touching the first strict
    # match while ``parse_yaml_subset`` reads a later relaxed match
    # would silently rewrite the wrong line.
    if len(_RE_NAME_KEY_ANY.findall(fm_text)) > 1:
        return None
    raw_matches = list(_RE_NAME_LINE.finditer(fm_text))
    if not raw_matches:
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

    frontmatter_raw, body_raw = split_frontmatter(content)
    if frontmatter_raw is None:
        errors.append(
            f"{LEVEL_FAIL}: [spec] no YAML frontmatter found — "
            "cannot locate the 'name' field to fix"
        )
        return None, applied, manual, errors, owned
    if body_raw is None:
        # Opening ``---`` without a closing delimiter: the frontmatter
        # bounds are undefined, so any rewrite could land on the wrong
        # side of the file.  Surface the structural failure and refuse
        # rather than touch a SKILL.md the parser cannot even bound.
        errors.append(
            f"{LEVEL_FAIL}: [spec] frontmatter has no closing '---' "
            "delimiter — cannot safely locate the 'name:' line"
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

    # Duplicate ``name`` keys are unambiguously broken frontmatter
    # regardless of whether the planner would propose a rewrite — the
    # parser silently picks one and the rewriter would touch the
    # other.  The error fires up front, before any other reasoning.
    # The duplicate guard uses the relaxed ``_RE_NAME_KEY_ANY`` regex
    # so a mixed-form pair (``name: First`` + ``name : Last``) cannot
    # bypass detection — the strict ``_RE_NAME_LINE`` below is still
    # used to locate the *rewriteable* line for the apply path.
    name_key_count = len(_RE_NAME_KEY_ANY.findall(frontmatter_raw))
    if name_key_count > 1:
        errors.append(
            f"{LEVEL_FAIL}: [foundry] multiple 'name:' keys in "
            f"frontmatter ({name_key_count} found) — "
            "parse_yaml_subset would use the last and the line "
            "rewriter would touch the first; remove the duplicates by "
            "hand"
        )
        return None, applied, manual, errors, owned
    raw_value_matches = list(_RE_NAME_LINE.finditer(frontmatter_raw))
    raw_value_match = raw_value_matches[0] if raw_value_matches else None

    current_name = parsed_fm["name"]
    if not isinstance(current_name, str):
        errors.append(
            f"{LEVEL_FAIL}: [foundry] 'name' value is not a string "
            f"scalar (got {type(current_name).__name__}) — cannot fix"
        )
        return None, applied, manual, errors, owned

    new_name, applied, fix_manual, fix_owned = compute_name_fix(
        current_name, dir_name,
    )

    # Rewrite-mechanics guards (no locatable ``name:`` line, quoted
    # scalar, inline ``#`` comment) only matter when the planner is
    # actually proposing a write.  A SKILL.md whose ``name`` is
    # already valid YAML and already passes ``validate_name`` —
    # e.g. ``name : my-skill`` with whitespace before the colon, or
    # ``name: "my-skill"`` as a quoted scalar — must not fail ``--fix``
    # just because its formatting is unusual.  When the planner has
    # nothing to apply (``new_name is None``), skip the guards so the
    # plan returns clean; otherwise emit the relevant refusal, discard
    # the would-be fix, and surrender ownership so the regular
    # validator's FAILs flow through.
    if new_name is not None:
        if raw_value_match is None:
            errors.append(
                f"{LEVEL_FAIL}: [foundry] 'name:' is not on its own "
                "line — the minimal line rewriter cannot target it; "
                "normalize the frontmatter by hand"
            )
            return None, [], manual, errors, []
        raw_value = raw_value_match.group("value")
        if _raw_value_blocks_rewrite(raw_value):
            manual.append(
                f"{LEVEL_FAIL}: [spec] manual fix needed — the 'name:' "
                "line carries a quoted scalar, an inline '#' comment, "
                "or a block-scalar header (|, >, |-, >-, |+, >+); the "
                "minimal line rewriter would silently strip that "
                "syntax or leave the indented scalar body behind — "
                "normalize the value by hand"
            )
            return None, [], manual, errors, []

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
    :func:`compute_name_fix_plan`.  Rewrites the single ``name:`` line
    in place (every body byte and every untouched frontmatter byte is
    preserved verbatim, written with ``newline="\\n"`` per the
    repo-wide LF-on-write convention — see the module docstring's
    note on CRLF-on-disk checkouts) and returns ``(modified, errors)``:

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
    refuse to rewrite rather than lose the source bytes.

    Block-scalar headers (``|``, ``>``, plus the chomping-modifier
    variants ``|-`` / ``>-`` / ``|+`` / ``>+``) appear on the ``name:``
    line alone, with the scalar text indented on the following lines.
    ``parse_yaml_subset`` assembles those into an ordinary string, so
    the planner would otherwise propose a rewrite — and the line-only
    rewriter would touch *only* the header line, leaving the indented
    body content as stray YAML the parser then re-reads as separate
    keys.  Block-scalar headers are therefore non-rewriteable.

    ``#`` is only flagged when preceded by a space, matching the exact
    rule ``yaml_parser._strip_inline_comment`` applies
    (``text[i - 1] == " "``); a ``#`` preceded by a tab or embedded in
    a plain scalar (``name: foo#bar`` → YAML value ``foo#bar``) is left
    for the parser to decide, since the parser treats it as part of
    the scalar and the rewriter must not be stricter than the parser's
    view of "what is a comment".
    """
    trimmed = raw_value.strip()
    if trimmed in ("|", ">", "|-", ">-", "|+", ">+"):
        return True
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
        if raw_value[index] == "#" and raw_value[index - 1] == " ":
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
