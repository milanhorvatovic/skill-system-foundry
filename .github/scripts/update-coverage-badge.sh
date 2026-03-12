#!/bin/bash
set -euo pipefail

# Validate required environment variables
: "${TOTAL:?Environment variable TOTAL is required}"

# Create coverage.json and push it to the orphan badges branch.
#
# Environment variables:
#   TOTAL  — integer coverage percentage (e.g. 72)
#
# Behaviour:
#   1. Maps the percentage to a shields.io colour band.
#   2. Creates a coverage.json file following the shields.io endpoint schema.
#   3. Pushes the file to the orphan badges branch (creates it if missing).
#   4. Uses [skip ci] to prevent infinite workflow loops.

# Determine badge colour from coverage percentage
if [ "$TOTAL" -ge 90 ]; then COLOR="brightgreen"
elif [ "$TOTAL" -ge 80 ]; then COLOR="green"
elif [ "$TOTAL" -ge 70 ]; then COLOR="yellowgreen"
elif [ "$TOTAL" -ge 60 ]; then COLOR="yellow"
else COLOR="red"; fi

# Build coverage.json in a temporary directory
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

cat > "$WORK_DIR/coverage.json" <<EOF
{
  "schemaVersion": 1,
  "label": "coverage",
  "message": "${TOTAL}%",
  "color": "${COLOR}"
}
EOF

# Initialise a throwaway repo so the push carries only coverage.json
git init "$WORK_DIR/repo"
cp "$WORK_DIR/coverage.json" "$WORK_DIR/repo/coverage.json"

git -C "$WORK_DIR/repo" checkout --orphan badges
git -C "$WORK_DIR/repo" add coverage.json

git -C "$WORK_DIR/repo" \
  -c user.name="github-actions[bot]" \
  -c user.email="github-actions[bot]@users.noreply.github.com" \
  commit -m "Update coverage badge to ${TOTAL}% [skip ci]"

# Propagate authentication from the checkout created by actions/checkout
AUTH_HEADER=$(git config --get http.https://github.com/.extraheader || true)
if [ -n "$AUTH_HEADER" ]; then
  git -C "$WORK_DIR/repo" config http.https://github.com/.extraheader "$AUTH_HEADER"
fi

REMOTE_URL=$(git remote get-url origin)
git -C "$WORK_DIR/repo" push --force "$REMOTE_URL" badges
