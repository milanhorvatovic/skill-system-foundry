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

**[platform: Anthropic]** `name` cannot contain "anthropic" or "claude". No XML tags in `name` or `description`. Extends frontmatter with subagent execution, dynamic context, and string substitutions. See [claude-code-extensions.md](claude-code-extensions.md).

**[platform: OpenAI]** Only `name` and `description` read for triggering. Supports optional `agents/openai.yaml` for UI metadata, discovery hierarchy, and tool dependencies. See [codex-extensions.md](codex-extensions.md).

**[platform: Cursor]** Cross-vendor discovery, rules migration, and AGENTS.md integration. See [cursor-extensions.md](cursor-extensions.md).

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

**[foundry]** The foundry refines the spec's relative-path requirement into a **file-relative** rule (standard markdown semantics): every link resolves from the directory containing the file the link lives in, with no privileged base. Two scopes own their own subgraph — the skill root and each capability root. A capability reaches the shared skill root via the explicit `../../<dir>/<file>` form. This refinement diverges from the spec text only in framing: the spec's worked example is a `SKILL.md` link (where file-relative and skill-root-relative resolution coincide), and the spec is silent on capabilities (a foundry construct), so the foundry defines their resolution. The full rule, the liftability invariant, and the migration cheat sheet live in [path-resolution.md](path-resolution.md).

**[foundry]** Paths that escape the skill root entirely (e.g., `../../shared/references/file.md` to a true cross-skill resource) are surfaced as INFO and skipped for filesystem checks to avoid acting as an existence oracle.

### Best Practices [foundry]

- Use forward slashes only (not backslashes) for cross-platform compatibility
- Use descriptive filenames: `form-validation-rules.md` not `doc2.md`

## Validation

```bash
skills-ref validate ./skill-name
```

Available from: https://github.com/agentskills/agentskills/tree/main/skills-ref

> **Note:** `skills-ref` is the official spec validator from the Agent Skills project. Skill System Foundry's [scripts/validate_skill.py](../scripts/validate_skill.py) covers the same spec checks plus foundry conventions (third-person voice, semver recommendations, directory conventions, etc.) and platform restrictions (reserved words, XML tags). Use `validate_skill.py` for day-to-day skill system validation; use `skills-ref` for standalone spec conformance.

## Foundry Conventions

The following are Skill System Foundry extensions, not part of the Agent Skills specification:

