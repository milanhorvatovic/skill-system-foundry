"""Shared validation functions for skill-system-foundry scripts."""

import difflib
import glob
import os
import re

from .constants import (
    MAX_NAME_CHARS, MIN_NAME_CHARS,
    RE_NAME_FORMAT, RESERVED_NAMES,
    KNOWN_FRONTMATTER_KEYS, KNOWN_TOOLS, MAX_ALLOWED_TOOLS,
    RE_METADATA_VERSION,
    MAX_AUTHOR_LENGTH, KNOWN_SPDX_LICENSES,
    FRONTMATTER_SUGGEST_MAX_MATCHES, FRONTMATTER_SUGGEST_CUTOFF,
    HARNESS_TOOLS_CLAUDE_CODE,
    RE_MCP_TOOL_NAME, RE_HARNESS_TOOL_SHAPE,
    TOOL_FENCE_LANGUAGES, TOOLS_INDICATING_SCRIPTS,
    DIR_CAPABILITIES, DIR_SCRIPTS,
    FILE_CAPABILITY_MD, FILE_SKILL_MD,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
)
from .fence_scan import has_fence_with_language
from .frontmatter import strip_frontmatter_for_scan


# Regex used to strip the optional ``(...)`` argument suffix from
# ``allowed-tools`` tokens before comparison.  Nested parens in
# ``allowed-tools`` patterns are not realistic in practice, so a
# non-greedy match is sufficient.
_RE_PAREN_ARGS = re.compile(r"\([^)]*\)")


