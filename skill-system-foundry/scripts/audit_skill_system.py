#!/usr/bin/env python3
"""
Validate the entire skill system structure for consistency.

Checks: spec compliance, dependency direction, role composition,
manifest consistency, nesting depth, shared resource usage,
capability entry naming, router-table consistency, and structural
rules.

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

The audit runs in two modes:

* **System-root mode** — <system-root> contains a skills/ directory
  with skill subdirectories.  This is the deployed system layout
  (e.g., .agents/ or a standalone system directory).  All per-skill
  rules iterate skills/<name>/.
* **Skill-root mode** — <system-root> contains SKILL.md directly,
  i.e., it is itself a skill (typically the foundry meta-skill or any
  integrator-built meta-skill).  In this mode the top-level SKILL.md
  is audited by the rules whose scope is structural consistency
  between a parent SKILL.md and its capabilities — today the
  router-table consistency rule, the orphan-references rule, the
  bottom-up ``allowed-tools`` aggregation rule, and the per-capability
  skill-only-fields redirect.  Other checks that iterate discovered
  skills (spec compliance, dependency direction, shared resources,
  capability entry naming, etc.) walk skills/<name>/ and do not treat
  the top-level skill as a discovered skill unless a skills/ directory
  is also present.

If neither mode applies (no skills/ and no top-level SKILL.md), the
script runs a partial audit and emits a warning.

Examples:
    python scripts/audit_skill_system.py /path/to/project/.agents
    python scripts/audit_skill_system.py /path/to/system --verbose
    python scripts/audit_skill_system.py /path/to/my-meta-skill
    python scripts/audit_skill_system.py /path/to/system --json
"""

import argparse
import json
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
    to_posix,
)
from lib.discovery import (
    find_skill_dirs,
    find_roles,
    find_router_audit_targets,
    check_line_count,
    read_file,
    load_capability_data,
    top_level_skill_entry,
    CapabilityRecord,
)
from lib.constants import (
    ALLOWED_ORPHANS,
    DIR_SKILLS, DIR_CAPABILITIES, DIR_SHARED,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, FILE_MANIFEST, EXT_MARKDOWN,
    MAX_BODY_LINES, MAX_DESCRIPTION_CHARS,
    RE_ROLES_REF, RE_SIBLING_CAP_REF,
    RE_SKILL_REF, RE_CAPABILITY_REF, MIN_ROLE_SKILLS,
    SEPARATOR_WIDTH,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
    PATH_RESOLUTION_DOC_PATH,
    PATH_RESOLUTION_RULE_NAME,
    collect_foundry_config_findings,
)
from lib.orphans import find_orphan_references, find_unresolved_allowed_orphans
from lib.prose_yaml import collect_prose_findings, format_finding_as_string
from lib.bundling import check_long_paths, check_reserved_path_components
from lib.router_table import audit_router_table
from lib.validation import (
    validate_description_triggers,
    aggregate_capability_allowed_tools,
    validate_allowed_tools,
    validate_capability_skill_only_fields,
)


