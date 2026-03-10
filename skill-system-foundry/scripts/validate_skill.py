#!/usr/bin/env python3
"""
Validate a single skill directory against the Agent Skills specification.

Usage:
    python scripts/validate_skill.py <skill-path>
    python scripts/validate_skill.py skills/project-mgmt
    python scripts/validate_skill.py skills/project-mgmt --verbose
    python scripts/validate_skill.py skills/project-mgmt/capabilities/gate-check --capability
    python scripts/validate_skill.py skills/meta-skill --allow-nested-references
"""

import sys
import os

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.frontmatter import load_frontmatter, count_body_lines
from lib.references import is_within_directory, strip_fragment
from lib.reporting import categorize_errors, print_error_line, print_summary
from lib.validation import validate_name
from lib.constants import (
    MAX_DESCRIPTION_CHARS,
    MAX_BODY_LINES, MAX_COMPATIBILITY_CHARS,
    RE_XML_TAG, RE_FIRST_PERSON, RE_FIRST_PERSON_PLURAL,
    RE_SECOND_PERSON, RE_IMPERATIVE_START,
    RE_MARKDOWN_LINK_REF, RE_BACKTICK_REF,
    RECOGNIZED_DIRS,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, SEPARATOR_WIDTH,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
)


def validate_description(description):
    """Validate the description field against spec rules."""
    errors = []
    passes = []

    if not description:
        errors.append(f"{LEVEL_FAIL}: 'description' field is empty")
        return errors, passes

    if len(description) > MAX_DESCRIPTION_CHARS:
        errors.append(
            f"{LEVEL_FAIL}: 'description' exceeds {MAX_DESCRIPTION_CHARS} characters ({len(description)} chars)"
        )
    else:
        passes.append(f"description: {len(description)} chars (max {MAX_DESCRIPTION_CHARS})")

    # Check for XML tags
    if RE_XML_TAG.search(description):
        errors.append(f"{LEVEL_WARN}: 'description' may contain XML tags (not allowed)")

    # Check for first/second person
    first_person = RE_FIRST_PERSON.search(description)
    first_person_plural = RE_FIRST_PERSON_PLURAL.search(description)
    second_person = RE_SECOND_PERSON.search(description)
    # Heuristic: detect imperative/infinitive starts (best-effort check —
    # some false positives are possible with uncommon verb forms)
    imperative_start = RE_IMPERATIVE_START.match(description)
    if first_person:
        errors.append(
            f"{LEVEL_WARN}: 'description' uses first person — should be third person"
        )
    elif first_person_plural:
        errors.append(
            f"{LEVEL_WARN}: 'description' uses first-person plural — should be third person"
        )
    elif second_person:
        errors.append(
            f"{LEVEL_WARN}: 'description' uses second person — should be third person"
        )
    elif imperative_start:
        errors.append(
            f"{LEVEL_WARN}: 'description' may use imperative voice — prefer third person "
            "(e.g., 'Processes data' not 'Process data'). "
            "Note: this is a best-effort heuristic check."
        )
    else:
        passes.append("description: third-person voice")

    return errors, passes


def validate_body(body, skill_md_path, allow_nested_refs=False):
    """Validate skill or capability entry point body."""
    errors = []
    passes = []
    entry_filename = os.path.basename(skill_md_path)

    line_count = count_body_lines(body)
    if line_count > MAX_BODY_LINES:
        errors.append(
            f"{LEVEL_WARN}: {entry_filename} body is {line_count} lines (recommended max: {MAX_BODY_LINES})"
        )
    else:
        passes.append(f"body: {line_count} lines (max {MAX_BODY_LINES})")

    # Check for deeply nested references (references to files that themselves reference)
    # This is a heuristic — check for reference files in the body
    refs = RE_MARKDOWN_LINK_REF.findall(body)
    backtick_refs = RE_BACKTICK_REF.findall(body)
    refs = list(set(refs + backtick_refs))
    # Exclude template placeholders (e.g., references/<file>.md)
    refs = [r for r in refs if "<" not in r and ">" not in r]

    # Always check for broken references regardless of allow_nested_refs
    broken_found = False
    nested_found = False

    skill_dir = os.path.dirname(skill_md_path)
    seen_paths: set[str] = set()

    for ref in refs:
        # Strip URL fragments, queries, and markdown link titles
        normalized_ref = strip_fragment(ref)
        if not normalized_ref:
            continue  # Nothing to check (pure fragment reference)
        ref_path = os.path.normpath(
            os.path.join(os.path.dirname(skill_md_path), normalized_ref)
        )

        # Skip refs that resolve to the same file (e.g., guide.md#one vs guide.md#two)
        if ref_path in seen_paths:
            continue
        seen_paths.add(ref_path)

        # Reject references that escape the skill directory
        if not is_within_directory(ref_path, skill_dir):
            broken_found = True
            errors.append(
                f"{LEVEL_WARN}: '{ref}' referenced in {entry_filename} escapes skill directory"
            )
            continue

        if not os.path.exists(ref_path):
            broken_found = True
            errors.append(
                f"{LEVEL_WARN}: '{ref}' referenced in {entry_filename} does not exist"
            )
            continue

        # Handle directory references gracefully
        if not os.path.isfile(ref_path):
            broken_found = True
            errors.append(
                f"{LEVEL_WARN}: '{ref}' referenced in {entry_filename} resolves to a non-file path"
            )
            continue

        # Check file is readable regardless of allow_nested_refs
        # (unreadable files should be reported even when nested check is skipped)
        try:
            with open(ref_path, "r", encoding="utf-8") as f:
                ref_content = f.read()
        except (OSError, UnicodeError) as exc:
            broken_found = True
            errors.append(
                f"{LEVEL_WARN}: '{ref}' referenced in {entry_filename} "
                f"cannot be read ({exc.__class__.__name__}: {exc})"
            )
            continue

        # Nested reference check — only when flag is not set
        if not allow_nested_refs:
            nested_refs = RE_MARKDOWN_LINK_REF.findall(ref_content)
            nested_backtick_refs = RE_BACKTICK_REF.findall(ref_content)
            nested_refs = list(set(nested_refs + nested_backtick_refs))
            # Exclude template placeholders in nested refs too
            nested_refs = [r for r in nested_refs if "<" not in r and ">" not in r]
            if nested_refs:
                nested_found = True
                errors.append(
                    f"{LEVEL_WARN}: '{ref}' contains nested references: {nested_refs}. "
                    f"Keep references one level deep from {entry_filename}."
                )

    if allow_nested_refs and refs and not broken_found:
        passes.append("references: nested-reference check skipped (--allow-nested-references)")
    elif refs and not nested_found and not broken_found:
        passes.append("references: one level deep, no nested refs")

    return errors, passes


