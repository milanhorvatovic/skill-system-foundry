---
allowed-tools: Bash Read Write
---

# Deployment

Deploy skills to AI tools, set up deployment pointers (wrapper files or symlinks), and use tool-specific extensions.

## Deploying Skills to Tools

Skills placed in `.agents/skills/` are natively discovered by most tools (Codex, Gemini CLI, Warp, OpenCode, Windsurf). For tools that do not scan this path, create a deployment pointer in the tool's discovery path. See [tool-integration.md](../../references/tool-integration.md) for per-tool details.

**Default to symlinks.** Symlinks provide zero-maintenance pointers that always read the canonical source, matching the foundry's "Write Once, Adapt Everywhere" principle. Follow [Setting Up Symlink-Based Pointers](references/symlink-setup.md). Fall back to wrapper files only when:

- The team includes Windows contributors without Developer Mode (symlinks degrade silently on those checkouts — see [tool-integration.md](../../references/tool-integration.md#symlink-based-deployment-pointers) for verification steps).
- The tool requires tool-specific adaptation in its pointer file (rare; most tools read the canonical SKILL.md verbatim).

See [tool-integration.md](../../references/tool-integration.md#symlink-based-deployment-pointers) for the full decision guide.

**Per-tool instructions (wrapper-file fallback):**

**Claude Code:** Create a pointer at `.claude/skills/<domain>/SKILL.md` that references the canonical source (registered skills only — not capability files). Or use the plugin marketplace.

**Claude.ai:** Bundle the skill as a zip using [bundle.py](../../scripts/bundle.py), then upload via Settings > Features. Per-user. Description must be max 200 characters.

**Claude API:** Upload via `/v1/skills` endpoints. Workspace-wide.

**Codex:** `skill-installer install <skill-name>` or place in `~/.agents/skills/`. Natively scans `.agents/skills/`.

**Cursor:** If canonical content is in `.agents/skills/`, create a pointer at `.cursor/skills/<domain>/SKILL.md`. If canonical content is in `.claude/skills/`, Cursor discovers it natively.

**Windsurf:** Usually no deployment pointer needed when canonical skills live in `.agents/skills/`. Optionally add `.windsurf/rules/<domain>.md` for rules-based activation.

**Kiro:** Create a pointer at `.kiro/skills/<domain>/SKILL.md` that references the canonical source.

## Tool-Specific Extensions

Read the relevant extension reference when using tool-specific features:

- [claude-code-extensions.md](../../references/claude-code-extensions.md) — Claude Code frontmatter, subagent execution, dynamic context, string substitutions
- [codex-extensions.md](../../references/codex-extensions.md) — Codex agents/openai.yaml, six-level discovery hierarchy, invocation methods
- [cursor-extensions.md](../../references/cursor-extensions.md) — Cursor cross-vendor discovery paths, rules system, AGENTS.md support

## Key Resources

**References** — load by trigger:
- [symlink-setup.md](references/symlink-setup.md) — read when creating any symlink-based pointer (the default mechanism); contains the platform-specific commands.
- [tool-integration.md](../../references/tool-integration.md) — read when choosing the pointer mechanism for a mixed-OS team, or when the tool-specific discovery path is unclear.
- [claude-code-extensions.md](../../references/claude-code-extensions.md), [codex-extensions.md](../../references/codex-extensions.md), [cursor-extensions.md](../../references/cursor-extensions.md) — read when using a tool-specific extension (frontmatter, subagent config, rules, six-level discovery) on the named tool.

**Scripts** — run by trigger:
- [bundle.py](../../scripts/bundle.py) — run when uploading to Claude.ai or producing a release-asset zip; not needed for symlink or wrapper deployment.
