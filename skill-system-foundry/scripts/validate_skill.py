#!/usr/bin/env python3
"""
Validate a single skill directory against the Agent Skills specification.

Usage:
    python scripts/validate_skill.py <skill-path>
    python scripts/validate_skill.py skills/project-mgmt
    python scripts/validate_skill.py skills/project-mgmt --verbose
    python scripts/validate_skill.py skills/project-mgmt/capabilities/gate-check --capability
    python scripts/validate_skill.py skills/meta-skill --allow-nested-references
    python scripts/validate_skill.py skills/project-mgmt --json
"""

import argparse
import re
import sys
import os

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.frontmatter import load_frontmatter, count_body_lines
from lib.references import is_within_directory, strip_fragment
from lib.reporting import (
    categorize_errors,
    categorize_errors_for_json,
    print_error_line,
    print_summary,
    to_json_output,
)
from lib.validation import (
    validate_name,
    validate_allowed_tools,
    validate_metadata,
    validate_license,
    validate_known_keys,
)
from lib.codex_config import validate_codex_config
from lib.constants import (
    MAX_DESCRIPTION_CHARS,
    MAX_BODY_LINES, MAX_COMPATIBILITY_CHARS,
    RE_XML_TAG, RE_FIRST_PERSON, RE_FIRST_PERSON_PLURAL,
    RE_SECOND_PERSON, RE_IMPERATIVE_START,
    RE_MARKDOWN_LINK_REF, RE_BACKTICK_REF,
    RECOGNIZED_DIRS,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, SEPARATOR_WIDTH,
    EXT_MARKDOWN,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
)


def find_skill_root(start_dir: str) -> str | None:
    """Walk upward from *start_dir* looking for a directory containing SKILL.md.

    Returns the absolute path of the directory containing ``SKILL.md``,
    or ``None`` if no such directory is found before reaching the
    filesystem root.
    """
    current = os.path.abspath(start_dir)
    while True:
        if os.path.isfile(os.path.join(current, FILE_SKILL_MD)):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def validate_description(description: str) -> tuple[list[str], list[str]]:
    """Validate the description field.

    Checks spec rules (length, non-empty), platform constraints
    (Anthropic XML-tag restriction), and foundry conventions
    (third-person voice recommendation).
    """
    errors: list[str] = []
    passes: list[str] = []

    if not description:
        errors.append(f"{LEVEL_FAIL}: [spec] 'description' field is empty")
        return errors, passes

    if len(description) > MAX_DESCRIPTION_CHARS:
        errors.append(
            f"{LEVEL_FAIL}: [spec] 'description' exceeds {MAX_DESCRIPTION_CHARS} characters ({len(description)} chars)"
        )
    else:
        passes.append(f"description: {len(description)} chars (max {MAX_DESCRIPTION_CHARS})")

    # Platform restriction (Anthropic): XML tags not allowed in description
    if RE_XML_TAG.search(description):
        errors.append(
            f"{LEVEL_WARN}: [platform: Anthropic] 'description' contains XML tags "
            "— not allowed on Anthropic platforms"
        )

    # Foundry convention: third-person voice recommended
    first_person = RE_FIRST_PERSON.search(description)
    first_person_plural = RE_FIRST_PERSON_PLURAL.search(description)
    second_person = RE_SECOND_PERSON.search(description)
    # Heuristic: detect imperative/infinitive starts (best-effort check —
    # some false positives are possible with uncommon verb forms)
    imperative_start = RE_IMPERATIVE_START.match(description)
    if first_person:
        errors.append(
            f"{LEVEL_INFO}: [foundry] 'description' uses first person — "
            "third-person voice recommended"
        )
    elif first_person_plural:
        errors.append(
            f"{LEVEL_INFO}: [foundry] 'description' uses first-person plural — "
            "third-person voice recommended"
        )
    elif second_person:
        errors.append(
            f"{LEVEL_INFO}: [foundry] 'description' uses second person — "
            "third-person voice recommended"
        )
    elif imperative_start:
        errors.append(
            f"{LEVEL_INFO}: [foundry] 'description' may use imperative voice — "
            "third-person recommended (e.g., 'Processes data' not 'Process data'). "
            "Note: this is a best-effort heuristic check."
        )
    else:
        passes.append("description: third-person voice")

    return errors, passes