def validate_directories(skill_path):
    """Check for recognized optional directories."""
    warnings = []
    passes = []

    for item in os.listdir(skill_path):
        item_path = os.path.join(skill_path, item)
        if os.path.isdir(item_path) and item not in RECOGNIZED_DIRS:
            warnings.append(
                f"{LEVEL_INFO}: Non-standard directory '{item}/' found. "
                f"Recognized directories: {', '.join(sorted(RECOGNIZED_DIRS))}"
            )

    if not warnings:
        passes.append("directories: all recognized")

    return warnings, passes


def validate_skill(skill_path, is_capability=False, allow_nested_refs=False):
    """Run all validations on a skill directory."""
    errors = []
    passes = []
    skill_path = os.path.abspath(skill_path)
    dir_name = os.path.basename(skill_path)

    # Capabilities use capability.md; registered skills use SKILL.md
    entry_filename = FILE_CAPABILITY_MD if is_capability else FILE_SKILL_MD
    skill_md = os.path.join(skill_path, entry_filename)
    if not os.path.exists(skill_md):
        errors.append(f"{LEVEL_FAIL}: No {entry_filename} found in {skill_path}")
        return errors, passes

    # Parse frontmatter
    frontmatter, body = load_frontmatter(skill_md)

    if frontmatter is None and not is_capability:
        errors.append(f"{LEVEL_FAIL}: No YAML frontmatter found (must start with ---)")
        return errors, passes

    if frontmatter and "_parse_error" in frontmatter:
        errors.append(f"{LEVEL_FAIL}: YAML parse error: {frontmatter['_parse_error']}")
        return errors, passes

    if is_capability:
        # Capabilities don't require frontmatter
        if frontmatter and "name" in frontmatter:
            errors.append(
                f"{LEVEL_INFO}: Capability has 'name' in frontmatter — this is fine for "
                "documentation but won't be used for discovery"
            )
        body_errors, body_passes = validate_body(body, skill_md, allow_nested_refs)
        errors.extend(body_errors)
        passes.extend(body_passes)
        return errors, passes

    # Validate required fields
    if not frontmatter:
        frontmatter = {}

    if "name" not in frontmatter:
        errors.append(f"{LEVEL_FAIL}: Missing required 'name' field in frontmatter")
    else:
        name_errors, name_passes = validate_name(frontmatter["name"], dir_name)
        errors.extend(name_errors)
        passes.extend(name_passes)

    if "description" not in frontmatter:
        errors.append(f"{LEVEL_FAIL}: Missing required 'description' field in frontmatter")
    else:
        desc_errors, desc_passes = validate_description(str(frontmatter["description"]))
        errors.extend(desc_errors)
        passes.extend(desc_passes)

    # Validate optional fields
    if "compatibility" in frontmatter:
        comp = str(frontmatter["compatibility"])
        if len(comp) > MAX_COMPATIBILITY_CHARS:
            errors.append(
                f"{LEVEL_FAIL}: 'compatibility' exceeds {MAX_COMPATIBILITY_CHARS} characters ({len(comp)} chars)"
            )
        else:
            passes.append(f"compatibility: {len(comp)} chars (max {MAX_COMPATIBILITY_CHARS})")

    # Validate body
    body_errors, body_passes = validate_body(body, skill_md, allow_nested_refs)
    errors.extend(body_errors)
    passes.extend(body_passes)

    # Validate directories
    dir_errors, dir_passes = validate_directories(skill_path)
    errors.extend(dir_errors)
    passes.extend(dir_passes)

    return errors, passes


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_skill.py <skill-path> [--capability] [--verbose] [--allow-nested-references]")
        print("Example: python validate_skill.py skills/project-mgmt")
        sys.exit(1)

    skill_path = sys.argv[1]
    is_capability = "--capability" in sys.argv
    verbose = "--verbose" in sys.argv
    allow_nested_refs = "--allow-nested-references" in sys.argv

    if not os.path.isdir(skill_path):
        print(f"Error: '{skill_path}' is not a directory")
        sys.exit(1)

    print(f"Validating: {skill_path}")
    print(f"Type: {'capability' if is_capability else 'registered skill'}")
    print("-" * SEPARATOR_WIDTH)

    errors, passes = validate_skill(skill_path, is_capability, allow_nested_refs)

    if verbose:
        for p in passes:
            print(f"  \u2713 {p}")

    if not errors:
        if not verbose:
            print("\u2713 All checks passed")
        else:
            print("-" * SEPARATOR_WIDTH)
            print(f"\u2713 All checks passed ({len(passes)} checks)")
        sys.exit(0)

    fails, warns, infos = categorize_errors(errors)

    for error in errors:
        print_error_line(error)

    print("-" * SEPARATOR_WIDTH)
    print_summary(fails, warns, infos)

    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
