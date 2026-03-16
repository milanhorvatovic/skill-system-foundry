---
name: <skill-name>
description: >
  <Description of what this skill does and when to trigger it.
  Max 1024 characters. Be specific about contexts, keywords, and use cases.
  Include trigger phrases. Be slightly pushy to avoid under-triggering.
  Third-person voice recommended (foundry convention).
  Optionally include "Don't use when..." for disambiguation.>
allowed-tools: <optional, space-delimited pre-approved tools — experimental>
compatibility: <optional, e.g., Requires git and network access>
license: <optional, e.g., MIT>
metadata:
  author: <optional>
  version: <optional, e.g., "1.0.0">
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
     - description: third-person voice recommended ("Processes..." not
       "I process..."), include trigger phrases and contexts, be slightly
       pushy to avoid under-triggering. Max 1024 characters.
     - Body: recommended max 500 lines. Only add context the model doesn't already have.
     Remove this comment block in your final skill. -->

# <Skill Name>

## Purpose

<Brief explanation — only what the model doesn't already know.>

## Instructions

<Step-by-step guidance. Use imperative form. Explain the "why" behind important steps. Match degrees of freedom to task fragility.>

## Examples

**Example 1:** Input: <example input> Output: <example output>

## References

<Pointers to reference files, with guidance on when to read each.>
- `references/<file>.md` — Read when <condition>

## Output Format

<Expected output structure, if applicable. Use template pattern for strict requirements, flexible guidance for adaptive tasks.>
