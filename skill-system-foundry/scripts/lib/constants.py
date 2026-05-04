"""Centralized constants for skill-system-foundry scripts.

Structural constants (directory names, file names, error levels,
templates) are defined directly in Python.  Validation rules
(limits, patterns, reserved words) are loaded from configuration.yaml.

Consumers import everything from this module:
    from lib.constants import DIR_SKILLS, MAX_BODY_LINES, RE_NAME_FORMAT
"""

import os
import re

# Error-level string constants.
LEVEL_FAIL = "FAIL"
LEVEL_WARN = "WARN"
LEVEL_INFO = "INFO"

from .yaml_parser import parse_yaml_subset

# ===================================================================
# Script Internals (structural — rarely changes)
# ===================================================================

# Directory Names
DIR_SKILLS = "skills"
DIR_CAPABILITIES = "capabilities"
DIR_ROLES = "roles"
DIR_SHARED = "shared"
DIR_REFERENCES = "references"
DIR_SCRIPTS = "scripts"
DIR_ASSETS = "assets"

# File Names and Extensions
FILE_SKILL_MD = "SKILL.md"
FILE_CAPABILITY_MD = "capability.md"
FILE_README = "README.md"
FILE_MANIFEST = "manifest.yaml"
FILE_CODEX_CONFIG = "agents/openai.yaml"
FILE_GITKEEP = ".gitkeep"
EXT_MARKDOWN = ".md"

# Error Level Prefixes — defined at the top of this file (before the
# yaml_parser import) so both this module and yaml_parser can use them.

# JSON Output
JSON_SCHEMA_VERSION = 1

# Error Symbols (for formatted output)
ERROR_SYMBOLS = {
    LEVEL_FAIL: "\u2717",
    LEVEL_WARN: "\u26a0",
    LEVEL_INFO: "\u2139",
}

# Visual Formatting
SEPARATOR_WIDTH = 60

# Template File Names (in assets/)
TEMPLATE_SKILL_ROUTER = "skill-router.md"
TEMPLATE_SKILL_STANDALONE = "skill-standalone.md"
TEMPLATE_CAPABILITY = "capability.md"
TEMPLATE_ROLE = "role.md"

# Template Placeholders
PH_DOMAIN_NAME = "<domain-name>"
PH_DOMAIN_TITLE = "<Domain Name>"
PH_SKILL_NAME = "<skill-name>"
PH_SKILL_TITLE = "<Skill Name>"
PH_CAPABILITY_NAME = "<capability-name>"
PH_CAPABILITY_TITLE = "<Capability Name>"
PH_ROLE_TITLE = "<Role Name>"

# Router Table — structural tokens for the SKILL.md router-table parser
# (see lib/router_table.py).  Header values are matched after stripping
# the characters in ROUTER_HEADER_STRIP_CHARS, so authors may decorate
# the header (e.g., '**Capability**', '_Capability_') without breaking
# discovery.  Both CommonMark italic forms (``*x*`` and ``_x_``) are
# accepted.
ROUTER_HEADERS: tuple[str, str, str] = ("Capability", "Trigger", "Path")
ROUTER_HEADER_STRIP_CHARS = " *_`"

# ===================================================================
# Validation Rules (loaded from configuration.yaml)
# ===================================================================

CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "configuration.yaml")
)

# Config is parsed twice by design: once at module load without findings
# (to populate the constants PLAIN_SCALAR_INDICATORS depends on), and
# lazily on first get_config_findings() call with findings enabled.
# Doing both in a single load would trigger a circular import because
# _check_plain_scalar imports PLAIN_SCALAR_INDICATORS from this module.
with open(CONFIG_PATH, "r", encoding="utf-8") as _f:
    _config = parse_yaml_subset(_f.read())

_CONFIG_FINDINGS: list[str] | None = None


def get_config_findings() -> list[str]:
    """Return plain-scalar divergence findings from ``configuration.yaml``.

    Lazily re-parses the config with a findings list on first call
    and caches the result.  Findings carry the ``FAIL:`` / ``WARN:``
    prefix produced by the YAML subset parser.  Returns a copy so
    callers cannot mutate the cached list.
    """
    global _CONFIG_FINDINGS
    if _CONFIG_FINDINGS is None:
        collected: list[str] = []
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            parse_yaml_subset(fh.read(), collected)
        _CONFIG_FINDINGS = collected
    return list(_CONFIG_FINDINGS)


