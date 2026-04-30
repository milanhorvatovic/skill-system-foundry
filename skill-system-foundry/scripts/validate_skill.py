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
from lib.discovery import load_capability_data
from lib.validation import (
    validate_name,
    validate_allowed_tools,
    validate_description_triggers,
    validate_metadata,
    validate_license,
    validate_known_keys,
    validate_tool_coherence,
    aggregate_capability_allowed_tools,
    validate_capability_skill_only_fields,
)
from lib.codex_config import validate_codex_config
from lib.prose_yaml import collect_prose_findings, format_finding_as_string
from lib.constants import (
    ALLOWED_ORPHANS,
    MAX_DESCRIPTION_CHARS,
    MAX_BODY_LINES, MAX_COMPATIBILITY_CHARS,
    RE_XML_TAG, RE_FIRST_PERSON, RE_FIRST_PERSON_PLURAL,
    RE_SECOND_PERSON, RE_IMPERATIVE_START,
    RECOGNIZED_DIRS,
    DIR_CAPABILITIES,
    FILE_SKILL_MD, FILE_CAPABILITY_MD, SEPARATOR_WIDTH,
    EXT_MARKDOWN,
    LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO,
    collect_foundry_config_findings,
)
from lib.orphans import find_orphan_references
from lib.reachability import extract_body_references


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

    if not description or not description.strip():
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

    trigger_errors, trigger_passes = validate_description_triggers(description)
    errors.extend(trigger_errors)
    passes.extend(trigger_passes)

    return errors, passes


def _check_references(
    body: str, source_label: str, skill_root: str,
    allow_nested_refs: bool = False,
    include_router_table: bool = False,
) -> tuple[list[str], list[str]]:
    """Check markdown references in *body* against the skill root.

    *source_label* identifies the file in error messages (e.g.
    ``"SKILL.md"`` or ``"references/guide.md"``).  All intra-skill
    references are resolved relative to *skill_root*.

    *include_router_table* (default False) augments the body
    reference set with capability paths recovered from a router
    table.  Only the SKILL.md entry legitimately carries one, so
    callers pass ``True`` only for that file — the validator then
    catches misspelled router-table cells (e.g.
    ``capabilities/typo/capability.md``) that the body regexes
    alone would miss because router-table cells are bare paths,
    not markdown links.  Without this, a misspelled cell would
    only be caught by the reachability walker, forcing the orphan
    rule to surface walk warnings to remain trustworthy.
    """
    errors: list[str] = []
    passes: list[str] = []

    # Single source of truth for body reference extraction lives in
    # lib.reachability.extract_body_references — applies the same
    # configured ``reference_patterns`` regexes, strips fenced code
    # blocks, and drops template placeholders.  Pass
    # ``filter_capability_entries=False`` so this rule still validates
    # ``capabilities/<name>/capability.md`` references for existence
    # and depth (the reachability walker filters those out because
    # they are entry-point-only edges, but validation still needs to
    # check that they resolve).
    refs = extract_body_references(
        body,
        filter_capability_entries=False,
        include_router_table=include_router_table,
    )

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

        # Nested reference check — only when flag is not set.
        # The agentskills.io spec only requires references to stay
        # one level deep from SKILL.md.  The foundry extends this
        # convention so that ``capability.md`` is also treated as
        # an entry point with its own one-hop scope (see
        # ``.github/instructions/markdown.instructions.md``):
        # links from a capability body that reach into ``references/``
        # are first-level under that entry point, not nested under
        # the parent SKILL.md.  Skip the recursion in that case.
        #
        # Match the canonical three-segment shape exactly —
        # capabilities/<name>/capability.md relative to the skill
        # root.  An unrelated reference file or asset that happens
        # to be named capability.md (e.g., references/capability.md)
        # is NOT a foundry entry point and must still have its own
        # links checked for nesting.
        rel_to_root = os.path.relpath(ref_path, skill_root).replace(
            os.sep, "/",
        )
        rel_parts = rel_to_root.split("/")
        is_capability_entry = (
            len(rel_parts) == 3
            and rel_parts[0] == DIR_CAPABILITIES
            and rel_parts[2] == FILE_CAPABILITY_MD
        )
        if not allow_nested_refs and not is_capability_entry:
            # Reuse the shared body-reference extractor so the nested
            # check sees the exact same set of links the outer scan
            # would.  ``filter_capability_entries=False`` keeps
            # references to ``capabilities/<name>/capability.md``
            # in scope — they are still legitimate one-hop targets
            # under the foundry router-skill convention.
            nested_refs = extract_body_references(
                ref_content, filter_capability_entries=False,
            )
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

    # Only the SKILL.md entry carries a router table.  Pass the flag
    # so misspelled router-table cells (bare-path, no markdown link)
    # are caught here — without this they would only be flagged by
    # the reachability walker, forcing the orphan rule to surface
    # walk warnings.
    ref_errors, ref_passes = _check_references(
        body, entry_filename, skill_root, allow_nested_refs,
        include_router_table=(entry_filename == FILE_SKILL_MD),
    )
    errors.extend(ref_errors)
    passes.extend(ref_passes)

    return errors, passes


