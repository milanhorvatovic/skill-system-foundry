# Architecture Patterns

## Table of Contents

- [Standalone vs Router: When to Split](#standalone-vs-router-when-to-split)
- [Orchestration Skills](#orchestration-skills)

---

Patterns specific to this skill system's multi-layer architecture. These extend the shared authoring principles (see [authoring-principles.md](authoring-principles.md)) for multi-skill, multi-tool systems.

---

## Standalone vs Router: When to Split

This is the first architectural decision when creating a skill. The default is always standalone. Only escalate to the router pattern when the evidence demands it.

### Stay Standalone When

- The skill performs a **single cohesive task** (even if complex).
- All operations share the **same trigger context** — the model never needs to choose between sub-tasks.
- The SKILL.md body stays **under ~300 lines** with references handling depth.
- The skill has **fewer than 3 distinct operations**, or the operations overlap enough that separating them would create ambiguous routing.
- You can describe the skill's purpose in **one sentence** without using "and" to join unrelated concerns.

**Example:** A `code-review` skill that analyzes code, checks conventions, and suggests improvements. These are steps in one workflow, not independent operations with different triggers.

### Split Into Router + Capabilities When

All three conditions are met:

1. **3+ distinct operations** exist, each with a clearly different trigger context (e.g., "triage a defect" vs. "generate a test plan" vs. "run a release gate check").
2. **Triggers are mutually exclusive** — given a user request, you can unambiguously determine which capability handles it. If you can't write non-overlapping trigger descriptions, don't split.
3. **Operations are independently useful** — each capability delivers value on its own without needing sibling capabilities. If operations frequently co-occur, they belong in one standalone skill or one capability.

### Decision Checklist

Ask these questions in order. Stop at the first "no":

1. Does the domain have 3+ operations with **different trigger phrases**? → No: stay standalone.
2. Can you write **mutually exclusive** trigger descriptions for each? → No: the operations are too intertwined — stay standalone.
3. Are the operations **independently useful** (not steps in a single workflow)? → No: stay standalone; use sections or references for internal structure.
4. Would a user reasonably invoke **only one** of these operations per task? → No: stay standalone; the model would load multiple capabilities anyway, negating the token savings.
5. Is the combined SKILL.md **growing past maintainability** (~500 lines body)? → If yes and the above hold: split. If no: stay standalone even with 3+ operations — size alone isn't a reason to split.

### Progression Path

```
standalone skill
    ↓ (when 3+ distinct, mutually exclusive, independent operations emerge)
router skill + capabilities
```

Do not skip the standalone phase. A skill should earn its capabilities through demonstrated complexity, not speculative design.

### What Is NOT a Reason to Split

- **Size alone.** A 400-line standalone skill with good progressive disclosure (references, conditional sections) is better than a premature router.
- **Organizational tidiness.** Directories don't help if the model still loads everything. Capabilities save tokens only when loaded selectively.
- **Future growth.** Design for what exists now. Add capabilities incrementally when new operations actually materialize.
- **One or two operations.** Two operations can coexist in a standalone skill using conditional workflow sections. A router with 1-2 capabilities adds overhead for no benefit.

---

## Orchestration Skills

A skill can serve as the entry point for orchestration. Two valid orchestration paths exist:

```
orchestration skill → roles → skills (with optional capabilities)
skill (standalone or router) → role(s) → skill's capabilities
```

Both are valid approaches serving different needs — not competing alternatives. A skill can load **one or more roles** based on the requirements of the flow.

### Path 1: Coordination-Only Skill

A lean standalone skill sequences roles across domains. It contains no domain logic — purely coordinates.

**When to use:**
- The workflow spans **multiple unrelated domains** and should be natively discoverable as a single entry point.
- The entry point requires **coordination logic** (selecting roles, sequencing workflows) that goes beyond what a single role should contain.
- Multiple roles need to be composed into a single discoverable entry point without creating a new role that merely wraps other roles.

**Constraints:**
- References **roles only** — never domain skills directly.
- Contains **no domain logic** — if domain-specific instructions accumulate, move them to a role or domain skill.
- A coordination-only skill may sequence multiple roles across domains.

### Path 2: Self-Contained Skill

A domain skill (standalone or router with capabilities) loads one or more roles for interactive workflow logic. The skill owns capabilities; roles provide responsibility, authority, and constraints, plus sequencing and interaction patterns.

**When to use:**
- The domain, capabilities, and orchestration belong together as **one discoverable unit** (e.g., a project management router skill with roles that know how to use its capabilities for triage, refinement, and gate checks).
- The skill already exists as a standalone or router and needs **interactive workflow logic** that a role provides.

**Constraints:**
- The skill owns **domain capabilities**; the role owns **workflow logic** — keep these separated.
- The role should define explicit responsibility, authority, and constraints, including handoff rules.
- The role references the skill's capabilities by system-root-relative path (e.g., `skills/<domain>/capabilities/<cap>/SKILL.md`).
- A self-contained skill may load different roles for different workflow phases, though adding multiple roles increases complexity — weigh the coordination overhead against the benefit before introducing additional roles.

**Not circular.** The skill provides the entry point and loads the role for workflow logic. The role references the skill's capabilities for execution. The capabilities themselves remain unaware of the role. This is a complementary relationship, not a circular dependency.

### Shared Principle

Regardless of path: **the skill owns domain execution, the role owns workflow logic** — keep these concerns separated. A thin deployment pointer can optionally sit in front of any path for tools that require tool-specific adaptation (see [tool-integration.md](tool-integration.md)).

### Decision Checklist

1. Does the workflow span multiple unrelated domains with no shared capabilities? → Yes: use **path 1** (coordination-only skill).
2. Do the domain capabilities and orchestration belong together as one discoverable unit? → Yes: use **path 2** (self-contained skill).
