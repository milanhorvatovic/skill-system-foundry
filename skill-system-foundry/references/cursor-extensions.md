# Cursor Extensions

Cursor extends the Agent Skills specification (agentskills.io) with cross-vendor skill discovery, a rules system, and AGENTS.md support. This reference covers what is specific to Cursor; see [agentskills-spec.md](agentskills-spec.md) for the core specification and [tool-integration.md](tool-integration.md) for cross-tool architecture.

## Discovery Paths

Cursor scans primary directories for skills (project + personal):

```
.cursor/skills/             ← project skills (Cursor-native)
.claude/skills/             ← project skills (Claude compatibility)
.codex/skills/              ← project skills (Codex compatibility)

~/.cursor/skills/           ← personal skills (Cursor-native)
~/.claude/skills/           ← personal skills (Claude compatibility)
~/.agents/skills/           ← personal skills (alias, may vary by release)
```

## Cross-Vendor Compatibility

Cursor's scanning of `.claude/skills/` and `.codex/skills/` means canonical content in either path is discovered natively — no Cursor deployment pointer needed. This is significant for this skill system's deployment strategy: placing canonical content in `.claude/skills/` gives native discovery for both Claude Code and Cursor simultaneously.

Cursor does not scan project-level `.agents/skills/`. Support for additional personal alias paths can vary by Cursor release; verify against current Cursor docs/changelog.

## Frontmatter

Cursor supports all core Agent Skills frontmatter fields plus `disable-model-invocation` (a Claude Code extension). When set to `true`, the skill can only be triggered manually via `/skill-name`, not by the model's autonomous selection.

## Rules System

`.cursor/rules/` supports `.md` and `.mdc` files with activation types:

| Type | Behavior |
|---|---|
| Always Apply | Loaded into every context |
| Apply Intelligently | Model decides when relevant |
| Glob-based | Applied to matching file patterns |
| Manual | User-triggered only |

Rules provide declarative context, while skills enable procedural workflows with progressive disclosure. The single-file `.cursorrules` format in the project root is still functional but deprecated — migrate to `.cursor/rules/` or Agent Skills.

## AGENTS.md Support

Cursor supports `AGENTS.md` with nested subdirectory discovery. Instructions from nested `AGENTS.md` files are combined with parent directories, with more specific instructions taking precedence.

## Migration

Cursor includes `/migrate-to-skills` for converting legacy rules to skills:

- **Converts:** Dynamic rules with `alwaysApply: false` or undefined, no glob patterns
- **Skips:** Rules with `alwaysApply: true` or specific glob patterns
- **Excludes:** User-level rules (only project rules migrate)

Remote skills can be imported via Settings > Rules > Add Rule > Remote Rule (GitHub repository URL).

## Loading Mechanism

- Reads SKILL.md frontmatter (name/description) into system prompt
- When triggered, reads full SKILL.md body
- Resources (`scripts/`, `references/`, `assets/`) loaded on demand
- Scripts executed via IDE terminal

## Deployment Pointer

Use `.cursor/skills/<domain>/SKILL.md` for Cursor-native placement. Deployment pointers can be wrapper files or symlinks — Cursor follows symlinked skill directories and files. See [tool-integration.md](tool-integration.md#symlink-based-deployment-pointers) for the decision guide and platform commands.

If canonical content lives in `.claude/skills/` or `.codex/skills/`, no Cursor deployment pointer is needed at all — Cursor discovers it natively.
