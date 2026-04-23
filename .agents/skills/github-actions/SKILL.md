---
name: github-actions
description: >
  Guides the creation, modification, and review of GitHub Actions workflows
  in the Skill System Foundry repository. Covers workflow YAML syntax,
  trigger configuration, permission models, SHA-pinned actions, matrix
  strategies, artifact passing, and concurrency control. Triggers when
  asked to create or modify a workflow, add a CI job, configure triggers
  or permissions, pin an action to a SHA, troubleshoot a failing workflow,
  or review a workflow change. Also triggers on phrases like "add a
  workflow," "fix the CI," "pin this action," "workflow permissions,"
  or "why is this action failing." Use this skill for any work involving
  .github/workflows/ YAML files.
---

# GitHub Actions Skill

Guides the creation, modification, and review of GitHub Actions workflows in the Skill System Foundry repository. Codifies the conventions established across the repository's existing workflows.

## Repository Workflows

| Workflow | File | Trigger | Jobs |
|---|---|---|---|
| Tests + coverage | `python-tests.yaml` | Push to `main`, PRs | `test` (matrix), `update-badge` |
| Shell lint | `shellcheck.yaml` | Push/PR (path-filtered to `.sh`) | `shellcheck` |
| Action-pin verify | `verify-action-pins.yaml` | Push to `main`, PRs | `verify` |
| Codex code review | `codex-code-review.yaml` | PR events (non-draft) | `review` (read-only), `publish` (write) |
| Release bundle | `release.yml` | Release published | `bundle` |

## Hard Requirements

### Actions Pinned to Commit SHAs

Every action must be pinned to a full 40-character commit SHA, not a tag. Include a comment with the tag and semver for readability:

```yaml
# Correct
- uses: actions/checkout@de0fac2e5ef641dbfe0fef2a1de4a5c3a0d70dce  # @v6 as 6.0.2

# Wrong — tag-only reference
- uses: actions/checkout@v4
```

When updating an action version:
1. Find the new tag's commit SHA on the action's repository releases page
2. Replace the SHA in the workflow
3. Update the comment to reflect the new tag and version

This rule is enforced by `.github/scripts/verify-action-pins.py`, which the `verify-action-pins.yaml` workflow runs on every PR and push to `main`. Any `uses:` line that is not a 40-character lowercase commit SHA (or `./local-path` / `docker://...`) fails CI. Run the script locally with `python .github/scripts/verify-action-pins.py` to check before pushing.

### Least-Privilege Permissions

Scope permissions as narrowly as possible. Default to `contents: read`. Only add write permissions where required, and prefer job-level over workflow-level permissions:

```yaml
# Preferred: job-level permissions
jobs:
  test:
    permissions:
      contents: read
  deploy:
    permissions:
      contents: write

# Acceptable: workflow-level when all jobs need the same
permissions:
  contents: read
```

The Codex code review workflow demonstrates the ideal pattern: a read-only `review` job followed by a write-capable `publish` job, isolating the permission boundary.

### No Hardcoded Secrets

Secrets are accessed via `${{ secrets.VARIABLE_NAME }}`, variables via `${{ vars.VARIABLE_NAME }}`. Never echo secrets to logs. Shell scripts called by workflows validate required environment variables at the top with `${VAR:?}`.

## Conventions

### Trigger Configuration

- **Push to `main`** — for CI that should run on every merge (tests, badge updates)
- **`pull_request`** — for validation that gates merges (tests, lint, code review)
- **Path filtering** — use `paths:` to avoid triggering on unrelated changes. `shellcheck.yaml` only runs when `.sh` files change
- **Activity types** — specify explicit types for PR workflows when not all events are relevant: `types: [opened, reopened, synchronize, ready_for_review]`

### Runner Selection

- `ubuntu-latest` is the default for all jobs
- Add `windows-latest` via matrix only when cross-platform testing is needed (currently only `python-tests.yaml`)
- Do not add macOS unless explicitly required — it consumes more CI minutes

### Matrix Strategy

Use matrix for cross-platform or multi-version testing. Set `fail-fast: false` so all combinations run even if one fails:

```yaml
strategy:
  fail-fast: false
  matrix:
    os: [ubuntu-latest, windows-latest]
    python-version: ["3.12"]
```

### Concurrency Control

Use concurrency groups with `cancel-in-progress: true` to avoid redundant runs on rapid pushes:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

The Codex review workflow uses PR-number-based concurrency: `codex-review-${{ github.event.pull_request.number }}`.

### Artifact Passing Between Jobs

When jobs with different permission scopes need to share data, use upload/download artifact pairs:

1. Job A (read-only) uploads an artifact
2. Job B (write) downloads and processes it

This pattern is used by both `python-tests.yaml` (coverage total) and `codex-code-review.yaml` (review output). Never pass data through workflow outputs for sensitive content.

### Timeout Discipline

Set explicit `timeout-minutes` on jobs that call external services or could hang:

```yaml
jobs:
  review:
    timeout-minutes: 30
  publish:
    timeout-minutes: 5
```

Jobs that only run shell commands or Python scripts can rely on the GitHub default (6 hours) but consider setting a reasonable limit.

## Adding a New Workflow

1. Create `.github/workflows/<name>.yaml`
2. Define the trigger (push, pull_request, release, workflow_dispatch)
3. Set the minimum required permissions at job level
4. Pin all actions to commit SHAs with version comments
5. Add path filtering if the workflow only applies to specific file types
6. Add concurrency control if the workflow could run redundantly
7. Test the workflow on a branch before merging to `main`

## Modifying an Existing Workflow

1. Identify which workflow file to change
2. Check if the change affects permissions — if adding a write operation, it may need to move to a separate job with elevated permissions
3. If adding a new action, pin it to a commit SHA immediately
4. If changing triggers, verify the workflow still runs when expected and does not run unnecessarily
5. Test on a branch — push a PR to verify the workflow triggers correctly

## Reviewing Workflow Changes

Check these in order:

1. **Are all actions SHA-pinned?** Enforced automatically by `verify-action-pins.yaml`; rely on the gate instead of reviewing this by eye.
2. **Are permissions minimal?** Does the workflow request more access than it needs? Does a write permission belong at job level instead of workflow level?
3. **Is the permission boundary maintained?** Read-only analysis and write-capable publishing should be in separate jobs
4. **Are new environment variables validated?** Scripts called by the workflow should check `${VAR:?}` at the top
5. **Is path filtering appropriate?** Does the workflow run on changes it does not need to process?
6. **Are concurrency groups set?** Could rapid pushes cause redundant runs?

## Common Mistakes

- Using a tag reference (`@v4`) instead of a SHA — breaks reproducibility and is a security risk
- Granting `contents: write` at workflow level when only one job needs it
- Missing path filter — workflow runs on every PR even when irrelevant files changed
- Forgetting to update the version comment after changing a SHA
- Passing sensitive data through workflow outputs instead of artifacts
- Missing `timeout-minutes` on jobs that call external APIs
- Adding a new action without verifying its SHA from the official repository