def collect_foundry_config_findings(target_path: str) -> list[str]:
    """Return configuration.yaml divergence findings when *target_path* is the foundry.

    Shared gate + retag helper used by ``validate_skill`` and
    ``audit_skill_system``.  Detects the foundry by comparing a
    canonicalized ``<target_path>/scripts/lib/configuration.yaml``
    path against the canonicalized path that ``constants.py`` loaded
    at import — matching the ``normcase(realpath(...))`` pattern used
    elsewhere in ``scripts/lib/`` so symlinks and case-insensitive
    filesystems (macOS, Windows) do not silently skip the check.
    When the paths match, each finding produced by
    :func:`get_config_findings` has its original ``[spec]`` tag
    stripped and is re-tagged with ``[foundry]
    scripts/lib/configuration.yaml``.  Third-party skills never
    trigger this check because their configuration file (if any)
    lives at a different canonical path.
    """
    candidate = os.path.normcase(
        os.path.realpath(
            os.path.join(target_path, "scripts", "lib", "configuration.yaml")
        )
    )
    config_path = os.path.normcase(os.path.realpath(CONFIG_PATH))
    if candidate != config_path:
        return []
    retagged: list[str] = []
    for f in get_config_findings():
        level, _, detail = f.partition(": ")
        detail = detail.removeprefix("[spec] ").removeprefix("[spec]").lstrip()
        retagged.append(
            f"{level}: [foundry] scripts/lib/configuration.yaml {detail}"
        )
    return retagged

# --- Skill Validation ---
_skill = _config["skill"]

# Skill name constraints
_skill_name = _skill["name"]
MAX_NAME_CHARS = int(_skill_name["max_length"])
MIN_NAME_CHARS = int(_skill_name["min_length"])
RE_NAME_FORMAT = re.compile(_skill_name["format_pattern"])
RESERVED_NAMES = _skill_name["reserved_words"]

# Skill description constraints
_skill_desc = _skill["description"]
MAX_DESCRIPTION_CHARS = int(_skill_desc["max_length"])
RE_XML_TAG = re.compile(_skill_desc["xml_tag_pattern"])
_voice = _skill_desc["voice_patterns"]
RE_FIRST_PERSON = re.compile(_voice["first_person"])
RE_FIRST_PERSON_PLURAL = re.compile(_voice["first_person_plural"])
RE_SECOND_PERSON = re.compile(_voice["second_person"])
RE_IMPERATIVE_START = re.compile(_voice["imperative_start"])

# Trigger-phrase heuristic: the agentskills.io spec requires
# descriptions to state both *what* the skill does and *when* it
# activates.  validate_description_triggers enforces the "when"
# half by checking that the folded, lowercased description contains
# at least one phrase from this list.  Stored as a sorted tuple of
# lowercased strings — order is deterministic across processes so
# --verbose output naming the matched phrase is reproducible, and
# the structure signals "configured policy, do not mutate" the same
# way RESERVED_NAMES does.  Empty / whitespace-only entries are
# rejected at load time: a substring match against an empty string
# always succeeds, which would silently neuter the rule.
if "trigger_phrases" not in _skill_desc:
    raise RuntimeError(
        "configuration.yaml is missing required section "
        "'skill.description.trigger_phrases'; update your checkout "
        "or restore the full configuration file."
    )
_raw_trigger_phrases = _skill_desc["trigger_phrases"]
if not isinstance(_raw_trigger_phrases, list) or not _raw_trigger_phrases:
    raise RuntimeError(
        "configuration.yaml has invalid value for "
        "'skill.description.trigger_phrases': expected a non-empty "
        f"list, got {_raw_trigger_phrases!r}."
    )
_normalized_trigger_phrases: list[str] = []
_seen_trigger_phrases: set[str] = set()
for _phrase in _raw_trigger_phrases:
    _candidate = str(_phrase).strip().lower()
    if not _candidate:
        raise RuntimeError(
            "configuration.yaml has an empty / whitespace-only entry "
            "in 'skill.description.trigger_phrases'; remove the entry "
            "or replace it with a real phrase — empty entries silently "
            "disable the rule."
        )
    if _candidate in _seen_trigger_phrases:
        raise RuntimeError(
            f"configuration.yaml has a duplicate entry '{_phrase}' "
            f"(normalized: '{_candidate}') in "
            "'skill.description.trigger_phrases'; remove the redundant "
            "entry — duplicates indicate a config edit accident."
        )
    _seen_trigger_phrases.add(_candidate)
    _normalized_trigger_phrases.append(_candidate)
