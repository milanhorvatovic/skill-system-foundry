---
name: <capability-name>
description: >
  <Third-person description of what this capability does and when to use it.
  Max 1024 characters. Be specific about contexts, keywords, and use cases.>
allowed-tools: <optional, space-delimited pre-approved tools — experimental>
compatibility: <optional, e.g., Requires git and network access>
license: <optional, e.g., MIT>
metadata:
  author: <optional>
  version: <optional, e.g., "1.0">
---
# <Capability Name>
<!-- TEMPLATE GUIDE: Save this file as `capability.md` inside the capability
     directory: capabilities/<name>/capability.md
     Replace <Capability Name> and all <placeholder> values. Capabilities are
     loaded on demand — this is where depth lives. Be comprehensive in
     Instructions. Frontmatter is not used for discovery but keeps capabilities
     portable and promotion-ready. Must not reference sibling capabilities. -->

## Purpose

<What this capability does within the parent domain.>

## Instructions

<Detailed step-by-step guidance. Capabilities can be comprehensive since they're loaded on demand — this is where depth lives. Use imperative form. Explain the "why" behind important steps.>

## References

- `references/<file>.md` — Read when <condition>
- `../../shared/references/<file>.md` — Shared reference, read when <condition>
- `../../shared/assets/<file>` — Shared asset, use when <condition>

## Output Format

<Expected output structure, if applicable.>

<!--
Notes:
- Capabilities are OPTIONAL granular sub-skills — only create when the
  integrator explicitly requests it or the domain clearly warrants decomposition
- Capabilities are NOT registered in the discovery layer
- Frontmatter is included to keep capabilities portable and promotion-ready
  (shared resource paths may need updating on promotion to standalone)
- Router skills can aggregate frontmatter from their capabilities (e.g., allowed-tools)
- Must not reference sibling capabilities
- Cross-capability orchestration is a role's job
- Prefer keeping a skill standalone until 3+ distinct operations justify a router
-->
