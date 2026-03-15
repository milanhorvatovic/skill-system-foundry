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
"""

import json

from .constants import ERROR_SYMBOLS, LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO, JSON_SCHEMA_VERSION


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