DESCRIPTION_TRIGGER_PHRASES = tuple(sorted(_normalized_trigger_phrases))

# Curated subset used as illustrative examples in the WARN message.
# Selected by first-word-distinct dedup over the sorted phrase tuple
# so the user-facing examples cover different root verbs (e.g.
# "activates on", "invoked on", "triggers on") rather than two
# variants of the same root ("activates on", "activates when").  Up
# to three entries — the helper that renders the WARN does not need
# more, and capping here keeps the message concise.  Deterministic
# across processes because the input is already a sorted tuple.
_example_seen_first_words: set[str] = set()
_example_phrases_buffer: list[str] = []
for _phrase in DESCRIPTION_TRIGGER_PHRASES:
    _first_word = _phrase.split(" ", 1)[0]
    if _first_word in _example_seen_first_words:
        continue
    _example_seen_first_words.add(_first_word)
    _example_phrases_buffer.append(_phrase)
    if len(_example_phrases_buffer) >= 3:
        break
DESCRIPTION_TRIGGER_EXAMPLE_PHRASES = tuple(_example_phrases_buffer)

# Skill body constraints
_skill_body = _skill["body"]
MAX_BODY_LINES = int(_skill_body["max_lines"])
_body_refs = _skill_body["reference_patterns"]
RE_MARKDOWN_LINK_REF = re.compile(_body_refs["markdown_link"])
RE_BACKTICK_REF = re.compile(_body_refs["backtick"])

# Skill compatibility constraints
MAX_COMPATIBILITY_CHARS = int(_skill["compatibility"]["max_length"])

# Known frontmatter keys (for unrecognized-key detection)
KNOWN_FRONTMATTER_KEYS = frozenset(_skill["known_frontmatter_keys"])

# "Did you mean?" suggestion parameters (difflib.get_close_matches).
# Fail-fast so a stale checkout missing this section produces a clear
# error at import rather than a later bare KeyError.
if "frontmatter_suggestions" not in _skill:
    raise RuntimeError(
        "configuration.yaml is missing required section "
        "'skill.frontmatter_suggestions'; update your checkout or "
        "restore the full configuration file."
    )
_fm_suggest = _skill["frontmatter_suggestions"]
FRONTMATTER_SUGGEST_MAX_MATCHES = int(_fm_suggest["max_matches"])
if FRONTMATTER_SUGGEST_MAX_MATCHES <= 0:
    raise RuntimeError(
        "configuration.yaml has invalid value for "
        "'skill.frontmatter_suggestions.max_matches': "
        f"{FRONTMATTER_SUGGEST_MAX_MATCHES!r}. Expected a positive integer."
    )
FRONTMATTER_SUGGEST_CUTOFF = float(_fm_suggest["cutoff"])
if not 0.0 <= FRONTMATTER_SUGGEST_CUTOFF <= 1.0:
    raise RuntimeError(
        "configuration.yaml has invalid value for "
        "'skill.frontmatter_suggestions.cutoff': "
        f"{FRONTMATTER_SUGGEST_CUTOFF!r}. Expected a number in [0.0, 1.0]."
    )

# Allowed-tools validation
_allowed_tools = _skill["allowed_tools"]
MAX_ALLOWED_TOOLS = int(_allowed_tools["max_tools"])

# Per-harness tool catalogs.  Today only ``claude_code`` consumes the
# ``allowed-tools`` field; new harnesses go alongside as additional
# buckets.  Fail-fast so a stale checkout missing the catalog produces
# a clear error at import rather than a silent ``KeyError`` later.
if "catalogs" not in _allowed_tools:
    raise RuntimeError(
        "configuration.yaml is missing required section "
        "'skill.allowed_tools.catalogs'; update your checkout or "
        "restore the full configuration file."
    )
_catalogs = _allowed_tools["catalogs"]
if "claude_code" not in _catalogs:
    raise RuntimeError(
        "configuration.yaml is missing required catalog "
        "'skill.allowed_tools.catalogs.claude_code'."
    )
