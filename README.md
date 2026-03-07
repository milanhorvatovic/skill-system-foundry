# Skill System Foundry

Meta-skill for building AI-agnostic skill systems with a two-layer architecture of skills and roles, templates, validation tools, and cross-platform authoring guidance based on the Agent Skills specification.

## Motivation

Modern AI-assisted development spans multiple tools — Claude Code for terminal work, Cursor for IDE tasks, Codex for sandboxed execution. Each tool has its own conventions for discovering and running skills. Without a governing architecture, three problems compound as adoption grows:

**Duplication.** The same domain knowledge (how to triage defects, how to generate reports, how to run database migrations) gets written separately for each tool. When the process changes, N files need updating instead of one. The drift between copies creates subtle behavioral inconsistencies that are hard to detect and harder to debug.

**Discovery bloat.** Every skill's name and description is injected into the system prompt for selection. Ten granular project management skills mean ten descriptions competing for attention on every request — even ones unrelated to project management. The context window is a shared, finite resource. Discovery tokens are always present, always expensive, and scale linearly with the number of registered skills.

**Structural drift.** Without clear rules about what goes where, domain logic leaks into tool-specific files, roles collapse into thin passthroughs, and the boundary between "what I can do" and "how I do it on this tool" erodes. Changes become unpredictable and testing becomes tool-specific instead of universal. Refactoring one skill can cascade into changes across every tool integration.

This repository provides the architecture, tooling, and meta-skill to solve all three problems systematically.

## Relationship to Skill Creators

Anthropic, OpenAI, and Google each publish official skill creator tools that teach how to write effective individual skills. Skill System Foundry is not a replacement for those tools — it builds on top of them.

The skill creators focus on single-skill authoring: frontmatter, descriptions, progressive disclosure, script design, and evaluation. Skill System Foundry focuses on what happens after you know how to write one good skill: organizing multiple skills into a layered architecture, managing cross-tool distribution, and maintaining consistency at scale.

The authoring principles ([`authoring-principles.md`](skill-system-foundry/references/authoring-principles.md)) consolidate shared best practices from all three platforms into a single cross-platform reference with a provenance table showing which vendor contributed each principle. Platform-specific extensions are documented separately in [`claude-code-extensions.md`](skill-system-foundry/references/claude-code-extensions.md), [`codex-extensions.md`](skill-system-foundry/references/codex-extensions.md), and [`cursor-extensions.md`](skill-system-foundry/references/cursor-extensions.md).

If you are writing a single skill for a single tool, the vendor's skill creator is sufficient. If you are building a multi-skill, multi-tool architecture, this project provides the structure the skill creators do not address.

**Further reading — official tool documentation:**

