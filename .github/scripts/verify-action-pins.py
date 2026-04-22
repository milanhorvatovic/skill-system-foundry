"""Enforce SHA-pinned ``uses:`` references in every workflow file.

Walks ``.github/workflows/*.yml`` and ``.github/workflows/*.yaml`` line by
line (no YAML parsing — the issue spec deliberately prefers a simple
scan over a full parse, at the cost of a theoretical false-positive
when a multi-line ``run: |`` block has a line whose first non-whitespace
text is literally ``uses:``; no current workflow trips this) and applies
these rules to every ``uses:`` key it finds:

===========================================  =========
Reference form                               Treatment
===========================================  =========
``org/repo@<40-char-lowercase-hex>``         allowed
``org/repo/subpath@<40-char-lowercase-hex>`` allowed
``./path``                                   allowed
``docker://image...``                        allowed
anything else                                rejected
===========================================  =========

Output:
  * Default human mode: one ``FAIL: <file>:<line>: <uses> -- <reason>``
    line per violation.
  * ``--json`` mode: a JSON list of ``{"file", "line", "uses",
    "reason"}`` dicts, sorted by ``(file, line)``.

Exit code: 0 when every ``uses:`` is pinned, 1 on any violation, 2 on
argparse/usage errors.
"""

import argparse
import json
import os
import re
import sys

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Matches a YAML-key ``uses:`` at the start of a line, optionally
# preceded by a list marker ("- "). The ``uses`` token may itself be
# quoted (``'uses':`` / ``"uses":``) — GitHub Actions still treats those
# as the same key, so the gate must not miss them. Captures the raw
# right-hand side (value plus any trailing comment); may be empty so an
# intentionally blank ``uses:`` reaches ``classify`` and is reported
# rather than silently ignored. The caller strips quotes and trailing
# comments before classification.
_USES_RE = re.compile(
    r"""^\s*(?:-\s+)?['"]?uses['"]?\s*:\s*(\S.*?|)\s*$"""
)
# Flow-style YAML mappings (``- { uses: ref }`` / ``{ name: x, uses: ref
# }``) are also valid GitHub Actions step syntax, so the scanner must
# find ``uses`` keys inside ``{}`` as well. The lookbehind is ``{`` or
# ``,`` to allow both leading and subsequent positions; the value is
# captured lazily up to the next ``,`` or ``}`` that would terminate
# it in the flow map.
_FLOW_USES_RE = re.compile(
    r"""[{,]\s*['"]?uses['"]?\s*:\s*([^,}\n]*?)\s*(?=[,}])"""
)


def _strip_inline(raw: str) -> str:
    """Return the bare ``uses:`` value with quotes and comment stripped.

    GitHub action references never contain ``#``, so a ``#`` that
    appears after whitespace on an unquoted value is always an inline
    YAML comment and is removed. For quoted values (single or double
    quote pairs) the inside of the quotes is returned verbatim and
    anything after the closing quote is discarded.
    """
    value = raw.strip()
    if not value:
        return value
    # An unquoted leading ``#`` makes the entire right-hand side a YAML
    # comment (the value is empty). Return empty so classify reports the
    # real issue — empty uses value — instead of a misleading
    # "missing '@<commit-sha>' pin" against the comment text.
    if value[0] == "#":
        return ""
    if value[0] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        if end == -1:
            # Unterminated quote would already be rejected by any YAML
            # parser — GitHub Actions will not accept the file — so the
            # scanner just returns the raw string and lets the classifier
            # decide. No correctness risk either way.
            return value
        return value[1:end]
    for sep in (" #", "\t#"):
        idx = value.find(sep)
        if idx != -1:
            value = value[:idx]
            break
    return value.strip()


def classify(value: str) -> str | None:
    """Return ``None`` when *value* is an allowed reference form.

    Otherwise return a short human-readable reason string. Leading and
    trailing whitespace is stripped so standalone callers see the same
    decision the scan path does (``scan_workflow`` already normalises
    via ``_strip_inline`` before calling in).
    """
    value = value.strip()
    if not value:
        return "empty uses value"
    # Reject any parent-traversal form *before* the ``./`` accept
    # branch, otherwise ``./../foo`` would slip through because it
    # starts with ``./``. Catch the bare, leading, embedded, and
    # trailing forms.
    if (
        value == ".."
        or value.startswith("../")
        or "/../" in value
        or value.endswith("/..")
    ):
        return "local action path must not contain parent traversal"
    if value.startswith("./"):
        if value == "./":
            return "local action path must not be empty"
        return None
    if value.startswith("docker://"):
        if value == "docker://":
            return "docker action reference must not be empty"
        return None
    if "@" not in value:
        return "missing '@<commit-sha>' pin"
    prefix, _, ref = value.rpartition("@")
    # The prefix must be ``owner/repo`` or ``owner/repo/subpath`` with
    # every segment non-empty. Splitting on ``/`` and checking segment
    # count + emptiness catches bypasses like ``org/@<sha>``,
    # ``/repo@<sha>``, or ``org//@<sha>`` that a naive ``"/" in prefix``
    # test would wave through.
    parts = prefix.split("/")
    if len(parts) < 2 or any(not part for part in parts) or not ref:
        return "not a recognised action reference form"
    if not _SHA_RE.match(ref):
        return f"ref '{ref}' is not a 40-character lowercase commit SHA"
    return None


