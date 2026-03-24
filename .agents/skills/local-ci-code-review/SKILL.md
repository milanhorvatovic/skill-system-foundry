---
name: local-ci-code-review
description: >
  Runs the CI code review pipeline locally, replicating the automated
  review from .github/workflows/codex-code-review.yaml without requiring
  GitHub Actions or an external API. Triggers when asked to run the CI
  review locally, replicate the pipeline review, do a deep code review,
  review like the pipeline would, or check what CI would flag. Also
  triggers on phrases like "run the CI review on this," "what would the
  pipeline review find," "deep review this branch," or "simulate the
  automated review." For running automated checks (tests, coverage,
  shellcheck), use the local-code-review skill instead. For human PR
  review process guidance, use the review skill instead.
---

# Local CI Code Review Skill

Replicates the CI code review pipeline locally. Applies the same review methodology, file-type checklists, confidence scoring, and output format defined in `.github/codex/` — executed by the local agent instead of the GitHub Actions pipeline.

## Step 1: Identify the Changes

Determine the diff to review:

```bash
# Changes on current branch vs main (default)
git diff main...HEAD

# Uncommitted changes (if no branch commits yet)
git diff HEAD

# Specific commit range (if provided)
git diff <base>..<head>
```

If no scope is specified, default to `main...HEAD`.

List the changed files and note their types — file types determine which checklists apply in Step 3.

## Step 2: Load Review Context

Read the review methodology and reference material:

- `.github/codex/review-prompt.md` — focus areas, analysis depth, priority levels, line number rules, suggestion format, self-review checklist
- `.github/codex/review-reference.md` — confidence scoring calibration, file-type checklists, few-shot examples, known limitations

These files are the authoritative source for how the review is conducted. Apply them exactly as written.

## Step 3: Review the Diff

Apply the review methodology from the loaded context. For each changed file:

1. **Identify the file type** and select the matching checklist from the reference material (Python, Shell, JavaScript, Markdown, Workflow YAML).
2. **Trace data flow** — follow values from input through parsing, transformation, and use.
3. **Check execution order** — verify validation happens before use.
4. **Verify edge cases** — empty arrays, zero, negatives, boundaries, missing optional fields.
5. **Connect schema to runtime** — check if documented contracts are enforced.
6. **Check error propagation** — verify callers handle failures.

For each finding, write the `reasoning` first, then assign priority and confidence.

### Priority levels

| Priority | Scope | Examples |
|---|---|---|
| P0 | Critical bugs, security vulnerabilities | Data loss, injection, auth bypass, crash in mainline path |
| P1 | Correctness and robustness | Off-by-one, unhandled error path, race condition |
| P2 | Maintainability and style | Misleading name, duplicated logic, missing type hint |
| P3 | Minor improvements | Whitespace, comment wording, optional simplification |

### Confidence scoring

| Range | Meaning |
|---|---|
| 0.9–1.0 | Certain — code is demonstrably wrong or violates documented rule |
| 0.7–0.9 | High — very likely based on context, depends on intent |
| 0.5–0.7 | Moderate — plausible, could be intentional |
| 0.3–0.5 | Low — possible concern, may be false positive |
| < 0.3 | Speculative — flag only if severe impact |

### Rules

- Flag only issues **introduced by the diff**. Do not flag pre-existing problems.
- Include findings at all priority levels — do not suppress low-priority findings.
- Do not flag known limitations listed in the reference material.
- Read the full source file when diff context is insufficient.

## Step 4: Run the Self-Review Checklist

Before producing output, verify:

1. Every changed file in the diff has been examined.
2. The relevant file-type checklist was applied to each file.
3. Data flow was traced for any new parsing, transformation, or validation logic.
4. Edge cases were checked for new conditional branches or numeric conversions.
5. If zero findings, each file's clean status can be explained.

## Step 5: Report Findings

Produce a structured review matching the CI pipeline output format.

### Output format

```
## Summary
[1-5 sentence description of what the changes do and why]

## Changes
- [Short bullet describing each logical change]

## Files
| File | Description |
|---|---|
| path/to/file | Short description of what changed |

## Findings

### P0 — Critical
[findings or "None"]

### P1 — Correctness
[findings or "None"]

### P2 — Maintainability
[findings or "None"]

### P3 — Minor
[findings or "None"]

## Verdict
**[patch is correct | patch is incorrect]** (confidence: X.XX)
[One-sentence rationale]
```

### Finding format

For each finding:

> **[P{n}] {title}** — `{path}:{line}` (confidence: {score})
>
> {body}
>
> <details>
> <summary>Reasoning</summary>
> {reasoning — what was observed, why it is a problem, concrete impact}
> </details>
>
> ```suggestion
> {exact replacement code, or omit block if null}
> ```

### Metadata

After the verdict, append:

```
---
Findings: {total} ({skipped} below confidence threshold)
Model: {self-reported model identifier}
Review scope: {diff range used}
```

### Rules

- Empty findings is a valid outcome — a clean diff is not a failure to review.
- Do not manufacture findings to justify the review.
- Do not suggest alternative implementations unless the current one is clearly wrong.
- Do not comment on style preferences without a documented convention backing them.
