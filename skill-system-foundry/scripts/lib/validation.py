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
    RE_MCP_TOOL_NAME, RE_HARNESS_TOOL_SHAPE,
    TOOL_FENCE_LANGUAGES, TOOLS_INDICATING_SCRIPTS,
    DESCRIPTION_TRIGGER_PHRASES, DESCRIPTION_TRIGGER_EXAMPLE_PHRASES,
    CAPABILITY_SKILL_ONLY_FIELDS,
    DIR_CAPABILITIES, DIR_SCRIPTS,
    FILE_CAPABILITY_MD, FILE_SKILL_MD,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
)
from .fence_scan import has_fence_with_language
from .frontmatter import load_frontmatter, strip_frontmatter_for_scan


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

    Note on the deliberate asymmetry with :func:`validate_allowed_tools`:
    this helper is a value extractor — it tells callers "what tokens
    are in here?" — and is intentionally more permissive than the
    spec-conformance validator.  ``load_frontmatter`` / the YAML
    subset parser does return a Python list for block-sequence YAML
    (``allowed-tools:\\n  - Bash\\n  - Read``), and this helper accepts
    that list form so direct API callers and ``validate_tool_coherence``
    (which only needs the token set) work today.
    ``validate_allowed_tools`` still emits a WARN for non-empty list
    inputs because the foundry treats them as non-conformant to the
    current spec expectation of a space-delimited string, even though
    they are parsed.  Only flow-sequence ``[]`` syntax remains outside
    the supported YAML subset (it parses as the literal string
    ``"[]"``).  See ``test_non_empty_list_still_warns`` and the
    ``test_yaml_list_form`` family for the pinned contract.
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


def _is_explicit_empty_allowed_tools(value: object) -> bool:
    """Return ``True`` only for declarations that explicitly mean "no tools".

    Matches:

    - ``""`` or any whitespace-only string;
    - the empty list ``[]``.

    Everything else — non-string / non-list scalars (``int``, ``float``,
    ``dict``), non-empty lists, and non-empty strings (including
    paren-only values like ``(Bash)``) — is **not** an explicit
    opt-out.  Those values either fail spec conformance elsewhere or
    declare real (or attempted) tools and must therefore continue
    through the coherence rule against the parsed token set.
    """
    if isinstance(value, list):
        return not value
    if isinstance(value, str):
        return not value.strip()
    return False


