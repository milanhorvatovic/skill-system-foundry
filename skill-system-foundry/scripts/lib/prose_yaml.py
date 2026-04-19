"""Doc-snippet validation for ```yaml fences in skill prose.

Scope (§4.1 of the design plan):
- Extract fenced ```yaml blocks from markdown text per the strict
  fence rules in §4.2.
- Parse each block with ``parse_yaml_subset`` and convert findings to
  structured dicts via ``parse_finding_string``.
- Frontmatter is **not** scanned (G26).  ``load_frontmatter`` already
  handles the ``---``-delimited block; this module only sees fenced
  code in the body.

Import discipline (G112): this module imports ``parse_yaml_subset``
from ``lib.yaml_parser`` and ``parse_finding_string`` / ``to_posix``
from ``lib.reporting``.  ``reporting`` is a pure string helper and
does not import this module — no cycle.
"""

import os

from .constants import LEVEL_FAIL, PROSE_YAML_OPT_OUT_MARKER
from .reporting import parse_finding_string, to_posix
from .yaml_parser import parse_yaml_subset


_FENCE_OPEN_LITERAL = "```yaml"
_FENCE_CLOSE_LITERAL = "```"


def extract_yaml_fences(markdown_text: str) -> list[dict]:
    """Return one record per ```yaml fence found in *markdown_text*.

    Each record dict::

        {
            "ordinal": int,   # 1-based across all matched fences
            "text":   str,    # fence body, LF-only
            "state":  "parsed" | "ignored" | "unterminated" | "wrong-case"
        }

    Fence shape rules (§4.2 / G69 / G70):

    - Backtick fences only.  Tilde fences are invisible.
    - Exactly three opening backticks at byte offset 0.
    - Case-sensitive literal ``yaml`` immediately after the backticks
      (no whitespace between).  ``yml`` / ``YAML`` / ``Yaml`` open
      lines surface as ``state="wrong-case"`` records.
    - Anything after ``yaml`` on the open line (an info-string suffix)
      is discarded.
    - The block closes on the next line that is exactly ``` `` ` ``` ``
      at byte offset 0; if no close marker is found before EOF the
      fence is reported as ``state="unterminated"``.

    Opt-out (§4.3, G42): if the line immediately above the fence-open
    line — with no blank line between — exactly matches the configured
    opt-out marker (whitespace around it allowed), the record's
    ``state`` is ``"ignored"``.

    Empty markdown input is a valid no-op — returns ``[]`` (G136).
    """
    if not markdown_text:
        return []
    text = markdown_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    records: list[dict] = []
    i = 0
    ordinal = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        opener = _classify_open_line(line)
        if opener is None:
            i += 1
            continue
        ordinal += 1
        is_ignored = _has_opt_out_marker(lines, i)
        # Collect body lines until a column-0 closing fence or EOF.
        body: list[str] = []
        j = i + 1
        terminated = False
        while j < n:
            if lines[j] == _FENCE_CLOSE_LITERAL:
                terminated = True
                break
            body.append(lines[j])
            j += 1
        body_text = "\n".join(body)
        if not terminated:
            records.append(
                {
                    "ordinal": ordinal,
                    "text": body_text,
                    "state": "unterminated",
                }
            )
            return records
        if opener == "wrong-case":
            records.append(
                {
                    "ordinal": ordinal,
                    "text": body_text,
                    "state": "wrong-case",
                    "language": _open_language(line),
                }
            )
        elif is_ignored:
            records.append(
                {
                    "ordinal": ordinal,
                    "text": body_text,
                    "state": "ignored",
                }
            )
        else:
            records.append(
                {
                    "ordinal": ordinal,
                    "text": body_text,
                    "state": "parsed",
                }
            )
        i = j + 1
    return records


