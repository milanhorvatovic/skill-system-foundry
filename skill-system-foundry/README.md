# Skill System Foundry — Skill Documentation

This is a **meta-skill** — a skill whose domain is building other skills. It provides the architecture, templates, validation tools, and guidance needed to construct and evolve AI-agnostic skill systems. It follows a **router pattern**: a lean `SKILL.md` entry point routes to five capabilities, with shared references, templates, and scripts at the skill root.

## What This Skill Does

Skill System Foundry enables an AI model to design, build, validate, and evolve a multi-layer skill system. It covers the full lifecycle — from scaffolding a new standalone skill to migrating an entire flat structure into the router+capabilities pattern, to auditing a mature skill system for consistency.

This is not a general-purpose coding skill. It is specifically scoped to the structural and architectural concerns of organizing AI-agnostic automation across multiple tools.

## Capabilities

The skill routes to five capabilities based on task context. Each capability is self-contained — an agent loading a capability has enough context to complete the task without reading the router.

| Capability | When to Use |
|---|---|
| [skill-design](capabilities/skill-design/capability.md) | Create a skill, capability, role, or manifest; decide architecture; write descriptions |
| [validation](capabilities/validation/capability.md) | Validate a skill against the spec; audit system consistency |
| [migration](capabilities/migration/capability.md) | Migrate flat skills to the router+capabilities pattern |
| [bundling](capabilities/bundling/capability.md) | Package a skill as a zip bundle for distribution |
| [deployment](capabilities/deployment/capability.md) | Deploy to tools; set up wrappers or symlinks; use tool-specific extensions |

## File Structure

```
skill-system-foundry/
├── README.md                              ← this file
├── SKILL.md                               ← router entry point (Agent Skills specification)
├── capabilities/                          ← self-contained capability modules
│   ├── skill-design/
│   │   └── capability.md                  ← create skills, capabilities, roles, manifests
│   ├── validation/
│   │   └── capability.md                  ← validate skills, audit systems
│   ├── migration/
│   │   └── capability.md                  ← migrate flat skills to router pattern
│   ├── bundling/
│   │   └── capability.md                  ← package skills as zip bundles
│   └── deployment/
│       ├── capability.md                  ← deploy to tools, wrappers, symlinks
│       └── references/
│           └── symlink-setup.md           ← platform-specific symlink commands
├── references/                            ← guidance loaded into context on demand
│   ├── authoring-principles.md            ← shared skill authoring principles
│   ├── architecture-patterns.md           ← standalone vs router decisions
│   ├── tool-integration.md               ← tool-specific discovery, deployment, and integration
│   ├── agentskills-spec.md               ← specification compliance
│   ├── claude-code-extensions.md          ← Claude Code frontmatter and features
│   ├── codex-extensions.md               ← Codex discovery and agents/openai.yaml
│   ├── cursor-extensions.md              ← Cursor cross-vendor discovery
│   ├── anti-patterns.md                  ← common mistakes and how to avoid them
│   └── directory-structure.md            ← layout conventions
├── assets/                                ← templates copied when creating components
│   ├── skill-standalone.md               ← standalone skill template
│   ├── skill-router.md                   ← router skill template
│   ├── capability.md                     ← capability template
│   ├── role.md                           ← role template
│   └── manifest.yaml                     ← manifest schema template
└── scripts/                               ← executable validation, scaffolding, and packaging
    ├── __init__.py                        ← package marker
    ├── lib/                               ← shared library modules
    │   ├── __init__.py                    ← package marker (re-exports public API)
    │   ├── configuration.yaml            ← validation rules, domain policy, and bundle config
    │   ├── constants.py                  ← centralized constants loaded from configuration
    │   ├── validation.py                 ← shared name validation logic
    │   ├── yaml_parser.py                ← lightweight YAML-subset parser
    │   ├── frontmatter.py                ← frontmatter extraction and body utilities
    │   ├── reporting.py                  ← error categorization and formatted output
    │   ├── discovery.py                  ← component discovery (skills, roles)
    │   ├── manifest.py                   ← manifest parsing and validation
    │   ├── bundling.py                   ← core bundling logic
    │   ├── codex_config.py               ← Codex agents/openai.yaml validation
    │   └── references.py                 ← reference scanning, resolution, graph traversal
    ├── validate_skill.py                  ← single skill spec validation
    ├── audit_skill_system.py              ← full skill system audit
    ├── scaffold.py                        ← component scaffolding from templates
    └── bundle.py                          ← bundle a skill into a self-contained zip bundle
```

