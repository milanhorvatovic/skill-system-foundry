#!/bin/bash
set -euo pipefail

# Validate and save Codex review output as guaranteed-valid JSON.
# Also copies JavaScript files to .codex/scripts/ for transport.
#
# Environment variables:
#   CODEX_REVIEW  — raw output from the Codex action
#
# Outputs:
#   has-review=true             → written to $GITHUB_OUTPUT (on success)
#   .codex/review-output.json   — valid JSON
#   .codex/scripts/*.js         — copied for publish job

mkdir -p .codex

# Try parsing the raw output as JSON directly.
if echo "$CODEX_REVIEW" | jq . > .codex/review-output.json 2>/dev/null; then
  mkdir -p .codex/scripts
  cp .github/scripts/*.js .codex/scripts/
  echo "has-review=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Strip markdown code fences and retry.
# shellcheck disable=SC2016
stripped="$(echo "$CODEX_REVIEW" | sed -n '/^```\(json\)\?[[:space:]]*$/,/^```[[:space:]]*$/{ /^```/d; p; }')"
if [ -n "$stripped" ] && echo "$stripped" | jq . > .codex/review-output.json 2>/dev/null; then
  mkdir -p .codex/scripts
  cp .github/scripts/*.js .codex/scripts/
  echo "has-review=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Both attempts failed — skip review.
echo "::warning::Could not parse Codex output as valid JSON. Skipping review."
rm -f .codex/review-output.json
