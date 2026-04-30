---
allowed-tools: Bash Read Write
---

# Deployment

Deploy skills to AI tools, set up deployment pointers (wrapper files or symlinks), and use tool-specific extensions.

## Deploying Skills to Tools

Skills placed in `.agents/skills/` are natively discovered by most tools (Codex, Gemini CLI, Warp, OpenCode, Windsurf). For tools that do not scan this path, create a deployment pointer in the tool's discovery path. See [tool-integration.md](references/tool-integration.md) for per-tool details.

**First, determine the pointer mechanism.** Ask the user before creating any deployment pointers:

```
How should deployment pointers be created?
> [ ] Wrapper files (portable, works everywhere)
> [ ] Symlinks (zero maintenance, but platform requirements apply)
```

See [tool-integration.md](references/tool-integration.md#symlink-based-deployment-pointers) for the full decision guide. If symlinks are chosen, follow the [Setting Up Symlink-Based Pointers](capabilities/deployment/references/symlink-setup.md) reference.

**Per-tool instructions (wrapper files):**

**Claude Code:** Create a pointer at `.claude/skills/<domain>/SKILL.md` that references the canonical source (registered skills only — not capability files). Or use the plugin marketplace.

**Claude.ai:** Bundle the skill as a zip using [bundle.py](scripts/bundle.py), then upload via Settings > Features. Per-user. Description must be max 200 characters.

**Claude API:** Upload via `/v1/skills` endpoints. Workspace-wide.

**Codex:** `skill-installer install <skill-name>` or place in `~/.agents/skills/`. Natively scans `.agents/skills/`.

**Cursor:** If canonical content is in `.agents/skills/`, create a pointer at `.cursor/skills/<domain>/SKILL.md`. If canonical content is in `.claude/skills/`, Cursor discovers it natively.

**Windsurf:** Usually no deployment pointer needed when canonical skills live in `.agents/skills/`. Optionally add `.windsurf/rules/<domain>.md` for rules-based activation.

**Kiro:** Create a pointer at `.kiro/skills/<domain>/SKILL.md` that references the canonical source.

## Tool-Specific Extensions

Read the relevant extension reference when using tool-specific features:

- [claude-code-extensions.md](references/claude-code-extensions.md) — Claude Code frontmatter, subagent execution, dynamic context, string substitutions
- [codex-extensions.md](references/codex-extensions.md) — Codex agents/openai.yaml, six-level discovery hierarchy, invocation methods
- [cursor-extensions.md](references/cursor-extensions.md) — Cursor cross-vendor discovery paths, rules system, AGENTS.md support

## Key Resources

**References:**
- [symlink-setup.md](capabilities/deployment/references/symlink-setup.md) — Platform-specific symlink commands (Linux/macOS/Windows)
- [tool-integration.md](references/tool-integration.md) — Tool-specific paths, discovery, and deployment
- [claude-code-extensions.md](references/claude-code-extensions.md) — Claude Code extensions
- [codex-extensions.md](references/codex-extensions.md) — Codex extensions
- [cursor-extensions.md](references/cursor-extensions.md) — Cursor extensions

**Scripts:**
- [bundle.py](scripts/bundle.py) — Bundle a skill for distribution (needed for Claude.ai upload)
