"""Validation for Codex-specific ``agents/openai.yaml`` configuration files.

Validates the optional ``agents/openai.yaml`` file that provides
Codex-specific interface metadata, policy settings, and tool
dependencies for a skill.  The file is not required — skills without
it are valid — but when present its structure must conform to the
schema documented in ``references/codex-extensions.md``.
"""

import os

from .yaml_parser import parse_yaml_subset
from .constants import (
    FILE_CODEX_CONFIG,
    CODEX_MAX_DISPLAY_NAME_LENGTH,
    CODEX_MAX_SHORT_DESCRIPTION_LENGTH,
    RE_HEX_COLOR,
    CODEX_KNOWN_TOOL_TYPES,
    CODEX_KNOWN_TRANSPORTS,
    LEVEL_FAIL,
    LEVEL_WARN,
    LEVEL_INFO,
)


# Top-level keys recognised in agents/openai.yaml.
_KNOWN_TOP_KEYS = frozenset({"interface", "policy", "dependencies"})

# Keys recognised under the ``interface`` section.
_KNOWN_INTERFACE_KEYS = frozenset({
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
})

# Keys recognised under the ``policy`` section.
_KNOWN_POLICY_KEYS = frozenset({"allow_implicit_invocation"})

# Keys recognised under the ``dependencies`` section.
_KNOWN_DEPENDENCIES_KEYS = frozenset({"tools"})

# Keys recognised on each tool entry.
_KNOWN_TOOL_KEYS = frozenset({
    "type",
    "value",
    "description",
    "transport",
    "url",
})


def validate_codex_config(skill_path: str) -> tuple[list[str], list[str]]:
    """Validate the ``agents/openai.yaml`` file inside *skill_path*.

    Returns ``(errors, passes)`` following the standard validation
    pattern.  When the file does not exist the function returns an
    empty pair — the file is optional.
    """
    errors: list[str] = []
    passes: list[str] = []

    config_path = os.path.join(skill_path, FILE_CODEX_CONFIG)
    if not os.path.isfile(config_path):
        # File is optional — absence is not an error.
        return errors, passes

    # Read and parse the YAML file.
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        errors.append(
            f"{LEVEL_FAIL}: cannot read {FILE_CODEX_CONFIG} "
            f"({exc.__class__.__name__}: {exc})"
        )
        return errors, passes

    if not text.strip():
        errors.append(f"{LEVEL_WARN}: {FILE_CODEX_CONFIG} is empty")
        return errors, passes

    # Pre-parse guard: detect top-level list syntax that the parser
    # would coerce to an empty dict, which would hide malformed input.
    # Checks both "- value" and bare "-" (content on following indented lines).
    top_level_lines = [
        ln.lstrip()
        for ln in text.splitlines()
        if ln.strip()
        and not ln.lstrip().startswith("#")
        and not ln[0:1].isspace()
    ]
    if any(ln == "-" or ln.startswith("- ") for ln in top_level_lines):
        errors.append(
            f"{LEVEL_FAIL}: {FILE_CODEX_CONFIG} top-level must be a "
            "mapping, not a sequence"
        )
        return errors, passes

    try:
        config = parse_yaml_subset(text)
    except ValueError as exc:
        errors.append(
            f"{LEVEL_FAIL}: {FILE_CODEX_CONFIG} YAML parse error: {exc}"
        )
        return errors, passes

    if not isinstance(config, dict):
        errors.append(
            f"{LEVEL_FAIL}: {FILE_CODEX_CONFIG} top-level must be a mapping"
        )
        return errors, passes

    # Reject configs that parse to empty dict despite having content —
    # the parser may silently coerce malformed input to {}.
    if config == {} and top_level_lines:
        errors.append(
            f"{LEVEL_FAIL}: {FILE_CODEX_CONFIG} malformed YAML content"
        )
        return errors, passes

    # Check for unrecognised top-level keys.
    unknown_top = sorted(k for k in config if k not in _KNOWN_TOP_KEYS)
    if unknown_top:
        errors.append(
            f"{LEVEL_INFO}: {FILE_CODEX_CONFIG} has unrecognised top-level "
            f"keys: {', '.join(unknown_top)}"
        )

    # --- interface section ---
    iface_errors, iface_passes = _validate_interface(config.get("interface"))
    errors.extend(iface_errors)
    passes.extend(iface_passes)

    # --- policy section ---
    policy_errors, policy_passes = _validate_policy(config.get("policy"))
    errors.extend(policy_errors)
    passes.extend(policy_passes)

    # --- dependencies section ---
    deps_errors, deps_passes = _validate_dependencies(config.get("dependencies"))
    errors.extend(deps_errors)
    passes.extend(deps_passes)

    if not errors:
        passes.append(f"{FILE_CODEX_CONFIG}: valid")

    return errors, passes


