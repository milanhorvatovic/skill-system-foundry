# Validation

Validate individual skills against the Agent Skills specification and audit entire skill systems for structural consistency.

## Validating a Single Skill

Run the spec validator against a skill directory:

```bash
python scripts/validate_skill.py <skill-path> [--capability] [--verbose] [--allow-nested-references] [--json]
```

- `--capability`: Validate a capability directory instead of a skill
- `--verbose`: Show all checks, not just failures
- `--allow-nested-references`: Suppress nested-reference warnings (needed for skills that intentionally cross-reference their own reference files)
- `--json`: Machine-readable output
- `--check-prose-yaml`: Validate ` ```yaml ` fences in `SKILL.md`, `capabilities/**/*.md`, and `references/**/*.md`. See [authoring-principles.md](references/authoring-principles.md) for the counter-example convention.
- `--foundry-self`: Run this skill the way the foundry runs itself (currently implies `--check-prose-yaml`).

For registered skills, the validator checks: frontmatter fields (`name`, `description`), naming conventions (lowercase + hyphens, max 64 chars, matches directory), line counts (recommended max 500 lines), and resource directory structure. In `--capability` mode it only validates the body (line counts, nested-reference rules) and, if frontmatter is present, reports name/description as informational notes without enforcing frontmatter or directory checks.

## Auditing System Consistency

Run the automated audit against a deployed system root — the directory containing a `skills/` subdirectory (e.g., `.agents/`):

```bash
python scripts/audit_skill_system.py <system-path> [--verbose] [--allow-orchestration] [--json]
```

- `--allow-orchestration`: Downgrade skill→role references from FAIL to WARN (expected for orchestration skills)

> **Note:** This is not the same as the distribution repository root. For single-skill validation, use `validate_skill.py` instead.

The script checks: spec compliance (frontmatter fields, naming, line counts), dependency direction (no upward references), role composition (2+ skills/capabilities, best-effort heuristic), nesting depth, shared resource usage, and manifest presence. Path validity and orphan detection require manual review (see checklist below).

### Manual Checklist

**Spec Compliance:**
- [ ] Every registered skill has `name` + `description` in frontmatter
- [ ] All names match directories, lowercase + hyphens, max 64 chars
- [ ] All descriptions: max 1024 chars, with triggers (third-person recommended)
- [ ] No SKILL.md exceeds 500 lines
- [ ] File references: relative paths, one level deep

**Structure:**
- [ ] No capability registered in discovery layer
- [ ] Shared resources used by 2+ capabilities
- [ ] Max 2 levels deep (router → capability)
- [ ] Roles compose 2+ skills or capabilities (automated — audit warns if < 2)
- [ ] No capability references siblings

**Dependencies:**
- [ ] Direction maintained (no upward references). Exception: orchestration skills (both paths) may reference roles intentionally.
- [ ] All role skill paths valid

**Manifest:**
- [ ] Complete and matches filesystem
- [ ] No orphaned files or phantom entries

## Key Resources

**References:**
- [agentskills-spec.md](references/agentskills-spec.md) — Agent Skills specification compliance guide

**Scripts:**
- [validate_skill.py](scripts/validate_skill.py) — Single skill spec validation
- [audit_skill_system.py](scripts/audit_skill_system.py) — Full skill system audit
- [validation.py](scripts/lib/validation.py) — Shared name/metadata/license/allowed-tools validation
- [frontmatter.py](scripts/lib/frontmatter.py) — Frontmatter extraction and body utilities
- [discovery.py](scripts/lib/discovery.py) — Component discovery for system audit
- [codex_config.py](scripts/lib/codex_config.py) — Codex agents/openai.yaml validation
