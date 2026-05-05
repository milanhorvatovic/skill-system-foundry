# Codex Extensions

Codex extends the Agent Skills specification (agentskills.io) with `agents/openai.yaml` for UI metadata and tool dependencies. This reference covers what is specific to Codex; see [agentskills-spec.md](agentskills-spec.md) for the core specification and [tool-integration.md](tool-integration.md) for cross-tool architecture.

## Table of Contents

- [agents/openai.yaml](#agentsopenaiyaml)
- [Discovery Paths](#discovery-paths)
- [Invocation Methods](#invocation-methods)
- [Configuration](#configuration)
- [Loading Mechanism](#loading-mechanism)
- [Deployment Pointer](#deployment-pointer)
- [Limitations](#limitations)

## agents/openai.yaml

Optional file placed alongside SKILL.md for Codex-specific configuration.

### Interface (UI Metadata)

| Field | Description |
|---|---|
| `interface.display_name` | Custom UI label for the skill. |
| `interface.short_description` | UI-specific description (separate from SKILL.md description). |
| `interface.icon_small` | Path to small icon (SVG). |
| `interface.icon_large` | Path to large icon (PNG). |
| `interface.brand_color` | Hex color for UI theming. |
| `interface.default_prompt` | Surrounding context prepended to skill invocation. |

### Policy

| Field | Description |
|---|---|
| `policy.allow_implicit_invocation` | When `false`, skill only activates via explicit `$skillname` or `/skills` menu. Default: `true`. |

### Dependencies

| Field | Description |
|---|---|
| `dependencies.tools` | Array of tool dependencies (MCP servers, etc.). |
| `dependencies.tools[].type` | Tool type, e.g. `mcp`. |
| `dependencies.tools[].value` | Tool identifier. |
| `dependencies.tools[].description` | Tool purpose. |
| `dependencies.tools[].transport` | Transport protocol, e.g. `streamable_http`. |
| `dependencies.tools[].url` | Tool endpoint URL. |

### Example

```yaml
interface:
  display_name: "Deploy Manager"
  short_description: "Deploy applications to production"
  icon_small: "./assets/deploy-icon.svg"
  brand_color: "#10B981"

policy:
  allow_implicit_invocation: false

dependencies:
  tools:
    - type: mcp
      value: deploy-server
      description: "Deployment orchestration"
      transport: streamable_http
      url: "http://localhost:3000/mcp"
```

## Discovery Paths

Six-level hierarchy (highest to lowest priority):

| Scope | Path | Use case |
|---|---|---|
| Repo (CWD) | `.agents/skills/` in working directory | Folder-specific workflows |
| Repo (parent) | `.agents/skills/` in parent directories | Nested repository skills |
| Repo (root) | `.agents/skills/` at `$REPO_ROOT` | Organization-wide skills |
| User | `~/.agents/skills/` | Cross-repository skills |
| Admin | `/etc/codex/skills/` | System-level defaults |
| System | Bundled by OpenAI | Built-in skills |

Codex follows symlinked skill folders. Duplicate skill names are allowed (both appear in selectors).

Skill installer:
```
skill-installer install <skill-name>
skill-installer install <skill-name> from the .experimental folder
```

## Invocation Methods

- **Explicit:** `/skills` command or `$skillname` syntax
- **Implicit:** Codex selects skills matching the task description

## Configuration

Disable individual skills via `~/.codex/config.toml`:

```toml
[[skills.config]]
path = "/path/to/skill/SKILL.md"
enabled = false
```

Requires Codex restart to apply.

## Loading Mechanism

- Reads frontmatter (name/description) into system prompt
- When triggered, reads SKILL.md via shell tool
- Progressive disclosure — full content loads only on activation
- Supports `agents/openai.yaml` for UI metadata and invocation policy

## Deployment Pointer

Deployment pointers for Codex can be wrapper files or symlinks. Codex follows symlinked skill folders (see [Discovery Paths](#discovery-paths)). See [tool-integration.md](tool-integration.md#symlink-based-deployment-pointers) for the decision guide and platform commands.

When creating a wrapper-based deployment pointer for Codex (see [tool-integration.md](tool-integration.md)), use these tool conventions:
- File reading: shell tool (read, cat, head)
- Tool invocation: shell commands
- Include `agents/openai.yaml` if UI metadata needed

## Limitations

- No skill merging on name conflicts (both appear in selectors)
- `allow_implicit_invocation: false` blocks only implicit selection; explicit `$skillname` invocation still works
- Skill folder changes may require restart for detection
- Symlink support requires proper target resolution