def _classify_open_line(line: str) -> str | None:
    """Return ``"parsed"`` / ``"wrong-case"`` / ``None`` for *line*.

    ``"parsed"`` — column-0 ``` ```yaml ``` open with the literal
    lowercase token.  ``"wrong-case"`` — column-0 backtick fence open
    with a known YAML-spelled token (``yml`` / ``YAML`` / ``Yaml``).
    ``None`` — not an opener this extractor recognises.
    """
    if not line.startswith("```"):
        return None
    # Must be exactly three backticks (G69 — exclude ``` ```` ``` etc.).
    if line.startswith("````"):
        return None
    rest = line[3:]
    # No leading whitespace before the language token (G69).
    if not rest:
        return None
    # Strip info-string suffix at the first whitespace.
    token = rest.split(" ", 1)[0].split("\t", 1)[0]
    if token == "yaml":
        return "parsed"
    if token in ("yml", "YAML", "Yaml"):
        return "wrong-case"
    return None


def _open_language(line: str) -> str:
    """Return the language token of a column-0 backtick fence opener."""
    rest = line[3:]
    return rest.split(" ", 1)[0].split("\t", 1)[0]


def _has_opt_out_marker(lines: list[str], fence_index: int) -> bool:
    """Return ``True`` when the line immediately above *fence_index*
    matches the opt-out marker exactly (G42)."""
    if fence_index == 0:
        return False
    above = lines[fence_index - 1].strip()
    return above == PROSE_YAML_OPT_OUT_MARKER


def validate_prose_yaml(file_path: str, markdown_text: str) -> list[dict]:
    """Validate every ```yaml fence in *markdown_text*.

    Returns a list of structured finding dicts::

        {
            "file":          str,    # echoed verbatim from *file_path*
            "block_ordinal": int,    # 1-based, stable across all fences
            "severity":      "fail" | "warn" | "info",
            "tag":           str,    # bracketed token, may be empty
            "message":       str,
        }

    *file_path* is echoed into each finding's ``file`` field verbatim
    (G120) — callers pre-normalise to skill-root-relative POSIX form
    (use :func:`lib.reporting.to_posix` if needed).

    Frontmatter blocks are **not** scanned (G26); this function only
    inspects fenced code in the body.
    """
    findings: list[dict] = []
    for record in extract_yaml_fences(markdown_text):
        ordinal = record["ordinal"]
        state = record["state"]
        if state == "ignored":
            continue
        if state == "unterminated":
            findings.append(
                _structured_finding(
                    file_path,
                    ordinal,
                    "fail",
                    "[spec]",
                    f"unterminated yaml fence (block ordinal {ordinal})",
                )
            )
            continue
        if state == "wrong-case":
            actual = record.get("language", "")
            findings.append(
                _structured_finding(
                    file_path,
                    ordinal,
                    "info",
                    "[spec]",
                    f"fence language identifier {actual!r} is not "
                    "recognized — did you mean 'yaml'?",
                )
            )
            continue
        # state == "parsed"
        try:
            parser_findings: list[str] = []
            parse_yaml_subset(record["text"], parser_findings)
        except ValueError as exc:
            findings.append(
                _structured_finding(
                    file_path,
                    ordinal,
                    "fail",
                    "[spec]",
                    f"structural parse error: {exc}",
                )
            )
            continue
        for raw in parser_findings:
            parsed = parse_finding_string(raw)
            findings.append(
                {
                    "file": file_path,
                    "block_ordinal": ordinal,
                    "severity": parsed["severity"],
                    "tag": parsed["tag"],
                    "message": parsed["message"],
                }
            )
    return findings


def _structured_finding(
    file_path: str,
    ordinal: int,
    severity: str,
    tag: str,
    message: str,
) -> dict:
    return {
        "file": file_path,
        "block_ordinal": ordinal,
        "severity": severity,
        "tag": tag,
        "message": message,
    }


def read_and_validate(path: str) -> list[dict]:
    """Convenience wrapper: read *path* (UTF-8) and validate its fences.

    OS errors (``FileNotFoundError``, ``PermissionError``) and decode
    errors (``UnicodeDecodeError``) propagate unchanged (G61).  Callers
    that want structured handling should use :func:`validate_prose_yaml`
    directly with their own I/O.

    The file path is normalised to POSIX separators so finding ``file``
    fields are platform-independent (G68).
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return validate_prose_yaml(to_posix(path), text)


# Re-export ``LEVEL_FAIL`` so callers building human output don't need
# to import constants separately.
__all__ = (
    "LEVEL_FAIL",
    "extract_yaml_fences",
    "validate_prose_yaml",
    "read_and_validate",
)