_claude_code_catalog = _catalogs["claude_code"]
HARNESS_TOOLS_CLAUDE_CODE = frozenset(_claude_code_catalog["harness_tools"])
CLI_TOOLS_CLAUDE_CODE = frozenset(_claude_code_catalog["cli_tools"])

# ``KNOWN_TOOLS`` is the union of harness primitives + generic CLI
# names — preserves the existing recognition behaviour of
# ``validate_allowed_tools`` for tokens already in either bucket.
KNOWN_TOOLS = HARNESS_TOOLS_CLAUDE_CODE | CLI_TOOLS_CLAUDE_CODE

# Token-shape regexes used by the pattern-fallback recognition tier.
# Patterns are loaded from ``configuration.yaml`` (single source of
# truth for validation rules) and compiled here.
# - MCP tools follow the ``mcp__server__tool`` convention; case-mixed
#   tokens are valid (e.g. ``mcp__claude_ai_Atlassian__addCommentToJiraIssue``).
# - Harness-shape regex matches bare PascalCase tokens.  Callers
#   strip the optional ``(...)`` argument suffix (e.g. ``Bash(git
#   add *)``) via ``_RE_PAREN_ARGS`` in ``validation`` *before*
#   applying this regex, so the regex itself does not need to model
#   parens.
if "mcp_tool_pattern" not in _allowed_tools:
    raise RuntimeError(
        "configuration.yaml is missing required pattern "
        "'skill.allowed_tools.mcp_tool_pattern'; this foundry build "
        "is incomplete."
    )
if "harness_tool_shape_pattern" not in _allowed_tools:
    raise RuntimeError(
        "configuration.yaml is missing required pattern "
        "'skill.allowed_tools.harness_tool_shape_pattern'; this "
        "foundry build is incomplete."
    )
RE_MCP_TOOL_NAME = re.compile(_allowed_tools["mcp_tool_pattern"])
RE_HARNESS_TOOL_SHAPE = re.compile(_allowed_tools["harness_tool_shape_pattern"])

# Tool fence-language signals (allowed-tools coherence rule).  Maps
# a harness-tool name to the set of Markdown fence-language tokens
# that count as "this tool is used in the body."  Sibling
# ``TOOLS_INDICATING_SCRIPTS`` is the set of tools whose YAML entry
# carries ``scripts_dir_indicator: true`` — those tools are also
# expected to be declared whenever the skill carries a top-level
# ``scripts/`` directory (WARN, not FAIL — non-shell ``scripts/``
# trees are legitimate).  Adding a tool is a YAML edit only.
if "fence_languages" not in _allowed_tools:
    raise RuntimeError(
        "configuration.yaml is missing required section "
        "'skill.allowed_tools.fence_languages'; this foundry build "
        "is incomplete."
    )
_fence_languages = _allowed_tools["fence_languages"]
TOOL_FENCE_LANGUAGES: dict[str, frozenset[str]] = {
    tool_name: frozenset(entry["languages"])
    for tool_name, entry in _fence_languages.items()
}
# The stdlib-only YAML subset parser returns every scalar as a
# string (see ``yaml_parser.parse_yaml_subset``), so the boolean
# ``scripts_dir_indicator`` arrives as the literal ``"true"``.
# Compare against the string explicitly rather than ``is True``.
TOOLS_INDICATING_SCRIPTS: frozenset[str] = frozenset(
    tool_name
    for tool_name, entry in _fence_languages.items()
    if entry.get("scripts_dir_indicator") == "true"
)

# Metadata sub-field validation (foundry conventions — spec allows arbitrary values)
_metadata = _skill["metadata"]
RE_METADATA_VERSION = re.compile(_metadata["version"]["pattern"])
MAX_AUTHOR_LENGTH = int(_metadata["author"]["max_length"])

# License validation
KNOWN_SPDX_LICENSES = frozenset(_skill["license"]["known_spdx"])

# Recognized skill subdirectories
RECOGNIZED_DIRS = frozenset(_skill["recognized_subdirectories"])

# Capability frontmatter governance — bottom-up aggregation model.
# ``CAPABILITY_SKILL_ONLY_FIELDS`` enumerates frontmatter keys whose
# authoritative home is the parent SKILL.md; capabilities declaring
# them get an INFO redirect.  Dotted entries (``metadata.author``)
# traverse nested mappings.  The list is YAML-driven so adding a new
# field is a configuration edit only.
if "capability_frontmatter" not in _skill:
    raise RuntimeError(
        "configuration.yaml is missing required section "
        "'skill.capability_frontmatter'; this foundry build is "
        "incomplete."
    )
