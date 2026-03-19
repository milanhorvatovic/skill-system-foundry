---
name: skill-authoring
description: >
  Guides the creation, evolution, and validation of skills within the
  Skill System Foundry ecosystem. Triggers when asked to create a new skill,
  scaffold a skill from a template, add capabilities to an existing skill,
  migrate a standalone skill to a router pattern, define a role, write or
  improve a skill description, set up a manifest, validate a skill against
  the Agent Skills specification, audit a skill system, bundle a skill for
  distribution, or decide between standalone and router architectures.
  Also triggers on questions about skill structure, progressive disclosure,
  token economy, or cross-platform deployment.
---

# Skill Authoring

Guides the full lifecycle of skill creation and evolution within the Skill System Foundry ecosystem — from initial scaffolding through validation, bundling, and distribution.

This skill encodes the two-layer architecture (skills and roles), the Agent Skills specification compliance rules, and the cross-platform authoring principles that the foundry enforces.

## Architecture Overview

The skill system has exactly two layers:

- **Skills** — canonical, AI-agnostic knowledge and logic. A skill handles a task directly (standalone) or routes to capabilities for complex domains
- **Roles** — canonical, AI-agnostic orchestration contracts. A role defines responsibility, authority, constraints, and handoff rules while composing multiple skills or capabilities

Dependencies flow strictly downward: `roles → skills → capabilities`. A capability must never know it is being orchestrated. A role must never reference other roles.

### Two Orchestration Paths

```
Path 1:  orchestration skill → roles → skills (with optional capabilities)
Path 2:  skill (standalone or router) → role(s) → skill's capabilities
```

- **Path 1** — a lean standalone skill sequences roles across domains. Contains no domain logic
- **Path 2** — a domain skill loads one or more roles for interactive workflow logic

## Creating a New Skill

### Step 1: Decide Architecture

Start with a standalone skill. Evolve to router + capabilities only when justified.

**Use standalone when:**
- The domain has a single coherent task
- All operations share the same trigger context
- The skill fits comfortably under 500 lines

**Use router + capabilities when:**
- 3+ distinct operations exist with mutually exclusive trigger contexts
- Different operations need different tool permissions
- The domain is large enough that a single file would exceed 500 lines

### Step 2: Scaffold

Use the scaffolding tool to generate from a template:

```bash
cd skill-system-foundry
python scripts/scaffold.py skill <skill-name> --root /path/to/project/.agents
```

Optional directories are not created by default. Add them when needed:
- `--with-references` — guidance documents
- `--with-scripts` — executable tools
- `--with-assets` — templates, icons, fonts

For roles:
```bash
python scripts/scaffold.py role <role-name> --root /path/to/project/.agents
```

### Step 3: Write the Entry Point

Every registered skill directory contains a `SKILL.md` with YAML frontmatter.

**Required frontmatter:**
- `name` — lowercase + hyphens, max 64 chars, matches directory name
- `description` — max 1024 chars, third person, states what AND when

**Optional frontmatter:**
- `allowed-tools` — space-delimited tool names
- `compatibility` — environment requirements (max 500 chars)
- `license` — SPDX identifier
- `metadata` — key-value map (author, version, spec)

Use folded block scalar (`>`) for multi-line descriptions to avoid YAML quoting issues.

### Step 4: Write the Body

The body is the Level 2 content — loaded when the skill triggers. Keep it under 500 lines.

**Body structure for standalone skills:**
1. One-sentence purpose statement
2. Core instructions (what to do, step-by-step)
3. Quick reference table pointing to bundled resources
4. Links to `references/`, `scripts/`, `assets/` with guidance on when to read each

**Body structure for router skills:**
1. One-sentence purpose statement
2. Architecture overview (layers, dependencies)
3. Core principles (spec compliance, token economy, conciseness)
4. Capability routing table mapping trigger contexts to capabilities
5. The router does not list individual references, assets, or scripts — those are the capabilities' concern

### Step 5: Write the Description

The description is the primary trigger mechanism. It must be "pushy" — keyword-rich and specific.

Include:
1. **What** — concrete verbs and nouns describing operations
2. **When** — user intent phrases and trigger keywords
3. **Distinguishers** — what separates this from related skills

**Good:** "Manages deployment workflows — runs pre-deploy checks, executes deployments to staging and production, and handles rollbacks. Activates when the user mentions deploying, releasing, or rolling back."

**Bad:** "Helps with deployments."

## Adding Capabilities

Capabilities are optional sub-skills within a parent router. Their entry point is `capability.md` (lowercase). Capability frontmatter is optional — use it when promotion to standalone is likely.

Only introduce capabilities when:
- 3+ distinct operations have different trigger contexts
- Different operations need different tool permissions
- Decomposition genuinely reduces complexity