def validate_description_triggers(
    description: str,
) -> tuple[list[str], list[str]]:
    """Check that the description contains at least one trigger phrase.

    The agentskills.io specification requires descriptions to state
    both *what* the skill does and *when* it activates.  This rule
    enforces the "when" half by case-insensitive substring matching
    against ``DESCRIPTION_TRIGGER_PHRASES`` (configured under
    ``skill.description.trigger_phrases`` in ``configuration.yaml``).

    Detection is heuristic — phrase matching cannot enumerate every
    valid wording — so the rule emits WARN, not FAIL.  Empty /
    whitespace-only inputs short-circuit silently: the spec-required
    non-empty FAIL is owned by the caller (``validate_description``
    in ``validate_skill.py`` and the per-skill block in
    ``audit_skill_system.py``), and stacking a trigger WARN on top
    of that FAIL would be redundant.  The guard is kept so direct
    API callers (e.g. ad-hoc scripts) can invoke the helper without
    a separate non-empty check of their own.

    Returns ``(errors, passes)`` per the standard validator contract.
    """
    errors: list[str] = []
    passes: list[str] = []

    if not description or not description.strip():
        return errors, passes

    lowered = description.lower()
    for phrase in DESCRIPTION_TRIGGER_PHRASES:
        if phrase in lowered:
            passes.append(
                f"description: contains trigger phrase '{phrase}'"
            )
            return errors, passes

    # Build the example list from the curated example subset so the
    # message never drifts from the YAML.  Examples are first-word
    # distinct (different root verbs) for educational variety; the
    # YAML pointer remains the canonical source for the full list.
    example_phrases = ", ".join(
        f"'{phrase.capitalize()} ...'"
        for phrase in DESCRIPTION_TRIGGER_EXAMPLE_PHRASES
    )
    errors.append(
        f"{LEVEL_WARN}: [spec] 'description' does not state when the skill "
        f"activates — add a trigger clause (e.g. {example_phrases}).  "
        "Phrase list configured under skill.description.trigger_phrases "
        "in configuration.yaml."
    )
    return errors, passes


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

    The spec defines ``allowed-tools`` as a space-separated string of
    tool names.  Empty / whitespace-only values are accepted as a
    deliberate "no harness tools" declaration and pass silently.  An
    empty Python list (``[]`` — passed directly by API callers) is
    also accepted, but note the foundry's stdlib-only YAML subset
    parser does not support inline flow sequences, so
    ``allowed-tools: []`` written in frontmatter parses as the literal
    string ``"[]"`` rather than an empty list — to declare "no tools"
    in YAML, use ``allowed-tools: ""`` (or just leave the value
    blank).  Non-empty lists still produce the spec-conformance WARN;
    full list-form acceptance is a separate follow-up.

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

    # Empty list ``allowed-tools: []`` is treated like an empty string:
    # an explicit "no harness tools" declaration.  Non-empty lists fall
    # through to the existing list-form WARN (deferred follow-up).
    if isinstance(value, list) and not value:
        passes.append("allowed-tools: explicitly declares no tools")
        return errors, passes

    if not isinstance(value, str):
        errors.append(
            f"{LEVEL_WARN}: [spec] 'allowed-tools' should be a space-separated string, "
            f"got {type(value).__name__}"
        )
        return errors, passes

    if not value.strip():
        # Empty / whitespace-only is a deliberate "no harness tools"
        # declaration — the author chose to write the field but list
        # nothing.  The harness still blocks every tool at runtime; the
        # validator does not need to nag.  The sibling rule
        # ``validate_tool_coherence`` also respects an explicitly empty
        # ``allowed-tools`` and skips its fence/script checks, so docs-
        # only skills with example fences do not need a fake ``Bash``
        # declaration.
        passes.append("allowed-tools: explicitly declares no tools")
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
    skill_root: str,
    frontmatter: dict | None,
    *,
    capability_data: dict[str, dict | None] | None = None,
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

    **Per-file effective declared set.**  Fence findings attribute to
    the file containing the fence and consult that file's *effective*
    declared set: a ``capability.md`` that declares its own
    ``allowed-tools`` is checked against its own tokens; a capability
    silent on the field falls back to the parent's declared set;
    ``SKILL.md`` always uses the parent's declared set.  This pairs
    with the bottom-up aggregation rule
    (:func:`aggregate_capability_allowed_tools`) which separately
    enforces parent-as-superset.

    The ``scripts/``-presence check stays at parent scope — there is
    no per-capability ``scripts/`` directory in the foundry layout —
    and consults only the parent's declared set.

    *frontmatter* is the parent skill's frontmatter dict (or ``None``
    for skills without frontmatter / when called in capability mode
    with the parent's frontmatter passed in by the caller).

    **Explicit-empty opt-out.**  When ``allowed-tools`` is *present* in
    frontmatter as an explicitly empty value — ``allowed-tools: ""``
    (or whitespace-only) or ``allowed-tools: []`` — the author has
    deliberately declared zero harness tools and the rule suppresses
    both fence and ``scripts/`` checks for that file.  At parent
    scope this also disables the parent-level ``scripts/`` check.
    A capability declaring an explicit-empty value opts itself out of
    its local fence checks but does not affect peers.  Distinct from
    key-absent: when the field is missing entirely the rule still
    fires (the painful #100 case where the author hasn't thought
    about tools at all).

    Malformed values (non-string, non-list scalars; mappings; or lists
    with no string elements) do **not** count as a deliberate opt-out
    — they parse to zero tokens but were not written as an explicit
    "no tools" declaration and they will not grant any tool at runtime
    either, so the coherence rule still runs against an empty declared
    set.  Paren-only string values (e.g. ``(Bash)``) likewise fall
    through; ``validate_allowed_tools`` already emits a separate WARN
    for those.

    Returns ``(errors, passes)`` per the standard validator contract.
    """
    errors: list[str] = []
    passes: list[str] = []

    parent_has_field = (
        isinstance(frontmatter, dict) and "allowed-tools" in frontmatter
    )
    parent_raw = frontmatter["allowed-tools"] if parent_has_field else None
    parent_declared = (
        parse_allowed_tools_tokens(parent_raw) if parent_has_field else set()
    )
    parent_explicit_empty = parent_has_field and _is_explicit_empty_allowed_tools(
        parent_raw
    )

    skill_md = os.path.join(skill_root, FILE_SKILL_MD)
    in_scope_files = _gather_in_scope_files(skill_root)
    has_scripts_dir = os.path.isdir(
        os.path.join(skill_root, DIR_SCRIPTS)
    )
    if capability_data is None:
        capability_data = load_capability_data(skill_root)

    # Build per-file (declared_set, explicit_empty) once.  Capabilities
    # may declare their own ``allowed-tools``; if silent they inherit
    # the parent's effective set.
    file_effective: dict[str, tuple[set[str], bool]] = {}
    for path in in_scope_files:
        if os.path.abspath(path) == os.path.abspath(skill_md):
            file_effective[path] = (parent_declared, parent_explicit_empty)
            continue
        cap_fm = capability_data.get(os.path.abspath(path))
        cap_declared, cap_has_field, cap_empty = _effective_tokens_from_fm(
            cap_fm
        )
        if cap_has_field:
            file_effective[path] = (cap_declared, cap_empty)
        else:
            file_effective[path] = (parent_declared, parent_explicit_empty)

    if parent_explicit_empty:
        passes.append(
            "tool-coherence: explicit empty 'allowed-tools' at SKILL.md "
            "— parent-level fence and scripts/ checks suppressed"
        )

    for tool_name in sorted(TOOL_FENCE_LANGUAGES.keys()):
        languages = TOOL_FENCE_LANGUAGES[tool_name]

        # Fence check (FAIL) — per-file with the file's effective set.
        offending: list[str] = []
        for path in in_scope_files:
            declared, explicit_empty = file_effective[path]
            if explicit_empty:
                continue
            if tool_name in declared:
                continue
            if _file_has_fence_in_languages(path, languages):
                offending.append(os.path.relpath(path, skill_root))
        if offending:
            errors.append(
                f"{LEVEL_FAIL}: [foundry] '{tool_name}' fence(s) found in "
                f"{', '.join(sorted(offending))} but '{tool_name}' is not "
                "declared in 'allowed-tools' — the harness may block the "
                f"tool at runtime under default permissions.  Add '{tool_name}' "
                f"(or scoped form like '{tool_name}(...)') to 'allowed-tools' "
                "frontmatter."
            )
        elif tool_name in parent_declared:
            passes.append(
                f"tool-coherence: '{tool_name}' declared in allowed-tools"
            )

        # Script-presence check (WARN) — parent-scope only.  The
        # ``scripts/`` directory has no capability-level analogue in
        # the foundry layout, so the rule consults only the parent's
        # declared set.  Suppressed when the parent declares an
        # explicit-empty ``allowed-tools``.
        if (
            has_scripts_dir
            and tool_name in TOOLS_INDICATING_SCRIPTS
            and not parent_explicit_empty
            and tool_name not in parent_declared
        ):
            errors.append(
                f"{LEVEL_WARN}: [foundry] skill has a 'scripts/' directory "
                f"but '{tool_name}' is not declared in 'allowed-tools' — "
                f"add '{tool_name}' if scripts will run via the harness."
            )

    return errors, passes


def load_capability_data(skill_root: str) -> dict[str, dict | None]:
    """Load every ``capabilities/**/capability.md`` frontmatter once.

    Returns a mapping from absolute path to frontmatter dict (or
    ``None`` when the file is unreadable or has no frontmatter).
    Parse errors are kept as a dict carrying ``_parse_error`` so
    callers can decide whether to skip or surface them — matches the
    contract of :func:`load_frontmatter`.

    Single discovery pass: ``aggregate_capability_allowed_tools``,
    ``validate_tool_coherence``, and the skill-only-fields walk in
    ``validate_skill.py`` all consume from one dict instead of
    re-reading the same file three times.  Callers that hold a
    ``capability_data`` dict pass it through to keep I/O O(1) per
    file even as new rules land on the same data.
    """
    result: dict[str, dict | None] = {}
    capability_glob = os.path.join(
        skill_root, DIR_CAPABILITIES, "**", FILE_CAPABILITY_MD,
    )
    for path in sorted(glob.glob(capability_glob, recursive=True)):
        abs_path = os.path.abspath(path)
        try:
            fm, _, _ = load_frontmatter(path)
        except (OSError, UnicodeDecodeError):
            result[abs_path] = None
            continue
        result[abs_path] = fm
    return result


def _effective_tokens_from_fm(
    fm: dict | None,
) -> tuple[set[str], bool, bool]:
    """Pure derivation of ``(declared_tokens, has_field, is_explicit_empty)``
    from a pre-loaded frontmatter dict.

    Treats ``None``, non-dict, parse-error, and ``allowed-tools``-absent
    inputs uniformly as "silent" (returns ``(set(), False, False)``) —
    callers fall back to the parent's declared set in that case.
    """
    if not isinstance(fm, dict) or "allowed-tools" not in fm:
        return set(), False, False
    if "_parse_error" in fm:
        return set(), False, False
    raw = fm["allowed-tools"]
    return (
        parse_allowed_tools_tokens(raw),
        True,
        _is_explicit_empty_allowed_tools(raw),
    )


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


def aggregate_capability_allowed_tools(
    skill_root: str,
    parent_frontmatter: dict | None,
    *,
    capability_data: dict[str, dict | None] | None = None,
) -> tuple[list[str], list[str]]:
    """Validate parent ``allowed-tools`` as a superset of the union of
    capability-declared ``allowed-tools``.

    Bottom-up aggregation: each ``capabilities/<name>/capability.md``
    may declare its own scoped ``allowed-tools``; the parent SKILL.md
    must declare every bare token the capability set contributes.
    Findings:

    - **FAIL** per (capability, tool): a capability declares a tool
      the parent does not.  The same FAIL fires whether the parent
      omits the field entirely, has an explicit-empty value, or
      simply has a partial set — the per-capability attribution
      tells the author exactly which capability needs the tool.
    - **INFO** per tool: parent declares a tool no capability declares
      in its own frontmatter and no file inheriting the parent set
      (SKILL.md, or a capability silent on ``allowed-tools``) signals
      a need via fence-language or ``scripts/`` directory presence.
      Suggests the tool may be unused — verify or remove.

    Set semantics: ``parse_allowed_tools_tokens`` strips
    ``(...)`` arguments, so ``Bash(git:*)`` declared in a capability
    plus ``Bash`` declared in the parent compare cleanly.  The rule
    is bare-token only and does not reason about argument patterns.

    Returns ``(errors, passes)`` per the standard validator contract.
    Skills with no capabilities declaring ``allowed-tools`` produce
    only an informational pass entry.
    """
    errors: list[str] = []
    passes: list[str] = []

    parent_has_field = (
        isinstance(parent_frontmatter, dict)
        and "allowed-tools" in parent_frontmatter
    )
    parent_declared = (
        parse_allowed_tools_tokens(parent_frontmatter["allowed-tools"])
        if parent_has_field
        else set()
    )

    # Single discovery pass: ``load_capability_data`` matches the
    # recursive glob in ``_gather_in_scope_files`` so the aggregation
    # rule and the coherence rule cannot drift on which files
    # contribute to the union.  Nested capabilities are themselves a
    # separate FAIL in the audit's nesting-depth rule but their
    # ``allowed-tools`` declarations still feed the aggregation set
    # — drift between the two rules would silently mis-attribute
    # tools.
    if capability_data is None:
        capability_data = load_capability_data(skill_root)

    declared_by: dict[str, list[str]] = {}
    capabilities_with_field = 0
    silent_capability_paths: list[str] = []
    for abs_path, fm in sorted(capability_data.items()):
        tokens, has_field, _is_empty = _effective_tokens_from_fm(fm)
        if not has_field:
            silent_capability_paths.append(abs_path)
            continue
        capabilities_with_field += 1
        rel = os.path.relpath(abs_path, skill_root).replace(os.sep, "/")
        for token in tokens:
            declared_by.setdefault(token, []).append(rel)

    if capabilities_with_field == 0:
        passes.append(
            "aggregation: no capabilities declare 'allowed-tools' — "
            "parent governs tool scope"
        )
        return errors, passes

    # FAIL — per (capability, tool) for tokens missing from the parent.
    for token in sorted(declared_by.keys()):
        if token in parent_declared:
            continue
        for rel in sorted(declared_by[token]):
            errors.append(
                f"{LEVEL_FAIL}: [foundry] '{token}' declared in {rel} "
                f"is missing from SKILL.md 'allowed-tools' — the parent "
                "must declare every tool any capability declares "
                "(bottom-up aggregation)."
            )

    union = set(declared_by.keys())
    covered = parent_declared & union
    for token in sorted(covered):
        passes.append(
            f"aggregation: '{token}' covered by SKILL.md "
            f"({len(declared_by[token])} capability declaration(s))"
        )

    # INFO — parent declares tools no capability declares.  The rule
    # only fires for tokens the validator can *observe*: tokens with a
    # fence-language entry (``Bash`` today) or a
    # ``scripts_dir_indicator`` flag.  Tokens with no observation
    # mechanism (``Read`` / ``Write`` / ``Edit`` / ``Glob`` / ``Grep``
    # / ``WebFetch``) are silently suppressed because we have no
    # principled basis to flag them — the SKILL.md body might
    # genuinely need the tool and there is no fence to confirm.
    # Adding a new fence-language entry to YAML automatically extends
    # this rule; no parallel allow-list to keep in sync.
    #
    # Among observable tokens, suppress the INFO when *any* file
    # inheriting the parent's declared set actually signals a need:
    # a fence in SKILL.md, a fence in a capability that is silent on
    # ``allowed-tools`` (and therefore inherits the parent set), or a
    # top-level ``scripts/`` directory for tools flagged as
    # script-presence indicators.  Without the silent-capability scan
    # the INFO would suggest removing a parent-declared tool that a
    # fallback capability actively relies on, breaking coherence on
    # the next run.
    skill_md = os.path.join(skill_root, FILE_SKILL_MD)
    has_scripts_dir = os.path.isdir(os.path.join(skill_root, DIR_SCRIPTS))
    for token in sorted(parent_declared - union):
        languages = TOOL_FENCE_LANGUAGES.get(token)
        is_script_indicator = token in TOOLS_INDICATING_SCRIPTS
        if not languages and not is_script_indicator:
            # No observation mechanism — never speculate.
            continue
        signaled_by_parent = False
        if languages and os.path.isfile(skill_md):
            signaled_by_parent = _file_has_fence_in_languages(skill_md, languages)
        if not signaled_by_parent and languages:
            for cap_path in silent_capability_paths:
                if _file_has_fence_in_languages(cap_path, languages):
                    signaled_by_parent = True
                    break
        if (
            not signaled_by_parent
            and has_scripts_dir
            and is_script_indicator
        ):
            signaled_by_parent = True
        if signaled_by_parent:
            continue
        errors.append(
            f"{LEVEL_INFO}: [foundry] '{token}' in SKILL.md 'allowed-tools' "
            "is not declared by any capability — verify it is needed by "
            "the SKILL.md body itself, or remove to keep the parent's "
            "tool surface minimal."
        )

    return errors, passes


def validate_capability_skill_only_fields(
    capability_frontmatter: dict | None, capability_rel_path: str,
) -> tuple[list[str], list[str]]:
    """Emit an INFO when a capability declares skill-only frontmatter fields.

    Bottom-up aggregation makes only ``allowed-tools`` per-capability;
    every other frontmatter field's authoritative home is the parent
    SKILL.md.  When a capability declares one of the fields listed in
    ``CAPABILITY_SKILL_ONLY_FIELDS`` (today: ``license``,
    ``compatibility``, ``metadata.author``, ``metadata.version``,
    ``metadata.spec``), the validator emits a per-field INFO
    suggesting removal — the value is informational only at the
    capability level and the parent governs the field, so leaving
    the duplicate is a drift risk.

    *capability_rel_path* is used for attribution in the message and
    should be a forward-slash POSIX-style relative path
    (e.g. ``capabilities/foo/capability.md``).

    Returns ``(errors, passes)`` per the standard validator contract.
    """
    errors: list[str] = []
    passes: list[str] = []

    if not isinstance(capability_frontmatter, dict):
        return errors, passes

    declared_skill_only: list[str] = []
    for field in CAPABILITY_SKILL_ONLY_FIELDS:
        if _frontmatter_has_dotted_field(capability_frontmatter, field):
            declared_skill_only.append(field)

    if not declared_skill_only:
        passes.append(
            f"capability frontmatter: {capability_rel_path} declares "
            "no skill-only fields"
        )
        return errors, passes

    for field in declared_skill_only:
        errors.append(
            f"{LEVEL_INFO}: [foundry] '{field}' in {capability_rel_path} "
            "frontmatter is informational only — the parent SKILL.md "
            "governs this field.  Consider removing to reduce drift risk."
        )

    return errors, passes


def _frontmatter_has_dotted_field(frontmatter: dict, dotted: str) -> bool:
    """Return True when *dotted* (e.g. ``metadata.author``) resolves to
    a present key in *frontmatter*.

    Walks dotted segments through nested mappings.  Missing
    intermediate keys, non-dict intermediate values, or a missing
    leaf key all return False.  Treating "value is None" the same as
    "key absent" would silently swallow ``metadata: null`` — but the
    spec / foundry already classify ``null`` as malformed elsewhere,
    so this helper only checks key presence.
    """
    cursor: object = frontmatter
    parts = dotted.split(".")
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            return False
        cursor = cursor[part]
    leaf = parts[-1]
    return isinstance(cursor, dict) and leaf in cursor
