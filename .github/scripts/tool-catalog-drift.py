"""Detect drift between the hand-maintained Claude Code tool catalog
and the canonical upstream tools reference.

Reads the catalog at ``skill-system-foundry/scripts/lib/configuration.yaml``
under ``skill.allowed_tools.catalogs.claude_code``, fetches the
upstream markdown table at the URL recorded in
``skill.allowed_tools.catalog_provenance.claude_code.source_url``,
and compares the two sets of tool names.

Outcomes:
  * Additions (upstream has, catalog lacks) — auto-applied to the YAML
    on disk in default mode.
  * Removals (catalog has, upstream lacks) — surfaced in the rendered
    summary as advisory; never auto-applied.  A regex miss or a
    one-version-wide doc edit could falsely propose dropping a real
    tool, so removals always require a human edit.
  * Removals-only drift — the catalog is left untouched (removals
    are advisory only, never applied) and the workflow's
    empty-commit fallback carries the advisory PR.  ``last_checked``
    records the date of the last *additions-applied* reconciliation,
    not the date of every drift event, so a removals-only run does
    not bump it.
  * No drift — no file is rewritten.  Quiet runs leave
    ``last_checked`` untouched; the GitHub Actions run history is
    the "did the sweep run today" signal.

The helper hard-fails on fetch errors, decoding errors, table-shape
mismatches, and zero tokens extracted.  Silent green is the worst
outcome for a drift sweep — every failure mode prints to stderr and
exits non-zero.

Stdlib only.  No third-party dependencies, no cross-tree imports from
the meta-skill: the helper is repo infrastructure under
``.github/scripts/`` and stays isolated from
``skill-system-foundry/scripts/lib/``.

Tracks ``claude_code`` only.  OpenAI Codex has no harness-level tool
catalog by design (every tool is MCP-server-sourced and
user-configured) and Cursor has no documented ``allowed-tools``
dialect, so no second harness ships in this helper.  The
``skill.allowed_tools.catalogs.<harness>`` YAML structure preserves
room for a future bucket; adding one will require helper changes
(``run`` and ``parse_catalog`` would need to iterate harness
names), not just a YAML edit.
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
CATALOG_PATH = os.path.join(
    REPO_ROOT, "skill-system-foundry", "scripts", "lib", "configuration.yaml"
)

# PascalCase token shape.  Matches ``Bash``, ``WebFetch``, ``LSP``, and
# any future PascalCase or all-caps acronym tool name.  Anchored.
RE_HARNESS_SHAPE = re.compile(r"^[A-Z][A-Za-z0-9]*$")

# Backticked-identifier-only first-cell match.  Tools-reference rows
# look like ``| `Bash` | Executes shell commands ... |``.  The pattern
# is anchored against the leading pipe and trailing pipe so prose-only
# rows do not false-positive.
#
# The leading-``|`` requirement is intentional and matches the
# canonical upstream format at
# https://code.claude.com/docs/en/tools-reference.md.  GitHub-Flavored
# Markdown also permits a pipe-less form (``Tool | Description | ...``
# with no leading or trailing ``|``), but the helper does NOT accept
# that form: per the documented hard-fail-on-shape-change contract, an
# upstream switch to pipe-less rendering should surface as a loud
# ``ParseError`` (and a CI-visible workflow failure) so a maintainer
# can update the parser deliberately, rather than being silently
# absorbed at the risk of hiding other simultaneous shape changes.
RE_TABLE_ROW_FIRST_CELL = re.compile(r"^\|\s*`([^`]+)`\s*\|")

# Header row sanity check.  The tools-reference table has a "Tool"
# column (first) and a "Description" column (second).  If the header
# changes shape, hard-fail rather than silently scanning the wrong
# table.  See the leading-pipe rationale above ``RE_TABLE_ROW_FIRST_CELL``.
RE_TABLE_HEADER = re.compile(
    r"^\|\s*Tool\s*\|\s*Description\s*\|", re.IGNORECASE
)
RE_TABLE_SEPARATOR = re.compile(r"^\|\s*[: -]+\s*\|")

# HTTP timeouts.  Generous enough for slow CDNs, tight enough that a
# hung connection does not stall the workflow indefinitely.
FETCH_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DriftHelperError(Exception):
    """Base exception for hard-fail conditions in this helper."""


class FetchError(DriftHelperError):
    """Network or HTTP error while fetching the upstream source."""


class ParseError(DriftHelperError):
    """The catalog YAML or upstream markdown does not have the expected shape."""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch(url: str) -> str:
    """Fetch *url* and return the response body as UTF-8 text.

    Raises :class:`FetchError` on any non-2xx status, network failure,
    or non-UTF-8 body.  No silent green — every error path is loud.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "skill-system-foundry-tool-catalog-drift",
            "Accept": "text/markdown, text/plain, */*",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=FETCH_TIMEOUT_SECONDS
        ) as response:
            status = response.status
            if status < 200 or status >= 300:
                raise FetchError(
                    f"HTTP {status} fetching {url}"
                )
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error fetching {url}: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise FetchError(f"I/O error fetching {url}: {exc}") from exc
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError(
            f"non-UTF-8 response body from {url}"
        ) from exc


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------


