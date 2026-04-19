"""Lightweight YAML-subset parser (no external dependencies).

Handles the subset of YAML used by this framework: key-value pairs,
folded/literal block scalars (> | >- |- |+ >+), nested mappings, scalar
lists, and lists of mappings.  All scalar values are returned as
strings — no type coercion for booleans, numbers, or null.

Outcome buckets
---------------
For any input the parser produces one of three outcomes:

1. **Parse cleanly.** Example: ``key: value\\n``.
2. **Emit a finding** (``FAIL`` / ``WARN`` / ``INFO`` strings appended
   to the optional *findings* list — see ``_check_plain_scalar``).
   Example: ``key: *alias\\n`` emits ``FAIL: [spec] 'key': unquoted
   value starts with '*' …``.
3. **Raise ``ValueError``.** Used for structural failures and the three
   pinned grammar gaps below.

Pinned ``ValueError`` message format
------------------------------------
``"unsupported YAML 1.2.2 construct: <construct-id> (spec §<n.n>)"``

The three canonical ``<construct-id>`` tokens (mirrored in
``configuration.yaml`` under ``yaml_conformance.construct_ids``):

- ``anchor-with-trailing-in-key`` — anchor properties followed by
  trailing key text in mapping-key position (e.g. ``&a key:``); spec §6.9.
- ``indent-indicator-block-scalar`` — block scalar header carrying an
  indentation indicator (e.g. ``key: |2``); spec §8.1.1.
- ``tag-in-mapping-key`` — tag indicator in mapping-key position
  (e.g. ``!!str key:``); spec §6.9.

Plain-scalar usage of anchor / tag indicators in **value** position
remains a ``WARN`` finding rather than a raise — only the mapping-key
position is upgraded.

Line-ending contract (YAML 1.2.2 §5.4)
--------------------------------------
**Input:** ``parse_yaml_subset`` accepts text with LF, CRLF, CR, or
mixed line terminators.  Normalization happens at the top of the
function (defense in depth — text-ingestion boundaries elsewhere
in the codebase normalize too).

**Output:** every string returned by the parser — including block-scalar
contents — uses **LF-only** line terminators regardless of the input
style.  Round-trip callers that re-emit parsed values will see LF even
if the original text used CRLF.
"""

def parse_yaml_subset(text: str | None, findings: list[str] | None = None) -> dict:
    """Parse a limited YAML subset into a Python dict.

    Raises ValueError on structural parse failures.

    If *findings* is a list, plain-scalar warnings/errors are appended
    to it.  If ``None`` (the default), findings are silently discarded.

    Input line endings (LF / CRLF / CR / mixed) are normalized to LF
    on entry; all string values returned use LF-only terminators (see
    module docstring).
    """
    if not text or not text.strip():
        return {}

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = []
    for raw in text.split("\n"):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        cleaned = _strip_inline_comment(stripped)
        if cleaned:
            lines.append((indent, cleaned))

    if not lines:
        return {}

    result, _ = _parse_structure(lines, 0, lines[0][0], findings)
    return result if isinstance(result, dict) else {}


def _raise_unsupported(construct_id: str, spec_section: str) -> None:
    """Raise ``ValueError`` with the pinned grammar-gap message format.

    Format is pinned so corpus fixtures can substring-match on the
    ``<construct-id>`` token without coupling to surrounding wording.
    """
    raise ValueError(
        f"unsupported YAML 1.2.2 construct: {construct_id} "
        f"(spec §{spec_section})"
    )


def _check_mapping_key_construct(key: str) -> None:
    """Raise on the two grammar gaps that surface in mapping-key position.

    "Mapping-key position" means the token appears before the
    first ``:`` on a logical line, outside any flow collection or block
    scalar.  Both ``_parse_mapping`` and the dict-item branch of
    ``_parse_list`` invoke this after extracting *key*.

    Bare ``&anchor`` (no trailing text) is left to the existing
    plain-scalar value check; only the trailing-text variant raises.
    """
    if not key:
        return
    head = key[0]
    if head == "&":
        rest = key[1:]
        for i, ch in enumerate(rest):
            if ch in (" ", "\t"):
                if rest[i:].strip():
                    _raise_unsupported("anchor-with-trailing-in-key", "6.9")
                return
        return
    if head == "!":
        _raise_unsupported("tag-in-mapping-key", "6.9")


def _strip_inline_comment(text: str) -> str:
    """Remove trailing ``# comment``, respecting quoted strings."""
    in_quote = False
    quote_char = None
    for i, ch in enumerate(text):
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
        elif in_quote and ch == quote_char:
            in_quote = False
        elif ch == "#" and not in_quote and i > 0 and text[i - 1] == " ":
            return text[:i].rstrip()
    return text


