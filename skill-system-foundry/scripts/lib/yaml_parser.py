"""Lightweight YAML-subset parser (no external dependencies).

Handles the subset of YAML used by this framework: key-value pairs,
folded/literal block scalars (> | >- |-), nested mappings, scalar
lists, and lists of mappings.  All scalar values are returned as
strings — no type coercion for booleans, numbers, or null.
"""

from .constants import LEVEL_FAIL, LEVEL_WARN


def parse_yaml_subset(text: str, findings: list[str] | None = None) -> dict:
    """Parse a limited YAML subset into a Python dict.

    Raises ValueError on structural parse failures.

    If *findings* is a list, plain-scalar warnings/errors are appended
    to it.  If ``None`` (the default), findings are silently discarded.
    """
    if not text or not text.strip():
        return {}

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


def _escape_double_quoted_yaml(value: str) -> str:
    """Escape *value* for use inside a YAML double-quoted scalar.

    YAML double-quoted scalars interpret backslash sequences (``\\n``,
    ``\\t``, ``\\\"``, etc.), so literal backslashes and embedded double
    quotes must be escaped.
    """
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


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
        return "use a block scalar (>-) — value contains line breaks"
    if "'" not in value:
        return "wrap value in single quotes"
    if '"' not in value and "\\" not in value:
        return "wrap value in double quotes"
    return "use a block scalar (>-) — value contains characters that require escape processing in quoted forms"


def _check_plain_scalar(key: str, value: str, findings: list[str] | None) -> None:
    """Append findings for unquoted plain scalar values that diverge from strict YAML 1.2."""
    if findings is None or not value:
        return
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return

    # Lazy import — loaded after all modules are fully initialised, which
    # avoids the circular dependency (constants imports yaml_parser to
    # parse configuration.yaml at module-load time).
    from .constants import PLAIN_SCALAR_INDICATORS, PLAIN_SCALAR_CONTEXT_WHITESPACE

    ind = PLAIN_SCALAR_INDICATORS
    ws = PLAIN_SCALAR_CONTEXT_WHITESPACE

    advice = _quote_advice(value)
    ch = value[0]

    # Leading-character checks (at most one finding).
    if ch in ind["flow"]:
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            f"'{ch}' (flow indicator) — strict parsers will reject this; "
            f"{advice}"
        )
    elif ch in ind["alias"]:
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            "'*' (alias indicator) — strict parsers will reject this; "
            f"{advice}"
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
            # Determine whether remaining content exists after the anchor name.
            has_remaining = any(
                value[i] in ws for i in range(1, len(value))
            )
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
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            f"'{ch}' followed by text (invalid block scalar header) — strict "
            f"parsers will reject this; {advice}"
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
    return _parse_mapping(lines, start, base_indent, findings)


def _parse_mapping(lines: list[tuple[int, str]], start: int, base_indent: int, findings: list[str] | None) -> tuple[dict, int]:
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
        after = content[colon + 1 :].strip()

        if _is_block_scalar_header(after):
            # Block scalar — collect indented continuation lines.
            fold = after.startswith(">")
            i += 1
            scalar_lines = []
            while i < len(lines) and lines[i][0] > base_indent:
                scalar_lines.append(lines[i][1])
                i += 1
            result[key] = " ".join(scalar_lines) if fold else "\n".join(scalar_lines)

        elif after == "":
            # Nested structure (mapping or list).
            i += 1
            if i < len(lines) and lines[i][0] > base_indent:
                nested, i = _parse_structure(lines, i, lines[i][0], findings, key)
                result[key] = nested
            else:
                result[key] = ""

        else:
            _check_plain_scalar(key, after, findings)
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
                fold = item_text.startswith(">")
                scalar_lines = []
                while i < len(lines) and lines[i][0] > base_indent:
                    scalar_lines.append(lines[i][1])
                    i += 1
                result.append(
                    " ".join(scalar_lines) if fold else "\n".join(scalar_lines)
                )
            else:
                # Plain scalar — use parent_key[index] as the finding
                # key so the user knows which list and position.
                item_key = f"{parent_key}[{len(result)}]" if parent_key else f"[{len(result)}]"
                _check_plain_scalar(item_key, item_text, findings)
                result.append(_unquote(item_text))
            continue

        # Dict item inside a list (``- key: value`` with possible continuations).
        first_key = item_text[:colon_pos].strip()
        first_val = item_text[colon_pos + 1 :].strip()
        # Build indexed prefix for finding keys: parent_key[index].field
        idx_prefix = f"{parent_key}[{len(result)}]" if parent_key else f"[{len(result)}]"

        if first_val:
            if _is_block_scalar_header(first_val):
                fold = first_val.startswith(">")
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
                    first_key: " ".join(scalar_lines) if fold else "\n".join(scalar_lines)
                }
            else:
                _check_plain_scalar(f"{idx_prefix}.{first_key}", first_val, findings)
                item_dict = {first_key: _unquote(first_val)}
        else:
            # Value is a nested structure on subsequent lines.
            item_dict = {}
            if i < len(lines) and lines[i][0] > base_indent:
                nested, i = _parse_structure(lines, i, lines[i][0], findings, first_key)
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
            sub_val = cc[sub_colon + 1 :].strip()

            if _is_block_scalar_header(sub_val):
                fold = sub_val.startswith(">")
                i += 1
                scalar_lines = []
                while i < len(lines) and lines[i][0] > ci:
                    scalar_lines.append(lines[i][1])
                    i += 1
                item_dict[sub_key] = (
                    " ".join(scalar_lines) if fold else "\n".join(scalar_lines)
                )
            elif sub_val == "":
                i += 1
                if i < len(lines) and lines[i][0] > ci:
                    nested, i = _parse_structure(lines, i, lines[i][0], findings, sub_key)
                    item_dict[sub_key] = nested
                else:
                    item_dict[sub_key] = ""
            else:
                _check_plain_scalar(f"{idx_prefix}.{sub_key}", sub_val, findings)
                item_dict[sub_key] = _unquote(sub_val)
                i += 1

        result.append(item_dict)

    return result, i
