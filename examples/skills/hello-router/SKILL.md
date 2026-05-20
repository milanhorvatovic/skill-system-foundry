---
name: hello-router
description: >
  Greets a recipient through one of two registered tones — formal or casual —
  by dispatching to a dedicated capability. Activates when the conversation
  asks for a tone-specific welcome or a switch between formal and casual
  greetings; use when comparing the two styles. Demonstrates the router
  pattern in the Skill System Foundry — a thin SKILL.md entry point routing to
  capability files, with allowed-tools declared in frontmatter so capability
  shell fences pass validation.
allowed-tools: Bash
metadata:
  version: "1.0.0"
---

# Hello Router

## Capabilities

Route to the matching capability based on the requested tone:

| Capability | Trigger | Path |
|---|---|---|
| greet-formal | When the request asks for a formal, business-appropriate, or honorific greeting | capabilities/greet-formal/capability.md |
| greet-casual | When the request asks for a casual, friendly, or first-name greeting | capabilities/greet-casual/capability.md |

Load only the capability that matches the request. Do not load both unless the conversation explicitly compares the two tones side by side.

## Shared Behavior

Both capabilities emit a single greeting line and stop. Neither capability loops, prompts, or escalates back to this entry point. The router itself holds no business logic — it only dispatches.
