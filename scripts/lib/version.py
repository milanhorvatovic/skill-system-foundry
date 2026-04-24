"""Shared version-string helpers for repo-infrastructure scripts.

This module is local to the top-level ``scripts/`` tree.  It is intentionally
independent from the meta-skill tree at ``skill-system-foundry/scripts/`` —
no imports cross between the two trees.  The regex shape mirrors
``RE_METADATA_VERSION`` inside the meta-skill's ``configuration.yaml``; keep
them in lockstep by hand.

The module exposes three kinds of primitives:

* semver validation (``SEMVER_RE``, ``parse``, ``compare``)
* read helpers that extract the current version from each manifest file
  (``read_skill_md_version``, ``read_plugin_json_version``,
  ``read_marketplace_json_version``)
* plan-edit helpers that return new file content with the version field
  replaced (``plan_skill_md_edit``, ``plan_plugin_json_edit``,
  ``plan_marketplace_json_edit``).  Each plan-edit helper raises
  ``ValueError`` when the anchored regex matches zero or multiple times,
  so callers can surface a structural failure instead of writing a
  subtly wrong file.
"""

import json
import os
import re


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?$")


def parse(version: str) -> tuple[int, int, int, str]:
    """Split *version* into ``(major, minor, patch, prerelease)``.

    The prerelease component is the substring after the first ``-`` (empty
    string when absent).  Build metadata is rejected by ``SEMVER_RE``.
    Raises ``ValueError`` when *version* does not match ``SEMVER_RE``.
    """
    if not SEMVER_RE.match(version):
        raise ValueError(f"not a valid semver: {version!r}")
    core, _, pre = version.partition("-")
    major, minor, patch = core.split(".")
    return (int(major), int(minor), int(patch), pre)


def compare(a: str, b: str) -> int:
    """Return -1/0/1 comparing semver *a* against *b*.

    Integer-tuple compare on ``(major, minor, patch)``.  Prerelease tie-breaker
    follows the essential semver rule — a version with a prerelease is less
    than the same version without one — but does not attempt to rank
    prerelease identifiers against each other.  When both sides carry a
    prerelease, the comparison falls back to lexicographic order of the
    prerelease strings.  This is a deliberate simplification; document it
    at call sites if strict ranking becomes necessary.
    """
    ma, mi, pa, pre_a = parse(a)
    mb, ni, pb, pre_b = parse(b)
    core_a = (ma, mi, pa)
    core_b = (mb, ni, pb)
    if core_a < core_b:
        return -1
    if core_a > core_b:
        return 1
    if pre_a == pre_b:
        return 0
    if not pre_a:
        return 1
    if not pre_b:
        return -1
    if pre_a < pre_b:
        return -1
    return 1


# ---------------------------------------------------------------------------
# read helpers
# ---------------------------------------------------------------------------


def _extract_frontmatter(content: str) -> str | None:
    """Return the YAML frontmatter block of *content*, or ``None`` when absent.

    A frontmatter block opens with ``---`` on the first line and closes on
    the next line that is exactly ``---`` (trailing whitespace allowed).
    """
    if not content.startswith("---"):
        return None
    first_newline = content.find("\n")
    if first_newline < 0:
        return None
    close_match = re.search(
        r"^---\s*$", content[first_newline + 1:], re.MULTILINE
    )
    if close_match is None:
        return None
    return content[first_newline + 1:first_newline + 1 + close_match.start()]


def _strip_yaml_scalar_quotes(value: str) -> str:
    """Strip matched surrounding single/double quotes from a YAML scalar."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def read_skill_md_version(path: str) -> str | None:
    """Read ``metadata.version`` from a SKILL.md file.

    Returns ``None`` when the file has no frontmatter, when the frontmatter
    has no ``metadata`` block, or when ``metadata.version`` is absent.
    Raises ``OSError`` when the file cannot be read.
    """
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()
    frontmatter = _extract_frontmatter(content)
    if frontmatter is None:
        return None
    in_metadata = False
    for line in frontmatter.splitlines():
        if not line.strip():
            continue
        if line.rstrip() == "metadata:":
            in_metadata = True
            continue
        if in_metadata:
            if line and not line[0].isspace():
                # Left the metadata block without finding version.
                return None
            match = re.match(r"^\s+version:\s*(\S.*)$", line)
            if match:
                return _strip_yaml_scalar_quotes(match.group(1))
    return None


def read_plugin_json_version(path: str) -> str | None:
    """Read the top-level ``version`` field from ``plugin.json``.

    Returns ``None`` when the key is absent or not a string.  Raises
    ``OSError`` / ``json.JSONDecodeError`` on file or parse errors — the
    caller decides whether to surface those as a FAIL or a crash.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    value = data.get("version") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def read_marketplace_json_version(
    path: str, plugin_name: str
) -> str | None:
    """Read ``plugins[name=<plugin_name>].version`` from ``marketplace.json``.

    Matches the plugin entry by ``name`` (mirroring the convention used by
    ``tests/test_claude_distribution_metadata.py``).  Returns ``None`` when
    no matching entry exists or when the entry lacks a string ``version``.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return None
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return None
    for entry in plugins:
        if not isinstance(entry, dict):
            continue
        if entry.get("name") == plugin_name:
            value = entry.get("version")
            return value if isinstance(value, str) else None
    return None


def read_plugin_name(path: str) -> str | None:
    """Read the top-level ``name`` field from ``plugin.json``."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    value = data.get("name") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


