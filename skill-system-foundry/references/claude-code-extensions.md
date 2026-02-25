# Claude Code Extensions

Claude Code extends the Agent Skills specification (agentskills.io) with additional frontmatter fields and features. This reference covers what is specific to Claude Code; see [agentskills-spec.md](agentskills-spec.md) for the core specification and [tool-integration.md](tool-integration.md) for cross-tool architecture.

## Table of Contents

- [Extended Frontmatter](#extended-frontmatter)
- [Invocation Control](#invocation-control)
- [Subagent Execution](#subagent-execution)
- [Dynamic Context Injection](#dynamic-context-injection)
- [String Substitutions](#string-substitutions)
- [Discovery Paths](#discovery-paths)
- [Surfaces](#surfaces)
- [Loading Mechanism](#loading-mechanism)
- [Skill Access Control](#skill-access-control)
- [Context Budget](#context-budget)
- [Deployment Pointer](#deployment-pointer)

## Extended Frontmatter

Claude Code supports all core Agent Skills frontmatter fields plus:

| Field | Required | Description |
|---|---|---|
| `disable-model-invocation` | No | When `true`, prevents the model from auto-loading the skill. Only manual `/skill-name` invocation works. Default: `false`. |
| `user-invocable` | No | When `false`, hides the skill from the `/` menu. Use for background knowledge the model should access but users shouldn't invoke directly. Default: `true`. |
| `argument-hint` | No | Hint shown during autocomplete to indicate expected arguments, e.g. `[issue-number]` or `[filename] [format]`. |
| `model` | No | Model override when this skill is active. |
| `context` | No | Set to `fork` to run the skill in an isolated subagent context. |
| `agent` | No | Subagent type when `context: fork` — built-in (`Explore`, `Plan`, `general-purpose`) or custom agent name from `.claude/agents/`. |
| `hooks` | No | Hooks scoped to this skill's lifecycle. |

## Invocation Control

| Frontmatter | User can invoke | Model can invoke | When loaded into context |
|---|---|---|---|
| (default) | Yes | Yes | Description always in context, full skill loads when invoked |
| `disable-model-invocation: true` | Yes | No | Description not in context, full skill loads when user invokes |
| `user-invocable: false` | No | Yes | Description always in context, full skill loads when invoked |

## Subagent Execution

Set `context: fork` to run a skill in an isolated subagent. The skill content becomes the prompt. Combine with `agent` to select the execution environment:

- `Explore` — read-only codebase exploration
- `Plan` — architecture and implementation planning
- `general-purpose` — full tool access (default when `agent` omitted)
- Custom agents from `.claude/agents/`

Skills with `context: fork` need explicit instructions (a task), not just guidelines. The subagent receives no conversation history.

## Dynamic Context Injection

The `` !`command` `` syntax runs shell commands before skill content is sent to the model. Output replaces the placeholder:

```
!`gh pr diff` → replaced with actual PR diff output at load time
```

This is preprocessing — the model only sees the final rendered content.

## String Substitutions

| Variable | Description |
|---|---|
| `$ARGUMENTS` | All arguments passed when invoking the skill. Appended as `ARGUMENTS: <value>` if not present in content. |
| `$ARGUMENTS[N]` | Specific argument by 0-based index. |
| `$N` | Shorthand for `$ARGUMENTS[N]`. |
| `${CLAUDE_SESSION_ID}` | Current session ID. |

## Discovery Paths

| Level | Path | Applies to |
|---|---|---|
| Enterprise | Managed settings | All users in organization |
| Personal | `~/.claude/skills/<skill-name>/SKILL.md` | All your projects |
| Project | `.claude/skills/<skill-name>/SKILL.md` | This project only |
| Plugin | `<plugin>/skills/<skill-name>/SKILL.md` | Where plugin is enabled |

Priority: enterprise > personal > project. Plugin skills use `plugin-name:skill-name` namespace (no conflicts). Nested `.claude/skills/` directories in subdirectories are auto-discovered (monorepo support).

Skills from `--add-dir` directories are loaded automatically with live change detection.

Plugin marketplace:
```
/plugin marketplace add <org>/<repo>
/plugin install <plugin-name>@<marketplace>
```

## Surfaces

| Surface | Network | Packages | Notes |
|---|---|---|---|
| Claude Code (CLI) | Full | Yes (prefer local) | Primary surface |
| Claude.ai (Consumer) | Varies | Yes (npm, PyPI, GitHub) | Upload zip via Settings > Features, per-user |
| Claude API | None | No (pre-installed only) | `/v1/skills` endpoints, `skill_id`, beta headers |

## Loading Mechanism

- Reads SKILL.md via bash/filesystem tools
- Scripts executed via bash
- Full network access (same as user's machine)
- Can install packages (prefer local installation)

## Skill Access Control

Three ways to control skill invocation:

- **Deny all skills:** Add `Skill` to permission deny rules
- **Allow/deny specific skills:** `Skill(name)` for exact, `Skill(name *)` for prefix
- **Hide individual skills:** `disable-model-invocation: true` in frontmatter

## Context Budget

Skill descriptions share a dynamic character budget (2% of context window, fallback 16,000 chars). Override with `SLASH_COMMAND_TOOL_CHAR_BUDGET` environment variable. Run `/context` to check for excluded skills.

## Deployment Pointer

When creating a deployment pointer for Claude Code (see [tool-integration.md](tool-integration.md)), use these tool conventions:
- File reading: bash `cat` or Claude's `view` tool
- Tool invocation: bash commands, MCP with `ServerName:tool_name` format
- Scripts: execute directly via bash
- Packages: install locally, don't modify global environment
