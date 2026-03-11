#!/bin/bash
set -euo pipefail

# Validate required environment variables
: "${CODEX_REVIEW:?Environment variable CODEX_REVIEW is required}"
: "${GITHUB_OUTPUT:?Environment variable GITHUB_OUTPUT is required}"

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
if printf '%s' "$CODEX_REVIEW" | jq . > .codex/review-output.json 2>/dev/null; then
  mkdir -p .codex/scripts
  cp .github/scripts/*.js .codex/scripts/
  echo "has-review=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Strip markdown code fences and retry (case-insensitive json tag, optional leading whitespace).
# shellcheck disable=SC2016
stripped="$(printf '%s' "$CODEX_REVIEW" | sed -n '/^[[:space:]]*```\([Jj][Ss][Oo][Nn]\)\?[[:space:]]*$/,/^[[:space:]]*```[[:space:]]*$/{ /^[[:space:]]*```/d; p; }')"
if [ -n "$stripped" ] && printf '%s' "$stripped" | jq . > .codex/review-output.json 2>/dev/null; then
  mkdir -p .codex/scripts
  cp .github/scripts/*.js .codex/scripts/
  echo "has-review=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Third attempt: extract JSON using Perl (handles multibyte correctly)
extracted=$(printf '%s' "$CODEX_REVIEW" | perl -0777 -ne 'if (/\{[\s\S]*\}/s) { print $& }' || true)
if [ -n "$extracted" ] && printf '%s' "$extracted" | jq . > .codex/review-output.json 2>/dev/null; then
  mkdir -p .codex/scripts
  cp .github/scripts/*.js .codex/scripts/
  echo "has-review=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

# All attempts failed — raise an error.
echo "::error::Could not parse Codex output as valid JSON."
rm -f .codex/review-output.json
exit 1
