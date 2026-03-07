# Skill System Foundry — Skill Documentation

This is a **meta-skill** — a skill whose domain is building other skills. It provides the architecture, templates, validation tools, and guidance needed to construct and evolve AI-agnostic skill systems. It follows a **router-style pattern**: a lean `SKILL.md` entry point, conceptual capabilities loaded on demand via references, templates for scaffolding, and scripts for validation.

## What This Skill Does

Skill System Foundry enables an AI model to design, build, validate, and evolve a multi-layer skill system. It covers the full lifecycle — from scaffolding a new standalone skill to migrating an entire flat structure into the router+capabilities pattern, to auditing a mature skill system for consistency.

This is not a general-purpose coding skill. It is specifically scoped to the structural and architectural concerns of organizing AI-agnostic automation across multiple tools.

## Capabilities (Optional)

The skill supports nine optional operations (conceptual capabilities — no literal `capabilities/` directory exists for this meta-skill). Most map to a distinct workflow defined in [`references/workflows.md`](references/workflows.md); others are advisory and reference-driven. These operations are **not required** — only introduce them when the integrator asks about them or when the task clearly warrants it. A standalone skill is the default starting point; capabilities are added incrementally as the domain grows.

| # | Capability | When to Use |
|---|------------|-------------|
| 1 | [Create Skills](#1-create-skills) | Add a new domain of automation |
| 2 | [Create Capabilities](#2-create-capabilities-optional) | Add operations under an existing router skill |
| 3 | [Create Roles](#3-create-roles) | Coordinate across multiple skills or capabilities |
| 4 | [Deploy to Tools](#4-deploy-to-tools-optional) | Make skills accessible in tools that need pointers |
| 5 | [Migrate Structures](#5-migrate-structures) | Convert flat skills to router+capabilities pattern |
| 6 | [Validate Skills](#6-validate-skills) | Check a skill against the Agent Skills specification |
| 7 | [Audit Skill Systems](#7-audit-skill-systems) | Check full system for structural consistency |
| 8 | [Maintain the Manifest](#8-maintain-the-manifest) | Keep manifest accurate after structural changes |
| 9 | [Reason About Architecture](#9-reason-about-architecture) | Evaluate token economy and structural trade-offs |

### 1. Create Skills

Create standalone or router skills that conform to the Agent Skills specification. Standalone skills handle focused tasks with a single `SKILL.md`. Router skills manage complex domains by dispatching to capabilities.

**When to use:** The user wants to add a new domain of automation (e.g., "create a skill for `<domain>`", "I need a skill for `<domain>` operations").

**Key resources:**
- `assets/skill-standalone.md` — Template for standalone skills
- `assets/skill-router.md` — Template for router skills
- [`references/authoring-principles.md`](references/authoring-principles.md) — Shared skill authoring principles
- [`references/architecture-patterns.md`](references/architecture-patterns.md) — Standalone vs router decisions
- [`references/agentskills-spec.md`](references/agentskills-spec.md) — Specification compliance

### 2. Create Capabilities (Optional)

Add optional capabilities under existing router skills. Each capability is a self-contained granular sub-skill with its own `capability.md` and optional resources. Capabilities are never registered in the discovery layer.

**When to use:** Only when the integrator explicitly requests it or when a router skill genuinely needs a new distinct operation (e.g., "add a `<capability>` capability to the `<domain>` skill"). Do not proactively create capabilities unless the domain clearly demands decomposition.

**Key constraints:**
- No sibling references — capabilities must not call other capabilities
- No discovery registration — only the parent router is visible
- Self-contained — each capability has its own resources

**Why `capability.md` instead of `SKILL.md`?** This convention is a preventive naming guardrail, not a fix to tool behavior.

- **Prevents:**
  - Codex startup warnings from scanning capability `SKILL.md` files without discovery frontmatter
  - Accidental capability promotion to standalone discovery entries when frontmatter is added only to silence warnings
  - Claude zip packaging conflicts caused by case-insensitive `SKILL.md` matching (`skill.md` still collides)

- **Does not solve:**
  - Tool behavior itself (Codex/Claude rules remain unchanged)
  - Migration automatically (existing files still need one-time renaming)
  - Core architecture constraints (router boundaries, no sibling-capability references)

**Key resources:**
- `assets/capability.md` — Template for capabilities
- [`references/directory-structure.md`](references/directory-structure.md) — Layout conventions

### 3. Create Roles

Define orchestration patterns that compose multiple skills or capabilities into interactive workflows. A role defines responsibility, authority, and constraints, plus handoff rules and coordination logic.

**When to use:** A task requires coordinating across multiple skills (e.g., "create a `<role>` role that coordinates `<skill-a>`, `<skill-b>`, and `<skill-c>` skills").

**Key constraints:**
- Should explicitly define responsibility, authority, constraints, and handoff rules
- Must compose two or more skills or capabilities, or add meaningful interaction logic
- Must not be a thin passthrough to a single capability
- Must reference skills by system-root-relative path (for example, `skills/<domain>/SKILL.md`)

**Key resources:**
- `assets/role.md` — Template for roles

### 4. Deploy to Tools (Optional)

Create thin deployment pointers for tools that do not natively scan the canonical skill location, or package a skill as a self-contained zip bundle for direct upload to surfaces like Claude.ai.

**When to use:** A skill needs to be accessible from a tool that does not scan `.agents/skills/` natively (e.g., Claude Code, Cursor, Kiro under the recommended layout), or you want to distribute a skill as a zip bundle for Claude.ai upload, Gemini CLI, or offline sharing.

**Key resources:**
- [`references/tool-integration.md`](references/tool-integration.md) — Tool-specific paths, formats, deployment guidance, and zip bundle packaging
- [`references/workflows.md`](references/workflows.md#packaging-a-skill-as-a-zip-bundle) — Step-by-step bundle packaging procedure

### 5. Migrate Structures

Convert existing flat skill structures into the router+capabilities pattern. This consolidates duplicate logic, reduces discovery tokens, and establishes proper layering.

**When to use:** An existing set of related skills should be unified under a single router (e.g., "these related `<domain>` skills should be capabilities under one router").

**Key resources:**
- [`references/workflows.md`](references/workflows.md) — Step-by-step migration procedure
- [`references/anti-patterns.md`](references/anti-patterns.md) — Common migration mistakes

### 6. Validate Skills

Check individual skills against the Agent Skills specification. Validates frontmatter fields, directory structure, line counts, naming conventions, and resource organization.

**When to use:** After creating or modifying a skill, before deployment.

**Key resources:**
- `scripts/validate_skill.py` — Single skill validation
- [`references/agentskills-spec.md`](references/agentskills-spec.md) — What the validator checks

### 7. Audit Skill Systems

Perform a structural audit across the entire skill system. Checks dependency direction, nesting depth, shared resource usage, and manifest presence.

**When to use:** Periodically, or when structural drift is suspected (e.g., "audit the skill system", "check for consistency issues").

**Key resources:**
- `scripts/audit_skill_system.py` — Full skill system audit
- [`references/workflows.md`](references/workflows.md) — Audit procedure and checklist

### 8. Maintain the Manifest

Keep the manifest YAML file accurate as components are added, removed, or restructured. The manifest is the single source of truth for the skill system's wiring.

**When to use:** After any structural change — new skill, new capability, new role, or any reorganization.

**Key resources:**
- `assets/manifest.yaml` — Manifest schema and template

### 9. Reason About Architecture

Analyze token economy trade-offs, granularity decisions, and structural evolution. This is the advisory capability — helping decide whether a skill should be standalone or a router, whether a role is justified, or how to optimize discovery cost.

**When to use:** The user is planning or evaluating structural decisions (e.g., "should this be a router or standalone?", "how do I reduce my discovery tokens?").

**Key resources:**
- [`references/architecture-patterns.md`](references/architecture-patterns.md) — Standalone vs router decisions
- [`references/anti-patterns.md`](references/anti-patterns.md) — What to avoid

## File Structure

```
skill-system-foundry/
├── README.md                              ← this file
├── SKILL.md                               ← router entry point (Agent Skills specification)
├── references/                            ← guidance loaded into context on demand
│   ├── authoring-principles.md             ← shared skill authoring principles
│   ├── architecture-patterns.md           ← standalone vs router decisions
│   ├── tool-integration.md                ← tool-specific discovery, deployment, and integration
│   ├── agentskills-spec.md                ← specification compliance
│   ├── claude-code-extensions.md          ← Claude Code frontmatter and features
│   ├── codex-extensions.md                ← Codex discovery and agents/openai.yaml
│   ├── cursor-extensions.md               ← Cursor cross-vendor discovery
│   ├── anti-patterns.md                   ← common mistakes and how to avoid them
│   ├── directory-structure.md             ← layout conventions
│   └── workflows.md                       ← creation, migration, audit procedures
├── assets/                                ← templates copied when creating components
│   ├── skill-standalone.md                ← standalone skill template
│   ├── skill-router.md                    ← router skill template
│   ├── capability.md                      ← capability template
│   ├── role.md                            ← role template
│   └── manifest.yaml                      ← manifest schema template
└── scripts/                               ← executable validation, scaffolding, and packaging
    ├── __init__.py                        ← package marker
    ├── lib/                               ← shared library modules
    │   ├── __init__.py                    ← package marker (re-exports public API)
    │   ├── configuration.yaml             ← validation rules, domain policy, and bundle config
    │   ├── constants.py                   ← centralized constants loaded from configuration
    │   ├── validation.py                  ← shared name validation logic
    │   ├── yaml_parser.py                 ← lightweight YAML-subset parser
    │   ├── frontmatter.py                 ← frontmatter extraction and body utilities
    │   ├── reporting.py                   ← error categorization and formatted output
    │   ├── discovery.py                   ← component discovery (skills, roles)
    │   └── references.py                  ← reference scanning, resolution, graph traversal
    ├── validate_skill.py                  ← single skill spec validation
    ├── audit_skill_system.py              ← full skill system audit
    ├── scaffold.py                        ← component scaffolding from templates
    └── bundle.py                          ← bundle a skill into a self-contained zip bundle
```

### References

Reference files are loaded into context when the model needs guidance for a specific task. They are never loaded at discovery time — only when the skill triggers and the task requires that specific knowledge.

| File                      | Purpose                                                           |
|---------------------------|-------------------------------------------------------------------|
| `authoring-principles.md` | Shared skill authoring principles: conciseness, descriptions, degrees of freedom, progressive disclosure, with provenance table |
| `architecture-patterns.md`| Skill-system-specific architecture decisions: standalone vs router, capability decomposition, orchestration skills (both paths) |
| `tool-integration.md`     | Tool-specific details for all supported tools (Claude Code, Codex, Cursor, Gemini CLI, Warp, OpenCode, Windsurf, Kiro, and non-Agent-Skills tools): discovery paths, deployment pointers, activation patterns, and known limitations |
| `agentskills-spec.md`     | Agent Skills specification compliance: frontmatter requirements, naming rules, line limits, and directory conventions |
| `claude-code-extensions.md` | Claude Code-specific frontmatter, subagent execution, dynamic context, string substitutions |
| `codex-extensions.md`     | Codex agents/openai.yaml, six-level discovery hierarchy, invocation methods |
| `cursor-extensions.md`    | Cursor cross-vendor discovery paths, rules system, AGENTS.md support |
| `anti-patterns.md`        | Common mistakes organized by category: system architecture (premature capabilities, deep nesting, role misuse) and skill authoring (over-explaining, inconsistent terminology, spec drift) |
| `directory-structure.md`  | Canonical directory layout for standalone skills, router skills, roles, and the system root |
| `workflows.md`            | Step-by-step procedures for skill creation, role creation, orchestration skill creation, capability addition, migration, deployment, and auditing |

### Assets

Asset files are templates that get copied and filled in when creating new components. They contain placeholder values and inline comments explaining what to replace.

| File                      | Creates                                   |
|---------------------------|-------------------------------------------|
| `skill-standalone.md`     | A standalone skill with YAML frontmatter  |
| `skill-router.md`         | A router skill with dispatch table         |
| `capability.md`           | A capability under an existing router      |
| `role.md`                 | A role with responsibility/authority/constraints contract and workflow definition |
| `manifest.yaml`           | A manifest with schema and examples         |

### Scripts

Scripts handle deterministic, repeatable tasks that should not be left to the model's judgment. They enforce consistency where text instructions would introduce variance.

| Script                    | Purpose                                                          |
|---------------------------|------------------------------------------------------------------|
| `validate_skill.py`       | Validates a single skill directory against the Agent Skills specification: checks frontmatter, naming, line counts, and resource directories |
| `audit_skill_system.py`   | Audits the full skill system: dependency direction, nesting depth, shared resource usage, and manifest presence |
| `scaffold.py`             | Creates new components from templates with proper directory structure and placeholder content |
| `bundle.py`               | Bundles a skill into a self-contained zip bundle: validates, resolves external references, rewrites paths, creates bundle |
| `lib/yaml_parser.py`      | Lightweight YAML-subset parser (no external dependencies) |
| `lib/frontmatter.py`      | Frontmatter extraction and body line counting |
| `lib/reporting.py`        | Shared error categorization and formatted output |
| `lib/discovery.py`        | Component discovery: finds skills and roles in a skill system |
| `lib/validation.py`       | Shared name validation logic (format, length, reserved words) |
| `lib/references.py`       | Reference scanning, resolution, and graph traversal for bundling |
| `lib/constants.py`        | Centralized constants loaded from `configuration.yaml` |
| `lib/configuration.yaml`  | Validation rules, constraints, domain policy, and bundle configuration |

**Dependencies:** None — all scripts use the Python standard library only.

## Usage

Quick start — scaffold a skill and validate it:

```bash
python scripts/scaffold.py skill my-skill
python scripts/validate_skill.py skills/my-skill
```

For project deployments, use `--root` to target the system directory:

```bash
python scripts/scaffold.py skill my-skill --root /path/to/project/.agents
```

To bundle a skill as a self-contained zip for distribution:

```bash
python scripts/bundle.py .agents/skills/my-skill --system-root .agents --output my-skill.zip
```

For complete procedures (creation, migration, auditing, bundling) and all command options, see [`references/workflows.md`](references/workflows.md).

### Typical Workflow

1. **Scaffold** a new component from a template
2. **Edit** the generated files with domain-specific content
3. **Validate** the skill against the spec
4. **Deploy to tools** that don't natively scan the canonical location (optional)
5. **Bundle for distribution** as a self-contained zip bundle (optional)
6. **Update the manifest** to reflect the new wiring
7. **Audit** the full skill system for consistency

## How This Skill Practices What It Preaches

> This section is for readers already familiar with the skill system's architecture and design principles. For background, see the [Architecture](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Architecture) and [Design Principles](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Design-Principles) wiki pages.

This skill is itself organized as a **logical router** within the skill system it describes. It routes to nine conceptual capabilities through reference files rather than literal `capabilities/` subdirectories. This is a valid pattern when capabilities are documentation-driven (reference files and templates) rather than independent execution units requiring their own `capability.md` and resources:

- **SKILL.md** is a lean router (~140 lines total, ~115 body lines) with YAML frontmatter, an architecture overview, resource pointers, core principles summary, and a quick reference table. It does not contain detailed instructions — those live in references.
- **Progressive disclosure** is respected: the discovery layer sees only the name and description (~100 tokens). The full SKILL.md loads when triggered. References, assets, and scripts load only when the specific task requires them.
- **Token economy** is optimized: one skill registration covers nine optional capabilities (loaded on demand), avoiding 9x discovery overhead.
- **Bundled resources** follow the standard layout: references for guidance, assets for templates, scripts for automation.
- **The spec is followed**: valid frontmatter, name matches directory, description is third-person with trigger words, body is recommended max 500 lines.
- **Nested references are a documented exception.** Reference files cross-reference each other for navigability (e.g., `workflows.md` links to templates, `anti-patterns.md` links to `workflows.md`). This is an accepted exception to the one-level-deep rule because the meta-skill's reference files describe the skill system's own components. Running `validate_skill.py` on this skill produces nested-reference warnings; all are expected. Use `--allow-nested-references` to suppress them.

## Learn More

For supplementary context beyond this skill documentation:

| Topic | Link |
|-------|------|
| Architecture and orchestration paths | [Architecture](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Architecture) |
| Token economy and design principles | [Design Principles](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Design-Principles) |
| Tool landscape and discovery paths | [Supported Tools](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Supported-Tools) |
| Project layout and deployment strategy | [Project Integration](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Project-Integration) |
| Key terms defined | [Glossary](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Glossary) |
| Guided examples | [Walkthroughs](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Walkthroughs) |