def _unquote(s: str) -> str:
    """Strip surrounding quotes from a scalar value."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _is_block_scalar_header(s: str) -> bool:
    """Return ``True`` if *s* is a block scalar header this parser supports.

    Matches ``[|>]`` optionally followed by a chomping modifier (``-``
    or ``+``).  Indentation indicators (``1``–``9``) are **not**
    accepted because the block-scalar collection logic does not honour
    them — accepting headers with digits would silently produce
    different values compared to strict YAML 1.2 parsers.
    """
    if not s or s[0] not in ("|", ">"):
        return False
    rest = s[1:]
    if not rest:
        return True
    if len(rest) == 1:
        return rest in "-+"
    return False


def _assemble_block_scalar(header: str, lines: list[str]) -> str:
    """Join block scalar *lines* according to *header* style and chomping."""
    text = " ".join(lines) if header.startswith(">") else "\n".join(lines)
    if "+" in header and lines:
        text += "\n"
    return text


def suggest_quoted_form(value: str) -> str | None:
    """Return *value* wrapped in the safest divergence-free quote style.

    The decision tree avoids escape-dependent recommendations — only
    quote styles that both this parser and strict YAML 1.2 parsers
    interpret identically are suggested:

    - ``None`` when the value contains line breaks or both quote types
      or backslashes that would need escaping (use a block scalar)
    - Single quotes when the value contains no ``'`` (YAML single
      quotes do not interpret escape sequences)
    - Double quotes when the value contains no ``"`` and no ``\\``
    """
    if "\n" in value or "\r" in value:
        return None
    if "'" not in value:
        return "'" + value + "'"
    if '"' not in value and "\\" not in value:
        return '"' + value + '"'
    return None


def _quote_advice(value: str) -> str:
    """Return human-readable quoting advice for a plain scalar value."""
    if "\n" in value or "\r" in value:
        return "use a literal block scalar (|-) — value contains line breaks"
    if "'" not in value:
        return "wrap value in single quotes"
    if '"' not in value and "\\" not in value:
        return "wrap value in double quotes"
    return "use a block scalar (|- preserves newlines; >- folds them) — value contains characters that require escape processing in quoted forms"


def _is_indent_indicator_header(value: str) -> bool:
    """Return ``True`` when *value* is a block-scalar header carrying a
    YAML 1.2 indentation indicator (``|2``, ``|2-``, ``|-2``, ``>+3``…).

    Bare ``|`` / ``>`` and bare chomping headers (``|-``, ``>+``) are
    handled by ``_is_block_scalar_header`` and remain supported.
    """
    if not value or value[0] not in ("|", ">"):
        return False
    rest = value[1:]
    if len(rest) == 1:
        return rest.isdigit() and rest != "0"
    if len(rest) == 2:
        c1, c2 = rest[0], rest[1]
        return (
            (c1.isdigit() and c1 != "0" and c2 in "-+")
            or (c1 in "-+" and c2.isdigit() and c2 != "0")
        )
    return False


def _check_plain_scalar(key: str, value: str, findings: list[str] | None) -> None:
    """Append findings for unquoted plain scalar values that diverge from strict YAML 1.2.

    Raises ``ValueError`` (independent of *findings*) when *value* is a
    block-scalar header carrying an indentation indicator — emits the
    pinned ``unsupported YAML 1.2.2 construct: …`` message format.
    """
    if not value:
        return
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return

    # Indent-indicator block-scalar headers raise unconditionally so the
    # parse-time outcome bucket does not depend on whether the
    # caller passed a findings list.
    if _is_indent_indicator_header(value):
        _raise_unsupported("indent-indicator-block-scalar", "8.1.1")

    if findings is None:
        return

    # Lazy import — loaded after all modules are fully initialised, which
    # avoids the circular dependency (constants imports yaml_parser to
    # parse configuration.yaml at module-load time).
    from .constants import (
        LEVEL_FAIL, LEVEL_WARN,
        PLAIN_SCALAR_INDICATORS, PLAIN_SCALAR_CONTEXT_WHITESPACE,
    )

    ind = PLAIN_SCALAR_INDICATORS
    ws = PLAIN_SCALAR_CONTEXT_WHITESPACE

    advice = _quote_advice(value)
    ch = value[0]

    # Leading-character checks (at most one finding).
    if ch in ind["flow"]:
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            f"'{ch}' (flow indicator) — strict parsers will interpret "
            f"this as a flow collection, not a string; {advice}"
        )
    elif ch in ind["alias"]:
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            "'*' (alias indicator) — strict parsers will treat this as "
            "an alias reference, changing the value or erroring if "
            f"undefined; {advice}"
        )
    elif ch in ind["reserved"]:
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            f"'{ch}' (reserved character) — strict parsers will reject "
            f"this; {advice}"
        )
    elif ch in ind["directive"]:
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            "'%' (directive indicator) — strict parsers will reject this; "
            f"{advice}"
        )
    elif ch in ind["block_entry"]:
        if len(value) == 1 or value[1] in ws:
            findings.append(
                f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
                "'-' followed by whitespace, or is '-' alone (block sequence "
                f"entry) — strict parsers will reject this; {advice}"
            )
    elif ch in ind["mapping_key"]:
        if len(value) == 1 or value[1] in ws:
            findings.append(
                f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
                "'?' followed by whitespace, or is '?' alone (explicit "
                f"mapping key) — strict parsers will reject this; {advice}"
            )
    elif ch in ind["anchor"]:
        if len(value) == 1 or value[1] in ws:
            findings.append(
                f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
                "'&' (anchor indicator) — strict parsers will reject this; "
                f"{advice}"
            )
        else:
            # &<non-whitespace>... — anchor name consumed by strict parsers.
            # Determine whether non-whitespace content exists after the
            # anchor name.  The anchor name ends at the first whitespace
            # character; anything beyond that (ignoring trailing spaces)
            # is the remaining scalar value.
            has_remaining = False
            for j, c in enumerate(value[1:], start=1):
                if c in ws:
                    has_remaining = any(k not in ws for k in value[j + 1:])
                    break
            if has_remaining:
                findings.append(
                    f"{LEVEL_WARN}: [spec] '{key}': unquoted value starts "
                    "with '&' (anchor name consumed by strict parsers, "
                    f"remaining text becomes the value) — {advice}"
                )
            else:
                findings.append(
                    f"{LEVEL_WARN}: [spec] '{key}': unquoted value starts "
                    "with '&' (anchor name consumed by strict parsers, "
                    f"value becomes null) — {advice}"
                )
    elif ch in ind["block_scalar"]:
        # Indent-indicator headers (``|2``, ``>+3``, …) raise earlier in
        # this function; reaching here means ``|abc`` / ``>foo`` style —
        # text in the header position that strict parsers reject.
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            f"'{ch}' followed by text (invalid block scalar header) — "
            f"strict parsers will reject this; {advice}"
        )
    elif ch in ind["tag"]:
        findings.append(
            f"{LEVEL_WARN}: [spec] '{key}': unquoted value starts with "
            "'!' (tag indicator consumed by strict parsers, silently "
            f"altering the value) — {advice}"
        )
    elif ch in ind["quote"]:
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            f"'{ch}' (unterminated quote — no matching closing quote) — "
            f"close the quote, or {advice}"
        )

    # Colon scan — break on first match.
    for i, c in enumerate(value):
        if c == ":":
            if i == len(value) - 1:
                findings.append(
                    f"{LEVEL_FAIL}: [spec] '{key}': unquoted value ends "
                    "with ':' — strict parsers treat this as a mapping "
                    f"key; {advice}"
                )
                break
            if value[i + 1] in ws:
                separator = repr(":" + value[i + 1])
                findings.append(
                    f"{LEVEL_FAIL}: [spec] '{key}': unquoted value "
                    f"contains {separator} — strict parsers treat this as a "
                    f"mapping key; {advice}"
                )
                break


def _parse_structure(lines: list[tuple[int, str]], start: int, base_indent: int, findings: list[str] | None, parent_key: str = "") -> tuple[dict | list, int]:
    """Dispatch to mapping or list parser based on the first token."""
    if start >= len(lines):
        return {}, start
    if lines[start][1].startswith("- "):
        return _parse_list(lines, start, base_indent, findings, parent_key)
    return _parse_mapping(lines, start, base_indent, findings, parent_key)


def _parse_mapping(lines: list[tuple[int, str]], start: int, base_indent: int, findings: list[str] | None, parent_key: str = "") -> tuple[dict, int]:
    """Parse ``key: value`` pairs at *base_indent*."""
    result = {}
    i = start

    while i < len(lines):
        indent, content = lines[i]
        if indent < base_indent:
            break
        if indent > base_indent:
            break

        colon = content.find(":")
        if colon < 0:
            i += 1
            continue

        key = content[:colon].strip()
        _check_mapping_key_construct(key)
        qualified_key = f"{parent_key}.{key}" if parent_key else key
        after = content[colon + 1 :].strip()

        if _is_block_scalar_header(after):
            # Block scalar — collect indented continuation lines.
            i += 1
            scalar_lines = []
            while i < len(lines) and lines[i][0] > base_indent:
                scalar_lines.append(lines[i][1])
                i += 1
            result[key] = _assemble_block_scalar(after, scalar_lines)

        elif after == "":
            # Nested structure (mapping or list).
            i += 1
            if i < len(lines) and lines[i][0] > base_indent:
                nested, i = _parse_structure(lines, i, lines[i][0], findings, qualified_key)
                result[key] = nested
            else:
                result[key] = ""

        else:
            _check_plain_scalar(qualified_key, after, findings)
            result[key] = _unquote(after)
            i += 1

    return result, i


def _parse_list(lines: list[tuple[int, str]], start: int, base_indent: int, findings: list[str] | None, parent_key: str = "") -> tuple[list, int]:
    """Parse ``- item`` entries at *base_indent*."""
    result = []
    i = start

    while i < len(lines):
        indent, content = lines[i]
        if indent != base_indent or not content.startswith("- "):
            break

        item_text = content[2:].strip()
        i += 1

        colon_pos = item_text.find(":")
        if colon_pos < 0:
            # Simple scalar list item.
            if _is_block_scalar_header(item_text):
                # Block scalar — consume indented continuation lines.
                scalar_lines = []
                while i < len(lines) and lines[i][0] > base_indent:
                    scalar_lines.append(lines[i][1])
                    i += 1
                result.append(_assemble_block_scalar(item_text, scalar_lines))
            else:
                # Plain scalar — use parent_key[index] as the finding
                # key so the user knows which list and position.
                item_key = f"{parent_key}[{len(result)}]" if parent_key else f"[{len(result)}]"
                _check_plain_scalar(item_key, item_text, findings)
                result.append(_unquote(item_text))
            continue

        # Dict item inside a list (``- key: value`` with possible continuations).
        first_key = item_text[:colon_pos].strip()
        _check_mapping_key_construct(first_key)
        first_val = item_text[colon_pos + 1 :].strip()
        # Build indexed prefix for finding keys: parent_key[index].field
        idx_prefix = f"{parent_key}[{len(result)}]" if parent_key else f"[{len(result)}]"

        if first_val:
            if _is_block_scalar_header(first_val):
                scalar_lines = []
                # Block scalar content must be indented deeper than
                # the mapping key column (base_indent + 2, accounting
                # for the "- " prefix).  This prevents sibling keys
                # at the item-content indent from being consumed when
                # the block scalar has no content lines.
                if i < len(lines) and lines[i][0] > base_indent + 2:
                    content_indent = lines[i][0]
                    while i < len(lines) and lines[i][0] >= content_indent:
                        scalar_lines.append(lines[i][1])
                        i += 1
                item_dict = {
                    first_key: _assemble_block_scalar(first_val, scalar_lines)
                }
            else:
                _check_plain_scalar(f"{idx_prefix}.{first_key}", first_val, findings)
                item_dict = {first_key: _unquote(first_val)}
        else:
            # Value is a nested structure on subsequent lines.
            item_dict = {}
            if i < len(lines) and lines[i][0] > base_indent:
                nested, i = _parse_structure(lines, i, lines[i][0], findings, f"{idx_prefix}.{first_key}")
                item_dict[first_key] = nested
            else:
                item_dict[first_key] = ""

        # Collect continuation keys belonging to the same dict item.
        while i < len(lines) and lines[i][0] > base_indent:
            ci, cc = lines[i]
            sub_colon = cc.find(":")
            if sub_colon < 0:
                break

            sub_key = cc[:sub_colon].strip()
            _check_mapping_key_construct(sub_key)
            sub_val = cc[sub_colon + 1 :].strip()

            if _is_block_scalar_header(sub_val):
                i += 1
                scalar_lines = []
                while i < len(lines) and lines[i][0] > ci:
                    scalar_lines.append(lines[i][1])
                    i += 1
                item_dict[sub_key] = _assemble_block_scalar(sub_val, scalar_lines)
            elif sub_val == "":
                i += 1
                if i < len(lines) and lines[i][0] > ci:
                    nested, i = _parse_structure(lines, i, lines[i][0], findings, f"{idx_prefix}.{sub_key}")
                    item_dict[sub_key] = nested
                else:
                    item_dict[sub_key] = ""
            else:
                _check_plain_scalar(f"{idx_prefix}.{sub_key}", sub_val, findings)
                item_dict[sub_key] = _unquote(sub_val)
                i += 1

        result.append(item_dict)

    return result, i
