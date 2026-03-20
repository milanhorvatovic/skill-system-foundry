# Anti-Patterns

Common mistakes and how to avoid them.

## System Architecture

### Premature Capability Creation
Capabilities are optional granular sub-skills. Do not create them by default. Start with a standalone skill. Only introduce capabilities when the integrator explicitly asks for them or when 3+ distinct operations with different trigger contexts clearly justify decomposition. Adding capabilities too early creates unnecessary complexity and maintenance overhead.

### 1:1 Role-to-Capability Mapping
Roles should compose 2+ skills or capabilities. Thin passthroughs add overhead.

### Style-Only Role Definitions
Roles are behavioral contracts, not tone presets. If a role omits explicit responsibility, authority, and constraints (plus handoff rules), behavior becomes ambiguous.

### Deep Nesting
Never exceed router → capability (two levels). Need sub-routers? Split into separate top-level skills instead.

### Vague Router Descriptions
Capability triggers must be mutually exclusive and action-oriented. If you can't confidently determine which capability handles a task, tighten them.

### Capability-Aware Capabilities
Capabilities are independent. Cross-capability orchestration is a role's job.

### Mixing Orchestration Concerns
Skills own domain execution; roles own workflow logic. In a coordination-only skill (path 1), domain logic should not accumulate — move it to a role or domain skill. In a self-contained skill (path 2), workflow and interaction logic should not live in the skill itself — extract it to a role.

### Absolute Symlink Paths
Symlink targets must use relative paths (`../../.agents/skills/my-skill`), not absolute paths (`/home/user/project/.agents/skills/my-skill`). Absolute paths break when the repository is cloned to a different location or by a different user. See [tool-integration.md](references/tool-integration.md#symlink-based-deployment-pointers).

### Symlinks Without Team Platform Verification
Using symlinks as deployment pointers on a mixed-OS team without verifying that all Windows contributors have Developer Mode enabled (or equivalent). Symlinks that cannot be resolved degrade silently — the tool sees a broken pointer instead of skill content. Prefer wrapper files when platform support cannot be guaranteed across all contributors.

### Discovery Layer Bloat
One registered skill per domain. Consolidate related skills under routers.

### Inlining Rare, Extracting Common
Extracting every operation into its own capability — even frequently used ones — inflates token cost and adds indirection. Conversely, inlining rare operations bloats the router with seldom-used logic. If a capability is used in >80% of tasks, inline it in the router. Reserve capabilities for distinct, intermittent operations.

### Orphaned Shared Resources
Audit periodically. Single-use resources belong in their capability's directory. Remove unreferenced files.

## Skill Authoring

### Over-Explaining
Only add context the model doesn't already have. "TOML (Tom's Obvious Minimal Language) is a configuration file format..." wastes tokens.

### Too Many Options
Provide a default with an escape hatch, not multiple equivalent approaches.

### Inconsistent Terminology
Choose one term per concept. Don't mix synonyms throughout.

### Time-Sensitive Content
Use an "old patterns" section for deprecated approaches.

### Deeply Nested References
Keep references one level deep from SKILL.md. The model may partially read files referenced from other referenced files.

### First/Second Person Descriptions
Third person recommended (foundry convention). "Processes files" not "I can help you process files."

### Magic Numbers in Scripts
Document why: `REQUEST_TIMEOUT = 30  # HTTP requests typically complete within 30 seconds`.

### Punting Errors
Scripts should handle errors explicitly with helpful messages.

### Specification Drift
Always validate new skills. Treat spec compliance as a hard requirement.

### Assuming Cross-Surface Sync
Skills don't sync. Distribute manually. See the [deployment capability](capabilities/deployment/capability.md) for per-tool instructions.
