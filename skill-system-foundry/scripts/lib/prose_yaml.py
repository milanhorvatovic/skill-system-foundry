"""Doc-snippet validation for ```yaml fences in skill prose.

Scope:
- Extract fenced ```yaml blocks from markdown text per the strict
  fence rules described under ``extract_yaml_fences``.
- Parse each block with ``parse_yaml_subset`` and convert findings to
  structured dicts via ``parse_finding_string``.
- Frontmatter is **not** scanned.  ``load_frontmatter`` already
  handles the ``---``-delimited block; this module only sees fenced
  code in the body.

Import discipline: this module imports ``parse_yaml_subset`` from
``lib.yaml_parser`` and ``parse_finding_string`` / ``to_posix`` from
``lib.reporting``.  ``reporting`` is a pure string helper and does not
import this module — no cycle.
"""

import glob
import os

from .constants import (
    LEVEL_FAIL, LEVEL_INFO, LEVEL_WARN,
    PROSE_YAML_IN_SCOPE_GLOBS, PROSE_YAML_OPT_OUT_MARKER,
)
from .frontmatter import split_frontmatter
from .reporting import parse_finding_string, to_posix
from .yaml_parser import parse_yaml_subset


_FENCE_CLOSE_LITERAL = "```"


def _strip_frontmatter(markdown_text: str) -> str:
    """Drop a leading ``---``-delimited frontmatter block if present.

    The prose-YAML check promises that frontmatter is not scanned —
    without this, a ``yaml`` fence embedded in a folded description
    would be validated as if it were body content.

    Delegates to :func:`lib.frontmatter.split_frontmatter` so delimiter
    rules stay in sync with ``load_frontmatter``.  To avoid misreading
    a Markdown thematic break (``---`` at column 0) as frontmatter,
    the candidate block is validated by ``parse_yaml_subset`` — only
    content that parses as a YAML mapping is treated as frontmatter
    and stripped.
    """
    frontmatter_raw, body_raw = split_frontmatter(markdown_text)
    if frontmatter_raw is None:
        return markdown_text
    if body_raw is None:
        # Opener present but no closing delimiter.  The block is
        # ambiguous — malformed frontmatter vs a thematic break at
        # line 1 of a file that happens not to have another ``---``.
        # Stay conservative and scan the original text so body fences
        # still reach the validator; ``load_frontmatter`` surfaces the
        # parse error separately when frontmatter was in fact intended.
        return markdown_text
    frontmatter_str = frontmatter_raw.strip()
    if frontmatter_str == "":
        # Explicitly-empty frontmatter (``---\\n---\\n``) is still
        # frontmatter for scope purposes — strip it.
        return body_raw
    try:
        parsed = parse_yaml_subset(frontmatter_str, [])
    except (ValueError, KeyError):
        return markdown_text
    # ``parse_yaml_subset`` returns ``{}`` for prose-like content too
    # (lines with no ``key:`` pairs), so an empty dict is not enough
    # evidence that the block is frontmatter.  Require at least one
    # parsed key before stripping.
    if not isinstance(parsed, dict) or not parsed:
        return markdown_text
    return body_raw


def extract_yaml_fences(markdown_text: str) -> list[dict]:
    """Return one record per ```yaml fence found in *markdown_text*.

    Each record dict::

        {
            "ordinal":  int,   # 1-based across all matched fences
            "text":     str,   # fence body, LF-only
            "state":    "parsed" | "ignored" | "unterminated" | "wrong-case",
            "language": str,   # only present when state=="wrong-case";
                               # the literal language token the author
                               # wrote (e.g. "YAML", "yml")
        }

    Fence shape rules:

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

    Opt-out: if the line immediately above the fence-open line — with
    no blank line between — exactly matches the configured opt-out
    marker (whitespace around it allowed), the record's ``state`` is
    ``"ignored"``.

    Empty markdown input is a valid no-op — returns ``[]``.
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
        if is_ignored:
            records.append(
                {
                    "ordinal": ordinal,
                    "text": body_text,
                    "state": "ignored",
                }
            )
        elif opener == "wrong-case":
            records.append(
                {
                    "ordinal": ordinal,
                    "text": body_text,
                    "state": "wrong-case",
                    "language": _open_language(line),
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
    # Must be exactly three backticks (exclude ``` ```` ``` etc.).
    if line.startswith("````"):
        return None
    rest = line[3:]
    # No leading whitespace before the language token.
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
    matches the opt-out marker exactly."""
    if fence_index == 0:
        return False
    above = lines[fence_index - 1].strip()
    return above == PROSE_YAML_OPT_OUT_MARKER


def validate_prose_yaml(file_path: str, markdown_text: str) -> list[dict]:
    """Validate every ```yaml fence in *markdown_text*.

    Returns a list of structured finding dicts::

        {
            "file":          str,          # echoed from *file_path*
            "block_ordinal": int | None,    # 1-based when a fence is
                                            # implicated; ``None`` for
                                            # file-level findings
                                            # (e.g. unreadable source)
            "severity":      "fail" | "warn" | "info",
            "tag":           str,           # bracketed token, may be empty
            "message":       str,
        }

    *file_path* is echoed into each finding's ``file`` field verbatim
    — callers pre-normalise to skill-root-relative POSIX form (use
    :func:`lib.reporting.to_posix` if needed).

    Frontmatter blocks are **not** scanned; this function only
    inspects fenced code in the body.
    """
    body = _strip_frontmatter(markdown_text)
    return _validate_records(file_path, extract_yaml_fences(body))


