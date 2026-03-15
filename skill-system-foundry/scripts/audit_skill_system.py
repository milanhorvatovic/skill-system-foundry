#!/usr/bin/env python3
"""
Validate the entire skill system structure for consistency.

Checks: spec compliance, dependency direction, role composition,
manifest consistency, nesting depth, shared resource usage,
capability entry naming, and structural rules.

Usage:
    python scripts/audit_skill_system.py <system-root> [--verbose]
        [--allow-orchestration] [--json]

Options:
    --verbose        Show detailed output for each check.
    --allow-orchestration
                     Downgrade skill→role references from FAIL to WARN.
                     Use when orchestration skills (both paths in
                     architecture-patterns.md) intentionally reference
                     roles.
    --json           Output results as machine-readable JSON.

The <system-root> should contain a skills/ directory with skill
subdirectories. This is the deployed system layout (e.g.,
.agents/ or a standalone system directory), not the distribution
repository root. See references/directory-structure.md for the
expected layout.

If skills/ is missing, the script runs a partial audit and emits a
warning. Use a deployed system root for full audit coverage.

Note: point this at the deployed system root (the directory
containing skills/), not at a specific skill directory or
distribution repository root.

Examples:
    python scripts/audit_skill_system.py /path/to/project/.agents
    python scripts/audit_skill_system.py /path/to/system --verbose
    python scripts/audit_skill_system.py /path/to/system --json
"""

import argparse
import sys
import os

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.frontmatter import load_frontmatter, count_body_lines
from lib.yaml_parser import parse_yaml_subset
from lib.reporting import (
    categorize_errors,
    categorize_errors_for_json,
    print_error_line,
    print_summary,
    to_json_output,
)
from lib.discovery import (
    find_skill_dirs,
    find_roles,
    check_line_count,
    read_file,
)
from lib.constants import (
    DIR_SKILLS, DIR_CAPABILITIES, DIR_SHARED,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, FILE_MANIFEST, EXT_MARKDOWN,
    MAX_BODY_LINES, MAX_DESCRIPTION_CHARS,
    RE_ROLES_REF, RE_SIBLING_CAP_REF,
    RE_SKILL_REF, RE_CAPABILITY_REF, MIN_ROLE_SKILLS,
    SEPARATOR_WIDTH,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
)


def check_upward_references(content, component_type, allow_orchestration=False):
    """Check for references that violate dependency direction.

    Returns a list of (level, message) tuples.
    """
    issues = []

    if component_type == "capability":
        # Capabilities must not reference roles
        if RE_ROLES_REF.search(content):
            issues.append((LEVEL_FAIL, "references roles/ (capabilities must not reference roles)"))
        # Check for sibling capability references
        if RE_SIBLING_CAP_REF.search(content):
            issues.append((LEVEL_FAIL, "may reference sibling capabilities (not allowed)"))

    elif component_type == "skill":
        # Skills must not reference roles (unless orchestration mode)
        if RE_ROLES_REF.search(content):
            if allow_orchestration:
                issues.append((LEVEL_WARN, "references roles/ (allowed — orchestration skill)"))
            else:
                issues.append((LEVEL_FAIL, "references roles/ (skills must not reference roles)"))

    return issues


def check_role_composition(role_path: str) -> tuple[list[tuple[str, str]], int]:
    """Check that a role composes enough unique skills/capabilities.

    Parses the role file to extract skill and capability references
    from the "Skills Used" section (everything between the heading and the next section).

    Returns a tuple of (issues, ref_count) where *issues* is a list
    of ``(level, message)`` tuples and *ref_count* is the number of
    unique skills/capabilities found.  Returns WARN if the role
    references fewer than ``MIN_ROLE_SKILLS`` unique entries.

    Note: this is a best-effort heuristic — it relies on regex
    matching of canonical path patterns inside the "Skills Used"
    section.  Non-standard reference formats may not be detected.
    """
    content = read_file(role_path)

    # Extract the "Skills Used" section (from heading to next ## heading or EOF)
    section_lines: list[str] = []
    in_section = False
    for line in content.splitlines():
        if line.strip().startswith("## Skills Used"):
            in_section = True
            continue
        if in_section and line.strip().startswith("## "):
            break
        if in_section:
            section_lines.append(line)
    skills_section = "\n".join(section_lines)

    # If no Skills Used section found, return a specific warning
    if not in_section:
        return [(
            LEVEL_WARN,
            "missing 'Skills Used' section; cannot determine composition",
        )], 0

    # Collect unique skill/capability references from the section
    refs: set[str] = set()
    for match in RE_SKILL_REF.finditer(skills_section):
        refs.add(match.group(0))
    for match in RE_CAPABILITY_REF.finditer(skills_section):
        refs.add(match.group(0))

    issues: list[tuple[str, str]] = []
    if len(refs) < MIN_ROLE_SKILLS:
        issues.append((
            LEVEL_WARN,
            f"composes {len(refs)} skill(s)/capability(ies) "
            f"(minimum {MIN_ROLE_SKILLS})",
        ))

    return issues, len(refs)