def validate_skill_references(
    skill_path: str, skill_root: str, entry_file: str,
    allow_nested_refs: bool = False,
) -> tuple[list[str], list[str]]:
    """Validate references in all markdown files across the skill tree.

    Walks *skill_path*, reads each ``.md`` file, and checks that all
    intra-skill references resolve from *skill_root*.  The entry file
    (*entry_file*) is skipped because it is already validated by
    :func:`validate_body`.

    Nested-reference depth checks are skipped for plain reference and
    asset files (the spec constrains depth from entry points only),
    but ``capability.md`` files are themselves entry points under the
    foundry's router-skill convention — their own one-hop boundary is
    enforced when *allow_nested_refs* is False, matching how the
    parent ``SKILL.md`` is validated.  This catches chains like
    ``SKILL.md -> capabilities/x/capability.md -> references/a.md ->
    references/b.md`` that would otherwise slip past the audit
    because the parent's own check stops at the capability boundary.
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

            # Build the cross-platform display label up front so every
            # finding (read error, nested-ref WARN) uses the POSIX form
            # — Windows runners would otherwise emit backslash paths in
            # WARN messages, which is inconsistent with the rest of the
            # codebase and breaks substring assertions in tests.
            rel_label = os.path.relpath(filepath, skill_root).replace(
                os.sep, "/",
            )
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeError) as exc:
                errors.append(
                    f"{LEVEL_WARN}: [spec] '{rel_label}' cannot be read "
                    f"({exc.__class__.__name__}: {exc})"
                )
                continue

            # Capability entry points get the same one-hop boundary
            # treatment as the parent SKILL.md — mirror the user's
            # ``--allow-nested-references`` flag.  Non-capability,
            # non-entry files are not subject to the depth rule.
            rel_parts = rel_label.split("/")
            is_capability_entry = (
                len(rel_parts) == 3
                and rel_parts[0] == DIR_CAPABILITIES
                and rel_parts[2] == FILE_CAPABILITY_MD
            )
            file_allow_nested = (
                allow_nested_refs if is_capability_entry else True
            )
            file_errors, _file_passes = _check_references(
                content, rel_label, skill_root, file_allow_nested,
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
    frontmatter, body, scalar_findings = load_frontmatter(skill_md)

    if frontmatter is None and not is_capability:
        errors.append(f"{LEVEL_FAIL}: [spec] No YAML frontmatter found (must start with ---)")
        return errors, passes

    if frontmatter and "_parse_error" in frontmatter:
        errors.append(f"{LEVEL_FAIL}: [spec] YAML parse error: {frontmatter['_parse_error']}")
        return errors, passes

    errors.extend(scalar_findings)

    # When validating the foundry itself, surface divergences detected
    # during configuration.yaml load so the meta-skill's own config is
    # held to the same standard as integrator skills.
    errors.extend(collect_foundry_config_findings(skill_path))

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
        # Skill-only frontmatter fields (license, compatibility, metadata.*)
        # — emit INFO redirect when a capability declares any of them.
        cap_rel = os.path.relpath(skill_md, skill_root).replace(os.sep, "/")
        sof_errors, sof_passes = validate_capability_skill_only_fields(
            frontmatter, cap_rel,
        )
        errors.extend(sof_errors)
        passes.extend(sof_passes)
        body_errors, body_passes = validate_body(body, skill_md, skill_root, allow_nested_refs)
        errors.extend(body_errors)
        passes.extend(body_passes)
        # Validate references in all .md files across the skill tree
        # (walk skill_root, not skill_path, so the entire skill is scanned)
        ref_errors, ref_passes = validate_skill_references(
            skill_root, skill_root, skill_md, allow_nested_refs,
        )
        errors.extend(ref_errors)
        passes.extend(ref_passes)
        # Tool coherence is owned by the skill-level invocation (the
        # rule's scope is the whole skill tree, not a single
        # capability), so this branch deliberately does not run it.
        # Validating the parent SKILL.md exercises the same files plus
        # ``scripts/`` presence — running it here would either scope
        # incorrectly (only one capability) or duplicate findings
        # already produced for the parent.  Emit an explicit pass so
        # JSON consumers see the rule was considered rather than
        # silently absent from the report.
        passes.append(
            "tool-coherence: skipped (capability mode — "
            "run on parent SKILL.md)"
        )
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
        skill_path, skill_root, skill_md, allow_nested_refs,
    )
    errors.extend(sref_errors)
    passes.extend(sref_passes)

    # Validate Codex configuration (agents/openai.yaml) when present
    codex_errors, codex_passes = validate_codex_config(skill_path)
    errors.extend(codex_errors)
    passes.extend(codex_passes)

    # Single discovery pass — read every ``capabilities/**/capability.md``
    # frontmatter once and share the result across the three rules
    # that consume it (coherence per-file effective set, aggregation
    # union, skill-only-fields walk).  Avoids re-reading the same
    # files three times in a single validation run.
    capability_data = load_capability_data(skill_path)

    # Tool coherence — fence and `scripts/` signals must match
    # ``allowed-tools``.  Top-level peer call (not nested under the
    # `allowed-tools` conditional) so the rule fires even when the
    # frontmatter omits the field entirely.
    coh_errors, coh_passes = validate_tool_coherence(
        skill_path, frontmatter, capability_data=capability_data,
    )
    errors.extend(coh_errors)
    passes.extend(coh_passes)

    # Bottom-up aggregation — parent SKILL.md ``allowed-tools`` must be
    # a superset of the union of capability-declared sets.  Layered on
    # top of the per-file coherence check above: coherence catches
    # fence/scripts signals, aggregation catches frontmatter
    # declarations.
    agg_errors, agg_passes = aggregate_capability_allowed_tools(
        skill_path, frontmatter, capability_data=capability_data,
    )
    errors.extend(agg_errors)
    passes.extend(agg_passes)

    # Per-capability skill-only-fields INFO redirect.  Iterates the
    # discovery dict above so all three rules agree on which
    # capability files contribute findings.  Nested capabilities are
    # themselves a separate FAIL in the audit's nesting-depth rule,
    # but if a nested capability does exist and declares a
    # skill-only field, the redirect still fires here.
    for cap_md, record in sorted(capability_data.items()):
        cap_fm = record.frontmatter
        if cap_fm and "_parse_error" in cap_fm:
            # Parse error already surfaces via the audit / capability
            # validator paths; skip silently here to avoid double-FAIL.
            continue
        cap_rel = os.path.relpath(cap_md, skill_path).replace(os.sep, "/")
        sof_errors, sof_passes = validate_capability_skill_only_fields(
            cap_fm, cap_rel,
        )
        errors.extend(sof_errors)
        passes.extend(sof_passes)

    # Orphan-reference rule — flag files under references/ that no
    # SKILL.md or capability.md reaches via the configured body
    # reference patterns.  Skipped in capability mode (the rule's
    # scope is the whole skill tree, not a single capability) — the
    # parent SKILL.md invocation owns the check.  Running it on a
    # capability directory would treat that directory as a standalone
    # skill root and emit false orphan WARNs for any capability-local
    # ``references/`` files.  The rule is independent of
    # --allow-nested-references: that flag suppresses depth warnings;
    # this rule only asks whether a file is reachable at all.
    #
    # validate_skill targets a single skill — there is no enclosing
    # skills/ directory, so allowed_orphans entries keyed
    # ``skills/<name>/...`` have nothing to disambiguate.  Pass
    # audit_root=None so those entries are skipped, matching the
    # documented hybrid-keying semantics.
    #
    # Suppress reachability-walk diagnostics: validate_skill_references
    # (above) already walks the same graph and emits equivalent broken-
    # reference WARNs.  Letting find_orphan_references re-emit them
    # would double the WARN count for every broken intra-skill link.
    # The suppression stays safe because validate_body invokes
    # _check_references on SKILL.md with include_router_table=True,
    # so even router-table-only cells (which the body regex misses)
    # are validated for existence before reaching this rule.
    if not is_capability:
        orphan_findings = find_orphan_references(
            skill_path,
            ALLOWED_ORPHANS,
            audit_root=None,
            skill_audit_prefix=os.path.basename(os.path.abspath(skill_path)),
            surface_walk_warnings=False,
        )
        if orphan_findings:
            errors.extend(orphan_findings)
        else:
            passes.append("orphan references: none under references/ trees")

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
    parser.add_argument(
        "--check-prose-yaml",
        action="store_true",
        dest="check_prose_yaml",
        help=(
            "Validate ```yaml fences in SKILL.md, capabilities/**/*.md, "
            "and references/**/*.md.  See "
            "references/authoring-principles.md for the convention."
        ),
    )
    parser.add_argument(
        "--foundry-self",
        action="store_true",
        dest="foundry_self",
        help=(
            "Run this skill as the foundry runs itself — currently "
            "implies --check-prose-yaml.  Silently no-op when the flag "
            "stack already includes the underlying check."
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
    # --foundry-self is a superset trigger; passing both flags is a
    # no-op.  --foundry-self on a non-foundry target is silently
    # equivalent to --check-prose-yaml.
    check_prose: bool = args.check_prose_yaml or args.foundry_self

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

    # Prose-YAML doc-snippet check.  Always populate the
    # yaml_conformance JSON slot so consumers don't need a
    # nullability branch.
    prose_findings: list[dict] = []
    prose_checked = 0
    if check_prose and is_capability:
        # Capability mode only sees a single ``capability.md`` body,
        # so the skill-root glob walk the prose check needs does not
        # apply.  Surface this as an INFO rather than silently
        # dropping the flag.
        errors.append(
            "INFO: [foundry] --check-prose-yaml has no effect with "
            "--capability; run against the parent skill root to scan "
            "prose fences"
        )
    elif check_prose:
        prose_findings, prose_checked, per_file = collect_prose_findings(
            os.path.abspath(skill_path)
        )
        if verbose and not json_output:
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
            "yaml_conformance": yaml_conformance_slot,
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