def extract_tools(markdown_text: str) -> set[str]:
    """Extract harness tool names from the upstream tools-reference markdown.

    Strategy: locate the header row whose first two columns are
    ``Tool`` and ``Description``, skip the separator row, then read
    the first column of every following row until the table ends (a
    blank line or a non-table line).  Each body row inside the table
    is expected to start with a backticked identifier in the first
    cell; rows that fail this check are treated as table-shape drift
    and raise :class:`ParseError`.  Identifiers must match the
    PascalCase shape regex; well-formed rows whose identifier does
    not (e.g. ``mcp__server__tool``) are skipped silently and do not
    contribute to the extracted set.

    Hard-fails (raises :class:`ParseError`) when:
      * No header row matching ``Tool | Description | ...`` is found.
      * The header row has no following body line (truncated table).
      * The header row is not followed by a ``| :--- | :--- | ...``
        separator (table format may have changed).
      * A body row inside the tools table has no backticked
        identifier in the first cell (table-shape drift).
      * Zero tools are extracted from the body rows.
    """
    lines = markdown_text.splitlines()
    header_index = -1
    for index, line in enumerate(lines):
        if RE_TABLE_HEADER.match(line):
            header_index = index
            break
    if header_index < 0:
        raise ParseError(
            "upstream markdown has no `| Tool | Description | ...` "
            "header row — table format may have changed"
        )
    if header_index + 1 >= len(lines):
        raise ParseError(
            "upstream markdown has a header row but no body — table "
            "format may have changed"
        )
    if not RE_TABLE_SEPARATOR.match(lines[header_index + 1]):
        raise ParseError(
            "upstream markdown header row is not followed by a "
            "separator — table format may have changed"
        )

    tools: set[str] = set()
    for line in lines[header_index + 2:]:
        # Two distinct table-end signals.  Check blank-line first so
        # the ``not line.startswith("|")`` branch handles only the
        # narrower "non-blank, not a table row" case (e.g. a heading
        # or paragraph immediately after the table); blank lines are
        # the more common terminator and reading the strip() check
        # first makes that intent explicit.
        if line.strip() == "":
            break
        if not line.startswith("|"):
            break
        match = RE_TABLE_ROW_FIRST_CELL.match(line)
        if match is None:
            # Row is inside the tools table (starts with ``|``) but
            # its first cell is not a backticked identifier.  Per
            # the helper's hard-fail-on-shape-change contract, this
            # is a real format drift — silently skipping would let
            # an upstream table-format change (e.g. ``| Bash |``
            # without backticks, or an unbackticked separator row
            # injected mid-table) drop tools from ``extracted`` and
            # produce misleading no-drift / advisory-removal output.
            raise ParseError(
                "upstream markdown table row does not start with a "
                f"backticked tool identifier: {line.rstrip()}"
            )
        identifier = match.group(1).strip()
        if RE_HARNESS_SHAPE.match(identifier):
            tools.add(identifier)

    if not tools:
        raise ParseError(
            "upstream markdown produced zero PascalCase tool names — "
            "table format may have changed"
        )
    return tools


# ---------------------------------------------------------------------------
# Parse the catalog (line-based YAML reader for the slice we care about)
# ---------------------------------------------------------------------------


def _line_indent(line: str) -> int:
    """Number of leading space characters on *line*.  Tabs are
    intentionally not counted — the foundry's YAML uses spaces only,
    and a tab anywhere in the slice we read would be a config error
    that we want to surface (downstream parsers fail on it).
    """
    return len(line) - len(line.lstrip(" "))


