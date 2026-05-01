"""Detect drift between the hand-maintained Claude Code tool catalog
and the canonical upstream tools reference.

Reads the catalog at ``skill-system-foundry/scripts/lib/configuration.yaml``
under ``allowed_tools.catalogs.claude_code``, fetches the upstream
markdown table at ``provenance.source_url`` (default
``https://code.claude.com/docs/en/tools-reference.md``), and compares
the two sets of tool names.

Outcomes:
  * Additions (upstream has, catalog lacks) — auto-applied to the YAML
    on disk in default mode.
  * Removals (catalog has, upstream lacks) — surfaced in the rendered
    summary as advisory; never auto-applied.  A regex miss or a
    one-version-wide doc edit could falsely propose dropping a real
    tool, so removals always require a human edit.
  * No drift — no file is rewritten.  ``last_checked`` records the
    date of the most recent drift-detected reconciliation; quiet
    runs leave it untouched.  The GitHub Actions run history is the
    "did the sweep run today" signal.

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
``catalogs.<harness>`` YAML structure preserves room for a future
bucket; adding one will require helper changes (``run`` and
``parse_catalog`` would need to iterate harness names), not just a
YAML edit.
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
RE_TABLE_ROW_FIRST_CELL = re.compile(r"^\|\s*`([^`]+)`\s*\|")

# Header row sanity check.  The tools-reference table has a "Tool"
# column (first) and a "Description" column (second).  If the header
# changes shape, hard-fail rather than silently scanning the wrong
# table.
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
    blank line or a non-table line).  The first cell is expected to
    be a backticked identifier; rows without one are skipped silently
    (footers, prose, or row separators).  Identifiers must match the
    PascalCase shape regex.

    Hard-fails (raises :class:`ParseError`) when:
      * No header row matching ``Tool | Description | ...`` is found.
      * The header row has no following body line (truncated table).
      * The header row is not followed by a ``| :--- | :--- | ...``
        separator (table format may have changed).
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
        if not line.startswith("|"):
            break
        if line.strip() == "":
            break
        match = RE_TABLE_ROW_FIRST_CELL.match(line)
        if match is None:
            continue
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
        ``provenance.last_checked``.

    Hard-fails (:class:`ParseError`) when the harness bucket, the
    provenance block, or the harness_tools list is missing or
    malformed.
    """
    lines = yaml_text.splitlines()

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
            "`allowed_tools.catalogs` — add the bucket or update the "
            "harness list in this helper"
        )

    provenance_index = _find_child_key(lines, harness_index, "provenance:")
    if provenance_index < 0:
        raise ParseError(
            f"configuration.yaml has no `provenance:` block under "
            f"`allowed_tools.catalogs.{harness}` — schema migration "
            "incomplete (see issue #118)"
        )

    source_url_line = _find_child_key(
        lines, provenance_index, "source_url:"
    )
    last_checked_line = _find_child_key(
        lines, provenance_index, "last_checked:"
    )
    if source_url_line < 0 or last_checked_line < 0:
        raise ParseError(
            "configuration.yaml is missing `source_url` and/or "
            f"`last_checked` under `{harness}.provenance` — schema "
            "migration incomplete"
        )

    source_url = _scalar_value(lines[source_url_line], "source_url:")
    last_checked = _scalar_value(lines[last_checked_line], "last_checked:")
    if not source_url:
        raise ParseError(
            f"configuration.yaml has an empty `source_url` value under "
            f"`{harness}.provenance` — provide an explicit URL rather "
            "than falling back to a default (silent fallback would "
            "mask misconfigurations)"
        )

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
        if stripped == "" or stripped.startswith("#"):
            continue
        indent = _line_indent(line)
        if indent <= parent_indent:
            end_line = index
            break
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
    """Find *key* under the chain of *parents*.

    Walks forward, descending into each parent in order.  Returns the
    index of the matching line or -1.
    """
    cursor = 0
    parent_indent = -1
    for parent in parents:
        cursor = _find_key_at_or_after(lines, parent, cursor, parent_indent)
        if cursor < 0:
            return -1
        parent_indent = _line_indent(lines[cursor])
        cursor += 1
    return _find_key_at_or_after(lines, key, cursor, parent_indent)


def _find_key_at_or_after(
    lines: list[str], key: str, start: int, parent_indent: int
) -> int:
    """Find *key* starting at line *start*, deeper than *parent_indent*.

    A negative *parent_indent* means "any indent" (used at the
    top-level scan).
    """
    for index in range(start, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        indent = _line_indent(line)
        if parent_indent >= 0 and indent <= parent_indent:
            # Left the parent block — key not found inside it.
            return -1
        if stripped.startswith(key):
            return index
    return -1


def _find_child_key(
    lines: list[str], parent_line: int, key: str
) -> int:
    """Find *key* as a direct child of the mapping declared at *parent_line*.

    A direct child is the first key found at indent strictly greater
    than the parent's indent, before any line at indent <= parent's.
    Returns the line index or -1.
    """
    parent_indent = _line_indent(lines[parent_line])
    return _find_key_at_or_after(lines, key, parent_line + 1, parent_indent)


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
) -> str:
    """Return a human- and PR-body-friendly markdown summary.

    Output is markdown so the same string works for stdout
    (``--dry-run``) and the GitHub PR body.  Sections are omitted
    when empty.
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
        lines.append(
            f"## Additions auto-applied ({len(additions)})"
        )
        lines.append("")
        lines.append(
            "Tools present in upstream but missing from the catalog. "
            "Already added to the YAML in this PR."
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
    (non-dry-run) mode the catalog file is rewritten only when drift
    is detected — additions are applied and ``last_checked`` is
    bumped to *today_iso* in the same write.  Quiet (no-drift) runs
    leave the file untouched.  In dry-run mode no file edits happen
    regardless.

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

    summary = render_summary(additions, removals, source_url, today_iso)
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

    # Only rewrite the file when drift is detected.  ``last_checked``
    # tracks "date the catalog was last changed to reflect upstream",
    # not "date the workflow last ran" — the GitHub Actions run
    # history already provides the latter signal, and bumping the
    # date on every quiet run would produce a noisy commit cadence.
    if not dry_run and drift_detected:
        new_yaml = apply_additions(yaml_text, additions, today_iso)
        if new_yaml != yaml_text:
            with open(catalog_path, "w", encoding="utf-8") as fh:
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
            "Print the planned diff to stdout without modifying the "
            "catalog file. Exits 0 when no drift, 1 when drift "
            "detected, non-zero on errors."
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
        with open(args.summary_out, "w", encoding="utf-8") as fh:
            fh.write(summary)

    if args.dry_run:
        return 1 if drift_detected else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
