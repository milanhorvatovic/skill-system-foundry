#!/usr/bin/env python3
"""
Scaffold new skill system components from templates.

Usage:
    python scripts/scaffold.py skill <name> [--router] [--root <path>] [--with-references] [--with-scripts] [--with-assets] [--update-manifest] [--json]
    python scripts/scaffold.py capability <domain> <name> [--root <path>] [--with-references] [--update-manifest] [--json]
    python scripts/scaffold.py role <group> <name> [--root <path>] [--update-manifest] [--json]

Options:
    --root <path>        Base directory for output (default: current working
                         directory). Use --root .agents to scaffold into
                         .agents/skills/, .agents/roles/, etc.
    --with-references    Also create a references/ directory (with .gitkeep)
    --with-scripts       Also create a scripts/ directory (with .gitkeep)
    --with-assets        Also create an assets/ directory (with .gitkeep)
    --update-manifest    For skills and roles: validate and append to manifest.yaml.
                         For capabilities: print guidance (capabilities are added
                         to the parent skill's capabilities list, not directly
                         to manifest.yaml). Creates a minimal manifest if none
                         exists. Detects name conflicts and warns without overwriting.
    --json               Output results as machine-readable JSON.

Examples:
    python scripts/scaffold.py skill my-skill
    python scripts/scaffold.py skill my-skill --root .agents
    python scripts/scaffold.py skill my-skill --with-references --with-scripts
    python scripts/scaffold.py skill my-domain --router
    python scripts/scaffold.py skill my-skill --update-manifest
    python scripts/scaffold.py capability my-domain my-capability
    python scripts/scaffold.py role my-group my-role
    python scripts/scaffold.py skill my-skill --json
"""

import sys
import os

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.frontmatter import load_frontmatter
from lib.reporting import to_json_output
from lib.validation import validate_name as _validate_name_detailed
from lib.manifest import (
    update_manifest_for_skill,
    update_manifest_for_role,
)
from lib.constants import (
    DIR_SKILLS, DIR_CAPABILITIES, DIR_ROLES,
    DIR_REFERENCES, DIR_SCRIPTS, DIR_ASSETS,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, FILE_README, FILE_GITKEEP, FILE_MANIFEST, EXT_MARKDOWN,
    TEMPLATE_SKILL_ROUTER, TEMPLATE_SKILL_STANDALONE,
    TEMPLATE_CAPABILITY, TEMPLATE_ROLE,
    PH_DOMAIN_NAME, PH_DOMAIN_TITLE, PH_SKILL_NAME, PH_SKILL_TITLE,
    PH_CAPABILITY_NAME, PH_CAPABILITY_TITLE,
    PH_ROLE_TITLE,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
)

# Resolve paths relative to script location
SCRIPT_DIR = _scripts_dir
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")


def _name_validation_details(name: str) -> list[str]:
    """Return human-readable validation failure messages for *name*."""
    errors, _ = _validate_name_detailed(name, name)
    strip = {
        LEVEL_FAIL: len(LEVEL_FAIL) + 2,
        LEVEL_WARN: len(LEVEL_WARN) + 2,
        LEVEL_INFO: len(LEVEL_INFO) + 2,
    }
    return [
        e[strip.get(e.split(":")[0], 0):] if ":" in e else e
        for e in errors
    ]


def validate_name(name: str, json_output: bool = False) -> bool:
    """Validate name follows Agent Skills spec conventions.

    Delegates to lib.validation.validate_name for the actual rules,
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


def _collect_frontmatter_findings(path: str) -> list[str]:
    """Return plain-scalar divergence findings from the written entry file.

    Re-parses the rendered frontmatter so post-write divergences surface
    even when they would otherwise bypass validate_name's gate (template
    changes, programmatic callers, etc.).  Missing files and files
    without frontmatter yield an empty list.
    """
    if not os.path.isfile(path):
        return []
    _fm, _body, findings = load_frontmatter(path)
    return findings


def read_template(template_name: str) -> str:
    """Read a template file from assets/."""
    template_path = os.path.join(ASSETS_DIR, template_name)
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found: {template_path}")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str, *, quiet: bool = False) -> None:
    """Write content to a file, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if not quiet:
        print(f"  Created: {path}")


