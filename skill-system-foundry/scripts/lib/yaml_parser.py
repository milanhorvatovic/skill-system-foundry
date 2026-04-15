"""Lightweight YAML-subset parser (no external dependencies).

Handles the subset of YAML used by this framework: key-value pairs,
folded/literal block scalars (> | >- |-), nested mappings, scalar
lists, and lists of mappings.  All scalar values are returned as
strings — no type coercion for booleans, numbers, or null.
"""


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

    _findings: list[str] = findings if findings is not None else []
    result, _ = _parse_structure(lines, 0, lines[0][0], _findings)
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
    """Return ``True`` if *s* is a valid YAML 1.2.2 block scalar header.

    Matches ``[|>]`` optionally followed by a chomping modifier (``-``
    or ``+``) and/or an indentation indicator (``1``–``9``) in either
    order.  Digit ``0`` is excluded per Section 8.1.1.
    """
    if not s or s[0] not in ("|", ">"):
        return False
    rest = s[1:]
    if not rest:
        return True
    if len(rest) == 1:
        return rest in "-+123456789"
    if len(rest) == 2:
        return (
            (rest[0] in "-+" and rest[1] in "123456789")
            or (rest[0] in "123456789" and rest[1] in "-+")
        )
    return False


def _check_plain_scalar(key: str, value: str, findings: list[str]) -> None:
    """Append findings for unquoted plain scalar values that diverge from strict YAML 1.2."""
    if not value:
        return
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return

    from .constants import LEVEL_FAIL, LEVEL_WARN

    ch = value[0]

    # Leading-character checks (at most one finding).
    if ch in ("[", "]", "{", "}", ","):
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            f"'{ch}' (flow indicator) — strict parsers will reject this; "
            "wrap value in double quotes"
        )
    elif ch == "*":
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            "'*' (alias indicator) — strict parsers will reject this; "
            "wrap value in double quotes"
        )
    elif ch in ("@", "`"):
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            f"'{ch}' (reserved character) — strict parsers will reject "
            "this; wrap value in double quotes"
        )
    elif ch == "%":
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            "'%' (directive indicator) — strict parsers will reject this; "
            "wrap value in double quotes"
        )
    elif ch == "-":
        if len(value) == 1 or value[1] in (" ", "\t"):
            findings.append(
                f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
                "'-' followed by whitespace, or is '-' alone (block sequence "
                "entry) — strict parsers will reject this; wrap value in "
                "double quotes"
            )
    elif ch == "?":
        if len(value) == 1 or value[1] in (" ", "\t"):
            findings.append(
                f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
                "'?' followed by whitespace, or is '?' alone (explicit "
                "mapping key) — strict parsers will reject this; wrap value "
                "in double quotes"
            )
    elif ch == "&":
        if len(value) == 1 or value[1] in (" ", "\t"):
            findings.append(
                f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
                "'&' (anchor indicator) — strict parsers will reject this; "
                "wrap value in double quotes"
            )
        else:
            findings.append(
                f"{LEVEL_WARN}: [spec] '{key}': unquoted value starts with "
                "'&' (anchor name consumed by strict parsers, value becomes "
                "null) — wrap value in double quotes"
            )
    elif ch == "|":
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            "'|' followed by text (invalid block scalar header) — strict "
            "parsers will reject this; wrap value in double quotes"
        )
    elif ch == ">":
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            "'>' followed by text (invalid block scalar header) — strict "
            "parsers will reject this; wrap value in double quotes"
        )
    elif ch == "!":
        findings.append(
            f"{LEVEL_WARN}: [spec] '{key}': unquoted value starts with "
            "'!' (tag indicator consumed by strict parsers, silently "
            "altering the value) — wrap value in double quotes"
        )
    elif ch in ("'", '"'):
        findings.append(
            f"{LEVEL_FAIL}: [spec] '{key}': unquoted value starts with "
            f"'{ch}' (unterminated quote — no matching closing quote) — "
            "close the quote or wrap in double quotes"
        )

    # Colon scan — break on first match.
    for i, c in enumerate(value):
        if c == ":":
            if i == len(value) - 1:
                findings.append(
                    f"{LEVEL_FAIL}: [spec] '{key}': unquoted value ends "
                    "with ':' — strict parsers treat this as a mapping "
                    "key; wrap value in double quotes"
                )
                break
            if value[i + 1] in (" ", "\t"):
                findings.append(
                    f"{LEVEL_FAIL}: [spec] '{key}': unquoted value "
                    "contains ': ' — strict parsers treat this as a "
                    "mapping key; wrap value in double quotes"
                )
                break


def _parse_structure(lines: list[tuple[int, str]], start: int, base_indent: int, findings: list[str], parent_key: str = "") -> tuple[dict | list, int]:
    """Dispatch to mapping or list parser based on the first token."""
    if start >= len(lines):
        return {}, start
    if lines[start][1].startswith("- "):
        return _parse_list(lines, start, base_indent, findings, parent_key)
    return _parse_mapping(lines, start, base_indent, findings)


def _parse_mapping(lines: list[tuple[int, str]], start: int, base_indent: int, findings: list[str]) -> tuple[dict, int]:
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


def _parse_list(lines: list[tuple[int, str]], start: int, base_indent: int, findings: list[str], parent_key: str = "") -> tuple[list, int]:
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
            # Simple scalar list item — use parent_key[index] as the
            # finding key so the user knows which list and position.
            if not _is_block_scalar_header(item_text):
                item_key = f"{parent_key}[{len(result)}]" if parent_key else f"[{len(result)}]"
                _check_plain_scalar(item_key, item_text, findings)
            result.append(_unquote(item_text))
            continue

        # Dict item inside a list (``- key: value`` with possible continuations).
        first_key = item_text[:colon_pos].strip()
        first_val = item_text[colon_pos + 1 :].strip()

        if first_val:
            if not _is_block_scalar_header(first_val):
                _check_plain_scalar(first_key, first_val, findings)
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
                _check_plain_scalar(sub_key, sub_val, findings)
                item_dict[sub_key] = _unquote(sub_val)
                i += 1

        result.append(item_dict)

    return result, i
