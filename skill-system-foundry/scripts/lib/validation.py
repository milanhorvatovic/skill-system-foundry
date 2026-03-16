"""Shared validation functions for skill-system-foundry scripts."""

from .constants import (
    MAX_NAME_CHARS, MIN_NAME_CHARS,
    RE_NAME_FORMAT, RESERVED_NAMES,
    KNOWN_FRONTMATTER_KEYS, KNOWN_TOOLS, MAX_ALLOWED_TOOLS,
    RE_METADATA_VERSION,
    MAX_AUTHOR_LENGTH, KNOWN_SPDX_LICENSES,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
)


def validate_name(name, dir_name):
    """Validate the name field against spec rules."""
    errors = []
    passes = []

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

    tools = value.split()
    if len(tools) > MAX_ALLOWED_TOOLS:
        errors.append(
            f"{LEVEL_WARN}: [foundry] 'allowed-tools' lists {len(tools)} tools "
            f"(max {MAX_ALLOWED_TOOLS}) — consider splitting the skill"
        )
    else:
        passes.append(f"allowed-tools: {len(tools)} tools (max {MAX_ALLOWED_TOOLS})")

    unknown = sorted(set(t for t in tools if t not in KNOWN_TOOLS))
    if unknown:
        errors.append(
            f"{LEVEL_INFO}: [foundry] 'allowed-tools' contains unrecognized tools: "
            f"{', '.join(unknown)} — verify spelling"
        )
    else:
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
                f"{LEVEL_WARN}: [spec] 'metadata.version' should be a string, "
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
                f"{LEVEL_WARN}: [spec] 'metadata.spec' should be a string, "
                f"got {type(spec).__name__}"
            )
        else:
            passes.append(f"metadata.spec: valid string ({spec})")

    if "author" in metadata:
        author = metadata["author"]
        if not isinstance(author, str):
            errors.append(
                f"{LEVEL_WARN}: [spec] 'metadata.author' should be a string, "
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
        errors.append(
            f"{LEVEL_INFO}: [foundry] unrecognized frontmatter keys: "
            f"{', '.join(unknown_keys)} — check for typos. "
            f"Known keys: {', '.join(sorted(KNOWN_FRONTMATTER_KEYS))}"
        )
    else:
        passes.append("frontmatter: all keys recognized")

    return errors, passes
