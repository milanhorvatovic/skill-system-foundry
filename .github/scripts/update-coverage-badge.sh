#!/bin/bash
set -euo pipefail

# Validate required environment variables
: "${TOTAL:?Environment variable TOTAL is required}"

# Update the coverage badge in README.md and push to main.
#
# Environment variables:
#   TOTAL  — integer coverage percentage (e.g. 72)
#
# Behaviour:
#   1. Maps the percentage to a shields.io colour band.
#   2. Replaces the badge URL in README.md via sed.
#   3. Commits and pushes only when the badge actually changed.
#   4. Uses [skip ci] to prevent infinite workflow loops.

# Determine badge colour from coverage percentage
if [ "$TOTAL" -ge 90 ]; then COLOR="brightgreen"
elif [ "$TOTAL" -ge 80 ]; then COLOR="green"
elif [ "$TOTAL" -ge 70 ]; then COLOR="yellowgreen"
elif [ "$TOTAL" -ge 60 ]; then COLOR="yellow"
else COLOR="red"; fi

# Fail fast if the expected badge pattern is missing
grep -q "img.shields.io/badge/coverage-" README.md || {
  echo "Coverage badge pattern not found in README.md" >&2
  exit 1
}

# Replace the badge URL with the current percentage and colour
sed -i "s|img.shields.io/badge/coverage-[0-9]*%25-[a-z]*|img.shields.io/badge/coverage-${TOTAL}%25-${COLOR}|" README.md

# Commit and push only when the badge changed
if git diff --quiet README.md; then
  echo "Badge already up to date"
else
  git config user.name "github-actions[bot]"
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git add README.md
  git commit -m "Update coverage badge to ${TOTAL}% [skip ci]"
  git pull --rebase origin main
  git push
fi
