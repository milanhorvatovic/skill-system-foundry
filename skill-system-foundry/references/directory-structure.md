# Directory Structure

## Table of Contents

- [Top-Level Layout](#top-level-layout)
- [Logical Structure vs Deployment Paths](#logical-structure-vs-deployment-paths)
- [Recommended Project Layout](#recommended-project-layout)
  - [Why `.agents/skills/`](#why-agentsskills)
  - [Alternative Layouts](#alternative-layouts)
- [Packaging for Distribution](#packaging-for-distribution)
- [Conventions](#conventions)
- [Naming](#naming)
- [Path Convention](#path-convention)

## Top-Level Layout

```
system/
├── skills/
│   ├── <domain>/                     ← router skill (multi-capability)
│   │   ├── SKILL.md                  ← registered, routes to capabilities
│   │   ├── shared/                   ← (optional) only if 2+ capabilities exist
│   │   │   ├── references/
│   │   │   └── assets/
│   │   └── capabilities/             ← (optional) add only when justified
│   │       ├── <capability-a>/
│   │       │   ├── capability.md     ← NOT registered, loaded on demand
│   │       │   └── references/
│   │       └── <capability-b>/
│   │           ├── capability.md
│   │           └── references/
│   └── <simple-skill>/               ← standalone skill
│       ├── SKILL.md                  ← registered
│       ├── scripts/
│       ├── references/
│       └── assets/
│
├── roles/
│   ├── <role-group>/
│   │   ├── <role-name>.md
│   │   └── README.md
│   └── README.md
│
└── manifest.yaml
```

## Logical Structure vs Deployment Paths

The tree above shows the skill system's **logical structure** — how skills and roles relate conceptually. When deploying to a project, canonical content is placed in a location AI tools discover (e.g., `.agents/skills/`, or a top-level `skills/` directory).

Tools that do not scan **project-level** `.agents/skills/` natively may need thin deployment pointers in their own discovery paths (e.g., `.claude/skills/`, `.cursor/skills/`, `.kiro/skills/`). These are optional, user-managed customizations — not Skill System Foundry artifacts. See [tool-integration.md](tool-integration.md) for details.

Roles are placed in `.agents/roles/` and referenced by skills directly. Roles have no tool-specific deployment path.

## Recommended Project Layout

The recommended approach places canonical content in `.agents/skills/`:

```
project/
├── .agents/                           ← canonical, AI-agnostic layer
│   ├── skills/
│   │   ├── project-mgmt/             ← router skill
│   │   │   ├── SKILL.md              ← registered in discovery
│   │   │   ├── capabilities/
│   │   │   │   ├── triage/capability.md      ← loaded on demand
│   │   │   │   ├── refine/capability.md
│   │   │   │   └── gate-check/capability.md
│   │   │   ├── references/
│   │   │   ├── scripts/
│   │   │   └── assets/
│   │   ├── code-review/              ← standalone skill
│   │   │   └── SKILL.md
│   │   └── db-migrations/            ← standalone skill
│   │       ├── SKILL.md
│   │       └── scripts/
│   ├── roles/
│   │   └── engineering/
│   │       ├── release-manager.md
│   │       └── incident-responder.md
│   └── manifest.yaml
│
├── AGENTS.md                          ← project-level AI context (optional)
└── src/
```

Tools that scan `.agents/skills/` natively (Codex, Gemini CLI, Warp, OpenCode, Windsurf) need no additional configuration. Tools that do not (Claude Code, Cursor, Kiro) may need thin deployment pointers — see [tool-integration.md](tool-integration.md) for details.

### Why `.agents/skills/`

1. **Maximum native reach.** Codex, Gemini CLI, Warp, OpenCode, and Windsurf scan `.agents/skills/` as a primary or recommended discovery path. Placing canonical content here means these tools discover skills with zero overhead.

2. **Vendor neutrality.** Unlike `.claude/skills/` or `.cursor/skills/`, the `.agents/` prefix is not associated with any single vendor. Canonical knowledge should not live under a vendor-specific namespace.

3. **Forward compatibility.** The `.agents/` convention is actively discussed under the Agentic AI Foundation (Linux Foundation) and gaining adoption. As more tools adopt this path, the number of deployment pointers needed shrinks.

### Alternative Layouts

The `.agents/skills/` recommendation is not a rigid rule. Two alternatives:

**Dedicated top-level directory:**

```
project/
├── skills/                    ← canonical content at repo root
│   └── project-mgmt/SKILL.md
├── roles/
├── .claude/skills/            ← deployment pointers
├── .cursor/skills/            ← deployment pointers
└── .agents/skills/            ← deployment pointers
```

Use when: the team wants canonical content highly visible in the repository root. Trade-off: adds a non-standard top-level directory and requires deployment pointers for all tools.

#### Deployment Pointer Mechanism: Wrapper Files vs Symlinks

Deployment pointers can be implemented as **wrapper files** or **symlinks**:

- **Wrapper files** — thin `SKILL.md` that references the canonical source. Portable, works everywhere.
- **Symlinks** — filesystem link to the canonical directory or file. Zero maintenance, no content duplication.

Choose based on team composition:
- **All Linux/macOS** — symlinks preferred (zero maintenance)
- **Mixed OS** — wrapper files safer unless all Windows contributors have Developer Mode enabled
- **Need tool-specific adaptation** — wrapper files required (symlinks cannot carry tool-specific content)

See [tool-integration.md](tool-integration.md#symlink-based-deployment-pointers) for the full decision guide, platform-specific commands, and tool compatibility details.

**Single-tool canonical location:**

```
project/
├── .claude/skills/            ← canonical content lives here
│   └── project-mgmt/SKILL.md
└── .agents/skills/            ← deployment pointers to .claude/
```

Use when: one tool dominates and others are secondary. Cursor discovers `.claude/skills/` natively, so no Cursor pointer is needed. Trade-off: couples canonical content to a vendor namespace.

The key invariant across all layouts: **domain knowledge is authored once, in one location, and deployment pointers only contain tool-specific adaptation.**

## Packaging for Distribution

When a skill is packaged as a zip bundle for distribution (Claude.ai upload, Gemini CLI `.skill`, offline sharing), it uses a self-contained structure that differs from the project layout.

### Bundle Structure

The archive contains a `<skill-name>/` wrapper directory as its root with `SKILL.md` and any standard subdirectories (`references/`, `assets/`, `scripts/`, `roles/`) mirrored exactly as they appear on disk. Files must not be placed directly at the archive root.

### Distinctions from Project Layout

| Aspect | Project layout | Zip bundle |
|---|---|---|
| Wrapper | `.agents/` or vendor path | Skill directory is the root |
| Roles | System-level `roles/` directory | Inlined under the skill |
| Deployment pointers | May exist per tool | Not applicable — the zip IS the skill |
| External references | Can reference roles, shared docs | All references resolved internally |
| Path style | System-root-relative for roles | Relative within the bundle |

The `roles/` directory in a bundle is a **distribution-only exception**. In the project layout, roles live at the system level and are shared across skills. In a bundle, roles referenced by the skill are copied in to make the archive self-contained. This is not a new architectural pattern — it is a packaging transformation.

### When to Use

- **Zip bundle**: End-user installation, Claude.ai upload, offline sharing, marketplace distribution
- **Repository**: Team collaboration, version control, CI/CD integration, multi-tool deployment

### Tooling

To package a skill as a zip bundle, run `bundle.py` from the project root. The bundler validates the skill, resolves external references, copies them into the bundle, rewrites markdown paths to bundle-relative form, and creates the archive.

---

## Conventions

**Registered skills** have full frontmatter (name + description) for discovery.

**Capabilities** under `capabilities/` are optional granular sub-skills. NOT registered in discovery. Loaded on demand. Only add when the integrator requests them or the domain warrants decomposition. Entry point is named `capability.md`.

**Shared resources** in `shared/` must be used by 2+ capabilities.

**Roles** are plain markdown, grouped by functional domain with README.md.

**Manifest** is the single source of truth. See [assets/manifest.yaml](../assets/manifest.yaml).

## Naming

Following the Agent Skills specification:
- Lowercase alphanumeric + hyphens: `my-domain`, `code-review`, `data-analysis`
- `name` field must match directory name exactly
- No uppercase, underscores, spaces, leading/trailing/consecutive hyphens
- Max 64 chars. No reserved words on Anthropic platforms ("anthropic", "claude").
- Consider gerund form: `processing-data`, `analyzing-metrics`
- Avoid vague names: `helper`, `utils`, `tools`, `data`

## Path Convention

Paths in SKILL.md bodies and skill-level reference files are relative to the skill root directory (the directory containing SKILL.md). For example, a reference file path resolves as `<skill-root>/references/<file>.md` (see [workflows.md](workflows.md)).

**Exception:** When an orchestration skill's SKILL.md references roles, those paths use system-root-relative form (e.g., `roles/<group>/<name>.md`) for consistency with how roles reference skills. See [architecture-patterns.md](architecture-patterns.md#orchestration-skills).

Paths in role files (e.g., `skills/<domain>/SKILL.md`) are relative to the **system root** — the directory containing `skills/` and `roles/`. This distinction matters because roles live at `roles/<group>/<name>.md`, not inside a skill directory.

Forward slashes are used regardless of operating system.
