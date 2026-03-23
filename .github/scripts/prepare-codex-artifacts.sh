#!/bin/bash
set -euo pipefail

# Validate required environment variables
: "${GITHUB_OUTPUT:?Environment variable GITHUB_OUTPUT is required}"

# Validate Codex review output file and copy JavaScript artifacts.
#
# Expects:
#   .codex/review-output.json — written by Codex via output-file
#
# Outputs:
#   has-review=true             → written to $GITHUB_OUTPUT (on success)
#   .codex/scripts/*.js         — copied for publish job

if [ ! -s .codex/review-output.json ]; then
  echo "::error::Codex review output file is missing or empty."
  echo "has-review=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

if ! jq . .codex/review-output.json > /dev/null 2>&1; then
  echo "::error::Codex review output is not valid JSON."
  echo "has-review=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

mkdir -p .codex/scripts
cp .github/scripts/*.js .codex/scripts/
echo "has-review=true" >> "$GITHUB_OUTPUT"
exit 0
