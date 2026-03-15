#!/usr/bin/env python3
"""
Scaffold new skill system components from templates.

Usage:
    python scripts/scaffold.py skill <name> [--router] [--root <path>] [--with-references] [--with-scripts] [--with-assets] [--json]
    python scripts/scaffold.py capability <domain> <name> [--root <path>] [--with-references] [--json]
    python scripts/scaffold.py role <group> <name> [--root <path>] [--json]

Options:
    --root <path>        Base directory for output (default: current working
                         directory). Use --root .agents to scaffold into
                         .agents/skills/, .agents/roles/, etc.
    --with-references    Also create a references/ directory (with .gitkeep)
    --with-scripts       Also create a scripts/ directory (with .gitkeep)
    --with-assets        Also create an assets/ directory (with .gitkeep)
    --json               Output results as machine-readable JSON.

Examples:
    python scripts/scaffold.py skill my-skill
    python scripts/scaffold.py skill my-skill --root .agents
    python scripts/scaffold.py skill my-skill --with-references --with-scripts
    python scripts/scaffold.py skill my-domain --router
    python scripts/scaffold.py capability my-domain my-capability
    python scripts/scaffold.py role my-group my-role
    python scripts/scaffold.py skill my-skill --json
"""

import sys
import os

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.reporting import to_json_output
from lib.validation import validate_name as _validate_name_detailed
from lib.constants import (
    DIR_SKILLS, DIR_CAPABILITIES, DIR_ROLES,
    DIR_REFERENCES, DIR_SCRIPTS, DIR_ASSETS,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, FILE_README, FILE_GITKEEP, FILE_MANIFEST, EXT_MARKDOWN,
    TEMPLATE_SKILL_ROUTER, TEMPLATE_SKILL_STANDALONE,
    TEMPLATE_CAPABILITY, TEMPLATE_ROLE,
    PH_DOMAIN_NAME, PH_DOMAIN_TITLE, PH_SKILL_NAME, PH_SKILL_TITLE,
    PH_CAPABILITY_NAME, PH_CAPABILITY_TITLE,
    PH_ROLE_TITLE,
    LEVEL_FAIL, LEVEL_WARN,
)

# Resolve paths relative to script location
SCRIPT_DIR = _scripts_dir
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")


def validate_name(name: str, json_output: bool = False) -> bool:
    """Validate name follows Agent Skills spec conventions.

    Delegates to validate_skill.validate_name for the actual rules,
    adapting the output to scaffold's print-and-return-bool interface.
    When *json_output* is True, messages are suppressed (the caller
    handles error reporting).
    """
    errors, _ = _validate_name_detailed(name, name)
    if not json_output:
        for e in errors:
            # Strip level prefix only if present, otherwise print full message
            if e.startswith(LEVEL_FAIL + ": "):
                level = "Error"
                message = e[len(LEVEL_FAIL) + 2:]  # +2 for ": "
            elif e.startswith(LEVEL_WARN + ": "):
                level = "Warning"
                message = e[len(LEVEL_WARN) + 2:]  # +2 for ": "
            else:
                # No recognized level prefix - treat as warning and print full message
                level = "Warning"
                message = e
            print(f"{level}: {message}")
    return not any(e.startswith(LEVEL_FAIL) for e in errors)


