"""Centralized constants for skill-system-foundry scripts.

Structural constants (directory names, file names, error levels,
templates) are defined directly in Python.  Validation rules
(limits, patterns, reserved words) are loaded from configuration.yaml.

Consumers import everything from this module:
    from lib.constants import DIR_SKILLS, MAX_BODY_LINES, RE_NAME_FORMAT
"""

import os
import re

from .levels import LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO
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

# Error Level Prefixes (imported from levels.py to avoid circular dependency)
# LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO — imported at the top of this file

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

# ===================================================================
# Validation Rules (loaded from configuration.yaml)
# ===================================================================

_config_path = os.path.join(os.path.dirname(__file__), "configuration.yaml")
with open(_config_path, "r", encoding="utf-8") as _f:
    _config = parse_yaml_subset(_f.read())

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

# Allowed-tools validation
_allowed_tools = _skill["allowed_tools"]
KNOWN_TOOLS = frozenset(_allowed_tools["known_tools"])
MAX_ALLOWED_TOOLS = int(_allowed_tools["max_tools"])

# Metadata sub-field validation (foundry conventions — spec allows arbitrary values)
_metadata = _skill["metadata"]
RE_METADATA_VERSION = re.compile(_metadata["version"]["pattern"])
MAX_AUTHOR_LENGTH = int(_metadata["author"]["max_length"])

# License validation
KNOWN_SPDX_LICENSES = frozenset(_skill["license"]["known_spdx"])

# Recognized skill subdirectories
RECOGNIZED_DIRS = frozenset(_skill["recognized_subdirectories"])

# --- Dependency Direction ---
_dep = _config["dependency_direction"]
RE_ROLES_REF = re.compile(_dep["roles_ref_pattern"])
RE_SIBLING_CAP_REF = re.compile(_dep["sibling_capability_ref_pattern"])

# --- Role Composition ---
_role = _config["role_composition"]
MIN_ROLE_SKILLS = int(_role["min_skills"])
RE_SKILL_REF = re.compile(_role["skill_ref_pattern"])
RE_CAPABILITY_REF = re.compile(_role["capability_ref_pattern"])

# --- Bundle Packaging ---
_bundle = _config["bundle"]
BUNDLE_MAX_REFERENCE_DEPTH = int(_bundle["max_reference_depth"])
BUNDLE_DESCRIPTION_MAX_LENGTH = int(_bundle["description_max_length"])
BUNDLE_INFER_MAX_WALK_DEPTH = int(_bundle["infer_max_walk_depth"])
BUNDLE_EXCLUDE_PATTERNS = _bundle["exclude_patterns"]

# Valid bundle target identifiers and default (single source of truth)
BUNDLE_VALID_TARGETS = tuple(_bundle["valid_targets"])
BUNDLE_DEFAULT_TARGET = _bundle["default_target"]

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
del _config_path, _f, _config
del _skill, _skill_name, _skill_desc, _voice, _skill_body, _body_refs
del _allowed_tools, _metadata
del _dep, _role, _bundle
del _codex, _codex_iface, _codex_deps