def _validate_records(file_path: str, records: list[dict]) -> list[dict]:
    """Produce structured findings from already-extracted fence records.

    Separated so ``collect_prose_findings`` can reuse the result of a
    single ``extract_yaml_fences`` call instead of parsing each file
    twice.
    """
    findings: list[dict] = []
    for record in records:
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
                    "unterminated yaml fence",
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
    ordinal: int | None,
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
    errors (``UnicodeDecodeError``) propagate unchanged.  Callers that
    want structured handling should use :func:`validate_prose_yaml`
    directly with their own I/O.

    The file path is normalised to POSIX separators so finding ``file``
    fields are platform-independent.
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return validate_prose_yaml(to_posix(path), text)


def find_in_scope_files(skill_root: str) -> list[str]:
    """Return absolute paths of in-scope Markdown files under *skill_root*.

    Scope is the three globs from ``PROSE_YAML_IN_SCOPE_GLOBS``
    (``SKILL.md``, ``capabilities/**/*.md``, ``references/**/*.md``).
    Returns a sorted, de-duplicated list using the native path
    separators produced on the current platform; callers normalise via
    ``to_posix`` when constructing finding paths.
    """
    seen: set[str] = set()
    matches: list[str] = []
    for pattern in PROSE_YAML_IN_SCOPE_GLOBS:
        for absolute in glob.glob(
            os.path.join(skill_root, pattern), recursive=True
        ):
            if not os.path.isfile(absolute):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            matches.append(absolute)
    matches.sort()
    return matches


def collect_prose_findings(
    skill_root: str, *, audit_prefix: str = ""
) -> tuple[list[dict], int, list[tuple[str, int]]]:
    """Walk *skill_root* and validate every in-scope Markdown file.

    Returns ``(findings, checked, per_file_counts)``:

    - ``findings`` — flat list of structured finding dicts (file paths
      already prefixed when *audit_prefix* is non-empty).
    - ``checked`` — count of fences in state ``"parsed"`` summed across
      every in-scope file.
    - ``per_file_counts`` — list of ``(relative_path, fence_count)``
      pairs in iteration order; verbose callers print one line per
      entry.

    *audit_prefix* — when set, every finding's ``file`` field becomes
    ``<audit_prefix>/<relative-path>`` so multi-skill aggregation in
    ``audit_skill_system`` is unambiguous.
    """
    findings: list[dict] = []
    checked = 0
    per_file_counts: list[tuple[str, int]] = []
    for absolute in find_in_scope_files(skill_root):
        relative = to_posix(os.path.relpath(absolute, skill_root))
        display_path = (
            f"{audit_prefix}/{relative}" if audit_prefix else relative
        )
        try:
            with open(absolute, "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            # An unreadable in-scope file must not crash the walk —
            # surface it as a structured FAIL so the caller routes it
            # through the existing finding stream.
            findings.append(
                _structured_finding(
                    display_path, None, "fail", "[spec]",
                    f"could not read file for prose YAML check: {exc}",
                )
            )
            per_file_counts.append((display_path, 0))
            continue
        records = extract_yaml_fences(_strip_frontmatter(text))
        parsed_count = sum(1 for r in records if r["state"] == "parsed")
        checked += parsed_count
        per_file_counts.append((display_path, len(records)))
        findings.extend(_validate_records(display_path, records))
    return findings, checked, per_file_counts


def format_finding_as_string(finding: dict) -> str:
    """Format a structured finding dict as a parser-style finding string.

    Reuses the existing ``SEVERITY: [tag] body`` shape so consumers
    that already iterate ``errors[]`` and call ``categorize_errors`` /
    ``print_error_line`` work without modification.  The body is the
    same regardless of whether the message is key-scoped — the
    parser's ``'key': body; advice`` chunk already begins with
    ``'key':`` when applicable, so no caller-side branching is needed.
    """
    severity_token = {
        "fail": LEVEL_FAIL, "warn": LEVEL_WARN, "info": LEVEL_INFO,
    }[finding["severity"]]
    tag = finding["tag"] or "[spec]"
    file_part = finding["file"]
    ordinal = finding["block_ordinal"]
    # File-level findings (no implicated fence) omit the ``block N``
    # segment — ``block 0`` / ``block None`` would be nonsensical.
    if ordinal is None:
        return f"{severity_token}: {tag} {file_part}: {finding['message']}"
    return (
        f"{severity_token}: {tag} {file_part} block {ordinal}: "
        f"{finding['message']}"
    )


# Re-export ``LEVEL_FAIL`` so callers building human output don't need
# to import constants separately.
__all__ = (
    "LEVEL_FAIL",
    "extract_yaml_fences",
    "validate_prose_yaml",
    "read_and_validate",
    "find_in_scope_files",
    "collect_prose_findings",
    "format_finding_as_string",
)