def scan_workflow(text: str) -> list[tuple[int, str, str]]:
    """Return ``(line_number, value, reason)`` tuples for every violation.

    *text* is the full content of a workflow file. Lines whose first
    non-whitespace character is ``#`` are skipped so commented-out
    examples do not register. Both block-style (``uses: ref``) and
    flow-style (``{ uses: ref }``) mapping forms are scanned. Line
    numbers are 1-indexed.
    """
    violations: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        block = _USES_RE.match(line)
        if block is not None:
            value = _strip_inline(block.group(1))
            reason = classify(value)
            if reason is not None:
                violations.append((lineno, value, reason))
            continue
        for flow in _FLOW_USES_RE.finditer(line):
            value = _strip_inline(flow.group(1))
            reason = classify(value)
            if reason is not None:
                violations.append((lineno, value, reason))
    return violations


def list_workflow_files(workflows_dir: str) -> list[str]:
    """Return sorted absolute paths of every workflow YAML in *dir*."""
    if not os.path.isdir(workflows_dir):
        return []
    names = [
        n for n in os.listdir(workflows_dir)
        if n.endswith(".yml") or n.endswith(".yaml")
    ]
    names.sort()
    return [os.path.join(workflows_dir, n) for n in names]


def collect_violations(workflows_dir: str) -> list[dict]:
    """Walk *workflows_dir* and return a sorted list of violation dicts.

    Violation ``file`` fields are always labelled
    ``.github/workflows/<basename>`` regardless of where the scanned
    directory actually lives on disk. That matches production output
    exactly, so a contributor who runs the script with
    ``--workflows-dir`` locally sees the same paths CI would print.
    Forward slashes make the label stable across platforms.
    """
    results: list[dict] = []
    for absolute in list_workflow_files(workflows_dir):
        label = ".github/workflows/" + os.path.basename(absolute)
        try:
            with open(absolute, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            results.append({
                "file": label,
                "line": 0,
                "uses": "",
                "reason": f"read-error: {type(exc).__name__}: {exc}",
            })
            continue
        for lineno, value, reason in scan_workflow(text):
            results.append({
                "file": label,
                "line": lineno,
                "uses": value,
                "reason": reason,
            })
    # Sort defensively on (file, line) even though insertion order
    # already matches today (list_workflow_files returns basenames
    # sorted lexically, scan_workflow yields ascending line numbers,
    # all entries for one file flush before the next). The docstring
    # advertises sorted output, so a future refactor that recurses into
    # subdirectories or parallelises reads must not quietly break the
    # contract.
    results.sort(key=lambda v: (v["file"], v["line"]))
    return results


def format_human(violations: list[dict]) -> str:
    """Format *violations* as one ``FAIL`` line per entry."""
    if not violations:
        return "All workflow `uses:` references are SHA-pinned."
    lines = [
        f"FAIL: {v['file']}:{v['line']}: {v['uses']} -- {v['reason']}"
        for v in violations
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 clean, 1 on violations, 2 on usage errors."""
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if args.workflows_dir is not None:
        workflows_dir = os.path.abspath(args.workflows_dir)
    else:
        workflows_dir = os.path.join(_REPO_ROOT, ".github", "workflows")

    # Fail closed when the workflows directory is missing. Returning 0
    # against ``list_workflow_files -> []`` would otherwise produce a
    # misleading "All workflow `uses:` references are SHA-pinned."
    # result that hides a setup error (wrong ``--workflows-dir``, a
    # repo without workflows, or a CI checkout that lost the tree).
    if not os.path.isdir(workflows_dir):
        print(
            f"ERROR: workflows directory not found: {workflows_dir}",
            file=sys.stderr,
        )
        return 1

    violations = collect_violations(workflows_dir)

    if args.json:
        print(json.dumps(violations, indent=2, sort_keys=True))
    else:
        print(format_human(violations))

    return 1 if violations else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments. Raises ``SystemExit`` on errors."""
    parser = argparse.ArgumentParser(
        description=(
            "Fail when any 'uses:' line in .github/workflows/ is not "
            "pinned to a 40-character commit SHA."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON list of {file, line, uses, reason} dicts.",
    )
    parser.add_argument(
        "--workflows-dir",
        default=None,
        help=(
            "Override the workflows directory to scan (primarily for "
            "tests). Defaults to <repo>/.github/workflows."
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
