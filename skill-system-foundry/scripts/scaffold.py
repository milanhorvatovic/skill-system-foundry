#!/usr/bin/env python3
"""
Scaffold new skill system components from templates.

Usage:
    python scripts/scaffold.py skill <name> [--router] [--root <path>]
    python scripts/scaffold.py capability <domain> <name> [--root <path>]
    python scripts/scaffold.py role <group> <name> [--root <path>]

Options:
    --root <path>   Base directory for output (default: current working
                    directory). Use --root .agents to scaffold into
                    .agents/skills/, .agents/roles/, etc.

Examples:
    python scripts/scaffold.py skill my-skill
    python scripts/scaffold.py skill my-skill --root .agents
    python scripts/scaffold.py skill my-domain --router
    python scripts/scaffold.py capability my-domain my-capability
    python scripts/scaffold.py role my-group my-role
"""

import sys
import os

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

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


def validate_name(name):
    """Validate name follows Agent Skills spec conventions.

    Delegates to validate_skill.validate_name for the actual rules,
    adapting the output to scaffold's print-and-return-bool interface.
    """
    errors, _ = _validate_name_detailed(name, name)
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


def write_file(path, content):
    """Write content to a file, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Created: {path}")


def create_dir_with_gitkeep(path):
    """Create directory with .gitkeep so it tracks in git."""
    os.makedirs(path, exist_ok=True)
    gitkeep = os.path.join(path, FILE_GITKEEP)
    if not os.path.exists(gitkeep):
        with open(gitkeep, "w", encoding="utf-8") as f:
            pass


def scaffold_skill(name, router=False, root=""):
    """Create a new skill directory."""
    if not validate_name(name):
        sys.exit(1)

    skill_path = os.path.join(root, DIR_SKILLS, name) if root else os.path.join(DIR_SKILLS, name)
    if os.path.exists(skill_path):
        print(f"{LEVEL_FAIL}: Directory already exists: {skill_path}")
        sys.exit(1)

    if router:
        template = read_template(TEMPLATE_SKILL_ROUTER)
        # Replace placeholders
        title = name.replace("-", " ").title()
        content = template.replace(PH_DOMAIN_NAME, name).replace(
            PH_DOMAIN_TITLE, title
        )
        write_file(os.path.join(skill_path, FILE_SKILL_MD), content)
        create_dir_with_gitkeep(os.path.join(skill_path, DIR_CAPABILITIES))
        create_dir_with_gitkeep(os.path.join(skill_path, DIR_REFERENCES))
        create_dir_with_gitkeep(os.path.join(skill_path, DIR_SCRIPTS))
        create_dir_with_gitkeep(os.path.join(skill_path, DIR_ASSETS))
        print(f"  Created: {os.path.join(skill_path, DIR_CAPABILITIES)}")
        print(f"  Created: {os.path.join(skill_path, DIR_REFERENCES)}")
        print(f"  Created: {os.path.join(skill_path, DIR_SCRIPTS)}")
        print(f"  Created: {os.path.join(skill_path, DIR_ASSETS)}")
        print(f"  Note: Add shared/ when 2+ capabilities exist (see directory-structure.md)")
    else:
        template = read_template(TEMPLATE_SKILL_STANDALONE)
        title = name.replace("-", " ").title()
        content = template.replace(PH_SKILL_NAME, name).replace(
            PH_SKILL_TITLE, title
        )
        write_file(os.path.join(skill_path, FILE_SKILL_MD), content)
        create_dir_with_gitkeep(os.path.join(skill_path, DIR_REFERENCES))
        create_dir_with_gitkeep(os.path.join(skill_path, DIR_SCRIPTS))
        create_dir_with_gitkeep(os.path.join(skill_path, DIR_ASSETS))
        print(f"  Created: {os.path.join(skill_path, DIR_REFERENCES)}")
        print(f"  Created: {os.path.join(skill_path, DIR_SCRIPTS)}")
        print(f"  Created: {os.path.join(skill_path, DIR_ASSETS)}")

    manifest_path = os.path.join(root, FILE_MANIFEST) if root else FILE_MANIFEST
    print(f"\n\u2713 Skill '{name}' scaffolded at {skill_path}")
    skill_md_path = os.path.join(skill_path, FILE_SKILL_MD)
    print(f"  Next: edit {skill_md_path} and update {manifest_path}")


def scaffold_capability(domain, name, root=""):
    """Create a new capability under an existing router skill."""
    if not validate_name(domain):
        sys.exit(1)
    if not validate_name(name):
        sys.exit(1)

    cap_path = os.path.join(root, DIR_SKILLS, domain, DIR_CAPABILITIES, name) if root else os.path.join(DIR_SKILLS, domain, DIR_CAPABILITIES, name)
    if os.path.exists(cap_path):
        print(f"{LEVEL_FAIL}: Directory already exists: {cap_path}")
        sys.exit(1)

    router_skill = os.path.join(root, DIR_SKILLS, domain, FILE_SKILL_MD) if root else os.path.join(DIR_SKILLS, domain, FILE_SKILL_MD)
    if not os.path.exists(router_skill):
        print(f"{LEVEL_FAIL}: Parent skill not found: {router_skill}")
        sys.exit(1)

    template = read_template(TEMPLATE_CAPABILITY)
    title = name.replace("-", " ").title()
    content = template.replace(PH_CAPABILITY_NAME, name).replace(
        PH_CAPABILITY_TITLE, title
    )
    write_file(os.path.join(cap_path, FILE_CAPABILITY_MD), content)
    create_dir_with_gitkeep(os.path.join(cap_path, DIR_REFERENCES))
    print(f"  Created: {os.path.join(cap_path, DIR_REFERENCES)}")

    manifest_path = os.path.join(root, FILE_MANIFEST) if root else FILE_MANIFEST
    print(f"\n\u2713 Capability '{name}' scaffolded at {cap_path}")
    cap_md_path = os.path.join(cap_path, FILE_CAPABILITY_MD)
    print(f"  Next: edit {cap_md_path}")
    print(f"  Next: add capability to {router_skill} routing table")
    print(f"  Next: update {manifest_path}")


def scaffold_role(group, name, root=""):
    """Create a new role file."""
    if not validate_name(group):
        sys.exit(1)
    if not validate_name(name):
        sys.exit(1)

    role_path = os.path.join(root, DIR_ROLES, group, f"{name}{EXT_MARKDOWN}") if root else os.path.join(DIR_ROLES, group, f"{name}{EXT_MARKDOWN}")
    if os.path.exists(role_path):
        print(f"{LEVEL_FAIL}: File already exists: {role_path}")
        sys.exit(1)

    template = read_template(TEMPLATE_ROLE)
    title = name.replace("-", " ").title()
    content = template.replace(PH_ROLE_TITLE, title)
    write_file(role_path, content)

    # Create top-level roles README if it doesn't exist
    roles_readme = os.path.join(root, DIR_ROLES, FILE_README) if root else os.path.join(DIR_ROLES, FILE_README)
    if not os.path.exists(roles_readme):
        write_file(
            roles_readme,
            "# Roles\n\nOrchestration patterns that compose skills into workflows.\n\n"
            "See subdirectories for role groups.\n",
        )

    # Create group-level README if it doesn't exist
    readme_path = os.path.join(root, DIR_ROLES, group, FILE_README) if root else os.path.join(DIR_ROLES, group, FILE_README)
    if not os.path.exists(readme_path):
        write_file(readme_path, f"# {group.replace('-', ' ').title()}\n\nRoles:\n- {name}\n")

    manifest_path = os.path.join(root, FILE_MANIFEST) if root else FILE_MANIFEST
    print(f"\n\u2713 Role '{name}' scaffolded at {role_path}")
    print(f"  Next: edit {role_path}")
    print(f"  Next: update {manifest_path}")


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

    if len(args) < 3:
        print(__doc__)
        sys.exit(1)

    component = args[1]

    if component == "skill":
        positional = [a for a in args[2:] if not a.startswith("--")]
        flags = [a for a in args[2:] if a.startswith("--")]
        if not positional:
            print("Usage: python scaffold.py skill <name> [--router]")
            sys.exit(1)
        name = positional[0]
        router = "--router" in flags
        scaffold_skill(name, router, root)

    elif component == "capability":
        if len(args) < 4:
            print("Usage: python scaffold.py capability <domain> <name>")
            sys.exit(1)
        scaffold_capability(args[2], args[3], root)

    elif component == "role":
        if len(args) < 4:
            print("Usage: python scaffold.py role <group> <name>")
            sys.exit(1)
        scaffold_role(args[2], args[3], root)

    else:
        print(f"Unknown component type: {component}")
        print("Valid types: skill, capability, role")
        sys.exit(1)


if __name__ == "__main__":
    main()