def parse_allowed_tools_tokens(value: object) -> set[str]:
    """Normalise an ``allowed-tools`` frontmatter value to bare tokens.

    The agentskills.io spec defines ``allowed-tools`` as a
    space-separated string; Claude Code accepts both that and a YAML
    list.  Tokens may carry an optional ``(...)`` argument pattern
    (e.g. ``Bash(git add *)``).  This helper accepts either form,
    strips the parenthesised suffix, and returns the bare tokens as a
    set so consumers can do membership / superset checks without
    reparsing.

    Returns an empty set for ``None``, non-string / non-list scalars,
    or empty / whitespace-only input.
    """
    if value is None:
        return set()
    raw_pieces: list[str] = []
    if isinstance(value, str):
        raw_pieces.append(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                raw_pieces.append(item)
    else:
        return set()
    tokens: set[str] = set()
    for piece in raw_pieces:
        cleaned = _RE_PAREN_ARGS.sub("", piece)
        for token in cleaned.split():
            if token:
                tokens.add(token)
    return tokens


def validate_name(name: str, dir_name: str) -> tuple[list[str], list[str]]:
    """Validate the name field.

    Checks spec rules (format, length, directory match), platform
    restrictions (Anthropic reserved words), and foundry conventions
    (minimum name length advisory).
    """
    errors: list[str] = []
    passes: list[str] = []

    if not name:
        errors.append(f"{LEVEL_FAIL}: [spec] 'name' field is empty")
        return errors, passes

    if len(name) > MAX_NAME_CHARS:
        errors.append(f"{LEVEL_FAIL}: [spec] 'name' exceeds {MAX_NAME_CHARS} characters ({len(name)} chars)")
    else:
        passes.append(f"name: {len(name)} chars (max {MAX_NAME_CHARS})")

    if name != name.lower():
        errors.append(f"{LEVEL_FAIL}: [spec] 'name' contains uppercase characters: '{name}'")

    if not RE_NAME_FORMAT.match(name):
        errors.append(
            f"{LEVEL_FAIL}: [spec] 'name' has invalid format: '{name}' "
            "(must be lowercase alphanumeric + hyphens, no leading/trailing hyphens)"
        )
    else:
        passes.append("name: valid format")

    if "--" in name:
        errors.append(f"{LEVEL_FAIL}: [spec] 'name' contains consecutive hyphens: '{name}'")

    if "_" in name:
        errors.append(f"{LEVEL_FAIL}: [spec] 'name' contains underscores: '{name}'")

    if " " in name:
        errors.append(f"{LEVEL_FAIL}: [spec] 'name' contains spaces: '{name}'")

    if name != dir_name:
        errors.append(
            f"{LEVEL_FAIL}: [spec] 'name' ({name}) does not match directory name ({dir_name})"
        )
    else:
        passes.append("name: matches directory")

    # Platform restriction (Anthropic): reserved words
    for reserved in RESERVED_NAMES:
        if reserved in name:
            errors.append(
                f"{LEVEL_WARN}: [platform: Anthropic] 'name' contains reserved word "
                f"'{reserved}' — not allowed on Anthropic platforms"
            )

    if len(name) < MIN_NAME_CHARS:
        errors.append(
            f"{LEVEL_INFO}: [foundry] 'name' is only {len(name)} character(s) — "
            "consider a more descriptive name (spec minimum is 1)"
        )

    return errors, passes


def validate_allowed_tools(value: object) -> tuple[list[str], list[str]]:
    """Validate the allowed-tools frontmatter field.

    Checks that the value is a space-separated list of tool names,
    each tool is checked against the known tools list, and the total
    count does not exceed the configured maximum.

    Recognition tier (in order):

    1. Token in ``HARNESS_TOOLS_CLAUDE_CODE`` or ``CLI_TOOLS_CLAUDE_CODE``
       — recognised silently.
    2. Token matches the MCP-tool name pattern
       (``mcp__server__tool``) — recognised silently; MCP servers are
       per-installation and unbounded by definition.
    3. Token matches PascalCase harness shape but is not in the
       catalog (after the optional ``(...)`` argument suffix has been
       stripped on entry) — INFO "harness-shaped but not in catalog".
    4. Anything else — INFO "unrecognized tool".

    Returns (errors, passes) tuple.
    """
    errors: list[str] = []
    passes: list[str] = []

    if not isinstance(value, str):
        errors.append(
            f"{LEVEL_WARN}: [spec] 'allowed-tools' should be a space-separated string, "
            f"got {type(value).__name__}"
        )
        return errors, passes

    if not value.strip():
        errors.append(f"{LEVEL_WARN}: [spec] 'allowed-tools' is empty")
        return errors, passes

    # Strip ``(...)`` argument suffixes *before* splitting on whitespace
    # so restricted-tool forms like ``Bash(git add *)`` survive the
    # tokenizer as a single ``Bash`` token instead of three garbage
    # pieces (``Bash(git``, ``add``, ``*)``).  The same helper is used
    # by ``validate_tool_coherence`` via ``parse_allowed_tools_tokens``,
    # which keeps the two recognition paths aligned.
    cleaned = _RE_PAREN_ARGS.sub("", value)
    tools = cleaned.split()
    if not tools:
        # Non-empty input that collapses to zero tokens means the entire
        # value was a parenthesised suffix (e.g. ``(Bash)`` — author
        # likely wrapped a tool name in parens by mistake).  Without
        # this guard the function would silently report "0 tools
        # recognized", which is misleading.
        errors.append(
            f"{LEVEL_WARN}: [spec] 'allowed-tools' contains no tool names "
            "after stripping argument suffixes — verify the value"
        )
        return errors, passes
    if len(tools) > MAX_ALLOWED_TOOLS:
        errors.append(
            f"{LEVEL_WARN}: [foundry] 'allowed-tools' lists {len(tools)} tools "
            f"(max {MAX_ALLOWED_TOOLS}) — consider splitting the skill"
        )
    else:
        passes.append(f"allowed-tools: {len(tools)} tools (max {MAX_ALLOWED_TOOLS})")

    harness_shaped: list[str] = []
    fully_unknown: list[str] = []
    seen: set[str] = set()
    for token in tools:
        if token in seen:
            continue
        seen.add(token)
        if token in KNOWN_TOOLS:
            continue
        if RE_MCP_TOOL_NAME.match(token):
            continue
        if RE_HARNESS_TOOL_SHAPE.match(token):
            harness_shaped.append(token)
        else:
            fully_unknown.append(token)

    if harness_shaped:
        errors.append(
            f"{LEVEL_INFO}: [foundry] 'allowed-tools' contains harness-shaped tokens "
            f"not in the catalog: {', '.join(sorted(harness_shaped))} — verify "
            "spelling or add to allowed_tools.catalogs.claude_code.harness_tools"
        )
    if fully_unknown:
        errors.append(
            f"{LEVEL_INFO}: [foundry] 'allowed-tools' contains unrecognized tools: "
            f"{', '.join(sorted(fully_unknown))} — verify spelling"
        )
    if not harness_shaped and not fully_unknown:
        passes.append("allowed-tools: all tools recognized")

    return errors, passes


def validate_metadata(metadata: object) -> tuple[list[str], list[str]]:
    """Validate the metadata frontmatter sub-fields.

    The spec defines metadata as an arbitrary key-value mapping.
    Checks here are foundry conventions (semver recommendation,
    author limits) not spec requirements.

    Returns (errors, passes) tuple.
    """
    errors: list[str] = []
    passes: list[str] = []

    if not isinstance(metadata, dict):
        errors.append(
            f"{LEVEL_WARN}: [spec] 'metadata' should be a key-value map, "
            f"got {type(metadata).__name__}"
        )
        return errors, passes

    if "version" in metadata:
        version = metadata["version"]
        if not isinstance(version, str):
            errors.append(
                f"{LEVEL_WARN}: [foundry] 'metadata.version' should be a string, "
                f"got {type(version).__name__}"
            )
        elif RE_METADATA_VERSION.match(version):
            passes.append(f"metadata.version: valid semver ({version})")
        else:
            errors.append(
                f"{LEVEL_INFO}: [foundry] 'metadata.version' does not follow "
                f"recommended semver pattern: '{version}' — consider "
                "MAJOR.MINOR.PATCH (spec allows any string)"
            )

    if "spec" in metadata:
        spec = metadata["spec"]
        if not isinstance(spec, str):
            errors.append(
                f"{LEVEL_WARN}: [foundry] 'metadata.spec' should be a string, "
                f"got {type(spec).__name__}"
            )
        else:
            passes.append(f"metadata.spec: valid string ({spec})")

    if "author" in metadata:
        author = metadata["author"]
        if not isinstance(author, str):
            errors.append(
                f"{LEVEL_WARN}: [foundry] 'metadata.author' should be a string, "
                f"got {type(author).__name__}"
            )
        elif not author.strip():
            errors.append(
                f"{LEVEL_WARN}: [foundry] 'metadata.author' is empty"
            )
        elif len(author) > MAX_AUTHOR_LENGTH:
            errors.append(
                f"{LEVEL_WARN}: [foundry] 'metadata.author' exceeds "
                f"{MAX_AUTHOR_LENGTH} characters ({len(author)} chars)"
            )
        else:
            passes.append(f"metadata.author: {len(author)} chars (max {MAX_AUTHOR_LENGTH})")

    return errors, passes


def validate_license(value: object) -> tuple[list[str], list[str]]:
    """Validate the license frontmatter field against known SPDX identifiers.

    Returns (errors, passes) tuple.  Unrecognized licenses produce an
    INFO-level message — the spec allows arbitrary license strings.
    """
    errors: list[str] = []
    passes: list[str] = []

    if not isinstance(value, str):
        errors.append(
            f"{LEVEL_WARN}: [spec] 'license' should be a string, "
            f"got {type(value).__name__}"
        )
        return errors, passes

    if not value.strip():
        errors.append(f"{LEVEL_WARN}: [spec] 'license' is empty")
        return errors, passes

    license_str = value.strip()
    if license_str in KNOWN_SPDX_LICENSES:
        passes.append(f"license: recognized SPDX identifier ({license_str})")
    else:
        errors.append(
            f"{LEVEL_INFO}: [foundry] 'license' value '{license_str}' is not a recognized "
            "SPDX identifier — verify spelling or use a standard SPDX ID"
        )

    return errors, passes


def validate_known_keys(frontmatter: object) -> tuple[list[str], list[str]]:
    """Check frontmatter keys against the known key list.

    Unrecognized keys produce INFO-level warnings to help catch
    misspellings (e.g. 'compatability' instead of 'compatibility').
    For each unknown key, ``difflib.get_close_matches`` is consulted
    (``n`` and ``cutoff`` sourced from ``configuration.yaml`` →
    ``FRONTMATTER_SUGGEST_MAX_MATCHES`` / ``FRONTMATTER_SUGGEST_CUTOFF``)
    and any hits are appended in the form ``key (did you mean: a, b, c?)``.
    Keys with no close match are emitted unchanged.

    Returns (errors, passes) tuple.
    """
    errors: list[str] = []
    passes: list[str] = []

    if not isinstance(frontmatter, dict):
        return errors, passes

    unknown_keys = sorted(
        k for k in frontmatter if k not in KNOWN_FRONTMATTER_KEYS
    )
    if unknown_keys:
        known_sorted = sorted(KNOWN_FRONTMATTER_KEYS)
        rendered: list[str] = []
        for key in unknown_keys:
            matches = difflib.get_close_matches(
                key,
                known_sorted,
                n=FRONTMATTER_SUGGEST_MAX_MATCHES,
                cutoff=FRONTMATTER_SUGGEST_CUTOFF,
            )
            if matches:
                rendered.append(f"{key} (did you mean: {', '.join(matches)}?)")
            else:
                rendered.append(key)
        errors.append(
            f"{LEVEL_INFO}: [foundry] unrecognized frontmatter keys: "
            f"{', '.join(rendered)} — check for typos. "
            f"Known keys: {', '.join(known_sorted)}"
        )
    else:
        passes.append("frontmatter: all keys recognized")

    return errors, passes


def validate_tool_coherence(
    skill_root: str, frontmatter: dict | None,
) -> tuple[list[str], list[str]]:
    """Check that fence-language and `scripts/` signals match `allowed-tools`.

    For every harness tool with a configured fence-language mapping
    (``TOOL_FENCE_LANGUAGES``), verify that ``allowed-tools`` declares
    the tool whenever:

    - any of the in-scope Markdown files (SKILL.md and
      ``capabilities/**/capability.md``) contains a fenced code block
      whose language token is in the tool's mapping → FAIL, or
    - the skill carries a top-level ``scripts/`` directory and the
      tool's YAML entry sets ``scripts_dir_indicator: true`` (gated by
      ``TOOLS_INDICATING_SCRIPTS``; today populated only for
      ``Bash``) → WARN.  Adding a new tool to the script-presence rule
      is a YAML edit only — set the flag on its ``fence_languages``
      entry and the rule fires automatically.

    *frontmatter* is the parent skill's frontmatter dict (or ``None``
    for skills without frontmatter / when called in capability mode
    with the parent's frontmatter passed in by the caller).  When the
    frontmatter declares the harness tool, both checks for that tool
    are skipped.

    Returns ``(errors, passes)`` per the standard validator contract.
    """
    errors: list[str] = []
    passes: list[str] = []

    declared = (
        parse_allowed_tools_tokens(frontmatter.get("allowed-tools"))
        if isinstance(frontmatter, dict)
        else set()
    )

    in_scope_files = _gather_in_scope_files(skill_root)
    has_scripts_dir = os.path.isdir(
        os.path.join(skill_root, DIR_SCRIPTS)
    )

    for tool_name in sorted(TOOL_FENCE_LANGUAGES.keys()):
        languages = TOOL_FENCE_LANGUAGES[tool_name]
        if tool_name in declared:
            passes.append(
                f"tool-coherence: '{tool_name}' declared in allowed-tools"
            )
            continue

        # Fence check (FAIL)
        offending: list[str] = []
        for path in in_scope_files:
            if _file_has_fence_in_languages(path, languages):
                offending.append(os.path.relpath(path, skill_root))
        if offending:
            errors.append(
                f"{LEVEL_FAIL}: [foundry] '{tool_name}' fence(s) found in "
                f"{', '.join(sorted(offending))} but '{tool_name}' is not "
                "declared in 'allowed-tools' — the harness will block the "
                f"tool at runtime.  Add '{tool_name}' (or scoped form like "
                f"'{tool_name}(...)') to 'allowed-tools' frontmatter."
            )

        # Script-presence check (WARN) — fires only for tools whose
        # YAML entry sets ``scripts_dir_indicator: true``.  Keeps the
        # coupling between "tool" and "scripts/ is a presence signal"
        # explicit in configuration, so adding a future tool is one
        # YAML edit and the rule does not depend on a magic
        # fence-language string.
        if has_scripts_dir and tool_name in TOOLS_INDICATING_SCRIPTS:
            errors.append(
                f"{LEVEL_WARN}: [foundry] skill has a 'scripts/' directory "
                f"but '{tool_name}' is not declared in 'allowed-tools' — "
                f"add '{tool_name}' if scripts will run via the harness."
            )

    return errors, passes


def _gather_in_scope_files(skill_root: str) -> list[str]:
    """Return absolute paths of files the coherence rule scans for fences.

    Scope: ``SKILL.md`` at the skill root + every
    ``capabilities/**/capability.md`` (any depth).  This is a
    deliberate subset of ``PROSE_YAML_IN_SCOPE_GLOBS``, which also
    covers ``references/**/*.md`` — reference files routinely embed
    illustrative shell snippets (e.g. install-or-deployment commands)
    that are not skill behaviour, so applying the coherence rule there
    would force every reference doc to declare ``Bash`` even when the
    skill itself never executes one.  Returns sorted, deduplicated
    paths so finding ordering is stable across platforms.
    """
    seen: set[str] = set()
    matches: list[str] = []
    candidates: list[str] = []
    skill_md = os.path.join(skill_root, FILE_SKILL_MD)
    if os.path.isfile(skill_md):
        candidates.append(skill_md)
    capability_glob = os.path.join(
        skill_root, DIR_CAPABILITIES, "**", FILE_CAPABILITY_MD,
    )
    candidates.extend(glob.glob(capability_glob, recursive=True))
    for path in candidates:
        absolute = os.path.abspath(path)
        if absolute in seen:
            continue
        seen.add(absolute)
        matches.append(absolute)
    matches.sort()
    return matches


def _file_has_fence_in_languages(
    file_path: str, languages: frozenset[str],
) -> bool:
    """Return True when *file_path* contains a fence whose language is
    in *languages*.  Frontmatter is stripped before scanning so a
    fence inside a folded description does not count.

    Unreadable files are treated as ``False`` — coherence findings
    must not depend on the rule being a filesystem-existence oracle;
    the caller's other checks already report I/O failures elsewhere.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except (OSError, UnicodeDecodeError):
        return False
    body = strip_frontmatter_for_scan(content)
    return has_fence_with_language(body, languages)