### References

Reference files are loaded into context when the model needs guidance for a specific task. They are never loaded at discovery time — only when the skill triggers and the task requires that specific knowledge.

| File                      | Purpose                                                           |
|---------------------------|-------------------------------------------------------------------|
| `authoring-principles.md` | Shared skill authoring principles: conciseness, descriptions, degrees of freedom, progressive disclosure, with provenance table |
| `architecture-patterns.md`| Skill-system-specific architecture decisions: standalone vs router, capability decomposition, orchestration skills (both paths) |
| `tool-integration.md`     | Tool-specific details for all supported tools (Claude Code, Codex, Cursor, Gemini CLI, Warp, OpenCode, Windsurf, Kiro, and non-Agent-Skills tools): discovery paths, deployment pointers, activation patterns, and known limitations |
| `agentskills-spec.md`     | Agent Skills specification compliance: frontmatter requirements, naming rules, line limits, and directory conventions |
| `claude-code-extensions.md` | Claude Code-specific frontmatter, subagent execution, dynamic context, string substitutions |
| `codex-extensions.md`     | Codex agents/openai.yaml, six-level discovery hierarchy, invocation methods |
| `cursor-extensions.md`    | Cursor cross-vendor discovery paths, rules system, AGENTS.md support |
| `anti-patterns.md`        | Common mistakes organized by category: system architecture (premature capabilities, deep nesting, role misuse) and skill authoring (over-explaining, inconsistent terminology, spec drift) |
| `directory-structure.md`  | Canonical directory layout for standalone skills, router skills, roles, and the system root |

### Assets

Asset files are templates that get copied and filled in when creating new components. They contain placeholder values and inline comments explaining what to replace.

| File                      | Creates                                   |
|---------------------------|-------------------------------------------|
| `skill-standalone.md`     | A standalone skill with YAML frontmatter  |
| `skill-router.md`         | A router skill with dispatch table         |
| `capability.md`           | A capability under an existing router      |
| `role.md`                 | A role with responsibility/authority/constraints contract and workflow definition |
| `manifest.yaml`           | A manifest with schema and examples         |

### Scripts

Scripts handle deterministic, repeatable tasks that should not be left to the model's judgment. They enforce consistency where text instructions would introduce variance.

| Script                    | Purpose                                                          |
|---------------------------|------------------------------------------------------------------|
| `validate_skill.py`       | Validates a single skill directory against the Agent Skills specification: checks frontmatter, naming, line counts, and resource directories |
| `audit_skill_system.py`   | Audits the full skill system: dependency direction, nesting depth, shared resource usage, and manifest presence |
| `scaffold.py`             | Creates new components from templates with proper directory structure and placeholder content |
| `bundle.py`               | Bundles a skill into a self-contained zip bundle: validates, resolves external references, rewrites paths, creates bundle |

#### YAML Parser

The `yaml_parser.py` module is a lightweight YAML-subset parser built entirely on the Python standard library — no external dependencies. It handles the subset of YAML used by skill frontmatter: key-value pairs, folded and literal block scalars, nested mappings, scalar lists, and lists of mappings. All values are returned as strings with no type coercion.

The parser deliberately excludes full YAML 1.2 compliance: it does not process escape sequences inside quoted scalars, does not resolve anchors or aliases, and does not coerce types (booleans, numbers, null). These exclusions are a direct consequence of the stdlib-only constraint and the limited YAML subset that skill frontmatter actually uses.

To bridge the gap between this lenient parser and strict YAML 1.2 parsers (such as the `yaml` npm package used by the `skills` CLI), the parser includes **plain scalar divergence detection**. During parsing, it checks unquoted values for patterns that would cause strict parsers to reject the frontmatter (FAIL) or silently misinterpret field values (WARN). The `validate_skill.py` script surfaces these findings so authors can fix portability issues before they reach consumers.

