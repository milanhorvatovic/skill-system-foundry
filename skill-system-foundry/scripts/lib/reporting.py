"""Shared error categorization and formatted output for validators.

JSON output convention
----------------------
Tool results use two different error keys depending on context:

* ``"error"`` (string) — used on early-exit paths where a single
  fatal condition prevents the tool from running (e.g. missing
  arguments, path is not a directory).  The value is a human-readable
  message describing the problem.

* ``"errors"`` (object) — used when the tool completes its validation
  run and reports structured results.  The value is a dict with keys
  ``"failures"``, ``"warnings"``, and ``"info"``, each mapping to a
  list of stripped message strings.

Consumers should check for ``"error"`` first (early exit) and fall
back to ``"errors"`` for full validation results.

Every tool result dict includes a ``"version"`` key (injected
automatically by ``to_json_output``) for forward-compatible schema
evolution.

Finding-string contract
-----------------------
Parser modules emit findings as strings shaped ``"SEVERITY: [tag] body"``
where ``SEVERITY`` is one of ``FAIL`` / ``WARN`` / ``INFO``, ``[tag]`` is
an optional bracketed token (e.g. ``[spec]``), and ``body`` is the
human-readable message.  ``parse_finding_string`` consumes this shape
without importing the producer module — it operates on the documented
string contract only.  Any producer adding a new tag must keep the
``"SEVERITY: [tag] body"`` shape; consumers that care about specific
tags filter them downstream.
"""

import json
import os

from .constants import ERROR_SYMBOLS, LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO, JSON_SCHEMA_VERSION


_SEVERITY_TO_LOWER = {
    LEVEL_FAIL: "fail",
    LEVEL_WARN: "warn",
    LEVEL_INFO: "info",
}


def to_posix(path: str) -> str:
    """Return *path* with path separators rewritten as ``/``.

    Single chokepoint for any path that crosses a UI boundary — JSON
    output payloads, FAIL/WARN/INFO finding strings, and human-mode
    diagnostic lines that quote a filename.  Internal data structures
    consumed only by other library modules (e.g. zip arcname maps,
    reference rewrite tables) keep their native form because the
    consumer relies on identity comparisons against ``os.path``-built
    keys.

    Used to keep the ``file`` field of structured findings consistent
    across Linux, macOS, and Windows runners.  Both Windows-style
    backslashes and the native ``os.sep`` are normalised so callers get
    POSIX output regardless of which platform produced the input.  No
    path normalization or canonicalization is performed — only
    separator characters are rewritten.
    """
    path = path.replace("\\", "/")
    if os.sep != "/":
        path = path.replace(os.sep, "/")
    return path


def parse_finding_string(raw: str) -> dict:
    """Parse a parser finding string into a structured dict.

    Input contract: ``"SEVERITY: [tag] body"`` where ``SEVERITY`` is one
    of ``FAIL`` / ``WARN`` / ``INFO``.  The bracketed ``[tag]`` is
    optional; any bracketed token is accepted verbatim (the helper is
    tag-agnostic — see module docstring).

    Returns ``{"severity": str, "tag": str, "message": str}`` where
    ``severity`` is the lowercase form (``"fail"`` / ``"warn"`` /
    ``"info"``) and ``tag`` includes the surrounding brackets (empty
    string when no tag is present).  The advice tail (after ``;``) is
    preserved verbatim in ``message``.

    Raises ``ValueError`` on malformed input — missing ``": "``
    separator, unrecognized severity token, or an unmatched opening
    ``[`` in the body (an unterminated tag is a producer bug, not a
    zero-tag message).
    """
    sep = ": "
    sep_index = raw.find(sep)
    if sep_index < 0:
        raise ValueError(
            f"malformed finding string (missing '{sep}' separator): {raw!r}"
        )
    severity_token = raw[:sep_index]
    body = raw[sep_index + len(sep):]
    if severity_token not in _SEVERITY_TO_LOWER:
        raise ValueError(
            f"unrecognized severity {severity_token!r} in finding: {raw!r}"
        )
    severity = _SEVERITY_TO_LOWER[severity_token]
    tag = ""
    message = body
    if body.startswith("["):
        end = body.find("]")
        if end <= 0:
            raise ValueError(
                f"malformed finding tag (unterminated '[') in finding: {raw!r}"
            )
        tag = body[: end + 1]
        message = body[end + 1:].lstrip()
    return {"severity": severity, "tag": tag, "message": message}


def categorize_errors(errors: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Split errors into (fails, warns, infos) lists by prefix."""
    fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
    warns = [e for e in errors if e.startswith(LEVEL_WARN)]
    infos = [e for e in errors if e.startswith(LEVEL_INFO)]
    return fails, warns, infos


def print_error_line(error: str) -> None:
    """Print a single error with the appropriate symbol prefix."""
    prefix = error.split(":")[0]
    symbol = ERROR_SYMBOLS.get(prefix, "?")
    print(f"  {symbol} {error}")


def print_summary(fails: list[str], warns: list[str], infos: list[str]) -> None:
    """Print the final summary line with counts."""
    print(
        f"Results: {len(fails)} failures, {len(warns)} warnings, {len(infos)} info"
    )


# ===================================================================
# JSON output helpers
# ===================================================================


def to_json_output(data: dict) -> str:
    """Serialize *data* to a pretty-printed, deterministic JSON string.

    Keys are sorted for reproducible output.  The result uses
    ``indent=2`` for readability and is intended for machine
    consumption — no trailing newline is added.

    When *data* contains a ``"tool"`` key (indicating a tool result
    rather than a raw data structure), a ``"version"`` key is
    automatically injected with the current ``JSON_SCHEMA_VERSION``
    to support forward-compatible schema evolution.
    """
    output = dict(data)
    if "tool" in output:
        output.setdefault("version", JSON_SCHEMA_VERSION)
    return json.dumps(output, indent=2, sort_keys=True)


def categorize_errors_for_json(
    errors: list[str],
) -> dict[str, list[str]]:
    """Return structured error categories suitable for JSON output.

    Each error message has its level prefix (e.g. ``"FAIL: "``)
    stripped so consumers do not need to parse it.

    Returns a dict with keys ``"failures"``, ``"warnings"``, and
    ``"info"``, each mapping to a list of stripped message strings.
    """
    fails, warns, infos = categorize_errors(errors)
    # Strip the "LEVEL: " prefix from each message
    strip_prefix_len = {
        LEVEL_FAIL: len(LEVEL_FAIL) + 2,  # "FAIL: "
        LEVEL_WARN: len(LEVEL_WARN) + 2,  # "WARN: "
        LEVEL_INFO: len(LEVEL_INFO) + 2,  # "INFO: "
    }
    return {
        "failures": [e[strip_prefix_len[LEVEL_FAIL]:] for e in fails],
        "warnings": [e[strip_prefix_len[LEVEL_WARN]:] for e in warns],
        "info": [e[strip_prefix_len[LEVEL_INFO]:] for e in infos],
    }
