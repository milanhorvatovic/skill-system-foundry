"""Shared validation functions for skill-system-foundry scripts."""

from .constants import (
    MAX_NAME_CHARS, MIN_NAME_CHARS,
    RE_NAME_FORMAT, RESERVED_NAMES,
    KNOWN_FRONTMATTER_KEYS, KNOWN_TOOLS, MAX_ALLOWED_TOOLS,
    RE_METADATA_VERSION, KNOWN_SPEC_VERSIONS, SPEC_VERSION_PREFIX,
    MAX_AUTHOR_LENGTH, KNOWN_SPDX_LICENSES,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
)


def validate_name(name, dir_name):
    """Validate the name field against spec rules."""
    errors = []
    passes = []

    if not name:
        errors.append(f"{LEVEL_FAIL}: 'name' field is empty")
        return errors, passes

    if len(name) > MAX_NAME_CHARS:
        errors.append(f"{LEVEL_FAIL}: 'name' exceeds {MAX_NAME_CHARS} characters ({len(name)} chars)")
    else:
        passes.append(f"name: {len(name)} chars (max {MAX_NAME_CHARS})")

    if name != name.lower():
        errors.append(f"{LEVEL_FAIL}: 'name' contains uppercase characters: '{name}'")

    if not RE_NAME_FORMAT.match(name):
        errors.append(
            f"{LEVEL_FAIL}: 'name' has invalid format: '{name}' "
            "(must be lowercase alphanumeric + hyphens, no leading/trailing hyphens)"
        )
    else:
        passes.append("name: valid format")

    if "--" in name:
        errors.append(f"{LEVEL_FAIL}: 'name' contains consecutive hyphens: '{name}'")

    if "_" in name:
        errors.append(f"{LEVEL_FAIL}: 'name' contains underscores: '{name}'")

    if " " in name:
        errors.append(f"{LEVEL_FAIL}: 'name' contains spaces: '{name}'")

    if name != dir_name:
        errors.append(
            f"{LEVEL_FAIL}: 'name' ({name}) does not match directory name ({dir_name})"
        )
    else:
        passes.append("name: matches directory")

    # Anthropic-specific restrictions
    for reserved in RESERVED_NAMES:
        if reserved in name:
            errors.append(
                f"{LEVEL_FAIL}: 'name' contains reserved word '{reserved}' "
                "(not allowed on Anthropic platforms)"
            )

    if len(name) < MIN_NAME_CHARS:
        errors.append(
            f"{LEVEL_WARN}: 'name' is only {len(name)} character(s) — "
            "consider a more descriptive name"
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
            f"{LEVEL_WARN}: 'allowed-tools' should be a space-separated string, "
            f"got {type(value).__name__}"
        )
        return errors, passes

    if not value.strip():
        errors.append(f"{LEVEL_WARN}: 'allowed-tools' is empty")
        return errors, passes

    tools = value.split()
    if len(tools) > MAX_ALLOWED_TOOLS:
        errors.append(
            f"{LEVEL_WARN}: 'allowed-tools' lists {len(tools)} tools "
            f"(max {MAX_ALLOWED_TOOLS}) — consider splitting the skill"
        )
    else:
        passes.append(f"allowed-tools: {len(tools)} tools (max {MAX_ALLOWED_TOOLS})")

    unknown = sorted(set(t for t in tools if t not in KNOWN_TOOLS))
    if unknown:
        errors.append(
            f"{LEVEL_INFO}: 'allowed-tools' contains unrecognized tools: "
            f"{', '.join(unknown)} — verify spelling"
        )
    else:
        passes.append("allowed-tools: all tools recognized")

    return errors, passes


def validate_metadata(metadata: object) -> tuple[list[str], list[str]]:
    """Validate the metadata frontmatter sub-fields.

    Checks version (semver pattern), spec (known versions), and
    author (non-empty string within length limit) when present.

    Returns (errors, passes) tuple.
    """
    errors: list[str] = []
    passes: list[str] = []

    if not isinstance(metadata, dict):
        errors.append(
            f"{LEVEL_WARN}: 'metadata' should be a key-value map, "
            f"got {type(metadata).__name__}"
        )
        return errors, passes

    if "version" in metadata:
        version = metadata["version"]
        if not isinstance(version, str):
            errors.append(
                f"{LEVEL_WARN}: 'metadata.version' should be a string, "
                f"got {type(version).__name__}"
            )
        elif RE_METADATA_VERSION.match(version):
            passes.append(f"metadata.version: valid semver ({version})")
        else:
            errors.append(
                f"{LEVEL_WARN}: 'metadata.version' does not match semver pattern: "
                f"'{version}' — expected MAJOR.MINOR.PATCH"
            )

    if "spec" in metadata:
        spec = metadata["spec"]
        if not isinstance(spec, str):
            errors.append(
                f"{LEVEL_WARN}: 'metadata.spec' should be a string, "
                f"got {type(spec).__name__}"
            )
        else:
            # Normalize optional prefix (e.g. "agentskills.io/1.0" -> "1.0")
            normalized = spec
            if SPEC_VERSION_PREFIX and spec.startswith(SPEC_VERSION_PREFIX):
                normalized = spec[len(SPEC_VERSION_PREFIX):]
            if normalized in KNOWN_SPEC_VERSIONS:
                passes.append(f"metadata.spec: recognized version ({spec})")
            else:
                errors.append(
                    f"{LEVEL_INFO}: 'metadata.spec' is not a recognized version: "
                    f"'{spec}' — known versions: {', '.join(sorted(KNOWN_SPEC_VERSIONS))}"
                )

    if "author" in metadata:
        author = metadata["author"]
        if not isinstance(author, str):
            errors.append(
                f"{LEVEL_WARN}: 'metadata.author' should be a string, "
                f"got {type(author).__name__}"
            )
        elif not author.strip():
            errors.append(
                f"{LEVEL_WARN}: 'metadata.author' is empty"
            )
        elif len(author) > MAX_AUTHOR_LENGTH:
            errors.append(
                f"{LEVEL_WARN}: 'metadata.author' exceeds {MAX_AUTHOR_LENGTH} "
                f"characters ({len(author)} chars)"
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
            f"{LEVEL_WARN}: 'license' should be a string, "
            f"got {type(value).__name__}"
        )
        return errors, passes

    if not value.strip():
        errors.append(f"{LEVEL_WARN}: 'license' is empty")
        return errors, passes

    license_str = value.strip()
    if license_str in KNOWN_SPDX_LICENSES:
        passes.append(f"license: recognized SPDX identifier ({license_str})")
    else:
        errors.append(
            f"{LEVEL_INFO}: 'license' value '{license_str}' is not a recognized "
            "SPDX identifier — verify spelling or use a standard SPDX ID"
        )

    return errors, passes


def validate_known_keys(frontmatter: dict) -> tuple[list[str], list[str]]:
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
            f"{LEVEL_INFO}: unrecognized frontmatter keys: "
            f"{', '.join(unknown_keys)} — check for typos. "
            f"Known keys: {', '.join(sorted(KNOWN_FRONTMATTER_KEYS))}"
        )
    else:
        passes.append("frontmatter: all keys recognized")

    return errors, passes