def _validate_interface(
    interface: object,
) -> tuple[list[str], list[str]]:
    """Validate the ``interface`` section of a Codex config."""
    errors: list[str] = []
    passes: list[str] = []

    if interface is None:
        return errors, passes

    if not isinstance(interface, dict):
        errors.append(
            f"{LEVEL_WARN}: {FILE_CODEX_CONFIG} 'interface' should be a "
            f"mapping, got {type(interface).__name__}"
        )
        return errors, passes

    # Unrecognised keys
    unknown = sorted(k for k in interface if k not in _KNOWN_INTERFACE_KEYS)
    if unknown:
        errors.append(
            f"{LEVEL_INFO}: {FILE_CODEX_CONFIG} 'interface' has unrecognised "
            f"keys: {', '.join(unknown)}"
        )

    # display_name
    if "display_name" in interface:
        val = interface["display_name"]
        if not isinstance(val, str):
            errors.append(
                f"{LEVEL_WARN}: 'interface.display_name' should be a string, "
                f"got {type(val).__name__}"
            )
        elif len(val) > CODEX_MAX_DISPLAY_NAME_LENGTH:
            errors.append(
                f"{LEVEL_FAIL}: 'interface.display_name' exceeds "
                f"{CODEX_MAX_DISPLAY_NAME_LENGTH} characters ({len(val)} chars)"
            )
        else:
            passes.append(
                f"interface.display_name: {len(val)} chars "
                f"(max {CODEX_MAX_DISPLAY_NAME_LENGTH})"
            )

    # short_description
    if "short_description" in interface:
        val = interface["short_description"]
        if not isinstance(val, str):
            errors.append(
                f"{LEVEL_WARN}: 'interface.short_description' should be a "
                f"string, got {type(val).__name__}"
            )
        elif len(val) > CODEX_MAX_SHORT_DESCRIPTION_LENGTH:
            errors.append(
                f"{LEVEL_FAIL}: 'interface.short_description' exceeds "
                f"{CODEX_MAX_SHORT_DESCRIPTION_LENGTH} characters "
                f"({len(val)} chars)"
            )
        else:
            passes.append(
                f"interface.short_description: {len(val)} chars "
                f"(max {CODEX_MAX_SHORT_DESCRIPTION_LENGTH})"
            )

    # icon_small
    if "icon_small" in interface:
        val = interface["icon_small"]
        if not isinstance(val, str):
            errors.append(
                f"{LEVEL_WARN}: 'interface.icon_small' should be a string, "
                f"got {type(val).__name__}"
            )
        elif not _is_valid_relative_path(val):
            errors.append(
                f"{LEVEL_WARN}: 'interface.icon_small' is not a valid "
                f"relative path: '{val}'"
            )
        else:
            passes.append("interface.icon_small: valid relative path")

    # icon_large
    if "icon_large" in interface:
        val = interface["icon_large"]
        if not isinstance(val, str):
            errors.append(
                f"{LEVEL_WARN}: 'interface.icon_large' should be a string, "
                f"got {type(val).__name__}"
            )
        elif not _is_valid_relative_path(val):
            errors.append(
                f"{LEVEL_WARN}: 'interface.icon_large' is not a valid "
                f"relative path: '{val}'"
            )
        else:
            passes.append("interface.icon_large: valid relative path")

    # brand_color
    if "brand_color" in interface:
        val = interface["brand_color"]
        if not isinstance(val, str):
            errors.append(
                f"{LEVEL_WARN}: 'interface.brand_color' should be a string, "
                f"got {type(val).__name__}"
            )
        elif not RE_HEX_COLOR.match(val):
            errors.append(
                f"{LEVEL_WARN}: 'interface.brand_color' is not a valid hex "
                f"color: '{val}' — expected format #RRGGBB"
            )
        else:
            passes.append(f"interface.brand_color: valid hex color ({val})")

    # default_prompt (just check it's a string)
    if "default_prompt" in interface:
        val = interface["default_prompt"]
        if not isinstance(val, str):
            errors.append(
                f"{LEVEL_WARN}: 'interface.default_prompt' should be a "
                f"string, got {type(val).__name__}"
            )
        else:
            passes.append("interface.default_prompt: present")

    return errors, passes


def _validate_policy(
    policy: object,
) -> tuple[list[str], list[str]]:
    """Validate the ``policy`` section of a Codex config."""
    errors: list[str] = []
    passes: list[str] = []

    if policy is None:
        return errors, passes

    if not isinstance(policy, dict):
        errors.append(
            f"{LEVEL_WARN}: {FILE_CODEX_CONFIG} 'policy' should be a "
            f"mapping, got {type(policy).__name__}"
        )
        return errors, passes

    # Unrecognised keys
    unknown = sorted(k for k in policy if k not in _KNOWN_POLICY_KEYS)
    if unknown:
        errors.append(
            f"{LEVEL_INFO}: {FILE_CODEX_CONFIG} 'policy' has unrecognised "
            f"keys: {', '.join(unknown)}"
        )

    # allow_implicit_invocation — must be a boolean-like string
    if "allow_implicit_invocation" in policy:
        val = policy["allow_implicit_invocation"]
        # The YAML parser returns all scalars as strings, so accept
        # "true"/"false" as valid boolean representations.
        if isinstance(val, str) and val.lower() in ("true", "false"):
            passes.append(
                f"policy.allow_implicit_invocation: {val}"
            )
        else:
            errors.append(
                f"{LEVEL_WARN}: 'policy.allow_implicit_invocation' should be "
                f"a boolean (true/false), got '{val}'"
            )

    return errors, passes


