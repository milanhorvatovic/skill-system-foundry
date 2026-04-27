"""Language-agnostic Markdown fenced-code-block extractor.

Used by the prose-YAML validator (``lib.prose_yaml``) and by the
fence/script tool-coherence rule (``lib.validation``).  Centralising
fence extraction in one place keeps both consumers in lockstep on
fence-edge semantics (column-0 only, exactly three fence characters,
strict closer matching, line-ending normalisation, unterminated-fence
short-circuit).

Frontmatter stripping is **not** the responsibility of this module —
callers that want frontmatter excluded must strip it before invoking
:func:`extract_fences`.  This keeps the extractor purely about fences.
"""

import re


# Deliberate subset of CommonMark's info-string parsing: the language
# token is captured greedily up to the first whitespace (or a fence
# character).  CommonMark allows arbitrary non-backtick characters in
# the info string and does not require whitespace before the suffix,
# so a fence like ``` ```yaml{linenos} ``` would carry the language
# token ``yaml{linenos}`` and fail to match a ``"yaml"`` filter.
# Real-world skill markdown only uses bare language tokens (``yaml``,
# ``bash``, etc.); the subset is acceptable today and the cost of a
# full info-string parser would not be repaid.
_OPEN_FENCE_RE = re.compile(r"^(`{3}|~{3})([^\s`~]*)(\s.*)?$")


def extract_fences(
    markdown_text: str | None,
    *,
    languages: frozenset[str] | None = None,
    fence_chars: frozenset[str] = frozenset({"`", "~"}),
) -> list[dict]:
    """Return one record per fenced code block found in *markdown_text*.

    Fence shape rules:

    - Exactly three identical fence characters at byte offset 0 open a
      fence.  Four or more fence characters at column 0 are ignored
      (matches the existing ``prose_yaml`` invisibility rule).
    - The opener line is followed immediately by an optional language
      token (no leading whitespace between the fence characters and the
      token).  Anything trailing the token after at least one whitespace
      character is treated as a CommonMark info-string suffix and is
      discarded — the language token alone is captured.
    - The closer is a column-0 line of exactly three identical fence
      characters of the **same kind** as the opener (a backtick fence
      closes only on backticks; a tilde fence closes only on tildes).
    - If no closer is found before EOF, the fence is reported as
      ``state="unterminated"`` and scanning stops — the remainder of the
      document is, per CommonMark, inside the unterminated fence and
      cannot contain more openers.

    Filtering:

    - *fence_chars* — set of fence-character kinds the extractor will
      accept as openers.  Default accepts both backtick and tilde.
      Pass ``frozenset({"`"})`` for backtick-only.
    - *languages* — when given, only records whose language token is in
      the set are returned (case-sensitive).  Records that fail this
      filter still consume their range so subsequent fence ordinals are
      not affected.

    Each record dict::

        {
            "ordinal":          int,       # 1-based across returned records
            "language":         str,       # opener language token (may be "")
            "text":             str,       # body, LF-only, no terminator
            "state":            "closed" | "unterminated",
            "fence_marker":     str,       # the literal opener marker, e.g. "```" or "~~~"
            "open_line_index":  int,       # 0-based index of the opener line
            "close_line_index": int | None,  # 0-based index of the closer, or None when unterminated
        }

    Input line endings (CR / CRLF / mixed) are normalised to LF before
    scanning.  Empty / ``None`` input returns ``[]``.
    """
    if not markdown_text:
        return []
    text = markdown_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    records: list[dict] = []
    ordinal = 0
    n = len(lines)
    i = 0
    while i < n:
        opener = _classify_opener(lines[i], fence_chars)
        if opener is None:
            i += 1
            continue
        marker, language = opener
        body: list[str] = []
        j = i + 1
        terminated = False
        close_index: int | None = None
        while j < n:
            if lines[j] == marker:
                terminated = True
                close_index = j
                break
            body.append(lines[j])
            j += 1
        body_text = "\n".join(body)
        record_passes_filter = languages is None or language in languages
        if record_passes_filter:
            ordinal += 1
            record: dict = {
                "ordinal": ordinal,
                "language": language,
                "text": body_text,
                "state": "closed" if terminated else "unterminated",
                "fence_marker": marker,
                "open_line_index": i,
                "close_line_index": close_index,
            }
            records.append(record)
        if not terminated:
            return records
        i = j + 1
    return records


def _classify_opener(
    line: str, fence_chars: frozenset[str],
) -> tuple[str, str] | None:
    """Return ``(marker, language)`` if *line* opens a fence, else ``None``.

    *marker* is the literal three-character opener (``"```"`` or
    ``"~~~"``).  *language* is the token that follows the marker on the
    same line, or the empty string when the opener carries no language
    tag.
    """
    match = _OPEN_FENCE_RE.match(line)
    if not match:
        return None
    marker = match.group(1)
    if marker[0] not in fence_chars:
        return None
    return marker, match.group(2)


def has_fence_with_language(
    markdown_text: str | None,
    languages: frozenset[str],
    *,
    fence_chars: frozenset[str] = frozenset({"`", "~"}),
) -> bool:
    """Return ``True`` when *markdown_text* contains at least one fence
    whose language token is in *languages*.

    Convenience predicate for callers that only need a yes/no answer
    (e.g. the fence/script tool-coherence rule).  Delegates to
    :func:`extract_fences` so the two consumers cannot drift on
    fence-edge semantics.  Skill markdown is small enough that walking
    the full document once is cheaper than maintaining two scanners.
    """
    return bool(
        extract_fences(
            markdown_text,
            languages=languages,
            fence_chars=fence_chars,
        )
    )
