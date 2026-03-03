# Agent Skills Specification Compliance

Reference for the Agent Skills specification (agentskills.io) plus platform-specific constraints from Anthropic, OpenAI, and Cursor.

## SKILL.md Format

Every registered skill requires a `SKILL.md` with YAML frontmatter + Markdown body.

### Required Frontmatter (Registered Skills)

| Field | Constraints |
|---|---|
| `name` | Max 64 chars. Lowercase letters, numbers, hyphens only. Must match directory name. No leading/trailing/consecutive hyphens. |
| `description` | Max 1024 chars. Non-empty. Third-person. Describes what the skill does AND when to use it. |

### Optional Frontmatter

| Field | Constraints |
|---|---|
| `allowed-tools` | Space-delimited pre-approved tools. Experimental. |
| `compatibility` | Max 500 chars. Environment requirements. |
| `license` | License name or reference to bundled LICENSE file. |
| `metadata` | Arbitrary key-value map (string → string). |

### Platform-Specific Details

Each tool has restrictions and extensions beyond the core spec. See the linked references for full details.

**Anthropic (Claude Code):** `name` cannot contain "anthropic" or "claude". No XML tags in `name` or `description`. Extends frontmatter with subagent execution, dynamic context, and string substitutions. See [claude-code-extensions.md](claude-code-extensions.md).

**OpenAI (Codex):** Only `name` and `description` read for triggering. Supports optional `agents/openai.yaml` for UI metadata, discovery hierarchy, and tool dependencies. See [codex-extensions.md](codex-extensions.md).

**Cursor:** Cross-vendor discovery, rules migration, and AGENTS.md integration. See [cursor-extensions.md](cursor-extensions.md).

### Name Validation

Valid: `my-domain`, `data-analysis`, `code-review`, `deploy-ops`

Invalid: `My-Domain` (uppercase), `-my-domain` (leading hyphen), `my--domain` (consecutive), `my_domain` (underscores), `claude-helper` (reserved word on Anthropic)

## Directory Structure

```
skill-name/
├── SKILL.md          ← required
├── scripts/          ← optional, executable code
├── references/       ← optional, documentation
└── assets/           ← optional, static resources
```

## Progressive Disclosure

| Level | When Loaded | Token Cost | Content |
|---|---|---|---|
| 1: Metadata | Always (startup) | ~100 tokens/skill | name + description |
| 2: Instructions | When triggered | <5000 tokens | SKILL.md body (recommended max 500 lines) |
| 3: Resources | As needed | Unlimited | scripts, references, assets |

Scripts execute via bash/shell without loading into context — only output consumes tokens.

## File References

- Relative paths from skill root
- One level deep from SKILL.md — meaning SKILL.md references files directly, but those files must not reference further files (no chained references). This does not restrict filesystem path depth (e.g., `../../shared/references/file.md` is valid).
- Forward slashes only (not backslashes)
- Descriptive filenames: `form-validation-rules.md` not `doc2.md`

## Validation

```bash
skills-ref validate ./skill-name
```

Available from: https://github.com/agentskills/agentskills/tree/main/skills-ref

> **Note:** `skills-ref` is the official spec validator from the Agent Skills project. Skill System Foundry's [scripts/validate_skill.py](../scripts/validate_skill.py) covers the same spec checks plus skill-system-specific rules (nested references, directory conventions, reserved-word checks). Use `validate_skill.py` for day-to-day skill system validation; use `skills-ref` for standalone spec conformance.

## Skill-System-Specific Notes

**Capabilities:** System-internal sub-skills under `capabilities/`, not registered in discovery. Entry point filename is `capability.md`. Frontmatter is optional and mainly for portability/documentation. If promoting a capability to a registered standalone skill, rename to `SKILL.md` and add required `name` and `description` frontmatter.

**Router skills:** Skill system convention, not in the spec. The SKILL.md body contains a dispatch table; capabilities are Level 3 resources.

**Roles:** Skill system construct not covered by the spec. Follow naming conventions for consistency.