def _read_plugin_json(path: str) -> tuple[dict | None, str | None]:
    """Load and return (data, error_message) from a plugin/marketplace JSON file.

    The tuple's error slot is populated with a human-readable message when
    the file is unreadable or not valid JSON, so the caller can emit a
    FAIL finding without crashing the audit.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        return None, f"cannot read: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})"
    if not isinstance(data, dict):
        return None, f"expected top-level object, got {type(data).__name__}"
    return data, None


def _skill_md_version(system_root: str) -> tuple[str | None, str | None]:
    """Return ``(version, error)`` for ``skill-system-foundry/SKILL.md``."""
    path = os.path.join(system_root, "skill-system-foundry", FILE_SKILL_MD)
    if not os.path.exists(path):
        return None, f"{path} does not exist"
    try:
        fm, _, _ = load_frontmatter(path)
    except OSError as exc:
        # A present-but-unreadable file (permissions, transient FS error)
        # must surface as a structured finding instead of aborting the
        # audit, mirroring how _read_plugin_json handles its own errors.
        return None, f"{path} cannot be read: {exc}"
    if fm is None:
        return None, f"{path} has no frontmatter"
    if "_parse_error" in fm:
        return None, f"{path} YAML parse error: {fm['_parse_error']}"
    metadata = fm.get("metadata")
    if not isinstance(metadata, dict):
        return None, f"{path} has no 'metadata' mapping"
    value = metadata.get("version")
    if not isinstance(value, str):
        return None, f"{path} missing 'metadata.version' string"
    return value, None


def check_version_consistency(system_root: str) -> list[str]:
    """Assert SKILL.md, plugin.json, and marketplace.json agree on version.

    The rule is a pre-loop, repo-level check — it runs once before the
    per-skill audit.  It is gated on the presence of **both**
    ``.claude-plugin/plugin.json`` *and* ``skill-system-foundry/SKILL.md``
    under the audit root, so it only fires for the foundry distribution
    repository itself.  Integrator skill systems that ship their own
    Claude plugin manifest (and therefore have ``.claude-plugin/plugin.json``)
    but lay out their canonical SKILL.md elsewhere are unaffected.

    Canonical source is ``skill-system-foundry/SKILL.md`` →
    ``metadata.version``.  The rule emits one FAIL finding per file that
    fails to expose a readable version, and a single summary FAIL when
    the three known versions disagree.  No finding is emitted when all
    three agree.
    """
    plugin_path = os.path.join(system_root, ".claude-plugin", "plugin.json")
    foundry_skill_path = os.path.join(
        system_root, "skill-system-foundry", FILE_SKILL_MD
    )
    if not (os.path.exists(plugin_path) and os.path.exists(foundry_skill_path)):
        return []

    findings: list[str] = []

    marketplace_path = os.path.join(
        system_root, ".claude-plugin", "marketplace.json"
    )

    # SKILL.md
    skill_version, skill_err = _skill_md_version(system_root)
    if skill_err:
        findings.append(f"{LEVEL_FAIL}: version drift — SKILL.md: {skill_err}")

    # plugin.json
    plugin_data, plugin_err = _read_plugin_json(plugin_path)
    plugin_version: str | None = None
    plugin_name: str | None = None
    if plugin_err:
        findings.append(
            f"{LEVEL_FAIL}: version drift — plugin.json: {plugin_err}"
        )
    elif plugin_data is not None:
        value = plugin_data.get("version")
        if isinstance(value, str):
            plugin_version = value
        else:
            findings.append(
                f"{LEVEL_FAIL}: version drift — plugin.json: missing "
                f"top-level 'version' string"
            )
        name_value = plugin_data.get("name")
        if isinstance(name_value, str) and name_value.strip():
            # Store the stripped form so the marketplace lookup matches
            # consistently — a manifest like ``"name": "  demo  "`` would
            # otherwise pass validation here but never match a
            # marketplace plugin entry whose ``"name": "demo"`` is
            # already canonical.
            plugin_name = name_value.strip()
        else:
            # Surface the root cause at plugin.json — the marketplace
            # lookup further down would otherwise emit a misleading
            # "no plugin entry matches name ''" finding without
            # pointing the operator at the file that actually needs
            # editing.  Whitespace-only names are treated the same as
            # missing because they cannot match any plugin entry.
            findings.append(
                f"{LEVEL_FAIL}: version drift — plugin.json: "
                f"top-level 'name' is missing, empty, or not a string"
            )

    # marketplace.json
    marketplace_version: str | None = None
    if not os.path.exists(marketplace_path):
        findings.append(
            f"{LEVEL_FAIL}: version drift — marketplace.json: "
            f"{marketplace_path} does not exist"
        )
    else:
        market_data, market_err = _read_plugin_json(marketplace_path)
        if market_err:
            findings.append(
                f"{LEVEL_FAIL}: version drift — marketplace.json: {market_err}"
            )
        elif market_data is not None:
            plugins = market_data.get("plugins")
            if not isinstance(plugins, list):
                findings.append(
                    f"{LEVEL_FAIL}: version drift — marketplace.json: "
                    f"'plugins' is not a list"
                )
            elif plugin_name is None:
                findings.append(
                    f"{LEVEL_FAIL}: version drift — marketplace.json: "
                    f"cannot match plugin entry because plugin.json 'name' is unavailable"
                )
            else:
                matched = None
                for entry in plugins:
                    if isinstance(entry, dict) and entry.get("name") == plugin_name:
                        matched = entry
                        break
                if matched is None:
                    findings.append(
                        f"{LEVEL_FAIL}: version drift — marketplace.json: "
                        f"no plugin entry matches name '{plugin_name}'"
                    )
                else:
                    value = matched.get("version")
                    if isinstance(value, str):
                        marketplace_version = value
                    else:
                        findings.append(
                            f"{LEVEL_FAIL}: version drift — marketplace.json: "
                            f"plugin '{plugin_name}' missing 'version' string"
                        )

    # Only compare when all three were successfully read.  Use ``is not None``
    # so an empty-string version (e.g., ``"version": ""`` in plugin.json) is
    # still compared and reported as drift instead of silently skipping.
    if (
        skill_version is not None
        and plugin_version is not None
        and marketplace_version is not None
    ):
        if not (skill_version == plugin_version == marketplace_version):
            findings.append(
                f"{LEVEL_FAIL}: version drift — "
                f"SKILL.md={skill_version}, plugin.json={plugin_version}, "
                f"marketplace.json={marketplace_version} "
                f"(canonical: SKILL.md)"
            )

    return findings


def check_upward_references(content: str, component_type: str, allow_orchestration: bool = False) -> list[tuple[str, str]]:
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


def audit_skill_system(
    system_root: str,
    verbose: bool = True,
    allow_orchestration: bool = False,
) -> list[str]:
    """Run all skill-system-level validations.

    Returns:
        A list of error strings. Each string is prefixed with a level
        (``FAIL``, ``WARN``, or ``INFO``).
    """
    errors: list[str] = []
    system_root = os.path.abspath(system_root)

    # When auditing the foundry itself, surface configuration.yaml
    # divergences detected at constants.py import.
    errors.extend(collect_foundry_config_findings(system_root))

    # Repo-level rule: SKILL.md, plugin.json, and marketplace.json must
    # declare the same version.  Silent skip when .claude-plugin/plugin.json
    # is absent — that is how we distinguish the foundry repo root from an
    # integrator's skill system.
    errors.extend(check_version_consistency(system_root))

    skills_dir = os.path.join(system_root, DIR_SKILLS)
    has_skills_dir = os.path.isdir(skills_dir)
    has_top_level_skill = os.path.isfile(
        os.path.join(system_root, FILE_SKILL_MD)
    )

    # Discover components
    skills = find_skill_dirs(system_root)
    roles = find_roles(system_root)

    registered_skills = [s for s in skills if s["type"] == "registered"]
    capabilities = [s for s in skills if s["type"] == "capability"]

    # Aggregation targets — the rule fires per parent SKILL.md and is
    # structural (parent must be a superset of capability declarations),
    # so it belongs in the same category as router-table and
    # orphan-references which already fire in both deployed-system and
    # skill-root modes.  In skill-root mode the meta-skill sits at
    # ``system_root`` itself rather than under ``skills/<name>/``, so
    # ``find_skill_dirs`` does not surface it; ``top_level_skill_entry``
    # supplies the synthetic entry whose ``name`` mirrors the
    # SKILL.md frontmatter.
    aggregation_targets: list[dict[str, str]] = list(registered_skills)
    skill_root_entry = top_level_skill_entry(system_root)
    if skill_root_entry is not None:
        aggregation_targets.append(skill_root_entry)

    # Capability-isolation targets — broader than ``capabilities``.
    # ``find_skill_dirs`` does not surface
    # ``<system_root>/capabilities/<cap>/`` in skill-root mode, so the
    # capability-isolation loop (parse-error FAIL, scalar findings,
    # "has full frontmatter" INFO, skill-only-fields redirect) would
    # silently skip the top-level skill's own capabilities.  Synthesize
    # entries for them here so the rule's coverage matches the
    # aggregation rule that just gained skill-root coverage.  The
    # *narrower* ``capabilities`` list still drives the
    # dependency-direction and nesting-depth loops below — those rules
    # produce false-positive FAILs on the foundry's own capability
    # documentation (which explains ``roles/`` paths in prose), so
    # they remain deployed-system-only by design.
    capability_isolation_targets: list[dict[str, str]] = list(capabilities)
    if skill_root_entry is not None:
        top_caps_dir = os.path.join(system_root, DIR_CAPABILITIES)
        if os.path.isdir(top_caps_dir):
            for cap_name in sorted(os.listdir(top_caps_dir)):
                cap_path = os.path.join(top_caps_dir, cap_name)
                cap_entry = os.path.join(cap_path, FILE_CAPABILITY_MD)
                if os.path.isdir(cap_path) and os.path.isfile(cap_entry):
                    capability_isolation_targets.append({
                        "name": cap_name,
                        "path": cap_path,
                        "type": "capability",
                        "parent": skill_root_entry["name"],
                    })

    # Audit-wide capability discovery pass.  Reads each
    # ``capability.md`` once and stores frontmatter + plain-scalar
    # findings keyed by absolute path.  The aggregation loop consumes
    # a per-target sub-dict; the per-capability loop below consumes the
    # full dict.  Net: one read per ``capability.md`` regardless of how
    # many audit rules touch it.
    #
    # Two sources feed the dict so it stays exhaustive over both
    # the ``capabilities`` list ``find_skill_dirs`` returns and the
    # ``aggregation_targets`` list above: aggregation targets (the bulk
    # path — registered skills plus the top-level skill in skill-root
    # mode) and orphan capability-only directories
    # (``skills/<name>/capabilities/<cap>/`` where the parent has no
    # ``SKILL.md``).  ``find_skill_dirs`` surfaces the latter for the
    # capability-isolation rule, so the lookup below must cover them
    # too.
    system_capability_data: dict[str, CapabilityRecord] = {}
    per_skill_capability_data: dict[str, dict[str, CapabilityRecord]] = {}
    for skill in aggregation_targets:
        sub = load_capability_data(skill["path"])
        per_skill_capability_data[skill["path"]] = sub
        system_capability_data.update(sub)
    for cap in capabilities:
        cap_md_abs = os.path.abspath(
            os.path.join(cap["path"], FILE_CAPABILITY_MD)
        )
        if cap_md_abs in system_capability_data:
            continue
        try:
            fm, _, cap_scalar_findings = load_frontmatter(cap_md_abs)
        except (OSError, UnicodeDecodeError) as exc:
            # Match ``load_capability_data``: surface I/O failures
            # as a ``_parse_error`` record so the capability-isolation
            # loop FAILs the file via its existing parse-error branch
            # instead of silently skipping or deferring the crash to a
            # later body-read site.
            fm = {"_parse_error": f"unreadable: {exc}"}
            cap_scalar_findings = []
        system_capability_data[cap_md_abs] = CapabilityRecord(
            fm, cap_scalar_findings,
        )

    if verbose:
        print(f"Found: {len(registered_skills)} skills, {len(capabilities)} capabilities, "
              f"{len(roles)} roles")
        if has_top_level_skill:
            # Skill-root mode: find_skill_dirs only walks <root>/skills/,
            # so the count above does not include the synthetic
            # skill-root entry that the router-table rule will audit.
            # Surface it explicitly so the verbose header agrees with
            # the findings about to be emitted.
            print(
                "Skill-root mode: also auditing skill at "
                f"{to_posix(system_root)}"
            )
        print()

    # Partial-audit WARN fires only when the audit cannot reach any
    # skill at all.  In skill-root mode (top-level SKILL.md), the audit
    # is a first-class single-skill audit — not a partial run.
    if not has_skills_dir and not has_top_level_skill:
        errors.append(
            f"{LEVEL_WARN}: No {DIR_SKILLS}/ directory under system root — ran partial audit "
            "(distribution-repo mode). Point to deployed system root for full coverage."
        )

    # --- Spec Compliance ---
    if verbose:
        print("== Spec Compliance ==")

    for skill in registered_skills:
        skill_md = os.path.join(skill["path"], FILE_SKILL_MD)
        fm, body, scalar_findings = load_frontmatter(skill_md)

        if fm is None:
            errors.append(f"{LEVEL_FAIL}: {skill['name']}/{FILE_SKILL_MD} has no frontmatter")
            continue

        if "_parse_error" in fm:
            errors.append(
                f"{LEVEL_FAIL}: {skill['name']}/{FILE_SKILL_MD} YAML parse error: "
                f"{fm['_parse_error']}"
            )
            continue

        for f in scalar_findings:
            level, _, detail = f.partition(": ")
            errors.append(f"{level}: {skill['name']}/{FILE_SKILL_MD} {detail}")


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
        else:
            description = str(fm["description"])
            if not description.strip():
                # Empty / whitespace-only descriptions are spec
                # violations (the spec mandates non-empty).  Without
                # this branch the per-skill audit treats blank values
                # as silently valid because the trigger heuristic
                # short-circuits on whitespace and the length check
                # passes a zero-length string.
                errors.append(
                    f"{LEVEL_FAIL}: {skill['name']}/{FILE_SKILL_MD} 'description' field is empty"
                )
            else:
                if len(description) > MAX_DESCRIPTION_CHARS:
                    errors.append(
                        f"{LEVEL_FAIL}: {skill['name']}/{FILE_SKILL_MD} description exceeds {MAX_DESCRIPTION_CHARS} chars"
                    )
                trigger_errors, _ = validate_description_triggers(description)
                for trigger_error in trigger_errors:
                    level, _, detail = trigger_error.partition(": ")
                    errors.append(
                        f"{level}: {skill['name']}/{FILE_SKILL_MD} {detail}"
                    )

        body_lines = count_body_lines(body)
        if body_lines > MAX_BODY_LINES:
            errors.append(
                f"{LEVEL_WARN}: {skill['name']}/{FILE_SKILL_MD} body is {body_lines} lines (max {MAX_BODY_LINES})"
            )
        elif verbose:
            print(f"  \u2713 {skill['name']}: spec compliant ({body_lines} body lines)")

    # --- Bottom-up allowed-tools aggregation ---
    # Parent SKILL.md ``allowed-tools`` must be a superset of the
    # union of capability-declared sets.  Iterates
    # ``aggregation_targets`` so the rule fires in both
    # deployed-system mode (registered skills under
    # ``skills/<name>/``) and skill-root mode (a top-level
    # SKILL.md).  Matches the scoping of the router-table and
    # orphan-references rules \u2014 each is a structural consistency
    # check between a parent SKILL.md and its capabilities, which
    # makes both modes equally relevant.  The raw finding format is
    # ``LEVEL: [foundry] message``; the audit injects the skill
    # name after the foundry tag so the prefix stays left-aligned
    # and consistent with other tagged findings.
    if aggregation_targets and verbose:
        print("\n== Allowed-Tools Aggregation ==")
    for skill in aggregation_targets:
        skill_md_path = os.path.join(skill["path"], FILE_SKILL_MD)
        try:
            agg_fm, _, _ = load_frontmatter(skill_md_path)
        except (OSError, UnicodeDecodeError):
            agg_fm = None
        # Spec-compliance and router-table loops already FAIL on
        # missing or unparseable parent frontmatter; aggregation
        # can only run against a parsed dict, so skip silently
        # here to avoid double-FAIL.
        if agg_fm is None or "_parse_error" in agg_fm:
            continue
        agg_errors, _ = aggregate_capability_allowed_tools(
            skill["path"], agg_fm,
            capability_data=per_skill_capability_data[skill["path"]],
        )
        for finding in agg_errors:
            level, _, detail = finding.partition(": ")
            tag_prefix = "[foundry] "
            if detail.startswith(tag_prefix):
                detail = detail[len(tag_prefix):]
                errors.append(
                    f"{level}: [foundry] {skill['name']}: {detail}"
                )
            else:
                errors.append(f"{level}: {skill['name']}: {detail}")
        if not agg_errors and verbose:
            print(f"  ✓ {skill['name']}: aggregation clean")

    # --- Long-path pre-flight (cross-platform) ---
    if verbose:
        print("\n== Long-Path Budget ==")
    # Iterate ``aggregation_targets`` rather than ``skills`` so the
    # rule covers both deployed-system layouts (registered skills
    # under ``skills/<name>/``) AND skill-root mode (the synthetic
    # top-level entry produced by ``top_level_skill_entry``).
    # ``find_skill_dirs`` does not surface the top-level SKILL.md
    # in skill-root mode, so iterating it alone would skip the most
    # common local-audit-self shape.  Capabilities are excluded
    # because they are part of their parent skill's archive and
    # would double-report.
    #
    # Boundary widening: pass *system_root* so the walker inspects
    # symlinks targeting sibling roles/skills the bundler would
    # ship.  Without it, the audit's default ``boundary=skill_path``
    # would silently skip those targets and miss problems that
    # ``bundle.py`` will FAIL on at packaging time.
    for skill in aggregation_targets:
        lp_errors, lp_passes = check_long_paths(
            skill["path"], severity=LEVEL_WARN, boundary=system_root,
        )
        for finding in lp_errors:
            level, _, detail = finding.partition(": ")
            errors.append(f"{level}: {skill['name']}: {detail}")
        if not lp_errors and verbose:
            print(f"  ✓ {skill['name']}: long-path clean")

    # --- Reserved-name path-component check (cross-platform) ---
    if verbose:
        print("\n== Reserved Names ==")
    for skill in aggregation_targets:
        rn_errors, _rn_passes = check_reserved_path_components(
            skill["path"], severity=LEVEL_WARN, boundary=system_root,
        )
        for finding in rn_errors:
            level, _, detail = finding.partition(": ")
            errors.append(f"{level}: {skill['name']}: {detail}")
        if not rn_errors and verbose:
            print(f"  ✓ {skill['name']}: no reserved-name path components")

    # ``roles/`` lives outside ``aggregation_targets`` (which only
    # contains registered skills + the synthetic top-level skill
    # entry) but the bundler can copy roles into the archive when
    # they appear in the skill's reference graph.  Walk the
    # ``<system_root>/roles/`` tree directly so a role with a
    # reserved-name component or an over-budget path is caught at
    # audit time instead of slipping through to bundle
    # post-validation.  Skip the section when no ``roles/`` tree
    # exists (distribution-repo mode, or a system that does not use
    # the role layer).
    roles_dir = os.path.join(system_root, "roles")
    if os.path.isdir(roles_dir):
        roles_lp_errors, _roles_lp_passes = check_long_paths(
            roles_dir, severity=LEVEL_WARN, boundary=system_root,
        )
        for finding in roles_lp_errors:
            level, _, detail = finding.partition(": ")
            errors.append(f"{level}: roles/: {detail}")
        if not roles_lp_errors and verbose:
            print("  ✓ roles/: long-path clean")
        roles_rn_errors, _roles_rn_passes = check_reserved_path_components(
            roles_dir, severity=LEVEL_WARN, boundary=system_root,
        )
        for finding in roles_rn_errors:
            level, _, detail = finding.partition(": ")
            errors.append(f"{level}: roles/: {detail}")
        if not roles_rn_errors and verbose:
            print("  ✓ roles/: no reserved-name path components")

    # --- Capabilities should not be registered ---
    if verbose:
        print("\n== Capability Isolation ==")

    for cap in capability_isolation_targets:
        cap_md = os.path.join(cap["path"], FILE_CAPABILITY_MD)
        # Audit-wide discovery pass populated this record (covering
        # registered-skill capabilities, orphan capability-only
        # directories, and top-level skill-root capabilities), so the
        # lookup is unconditional — no fallback needed.
        cap_record = system_capability_data[os.path.abspath(cap_md)]
        fm = cap_record.frontmatter
        scalar_findings = cap_record.scalar_findings
        if fm and "_parse_error" in fm:
            errors.append(
                f"{LEVEL_FAIL}: {cap['parent']}/capabilities/{cap['name']}/{FILE_CAPABILITY_MD} "
                f"frontmatter parse error: {fm['_parse_error']}"
            )
            continue
        for f in scalar_findings:
            level, _, detail = f.partition(": ")
            errors.append(f"{level}: {cap['parent']}/capabilities/{cap['name']}/{FILE_CAPABILITY_MD} {detail}")
        if fm and "name" in fm and "description" in fm:
            errors.append(
                f"{LEVEL_INFO}: {cap['parent']}/capabilities/{cap['name']} has full "
                f"frontmatter — verify it's not registered in discovery"
            )
        elif verbose:
            print(f"  \u2713 {cap['parent']}/{cap['name']}: not registered")

        cap_rel = (
            f"{cap['parent']}/capabilities/{cap['name']}/{FILE_CAPABILITY_MD}"
        )

        # Capability-scope ``allowed-tools`` validation.  Capability
        # declarations are now authoritative input for aggregation
        # and the per-file coherence check, so they need the same
        # type/catalog diagnostics ``SKILL.md``'s ``allowed-tools``
        # gets.  Without this loop a capability declaring
        # ``allowed-tools: {bash: true}`` (a mapping) would
        # contribute zero tokens to aggregation and pass the audit
        # silently.  Findings are re-emitted with the capability
        # path so attribution stays with the offending file.
        if isinstance(fm, dict) and "allowed-tools" in fm:
            at_errors, _ = validate_allowed_tools(fm["allowed-tools"])
            for finding in at_errors:
                level, _, detail = finding.partition(": ")
                errors.append(f"{level}: {cap_rel} {detail}")

        # Skill-only-fields INFO redirect \u2014 capability frontmatter must
        # not duplicate fields whose authoritative home is the parent
        # SKILL.md (license, compatibility, metadata.author/version/spec).
        sof_errors, _ = validate_capability_skill_only_fields(fm, cap_rel)
        errors.extend(sof_errors)

    # --- Dependency Direction ---
    if verbose:
        print("\n== Dependency Direction ==")

    for cap in capabilities:
        cap_md_path = os.path.join(cap["path"], FILE_CAPABILITY_MD)
        # Skip capabilities the discovery pass already marked
        # unreadable (``_parse_error`` record).  The capability
        # isolation loop above has already FAILed them; reading the
        # body again here would re-crash on invalid UTF-8 or repeat
        # the I/O error.
        cap_record = system_capability_data.get(os.path.abspath(cap_md_path))
        cap_fm = cap_record.frontmatter if cap_record is not None else None
        if isinstance(cap_fm, dict) and "_parse_error" in cap_fm:
            continue
        content = read_file(cap_md_path)
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

    # --- Router Table ---
    if verbose:
        print("\n== Router Table ==")

    # Router-table audit is the only per-skill rule that intentionally
    # scans a top-level SKILL.md (skill-root mode) and also reaches
    # capability-bearing directories that find_skill_dirs filters out.
    # find_router_audit_targets returns every directory where the rule
    # could possibly fire (one half or both present); audit_router_table
    # itself returns [] for the no-router half-case.
    router_skills = find_router_audit_targets(system_root)

    for skill in router_skills:
        rt_findings = audit_router_table(skill["path"])
        for level, message in rt_findings:
            errors.append(f"{level}: {skill['name']} {message}")
        if not rt_findings and verbose:
            # Confirm cleanliness only for actual router skills.  A
            # registered standalone (SKILL.md, no router, no
            # capabilities/) returns [] from audit_router_table — there
            # is nothing to confirm, so stay quiet.
            if os.path.isdir(
                os.path.join(skill["path"], DIR_CAPABILITIES)
            ):
                print(
                    f"  ✓ {skill['name']}: router table consistent"
                )

    # --- Orphan References ---
    # Per-skill rule: any file under references/ or
    # capabilities/<name>/references/ that no SKILL.md or capability.md
    # reaches via the configured body reference patterns.  Fires in
    # both system-root mode (every registered skill) and skill-root
    # mode (the top-level skill).  The rule is independent of
    # --allow-nested-references — that flag suppresses depth warnings;
    # this rule only asks whether each file is reachable at all.
    if verbose:
        print("\n== Orphan References ==")

    # Pair each (skill_root, prefix) target with the audit_root that
    # makes ``skills/<name>/...``-keyed allowed_orphans entries
    # meaningful.  In system-root mode that is the system root (which
    # contains skills/).  In skill-root mode there is no enclosing
    # skills/ directory, so audit_root is None — skills/-prefixed
    # entries simply don't match anything in that mode.
    orphan_targets: list[tuple[str, str, str | None]] = []
    for skill in registered_skills:
        orphan_targets.append(
            (skill["path"], f"{DIR_SKILLS}/{skill['name']}", system_root)
        )
    if has_top_level_skill:
        # Skill-root mode: derive the prefix from the SKILL.md name
        # frontmatter, falling back to the directory basename.  Use
        # the absolute path's basename so a target invoked as ``.``
        # or with a trailing separator (where ``basename`` would
        # otherwise yield ``.`` or empty) still produces a usable
        # display label.
        top_label = os.path.basename(os.path.abspath(system_root))
        try:
            fm, _, _ = load_frontmatter(
                os.path.join(system_root, FILE_SKILL_MD)
            )
            if fm and isinstance(fm.get("name"), str) and fm["name"].strip():
                top_label = fm["name"].strip()
        except (OSError, UnicodeError):
            # load_frontmatter opens with encoding="utf-8"; non-UTF-8
            # SKILL.md files raise UnicodeDecodeError.  Fall back to
            # the directory basename so the audit completes — the
            # spec-compliance check elsewhere will surface the
            # underlying file problem.
            pass
        orphan_targets.append((system_root, top_label, None))

    for skill_root, prefix, audit_root in orphan_targets:
        orphan_findings = find_orphan_references(
            skill_root,
            ALLOWED_ORPHANS,
            audit_root=audit_root,
            skill_audit_prefix=prefix,
        )
        errors.extend(orphan_findings)
        if not orphan_findings and verbose:
            print(f"  ✓ {prefix}: no orphan references")

    # Stale allow-list detection: any allowed_orphans entry that does
    # not resolve to an existing file under the audited skills is
    # surfaced as INFO so dead entries don't accumulate silently.  In
    # system-root mode the lookup spans every audited skill root plus
    # the system root (for ``skills/<name>/...`` entries); in skill-
    # root mode ``skills/<name>/...`` entries are silently skipped
    # because they target a layout this invocation cannot inspect.
    #
    # Derive the global audit_root from orphan_targets directly so
    # there is one source of truth — the third tuple element is the
    # per-target audit_root (system_root for registered skills, None
    # for the top-level skill).  Picking the first non-None value
    # mirrors the old ``system_root if has_skills_dir else None``
    # gate without re-deriving it from has_skills_dir.
    #
    # Invariant: every non-None audit_root in orphan_targets equals
    # system_root.  The orphan_targets construction above is the only
    # place that populates the third element, and it always passes
    # system_root for registered skills and None for the top-level
    # skill — so ``next()`` returns either system_root or None.  If a
    # future contributor adds a new orphan_target variant with a
    # different audit_root, this derivation must be revisited (use a
    # set comprehension and check cardinality).
    unresolved_skill_roots = [t[0] for t in orphan_targets]
    unresolved_audit_root = next(
        (t[2] for t in orphan_targets if t[2] is not None),
        None,
    )
    stale_findings = find_unresolved_allowed_orphans(
        ALLOWED_ORPHANS,
        unresolved_skill_roots,
        unresolved_audit_root,
    )
    errors.extend(stale_findings)
    if not stale_findings and verbose and ALLOWED_ORPHANS:
        print("  ✓ allowed_orphans: every entry resolves to an existing file")

    # --- Manifest ---
    if verbose:
        print("\n== Manifest ==")

    if not has_skills_dir:
        # No skills/ directory — either a distribution repo or skill-root
        # mode (top-level SKILL.md).  Manifest is a deployed-system
        # concept and is not applicable in either case.
        if verbose:
            if has_top_level_skill:
                print(
                    "  - skipped (skill-root mode \u2014 manifest is a "
                    "deployed-system concept)"
                )
            else:
                print(
                    "  - skipped (no skills/ directory \u2014 not a "
                    "deployed skill system)"
                )
    else:
        manifest_path = os.path.join(system_root, FILE_MANIFEST)
        if not os.path.exists(manifest_path):
            errors.append(f"{LEVEL_WARN}: No {FILE_MANIFEST} found at system root")
        else:
            if verbose:
                print(f"  \u2713 {FILE_MANIFEST} exists")
            try:
                scalar_findings: list[str] = []
                manifest = parse_yaml_subset(
                    read_file(manifest_path), scalar_findings,
                )
                for finding in scalar_findings:
                    level, _, detail = finding.partition(": ")
                    detail = detail.removeprefix("[spec] ").removeprefix("[spec]").lstrip()
                    errors.append(
                        f"{level}: [spec] {FILE_MANIFEST} {detail}"
                    )
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
            "Path to a skill system root (contains skills/, roles/) or "
            "to a single skill root (contains SKILL.md directly).  "
            "Skill-root mode triggers the router-table rule on the "
            "target skill itself."
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
    parser.add_argument(
        "--check-prose-yaml",
        action="store_true",
        dest="check_prose_yaml",
        help=(
            "Run the doc-snippet ```yaml validation across every "
            "scanned skill (SKILL.md + capabilities/**/*.md + "
            "references/**/*.md).  See "
            "references/authoring-principles.md for the convention."
        ),
    )
    parser.add_argument(
        "--foundry-self",
        action="store_true",
        dest="foundry_self",
        help=(
            "Mode switch: run every scanned skill the way the foundry "
            "runs itself.  Currently implies --check-prose-yaml across "
            "all skills."
        ),
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
                "tool": "audit_skill_system",
                "success": False,
                "error": message,
            }))
            sys.exit(1)
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)

    parser.error = _json_aware_error  # type: ignore[assignment]

    args = parser.parse_args()

    system_root: str = args.system_root
    verbose: bool = args.verbose
    allow_orchestration: bool = args.allow_orchestration
    json_output: bool = args.json_output
    # --foundry-self is a mode switch across every scanned skill.
    check_prose: bool = args.check_prose_yaml or args.foundry_self

    if not os.path.isdir(system_root):
        if json_output:
            print(to_json_output({
                "tool": "audit_skill_system",
                "path": to_posix(os.path.abspath(system_root)),
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

    # Aggregate prose-YAML doc-snippet findings across every scanned
    # skill.  Always populate the yaml_conformance JSON slot so
    # consumers don't need a nullability branch.
    prose_findings: list[dict] = []
    prose_checked = 0
    if check_prose:
        all_skills = find_skill_dirs(system_root)
        for skill in all_skills:
            if skill["type"] != "registered":
                continue
            skill_name = os.path.basename(skill["path"])
            audit_prefix = f"{DIR_SKILLS}/{skill_name}"
            findings, checked, per_file = collect_prose_findings(
                skill["path"], audit_prefix=audit_prefix
            )
            prose_checked += checked
            prose_findings.extend(findings)
            if effective_verbose:
                for path, fence_count in per_file:
                    print(
                        f"Checking prose YAML: {path} ({fence_count} fences)"
                    )
        for finding in prose_findings:
            errors.append(format_finding_as_string(finding))
    yaml_conformance_slot = {
        "corpus": {
            "total": 0, "passed": 0, "failed": 0, "failures": [],
        },
        "doc_snippets": {
            "checked": prose_checked,
            "findings": prose_findings,
        },
    }

    if json_output:
        # Compute component counts directly for JSON output (the
        # public API intentionally returns only errors for backward
        # compatibility).
        skills = find_skill_dirs(system_root)
        roles = find_roles(system_root)
        counts = {
            "skills": len([s for s in skills if s["type"] == "registered"]),
            "capabilities": len([s for s in skills if s["type"] == "capability"]),
            "roles": len(roles),
        }
        fails, warns, infos = categorize_errors(errors)
        result = {
            "tool": "audit_skill_system",
            "path": to_posix(os.path.abspath(system_root)),
            "success": len(fails) == 0,
            "counts": counts,
            "summary": {
                "failures": len(fails),
                "warnings": len(warns),
                "info": len(infos),
            },
            "errors": categorize_errors_for_json(errors),
            "yaml_conformance": yaml_conformance_slot,
            "path_resolution": {
                "rule_name": PATH_RESOLUTION_RULE_NAME,
                "documentation_path": PATH_RESOLUTION_DOC_PATH,
            },
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