_capability_frontmatter = _skill["capability_frontmatter"]
# Reject scalar / list shapes before indexing — a typo like
# ``capability_frontmatter: []`` would otherwise pass the ``in``
# check (lists support ``in`` for elements) and crash with a bare
# ``TypeError`` on the next subscript, breaking the fail-fast
# RuntimeError contract used elsewhere in this loader.
if not isinstance(_capability_frontmatter, dict):
    raise RuntimeError(
        "configuration.yaml has invalid value for "
        "'skill.capability_frontmatter': expected a mapping, got "
        f"{type(_capability_frontmatter).__name__}."
    )
if "skill_only_fields" not in _capability_frontmatter:
    raise RuntimeError(
        "configuration.yaml is missing required list "
        "'skill.capability_frontmatter.skill_only_fields'; this "
        "foundry build is incomplete."
    )
# Fail-fast normalization mirrors the trigger_phrases handling above.
# A malformed list (empty, non-list, empty entries, duplicates) would
# otherwise silently neuter the skill-only-fields rule and let
# capability frontmatter drift land without a finding.
_raw_skill_only_fields = _capability_frontmatter["skill_only_fields"]
if not isinstance(_raw_skill_only_fields, list) or not _raw_skill_only_fields:
    raise RuntimeError(
        "configuration.yaml has invalid value for "
        "'skill.capability_frontmatter.skill_only_fields': expected "
        f"a non-empty list, got {_raw_skill_only_fields!r}."
    )
_normalized_skill_only_fields: list[str] = []
_seen_skill_only_fields: set[str] = set()
for _field in _raw_skill_only_fields:
    _candidate = str(_field).strip()
    if not _candidate:
        raise RuntimeError(
            "configuration.yaml has an empty / whitespace-only entry "
            "in 'skill.capability_frontmatter.skill_only_fields'; "
            "remove the entry or replace it with a real field name — "
            "empty entries silently disable the redirect."
        )
    if _candidate in _seen_skill_only_fields:
        raise RuntimeError(
            f"configuration.yaml has a duplicate entry '{_field}' "
            "in 'skill.capability_frontmatter.skill_only_fields'; "
            "remove the redundant entry — duplicates indicate a "
            "config edit accident."
        )
    _seen_skill_only_fields.add(_candidate)
    _normalized_skill_only_fields.append(_candidate)
CAPABILITY_SKILL_ONLY_FIELDS: tuple[str, ...] = tuple(
    sorted(_normalized_skill_only_fields)
)

# --- Plain Scalar Divergence Detection ---
_plain_scalar = _config["plain_scalar"]
PLAIN_SCALAR_INDICATORS = _plain_scalar["indicators"]
# Combine separate quote entries into one string (both characters
# cannot coexist in a single YAML scalar without escape processing).
PLAIN_SCALAR_INDICATORS["quote"] = (
    PLAIN_SCALAR_INDICATORS.pop("quote_single")
    + PLAIN_SCALAR_INDICATORS.pop("quote_double")
)
# Decode context whitespace from YAML list (tab is stored as the
# token "TAB" because the subset parser does not process escapes).
_WS_DECODE = {"TAB": "\t"}
PLAIN_SCALAR_CONTEXT_WHITESPACE = "".join(
    _WS_DECODE.get(ch, ch) for ch in _plain_scalar["context_whitespace"]
)

# --- Dependency Direction ---
_dep = _config["dependency_direction"]
RE_ROLES_REF = re.compile(_dep["roles_ref_pattern"])
RE_SIBLING_CAP_REF = re.compile(_dep["sibling_capability_ref_pattern"])

# --- Role Composition ---
_role = _config["role_composition"]
MIN_ROLE_SKILLS = int(_role["min_skills"])
RE_SKILL_REF = re.compile(_role["skill_ref_pattern"])
RE_CAPABILITY_REF = re.compile(_role["capability_ref_pattern"])

# --- Orphan Reference Audit ---
# Fail-fast when the section is missing so a stale checkout produces a
# clear error at import rather than a silent KeyError later.
if "orphan_references" not in _config:
    raise RuntimeError(
        "configuration.yaml is missing required section "
        "'orphan_references'; this foundry build is incomplete."
    )
