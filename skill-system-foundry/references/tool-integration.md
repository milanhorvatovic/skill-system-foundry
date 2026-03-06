# Tool Integration

How skills are discovered, loaded, and executed across different AI tools.

## Table of Contents

- [Cross-Tool Architecture](#cross-tool-architecture)
- [Deployment Strategy](#deployment-strategy)
- [Claude Code](#claude-code)
- [Codex (OpenAI)](#codex-openai)
- [Cursor](#cursor)
- [Other Agent Skills-Compatible Tools](#other-agent-skills-compatible-tools)
- [Non-Agent-Skills Tools](#non-agent-skills-tools)
- [Deployment Pointer Guidelines](#deployment-pointer-guidelines)
- [Symlink-Based Deployment Pointers](#symlink-based-deployment-pointers)
- [Convention Coexistence](#convention-coexistence)
- [Personal vs Project Skills](#personal-vs-project-skills)
- [Zip Bundle Packaging](#zip-bundle-packaging)
- [Cross-Surface Limitations](#cross-surface-limitations)

---

## Cross-Tool Architecture

All tools follow a similar pattern:

1. **Discovery** — Tool scans known locations for SKILL.md files
2. **Metadata extraction** — name + description from frontmatter
3. **System prompt injection** — Metadata added to context at startup
4. **On-demand loading** — Full SKILL.md read when skill triggers
5. **Resource access** — Additional files read as needed

The canonical skill content is identical across tools. Only a thin deployment pointer adapts the delivery mechanism when needed.

---

## Deployment Strategy

Tools fall into three categories based on how they relate to the canonical location (`.agents/skills/`):

**Native tools — scan `.agents/skills/` directly (no pointer needed):**

| Tool | How it discovers `.agents/skills/` |
|---|---|
| Codex | Primary discovery path, scans from CWD to root |
| Gemini CLI | Alias path, `.agents/` takes precedence over `.gemini/` |
| Warp | Recommended path |
| OpenCode | Scans alongside `.opencode/skills/` |
| Windsurf | Scans `.agents/skills/` natively (v1.9552.21+) |

**Cross-compatible tools — scan multiple vendor paths:**

| Tool | Scanned paths |
|---|---|
| Cursor | Project: `.cursor/skills/`, `.claude/skills/`, `.codex/skills/`; Personal: `~/.cursor/skills/`, `~/.claude/skills/` (plus aliases such as `~/.agents/skills/`, depending on release) |

Cursor does not scan **project-level** `.agents/skills/` directly. Placing canonical content in `.claude/skills/` eliminates the need for a Cursor pointer. Personal alias support may vary by Cursor release.

**Pointer-required tools — need thin deployment pointers to canonical content:**

| Tool | Pointer location | Format |
|---|---|---|
| Claude Code | `.claude/skills/` | `SKILL.md` |
| Cursor | `.cursor/skills/` | `SKILL.md` |
| Kiro | `.kiro/skills/` | `SKILL.md` |

> Under the recommended layout (canonical in `.agents/skills/`), Claude Code, Cursor, and Kiro require deployment pointers. If canonical content is in `.claude/skills/` instead, only tools that don't scan that path need pointers. See [directory-structure.md](directory-structure.md#alternative-layouts).

Capability entry naming (cross-tool): use `capability.md` for capability files.

---

## Claude Code

Discovery: `~/.claude/skills/`, `.claude/skills/`, plugins.

Full details: [claude-code-extensions.md](claude-code-extensions.md).

---

## Codex (OpenAI)

Discovery: `.agents/skills/` (hierarchical scan up to repo root), `~/.agents/skills/`.

Supports `agents/openai.yaml` for UI metadata and tool dependencies.

Full details: [codex-extensions.md](codex-extensions.md).

---

## Cursor

Discovery: Project paths `.cursor/skills/`, `.claude/skills/`, `.codex/skills/`; personal paths `~/.cursor/skills/`, `~/.claude/skills/` (plus aliases such as `~/.agents/skills/`, depending on release).

Cross-vendor compatible — no deployment pointer needed when canonical content is in `.claude/skills/`.

Full details: [cursor-extensions.md](cursor-extensions.md).

---

## Other Agent Skills-Compatible Tools

The following tools support the Agent Skills specification. Most scan `.agents/skills/` natively — no deployment pointer needed. Exceptions are noted per tool.

### Gemini CLI

- Discovery: `.agents/skills/`, `.gemini/skills/`, `~/.gemini/skills/`, `~/.agents/skills/`
- `.agents/` takes precedence over `.gemini/`
- User consent required before skill activation
- Supports `gemini skills link` for symlink management
- Installation: Git repos, local directories, `.skill` zipped files
- Standard SKILL.md format

### Warp

- Discovery: `.agents/skills/` (recommended), plus vendor-specific paths (Warp does not publish a stable list of all fallback paths)
- Standard SKILL.md format
- No deployment pointer needed when using `.agents/skills/`

### OpenCode

- Discovery: `.agents/skills/`, `.opencode/skills/`, `~/.agents/skills/`
- Standard SKILL.md format
- No deployment pointer needed when using `.agents/skills/`

### Windsurf

- Discovery: `.windsurf/skills/`, `.agents/skills/`, `~/.codeium/windsurf/skills/`
- `.agents/skills/` support added in v1.9552.21
- Manual invocation via `@skill-name` syntax
- Supports `.windsurf/rules/` for plain markdown rules (no frontmatter)
- Supports AGENTS.md for project-level context
- Standard SKILL.md format
- No deployment pointer needed when using `.agents/skills/`

### Kiro

- Discovery: `.kiro/skills/` (workspace), `~/.kiro/skills/` (global)
- Standard SKILL.md format, follows Agent Skills specification
- Custom agents require explicit resource declarations via `skill://` URI scheme in agent JSON config
- Does not scan `.agents/skills/` natively — deployment pointer required under recommended layout

---

## Non-Agent-Skills Tools

The following tools do not follow the Agent Skills specification. Integration requires tool-specific approaches outside Skill System Foundry's deployment strategy.

| Tool | Convention | Notes |
|---|---|---|
| VS Code / Copilot | `.github/` instructions | Agent Skills support planned |
| Cline | `.clinerules/` | Markdown rules |
| Aider | `AGENTS.md`, convention files | Single-file convention |
| Continue.dev | `.continue/agents/` | Markdown agents |

For these tools, consider using `AGENTS.md` for project-level context or manual context injection.

---

## Deployment Pointer Guidelines

Deployment pointers are optional, user-managed files — not Skill System Foundry artifacts. When you need one, follow these guidelines:

1. **One pointer per registered skill per tool** — not per capability
2. **Keep them minimal** — a pointer should contain only a reference to the canonical source and any genuine tool-specific conventions
3. **No domain logic** — only tool-specific conventions
4. **Point to canonical source** — never duplicate skill content

### Legitimate Content

- Tool cannot read files the same way (e.g., API surface vs CLI)
- Tool has different package availability (API vs CLI)
- Tool requires specific output formatting
- Tool has unique MCP or plugin integration

### Content That Belongs in the Canonical Layer

- Domain-specific workflow steps
- Business logic or decision rules
- Reference material or examples

---

## Symlink-Based Deployment Pointers

Symlinks are an alternative to wrapper files for deployment pointers. Instead of creating a thin `SKILL.md` that references canonical content, a symlink points the tool's discovery path directly to the canonical source — zero maintenance, no content duplication.

### When to Use Symlinks vs Wrapper Files

| Criteria | Symlinks | Wrapper files |
|---|---|---|
| Maintenance | Zero — canonical source always read | Must keep wrapper in sync |
| Content duplication | None | Risk of divergence |
| Platform support | Requires setup on Windows | Works everywhere |
| Tool-specific adaptation | Not possible — content is identical | Can add tool-specific conventions |
| Team OS mix | Requires all contributors to support symlinks | No platform constraints |

**Use symlinks when:** the team is on Linux/macOS (or Windows with Developer Mode), no tool-specific adaptation is needed, and you want zero-maintenance pointers.

**Use wrapper files when:** the team includes Windows users without Developer Mode, the tool requires specific conventions in its pointer, or platform reliability is more important than maintenance savings.

### Symlink Forms

**Directory-level** — symlink the entire skill directory:

```
.claude/skills/my-skill -> ../../.agents/skills/my-skill
```

**File-level** — symlink only SKILL.md:

```
.claude/skills/my-skill/SKILL.md -> ../../../.agents/skills/my-skill/SKILL.md
```

Directory-level symlinks are simpler and preferred. File-level symlinks are useful when the pointer directory needs additional tool-specific files alongside the symlinked SKILL.md.

### Platform Commands

Symlink creation syntax differs across platforms. Note the reversed argument order between Unix and Windows.

**Linux / macOS:**

```bash
# Directory-level
ln -s ../../.agents/skills/my-skill .claude/skills/my-skill

# File-level
mkdir -p .claude/skills/my-skill
ln -s ../../../.agents/skills/my-skill/SKILL.md .claude/skills/my-skill/SKILL.md
```

**Windows (cmd) — requires Developer Mode or admin:**

```cmd
:: Directory-level
mklink /D .claude\skills\my-skill ..\..\.agents\skills\my-skill

:: File-level
mkdir .claude\skills\my-skill
mklink .claude\skills\my-skill\SKILL.md ..\..\..\.agents\skills\my-skill\SKILL.md
```

**Windows (PowerShell) — requires Developer Mode or admin:**

```powershell
# Directory-level
New-Item -ItemType SymbolicLink -Path .claude\skills\my-skill -Target ..\..\.agents\skills\my-skill

# File-level
New-Item -ItemType Directory -Path .claude\skills\my-skill -Force
New-Item -ItemType SymbolicLink -Path .claude\skills\my-skill\SKILL.md -Target ..\..\..\.agents\skills\my-skill\SKILL.md
```

### Tool Compatibility

| Tool | Symlink support | Evidence |
|---|---|---|
| Codex | Confirmed | [`codex-extensions.md`](codex-extensions.md) documents symlinked folder support |
| Gemini CLI | Confirmed | `gemini skills link` command (documented in this file and Gemini docs) |
| Claude Code | Confirmed | Maintainer verification (2026-03) + [`claude-code-extensions.md`](claude-code-extensions.md) |
| Cursor | Confirmed | Maintainer verification (2026-03) + [`cursor-extensions.md`](cursor-extensions.md) |
| Windsurf | Expected | Standard filesystem traversal (not explicitly documented by vendor) |
| Kiro | Expected | Standard filesystem traversal (not explicitly documented by vendor) |

Tools marked "Expected" follow symlinks through standard filesystem behavior. If a tool explicitly breaks symlink resolution in a future release, fall back to wrapper files for that tool.

### Git and Platform Considerations

**Git on Windows** does not preserve symlinks by default. Cloning a repository with symlinks on Windows without configuration replaces symlinks with plain text files containing the target path.

Fix before cloning:

```bash
git clone -c core.symlinks=true <repo-url>
```

Or configure an existing checkout:

```bash
git config core.symlinks true
```

Then re-clone the repository (recommended). In-place retrofitting can rewrite files and should only be attempted after committing or stashing all local changes.

**CI/CD pipelines** on Windows runners need `core.symlinks=true` in their git configuration. Linux/macOS runners handle symlinks natively.

**Cloud editors and remote development environments** (Codespaces, Gitpod, remote SSH) generally support symlinks on their Linux-based backends. Verify if the environment mounts the repository with symlink support.

---

## Convention Coexistence

`AGENTS.md`, `ROLES.md`, and Agent Skills are three complementary conventions:

| Concern | AGENTS.md | ROLES.md | Agent Skills (`.agents/skills/`) |
|---|---|---|---|
| Scope | Project-wide context | Per-role behavioral contract | Domain-specific capabilities |
| Token cost | Always loaded (~full file) | Loaded when role is active | Progressive disclosure (metadata only at startup) |
| Structure | Single markdown file | Single markdown file | Directory per skill with resources |
| Activation | Always present | When a role is assigned | On-demand when triggered |
| Content | Coding standards, repo conventions | Responsibilities, allowed/forbidden actions, handoff rules | Workflows, procedures, domain logic |

A typical project uses `AGENTS.md` for broad project context ("we use TypeScript, our API follows REST conventions, tests go in `__tests__/`"), `ROLES.md` for role-specific behavioral contracts ("an Implementer may not approve PRs; a Reviewer may not write implementation code"), and Agent Skills for domain-specific capabilities ("how to triage a defect", "how to run a database migration").

None of these should duplicate content. If coding standards are in `AGENTS.md`, skills should not repeat them. If a role's allowed actions are defined in `ROLES.md`, the `roles/` file should not restate them.

---

## Personal vs Project Skills

Skills can be installed at the project level (shared via repository) or the personal level (user-scoped, not committed):

| Tool | Personal skill path |
|---|---|
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.agents/skills/` |
| Gemini CLI | `~/.gemini/skills/` (also `~/.agents/skills/` via alias) |
| OpenCode | `~/.agents/skills/` |
| Cursor | `~/.cursor/skills/`, `~/.claude/skills/` (plus aliases such as `~/.agents/skills/`, depending on release) |
| Windsurf | `~/.codeium/windsurf/skills/` |
| Kiro | `~/.kiro/skills/` |
| Warp | Not publicly documented |

Personal skills are useful for individual productivity tools (custom workflows, personal templates) that don't belong in a shared repository. The same Agent Skills specification applies regardless of install location.

---

## Zip Bundle Packaging

Skills can be distributed as self-contained zip bundles for surfaces that support direct upload, offline sharing, or marketplace distribution.

### Target Surfaces

| Surface | Upload mechanism |
|---|---|
| Claude.ai (Consumer) | Upload zip via Settings > Features, per-user |
| Gemini CLI | `.skill` zipped files via `gemini skills link` |
| GitHub Releases | Attach `.zip` as release asset |

### Claude.ai Constraints

Claude.ai enforces constraints stricter than the Agent Skills specification:

| Constraint | Claude.ai | Agent Skills spec |
|---|---|---|
| SKILL.md count | Exactly one (case-insensitive scan) | One per skill directory |
| Description length | Max 200 characters | Max 1024 characters |
| Folder name | Must match skill name | Must match skill name |

The case-insensitive SKILL.md scan is why capability entry points use `capability.md` — a file named `skill.md` (lowercase) would be treated as a second SKILL entry point and fail Claude.ai's validation.

### Required Archive Structure

Per Claude.ai documentation, the zip must contain the skill folder as its root:

```
<skill-name>.zip
└── <skill-name>/
    ├── SKILL.md
    ├── assets/
    ├── capabilities/
    │   └── <capability>/
    │       ├── capability.md
    │       └── references/
    ├── references/
    ├── scripts/
    └── roles/                  ← inlined from system level
```

Files must **not** be placed directly at the archive root. The wrapper directory name must match the skill's `name` field.

Source: [How to create custom Skills (Claude Help Center)](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)

### Key Distinctions from Project Layout

A zip bundle is a self-contained distribution artifact: it inlines any system-level `roles/` directory, omits the `.agents/` wrapper, and excludes deployment pointer files. The project layout can be larger and include additional tooling, manifests, and deployment pointers that never ship inside the bundle.

### Tooling

To package a skill as a zip bundle, run `bundle.py` from the project root. The bundler validates the skill, resolves external references, copies them into the bundle, rewrites markdown paths to bundle-relative form, and creates the archive.

---

## Cross-Surface Limitations

### Skills Don't Sync

- Skills don't sync automatically across surfaces
- Installation is per surface
- Deployment pointers are needed only for tools that do not natively scan `.agents/skills/`

### Network Access

| Surface | Network |
|---|---|
| Claude Code | Full |
| Claude.ai | Varies by settings |
| Claude API | None |
| Codex (CLI) | Configurable |
| Cursor | Full (IDE context) |
| Windsurf | Full (IDE context) |

### Package Installation

| Surface | Packages |
|---|---|
| Claude Code | Yes (prefer local) |
| Claude.ai | Yes (npm, PyPI, GitHub) |
| Claude API | No (pre-installed only) |
| Codex | Configurable |
| Cursor | Via IDE terminal |
| Windsurf | Via IDE terminal |

Design skills to work without network by default. Document requirements in the `compatibility` frontmatter field.