# ---------------------------------------------------------------------------
# plan-edit helpers
# ---------------------------------------------------------------------------


def plan_skill_md_edit(content: str, current: str, new: str) -> str:
    """Return *content* with ``metadata.version`` changed from *current* to *new*.

    Edits are restricted to the frontmatter block so a stray ``version:`` line
    in the body cannot be rewritten.  Raises ``ValueError`` when the
    anchored pattern does not match exactly once.
    """
    if not content.startswith("---"):
        raise ValueError("SKILL.md missing opening '---' frontmatter delimiter")
    first_newline = content.find("\n")
    if first_newline < 0:
        raise ValueError("SKILL.md frontmatter is truncated")
    close_match = re.search(
        r"^---\s*$", content[first_newline + 1:], re.MULTILINE
    )
    if close_match is None:
        raise ValueError("SKILL.md frontmatter is not terminated")
    fm_start = first_newline + 1
    fm_end = fm_start + close_match.start()
    frontmatter = content[fm_start:fm_end]

    pattern = re.compile(
        rf"^(?P<prefix>\s+version:\s*){re.escape(current)}(?P<suffix>\s*)$",
        re.MULTILINE,
    )
    matches = pattern.findall(frontmatter)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one 'version: {current}' line in SKILL.md "
            f"frontmatter, found {len(matches)}"
        )
    new_frontmatter = pattern.sub(
        lambda m: f"{m.group('prefix')}{new}{m.group('suffix')}",
        frontmatter,
        count=1,
    )
    return content[:fm_start] + new_frontmatter + content[fm_end:]


def _plan_json_version_edit(
    content: str, current: str, new: str, label: str
) -> str:
    """Replace a ``"version": "<current>"`` line with *new*.

    The anchored pattern targets an indented key at any depth but refuses to
    run unless exactly one line matches.  *label* is used only in error
    messages so the caller's ``ValueError`` is actionable.
    """
    pattern = re.compile(
        rf'^(?P<prefix>\s+"version"\s*:\s*"){re.escape(current)}'
        rf'(?P<suffix>"\s*,?\s*)$',
        re.MULTILINE,
    )
    matches = pattern.findall(content)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one '\"version\": \"{current}\"' line in "
            f"{label}, found {len(matches)}"
        )
    return pattern.sub(
        lambda m: f"{m.group('prefix')}{new}{m.group('suffix')}",
        content,
        count=1,
    )


def plan_plugin_json_edit(content: str, current: str, new: str) -> str:
    """Return *content* of plugin.json with ``version`` changed to *new*."""
    return _plan_json_version_edit(content, current, new, "plugin.json")


def plan_marketplace_json_edit(content: str, current: str, new: str) -> str:
    """Return *content* of marketplace.json with the plugin ``version`` set to *new*.

    The marketplace file is expected to contain exactly one plugin entry
    whose version matches *current*; the single-match guard enforces that.
    """
    return _plan_json_version_edit(content, current, new, "marketplace.json")


# ---------------------------------------------------------------------------
# path helpers
# ---------------------------------------------------------------------------


def skill_md_path(repo_root: str) -> str:
    return os.path.join(repo_root, "skill-system-foundry", "SKILL.md")


def plugin_json_path(repo_root: str) -> str:
    return os.path.join(repo_root, ".claude-plugin", "plugin.json")


def marketplace_json_path(repo_root: str) -> str:
    return os.path.join(repo_root, ".claude-plugin", "marketplace.json")