def parse_catalog(yaml_text: str, harness: str = "claude_code") -> dict:
    """Parse the catalog slice for *harness* from *yaml_text*.

    Returns a mapping with:
      * ``source_url`` — string, the upstream URL.
      * ``last_checked`` — string, the previous check date.
      * ``harness_tools`` — list of strings (insertion order preserved).
      * ``harness_tools_indent`` — int, the indent of each
        ``- ToolName`` list item line; the writer uses this to keep
        added items aligned with existing items.
      * ``harness_tools_end_line`` — int, the index of the line
        immediately after the last existing harness-tool item.  The
        writer inserts new items there.
      * ``last_checked_line`` — int, the line index of
        ``catalog_provenance.<harness>.last_checked``.

    Hard-fails (:class:`ParseError`) when the catalog harness bucket,
    the catalog_provenance harness bucket, or the harness_tools list
    is missing or malformed; also rejects a leftover legacy
    ``provenance:`` child or a misplaced ``catalog_provenance:`` child
    under ``catalogs.<harness>``.
    """
    lines = yaml_text.splitlines()

    # Locate ``catalogs.<harness>`` first so the migration-mistake
    # checks (legacy ``provenance:`` and misplaced
    # ``catalog_provenance:`` directly under the harness bucket) can
    # fire BEFORE the top-level ``catalog_provenance`` lookup.  A user
    # who put the new key in the wrong place would otherwise hit the
    # generic "missing top-level catalog_provenance" message and miss
    # the actionable wrong-path/right-path guidance below.
    catalogs_index = _find_key_line(
        lines, "catalogs:", parents=("skill:", "allowed_tools:")
    )
    if catalogs_index < 0:
        raise ParseError(
            "configuration.yaml has no `catalogs:` block under "
            "`skill.allowed_tools` — schema mismatch"
        )

    harness_index = _find_child_key(
        lines, catalogs_index, f"{harness}:"
    )
    if harness_index < 0:
        raise ParseError(
            f"configuration.yaml has no `{harness}:` bucket under "
            "`skill.allowed_tools.catalogs` — add the bucket or "
            "update the harness list in this helper"
        )

    # Reject a leftover legacy ``provenance:`` child even when the new
    # ``catalog_provenance.<harness>`` key is also present.  A
    # partial-migration YAML carrying both shapes would otherwise parse
    # cleanly and silently re-introduce the non-list child this schema
    # move is meant to make impossible under ``catalogs.<harness>``.
    legacy_provenance_index = _find_child_key(
        lines, harness_index, "provenance:"
    )
    if legacy_provenance_index >= 0:
        raise ParseError(
            f"configuration.yaml still has a legacy `provenance:` child "
            f"under `skill.allowed_tools.catalogs.{harness}` — remove "
            "it; provenance now lives at "
            f"`skill.allowed_tools.catalog_provenance.{harness}`"
        )

    # Also reject a misplaced ``catalog_provenance:`` *under* the
    # harness bucket — the new schema requires it to live as a sibling
    # of ``catalogs:`` at ``skill.allowed_tools.catalog_provenance``,
    # not nested under any ``catalogs.<harness>``.  This check runs
    # before the top-level lookup below so a single-mistake migration
    # (only the misplaced version, no top-level one) still produces
    # the actionable wrong-path/right-path guidance instead of the
    # generic "missing top-level catalog_provenance" error.
    misplaced_provenance_index = _find_child_key(
        lines, harness_index, "catalog_provenance:"
    )
    if misplaced_provenance_index >= 0:
        raise ParseError(
            f"configuration.yaml has a misplaced `catalog_provenance:` "
            f"child under `skill.allowed_tools.catalogs.{harness}` — "
            "move it to the sibling top-level key "
            f"`skill.allowed_tools.catalog_provenance.{harness}`"
        )

    # Provenance lives under a sibling top-level key
    # ``skill.allowed_tools.catalog_provenance.<harness>`` so
    # ``catalogs.<harness>`` stays a pure tool-name source (every
    # direct child is a list of tool names).
    catalog_prov_index = _find_key_line(
        lines, "catalog_provenance:", parents=("skill:", "allowed_tools:")
    )
    if catalog_prov_index < 0:
        raise ParseError(
            "configuration.yaml has no `catalog_provenance:` block "
            "under `skill.allowed_tools` — schema mismatch"
        )

    harness_prov_index = _find_child_key(
        lines, catalog_prov_index, f"{harness}:"
    )
    if harness_prov_index < 0:
        raise ParseError(
            f"configuration.yaml has no `{harness}:` bucket under "
            "`skill.allowed_tools.catalog_provenance` — add the "
            "bucket or update the harness list in this helper"
        )

    source_url_line = _find_child_key(
        lines, harness_prov_index, "source_url:"
    )
    last_checked_line = _find_child_key(
        lines, harness_prov_index, "last_checked:"
    )
    if source_url_line < 0 or last_checked_line < 0:
        raise ParseError(
            "configuration.yaml is missing `source_url` and/or "
            f"`last_checked` under "
            f"`skill.allowed_tools.catalog_provenance.{harness}` — "
            "schema migration incomplete"
        )

    source_url = _scalar_value(lines[source_url_line], "source_url:")
    last_checked = _scalar_value(lines[last_checked_line], "last_checked:")
    if not source_url:
        raise ParseError(
            f"configuration.yaml has an empty `source_url` value under "
            f"`skill.allowed_tools.catalog_provenance.{harness}` — "
            "provide an explicit URL rather than falling back to a "
            "default (silent fallback would mask misconfigurations)"
        )
    if not last_checked:
        raise ParseError(
            f"configuration.yaml has an empty `last_checked` value "
            f"under `skill.allowed_tools.catalog_provenance.{harness}` — "
            "provide an explicit ISO-8601 `YYYY-MM-DD` date so a "
            "no-drift / removals-only run cannot leave the catalog "
            "in an unprovenanced state"
        )
    # ``datetime.date.fromisoformat`` alone accepts the compact ISO
    # form (e.g. ``20260501``) since Python 3.11.  Pre-check the
    # exact ``YYYY-MM-DD`` shape so the helper enforces the format it
    # documents — otherwise a hyphen-less value would round-trip into
    # ``configuration.yaml`` even though the canary and the workflow
    # both assume canonical extended-form dates.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_checked):
        raise ParseError(
            f"configuration.yaml has an invalid `last_checked` value "
            f"under `skill.allowed_tools.catalog_provenance.{harness}`: "
            f"{last_checked!r} — expected ISO-8601 `YYYY-MM-DD` "
            "(extended form with hyphen separators)"
        )
    try:
        datetime.date.fromisoformat(last_checked)
    except ValueError as exc:
        raise ParseError(
            f"configuration.yaml has an invalid `last_checked` value "
            f"under `skill.allowed_tools.catalog_provenance.{harness}`: "
            f"{last_checked!r} — expected ISO-8601 `YYYY-MM-DD`"
        ) from exc

    harness_tools_index = _find_child_key(
        lines, harness_index, "harness_tools:"
    )
    if harness_tools_index < 0:
        raise ParseError(
            f"configuration.yaml has no `harness_tools:` list under "
            f"`{harness}` — schema mismatch"
        )

    parent_indent = _line_indent(lines[harness_tools_index])
    item_indent: int | None = None
    items: list[str] = []
    end_line = harness_tools_index + 1
    for index in range(harness_tools_index + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        # Check dedent BEFORE the blank/comment fast-path so a sibling
        # comment at the same indent as ``harness_tools:`` terminates
        # the list scan.  Without this, a comment block documenting the
        # next sibling key (e.g. the ``# Generic CLI names...`` block
        # in the foundry catalog) is silently skipped, ``end_line`` is
        # advanced past the comment, and ``apply_additions`` then
        # inserts new items between the comment and the key it
        # documents — splitting the doc from its key in the diff.
        # Blank lines (indent 0) terminate the same way: standard YAML
        # lists do not contain blank lines between items.
        indent = _line_indent(line)
        if indent <= parent_indent:
            end_line = index
            break
        if stripped == "" or stripped.startswith("#"):
            continue
        if not stripped.startswith("- "):
            end_line = index
            break
        if item_indent is None:
            item_indent = indent
        elif indent != item_indent:
            raise ParseError(
                f"configuration.yaml has inconsistent indentation in "
                f"`{harness}.harness_tools` at line {index + 1} — "
                "schema mismatch"
            )
        token = stripped[2:].strip()
        if not token:
            raise ParseError(
                f"configuration.yaml has an empty list item in "
                f"`{harness}.harness_tools` at line {index + 1}"
            )
        items.append(token)
        end_line = index + 1

    if item_indent is None:
        # Empty list — preserve a sensible insertion indent.  Use
        # ``parent_indent + 2`` (foundry convention).
        item_indent = parent_indent + 2

    return {
        "source_url": source_url,
        "last_checked": last_checked,
        "harness_tools": items,
        "harness_tools_indent": item_indent,
        "harness_tools_end_line": end_line,
        "last_checked_line": last_checked_line,
    }


def _find_key_line(
    lines: list[str], key: str, parents: tuple[str, ...]
) -> int:
    """Find *key* as a direct child of the chain of *parents*.

    Walks forward, descending into each parent in order, then looks
    for *key* at the direct-child indent of the deepest parent.  Both
    the parent descent and the final lookup enforce direct-child
    semantics — a same-named key nested deeper in the subtree (or
    embedded in a block scalar that happens to look like YAML) cannot
    bind by accident.  Returns the line index or -1.
    """
    cursor = 0
    parent_indent = -1
    for parent in parents:
        cursor = _find_direct_child_at_or_after(
            lines, parent, cursor, parent_indent
        )
        if cursor < 0:
            return -1
        parent_indent = _line_indent(lines[cursor])
        cursor += 1
    return _find_direct_child_at_or_after(lines, key, cursor, parent_indent)


def _find_direct_child_at_or_after(
    lines: list[str], key: str, start: int, parent_indent: int
) -> int:
    """Find *key* as a direct child starting at line *start*.

    A direct child is a key at the first non-blank/non-comment indent
    encountered deeper than *parent_indent*.  Lines at greater depth
    (descendants) are skipped so a future nested key with the same
    name cannot bind by accident.  Returns the line index or -1 if
    the parent block ends before finding *key*.

    A negative *parent_indent* means "no parent" — the first key
    encountered sets the direct-child indent (matches top-level keys).
    """
    direct_child_indent: int | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        indent = _line_indent(line)
        if parent_indent >= 0 and indent <= parent_indent:
            return -1
        if direct_child_indent is None:
            direct_child_indent = indent
        elif indent != direct_child_indent:
            continue
        if stripped.startswith(key):
            return index
    return -1


def _find_child_key(
    lines: list[str], parent_line: int, key: str
) -> int:
    """Find *key* as a direct child of the mapping declared at *parent_line*.

    A direct child is a key at the first non-blank/non-comment indent
    deeper than the parent's indent.  Descendants at greater depth are
    skipped so a same-named nested key cannot bind by accident.
    Returns the line index or -1.
    """
    parent_indent = _line_indent(lines[parent_line])
    return _find_direct_child_at_or_after(
        lines, key, parent_line + 1, parent_indent
    )


def _scalar_value(line: str, key: str) -> str:
    """Return the scalar value following *key* on *line*.

    Strips inline ``# comment`` tails, surrounding whitespace, and
    matching surrounding quotes (single or double).  Returns ``""`` if
    the key has no value (a list-introducing scalar).
    """
    after_key = line.split(key, 1)[1]
    # Strip trailing inline comment.  YAML allows a comment after a
    # space; a literal ``#`` inside a quoted scalar is preserved by
    # this helper, since the configuration file does not use ``#`` in
    # scalar values today.
    hash_index = after_key.find(" #")
    if hash_index >= 0:
        after_key = after_key[:hash_index]
    value = after_key.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def diff(
    catalog: set[str], extracted: set[str]
) -> tuple[set[str], set[str]]:
    """Return ``(additions, removals)`` between *catalog* and *extracted*.

    Additions are tools in *extracted* not in *catalog* (upstream-led).
    Removals are tools in *catalog* not in *extracted* (catalog-led).
    """
    return (extracted - catalog, catalog - extracted)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_additions(
    yaml_text: str,
    additions: set[str],
    today_iso: str,
    harness: str = "claude_code",
) -> str:
    """Return *yaml_text* with *additions* appended to the harness-tools
    list and ``last_checked`` rewritten to *today_iso*.

    Additions are inserted in alphabetical order at the end of the
    existing list — preserves the existing order of catalog entries
    (so the diff stays readable) while keeping new entries
    deterministic.  Removals are NOT applied here; they are rendered
    in the human-readable summary for review.

    If *additions* is empty, only ``last_checked`` is updated.
    """
    parsed = parse_catalog(yaml_text, harness=harness)
    lines = yaml_text.splitlines(keepends=True)
    indent = " " * parsed["harness_tools_indent"]

    existing = set(parsed["harness_tools"])
    new_items = [
        f"{indent}- {tool}\n"
        for tool in sorted(additions)
        if tool not in existing
    ]

    insert_at = parsed["harness_tools_end_line"]

    rebuilt: list[str] = []
    for index, line in enumerate(lines):
        if index == insert_at and new_items:
            rebuilt.extend(new_items)
        if index == parsed["last_checked_line"]:
            rebuilt.append(_replace_scalar(line, "last_checked:", today_iso))
        else:
            rebuilt.append(line)

    if insert_at >= len(lines) and new_items:
        # End-of-file insertion — list runs to the very last line.
        # If that last line lacks a trailing newline, appending the
        # first ``- Tool\n`` would concatenate it onto the previous
        # line and produce invalid YAML.  Repair the previous line
        # before extending.
        if rebuilt and not rebuilt[-1].endswith("\n"):
            rebuilt[-1] += "\n"
        rebuilt.extend(new_items)

    return "".join(rebuilt)


def _replace_scalar(line: str, key: str, value: str) -> str:
    """Rewrite the scalar after *key* on *line* to *value*.

    Preserves leading whitespace, the key, the gap between key and
    value (a single space), and the trailing newline.  Always
    double-quotes the value for stylistic consistency with the
    existing ``last_checked: "YYYY-MM-DD"`` form in the catalog and
    to keep the rewritten value safe under stricter YAML 1.1 readers
    (PyYAML and friends), which DO coerce unquoted ISO-8601 dates
    to ``datetime.date``.  The foundry's own subset parser returns
    every scalar as a string, so for foundry consumers the quoting
    is purely cosmetic; the defensive form helps third-party tooling
    that may load this file.
    """
    leading_ws = line[: len(line) - len(line.lstrip(" "))]
    eol = "\n" if line.endswith("\n") else ""
    return f'{leading_ws}{key} "{value}"{eol}'


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_summary(
    additions: set[str],
    removals: set[str],
    source_url: str,
    today_iso: str,
    applied: bool = True,
) -> str:
    """Return a human- and PR-body-friendly markdown summary.

    Output is markdown so the same string works for stdout
    (``--dry-run``) and the GitHub PR body.  Sections are omitted
    when empty.

    *applied* controls the verb tense in the additions section:
    ``True`` (default, for non-dry-run runs and the workflow's
    PR-body output) renders "auto-applied" / "Already added"; ``False``
    (for ``--dry-run``) renders "would be applied" / "Would be added"
    so the output does not falsely claim file mutation.
    """
    lines: list[str] = []
    if additions or removals:
        lines.append("# Tool catalog drift detected")
    else:
        lines.append("# No drift detected")
    lines.append("")
    lines.append(f"- **Source:** {source_url}")
    lines.append(f"- **Checked:** {today_iso}")
    lines.append("")

    if additions:
        if applied:
            lines.append(
                f"## Additions auto-applied ({len(additions)})"
            )
            lines.append("")
            lines.append(
                "Tools present in upstream but missing from the "
                "catalog. Already added to the YAML in this PR."
            )
        else:
            lines.append(
                f"## Additions that would be applied ({len(additions)})"
            )
            lines.append("")
            lines.append(
                "Tools present in upstream but missing from the "
                "catalog. Dry run — no file mutation; running "
                "without `--dry-run` would add these to the YAML."
            )
        lines.append("")
        for tool in sorted(additions):
            lines.append(f"- `{tool}`")
        lines.append("")

    if removals:
        lines.append(
            f"## Candidate removals — review before deleting ({len(removals)})"
        )
        lines.append("")
        lines.append(
            "Tools in the catalog but not seen in the upstream tools "
            "reference table. NOT auto-removed — verify each name "
            "before deleting. Possible causes: upstream renamed or "
            "removed the tool, the table format changed, or the "
            "extraction missed a row."
        )
        lines.append("")
        for tool in sorted(removals):
            lines.append(f"- `{tool}`")
        lines.append("")

    if not additions and not removals:
        lines.append(
            "All catalog tools match the upstream tools reference. "
            "No catalog changes written — quiet runs leave "
            "`last_checked` untouched."
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _today_iso() -> str:
    return datetime.date.today().isoformat()


def run(
    catalog_path: str,
    today_iso: str,
    dry_run: bool,
) -> tuple[bool, str, dict]:
    """Run the drift sweep against the catalog at *catalog_path*.

    Returns ``(drift_detected, summary, json_payload)``.  In default
    (non-dry-run) mode the catalog file is rewritten only when there
    are additions to apply — additions are inserted and
    ``last_checked`` is bumped to *today_iso* in the same write.
    Removals-only drift leaves the file untouched (removals are
    advisory and never applied); the workflow surfaces those via the
    PR body.  Quiet (no-drift) runs also leave the file untouched.
    In dry-run mode no file edits happen regardless.

    Raises :class:`FetchError` or :class:`ParseError` on hard-fail
    conditions; the caller maps those to non-zero exit codes.
    """
    with open(catalog_path, "r", encoding="utf-8") as fh:
        yaml_text = fh.read()

    parsed = parse_catalog(yaml_text)
    source_url = parsed["source_url"]

    markdown = fetch(source_url)
    extracted = extract_tools(markdown)
    catalog = set(parsed["harness_tools"])
    additions, removals = diff(catalog, extracted)

    summary = render_summary(
        additions, removals, source_url, today_iso, applied=not dry_run,
    )
    drift_detected = bool(additions or removals)
    json_payload = {
        "drift": drift_detected,
        "source_url": source_url,
        "checked": today_iso,
        "additions": sorted(additions),
        "removals": sorted(removals),
        "catalog_size": len(catalog),
        "upstream_size": len(extracted),
    }

    # Rewrite the catalog only when there are additions to apply.
    # ``last_checked`` records "date the catalog was last changed to
    # reflect upstream", which means the date of the last
    # auto-applied additions — not the date of any drift-detection
    # run.  Removals are advisory only; bumping ``last_checked`` for
    # a removals-only run would mutate the catalog despite nothing
    # being applied, producing date-only churn that contradicts the
    # advisory-only contract.  Quiet runs (no drift) and removals-only
    # drift therefore both leave the file untouched; the workflow's
    # empty-commit fallback carries the advisory PR for removals.
    if not dry_run and additions:
        new_yaml = apply_additions(yaml_text, additions, today_iso)
        if new_yaml != yaml_text:
            with open(catalog_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new_yaml)

    return (drift_detected, summary, json_payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect drift between the Claude Code tool catalog in "
            "configuration.yaml and the canonical upstream tools "
            "reference. Auto-applies additions; flags removals as "
            "advisory."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the planned summary to stdout (or JSON with "
            "--json) without modifying the catalog file. Exits 0 "
            "when no drift, 1 when drift detected, non-zero on "
            "errors."
        ),
    )
    parser.add_argument(
        "--catalog-path",
        default=CATALOG_PATH,
        help=(
            "Path to configuration.yaml. Defaults to the foundry's "
            "canonical location."
        ),
    )
    parser.add_argument(
        "--today",
        default=None,
        help=(
            "Override today's date (ISO 8601 YYYY-MM-DD) for "
            "deterministic test runs. Defaults to the system date."
        ),
    )
    parser.add_argument(
        "--summary-out",
        default=None,
        help=(
            "If set, write the rendered summary to this path "
            "(in addition to printing it to stdout). Used by the "
            "workflow to compose the PR body."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit the drift result as a JSON object to stdout instead "
            "of human-readable markdown. Object keys: drift (bool), "
            "source_url, checked, additions, removals, catalog_size, "
            "upstream_size. Useful for tooling consumers."
        ),
    )
    args = parser.parse_args(argv)

    today_iso = args.today or _today_iso()

    try:
        drift_detected, summary, json_payload = run(
            catalog_path=args.catalog_path,
            today_iso=today_iso,
            dry_run=args.dry_run,
        )
    except FetchError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    except ParseError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"FAIL: I/O error: {exc}", file=sys.stderr)
        return 4

    if args.json:
        sys.stdout.write(json.dumps(json_payload, indent=2, sort_keys=True))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(summary)

    if args.summary_out:
        # Match the helper's documented hard-fail contract: an I/O
        # error here (missing parent dir, unwritable path, full disk)
        # surfaces as exit 4 with a stderr message, not a bare
        # traceback.  The summary-out write is the workflow's only
        # path to the PR body, so a clean failure mode matters.
        try:
            with open(args.summary_out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(summary)
        except OSError as exc:
            print(f"FAIL: I/O error writing summary: {exc}", file=sys.stderr)
            return 4

    if args.dry_run:
        return 1 if drift_detected else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