def _check_references(
    body: str, source_label: str, skill_root: str,
    allow_nested_refs: bool = False,
) -> tuple[list[str], list[str]]:
    """Check markdown references in *body* against the skill root.

    *source_label* identifies the file in error messages (e.g.
    ``"SKILL.md"`` or ``"references/guide.md"``).  All intra-skill
    references are resolved relative to *skill_root*.
    """
    errors: list[str] = []
    passes: list[str] = []

    # Strip fenced code blocks so example links inside ``` are not
    # treated as real references.
    stripped = re.sub(r"```[^\n]*\n.*?```", "", body, flags=re.DOTALL)

    refs = RE_MARKDOWN_LINK_REF.findall(stripped)
    backtick_refs = RE_BACKTICK_REF.findall(stripped)
    refs = list(set(refs + backtick_refs))
    # Exclude template placeholders (e.g., references/<file>.md)
    refs = [r for r in refs if "<" not in r and ">" not in r]

    broken_found = False
    nested_found = False
    external_found = False
    internal_checked = 0

    seen_paths: set[str] = set()

    for ref in refs:
        # Strip URL fragments, queries, and markdown link titles
        normalized_ref = strip_fragment(ref)
        if not normalized_ref:
            continue  # Nothing to check (pure fragment reference)
        ref_path = os.path.normpath(
            os.path.join(skill_root, normalized_ref)
        )

        # Skip refs that resolve to the same file (e.g., guide.md#one vs guide.md#two)
        if ref_path in seen_paths:
            continue
        seen_paths.add(ref_path)

        # Note: references escaping the skill directory are allowed by the
        # spec and used by the foundry's shared-resource architecture
        # (e.g., ../../shared/references/).  Report as INFO for awareness.
        # All filesystem checks (existence, readability, nesting) are
        # skipped for external refs to avoid acting as an existence oracle.
        is_external = not is_within_directory(ref_path, skill_root)

        # Reject parent traversals (../) for intra-skill references.
        # Check raw path segments before normalization to catch patterns
        # like references/../references/guide.md that normpath would collapse.
        # The WARN is emitted but validation continues so broken-link and
        # nesting checks still run for the resolved path.
        if not is_external and ".." in normalized_ref.replace("\\", "/").split("/"):
            errors.append(
                f"{LEVEL_WARN}: [foundry] '{ref}' referenced in {source_label} "
                "uses parent traversal — use skill-root-relative paths instead"
            )
        if is_external:
            external_found = True
            errors.append(
                f"{LEVEL_INFO}: [foundry] '{ref}' referenced in {source_label} "
                "resolves outside skill directory — acceptable for shared "
                "resources but verify the path is intentional"
            )
            # Skip all filesystem checks for external refs to avoid acting
            # as a filesystem existence oracle in CI environments.
            continue

        internal_checked += 1

        if not os.path.exists(ref_path):
            broken_found = True
            errors.append(
                f"{LEVEL_WARN}: [spec] '{ref}' referenced in {source_label} does not exist"
            )
            continue

        # Handle directory references gracefully
        if not os.path.isfile(ref_path):
            broken_found = True
            errors.append(
                f"{LEVEL_WARN}: [spec] '{ref}' referenced in {source_label} resolves to a non-file path"
            )
            continue

        # Check file is readable
        try:
            with open(ref_path, "r", encoding="utf-8") as f:
                ref_content = f.read()
        except (OSError, UnicodeError) as exc:
            broken_found = True
            errors.append(
                f"{LEVEL_WARN}: [spec] '{ref}' referenced in {source_label} "
                f"cannot be read ({exc.__class__.__name__}: {exc})"
            )
            continue

        # Nested reference check — only when flag is not set
        if not allow_nested_refs:
            # Strip fenced code blocks from referenced content so example
            # links inside ``` don't trigger false nested-reference WARNs.
            ref_stripped = re.sub(
                r"```[^\n]*\n.*?```", "", ref_content, flags=re.DOTALL,
            )
            nested_refs = RE_MARKDOWN_LINK_REF.findall(ref_stripped)
            nested_backtick_refs = RE_BACKTICK_REF.findall(ref_stripped)
            nested_refs = list(set(nested_refs + nested_backtick_refs))
            # Exclude template placeholders in nested refs too
            nested_refs = [r for r in nested_refs if "<" not in r and ">" not in r]
            if nested_refs:
                nested_found = True
                errors.append(
                    f"{LEVEL_WARN}: [spec] '{ref}' contains nested references: {nested_refs}. "
                    f"Keep references one level deep from {source_label}."
                )

    if allow_nested_refs and refs and not broken_found:
        passes.append("references: nested-reference check skipped (--allow-nested-references)")
    elif internal_checked > 0 and not nested_found and not broken_found:
        if external_found:
            passes.append(
                "references: internal refs one level deep, no nested refs "
                "(external refs excluded from nesting checks)"
            )
        else:
            passes.append("references: one level deep, no nested refs")

    if external_found and internal_checked == 0 and refs:
        passes.append(
            "references: all references resolve outside skill directory "
            "(external refs excluded from nesting checks)"
        )

    return errors, passes


