# GitHub Copilot Instructions

Review changes as an **Agent Skills expert**, focusing on the **Agent Skills open format** specification and ensuring this repository stays a well-structured, specification-compliant **meta-skill for building AI-agnostic skill systems**.

## Project Context

Skill System Foundry is a meta-skill that teaches AI agents how to create, validate, and evolve skill systems. It follows a two-layer architecture: **skills** (with optional capabilities) and **roles**. The repository contains reference documentation, templates, and Python validation scripts — no application code.

**Repository structure:**
- `skill-system-foundry/SKILL.md` — the meta-skill entry point
- `skill-system-foundry/references/` — guidance documents
- `skill-system-foundry/assets/` — templates for scaffolding
- `skill-system-foundry/scripts/` — validation, scaffolding, and bundling tools (entry points)
- `skill-system-foundry/scripts/lib/` — shared script logic (constants, validation, discovery, references, bundling)

## Agent Skills Format Compliance

- Every registered skill directory must contain a `SKILL.md` with YAML frontmatter
- `name`: lowercase letters, numbers, and hyphens only, max 64 characters, must match the parent directory name exactly, no leading/trailing/consecutive hyphens. Note: "anthropic" and "claude" are reserved on Anthropic platforms (produces WARN, not FAIL)
- `description`: max 1024 characters, written in third person, must state what the skill does and when to trigger it, no XML tags
- Optional frontmatter fields: `allowed-tools` (space-delimited tool names), `compatibility` (max 500 chars, environment requirements), `license` (license name or reference), `metadata` (arbitrary key-value map)
- Progressive disclosure must be preserved: metadata (Level 1) → instructions (Level 2) → resources (Level 3)
- `SKILL.md` body should stay under ~5k tokens; move deep dives into `references/`
- Cross-references from `SKILL.md` must stay one level deep — no chains through referenced files

## Repository-Specific Constraints

### Architecture Rules

- The system has exactly two layers: **skills** (with optional capabilities) and **roles** — no additional layers
- Dependencies flow strictly top-down: `roles → skills → capabilities` — never the reverse
- A capability must not reference its parent router or sibling capabilities
- Maximum nesting depth: router → capability (two levels) — no sub-routers
- A role must compose 2+ skills or capabilities — no single-skill passthrough roles
- A role must define: responsibility, authority, constraints, and handoff rules

### Platform-Agnostic Authoring

- Core content (`SKILL.md` body, `references/`, `assets/`) must stay platform-neutral — no assumptions about a specific AI tool
- Platform-specific details belong in their respective extension docs (`claude-code-extensions.md`, `codex-extensions.md`, `cursor-extensions.md`)
- Platform restrictions (e.g., Anthropic's reserved-word rule) are enforced by validation scripts, not by hardcoding platform names in skill content

### Capability Policy

- Capabilities are optional and not discovery-registered — frontmatter is optional for capabilities
- Do not introduce capabilities unless 3+ distinct operations with mutually exclusive triggers exist
- Prefer standalone skills; evolve to router + capabilities only when justified

## Automated Validation Coverage

The following checks are enforced by `validate_skill.py` and `audit_skill_system.py`. Do not duplicate these in review — focus on what the scripts cannot catch.

**`validate_skill.py`** (single skill):
- Frontmatter presence and YAML syntax
- `name`: length, format (lowercase alphanumeric + hyphens), directory match, reserved words, consecutive hyphens
- `description`: length limit, XML tags, person/voice (third-person heuristic)
- Body: line count, nested reference depth
- Directories: recognized directory names

**`audit_skill_system.py`** (full system):
- Spec compliance across all registered skills
- Capability isolation (flags capabilities that look discovery-registered)
- Dependency direction (no upward references from capabilities or skills to roles)
- Nesting depth (no sub-capabilities)
- Shared resource usage (shared files used by 2+ capabilities)
- Manifest consistency (declared skills/capabilities exist on disk)

## Review Focus Areas

Focus review on what automated validation cannot catch:

1. **Description quality** — Does the description include trigger phrases and keyword coverage so agents activate the skill reliably? A vague "Helps with projects" is worse than "Manages project timelines, tracks milestones, generates status reports. Use when asked to plan sprints, check deadlines, or summarize progress."
2. **Progressive disclosure** — Is content in the right layer? Does `SKILL.md` duplicate reference material that should be loaded on demand? Are deeper topics in `references/` and linked appropriately?
3. **Architecture justification** — Are capabilities warranted (3+ distinct operations with mutually exclusive triggers), or would a standalone skill suffice?
4. **Role completeness** — Does each role compose 2+ skills with responsibility, authority, constraints, and handoff rules? (Not automated)

Only flag issues with high confidence. If uncertain whether something is a problem, do not comment — the validation scripts catch mechanical errors, so review should focus on semantic and architectural judgment.

When commenting, use this format:
1. **Problem** — what is wrong (1 sentence)
2. **Why it matters** — impact on agents, users, or maintainability (1 sentence, omit if obvious)
3. **Suggested fix** — concrete action or code snippet

## Common Issues to Flag

These are issues the validation scripts do not catch:

- `description` that is technically valid but vague — missing trigger phrases, keyword coverage, or context about when to activate
- `SKILL.md` that inlines content belonging in `references/` (progressive disclosure violation)
- Reversed dependency direction not caught by regex (e.g., a capability's prose describing when to "hand back to the router")
- Capability introduced without 3+ distinct operations or mutually exclusive triggers
- Single-skill passthrough role or role missing responsibility/authority/constraints/handoff rules
- Inconsistent terminology between `SKILL.md` and its reference files
- Platform-specific assumptions in core content (e.g., Claude-only behavior in `SKILL.md` body or reference files that should be platform-neutral)

---

**Remember:** Review as an Agent Skills expert. The validation scripts handle mechanical checks — focus your review on description quality, progressive disclosure, architecture justification, and semantic consistency.
