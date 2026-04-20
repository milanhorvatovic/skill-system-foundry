"""Preflight scanner for the YAML 1.2.2 grammar-gap upgrade.

Walks every tracked YAML file and every frontmatter block in every
tracked Markdown file (no directory exclusions — ``.agents/`` and
``assets/`` are scanned too).  Reports any input that would trip the
three new ``ValueError`` paths once the parser hardening lands:

  - ``anchor-with-trailing-in-key`` — ``&name key:`` syntax.
  - ``indent-indicator-block-scalar`` — block scalar header with a
    digit indentation indicator (``key: |2``, ``key: >-3``, etc.).
  - ``tag-in-mapping-key`` — ``!tag key:`` syntax.

Output:
  * Default ``human`` mode: one ``FAIL: <construct-id> at <file>
    [<position>]`` line per hit.  ``<position>`` is the literal string
    ``"frontmatter"`` for Markdown frontmatter blocks or ``"line N"``
    for YAML files.
  * ``--json`` mode: a JSON list of ``{"file", "construct_id",
    "position"}`` dicts, sorted by ``(file, position)``.

Exit code: 0 on zero hits, 1 on any hit.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

ANCHOR_ID = "anchor-with-trailing-in-key"
INDENT_ID = "indent-indicator-block-scalar"
TAG_ID = "tag-in-mapping-key"

# A leading list marker ("- ") may or may not be present; the indent
# stripped before the construct is allowed to be any whitespace.
_LIST_PREFIX = r"(?:-\s+)?"
# Anchor in mapping-key position: "&<token> key:" — must mirror what
# ``lib.yaml_parser._check_mapping_key_construct`` actually rejects.
# The parser keys lines on the **first** colon, so the substring
# before the colon is the key.  ``_check_mapping_key_construct``
# splits that key on whitespace; only when the first whitespace-
# separated token starts with ``&`` AND trailing key text exists does
# it raise.  Excluding ``:`` from the anchor-name token is essential:
# a line like ``&a:b key: value`` has key=``&a`` (no trailing text)
# in parser semantics, so it does NOT raise — flagging it in
# preflight would be a false positive that fails clean content at
# the upgrade gate.
_RE_ANCHOR_KEY = re.compile(
    rf"^\s*{_LIST_PREFIX}&[^\s:]*\s+\S[^\n]*?:"
)
# Tag in mapping-key position — must mirror what
# ``lib.yaml_parser._check_mapping_key_construct`` actually rejects.
# The parser raises whenever the first whitespace-separated key token
# starts with ``!``, with **no** "must have trailing key text"
# precondition (unlike the anchor case).  So ``!tag:`` and ``!!str:``
# are upgrade-breaking even though they have no trailing key word.
# Trailing key text remains optional in the regex (matches both
# ``!tag:`` and ``!tag key:`` / ``!!type key:`` shapes).  Excludes
# the YAML directive line ``%TAG …``, which never starts with
# whitespace+``!``.
_RE_TAG_KEY = re.compile(
    rf"^\s*{_LIST_PREFIX}!{{1,2}}\S*(?:\s+\S[^\n]*?)?:"
)
# Block scalar header with indentation indicator (digit 1-9) anywhere
# in the header — accepts the YAML 1.2 forms ``|2``, ``|2-``, ``|-2``,
# ``>2+``, ``>+2``.  Match against the value portion (after ``: ``) so
# bare ``|`` / ``>`` headers (which the parser does support) do not
# trigger.
_RE_INDENT_INDICATOR = re.compile(
    r":\s*[|>](?:[1-9][-+]?|[-+]?[1-9])\s*(?:#.*)?$"
)


def list_tracked_files() -> list[str]:
    """Return absolute paths of every file tracked by ``git ls-files``."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        os.path.join(_REPO_ROOT, p)
        for p in result.stdout.splitlines()
        if p
    ]


