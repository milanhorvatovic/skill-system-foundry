# Agent Skills Specification Compliance

Reference for the Agent Skills specification (agentskills.io) plus platform-specific constraints and foundry conventions.

Each rule in this document is tagged with its origin:
- **[spec]** — From the Agent Skills specification (agentskills.io)
- **[platform: Anthropic]** / **[platform: OpenAI]** / **[platform: Cursor]** — From specific platform tools
- **[foundry]** — Skill System Foundry opinionated best practice / recommendation

## Contents

- [SKILL.md Format](#skillmd-format)
- [Directory Structure](#directory-structure)
- [Progressive Disclosure](#progressive-disclosure)
- [File References](#file-references)
- [Validation](#validation)
- [Foundry Conventions](#foundry-conventions)
- [Skill-System-Specific Notes](#skill-system-specific-notes)

## SKILL.md Format

**[spec]** Every registered skill requires a `SKILL.md` with YAML frontmatter + Markdown body.

### Required Frontmatter (Registered Skills)

| Field | Origin | Constraints |
|---|---|---|
| `name` | [spec] | 1-64 chars. Lowercase letters, numbers, hyphens only. Must match directory name. No leading/trailing/consecutive hyphens. |
| `description` | [spec] | 1-1024 chars. Non-empty. Describes what the skill does AND when to use it. |

### Optional Frontmatter

| Field | Origin | Constraints |
|---|---|---|
| `allowed-tools` | [spec] | Space-delimited pre-approved tools. Experimental. |
| `compatibility` | [spec] | Max 500 chars. Environment requirements. |
| `license` | [spec] | License name or reference to bundled LICENSE file. |
| `metadata` | [spec] | Arbitrary key-value map. Clients can use this for additional properties not defined by the spec. The validator is permissive with value types. |

### Platform-Specific Details

Each tool has restrictions and extensions beyond the core spec. See the linked references for full details.

**[platform: Anthropic]** `name` cannot contain "anthropic" or "claude". No XML tags in `name` or `description`. Extends frontmatter with subagent execution, dynamic context, and string substitutions. See [claude-code-extensions.md](references/claude-code-extensions.md).

**[platform: OpenAI]** Only `name` and `description` read for triggering. Supports optional `agents/openai.yaml` for UI metadata, discovery hierarchy, and tool dependencies. See [codex-extensions.md](references/codex-extensions.md).

**[platform: Cursor]** Cross-vendor discovery, rules migration, and AGENTS.md integration. See [cursor-extensions.md](references/cursor-extensions.md).

### Name Validation

**[spec]** Valid: `my-domain`, `data-analysis`, `code-review`, `deploy-ops`

**[spec]** Invalid: `My-Domain` (uppercase), `-my-domain` (leading hyphen), `my--domain` (consecutive), `my_domain` (underscores)

**[platform: Anthropic]** Invalid on Anthropic: `claude-helper` (reserved word)

## Directory Structure

**[spec]** A skill is a directory containing, at minimum, a `SKILL.md` file. The spec explicitly allows any additional files or directories.

```
skill-name/
├── SKILL.md          ← required [spec]
├── scripts/          ← optional [spec]
├── references/       ← optional [spec]
├── assets/           ← optional [spec]
└── ...               ← any additional files/directories [spec]
```

**[foundry]** The foundry also recognizes `shared/`, `capabilities/`, and `agents/` as conventional directories.

## Progressive Disclosure

**[spec]** Skills should be structured for efficient use of context:

| Level | When Loaded | Token Cost | Content |
|---|---|---|---|
| 1: Metadata | Always (startup) | ~100 tokens/skill | name + description |
| 2: Instructions | When triggered | <5000 tokens recommended | SKILL.md body (recommended max 500 lines) |
| 3: Resources | As needed | Unlimited | scripts, references, assets |

**[foundry]** Scripts execute via bash/shell without loading into context — only output consumes tokens.

## File References

**[spec]** When referencing other files in your skill, use relative paths from the skill root. Keep file references one level deep from `SKILL.md`. Avoid deeply nested reference chains.

```markdown
See [the reference guide](references/REFERENCE.md) for details.
```

**[foundry]** The foundry's shared-resource architecture uses paths that resolve outside the skill directory (e.g., `../../shared/references/file.md`). The validator reports these as INFO for awareness but skips all filesystem checks (existence, readability, nesting) for external paths to avoid acting as an existence oracle.

### Best Practices [foundry]

- Use forward slashes only (not backslashes) for cross-platform compatibility
- Use descriptive filenames: `form-validation-rules.md` not `doc2.md`

## Validation

```bash
skills-ref validate ./skill-name
```

Available from: https://github.com/agentskills/agentskills/tree/main/skills-ref

> **Note:** `skills-ref` is the official spec validator from the Agent Skills project. Skill System Foundry's [scripts/validate_skill.py](scripts/validate_skill.py) covers the same spec checks plus foundry conventions (third-person voice, semver recommendations, directory conventions, etc.) and platform restrictions (reserved words, XML tags). Use `validate_skill.py` for day-to-day skill system validation; use `skills-ref` for standalone spec conformance.

## Foundry Conventions

The following are Skill System Foundry extensions, not part of the Agent Skills specification:

- **[foundry] Third-person voice:** Descriptions should use third-person voice ("Processes data..." not "I process..."). This improves consistency across skills but is not required by the spec.
- **[foundry] Semver versioning:** `metadata.version` is recommended to follow MAJOR.MINOR.PATCH format. The spec allows any string value.
- **[foundry] Minimum name length:** Names shorter than 2 characters trigger an advisory. The spec minimum is 1 character.
- **[foundry] Per-harness tool catalogs:** `allowed-tools` entries are checked against a per-harness catalog at `allowed_tools.catalogs.<harness>` in `configuration.yaml`. Today only `claude_code` is populated, with two buckets: `harness_tools` (PascalCase Claude Code primitives like `Bash`, `Read`, `WebFetch`) and `cli_tools` (lowercase generic CLI names sometimes written into `allowed-tools` for documentation, which the harness does not recognise as primitives). Unknown tokens are then graded by shape: `mcp__server__tool` patterns are silently recognised (MCP servers are unbounded by definition), PascalCase tokens that look like harness tools but are not in the catalog get a milder INFO suggesting addition or typo correction, and everything else falls through to the generic "unrecognized tool" INFO.
- **[foundry] Fence/script vs `allowed-tools` coherence:** When `SKILL.md` or any `capabilities/<name>/capability.md` contains a fenced code block in a language listed under `tool_fence_languages.<Tool>` (currently `Bash` → `bash`, `sh`, `shell`, `zsh`), `allowed-tools` must declare the corresponding harness tool (e.g. `Bash`, possibly with restricted-arg form `Bash(git add *)`). A skill with a top-level `scripts/` directory is also expected to declare `Bash` — missing produces a WARN, not a FAIL, because some `scripts/` trees only hold non-shell helpers. Match is case-sensitive on the bare token after stripping `(...)` arguments, so lowercase `bash` does not satisfy the rule.
- **[foundry] Max tools count:** Skills listing more than 20 tools are flagged as candidates for splitting.
- **[foundry] Author max length:** `metadata.author` is limited to 128 characters.
- **[foundry] Manifest concept:** `manifest.yaml` is a foundry convention for declaring skill system structure.
- **[foundry] `shared/` directory:** Convention for resources shared across capabilities within a router skill.
- **[foundry] Script execution semantics:** "Only output consumes tokens" is a foundry guideline.

## Skill-System-Specific Notes

**Capabilities:** System-internal sub-skills under `capabilities/`, not registered in discovery. Entry point filename is `capability.md`. Frontmatter is optional and mainly for portability/documentation. If promoting a capability to a registered standalone skill, rename to `SKILL.md` and add required `name` and `description` frontmatter.

**Router skills:** Skill system convention, not in the spec. The SKILL.md body contains a dispatch table; capabilities are Level 3 resources.

**Roles:** Skill system construct not covered by the spec. Follow naming conventions for consistency.