- [Claude Code](https://code.claude.com/docs/en/skills) — skills in Claude Code
- [OpenAI Codex](https://developers.openai.com/codex/skills/) — skills in Codex
- [Gemini CLI](https://geminicli.com/docs/cli/skills/) — skills in Gemini CLI
- [Cursor](https://cursor.com/docs/context/skills) — skills in Cursor
- [Windsurf](https://docs.windsurf.com/windsurf/cascade/skills) — skills in Windsurf
- [Kiro](https://kiro.dev/docs/cli/skills/) — skills in Kiro

**Further reading — authoring guides (official skill creators):**

- [Anthropic (Claude Code)](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md)
- [OpenAI (Codex)](https://github.com/openai/skills/blob/main/skills/.system/skill-creator/SKILL.md)
- [Google (Gemini CLI)](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/skills/builtin/skill-creator/SKILL.md)

**Further reading — open standards and conventions:**

- [Agent Skills specification](https://agentskills.io) — open standard governing skill structure (frontmatter, naming, layout)
- [AGENTS.md convention](https://agents.md/) — project-level context convention, governed by the Agentic AI Foundation under the Linux Foundation
- [ROLES.md convention](https://www.roles.md) — AI agent behavioral contracts (responsibilities, allowed/forbidden actions, handoff rules)

## Installation

### npx skills

```bash
npx skills add milanhorvatovic/skill-system-foundry
```

Installs the skill to Claude Code, Codex, Cursor, Gemini CLI, Windsurf, Kiro, GitHub Copilot, Cline, OpenCode, and many more agents. See [skills.sh](https://skills.sh) for the full list of supported agents.

### Claude Code Plugin

```
/plugin marketplace add milanhorvatovic/skill-system-foundry
/plugin install skill-system-foundry@skill-system-foundry
```

### Gemini CLI

```bash
gemini skills link milanhorvatovic/skill-system-foundry
```

### Manual

Copy the `skill-system-foundry/` directory into your project's `.agents/skills/` path:

```bash
cp -r skill-system-foundry /path/to/project/.agents/skills/
```

### GitHub Releases

Download the latest versioned zip from [Releases](https://github.com/milanhorvatovic/skill-system-foundry/releases) and extract into your skills directory.

## Architecture

The skill system follows a two-layer architecture — **skills** and **roles** — that separates **what** from **who**. Each layer has one job. Dependencies flow strictly downward — never the reverse. A capability must never know it's being orchestrated. A role references skills but never other roles. Capabilities are optional sub-units within a skill, not a separate layer. Canonical knowledge lives in one place and is adapted, never duplicated, for each tool.

This strict directionality means changes propagate predictably: modifying a capability never breaks a role, adding a tool never touches a skill. The dependency direction governs **references between layers**, not where orchestration begins. Two valid orchestration paths exist:

```
Path 1:  orchestration skill → roles → skills (with optional capabilities)
Path 2:  skill (standalone or router) → role(s) → skill's capabilities
```

**Path 1 — Coordination-only skill.** A lean standalone skill sequences roles across domains. It contains no domain logic — purely coordinates. Use when the workflow spans multiple unrelated domains.

**Path 2 — Self-contained skill.** A domain skill (standalone or router with capabilities) loads one or more roles for interactive workflow logic. The skill owns capabilities; roles provide responsibility, authority, and constraints, plus handoff rules, sequencing, and interaction patterns. Use when the domain, capabilities, and orchestration belong together as one discoverable unit (e.g., a project management router skill with roles that know how to use its capabilities).

A skill can load **one or more roles** based on the requirements of the flow. A coordination-only skill may sequence multiple roles across domains. A self-contained skill may load different roles for different workflow phases, though adding multiple roles increases complexity — weigh the coordination overhead against the benefit before introducing additional roles.

Regardless of path, one shared principle applies: **the skill owns domain execution, the role owns workflow logic** — keep these concerns separated.

See [`architecture-patterns.md`](skill-system-foundry/references/architecture-patterns.md) for detailed guidance, decision checklists, and constraints per path.

> **Note:** By default, `audit_skill_system.py` flags any skill referencing `roles/` as a failure. For orchestration skills (both paths), use the `--allow-orchestration` flag to downgrade these to warnings:
> ```bash
> python scripts/audit_skill_system.py /path/to/system --allow-orchestration
> ```

### Skills

A skill is a unit of canonical, AI-agnostic knowledge. It describes what to do and how to do it, without reference to any specific AI tool. Every skill conforms to the [Agent Skills](https://agentskills.io) open specification.

Skills come in two forms:

- **Standalone skills** handle a focused task directly. A single `SKILL.md` contains everything needed. Use when the domain is narrow and instructions fit in under ~300 lines with references handling depth.

- **Router skills** manage complex domains with multiple distinct operations. The `SKILL.md` acts as a dispatch table that routes to **capabilities** — self-contained sub-skills loaded on demand. Only the router is registered in the discovery layer; capabilities are invisible until needed.

A skill directory may contain three types of bundled resources:

| Directory      | Purpose                                                    | Example                      |
|----------------|------------------------------------------------------------|------------------------------|
| `references/`  | Documentation loaded into context to inform decisions      | API guides, domain rules     |
| `scripts/`     | Executable code for deterministic, repeatable tasks        | Validators, generators       |
| `assets/`      | Static resources copied or referenced in output            | Templates, schemas           |

For registered skills (discovery-visible skills), the specification requires:
- YAML frontmatter with `name` (lowercase + hyphens, max 64 chars) and `description` (max 1024 chars, third-person, describes what and when)
- A markdown body (recommended max 500 lines)
- The `name` field must match the parent directory name

Note: capability entry points use `capability.md` (not `SKILL.md`). Frontmatter in `capability.md` is optional; include it when promotion to a standalone skill is likely.

### Capabilities

A capability is a skill that lives under a router and is not registered in the discovery layer. It exists purely to be loaded on demand when the router dispatches to it.

Key constraints:
- Capabilities must not reference sibling capabilities — if a task spans multiple capabilities, that's a role's job
- Capabilities are invisible to the discovery layer; only the parent router appears in discovery
- Each capability is self-contained with its own `capability.md` and optional resources

#### Why `capability.md`

This convention is a preventive naming guardrail, not a tool-level fix.

- **What it prevents:**
  - Codex CLI startup warnings caused by recursively scanning capability `SKILL.md` files that intentionally omit discovery frontmatter
  - The opposite failure mode where adding frontmatter to silence warnings accidentally makes capabilities look like standalone registered skills
  - Claude zip packaging collisions from case-insensitive `SKILL.md` handling (`skill.md` vs `SKILL.md`)

- **What it does not solve:**
  - It does not change Codex or Claude behavior; it avoids known conflict paths
  - It does not auto-migrate existing capability files; repositories still need a one-time rename/update
  - It does not replace architecture rules (router dispatch, no sibling-capability references, role boundaries)

Tool-specific details:
- [`codex-extensions.md`](skill-system-foundry/references/codex-extensions.md) — Codex discovery, scanning, and `agents/openai.yaml`
- [`claude-code-extensions.md`](skill-system-foundry/references/claude-code-extensions.md) — Claude Code surfaces, zip packaging, and extended frontmatter
- [`cursor-extensions.md`](skill-system-foundry/references/cursor-extensions.md) — Cursor cross-vendor discovery and rules migration

### Roles

A role is a canonical, AI-agnostic orchestration contract. It defines responsibility, authority, and constraints, plus handoff rules and workflow sequencing across skills/capabilities.

Key constraints:
- A role should explicitly define: responsibility, authority, constraints, and handoff rules
- A role must compose two or more skills or capabilities, or add meaningful interaction logic beyond what any single skill provides
- If a role is just a thin passthrough to one capability, it should not exist
- Roles are plain markdown files (not Agent Skills specification files)
- Roles reference skills by system-root-relative path (for example, `skills/<domain>/SKILL.md`)
- A role is a behavioral contract, not a subagent; the same agent can switch roles without spawning a new entity

### Manifest

A YAML file at the system root that serves as the single source of truth for what exists and how it's wired. It maps every skill to its capabilities and every role to its skill dependencies. In both orchestration paths (see [Architecture](#architecture) above), a skill may also declare role dependencies — the manifest supports this relationship.

The manifest enables automated validation: scripts can verify manifest presence, spec compliance, dependency direction, nesting depth, and shared resource usage. Path validity and orphan detection require manual review (see the audit checklist in [`workflows.md`](skill-system-foundry/references/workflows.md)).

## Design Principles

### Token Economy

Discovery tokens are the most expensive tokens in the system because they're always present — injected into the system prompt before every request, for every conversation, regardless of whether the skill is needed.

The architecture minimizes discovery cost through progressive disclosure:

| Level    | When Loaded          | Token Cost           | Content                          |
|----------|----------------------|----------------------|----------------------------------|
| Metadata | Always (startup)     | ~100 tokens/skill    | name + description               |
| Instructions | When triggered   | <5000 tokens         | SKILL.md body (recommended max 500 lines) |
| Resources | As needed           | Unlimited            | references, scripts, assets      |

Register one skill per domain, not one per capability. A project management domain with 10 capabilities registers as one skill in discovery (~100 tokens) rather than 10 skills (~1000 tokens). The detailed instructions only load when the skill triggers.

### Conciseness

The model is already smart. Only add context it doesn't already have. Challenge every paragraph: "Does the model really need this explanation?" A skill that wastes 100 tokens explaining what a PDF is, is a skill that's 100 tokens less effective at its actual job.

Conciseness applies at every level:
- **Descriptions** should be dense with trigger words, not padded with filler
- **Instructions** should omit what the model already knows
- **References** should contain domain-specific knowledge, not general programming advice

### Degrees of Freedom

Match specificity to task fragility:

- **High freedom** (text instructions) — Flexible tasks where multiple approaches are valid. Let the model choose the best path.
- **Medium freedom** (pseudocode, parameterized scripts) — Tasks where the general approach matters but details can vary.
- **Low freedom** (exact scripts) — Fragile operations where consistency is critical. Lock down every step.

Over-constraining flexible tasks wastes tokens and limits the model's ability to adapt. Under-constraining fragile tasks creates unpredictable results.

### Write Once, Adapt Everywhere

Domain knowledge is authored exactly once in the canonical layer (skills and roles). When domain knowledge changes, one file changes. Tool-specific deployment pointers, if needed, are optional user-managed customizations documented in [`tool-integration.md`](skill-system-foundry/references/tool-integration.md).

For common pitfalls — premature capability creation, discovery bloat, and more — see [`anti-patterns.md`](skill-system-foundry/references/anti-patterns.md).

## Supported Tools

The skill system targets AI coding tools that support skill discovery — scanning known filesystem paths for `SKILL.md` files and injecting their metadata into the system prompt. Discovery paths shown are project-level; see [Personal vs Project Skills](#personal-vs-project-skills) for user-scoped paths.

### Tool Landscape

| Tool             | Discovery Path                              | Wrapper Format                         | Agent Skills Spec | `.agents/skills/` (project) |
|------------------|---------------------------------------------|----------------------------------------|-------------------|-----------------------------|
| Claude Code      | `.claude/skills/`                           | `SKILL.md`                             | Yes               | No                          |
| Codex (OpenAI)   | `.agents/skills/`                           | `SKILL.md` + optional `agents/openai.yaml` | Yes          | Yes (primary)               |
| Gemini CLI       | `.agents/skills/`, `.gemini/skills/`        | `SKILL.md`                             | Yes               | Yes (alias)                 |
| Warp             | `.agents/skills/` (recommended), plus vendor-specific paths | `SKILL.md`                 | Yes               | Yes (recommended)           |
| OpenCode         | `.agents/skills/`, `.opencode/skills/`      | `SKILL.md`                             | Yes               | Yes                         |
| VS Code / Copilot| `.github/`                                  | `.md`                                  | Planned           | Planned                     |
| Cursor           | `.cursor/skills/`, `.claude/skills/`, `.codex/skills/` (cross-vendor) | `SKILL.md`                 | Yes               | No                          |
| Windsurf         | `.windsurf/skills/`, `.agents/skills/`      | `SKILL.md`                             | Yes               | Yes                         |
| Kiro             | `.kiro/skills/`                             | `SKILL.md`                             | Yes               | No                          |
| Cline            | `.clinerules/`                              | `.md`                                  | No                | No                          |
| Aider            | Convention files, `AGENTS.md`               | `.md`                                  | No                | No                          |
| Continue.dev     | `.continue/agents/`                         | `.md`                                  | No                | No                          |

Cursor note: project-level `.agents/skills/` is not scanned. Personal `~/.agents/skills/` is available as an alias but may vary by Cursor release.

### Key Observations

**The Agent Skills specification** ([agentskills.io](https://agentskills.io)) is the open standard for skill structure — YAML frontmatter with `name` and `description`, a markdown body (recommended max 500 lines), and optional bundled resources. Codex, Gemini CLI, Warp, OpenCode, Claude Code, Cursor, Windsurf, and Kiro all follow it. VS Code has it planned. This is the structural standard Skill System Foundry builds on.

**The `.agents/skills/` path** is emerging as the vendor-neutral discovery location. It is already the primary or recommended path for Codex, Gemini CLI, Warp, OpenCode, and Windsurf. Unlike `.claude/skills/` or `.cursor/skills/`, it carries no vendor prefix, making it the natural candidate for canonical content that should not be owned by any single tool.

**AGENTS.md** is a separate but complementary convention — a single file (not a directory) that provides project-level instructions to AI tools. It is widely adopted and is governed by the Agentic AI Foundation under the Linux Foundation. AGENTS.md and the Agent Skills specification serve different purposes: AGENTS.md provides global project context, while skills provide domain-specific capabilities with progressive disclosure.

**ROLES.md** is another complementary convention — a file placed at the project root that defines behavioral contracts for AI agents: what a role is responsible for, what it is permitted to do, what is forbidden, and when to hand off work. Where AGENTS.md provides broad project context and skills provide domain capabilities, ROLES.md constrains how an agent behaves while operating under a given role. The convention is lightweight (no required fields or schema) and tool-agnostic. See the [ROLES.md convention](https://www.roles.md) and [its docs](https://www.roles.md/docs).

**No universal path exists yet.** Each tool still maintains its own vendor-specific directory. The `.agents/` convention is the closest to a cross-tool standard but is not yet ratified formally. This is precisely why Skill System Foundry separates canonical content from tool-specific deployment — the canonical layer is stable regardless of which tools adopt which paths.

## Project Integration

This section describes how to deploy this skill system's two-layer architecture into an actual project. The core decision is where the canonical (AI-agnostic) content lives.

### Recommended Layout

Place canonical content under `.agents/`, with skills in `.agents/skills/`, roles in `.agents/roles/`, and `manifest.yaml` at `.agents/manifest.yaml`. Tools that do not scan `.agents/skills/` natively may need thin deployment pointers.

See [directory-structure.md](skill-system-foundry/references/directory-structure.md) § Recommended Project Layout for the full directory tree and examples.

### Why `.agents/skills/`

Maximum native reach (most tools scan it), vendor neutrality (not tied to a single tool), and forward compatibility (gaining adoption under the Agentic AI Foundation).

See [directory-structure.md](skill-system-foundry/references/directory-structure.md) § Why `.agents/skills/` for details.

### Deployment Strategy

Tools fall into three categories: **native** (scan `.agents/skills/` directly — Codex, Gemini CLI, Warp, OpenCode, Windsurf), **cross-compatible** (Cursor scans multiple vendor paths), and **pointer-required** under the recommended layout (Claude Code, Cursor, Kiro). Some tools (Cline, Aider, Continue.dev) do not follow the Agent Skills specification and require different approaches.

See [tool-integration.md](skill-system-foundry/references/tool-integration.md) § Deployment Strategy for the full per-tool breakdown and tables.

### Deployment Pointer Examples

A Claude Code deployment pointer for a project management router skill:

```markdown
---
name: project-mgmt
description: >
  Project management operations — triage defects, refine stories, run gate checks.
---

Read and follow the canonical skill at `.agents/skills/project-mgmt/SKILL.md`.

Use bash to read files. Execute scripts directly via bash.
```

A Cursor deployment pointer placed in `.cursor/skills/project-mgmt/SKILL.md`:

```markdown
---
name: project-mgmt
description: >
  Project management operations — triage defects, refine stories, run gate checks.
---

Read and follow the canonical skill at `.agents/skills/project-mgmt/SKILL.md`.
```

Since Cursor now follows the Agent Skills specification, its deployment pointers use the same `SKILL.md` format as Claude Code — not the `.mdc` rule format. Both pointers are under 10 lines. All domain knowledge — what triage means, how gate checks work, which fields to set — lives in the canonical `.agents/skills/project-mgmt/` directory and is authored exactly once.

Note: if canonical content is placed in `.claude/skills/` instead of `.agents/skills/`, Cursor discovers it natively (it scans `.claude/skills/`) and no Cursor pointer is needed at all.

Note: Windsurf and Codex scan `.agents/skills/` natively — no deployment pointer needed for these tools under the recommended layout.

### Personal vs Project Skills

The `.agents/skills/` path is **project-level** (shared via repository). Skills can also be installed at the **personal level** (`~/` paths) for individual productivity tools that don't belong in a shared repository.

See [tool-integration.md](skill-system-foundry/references/tool-integration.md) § Personal vs Project Skills for per-tool personal paths.

### Convention Coexistence

Three complementary conventions can be used together without conflict:

- **`AGENTS.md`** — broad project context (coding standards, repo conventions); always loaded
- **`ROLES.md`** — behavioral contracts for AI agents (responsibilities, allowed/forbidden actions, handoff rules); loaded per role
- **Agent Skills** — domain-specific capabilities (workflows, procedures); progressively disclosed on demand

None of these should duplicate content. If coding standards are in `AGENTS.md`, skills should not repeat them. If a role's allowed actions are in `ROLES.md`, the role file in `roles/` should not restate them.

See [tool-integration.md](skill-system-foundry/references/tool-integration.md) § Convention Coexistence for the full comparison table.

### Alternative Layouts

The `.agents/skills/` recommendation is not rigid. Alternative layouts (dedicated top-level directory, single-tool canonical location) are viable depending on team preferences. The key invariant: **domain knowledge is authored once, in one location, and deployment pointers only contain tool-specific adaptation.**

See [directory-structure.md](skill-system-foundry/references/directory-structure.md) § Alternative Layouts for examples and trade-offs.

## Repository Structure

```
.
├── LICENSE                      ← MIT license
├── README.md                    ← this file (repository overview)
└── skill-system-foundry/         ← the meta-skill itself
    ├── README.md                ← skill-level documentation
    ├── SKILL.md                 ← router entry point (Agent Skills specification)
    ├── references/              ← guidance loaded into context
    ├── assets/                  ← templates for scaffolding components
    └── scripts/                 ← validation, scaffolding, and bundling tools
```

Note: The scaffold tool ([`scaffold.py`](skill-system-foundry/scripts/scaffold.py)) creates components under `skills/` and `roles/` relative to CWD. This matches the skill system's logical structure (see [`directory-structure.md`](skill-system-foundry/references/directory-structure.md)), not the distribution repository layout shown above. For project deployments, use `--root` to target the desired base directory (e.g., `--root .agents`). The bundle tool ([`bundle.py`](skill-system-foundry/scripts/bundle.py)) packages a skill into a self-contained zip bundle for distribution to surfaces like Claude.ai or Gemini CLI.

The `skill-system-foundry/` directory contains the meta-skill that implements this architecture. It follows a router-style pattern with conceptual capabilities documented in references (rather than a literal `capabilities/` tree), so it still demonstrates the skill system's conventions. See [skill-system-foundry/README.md](skill-system-foundry/README.md) for details on the skill's structure, requirements, and usage.

## Getting Started

1. **Understand the architecture** — Read this file to grasp the two-layer model and design principles.

2. **Explore the meta-skill** — See [skill-system-foundry/README.md](skill-system-foundry/README.md) for the skill's capabilities, file layout, and usage instructions.

3. **Create your first skill** — Use the scaffolding tool to generate a new skill from a template. Run from within `skill-system-foundry/`:
   ```bash
   cd skill-system-foundry
   python scripts/scaffold.py skill my-skill
   ```
   This creates a local example at `skill-system-foundry/skills/my-skill/`. For actual project deployment, use `--root` to target your project's system directory:
   ```bash
   python scripts/scaffold.py skill my-skill --root /path/to/project/.agents
   ```

4. **Validate your work** — Run validation to ensure spec compliance (still from within `skill-system-foundry/`):
   ```bash
   python scripts/validate_skill.py skills/my-skill
   ```
   For full skill system validation, point to the deployed system root (the directory containing a `skills/` subdirectory):
   ```bash
   python scripts/audit_skill_system.py /path/to/project/.agents
   ```
   > **Note:** Running `validate_skill.py` on the `skill-system-foundry` meta-skill produces nested-reference warnings. These are expected — use `--allow-nested-references` to suppress them. See [skill-system-foundry/README.md](skill-system-foundry/README.md) for the documented exception.

5. **Deploy to tools** — For tools that do not natively scan your canonical content location, create thin deployment pointers (see [Deployment Strategy](#deployment-strategy) for which tools need pointers). See [`tool-integration.md`](skill-system-foundry/references/tool-integration.md) for tool-specific details.

6. **Bundle for distribution** (optional) — Package a skill as a self-contained zip bundle for Claude.ai upload, Gemini CLI, or offline sharing:
   ```bash
   python scripts/bundle.py .agents/skills/my-skill --system-root .agents --output my-skill.zip
   ```
   The bundler validates, resolves external references (roles, shared docs), rewrites paths, and creates the archive. See [`workflows.md`](skill-system-foundry/references/workflows.md#packaging-a-skill-as-a-zip-bundle) for the full procedure.
