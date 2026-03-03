"""Centralized constants for skill-system-foundry scripts.

Structural constants (directory names, file names, error levels,
templates) are defined directly in Python.  Validation rules
(limits, patterns, reserved words) are loaded from configuration.yaml.

Consumers import everything from this module:
    from lib.constants import DIR_SKILLS, MAX_BODY_LINES, RE_NAME_FORMAT
"""

import os
import re

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
FILE_GITKEEP = ".gitkeep"
EXT_MARKDOWN = ".md"

# Error Level Prefixes
LEVEL_FAIL = "FAIL"
LEVEL_WARN = "WARN"
LEVEL_INFO = "INFO"

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

# Recognized skill subdirectories
RECOGNIZED_DIRS = frozenset(_skill["recognized_subdirectories"])

# --- Dependency Direction ---
_dep = _config["dependency_direction"]
RE_ROLES_REF = re.compile(_dep["roles_ref_pattern"])
RE_SIBLING_CAP_REF = re.compile(_dep["sibling_capability_ref_pattern"])

# Clean up private names
del _config_path, _f, _config
del _skill, _skill_name, _skill_desc, _voice, _skill_body, _body_refs, _dep