def validate_body(
    body: str, skill_md_path: str, skill_root: str,
    allow_nested_refs: bool = False,
) -> tuple[list[str], list[str]]:
    """Validate skill or capability entry point body."""
    errors: list[str] = []
    passes: list[str] = []
    entry_filename = os.path.basename(skill_md_path)

    line_count = count_body_lines(body)
    if line_count > MAX_BODY_LINES:
        errors.append(
            f"{LEVEL_WARN}: [foundry] {entry_filename} body is {line_count} lines (recommended max: {MAX_BODY_LINES})"
        )
    else:
        passes.append(f"body: {line_count} lines (max {MAX_BODY_LINES})")

    ref_errors, ref_passes = _check_references(
        body, entry_filename, skill_root, allow_nested_refs,
    )
    errors.extend(ref_errors)
    passes.extend(ref_passes)

    return errors, passes


def validate_skill_references(
    skill_path: str, skill_root: str, entry_file: str,
) -> tuple[list[str], list[str]]:
    """Validate references in all markdown files across the skill tree.

    Walks *skill_path*, reads each ``.md`` file, and checks that all
    intra-skill references resolve from *skill_root*.  The entry file
    (*entry_file*) is skipped because it is already validated by
    :func:`validate_body`.  Nested-reference depth checks are always
    skipped for non-entry files because the spec constrains nesting
    from entry points only.
    """
    errors: list[str] = []
    passes: list[str] = []
    entry_abs = os.path.abspath(entry_file)
    files_checked = 0

    for dirpath, _dirnames, filenames in os.walk(skill_path):
        for fname in sorted(filenames):
            if not fname.endswith(EXT_MARKDOWN):
                continue
            filepath = os.path.join(dirpath, fname)
            if os.path.abspath(filepath) == entry_abs:
                continue

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeError) as exc:
                rel_label = os.path.relpath(filepath, skill_root)
                errors.append(
                    f"{LEVEL_WARN}: [spec] '{rel_label}' cannot be read "
                    f"({exc.__class__.__name__}: {exc})"
                )
                continue

            rel_label = os.path.relpath(filepath, skill_root)
            file_errors, _file_passes = _check_references(
                content, rel_label, skill_root,
                True,  # nested refs allowed in non-entry files; spec constrains depth from entry points only
            )

            files_checked += 1
            errors.extend(file_errors)

    if files_checked > 0:
        warn_errors = [e for e in errors if e.startswith(LEVEL_WARN)]
        if not warn_errors:
            passes.append(
                f"skill-wide references: {files_checked} additional files checked, all refs valid"
            )

    return errors, passes


def validate_directories(skill_path: str) -> tuple[list[str], list[str]]:
    """Check for recognized optional directories.

    The spec explicitly allows any additional files/directories.
    This check is a foundry convention to flag non-standard directories
    for awareness, not as an error.
    """
    warnings: list[str] = []
    passes: list[str] = []

    for item in os.listdir(skill_path):
        item_path = os.path.join(skill_path, item)
        if os.path.isdir(item_path) and item not in RECOGNIZED_DIRS:
            warnings.append(
                f"{LEVEL_INFO}: [foundry] Non-standard directory '{item}/' found "
                "(the spec allows arbitrary directories). "
                f"Recognized directories: {', '.join(sorted(RECOGNIZED_DIRS))}"
            )

    if not warnings:
        passes.append("directories: all recognized")

    return warnings, passes