_orphan_refs = _config["orphan_references"]
if "allowed_orphans" not in _orphan_refs:
    raise RuntimeError(
        "configuration.yaml is missing required key "
        "'orphan_references.allowed_orphans'; leave the value blank "
        "(or list block-style entries beneath it) to keep the rule "
        "fully active."
    )
_raw_allowed_orphans = _orphan_refs["allowed_orphans"]
# A key with no value (``allowed_orphans:`` followed by no items) is
# returned as ``""`` by the YAML subset parser; ``None`` is also
# accepted for forward-compat.  Coerce both to a real empty list so
# downstream consumers don't need to special-case the absent form.
if _raw_allowed_orphans is None or _raw_allowed_orphans == "":
    _raw_allowed_orphans = []
if not isinstance(_raw_allowed_orphans, list):
    raise RuntimeError(
        "configuration.yaml has invalid value for "
        "'orphan_references.allowed_orphans': expected a list, got "
        f"{type(_raw_allowed_orphans).__name__}."
    )
_normalized_orphans: list[str] = []
for _entry in _raw_allowed_orphans:
    if not isinstance(_entry, str):
        raise RuntimeError(
            "configuration.yaml has a non-string entry in "
            f"'orphan_references.allowed_orphans': {_entry!r}."
        )
    _candidate = _entry.replace("\\", "/").strip()
    if _candidate.startswith("./"):
        _candidate = _candidate[2:]
    if not _candidate:
        raise RuntimeError(
            "configuration.yaml has an empty / whitespace-only entry "
            "in 'orphan_references.allowed_orphans'; remove the entry "
            "or replace it with a real path."
        )
    # Entries are documented as skill-root-relative or
    # ``skills/<name>/...`` audit-root-relative.  Reject anything that
    # would make matching environment-dependent: absolute paths and
    # UNC roots (``/foo``, ``//host/share``) would only match on
    # specific machines, drive-letter prefixes (``C:/foo``) likewise,
    # and ``..`` segments could escape the intended root entirely.
    # Each invalid form silently never matches a candidate orphan,
    # so it would suppress the rule by accident — make it loud.
    if _candidate.startswith("/"):
        raise RuntimeError(
            "configuration.yaml has an invalid entry in "
            f"'orphan_references.allowed_orphans': {_entry!r}. "
            "Entries must be relative POSIX paths and must not start "
            "with '/'."
        )
    if (
        len(_candidate) >= 2
        and _candidate[0].isalpha()
        and _candidate[1] == ":"
    ):
        raise RuntimeError(
            "configuration.yaml has an invalid entry in "
            f"'orphan_references.allowed_orphans': {_entry!r}. "
            "Entries must be relative POSIX paths and must not use a "
            "drive-letter prefix."
        )
    if ".." in _candidate.split("/"):
        raise RuntimeError(
            "configuration.yaml has an invalid entry in "
            f"'orphan_references.allowed_orphans': {_entry!r}. "
            "Entries must be relative POSIX paths and must not contain "
            "'..' segments."
        )
    _normalized_orphans.append(_candidate)
ALLOWED_ORPHANS = tuple(_normalized_orphans)

# --- Path Resolution ---
# Cross-file references inside a skill follow standard markdown
# semantics (file-relative).  See references/path-resolution.md for
# the canonical rule, the per-scope behavior (skill root vs
# capability root), the external-reference syntax (../../<dir>/<file>),
# and the liftability invariant.
if "path_resolution" not in _config:
    raise RuntimeError(
        "configuration.yaml is missing required section "
        "'path_resolution'; this foundry build is incomplete."
    )
_path_resolution = _config["path_resolution"]
if "rule_name" not in _path_resolution:
    raise RuntimeError(
        "configuration.yaml is missing required key "
        "'path_resolution.rule_name'."
    )
if "documentation_path" not in _path_resolution:
    raise RuntimeError(
        "configuration.yaml is missing required key "
        "'path_resolution.documentation_path'."
    )
PATH_RESOLUTION_RULE_NAME = str(_path_resolution["rule_name"]).strip()
PATH_RESOLUTION_DOC_PATH = str(_path_resolution["documentation_path"]).strip()
if not PATH_RESOLUTION_RULE_NAME:
    raise RuntimeError(
        "configuration.yaml has an empty value for "
        "'path_resolution.rule_name'."
    )
