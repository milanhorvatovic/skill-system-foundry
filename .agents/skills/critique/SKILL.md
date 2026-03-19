---
name: critique
description: >
  Provides constructive criticism of proposed plans and implemented solutions
  in the Skill System Foundry repository. Challenges approach decisions,
  identifies weaknesses, trade-offs, and blind spots before changes reach
  automated checks or PR review. Triggers when asked to critique a solution,
  challenge an approach, find weaknesses in an implementation, review a plan
  before implementation, play devil's advocate, or provide constructive
  feedback on design decisions. Also triggers on phrases like "what could go
  wrong," "what am I missing," "is this the right approach," "poke holes in
  this," or "give me honest feedback." Use this skill after implementation
  and before running local-code-review to catch design-level issues that
  automated checks cannot detect.
---

# Critique Skill

Provides constructive, opinionated criticism of plans and implemented solutions in the Skill System Foundry repository. This skill focuses on qualitative judgment — whether the approach is sound, maintainable, and complete — not on mechanical checks (that is what local-code-review handles).

## When to Use

This skill sits in the development workflow between implementation and automated checks:

1. Plan the solution
2. Validate the plan
3. Implement it
4. **Critique the implementation** (this skill)
5. Local code review (automated checks)
6. Push / PR

It can also be used earlier — to critique a proposed plan before implementation begins.

## Step 1: Understand the Intent

Before criticizing, establish what the change is trying to achieve:

- Read the diff or proposed plan
- Identify the stated goal (what problem does this solve?)
- Note the scope (how many files, what areas of the codebase)

Do not critique without understanding intent. Criticism of a solution you misunderstand is noise.

## Step 2: Challenge the Approach

Ask these questions about the solution. Each "no" is a finding:

### Is this the simplest solution?

- Could a simpler approach achieve the same result?
- Are there abstractions that add complexity without clear benefit?
- Is there indirection that makes the code harder to follow?
- Would a future contributor understand this without explanation?

### Does it solve the right problem?

- Does the solution address the root cause or just the symptom?
- Are there edge cases the solution does not handle?
- Does it make assumptions about inputs that may not hold?
- Could the problem recur in a different form?

### What are the trade-offs?

- What does this solution gain? What does it sacrifice?
- Does it trade short-term convenience for long-term maintenance cost?
- Does it introduce coupling between previously independent components?
- Does it make future changes harder or easier?

### Is it consistent with the codebase?

- Does it follow established patterns in the repository?
- Does it introduce a new pattern where an existing one would work?
- If it introduces a new pattern, is the deviation justified?
- Does it respect the architectural boundaries (skills, capabilities, roles)?

### What could go wrong?

- What happens if inputs are unexpected (empty, malformed, very large)?
- Are there failure modes that are silently ignored?
- Could this break existing functionality?
- Are there concurrency or ordering assumptions?

## Step 3: Evaluate Completeness

Check whether the solution is finished or has gaps:

- **Missing tests** — not "are tests present" (local-code-review handles that) but "do the tests cover the interesting scenarios and edge cases?"
- **Missing documentation** — if the change affects user-facing behavior, is it reflected in descriptions, references, or templates?
- **Missing migration path** — if this changes behavior, do existing users have a way to adapt?
- **Unfinished work** — are there TODOs, placeholder values, or commented-out code that suggest the solution is incomplete?

## Step 4: Report Findings

Structure criticism as actionable findings. Every finding must include:

1. **What** — the specific concern (one sentence)
2. **Why it matters** — the impact if unaddressed (one sentence)
3. **Suggestion** — a concrete alternative or improvement (one sentence or code snippet)

### Severity Levels

- **Rethink** — the approach has a fundamental flaw that will cause problems. Suggest an alternative direction before proceeding
- **Improve** — the approach is sound but has a weakness that should be addressed. Suggest a specific fix
- **Consider** — a trade-off or edge case worth thinking about. May be acceptable as-is with explicit acknowledgment

### Output Format

```
## Critique Summary

**Goal:** [one-sentence restatement of what the change achieves]
**Approach:** [one-sentence summary of how it achieves it]

## Findings

### Rethink
(list or "None")

### Improve
(list or "None")

### Consider
(list or "None")

## Overall Assessment
[1-2 sentences: is the approach sound? What is the single most important
thing to address before proceeding?]
```

## Rules

- **Be constructive** — every criticism must come with a suggestion. "This is wrong" without a direction forward is not useful
- **Be specific** — "the error handling could be better" is vague. "The `validate_name` function swallows the `KeyError` on line 42 — propagate it with a descriptive message" is actionable
- **Be honest** — do not soften findings to be polite. A clear "this will break when X happens" is more respectful than hedging
- **Prioritize** — report at most 5-7 findings. If everything is a problem, focus on the ones with the highest impact. Do not overwhelm with a wall of criticism
- **Acknowledge strengths** — if the approach has clear strengths, note them briefly in the overall assessment. This is not about being positive for its own sake — it helps the contributor understand what to preserve
- **Do not duplicate automated checks** — if local-code-review or CI would catch it (missing type hints, test failures, shellcheck violations), do not report it here. Focus on what requires human judgment
- **Separate opinion from fact** — if a finding is subjective ("I would prefer X"), say so. If it is objective ("this will fail when the input is empty"), state it as fact
- **Respect the codebase conventions** — critique within the framework of AGENTS.md constraints. Do not suggest pathlib when the repo uses os.path. Do not suggest third-party libraries when the repo is stdlib-only