- **[foundry] Third-person voice:** Descriptions should use third-person voice ("Processes data..." not "I process..."). This improves consistency across skills but is not required by the spec.
- **[foundry] Semver versioning:** `metadata.version` is recommended to follow MAJOR.MINOR.PATCH format. The spec allows any string value.
- **[foundry] Minimum name length:** Names shorter than 2 characters trigger an advisory. The spec minimum is 1 character.
- **[foundry] Per-harness tool catalogs:** `allowed-tools` entries are checked against a per-harness catalog at `skill.allowed_tools.catalogs.<harness>` in `configuration.yaml`. Today only `claude_code` is populated, with two buckets: `harness_tools` (PascalCase Claude Code primitives like `Bash`, `Read`, `WebFetch`) and `cli_tools` (lowercase generic CLI names sometimes written into `allowed-tools` for documentation, which the harness does not recognise as primitives). Unknown tokens are then graded by shape: `mcp__server__tool` patterns are silently recognised (MCP servers are unbounded by definition), PascalCase tokens that look like harness tools but are not in the catalog get a milder INFO suggesting addition or typo correction, and everything else falls through to the generic "unrecognized tool" INFO.
- **[foundry] Fence/script vs `allowed-tools` coherence:** When `SKILL.md` or any `capabilities/<name>/capability.md` contains a fenced code block in a language listed under `skill.allowed_tools.fence_languages.<Tool>.languages` (currently `Bash` → `bash`, `sh`, `shell`, `zsh`), the file's effective `allowed-tools` must declare the corresponding harness tool (e.g. `Bash`, possibly with restricted-arg form `Bash(git add *)`). Tools whose YAML entry sets `scripts_dir_indicator: true` (currently `Bash`) are also expected to be declared on `SKILL.md` whenever the skill carries a top-level `scripts/` directory — missing produces a WARN, not a FAIL, because some `scripts/` trees only hold non-shell helpers. Match is case-sensitive on the bare token after stripping `(...)` arguments, so lowercase `bash` does not satisfy the rule. **Per-file effective set:** a `capability.md` declaring its own `allowed-tools` is checked against its own tokens; capabilities silent on the field fall back to the parent's declared set; `SKILL.md` always uses the parent's declared set. The rule fires once at skill scope (not per capability) — invoking `validate_skill.py --capability` on a single `capability.md` does **not** run the coherence check; the parent-level invocation owns it. Docs-only skills opt out by declaring `allowed-tools: ""` (or leaving the value blank): the field present but empty is treated as a deliberate "no harness tools" declaration and both fence and `scripts/` checks are suppressed for that scope (parent-scope opt-out also suppresses the `scripts/` check; capability-scope opt-out applies only to that capability's local fence). Inline flow-sequence form (`allowed-tools: []`) is **not** supported — the foundry's stdlib-only YAML subset parser does not recognise flow sequences, so that spelling parses as the literal string `[]` and produces an "unrecognized tools" INFO rather than the opt-out. Distinct from omitting the field entirely — a skill with no `allowed-tools` key still triggers FAIL/WARN because the runtime-blocking failure mode the rule catches is unintended omission, not deliberate restraint.
- **[foundry] Bottom-up `allowed-tools` aggregation:** Capabilities **may** declare their own `allowed-tools` to document the harness tools they need locally; the parent `SKILL.md`'s `allowed-tools` is then validated as a superset of the union of every capability-declared set. Findings: (a) FAIL per (capability, tool) when a capability declares a tool the parent does not — the same FAIL fires whether the parent omits the field, has an explicit-empty value, or carries a partial set; (b) INFO per tool when the parent declares an *observable* tool (one with a fence-language entry or a `scripts_dir_indicator` flag in `configuration.yaml`) that no capability declares **and** the parent body has no fence or `scripts/` signal for it, suggesting the parent may be over-permissioned. Tools without an observation mechanism (today: `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebFetch`, etc.) are silently suppressed because the validator has no principled basis to flag them — adding a new fence-language entry to YAML automatically extends the rule. Set semantics are bare-token only: scoped argument forms like `Bash(git:*)` declared in a capability are satisfied by `Bash` (or any other `Bash(...)` form) on the parent — the validator does not reason about argument-pattern overlap. The rule runs at skill scope; `validate_skill.py --capability` deliberately skips it because aggregation is inherently a multi-file concern.
- **[foundry] Capability-frontmatter scoping:** Only `allowed-tools` is per-capability today. Other frontmatter fields whose authoritative home is the parent `SKILL.md` (`license`, `compatibility`, `metadata.author`, `metadata.version`, `metadata.spec`) emit an INFO redirect when declared on a capability — the value is informational only at that level and the parent governs the field. Configured under `skill.capability_frontmatter.skill_only_fields` in `configuration.yaml`; adding a new skill-only field is a YAML edit only.
- **[foundry] Max tools count:** Skills listing more than 20 tools are flagged as candidates for splitting.
- **[foundry] Author max length:** `metadata.author` is limited to 128 characters.
- **[foundry] Manifest concept:** `manifest.yaml` is a foundry convention for declaring skill system structure.
- **[foundry] `shared/` directory:** Convention for resources shared across capabilities within a router skill.
- **[foundry] Script execution semantics:** "Only output consumes tokens" is a foundry guideline.

## Skill-System-Specific Notes

**Capabilities:** System-internal sub-skills under `capabilities/`, not registered in discovery. Entry point filename is `capability.md`. Frontmatter is optional and mainly for portability/documentation. If promoting a capability to a registered standalone skill, rename to `SKILL.md` and add required `name` and `description` frontmatter.

**Router skills:** Skill system convention, not in the spec. The SKILL.md body contains a dispatch table; capabilities are Level 3 resources.

**Roles:** Skill system construct not covered by the spec. Follow naming conventions for consistency.
