---
name: solution-design
description: >
  Guides the design and validation of a solution before implementation
  begins. Breaks a task into steps, identifies affected files, evaluates
  trade-offs, and validates the plan is sound. Triggers when asked to
  plan a solution, design an approach, think through a change before
  coding, break down a task, or validate a proposed plan. Also triggers
  on phrases like "how should we approach this," "plan this change,"
  "what's the best way to implement this," "break this down," or "let me
  think through this first." Use this skill as the first step in the
  development workflow — before implementation, critique, and local code
  review.
---

# Solution Design Skill

Guides the design and validation of a solution before implementation begins. Produces a structured plan that the critique skill can then challenge, and that implementation can follow step by step.

## When to Use

This skill is the first step in the development workflow:

1. **Solution design** (this skill)
2. Implement
3. Critique the implementation
4. Local code review (automated checks)
5. Push / PR

Use it whenever a task is non-trivial — more than a single-file edit or a straightforward bug fix. Skip it for simple changes where the path is obvious.

## Step 1: Understand the Task

Before designing a solution, establish clarity on what needs to happen:

- **What is the goal?** Restate the task in one sentence. If you cannot, the task is not well-defined enough to plan
- **What are the constraints?** Identify any hard constraints from AGENTS.md (stdlib-only, os.path, type hints, etc.) that apply
- **What is the scope?** Determine whether this is a single-file change, a multi-file change, or a cross-cutting concern
- **What already exists?** Search the codebase for related functionality. Do not design something that already exists or overlaps with existing code

## Step 2: Identify Affected Areas

Map out which parts of the codebase the change will touch:

- **Files to modify** — list specific files that need changes
- **Files to create** — list any new files needed (and justify why existing files cannot be extended)
- **Files to read** — list files that need to be understood but not modified (dependencies, interfaces)
- **Tests to update** — list existing test files that will need new or modified test cases
- **Tests to create** — list new test files needed for new modules

For each file, note what kind of change is needed (new function, modified logic, new test cases, updated documentation).

## Step 3: Design the Approach

Describe the solution at the right level of detail — enough to implement without ambiguity, not so much that it becomes pseudo-code.

### Structure the design around decisions

For each significant decision, state:

1. **The decision** — what approach to take
2. **The alternatives** — what other approaches were considered
3. **The rationale** — why this approach over the alternatives

Do not describe obvious implementation details. Focus on the decisions that would not be obvious to someone reading the task description alone.

### Consider integration points

- How does the new code integrate with existing modules?
- Does it follow existing patterns (e.g., `(errors, passes)` return pattern, error level constants)?
- Does it require changes to configuration.yaml?
- Does it affect the public interface of any module?

### Consider edge cases

- What inputs could be unexpected (empty, malformed, very large)?
- What happens when dependencies are missing or unavailable?
- Are there ordering or timing assumptions?

## Step 4: Define the Implementation Sequence

Order the steps so that each builds on the previous one. A good sequence:

1. Start with the lowest-level changes (library modules, constants)
2. Build up to the integration layer (entry points that use the library)
3. Add tests alongside or immediately after each layer
4. Update documentation last (it depends on the final implementation)

For each step, state:
- **What** to do (one sentence)
- **Where** to do it (file path)
- **Dependencies** — which previous steps must be complete first

## Step 5: Validate the Plan

Before starting implementation, check the plan against these criteria:

### Completeness

- Does every affected file have a clear change description?
- Are all new functions/modules accounted for?
- Are tests included for every new code path?
- Is documentation updated if user-facing behavior changes?

### Consistency

- Does the plan follow existing codebase patterns?
- Are naming conventions consistent with AGENTS.md?
- Do new validation rules go in configuration.yaml (not hardcoded)?

### Feasibility

- Can each step be implemented independently and tested?
- Are there circular dependencies between steps?
- Is the scope realistic for a single PR, or should it be split?

### Risk

- Which step is most likely to cause problems?
- What is the fallback if the approach does not work?
- Are there breaking changes that need migration paths?

If the plan fails any of these checks, revise it before proceeding.

## Output Format

```
## Solution Design

### Goal
(one-sentence restatement of the task)

### Constraints
(relevant constraints from AGENTS.md or the spec)

### Affected Files
| File | Action | Description |
|---|---|---|
| path/to/file.py | Modify | Brief description of change |
| path/to/new.py | Create | Brief description of purpose |
| tests/test_new.py | Create | Tests for new module |

### Approach
(description of the solution with key decisions and rationale)

### Implementation Sequence
1. (step — file — dependencies)
2. (step — file — dependencies)
3. ...

### Risks
(key risks and mitigations, or "None identified")

### Validation
- Completeness: (pass/issues)
- Consistency: (pass/issues)
- Feasibility: (pass/issues)
- Risk: (low/medium/high — rationale)
```

## Rules

- **Do not write code during planning** — the output is a plan, not an implementation. Code belongs in the implementation step
- **Do not over-plan simple changes** — if the task is a one-file bug fix, skip this skill entirely. Planning is for non-trivial work
- **Be specific about files** — "update the validation logic" is vague. "Add a `validate_forward_slashes()` function to `scripts/lib/validation.py`" is actionable
- **Surface unknowns early** — if the plan depends on understanding code you have not read yet, call that out. Read the code before finalizing the plan
- **Keep it concise** — a plan that takes longer to read than the implementation takes to write is over-engineered