def scan_yaml_text(
    text: str, position_for_line: Callable[[int], str]
) -> list[dict]:
    """Return hits for the three constructs in *text*.

    *position_for_line* maps a 1-based line number to the canonical
    ``position`` string used in output (``"line N"`` for YAML files,
    ``"frontmatter"`` for Markdown frontmatter blocks).
    """
    hits: list[dict] = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for line_no, line in enumerate(text.split("\n"), start=1):
        if _RE_ANCHOR_KEY.match(line):
            hits.append(
                {
                    "construct_id": ANCHOR_ID,
                    "position": position_for_line(line_no),
                }
            )
        elif _RE_TAG_KEY.match(line):
            hits.append(
                {
                    "construct_id": TAG_ID,
                    "position": position_for_line(line_no),
                }
            )
        if _RE_INDENT_INDICATOR.search(line):
            hits.append(
                {
                    "construct_id": INDENT_ID,
                    "position": position_for_line(line_no),
                }
            )
    return hits


def extract_frontmatter(text: str) -> str | None:
    """Return the YAML frontmatter block of *text* or ``None`` if absent.

    Markdown without frontmatter is a documented no-op — the caller
    should treat ``None`` as "skip silently."  Delimiter detection is
    line-based: the first line must be exactly ``---`` and the closing
    delimiter must be a standalone ``---`` line, so a ``---`` substring
    inside a YAML block scalar value does not terminate the block early.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\n") == "---":
            return "".join(lines[1:index])
    return None


def scan_file(path: str, rel_path: str) -> list[dict]:
    """Scan *path* and return preflight hits keyed by *rel_path*."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (UnicodeDecodeError, OSError):
        return []

    if rel_path.endswith(".md"):
        block = extract_frontmatter(text)
        if block is None:
            return []
        hits = scan_yaml_text(block, lambda _n: "frontmatter")
    elif rel_path.endswith((".yaml", ".yml")):
        hits = scan_yaml_text(text, lambda n: f"line {n}")
    else:
        return []
    for h in hits:
        h["file"] = rel_path
    return hits


# Conformance-corpus fixtures are intentionally invalid inputs that
# exercise the upgraded ValueError paths.  Skipping them keeps the
# preflight focused on production inputs that would break under the
# upgrade — finding hits in the corpus is the harness's job, not the
# preflight's.
_EXCLUDED_PREFIXES = ("tests/fixtures/yaml-conformance/",)


def collect_hits(paths: list[str]) -> list[dict]:
    """Run :func:`scan_file` over each tracked path and return all hits."""
    hits: list[dict] = []
    for absolute in paths:
        rel = os.path.relpath(absolute, _REPO_ROOT).replace(os.sep, "/")
        if any(rel.startswith(p) for p in _EXCLUDED_PREFIXES):
            continue
        hits.extend(scan_file(absolute, rel))
    hits.sort(key=lambda h: (h["file"], h["position"], h["construct_id"]))
    return hits


def format_human(hits: list[dict]) -> str:
    """Format *hits* as one ``FAIL: ...`` line per hit (no trailing NL)."""
    if not hits:
        return "No grammar-gap hits found across tracked YAML and Markdown."
    lines = [
        f"FAIL: {h['construct_id']} at {h['file']} [{h['position']}]"
        for h in hits
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns 0 on clean run, 1 on any hit."""
    parser = argparse.ArgumentParser(
        description=(
            "Scan every tracked YAML file and Markdown frontmatter block "
            "for inputs that would trip the upgraded YAML parser."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON list of {file, construct_id, position} dicts.",
    )
    args = parser.parse_args(argv)

    paths = list_tracked_files()
    hits = collect_hits(paths)

    if args.json:
        # Drop ``construct_id``-key field ordering for stable output.
        payload = [
            {
                "file": h["file"],
                "construct_id": h["construct_id"],
                "position": h["position"],
            }
            for h in hits
        ]
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_human(hits))

    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
