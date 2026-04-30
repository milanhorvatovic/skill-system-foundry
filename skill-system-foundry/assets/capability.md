---
name: <capability-name>
description: >
  <Description of what this capability does and when to use it.
  Max 1024 characters. Be specific about contexts, keywords, and use cases.
  Third-person voice recommended (foundry convention).>
# allowed-tools: optional, space-delimited harness tools needed by THIS
#   capability — e.g. "Bash Read".  The foundry uses bottom-up
#   aggregation: the parent SKILL.md must be a superset of the union of
#   capability-declared sets.  Declaring per-capability tools enables
#   precise validation and makes future tool surface changes
#   self-documenting.  Skill-wide fields (license, compatibility,
#   metadata.author/version/spec) belong only on the parent SKILL.md;
#   declaring them here triggers an INFO redirect.
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
- Bottom-up aggregation: per-capability ``allowed-tools`` is unioned and
  the parent SKILL.md is validated as a superset.  Skill-wide fields
  (license, compatibility, metadata.*) belong only on the parent.
- Must not reference sibling capabilities
- Cross-capability orchestration is a role's job
- Prefer keeping a skill standalone until 3+ distinct operations justify a router
-->
