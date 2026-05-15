---
name: skill-system-foundry
description: >
  Designs and evolves AI-agnostic skill systems with skills, capabilities, and
  roles. Triggers on skill/capability creation, role definition, router
  migration, consistency audits, or token efficiency.
allowed-tools: Bash Read Write Edit
compatibility: Requires Python 3.12+ (stdlib only) for validation, scaffolding, and bundling scripts.
license: MIT
metadata:
  author: Milan Horvatovič
  version: 1.1.0
  spec: agentskills.io
---

# Skill System Foundry

A meta-skill for constructing and evolving AI-agnostic skill systems.

This skill governs the creation and maintenance of a two-layer architecture: **skills** (with optional capabilities) and **roles**. All skills produced by this system follow the [Agent Skills specification](references/agentskills-spec.md). They incorporate [authoring best practices](references/authoring-principles.md) from official vendor guides. Role contracts align with [tool integration guidance](references/tool-integration.md#convention-coexistence) for seamless deployment across platforms.

**Important:** Capabilities are optional, granular sub-skills within a parent skill. Do not create capabilities by default. Only introduce them when the integrator explicitly asks for them or when the domain clearly demands decomposition (3+ distinct operations with different trigger contexts). Start with a standalone skill; evolve to router+capabilities only when justified.

## Architecture Overview

The skill system follows a strict two-layer architecture — **skills** and **roles**. Dependencies flow strictly downward — never the reverse. A capability must never know it's being orchestrated. A role references skills but never other roles.

The dependency direction governs **references between layers**, not where orchestration begins. Two valid orchestration paths exist:

```
Path 1:  orchestration skill → roles → skills (with optional capabilities)
Path 2:  skill (standalone or router) → role(s) → skill's capabilities
```

- **Path 1 — Coordination-only skill.** A lean standalone skill sequences roles across domains. Contains no domain logic.
- **Path 2 — Self-contained skill.** A domain skill loads one or more roles for interactive workflow logic. The skill owns capabilities; roles provide responsibility, authority, and constraints, plus handoff rules, sequencing, and interaction patterns.

See [`references/architecture-patterns.md`](references/architecture-patterns.md#orchestration-skills) for decision checklists and constraints per path.

Each layer has a clear responsibility:

- **Skills** — Canonical, AI-agnostic knowledge and logic. Conform to the Agent Skills specification. A skill handles a task directly (standalone) or optionally routes to capabilities for complex domains that warrant decomposition.
- **Roles** — Canonical, AI-agnostic orchestration contracts. A role defines responsibility, authority, and constraints, plus handoff rules and workflow sequencing while composing multiple skills/capabilities.

## Capabilities

Route to the appropriate capability based on the task:

| Capability | Trigger | Path |
|---|---|---|
| skill-design | Create a skill, capability, role, or manifest; decide architecture; write descriptions | capabilities/skill-design/capability.md |
| validation | Validate a skill against the spec; audit system consistency | capabilities/validation/capability.md |
| migration | Migrate flat skills to the router+capabilities pattern | capabilities/migration/capability.md |
| bundling | Package a skill as a zip bundle for distribution | capabilities/bundling/capability.md |
| deployment | Deploy to tools; set up wrappers or symlinks; use tool-specific extensions | capabilities/deployment/capability.md |

Read only the relevant capability file. Do not load multiple capabilities unless the task explicitly spans them.

## Shared Resources

Shared resources live at the skill root and are referenced by capabilities via relative paths. Each capability's tail `## Key Resources` block lists cross-cutting resources with **load triggers** (when to read, not what they contain); action-specific resources are linked inline at the body step where they apply. The router indexes directories, capabilities index files.

### references/ — Guidance loaded on demand by capabilities

Cross-cutting reference material shared across capabilities. Capabilities reference these by relative path.

### assets/ — Templates for scaffolding new components

Skill, capability, role, and manifest templates copied and filled in when creating new components.

### scripts/ — Validation, scaffolding, bundling, and measurement tools

Six entry points (`validate_skill.py`, `audit_skill_system.py`, `scaffold.py`, `bundle.py`, `stats.py`, `yaml_conformance_report.py`) and shared library modules. All entry points support `--json` for machine-readable output.

`stats.py` reports two byte-based proxies for a skill's context cost: `discovery_bytes` (the SKILL.md frontmatter block) and `load_bytes` (SKILL.md plus every transitively reachable capability and reference file, with `scripts/` and `assets/` excluded). Bytes are a deterministic on-disk signal, not tokenizer-accurate — use the trend across edits, not the absolute number across models.

## Core Principles

### 1. Agent Skills Specification Compliance

All skills must conform to the Agent Skills specification (agentskills.io). Every registered skill directory contains a `SKILL.md` with valid YAML frontmatter. The `name` field matches the parent directory name, lowercase + hyphens only, max 64 chars. The `description` field is max 1024 chars and describes both what the skill does and when to trigger it. Third-person voice is a foundry convention, not a spec requirement.

Note: capabilities are discovery-internal sub-skills. Their entry point is `capability.md`. Capability frontmatter is optional (use it when portability/promotion to standalone is likely).

Progressive disclosure is respected at all levels:
- **Level 1: Metadata** (~100 tokens) — name + description, always in context
- **Level 2: Instructions** (<5000 tokens / recommended max 500 lines) — loaded when triggered
- **Level 3: Resources** (unlimited) — scripts, references, assets, on demand

### 2. Token Economy

Discovery tokens are always present and expensive. Execution tokens are only paid when activated. Register one skill per domain, not one per capability. Keep router SKILL.md files lean. Push detail into capabilities or references. Prefer a standalone skill until the domain justifies capabilities.

### 3. Conciseness

The model is already smart. Only add context it doesn't already have. Challenge each piece of information: "Does the model really need this explanation?" See [`references/authoring-principles.md`](references/authoring-principles.md) for detailed guidance.

### 4. Degrees of Freedom

Match specificity to the task's fragility. High freedom for flexible tasks, low freedom for fragile operations. See [`references/authoring-principles.md`](references/authoring-principles.md).

### 5. Write Once, Adapt Everywhere

Domain knowledge is authored exactly once in the canonical layer (skills and roles). When domain knowledge changes, one file changes. Tool-specific deployment pointers, if needed, are optional user-managed customizations. **Default to symlinks** — zero-maintenance, single source of truth, alignment with this principle. Fall back to wrapper files only when the team includes Windows contributors without Developer Mode or the tool requires tool-specific adaptation in its pointer. See [`references/tool-integration.md`](references/tool-integration.md#symlink-based-deployment-pointers) for the decision guide.

## Gotchas

The most common foot-guns when working with this meta-skill. Surfaced here because by the time you'd think to load `references/anti-patterns.md`, you've usually already hit them. Each entry links to the long-form treatment.

- **Premature capability decomposition.** Capabilities are optional. Default to standalone. Only split when 3+ distinct operations with mutually exclusive triggers exist. See [anti-patterns.md#premature-capability-creation](references/anti-patterns.md#premature-capability-creation).
- **Sibling capability references.** Capabilities are independent — never reference a sibling capability. Cross-capability orchestration is a role's job. See [anti-patterns.md#capability-aware-capabilities](references/anti-patterns.md#capability-aware-capabilities).
- **Deep nesting.** Two levels max (router → capability). Need sub-routers? Split into separate top-level skills. See [anti-patterns.md#deep-nesting](references/anti-patterns.md#deep-nesting).
- **Mixing file-reference conventions.** Markdown links resolve from the file that contains them — standard markdown semantics, not a foundry-specific rule. From a capability entry point (`capability.md`), capability-local references use `references/<file>`; references to shared skill-root resources use `../../<dir>/<file>`. From a nested capability reference file (`capabilities/<name>/references/foo.md`), the offsets shift accordingly. See [path-resolution.md](references/path-resolution.md).
- **Descriptions as documentation, not triggers.** The `description` field is the primary discovery mechanism. Write it for the model selecting between 100+ skills, not as a README summary. Be specific, third-person, include trigger phrases. See [authoring-principles.md#writing-descriptions](references/authoring-principles.md#writing-descriptions).
- **Symlinks without team OS verification.** Symlinks are the default deployment-pointer mechanism, but degrade silently on Windows checkouts without Developer Mode (or `git config core.symlinks=true`). Verify the team's OS mix before defaulting; fall back to wrapper files when in doubt. See [anti-patterns.md#symlinks-without-team-platform-verification](references/anti-patterns.md#symlinks-without-team-platform-verification).
