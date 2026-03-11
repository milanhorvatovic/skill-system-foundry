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

# Strip markdown code fences and retry (case-insensitive json tag, optional leading whitespace).
# shellcheck disable=SC2016
stripped="$(echo "$CODEX_REVIEW" | sed -n '/^[[:space:]]*```\([Jj][Ss][Oo][Nn]\)\?[[:space:]]*$/,/^[[:space:]]*```[[:space:]]*$/{ /^[[:space:]]*```/d; p; }')"
if [ -n "$stripped" ] && echo "$stripped" | jq . > .codex/review-output.json 2>/dev/null; then
  mkdir -p .codex/scripts
  cp .github/scripts/*.js .codex/scripts/
  echo "has-review=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Third attempt: extract JSON from first '{' to last '}'
first_pos=$(printf '%s' "$CODEX_REVIEW" | grep -b -m1 -o '{' | cut -d: -f1 || true)
last_pos=$(printf '%s' "$CODEX_REVIEW" | grep -b -o '}' | tail -1 | cut -d: -f1 || true)
if [ -n "$first_pos" ] && [ -n "$last_pos" ] && [ "$first_pos" -lt "$last_pos" ]; then
  extracted="${CODEX_REVIEW:$first_pos:$((last_pos - first_pos + 1))}"
  if echo "$extracted" | jq . > .codex/review-output.json 2>/dev/null; then
    mkdir -p .codex/scripts
    cp .github/scripts/*.js .codex/scripts/
    echo "has-review=true" >> "$GITHUB_OUTPUT"
    exit 0
  fi
fi

# All attempts failed — skip review.
echo "::warning::Could not parse Codex output as valid JSON. Skipping review."
echo "has-review=false" >> "$GITHUB_OUTPUT"
exit 0
