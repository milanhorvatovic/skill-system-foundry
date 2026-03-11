#!/bin/bash
set -euo pipefail

# Check prerequisites for Codex code review.
#
# Environment variables:
#   HAS_OPENAI_API_KEY  — "true" if the secret is present
#   REVIEW_USERS_RAW    — comma/newline-separated allowlist
#   PR_AUTHOR           — github.event.pull_request.user.login
#
# Output:
#   allowed=true|false  → written to $GITHUB_OUTPUT

if [ "$HAS_OPENAI_API_KEY" != "true" ]; then
  echo "OPENAI_API_KEY is not set. Skipping Codex review."
  echo "allowed=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

if [ -z "$REVIEW_USERS_RAW" ]; then
  echo "CODEX_REVIEW_USERS is not set. Skipping Codex review."
  echo "allowed=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

allowed=false
pr_author_lower="$(printf '%s' "$PR_AUTHOR" | tr '[:upper:]' '[:lower:]')"
normalized_users="$(
  printf '%s' "$REVIEW_USERS_RAW" \
    | tr '[:upper:]' '[:lower:]' \
    | tr ',\r\n\t' '\n' \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
    | sed '/^$/d'
)"

while IFS= read -r username; do
  if [ "$username" = "$pr_author_lower" ]; then
    allowed=true
    break
  fi
done <<< "$normalized_users"

echo "allowed=$allowed" >> "$GITHUB_OUTPUT"
if [ "$allowed" != "true" ]; then
  echo "PR author '$PR_AUTHOR' is not in CODEX_REVIEW_USERS. Skipping review."
fi
