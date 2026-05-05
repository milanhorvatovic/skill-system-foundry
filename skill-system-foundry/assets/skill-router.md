---
name: <domain-name>
description: >
  <Description covering all major capabilities and their trigger contexts.
  Max 1024 characters. Be slightly pushy. Third-person voice recommended
  (foundry convention).>
allowed-tools: <optional, space-delimited pre-approved tools — experimental>
compatibility: <optional, e.g., Requires git and network access>
license: <optional, e.g., MIT>
metadata:
  author: <optional>
  version: <optional>
# Claude Code extensions (see references/claude-code-extensions.md)
# disable-model-invocation: <optional, true prevents auto-loading by model>
# user-invocable: <optional, false hides from /menu>
# argument-hint: <optional, e.g., [issue-number]>
# model: <optional, model override when skill is active>
# context: <optional, fork runs in subagent>
# agent: <optional, subagent type when context is fork — e.g., Explore, Plan>
# hooks: <optional, skill-scoped lifecycle hooks>
---
<!-- TEMPLATE GUIDE: Replace all <placeholder> values with your content.
     - name: lowercase + hyphens only, must match parent directory name
     - description: cover ALL major capabilities and their triggers in a
       single dense paragraph. Third-person voice recommended. Max 1024 characters.
     - Capabilities are optional — only add when 3+ distinct operations justify it.
     Remove this comment block in your final skill. -->

# <Domain Name>

## Capabilities (Optional)

Capabilities are optional, granular sub-skills. Only add them when the integrator explicitly requests them or when the domain clearly demands decomposition. Start with the minimum set; add more incrementally.

Route to the appropriate capability based on the task:

| Capability | Trigger | Path |
|---|---|---|
| <name-a> | When <specific, action-oriented trigger> | capabilities/<name-a>/capability.md |
| <name-b> | When <specific, action-oriented trigger> | capabilities/<name-b>/capability.md |
| <name-c> | When <specific, action-oriented trigger> | capabilities/<name-c>/capability.md |

Read only the relevant capability file. Do not load multiple capabilities unless the task explicitly spans them.

## Shared Resources

- `shared/references/<file>.md` — Common reference material across capabilities
- `shared/assets/<file>` — Reusable templates and static resources

<!--
Trigger description rules:
- Capabilities are optional — only add rows when justified
- Mutually exclusive (no ambiguity between capabilities)
- Action-oriented for capabilities ("triage this defect")
- 1-2 sentences maximum per entry
- Create shared/ only when 2+ capabilities exist and need common resources
-->