Place capabilities in `<skill>/capabilities/<capability-name>/capability.md`.

### Capability Self-Sufficiency

Each capability must be self-sufficient — an agent loading a capability has enough context to complete the task without reading the router or sibling capabilities. This means:
- Inline the step-by-step workflow directly in `capability.md`
- Reference shared resources (`references/`, `scripts/`, `assets/`) by relative path from the capability
- Do not assume the agent has read the router's overview or principles

### Shared Resources Stay at Skill Root

Scripts, references, and assets that serve multiple capabilities stay at the skill root — do not duplicate them into capability directories. This is especially important when:
- A `lib/` dependency chain connects entry points (all scripts import from shared modules)
- Reference documents (e.g., `architecture-patterns.md`) serve multiple capabilities
- Templates in `assets/` are used across different operations

Capabilities reference shared resources via relative paths (e.g., `../../references/authoring-principles.md`). Only create capability-specific resources (under `<capability>/references/`) when the content is truly exclusive to that capability.

### Dissolving Reference Files into Capabilities

When migrating from standalone to router, large workflow reference files can be dissolved — each section absorbed into the relevant capability. The pattern:

1. Map each section of the reference file to exactly one capability
2. Inline each section's content into the corresponding `capability.md`
3. Extract platform-specific or lengthy content into capability-level `references/` if needed
4. Remove the original reference file
5. Update all cross-references across the repository

This eliminates a layer of indirection: agents load the capability and immediately have the workflow, rather than loading the capability which points to a reference file.

### Capability Isolation Rules

A capability must never reference its parent router or sibling capabilities. The one exception: a capability may include a relative path to another capability when explaining a cross-cutting workflow (e.g., deployment referencing bundling for Claude.ai upload).

## Defining Roles

A role must:
- Compose 2+ skills or capabilities
- Define responsibility, authority, constraints, and handoff rules
- Never reference other roles

When orchestration spans multiple roles, a coordination skill (Path 1) sequences them.

Place roles in `roles/<group>/<n>.md` using system-root-relative paths.

## Validation

### Single Skill

```bash
python scripts/validate_skill.py /path/to/skill [--verbose] [--json]
```

Checks: frontmatter presence, name format and directory match, description length and voice, body line count, reference depth, directory names.

### Full System Audit

```bash
python scripts/audit_skill_system.py /path/to/system-root
```

Checks: spec compliance across all skills, capability isolation, dependency direction, nesting depth, shared resource usage, manifest consistency.

### Capabilities

```bash
python scripts/validate_skill.py /path/to/capability --capability
```

### Nested References

For meta-skills that intentionally use nested references:
```bash
python scripts/validate_skill.py /path/to/skill --allow-nested-references
```

## Bundling for Distribution

Package a skill as a self-contained zip for Claude.ai upload, Gemini CLI, or offline sharing:

```bash
python scripts/bundle.py /path/to/skill \
  --system-root /path/to/.agents --output my-skill.zip
```

## Token Economy

Discovery tokens (Level 1 metadata) are always present and expensive. Execution tokens (Level 2-3) are only paid when activated.

Rules:
- Register one skill per domain, not one per capability
- Keep router `SKILL.md` files lean
- Push detail into capabilities or references
- Prefer standalone until the domain justifies capabilities

## Progressive Disclosure

Three levels of content loading:
1. **Level 1: Metadata** (~100 tokens) — name + description, always in context
2. **Level 2: Instructions** (<5000 tokens / ~500 lines) — loaded when triggered
3. **Level 3: Resources** (unlimited) — scripts, references, assets, on demand

Move deep dives into `references/`. Keep cross-references one level deep from `SKILL.md`.

## Cross-Platform Deployment

Core content (`SKILL.md`, `references/`, `assets/`) stays platform-neutral. Platform-specific details go in extension docs.

Tools that scan `.agents/skills/` natively (Codex, Gemini CLI, Warp, OpenCode, Windsurf) need no additional configuration. For others (Claude Code, Cursor, Kiro), create thin deployment pointers — wrappers or symlinks.

## Quick Decision Guide

| Question | Answer |
|---|---|
| Standalone or router? | Standalone unless 3+ distinct operations with mutually exclusive triggers |
| Add a capability? | Only when decomposition genuinely reduces complexity |
| Add a role? | Only when orchestrating 2+ skills with clear handoff rules |
| Where to put detail? | Router for overview/principles, capabilities for workflows, `references/` for deep dives |
| Shared or capability-specific resource? | Shared at skill root if 2+ capabilities use it, capability-level if exclusive |
| Dissolve a reference file? | Yes, when each section maps cleanly to one capability with no overlap |
| How to validate? | `validate_skill.py` for single skill, `audit_skill_system.py` for system |
| How to distribute? | `bundle.py` for zip, `npx skills add` for direct install |
