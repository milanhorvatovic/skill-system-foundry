---
name: shell-scripts
description: >
  Enforces quality, safety, and consistency for shell scripts in the
  Skill System Foundry .github/scripts/ directory. Triggers when creating,
  editing, reviewing, or debugging any .sh file under .github/scripts/,
  modifying GitHub Actions workflows that call shell scripts, or working
  with CI automation scripts. Also triggers when asked to add a new CI
  helper script, fix shellcheck violations, handle GitHub Actions
  environment variables, or work with CI automation.
  Use this skill for any shell scripting work in the repository.
---

# Shell Scripts Skill

Enforces quality, safety, and consistency for all shell scripts under `.github/scripts/` in the Skill System Foundry repository.

These scripts are CI helpers called by GitHub Actions workflows. They handle coverage badge updates and per-file coverage checks. They run in ephemeral CI environments and must be reliable, secure, and shellcheck-clean.

## Directory Layout

```
.github/
├── scripts/
│   ├── check-per-file-coverage.py  ← enforces per-file branch coverage minimum
│   └── update-coverage-badge.sh    ← pushes coverage.json to orphan badges branch
├── workflows/
│   ├── python-tests.yaml           ← runs tests, coverage, badge update
│   ├── shellcheck.yaml             ← lints all .sh files with shellcheck
│   ├── codex-code-review.yaml      ← Codex PR review via codex-ai-code-review-action
│   └── release.yml                 ← bundles and uploads release assets
├── instructions/
│   ├── markdown.instructions.md    ← Markdown review rules
│   └── scripts.instructions.md     ← Python review rules
├── copilot-instructions.md         ← top-level review guidance
└── CODEOWNERS                      ← requires code-owner approval
```

## Hard Requirements

### Strict Mode

Every script starts with:

```bash
#!/bin/bash
set -euo pipefail
```

- `set -e` — exit immediately on non-zero return
- `set -u` — treat unset variables as errors
- `set -o pipefail` — propagate pipe failures

### Environment Variable Validation

Validate all required environment variables at the top of the script, before any work:

```bash
# Validate required environment variables
: "${BASE_SHA:?Environment variable BASE_SHA is required}"
: "${HEAD_SHA:?Environment variable HEAD_SHA is required}"
: "${GITHUB_OUTPUT:?Environment variable GITHUB_OUTPUT is required}"
```

This pattern uses parameter expansion with `:?` — if the variable is unset or empty, the script exits immediately with the error message. Group all validations together at the top.

### ShellCheck Compliance

All `.sh` files must pass `shellcheck` with no warnings. The `shellcheck.yaml` workflow runs automatically on PRs that modify `.github/scripts/*.sh` and on pushes to `main`.

Common shellcheck rules to watch:
- **SC2086** — double-quote variable expansions: `"$VAR"` not `$VAR`
- **SC2155** — separate declaration and assignment: `local var; var=$(...)` not `local var=$(cmd)`
- **SC2046** — quote command substitutions: `"$(cmd)"` not `$(cmd)`
- **SC2034** — unused variables (remove or export)

### CODEOWNERS Protection

`.github/scripts/` is protected by CODEOWNERS — changes require code-owner approval. This is a security boundary: these scripts run in CI with access to secrets and write permissions.

## Script Header Convention

Every script follows this structure:

```bash
#!/bin/bash
set -euo pipefail

# Validate required environment variables
: "${VAR1:?Environment variable VAR1 is required}"
: "${VAR2:?Environment variable VAR2 is required}"

# <Brief description of what this script does.>
#
# Environment variables:
#   VAR1  — description of what this variable provides
#   VAR2  — description of what this variable provides
#
# Outputs:
#   output-name=value  → written to $GITHUB_OUTPUT
#   path/to/file       → created on disk
```

The header documents: purpose, required environment variables with descriptions, and outputs (both `$GITHUB_OUTPUT` values and files created).

## GitHub Actions Integration

### Writing to GITHUB_OUTPUT

Use `>>` append, not `>` overwrite:

