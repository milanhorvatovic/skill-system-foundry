"""Shared validation functions for skill-system-foundry scripts."""

from .constants import (
    MAX_NAME_CHARS, MIN_NAME_CHARS,
    RE_NAME_FORMAT, RESERVED_NAMES,
    LEVEL_FAIL, LEVEL_WARN,
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