if not PATH_RESOLUTION_DOC_PATH:
    raise RuntimeError(
        "configuration.yaml has an empty value for "
        "'path_resolution.documentation_path'."
    )
if "reference_extensions" not in _path_resolution:
    raise RuntimeError(
        "configuration.yaml is missing required key "
        "'path_resolution.reference_extensions'."
    )
_raw_extensions = _path_resolution["reference_extensions"]
if not isinstance(_raw_extensions, list) or not _raw_extensions:
    raise RuntimeError(
        "configuration.yaml 'path_resolution.reference_extensions' "
        "must be a non-empty list."
    )
PATH_RESOLUTION_REFERENCE_EXTENSIONS: tuple[str, ...] = tuple(
    str(ext).strip() for ext in _raw_extensions
)
del _raw_extensions

# --- Bundle Packaging ---
_bundle = _config["bundle"]
BUNDLE_MAX_REFERENCE_DEPTH = int(_bundle["max_reference_depth"])
BUNDLE_DESCRIPTION_MAX_LENGTH = int(_bundle["description_max_length"])
BUNDLE_INFER_MAX_WALK_DEPTH = int(_bundle["infer_max_walk_depth"])
BUNDLE_EXCLUDE_PATTERNS = _bundle["exclude_patterns"]

# Valid bundle target identifiers and default (single source of truth)
BUNDLE_VALID_TARGETS = tuple(_bundle["valid_targets"])
BUNDLE_DEFAULT_TARGET = _bundle["default_target"]

# --- Prose YAML Validation ---
# Fail-fast: a stale checkout missing this section produces a clear
# error at import rather than a subtle KeyError later.
if "prose_yaml" not in _config:
    raise RuntimeError(
        "configuration.yaml is missing required section 'prose_yaml'; "
        "this foundry build is incomplete."
    )
_prose = _config["prose_yaml"]
PROSE_YAML_OPT_OUT_MARKER = _prose["opt_out_marker"]
PROSE_YAML_IN_SCOPE_GLOBS = tuple(_prose["in_scope_globs"])

# --- YAML Conformance (construct-id enumeration) ---
if "yaml_conformance" not in _config:
    raise RuntimeError(
        "configuration.yaml is missing required section 'yaml_conformance'; "
        "this foundry build is incomplete."
    )
_yaml_conf = _config["yaml_conformance"]
YAML_CONFORMANCE_CONSTRUCT_IDS = tuple(_yaml_conf["construct_ids"])

# --- Codex Configuration (agents/openai.yaml) ---
_codex = _config["codex_config"]
_codex_iface = _codex["interface"]
CODEX_MAX_DISPLAY_NAME_LENGTH = int(_codex_iface["max_display_name_length"])
CODEX_MAX_SHORT_DESCRIPTION_LENGTH = int(_codex_iface["max_short_description_length"])
RE_HEX_COLOR = re.compile(_codex_iface["hex_color_pattern"])
_codex_deps = _codex["dependencies"]
CODEX_KNOWN_TOOL_TYPES = frozenset(_codex_deps["known_tool_types"])
CODEX_KNOWN_TRANSPORTS = frozenset(_codex_deps["known_transports"])

# Schema key sets for agents/openai.yaml structure validation
CODEX_KNOWN_TOP_KEYS = frozenset(_codex["known_top_level_keys"])
CODEX_KNOWN_INTERFACE_KEYS = frozenset(_codex["known_interface_keys"])
CODEX_KNOWN_POLICY_KEYS = frozenset(_codex["known_policy_keys"])
CODEX_KNOWN_DEPENDENCIES_KEYS = frozenset(_codex["known_dependencies_keys"])
CODEX_KNOWN_TOOL_KEYS = frozenset(_codex["known_tool_keys"])

# Clean up private names
del _f, _config
del _skill, _skill_name, _skill_desc, _voice, _skill_body, _body_refs
del _allowed_tools, _catalogs, _claude_code_catalog, _fence_languages
del _capability_frontmatter, _raw_skill_only_fields
del _normalized_skill_only_fields, _seen_skill_only_fields
del _metadata, _plain_scalar, _WS_DECODE, _fm_suggest
del _dep, _role, _bundle
del _orphan_refs, _raw_allowed_orphans, _normalized_orphans
del _path_resolution
del _codex, _codex_iface, _codex_deps
del _prose, _yaml_conf