```bash
echo "has-changes=true" >> "$GITHUB_OUTPUT"
```

### Accessing Secrets Safely

Never echo secrets. Use environment variables set by the workflow:

```bash
env:
  HAS_OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY != '' }}
```

Check the boolean string, not the secret itself:

```bash
if [ "$HAS_OPENAI_API_KEY" != "true" ]; then
  echo "OPENAI_API_KEY is not set. Skipping."
  echo "allowed=false" >> "$GITHUB_OUTPUT"
  exit 0
fi
```

### GitHub Actions Annotations

Use `::warning::` and `::error::` prefixes for structured log output:

```bash
echo "::warning::Base SHA ${BASE_SHA} not found locally — fetching from origin"
echo "::error::CODEX_REVIEW_USERS repository variable is not set."
```

## Workflow Security Model

The repository uses permission isolation across workflow jobs:

- **Read-only jobs** — `contents: read` only. Cannot modify the repo.
- **Write jobs** — scoped to the minimum permission needed (e.g. `pull-requests: write`).

When adding new scripts:
- Determine which permission boundary the script belongs in
- Never combine read and write permissions in one job
- Pin all actions to full commit SHAs (not tags): `uses: actions/checkout@de0fac...`
- Fork PRs cannot access secrets — this is a GitHub security guarantee the pipeline relies on

## Temporary Files and Cleanup

Use `mktemp` for temporary directories and `trap` for cleanup:

```bash
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT
```

This ensures cleanup runs even on errors (because `set -e` triggers EXIT).

## Adding a New Script

1. Create `.github/scripts/<name>.sh` with the standard header
2. Make it executable: `chmod +x .github/scripts/<name>.sh`
3. Add environment variable validation at the top
4. Document environment variables and outputs in the header comment
5. Run `shellcheck .github/scripts/<name>.sh` locally before pushing
6. Call from the workflow with `bash .github/scripts/<name>.sh` (not `sh` — these are bash scripts)
7. Use explicit `env:` blocks in the workflow step to pass variables

## Common Patterns

### Conditional Execution with Outputs

```bash
if [ "$CONDITION" = "true" ]; then
  echo "proceed=true" >> "$GITHUB_OUTPUT"
else
  echo "proceed=false" >> "$GITHUB_OUTPUT"
  exit 0  # Clean exit — not a failure
fi
```

### JSON Validation with jq

```bash
if printf '%s' "$RAW_JSON" | jq . > output.json 2>/dev/null; then
  handle_success
else
  echo "::error::Invalid JSON in output"
  exit 1
fi
```

### Git Operations in CI

```bash
# Fetch with authentication fallback
if ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  git fetch --no-tags origin "${BASE_SHA}"
fi
```

### Orphan Branch Push (Coverage Badge Pattern)

```bash
git init "$WORK_DIR/repo"
cp "$WORK_DIR/coverage.json" "$WORK_DIR/repo/coverage.json"
git -C "$WORK_DIR/repo" checkout --orphan badges
git -C "$WORK_DIR/repo" add coverage.json
git -C "$WORK_DIR/repo" \
  -c user.name="github-actions[bot]" \
  -c user.email="github-actions[bot]@users.noreply.github.com" \
  commit -m "Update coverage badge [skip ci]"
```

Key details: use `[skip ci]` to prevent infinite loops, use `github-actions[bot]` as committer, propagate auth headers from `actions/checkout`.

## Common Mistakes

- Missing `set -euo pipefail` at the top
- Unquoted variable expansion (`$VAR` instead of `"$VAR"`)
- Using `>` instead of `>>` for `$GITHUB_OUTPUT` (overwrites previous outputs)
- Echoing secrets to logs
- Mixing `sh` and `bash` syntax (these are bash scripts, call with `bash`)
- Missing `trap` cleanup for temporary files
- Forgetting to validate environment variables before using them
- Using tag-based action pins (`@v6`) instead of commit SHA pins
- Combining read and write permissions in a single workflow job