def validate_skill(
    skill_path: str, is_capability: bool = False, allow_nested_refs: bool = False,
) -> tuple[list[str], list[str]]:
    """Run all validations on a skill directory."""
    errors: list[str] = []
    passes: list[str] = []
    skill_path = os.path.abspath(skill_path)
    dir_name = os.path.basename(skill_path)

    # Capabilities use capability.md; registered skills use SKILL.md
    entry_filename = FILE_CAPABILITY_MD if is_capability else FILE_SKILL_MD
    skill_md = os.path.join(skill_path, entry_filename)
    if not os.path.exists(skill_md):
        errors.append(f"{LEVEL_FAIL}: [spec] No {entry_filename} found in {skill_path}")
        return errors, passes

    # Parse frontmatter
    frontmatter, body, scalar_warnings = load_frontmatter(skill_md)

    if frontmatter is None and not is_capability:
        errors.append(f"{LEVEL_FAIL}: [spec] No YAML frontmatter found (must start with ---)")
        return errors, passes

    if frontmatter and "_parse_error" in frontmatter:
        errors.append(f"{LEVEL_FAIL}: [spec] YAML parse error: {frontmatter['_parse_error']}")
        return errors, passes

    errors.extend(scalar_warnings)

    # Determine the skill root for reference resolution.
    # For regular skills, skill_path is the root (contains SKILL.md).
    # For capabilities, walk upward to find the containing skill root.
    if is_capability:
        detected_root = find_skill_root(os.path.dirname(skill_path))
        skill_root = detected_root if detected_root is not None else skill_path
    else:
        skill_root = skill_path

    if is_capability:
        # Capabilities don't require frontmatter
        if frontmatter and "name" in frontmatter:
            errors.append(
                f"{LEVEL_INFO}: [foundry] Capability has 'name' in frontmatter — this is fine for "
                "documentation but won't be used for discovery"
            )
        body_errors, body_passes = validate_body(body, skill_md, skill_root, allow_nested_refs)
        errors.extend(body_errors)
        passes.extend(body_passes)
        # Validate references in all .md files across the skill tree
        # (walk skill_root, not skill_path, so the entire skill is scanned)
        ref_errors, ref_passes = validate_skill_references(
            skill_root, skill_root, skill_md,
        )
        errors.extend(ref_errors)
        passes.extend(ref_passes)
        return errors, passes

    # Validate required fields
    if not frontmatter:
        frontmatter = {}

    if "name" not in frontmatter:
        errors.append(f"{LEVEL_FAIL}: [spec] Missing required 'name' field in frontmatter")
    else:
        name_errors, name_passes = validate_name(frontmatter["name"], dir_name)
        errors.extend(name_errors)
        passes.extend(name_passes)

    if "description" not in frontmatter:
        errors.append(f"{LEVEL_FAIL}: [spec] Missing required 'description' field in frontmatter")
    else:
        desc_errors, desc_passes = validate_description(str(frontmatter["description"]))
        errors.extend(desc_errors)
        passes.extend(desc_passes)

    # Validate optional fields
    if "compatibility" in frontmatter:
        comp = str(frontmatter["compatibility"])
        if len(comp) > MAX_COMPATIBILITY_CHARS:
            errors.append(
                f"{LEVEL_FAIL}: [spec] 'compatibility' exceeds {MAX_COMPATIBILITY_CHARS} characters ({len(comp)} chars)"
            )
        else:
            passes.append(f"compatibility: {len(comp)} chars (max {MAX_COMPATIBILITY_CHARS})")

    if "allowed-tools" in frontmatter:
        tools_errors, tools_passes = validate_allowed_tools(
            frontmatter["allowed-tools"]
        )
        errors.extend(tools_errors)
        passes.extend(tools_passes)

    if "metadata" in frontmatter:
        meta_errors, meta_passes = validate_metadata(frontmatter["metadata"])
        errors.extend(meta_errors)
        passes.extend(meta_passes)

    if "license" in frontmatter:
        license_errors, license_passes = validate_license(
            frontmatter["license"]
        )
        errors.extend(license_errors)
        passes.extend(license_passes)

    # Check for unrecognized frontmatter keys
    key_errors, key_passes = validate_known_keys(frontmatter)
    errors.extend(key_errors)
    passes.extend(key_passes)

    # Validate body
    body_errors, body_passes = validate_body(body, skill_md, skill_root, allow_nested_refs)
    errors.extend(body_errors)
    passes.extend(body_passes)

    # Validate directories
    dir_errors, dir_passes = validate_directories(skill_path)
    errors.extend(dir_errors)
    passes.extend(dir_passes)

    # Validate references in all other .md files in the skill tree
    sref_errors, sref_passes = validate_skill_references(
        skill_path, skill_root, skill_md,
    )
    errors.extend(sref_errors)
    passes.extend(sref_passes)

    # Validate Codex configuration (agents/openai.yaml) when present
    codex_errors, codex_passes = validate_codex_config(skill_path)
    errors.extend(codex_errors)
    passes.extend(codex_passes)

    return errors, passes


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for validate_skill."""
    parser = argparse.ArgumentParser(
        description="Validate a single skill directory against the Agent Skills specification.",
        epilog=(
            "Examples:\n"
            "  python scripts/validate_skill.py skills/project-mgmt\n"
            "  python scripts/validate_skill.py skills/project-mgmt --verbose\n"
            "  python scripts/validate_skill.py skills/project-mgmt --json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "skill_path",
        help="Path to the skill directory to validate.",
    )
    parser.add_argument(
        "--capability",
        action="store_true",
        help="Validate as a capability (uses capability.md instead of SKILL.md).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output including individual passed checks.",
    )
    parser.add_argument(
        "--allow-nested-references",
        action="store_true",
        dest="allow_nested_refs",
        help="Skip nested-reference depth checks.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as machine-readable JSON.",
    )
    return parser


def main() -> None:
    # Pre-check for --json so parse errors can be reported as JSON.
    _json_mode = "--json" in sys.argv

    # Fast-path: no arguments at all → print module docstring (matches
    # the convention used by bundle.py and scaffold.py).
    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(1)

    parser = _build_parser()

    # Override parser.error() to emit JSON on parse failures when
    # --json is present and to always exit with code 1 (not
    # argparse's default 2) to match the repo convention.
    def _json_aware_error(message: str) -> None:
        if _json_mode:
            print(to_json_output({
                "tool": "validate_skill",
                "success": False,
                "error": message,
            }))
            sys.exit(1)
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)

    parser.error = _json_aware_error  # type: ignore[assignment]

    args = parser.parse_args()

    skill_path: str = args.skill_path
    is_capability: bool = args.capability
    verbose: bool = args.verbose
    allow_nested_refs: bool = args.allow_nested_refs
    json_output: bool = args.json_output

    if not os.path.isdir(skill_path):
        if json_output:
            print(to_json_output({
                "tool": "validate_skill",
                "path": os.path.abspath(skill_path),
                "success": False,
                "error": f"'{skill_path}' is not a directory",
            }))
        else:
            print(f"Error: '{skill_path}' is not a directory")
        sys.exit(1)

    errors, passes = validate_skill(skill_path, is_capability, allow_nested_refs)

    if json_output:
        fails, warns, infos = categorize_errors(errors)
        result = {
            "tool": "validate_skill",
            "path": os.path.abspath(skill_path),
            "type": "capability" if is_capability else "registered skill",
            "success": len(fails) == 0,
            "summary": {
                "failures": len(fails),
                "warnings": len(warns),
                "info": len(infos),
                "passes": len(passes),
            },
            "errors": categorize_errors_for_json(errors),
        }
        if verbose:
            result["passes"] = passes
        print(to_json_output(result))
        sys.exit(1 if fails else 0)

    print(f"Validating: {skill_path}")
    print(f"Type: {'capability' if is_capability else 'registered skill'}")
    print("-" * SEPARATOR_WIDTH)

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