def _validate_dependencies(
    dependencies: object,
) -> tuple[list[str], list[str]]:
    """Validate the ``dependencies`` section of a Codex config."""
    errors: list[str] = []
    passes: list[str] = []

    if dependencies is None:
        return errors, passes

    if not isinstance(dependencies, dict):
        errors.append(
            f"{LEVEL_WARN}: {FILE_CODEX_CONFIG} 'dependencies' should be a "
            f"mapping, got {type(dependencies).__name__}"
        )
        return errors, passes

    # Unrecognised keys
    unknown = sorted(
        k for k in dependencies if k not in _KNOWN_DEPENDENCIES_KEYS
    )
    if unknown:
        errors.append(
            f"{LEVEL_INFO}: {FILE_CODEX_CONFIG} 'dependencies' has "
            f"unrecognised keys: {', '.join(unknown)}"
        )

    # tools
    tools = dependencies.get("tools")
    if tools is None:
        return errors, passes

    if not isinstance(tools, list):
        errors.append(
            f"{LEVEL_WARN}: 'dependencies.tools' should be a list, "
            f"got {type(tools).__name__}"
        )
        return errors, passes

    for idx, tool in enumerate(tools):
        t_errors, t_passes = _validate_tool_entry(tool, idx)
        errors.extend(t_errors)
        passes.extend(t_passes)

    if not errors and tools:
        passes.append(
            f"dependencies.tools: {len(tools)} tool(s) validated"
        )

    return errors, passes


def _validate_tool_entry(
    tool: object,
    index: int,
) -> tuple[list[str], list[str]]:
    """Validate a single tool entry in the ``dependencies.tools`` list."""
    errors: list[str] = []
    passes: list[str] = []
    prefix = f"dependencies.tools[{index}]"

    if not isinstance(tool, dict):
        errors.append(
            f"{LEVEL_WARN}: '{prefix}' should be a mapping, "
            f"got {type(tool).__name__}"
        )
        return errors, passes

    # Unrecognised keys
    unknown = sorted(k for k in tool if k not in _KNOWN_TOOL_KEYS)
    if unknown:
        errors.append(
            f"{LEVEL_INFO}: '{prefix}' has unrecognised keys: "
            f"{', '.join(unknown)}"
        )

    # Required fields: type, value
    if "type" not in tool:
        errors.append(f"{LEVEL_FAIL}: '{prefix}' missing required 'type' field")
    else:
        tool_type = tool["type"]
        if not isinstance(tool_type, str):
            errors.append(
                f"{LEVEL_WARN}: '{prefix}.type' should be a string, "
                f"got {type(tool_type).__name__}"
            )
        elif tool_type not in CODEX_KNOWN_TOOL_TYPES:
            errors.append(
                f"{LEVEL_INFO}: '{prefix}.type' is not a recognised tool "
                f"type: '{tool_type}' — known types: "
                f"{', '.join(sorted(CODEX_KNOWN_TOOL_TYPES))}"
            )

    if "value" not in tool:
        errors.append(
            f"{LEVEL_FAIL}: '{prefix}' missing required 'value' field"
        )
    elif not isinstance(tool["value"], str):
        errors.append(
            f"{LEVEL_WARN}: '{prefix}.value' should be a string, "
            f"got {type(tool['value']).__name__}"
        )

    # Optional fields
    if "description" in tool and not isinstance(tool["description"], str):
        errors.append(
            f"{LEVEL_WARN}: '{prefix}.description' should be a string, "
            f"got {type(tool['description']).__name__}"
        )

    if "transport" in tool:
        transport = tool["transport"]
        if not isinstance(transport, str):
            errors.append(
                f"{LEVEL_WARN}: '{prefix}.transport' should be a string, "
                f"got {type(transport).__name__}"
            )
        elif transport not in CODEX_KNOWN_TRANSPORTS:
            errors.append(
                f"{LEVEL_INFO}: '{prefix}.transport' is not a recognised "
                f"transport: '{transport}' — known transports: "
                f"{', '.join(sorted(CODEX_KNOWN_TRANSPORTS))}"
            )

    if "url" in tool and not isinstance(tool["url"], str):
        errors.append(
            f"{LEVEL_WARN}: '{prefix}.url' should be a string, "
            f"got {type(tool['url']).__name__}"
        )

    return errors, passes


def _is_valid_relative_path(path: str) -> bool:
    """Return True if *path* looks like a valid relative file path.

    Rejects empty strings, absolute paths, and paths containing
    path-traversal sequences (``..``).
    """
    if not path or not path.strip():
        return False
    if os.path.isabs(path):
        return False
    if ".." in path.split("/"):
        return False
    return True
