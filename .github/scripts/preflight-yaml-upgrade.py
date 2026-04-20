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
from collections.abc import Callable

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

ANCHOR_ID = "anchor-with-trailing-in-key"
INDENT_ID = "indent-indicator-block-scalar"
TAG_ID = "tag-in-mapping-key"
# Synthetic construct-id surfaced when a tracked in-scope file
# (``.md`` / ``.yaml`` / ``.yml``) cannot be read or decoded as
# UTF-8.  The preflight gate fails loud on these so a corrupted
# tracked file is not silently treated as "clean".
UNREADABLE_ID = "unreadable-file"

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
# precondition (unlike the anchor case).  So ``!tag:``, ``!!str:``,
# ``! :``, and ``!tag :`` are all upgrade-breaking — anything before
# the line's first ``:`` whose first ``\S`` token starts with ``!``
# raises.  ``[^\n]*?`` (non-greedy) between the tag token and the
# colon covers trailing key text and bare-whitespace gap forms
# without missing parser-rejected shapes.  Excludes the YAML
# directive line ``%TAG …``, which never starts with whitespace+``!``.
_RE_TAG_KEY = re.compile(
    rf"^\s*{_LIST_PREFIX}!{{1,2}}\S*[^\n]*?:"
)
# Block scalar header with indentation indicator (digit 1-9) in the
# header — mirrors ``lib.yaml_parser._is_indent_indicator_header``.
# Accepts the YAML 1.2 forms ``|2``, ``|2-``, ``|-2``, ``|+2``,
# ``|2+`` (and the ``>`` variants).  Anchored to ``^<key>:`` (with
# optional indent and list marker).  The key segment is ``[^:\n]+?``
# so keys containing spaces (e.g. ``my key: |2``) match — the parser
# uses ``find(":")`` to slice keys from values, and raises on the
# value regardless of key text, so preflight must too.  Trade-off:
# block-scalar literal content shaped like ``some text: |2 more``
# can false-positive (preflight has no structural awareness of which
# line is content vs key); the upside is no real parser-failure
# shape slips past the gate.  Whitespace after ``:`` is **optional**
# (``\s*``) to mirror ``parse_yaml_subset`` stripping the post-colon
# value.  Requires whitespace or end-of-line after the indicator —
# ``|2#note`` (no space before ``#``) is plain-scalar territory that
# the parser does not raise on, so preflight must not either.
_RE_INDENT_INDICATOR = re.compile(
    rf"^\s*{_LIST_PREFIX}[^:\n]+?:\s*[|>](?:[1-9][-+]?|[-+][1-9])(?:\s|$)"
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
        # Skip whole-line comments — the parser never treats their
        # contents as keys/values, so flagging a colon inside a comment
        # would be a false positive.  Block-scalar literal content is
        # harder to detect without structural parsing; the anchored
        # ``^\\s*<key>:`` pattern in the construct regexes mitigates
        # that case for keys, but is not exhaustive.
        if line.lstrip().startswith("#"):
            continue
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
    """Scan *path* and return preflight hits keyed by *rel_path*.

    Out-of-scope files (anything that is not ``.md`` / ``.yaml`` /
    ``.yml``) are skipped before any I/O so the walk does not read
    and decode every tracked file in the repo.  Two side benefits:
    less work, and UTF-8 decode failures on out-of-scope binaries
    (images, fonts) never reach the silent-skip path.
    """
    is_markdown = rel_path.endswith(".md")
    is_yaml = rel_path.endswith((".yaml", ".yml"))
    if not is_markdown and not is_yaml:
        return []

    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (UnicodeDecodeError, OSError) as exc:
        # In-scope file that cannot be read or UTF-8 decoded must
        # surface as a failure rather than silently disappearing —
        # otherwise the upgrade gate trusts a corrupted tracked file
        # the same as a clean one.
        return [
            {
                "construct_id": UNREADABLE_ID,
                "position": f"read-error: {type(exc).__name__}",
                "file": rel_path,
            }
        ]

    if is_markdown:
        block = extract_frontmatter(text)
        if block is None:
            return []
        hits = scan_yaml_text(block, lambda _n: "frontmatter")
    else:
        hits = scan_yaml_text(text, lambda n: f"line {n}")
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
