#!/bin/bash
set -euo pipefail

# Validate required environment variables
: "${BASE_SHA:?Environment variable BASE_SHA is required}"
: "${HEAD_SHA:?Environment variable HEAD_SHA is required}"
: "${GITHUB_OUTPUT:?Environment variable GITHUB_OUTPUT is required}"
: "${GITHUB_TOKEN:?Environment variable GITHUB_TOKEN is required}"

# Build the PR diff for Codex review.
#
# Environment variables:
#   BASE_SHA      — PR base commit SHA
#   HEAD_SHA      — PR head commit SHA
#   GITHUB_TOKEN  — used as a fallback fetch credential
#
# Outputs:
#   has-changes=true|false  → written to $GITHUB_OUTPUT
#   .codex/pr.diff          → the unified diff

# fetch-depth: 0 normally makes the base SHA available locally.
# Fetch explicitly as a fallback (e.g. when the base branch was force-pushed).
if ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  echo "::warning::Base SHA ${BASE_SHA} not found locally — fetching from origin"
  git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "${GITHUB_TOKEN}" | base64 -w0)" \
    fetch --no-tags origin "${BASE_SHA}"
fi

mkdir -p .codex
git diff --no-color --unified=3 "${BASE_SHA}...${HEAD_SHA}" > .codex/pr.diff

if [ -s .codex/pr.diff ]; then
  echo "has-changes=true" >> "$GITHUB_OUTPUT"
else
  echo "Diff is empty — nothing to review."
  echo "has-changes=false" >> "$GITHUB_OUTPUT"
fi