def create_dir_with_gitkeep(path: str) -> str:
    """Create directory with .gitkeep so it tracks in git.

    Returns:
        The path to the ``.gitkeep`` file (relative or absolute,
        matching the input *path*).
    """
    os.makedirs(path, exist_ok=True)
    gitkeep = os.path.join(path, FILE_GITKEEP)
    if not os.path.exists(gitkeep):
        with open(gitkeep, "w", encoding="utf-8") as f:
            pass
    return gitkeep


def scaffold_skill(
    name: str,
    router: bool = False,
    root: str = "",
    optional_dirs: list[str] | None = None,
    json_output: bool = False,
    update_manifest: bool = False,
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
        update_manifest: If True, validate and update manifest.yaml
            after scaffolding.

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
                "details": _name_validation_details(name),
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

    # Tracks created filesystem entries: content files (e.g. SKILL.md),
    # optional directories, and their .gitkeep sentinel files.
    # Exposed as the ``"created"`` list in JSON output.
    created_paths: list[str] = []

    if router:
        try:
            template = read_template(TEMPLATE_SKILL_ROUTER)
        except FileNotFoundError as e:
            if json_output:
                return {
                    "tool": "scaffold",
                    "component": "skill",
                    "name": name,
                    "success": False,
                    "error": str(e),
                }
            print(f"{LEVEL_FAIL}: {e}")
            sys.exit(1)
        # Replace placeholders
        title = name.replace("-", " ").title()
        content = template.replace(PH_DOMAIN_NAME, name).replace(
            PH_DOMAIN_TITLE, title
        )
        write_file(os.path.join(skill_path, FILE_SKILL_MD), content, quiet=json_output)
        created_paths.append(os.path.join(skill_path, FILE_SKILL_MD))
        caps_dir = os.path.join(skill_path, DIR_CAPABILITIES)
        gitkeep = create_dir_with_gitkeep(caps_dir)
        created_paths.append(caps_dir)
        created_paths.append(gitkeep)
        if not json_output:
            print(f"  Created: {caps_dir}")
        for d in optional_dirs:
            opt_dir = os.path.join(skill_path, d)
            gitkeep = create_dir_with_gitkeep(opt_dir)
            created_paths.append(opt_dir)
            created_paths.append(gitkeep)
            if not json_output:
                print(f"  Created: {opt_dir}")
        if not json_output:
            print(f"  Note: Add shared/ when 2+ capabilities exist (see directory-structure.md)")
    else:
        try:
            template = read_template(TEMPLATE_SKILL_STANDALONE)
        except FileNotFoundError as e:
            if json_output:
                return {
                    "tool": "scaffold",
                    "component": "skill",
                    "name": name,
                    "success": False,
                    "error": str(e),
                }
            print(f"{LEVEL_FAIL}: {e}")
            sys.exit(1)
        title = name.replace("-", " ").title()
        content = template.replace(PH_SKILL_NAME, name).replace(
            PH_SKILL_TITLE, title
        )
        write_file(os.path.join(skill_path, FILE_SKILL_MD), content, quiet=json_output)
        created_paths.append(os.path.join(skill_path, FILE_SKILL_MD))
        for d in optional_dirs:
            opt_dir = os.path.join(skill_path, d)
            gitkeep = create_dir_with_gitkeep(opt_dir)
            created_paths.append(opt_dir)
            created_paths.append(gitkeep)
            if not json_output:
                print(f"  Created: {opt_dir}")

    manifest_path = os.path.join(root, FILE_MANIFEST) if root else FILE_MANIFEST

    # --- Frontmatter re-parse of the written entry file ---
    skill_md_full_path = os.path.join(skill_path, FILE_SKILL_MD)
    frontmatter_findings = _collect_frontmatter_findings(skill_md_full_path)
    if frontmatter_findings and not json_output:
        for f in frontmatter_findings:
            print(f"  {f}")

    # --- Manifest update ---
    manifest_updated = False
    manifest_warning: str | None = None
    manifest_findings: list[str] = []

    if update_manifest:
        (
            manifest_updated,
            manifest_warning,
            created_manifest,
            manifest_findings,
        ) = update_manifest_for_skill(
            manifest_path, name, router=router,
        )
        if created_manifest and not json_output:
            print(f"  Created: {manifest_path}")
        if created_manifest:
            created_paths.append(manifest_path)
        if manifest_warning and not json_output:
            print(f"  {LEVEL_WARN}: {manifest_warning}")
        if manifest_updated and not json_output:
            print(f"  Updated: {manifest_path}")
        if manifest_findings and not json_output:
            for f in manifest_findings:
                print(f"  {f}")

    if json_output:
        result_dict: dict = {
            "tool": "scaffold",
            "component": "skill",
            "name": name,
            "success": True,
            "path": os.path.abspath(skill_path),
            "created": [os.path.abspath(p) for p in created_paths],
            "router": router,
        }
        if frontmatter_findings:
            result_dict["frontmatter_findings"] = frontmatter_findings
        if update_manifest:
            result_dict["manifest_updated"] = manifest_updated
            if manifest_warning:
                result_dict["manifest_warning"] = manifest_warning
            if manifest_findings:
                result_dict["manifest_findings"] = manifest_findings
        return result_dict

    print(f"\n\u2713 Skill '{name}' scaffolded at {skill_path}")
    skill_md_path = os.path.join(skill_path, FILE_SKILL_MD)
    if not update_manifest:
        print(f"  Next: edit {skill_md_path} and update {manifest_path}")
    else:
        print(f"  Next: edit {skill_md_path}")
    return None


def scaffold_capability(
    domain: str,
    name: str,
    root: str = "",
    optional_dirs: list[str] | None = None,
    json_output: bool = False,
    update_manifest: bool = False,
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
        update_manifest: If True, print a message that capabilities
            should be added to the parent skill's manifest entry.

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
                "details": _name_validation_details(domain),
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
                "details": _name_validation_details(name),
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

    # Tracks created filesystem entries: content files (e.g.
    # capability.md), optional directories, and their .gitkeep files.
    created_paths: list[str] = []

    try:
        template = read_template(TEMPLATE_CAPABILITY)
    except FileNotFoundError as e:
        if json_output:
            return {
                "tool": "scaffold",
                "component": "capability",
                "name": name,
                "domain": domain,
                "success": False,
                "error": str(e),
            }
        print(f"{LEVEL_FAIL}: {e}")
        sys.exit(1)
    title = name.replace("-", " ").title()
    content = template.replace(PH_CAPABILITY_NAME, name).replace(
        PH_CAPABILITY_TITLE, title
    )
    write_file(os.path.join(cap_path, FILE_CAPABILITY_MD), content, quiet=json_output)
    created_paths.append(os.path.join(cap_path, FILE_CAPABILITY_MD))
    for d in optional_dirs:
        opt_dir = os.path.join(cap_path, d)
        gitkeep = create_dir_with_gitkeep(opt_dir)
        created_paths.append(opt_dir)
        created_paths.append(gitkeep)
        if not json_output:
            print(f"  Created: {opt_dir}")

    manifest_path = os.path.join(root, FILE_MANIFEST) if root else FILE_MANIFEST

    # --- Frontmatter re-parse of the written entry file ---
    cap_md_full_path = os.path.join(cap_path, FILE_CAPABILITY_MD)
    frontmatter_findings = _collect_frontmatter_findings(cap_md_full_path)
    if frontmatter_findings and not json_output:
        for f in frontmatter_findings:
            print(f"  {f}")

    # Capabilities are not added to the manifest directly — they
    # belong under their parent skill's ``capabilities:`` list.
    cap_manifest_msg = (
        f"Capabilities are not added to manifest.yaml directly. "
        f"Add '{name}' to the capabilities list of '{domain}' in {manifest_path}."
    )

    if json_output:
        result_dict: dict = {
            "tool": "scaffold",
            "component": "capability",
            "name": name,
            "domain": domain,
            "success": True,
            "path": os.path.abspath(cap_path),
            "created": [os.path.abspath(p) for p in created_paths],
        }
        if frontmatter_findings:
            result_dict["frontmatter_findings"] = frontmatter_findings
        if update_manifest:
            result_dict["manifest_updated"] = False
            result_dict["manifest_warning"] = cap_manifest_msg
        return result_dict

    print(f"\n\u2713 Capability '{name}' scaffolded at {cap_path}")
    cap_md_path = os.path.join(cap_path, FILE_CAPABILITY_MD)
    print(f"  Next: edit {cap_md_path}")
    print(f"  Next: add capability to {router_skill} routing table")
    if update_manifest:
        print(f"  {LEVEL_INFO}: {cap_manifest_msg}")
    else:
        print(f"  Next: update {manifest_path}")
    return None


def scaffold_role(
    group: str,
    name: str,
    root: str = "",
    json_output: bool = False,
    update_manifest: bool = False,
) -> dict | None:
    """Create a new role file.

    Args:
        group: Role group name (lowercase + hyphens).
        name: Role name (lowercase + hyphens).
        root: Base directory for output.
        json_output: If True, suppress terminal output and return a
            result dict instead.
        update_manifest: If True, validate and update manifest.yaml
            after scaffolding.

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
                "details": _name_validation_details(group),
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
                "details": _name_validation_details(name),
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

    # Tracks all filesystem entries created (files only for roles).
    created_paths: list[str] = []

    try:
        template = read_template(TEMPLATE_ROLE)
    except FileNotFoundError as e:
        if json_output:
            return {
                "tool": "scaffold",
                "component": "role",
                "name": name,
                "group": group,
                "success": False,
                "error": str(e),
            }
        print(f"{LEVEL_FAIL}: {e}")
        sys.exit(1)
    title = name.replace("-", " ").title()
    content = template.replace(PH_ROLE_TITLE, title)
    write_file(role_path, content, quiet=json_output)
    created_paths.append(role_path)

    # Create top-level roles README if it doesn't exist
    roles_readme = os.path.join(root, DIR_ROLES, FILE_README) if root else os.path.join(DIR_ROLES, FILE_README)
    if not os.path.exists(roles_readme):
        write_file(
            roles_readme,
            "# Roles\n\nOrchestration patterns that compose skills into workflows.\n\n"
            "See subdirectories for role groups.\n",
            quiet=json_output,
        )
        created_paths.append(roles_readme)

    # Create group-level README if it doesn't exist
    readme_path = os.path.join(root, DIR_ROLES, group, FILE_README) if root else os.path.join(DIR_ROLES, group, FILE_README)
    if not os.path.exists(readme_path):
        write_file(
            readme_path,
            f"# {group.replace('-', ' ').title()}\n\nRoles:\n- {name}\n",
            quiet=json_output,
        )
        created_paths.append(readme_path)

    manifest_path = os.path.join(root, FILE_MANIFEST) if root else FILE_MANIFEST

    # --- Manifest update ---
    manifest_updated = False
    manifest_warning: str | None = None
    manifest_findings: list[str] = []

    if update_manifest:
        (
            manifest_updated,
            manifest_warning,
            created_manifest,
            manifest_findings,
        ) = update_manifest_for_role(
            manifest_path, group, name,
        )
        if created_manifest and not json_output:
            print(f"  Created: {manifest_path}")
        if created_manifest:
            created_paths.append(manifest_path)
        if manifest_warning and not json_output:
            print(f"  {LEVEL_WARN}: {manifest_warning}")
        if manifest_updated and not json_output:
            print(f"  Updated: {manifest_path}")
        if manifest_findings and not json_output:
            for f in manifest_findings:
                print(f"  {f}")

    if json_output:
        result_dict: dict = {
            "tool": "scaffold",
            "component": "role",
            "name": name,
            "group": group,
            "success": True,
            "path": os.path.abspath(role_path),
            "created": [os.path.abspath(p) for p in created_paths],
        }
        if update_manifest:
            result_dict["manifest_updated"] = manifest_updated
            if manifest_warning:
                result_dict["manifest_warning"] = manifest_warning
            if manifest_findings:
                result_dict["manifest_findings"] = manifest_findings
        return result_dict

    print(f"\n\u2713 Role '{name}' scaffolded at {role_path}")
    print(f"  Next: edit {role_path}")
    if not update_manifest:
        print(f"  Next: update {manifest_path}")
    return None


# Maps --with-* CLI flags to directory constants.
_WITH_FLAG_MAP = {
    "--with-references": DIR_REFERENCES,
    "--with-scripts": DIR_SCRIPTS,
    "--with-assets": DIR_ASSETS,
}

# All flags recognised per component type.  --root and --json are
# stripped before component dispatch and are not included here.
# --update-manifest is included so it appears in "Allowed:" error messages.
_KNOWN_FLAGS = {
    "skill": {"--router", "--with-references", "--with-scripts", "--with-assets", "--update-manifest"},
    "capability": {"--with-references", "--update-manifest"},
    "role": {"--update-manifest"},
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


def _parse_optional_dirs(flags: list[str]) -> list[str]:
    """Return deduplicated list of optional directory constants from *flags*.

    Call *_validate_flags* first to ensure all flags are recognised.
    """
    with_flags = list(dict.fromkeys(f for f in flags if f in _WITH_FLAG_MAP))
    return [_WITH_FLAG_MAP[f] for f in with_flags]


def main() -> None:
    args = sys.argv[:]

    # Parse --json flag first so that all subsequent error paths can
    # emit machine-readable output when requested.
    json_output = "--json" in args
    if json_output:
        args = [a for a in args if a != "--json"]

    # Parse --update-manifest flag
    update_manifest = "--update-manifest" in args
    if update_manifest:
        args = [a for a in args if a != "--update-manifest"]

    # Parse --root option
    root = ""
    if "--root" in args:
        idx = args.index("--root")
        if idx + 1 >= len(args) or args[idx + 1].startswith("--"):
            if json_output:
                print(to_json_output({
                    "tool": "scaffold",
                    "success": False,
                    "error": "--root requires a path argument",
                }))
            else:
                print(f"{LEVEL_FAIL}: --root requires a path argument")
            sys.exit(1)
        root = args[idx + 1]
        del args[idx : idx + 2]

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
                print("Usage: python scripts/scaffold.py skill <name> [--router] [--root <path>] [--with-references] [--with-scripts] [--with-assets] [--update-manifest] [--json]")
            sys.exit(1)
        _validate_flags(flags, "skill", json_mode=json_output)
        name = positional[0]
        router = "--router" in flags
        optional_dirs = _parse_optional_dirs(flags)
        try:
            result = scaffold_skill(
                name, router, root, optional_dirs,
                json_output=json_output,
                update_manifest=update_manifest,
            )
        except Exception as exc:
            if json_output:
                print(to_json_output({
                    "tool": "scaffold",
                    "component": "skill",
                    "name": name,
                    "success": False,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }))
                sys.exit(1)
            raise
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
                print("Usage: python scripts/scaffold.py capability <domain> <name> [--root <path>] [--with-references] [--update-manifest] [--json]")
            sys.exit(1)
        _validate_flags(flags, "capability", json_mode=json_output)
        optional_dirs = _parse_optional_dirs(flags)
        try:
            result = scaffold_capability(
                positional[0], positional[1], root, optional_dirs,
                json_output=json_output,
                update_manifest=update_manifest,
            )
        except Exception as exc:
            if json_output:
                print(to_json_output({
                    "tool": "scaffold",
                    "component": "capability",
                    "name": positional[1],
                    "domain": positional[0],
                    "success": False,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }))
                sys.exit(1)
            raise
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
                print("Usage: python scripts/scaffold.py role <group> <name> [--root <path>] [--update-manifest] [--json]")
            sys.exit(1)
        _validate_flags(flags, "role", json_mode=json_output)
        try:
            result = scaffold_role(
                positional[0], positional[1], root,
                json_output=json_output,
                update_manifest=update_manifest,
            )
        except Exception as exc:
            if json_output:
                print(to_json_output({
                    "tool": "scaffold",
                    "component": "role",
                    "name": positional[1],
                    "group": positional[0],
                    "success": False,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }))
                sys.exit(1)
            raise
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