For the full details — pattern categories, quoting strategies, edge cases, and verification methods — see the [YAML Compliance](https://github.com/milanhorvatovic/skill-system-foundry/wiki/YAML-Compliance) and [Quoting Guide](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Quoting-Guide) wiki pages.

**Dependencies:** None — all scripts use the Python standard library only.

## Usage

Quick start — scaffold a skill and validate it:

```bash
python scripts/scaffold.py skill my-skill
python scripts/validate_skill.py skills/my-skill
```

For project deployments, use `--root` to target the system directory:

```bash
python scripts/scaffold.py skill my-skill --root /path/to/project/.agents
```

To bundle a skill as a self-contained zip for distribution:

```bash
python scripts/bundle.py .agents/skills/my-skill --system-root .agents --output my-skill.zip
```

For complete procedures, see the relevant capability: [skill-design](capabilities/skill-design/capability.md) for creation, [migration](capabilities/migration/capability.md) for restructuring, [validation](capabilities/validation/capability.md) for auditing, [bundling](capabilities/bundling/capability.md) for packaging, and [deployment](capabilities/deployment/capability.md) for tool integration.

### Typical Workflow

1. **Scaffold** a new component from a template
2. **Edit** the generated files with domain-specific content
3. **Validate** the skill against the spec
4. **Deploy to tools** that don't natively scan the canonical location (optional)
5. **Bundle for distribution** as a self-contained zip bundle (optional)
6. **Update the manifest** to reflect the new wiring
7. **Audit** the full skill system for consistency

## How This Skill Practices What It Preaches

> This section is for readers already familiar with the skill system's architecture and design principles. For background, see the [Architecture](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Architecture) and [Design Principles](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Design-Principles) wiki pages.

This skill is organized as a **router** within the skill system it describes. It routes to five capabilities through `capabilities/` subdirectories, with shared references, assets, and scripts at the skill root:

- **SKILL.md** is a lean router (~85 body lines) with YAML frontmatter, an architecture overview, core principles, a routing table, and a compressed shared resources section. It does not contain detailed instructions — those live in capabilities and references.
- **Progressive disclosure** is respected: the discovery layer sees only the name and description (~100 tokens). The full SKILL.md loads when triggered. Capabilities, references, assets, and scripts load only when the specific task requires them.
- **Token economy** is optimized: one skill registration covers five capabilities (loaded on demand), avoiding 5x discovery overhead.
- **Capability self-sufficiency** — each capability is self-contained with its own key resources section. An agent loading a capability has enough context to complete the task without reading the router.
- **Transitive file discoverability** — the router indexes directories, capabilities index individual files. Every shared file is reachable through router → capability → resource. This is an intentional router-pattern deviation from the stricter markdown-docs guidance that every bundled file be linked directly from `SKILL.md`.
- **The spec is followed**: valid frontmatter, name matches directory, description is third-person with trigger words, body is recommended max 500 lines.
- **Nested references are a documented exception.** Reference files cross-reference each other for navigability. This is an accepted exception to the one-level-deep rule because the meta-skill's reference files describe the skill system's own components. Running `validate_skill.py` on this skill produces nested-reference warnings; all are expected. Use `--allow-nested-references` to suppress them.

## Learn More

For supplementary context beyond this skill documentation:

| Topic | Link |
|-------|------|
| Architecture and orchestration paths | [Architecture](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Architecture) |
| Token economy and design principles | [Design Principles](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Design-Principles) |
| Tool landscape and discovery paths | [Supported Tools](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Supported-Tools) |
| Project layout and deployment strategy | [Project Integration](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Project-Integration) |
| YAML parser scope and divergence detection | [YAML Compliance](https://github.com/milanhorvatovic/skill-system-foundry/wiki/YAML-Compliance) |
| Quoting styles, fix examples, and verification | [Quoting Guide](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Quoting-Guide) |
| Key terms defined | [Glossary](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Glossary) |
| Guided examples | [Walkthroughs](https://github.com/milanhorvatovic/skill-system-foundry/wiki/Walkthroughs) |