def read_template(template_name):
    """Read a template file from assets/."""
    template_path = os.path.join(ASSETS_DIR, template_name)
    if not os.path.exists(template_path):
        print(f"{LEVEL_FAIL}: Template not found: {template_path}")
        sys.exit(1)
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str, *, quiet: bool = False) -> None:
    """Write content to a file, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if not quiet:
        print(f"  Created: {path}")


def create_dir_with_gitkeep(path):
    """Create directory with .gitkeep so it tracks in git."""
    os.makedirs(path, exist_ok=True)
    gitkeep = os.path.join(path, FILE_GITKEEP)
    if not os.path.exists(gitkeep):
        with open(gitkeep, "w", encoding="utf-8") as f:
            pass


def scaffold_skill(
    name: str,
    router: bool = False,
    root: str = "",
    optional_dirs: list[str] | None = None,
    json_output: bool = False,
) -> dict | None:
    """Create a new skill directory.

    Args:
        name: Skill name (lowercase + hyphens).
        router: If True, create a router skill with capabilities/.
        root: Base directory for output.
        optional_dirs: List of optional directories to create (e.g.
            references/, scripts/, assets/). Empty by default.
        json_output: If True, suppress terminal output and return a
            result dict instead.

    Returns:
        A result dict when *json_output* is True, otherwise None.
    """
    if optional_dirs is None:
        optional_dirs = []
    if not validate_name(name, json_output=json_output):
        if json_output:
            return {
                "tool": "scaffold",
                "component": "skill",
                "name": name,
                "success": False,
                "error": f"Invalid name: '{name}'",
            }
        sys.exit(1)

    skill_path = os.path.join(root, DIR_SKILLS, name) if root else os.path.join(DIR_SKILLS, name)
    if os.path.exists(skill_path):
        if json_output:
            return {
                "tool": "scaffold",
                "component": "skill",
                "name": name,
                "success": False,
                "error": f"Directory already exists: {skill_path}",
            }
        print(f"{LEVEL_FAIL}: Directory already exists: {skill_path}")
        sys.exit(1)

    created_files: list[str] = []

    if router:
        template = read_template(TEMPLATE_SKILL_ROUTER)
        # Replace placeholders
        title = name.replace("-", " ").title()
        content = template.replace(PH_DOMAIN_NAME, name).replace(
            PH_DOMAIN_TITLE, title
        )
        write_file(os.path.join(skill_path, FILE_SKILL_MD), content, quiet=json_output)
        created_files.append(os.path.join(skill_path, FILE_SKILL_MD))
        create_dir_with_gitkeep(os.path.join(skill_path, DIR_CAPABILITIES))
        created_files.append(os.path.join(skill_path, DIR_CAPABILITIES))
        if not json_output:
            print(f"  Created: {os.path.join(skill_path, DIR_CAPABILITIES)}")
        for d in optional_dirs:
            create_dir_with_gitkeep(os.path.join(skill_path, d))
            created_files.append(os.path.join(skill_path, d))
            if not json_output:
                print(f"  Created: {os.path.join(skill_path, d)}")
        if not json_output:
            print(f"  Note: Add shared/ when 2+ capabilities exist (see directory-structure.md)")
    else:
        template = read_template(TEMPLATE_SKILL_STANDALONE)
        title = name.replace("-", " ").title()
        content = template.replace(PH_SKILL_NAME, name).replace(
            PH_SKILL_TITLE, title
        )
        write_file(os.path.join(skill_path, FILE_SKILL_MD), content, quiet=json_output)
        created_files.append(os.path.join(skill_path, FILE_SKILL_MD))
        for d in optional_dirs:
            create_dir_with_gitkeep(os.path.join(skill_path, d))
            created_files.append(os.path.join(skill_path, d))
            if not json_output:
                print(f"  Created: {os.path.join(skill_path, d)}")

    manifest_path = os.path.join(root, FILE_MANIFEST) if root else FILE_MANIFEST

    if json_output:
        return {
            "tool": "scaffold",
            "component": "skill",
            "name": name,
            "success": True,
            "path": os.path.abspath(skill_path),
            "created": [os.path.abspath(f) for f in created_files],
            "router": router,
        }

    print(f"\n\u2713 Skill '{name}' scaffolded at {skill_path}")
    skill_md_path = os.path.join(skill_path, FILE_SKILL_MD)
    print(f"  Next: edit {skill_md_path} and update {manifest_path}")
    return None


def scaffold_capability(
    domain: str,
    name: str,
    root: str = "",
    optional_dirs: list[str] | None = None,
    json_output: bool = False,
) -> dict | None:
    """Create a new capability under an existing router skill.

    Args:
        domain: Parent router skill name.
        name: Capability name (lowercase + hyphens).
        root: Base directory for output.
        optional_dirs: List of optional directories to create (e.g.
            references/). Empty by default.
        json_output: If True, suppress terminal output and return a
            result dict instead.

    Returns:
        A result dict when *json_output* is True, otherwise None.
    """
    if optional_dirs is None:
        optional_dirs = []
    if not validate_name(domain, json_output=json_output):
        if json_output:
            return {
                "tool": "scaffold",
                "component": "capability",
                "name": name,
                "domain": domain,
                "success": False,
                "error": f"Invalid domain name: '{domain}'",
            }
        sys.exit(1)
    if not validate_name(name, json_output=json_output):
        if json_output:
            return {
                "tool": "scaffold",
                "component": "capability",
                "name": name,
                "domain": domain,
                "success": False,
                "error": f"Invalid name: '{name}'",
            }
        sys.exit(1)

    cap_path = os.path.join(root, DIR_SKILLS, domain, DIR_CAPABILITIES, name) if root else os.path.join(DIR_SKILLS, domain, DIR_CAPABILITIES, name)
    if os.path.exists(cap_path):
        if json_output:
            return {
                "tool": "scaffold",
                "component": "capability",
                "name": name,
                "domain": domain,
                "success": False,
                "error": f"Directory already exists: {cap_path}",
            }
        print(f"{LEVEL_FAIL}: Directory already exists: {cap_path}")
        sys.exit(1)

    router_skill = os.path.join(root, DIR_SKILLS, domain, FILE_SKILL_MD) if root else os.path.join(DIR_SKILLS, domain, FILE_SKILL_MD)
    if not os.path.exists(router_skill):
        if json_output:
            return {
                "tool": "scaffold",
                "component": "capability",
                "name": name,
                "domain": domain,
                "success": False,
                "error": f"Parent skill not found: {router_skill}",
            }
        print(f"{LEVEL_FAIL}: Parent skill not found: {router_skill}")
        sys.exit(1)

    created_files: list[str] = []

    template = read_template(TEMPLATE_CAPABILITY)
    title = name.replace("-", " ").title()
    content = template.replace(PH_CAPABILITY_NAME, name).replace(
        PH_CAPABILITY_TITLE, title
    )
    write_file(os.path.join(cap_path, FILE_CAPABILITY_MD), content, quiet=json_output)
    created_files.append(os.path.join(cap_path, FILE_CAPABILITY_MD))
    for d in optional_dirs:
        create_dir_with_gitkeep(os.path.join(cap_path, d))
        created_files.append(os.path.join(cap_path, d))
        if not json_output:
            print(f"  Created: {os.path.join(cap_path, d)}")

    if json_output:
        return {
            "tool": "scaffold",
            "component": "capability",
            "name": name,
            "domain": domain,
            "success": True,
            "path": os.path.abspath(cap_path),
            "created": [os.path.abspath(f) for f in created_files],
        }

    manifest_path = os.path.join(root, FILE_MANIFEST) if root else FILE_MANIFEST
    print(f"\n\u2713 Capability '{name}' scaffolded at {cap_path}")
    cap_md_path = os.path.join(cap_path, FILE_CAPABILITY_MD)
    print(f"  Next: edit {cap_md_path}")
    print(f"  Next: add capability to {router_skill} routing table")
    print(f"  Next: update {manifest_path}")
    return None


def scaffold_role(
    group: str,
    name: str,
    root: str = "",
    json_output: bool = False,
) -> dict | None:
    """Create a new role file.

    Args:
        group: Role group name (lowercase + hyphens).
        name: Role name (lowercase + hyphens).
        root: Base directory for output.
        json_output: If True, suppress terminal output and return a
            result dict instead.

    Returns:
        A result dict when *json_output* is True, otherwise None.
    """
    if not validate_name(group, json_output=json_output):
        if json_output:
            return {
                "tool": "scaffold",
                "component": "role",
                "name": name,
                "group": group,
                "success": False,
                "error": f"Invalid group name: '{group}'",
            }
        sys.exit(1)
    if not validate_name(name, json_output=json_output):
        if json_output:
            return {
                "tool": "scaffold",
                "component": "role",
                "name": name,
                "group": group,
                "success": False,
                "error": f"Invalid name: '{name}'",
            }
        sys.exit(1)

    role_path = os.path.join(root, DIR_ROLES, group, f"{name}{EXT_MARKDOWN}") if root else os.path.join(DIR_ROLES, group, f"{name}{EXT_MARKDOWN}")
    if os.path.exists(role_path):
        if json_output:
            return {
                "tool": "scaffold",
                "component": "role",
                "name": name,
                "group": group,
                "success": False,
                "error": f"File already exists: {role_path}",
            }
        print(f"{LEVEL_FAIL}: File already exists: {role_path}")
        sys.exit(1)

    created_files: list[str] = []

    template = read_template(TEMPLATE_ROLE)
    title = name.replace("-", " ").title()
    content = template.replace(PH_ROLE_TITLE, title)
    write_file(role_path, content, quiet=json_output)
    created_files.append(role_path)

    # Create top-level roles README if it doesn't exist
    roles_readme = os.path.join(root, DIR_ROLES, FILE_README) if root else os.path.join(DIR_ROLES, FILE_README)
    if not os.path.exists(roles_readme):
        write_file(
            roles_readme,
            "# Roles\n\nOrchestration patterns that compose skills into workflows.\n\n"
            "See subdirectories for role groups.\n",
            quiet=json_output,
        )
        created_files.append(roles_readme)

    # Create group-level README if it doesn't exist
    readme_path = os.path.join(root, DIR_ROLES, group, FILE_README) if root else os.path.join(DIR_ROLES, group, FILE_README)
    if not os.path.exists(readme_path):
        write_file(
            readme_path,
            f"# {group.replace('-', ' ').title()}\n\nRoles:\n- {name}\n",
            quiet=json_output,
        )
        created_files.append(readme_path)

    if json_output:
        return {
            "tool": "scaffold",
            "component": "role",
            "name": name,
            "group": group,
            "success": True,
            "path": os.path.abspath(role_path),
            "created": [os.path.abspath(f) for f in created_files],
        }

    manifest_path = os.path.join(root, FILE_MANIFEST) if root else FILE_MANIFEST
    print(f"\n\u2713 Role '{name}' scaffolded at {role_path}")
    print(f"  Next: edit {role_path}")
    print(f"  Next: update {manifest_path}")
    return None


# Maps --with-* CLI flags to directory constants.
_WITH_FLAG_MAP = {
    "--with-references": DIR_REFERENCES,
    "--with-scripts": DIR_SCRIPTS,
    "--with-assets": DIR_ASSETS,
}

# All flags recognised per component type (excluding --root and --json,
# which are stripped before component dispatch).
_KNOWN_FLAGS = {
    "skill": {"--router", "--with-references", "--with-scripts", "--with-assets"},
    "capability": {"--with-references"},
    "role": set(),
}


def _validate_flags(flags: list[str], component: str, *, json_mode: bool = False) -> None:
    """Validate *flags* against the known set for *component*.

    Exits with an error message listing the unrecognised flags.
    When *json_mode* is ``True`` the error is emitted as a JSON object
    instead of human-readable text.  Duplicates are silently ignored.
    """
    known = _KNOWN_FLAGS.get(component, set())
    unique_flags = list(dict.fromkeys(flags))
    unknown = [f for f in unique_flags if f not in known]
    if unknown:
        if json_mode:
            allowed = ", ".join(sorted(known)) or "(none)"
            print(to_json_output({
                "tool": "scaffold",
                "component": component,
                "success": False,
                "error": (
                    f"Unknown flag(s): {', '.join(unknown)}. "
                    f"Allowed: {allowed}"
                ),
            }))
        else:
            print(
                f"{LEVEL_FAIL}: Unknown flag(s) for '{component}': "
                f"{', '.join(unknown)}"
            )
            print(f"  Allowed: {', '.join(sorted(known)) or '(none)'}")
        sys.exit(1)


def _parse_optional_dirs(flags):
    """Return deduplicated list of optional directory constants from *flags*.

    Call *_validate_flags* first to ensure all flags are recognised.
    """
    with_flags = list(dict.fromkeys(f for f in flags if f in _WITH_FLAG_MAP))
    return [_WITH_FLAG_MAP[f] for f in with_flags]


def main():
    args = sys.argv[:]

    # Parse --root option
    root = ""
    if "--root" in args:
        idx = args.index("--root")
        if idx + 1 >= len(args):
            print(f"{LEVEL_FAIL}: --root requires a path argument")
            sys.exit(1)
        root = args[idx + 1]
        del args[idx : idx + 2]

    # Parse --json flag (strip before component dispatch)
    json_output = "--json" in args
    if json_output:
        args = [a for a in args if a != "--json"]

    if len(args) < 3:
        if json_output:
            print(to_json_output({
                "tool": "scaffold",
                "success": False,
                "error": "Insufficient arguments",
            }))
        else:
            print(__doc__)
        sys.exit(1)

    component = args[1]

    if component == "skill":
        positional = [a for a in args[2:] if not a.startswith("--")]
        flags = [a for a in args[2:] if a.startswith("--")]
        if not positional:
            if json_output:
                print(to_json_output({
                    "tool": "scaffold",
                    "component": "skill",
                    "success": False,
                    "error": "Missing skill name",
                }))
            else:
                print("Usage: python scripts/scaffold.py skill <name> [--router] [--root <path>] [--with-references] [--with-scripts] [--with-assets]")
            sys.exit(1)
        _validate_flags(flags, "skill", json_mode=json_output)
        name = positional[0]
        router = "--router" in flags
        optional_dirs = _parse_optional_dirs(flags)
        result = scaffold_skill(name, router, root, optional_dirs, json_output=json_output)
        if json_output and result is not None:
            print(to_json_output(result))
            sys.exit(0 if result.get("success") else 1)

    elif component == "capability":
        positional = [a for a in args[2:] if not a.startswith("--")]
        flags = [a for a in args[2:] if a.startswith("--")]
        if len(positional) < 2:
            if json_output:
                print(to_json_output({
                    "tool": "scaffold",
                    "component": "capability",
                    "success": False,
                    "error": "Missing domain or capability name",
                }))
            else:
                print("Usage: python scripts/scaffold.py capability <domain> <name> [--root <path>] [--with-references]")
            sys.exit(1)
        _validate_flags(flags, "capability", json_mode=json_output)
        optional_dirs = _parse_optional_dirs(flags)
        result = scaffold_capability(
            positional[0], positional[1], root, optional_dirs,
            json_output=json_output,
        )
        if json_output and result is not None:
            print(to_json_output(result))
            sys.exit(0 if result.get("success") else 1)

    elif component == "role":
        positional = [a for a in args[2:] if not a.startswith("--")]
        flags = [a for a in args[2:] if a.startswith("--")]
        if len(positional) < 2:
            if json_output:
                print(to_json_output({
                    "tool": "scaffold",
                    "component": "role",
                    "success": False,
                    "error": "Missing group or role name",
                }))
            else:
                print("Usage: python scripts/scaffold.py role <group> <name> [--root <path>]")
            sys.exit(1)
        _validate_flags(flags, "role", json_mode=json_output)
        result = scaffold_role(
            positional[0], positional[1], root,
            json_output=json_output,
        )
        if json_output and result is not None:
            print(to_json_output(result))
            sys.exit(0 if result.get("success") else 1)

    else:
        if json_output:
            print(to_json_output({
                "tool": "scaffold",
                "success": False,
                "error": f"Unknown component type: {component}",
            }))
        else:
            print(f"{LEVEL_FAIL}: Unknown component type: {component}")
            print("  Valid types: skill, capability, role")
        sys.exit(1)


if __name__ == "__main__":
    main()