def audit_skill_system(system_root, verbose=True, allow_orchestration=False):
    """Run all skill-system-level validations."""
    errors = []
    system_root = os.path.abspath(system_root)

    skills_dir = os.path.join(system_root, DIR_SKILLS)
    has_skills_dir = os.path.isdir(skills_dir)

    # Discover components
    skills = find_skill_dirs(system_root)
    roles = find_roles(system_root)

    registered_skills = [s for s in skills if s["type"] == "registered"]
    capabilities = [s for s in skills if s["type"] == "capability"]

    if verbose:
        print(f"Found: {len(registered_skills)} skills, {len(capabilities)} capabilities, "
              f"{len(roles)} roles")
        print()

    if not has_skills_dir:
        errors.append(
            f"{LEVEL_WARN}: No {DIR_SKILLS}/ directory under system root — ran partial audit "
            "(distribution-repo mode). Point to deployed system root for full coverage."
        )

    # --- Spec Compliance ---
    if verbose:
        print("== Spec Compliance ==")

    for skill in registered_skills:
        skill_md = os.path.join(skill["path"], FILE_SKILL_MD)
        fm, body = load_frontmatter(skill_md)

        if fm is None:
            errors.append(f"{LEVEL_FAIL}: {skill['name']}/{FILE_SKILL_MD} has no frontmatter")
            continue

        if "name" not in fm:
            errors.append(f"{LEVEL_FAIL}: {skill['name']}/{FILE_SKILL_MD} missing 'name' field")
        elif fm["name"] != skill["name"]:
            errors.append(
                f"{LEVEL_FAIL}: {skill['name']}/{FILE_SKILL_MD} 'name' ({fm['name']}) "
                f"doesn't match directory"
            )

        if "description" not in fm:
            errors.append(
                f"{LEVEL_FAIL}: {skill['name']}/{FILE_SKILL_MD} missing 'description' field"
            )
        elif len(str(fm["description"])) > MAX_DESCRIPTION_CHARS:
            errors.append(
                f"{LEVEL_FAIL}: {skill['name']}/{FILE_SKILL_MD} description exceeds {MAX_DESCRIPTION_CHARS} chars"
            )

        body_lines = count_body_lines(body)
        if body_lines > MAX_BODY_LINES:
            errors.append(
                f"{LEVEL_WARN}: {skill['name']}/{FILE_SKILL_MD} body is {body_lines} lines (max {MAX_BODY_LINES})"
            )
        elif verbose:
            print(f"  \u2713 {skill['name']}: spec compliant ({body_lines} body lines)")

    # --- Capabilities should not be registered ---
    if verbose:
        print("\n== Capability Isolation ==")

    for cap in capabilities:
        cap_md = os.path.join(cap["path"], FILE_CAPABILITY_MD)
        fm, _ = load_frontmatter(cap_md)
        if fm and "name" in fm and "description" in fm:
            errors.append(
                f"{LEVEL_INFO}: {cap['parent']}/capabilities/{cap['name']} has full "
                f"frontmatter — verify it's not registered in discovery"
            )
        elif verbose:
            print(f"  \u2713 {cap['parent']}/{cap['name']}: not registered")

    # --- Dependency Direction ---
    if verbose:
        print("\n== Dependency Direction ==")

    for cap in capabilities:
        content = read_file(os.path.join(cap["path"], FILE_CAPABILITY_MD))
        issues = check_upward_references(content, "capability")
        for level, issue in issues:
            errors.append(
                f"{level}: {cap['parent']}/capabilities/{cap['name']} {issue}"
            )
        if not issues and verbose:
            print(f"  \u2713 {cap['parent']}/{cap['name']}: no upward references")

    for skill in registered_skills:
        content = read_file(os.path.join(skill["path"], FILE_SKILL_MD))
        issues = check_upward_references(content, "skill", allow_orchestration=allow_orchestration)
        for level, issue in issues:
            errors.append(f"{level}: {skill['name']} {issue}")
        if not issues and verbose:
            print(f"  \u2713 {skill['name']}: no upward references")

    # --- Role Composition ---
    if verbose:
        print("\n== Role Composition ==")

    for role in roles:
        issues, ref_count = check_role_composition(role["path"])
        for level, issue in issues:
            errors.append(f"{level}: {role['group']}/{role['name']} {issue}")
        if not issues and verbose:
            print(
                f"  ✓ {role['group']}/{role['name']}: "
                f"composes {ref_count} skills/capabilities"
            )

    # --- Nesting Depth ---
    if verbose:
        print("\n== Nesting Depth ==")

    for cap in capabilities:
        # Check if capability has sub-capabilities
        sub_cap_dir = os.path.join(cap["path"], DIR_CAPABILITIES)
        if os.path.isdir(sub_cap_dir):
            errors.append(
                f"{LEVEL_FAIL}: {cap['parent']}/capabilities/{cap['name']} has nested "
                f"capabilities/ (max 2 levels: router \u2192 capability)"
            )
        elif verbose:
            print(f"  \u2713 {cap['parent']}/{cap['name']}: no nested capabilities")

    # --- Shared Resources ---
    if verbose:
        print("\n== Shared Resources ==")

    for skill in registered_skills:
        shared_dir = os.path.join(skill["path"], DIR_SHARED)
        if not os.path.isdir(shared_dir):
            continue

        # Walk shared files and check if they're referenced by 2+ capabilities
        cap_dir = os.path.join(skill["path"], DIR_CAPABILITIES)
        if not os.path.isdir(cap_dir):
            errors.append(
                f"{LEVEL_WARN}: {skill['name']} has shared/ but no capabilities/"
            )
            continue

        cap_contents = {}
        for cap in os.listdir(cap_dir):
            cap_skill = os.path.join(cap_dir, cap, FILE_CAPABILITY_MD)
            if os.path.exists(cap_skill):
                cap_contents[cap] = read_file(cap_skill)

        for root, _, files in os.walk(shared_dir):
            for f in files:
                shared_file = os.path.relpath(
                    os.path.join(root, f), skill["path"]
                )
                users = [c for c, content in cap_contents.items()
                         if shared_file in content or f in content]
                if len(users) < 2:
                    errors.append(
                        f"{LEVEL_WARN}: {skill['name']}/{shared_file} used by "
                        f"{len(users)} capabilities (shared should be 2+)"
                    )

    # --- Capability Entry Naming ---
    if verbose:
        print("\n== Capability Entry Naming ==")

    for skill in registered_skills:
        cap_dir = os.path.join(skill["path"], DIR_CAPABILITIES)
        if not os.path.isdir(cap_dir):
            continue

        for cap in os.listdir(cap_dir):
            cap_path = os.path.join(cap_dir, cap)
            if not os.path.isdir(cap_path):
                continue

            capability_md = os.path.join(cap_path, FILE_CAPABILITY_MD)
            legacy_skill_md = os.path.join(cap_path, FILE_SKILL_MD)

            if os.path.exists(legacy_skill_md):
                errors.append(
                    f"{LEVEL_FAIL}: {skill['name']}/capabilities/{cap}/{FILE_SKILL_MD} "
                    f"found (capabilities must use {FILE_CAPABILITY_MD})"
                )
            elif not os.path.exists(capability_md):
                errors.append(
                    f"{LEVEL_WARN}: {skill['name']}/capabilities/{cap}/ has no "
                    f"{FILE_CAPABILITY_MD} entry file"
                )
            elif verbose:
                print(
                    f"  ✓ {skill['name']}/capabilities/{cap}/{FILE_CAPABILITY_MD}"
                )

    # --- Manifest ---
    if verbose:
        print("\n== Manifest ==")

    if not has_skills_dir:
        # No skills/ directory — this is a distribution repo, not a deployed
        # skill system.  Manifest check is not applicable.
        if verbose:
            print("  - skipped (no skills/ directory \u2014 not a deployed skill system)")
    else:
        manifest_path = os.path.join(system_root, FILE_MANIFEST)
        if not os.path.exists(manifest_path):
            errors.append(f"{LEVEL_WARN}: No {FILE_MANIFEST} found at system root")
        else:
            if verbose:
                print(f"  \u2713 {FILE_MANIFEST} exists")
            try:
                manifest = parse_yaml_subset(read_file(manifest_path))
                if manifest and isinstance(manifest.get("skills"), dict):
                    for skill_name, skill_def in manifest["skills"].items():
                        skill_dir = os.path.join(
                            system_root, DIR_SKILLS, skill_name
                        )
                        if not os.path.isdir(skill_dir):
                            errors.append(
                                f"{LEVEL_WARN}: manifest declares skill '{skill_name}' "
                                f"but {skill_dir} does not exist"
                            )
                        elif isinstance(skill_def, dict) and isinstance(
                            skill_def.get("capabilities"), list
                        ):
                            for cap_name in skill_def["capabilities"]:
                                cap_dir = os.path.join(
                                    skill_dir, DIR_CAPABILITIES, str(cap_name)
                                )
                                if not os.path.isdir(cap_dir):
                                    errors.append(
                                        f"{LEVEL_WARN}: manifest declares capability "
                                        f"'{cap_name}' under '{skill_name}' "
                                        f"but {cap_dir} does not exist"
                                    )
                    if verbose:
                        print(f"  \u2713 {FILE_MANIFEST} content validated")
                elif verbose:
                    print(
                        f"  \u2713 {FILE_MANIFEST} exists "
                        f"(no skills section to validate)"
                    )
            except Exception as e:
                errors.append(f"{LEVEL_WARN}: Failed to parse {FILE_MANIFEST}: {e}")

    return errors


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for audit_skill_system."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate the entire skill system structure for consistency. "
            "Checks spec compliance, dependency direction, role composition, "
            "manifest consistency, nesting depth, shared resource usage, "
            "capability entry naming, and structural rules."
        ),
        epilog=(
            "Examples:\n"
            "  python scripts/audit_skill_system.py /path/to/project/.agents\n"
            "  python scripts/audit_skill_system.py /path/to/system --verbose\n"
            "  python scripts/audit_skill_system.py /path/to/system --json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "system_root",
        help=(
            "Path to the skill system root (contains skills/, roles/). "
            "This is the deployed system layout, not the distribution "
            "repository root."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output for each check.",
    )
    parser.add_argument(
        "--allow-orchestration",
        action="store_true",
        dest="allow_orchestration",
        help=(
            "Downgrade skill→role references from FAIL to WARN. "
            "Use when orchestration skills intentionally reference roles."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as machine-readable JSON.",
    )
    return parser


def main():
    # Pre-check for --json so parse errors can be reported as JSON.
    _json_mode = "--json" in sys.argv

    parser = _build_parser()

    # Override parser.error() to emit JSON on parse failures when
    # --json is present (argparse normally prints to stderr and exits).
    _original_error = parser.error

    def _json_aware_error(message: str) -> None:
        if _json_mode:
            print(to_json_output({
                "tool": "audit_skill_system",
                "success": False,
                "error": message,
            }))
            sys.exit(1)
        # Print usage and error to stderr, then exit with code 1
        # (not argparse's default 2) to match the repo convention.
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)

    parser.error = _json_aware_error  # type: ignore[assignment]

    args = parser.parse_args()

    system_root: str = args.system_root
    verbose: bool = args.verbose
    allow_orchestration: bool = args.allow_orchestration
    json_output: bool = args.json_output

    if not os.path.isdir(system_root):
        if json_output:
            print(to_json_output({
                "tool": "audit_skill_system",
                "path": system_root,
                "success": False,
                "error": f"'{system_root}' is not a directory",
            }))
        else:
            print(f"Error: '{system_root}' is not a directory")
        sys.exit(1)

    # When --json is active, suppress verbose terminal output from
    # audit_skill_system so only the JSON blob is printed.
    effective_verbose = verbose and not json_output

    if not json_output:
        print(f"Auditing skill system: {system_root}")
        if allow_orchestration:
            print("Orchestration mode: skill\u2192role references downgraded to WARN")
        if verbose:
            print("=" * SEPARATOR_WIDTH)

    errors = audit_skill_system(
        system_root, verbose=effective_verbose,
        allow_orchestration=allow_orchestration,
    )

    if json_output:
        # Discover component counts for the JSON summary.
        # This duplicates the discovery inside audit_skill_system() but
        # avoids changing that function's return type.
        abs_root = os.path.abspath(system_root)
        all_skills = find_skill_dirs(abs_root)
        all_roles = find_roles(abs_root)
        registered = [s for s in all_skills if s["type"] == "registered"]
        caps = [s for s in all_skills if s["type"] == "capability"]

        fails, warns, infos = categorize_errors(errors)
        result = {
            "tool": "audit_skill_system",
            "path": abs_root,
            "success": len(fails) == 0,
            "counts": {
                "skills": len(registered),
                "capabilities": len(caps),
                "roles": len(all_roles),
            },
            "summary": {
                "failures": len(fails),
                "warnings": len(warns),
                "info": len(infos),
            },
            "errors": categorize_errors_for_json(errors),
        }
        print(to_json_output(result))
        sys.exit(1 if fails else 0)

    if verbose:
        print("\n" + "=" * SEPARATOR_WIDTH)

    if not errors:
        print("\u2713 All checks passed")
        sys.exit(0)

    fails, warns, infos = categorize_errors(errors)

    print("\nIssues found:")
    for error in errors:
        print_error_line(error)

    print_summary(fails, warns, infos)

    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
