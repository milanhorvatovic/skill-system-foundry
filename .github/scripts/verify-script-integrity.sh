#!/bin/bash
set -euo pipefail

# Verify script integrity against CODEX_SCRIPT_HASHES repository variable.
#
# Environment variables:
#   SCRIPT_HASHES  — JSON object from vars.CODEX_SCRIPT_HASHES
#
# Outputs:
#   allowed=true|false  → written to $GITHUB_OUTPUT

# Check if SCRIPT_HASHES is set
if [ -z "${SCRIPT_HASHES:-}" ]; then
  echo "::error::CODEX_SCRIPT_HASHES repository variable is not set. Please configure it in Settings → Actions → Variables."
  echo "allowed=false" >> "$GITHUB_OUTPUT"
  exit 1
fi

# Validate JSON format
if ! echo "$SCRIPT_HASHES" | jq -e . > /dev/null 2>&1; then
  echo "::error::CODEX_SCRIPT_HASHES is not valid JSON. Please check the variable format."
  echo "allowed=false" >> "$GITHUB_OUTPUT"
  exit 1
fi

# Parse the hashes JSON
hashes_json="$SCRIPT_HASHES"

# Get files on disk
disk_files=$(find .github/scripts -type f -exec basename {} \; | sort)

# Get files from JSON
json_files=$(echo "$hashes_json" | jq -r 'keys | .[]' | sort)

# Set match check
if [ "$disk_files" != "$json_files" ]; then
  echo "::error::Script set mismatch. Disk: $disk_files, JSON: $json_files"
  echo "allowed=false" >> "$GITHUB_OUTPUT"
  exit 1
fi

# Hash match check
for file in $disk_files; do
  computed_hash=$(sha256sum ".github/scripts/$file" | awk '{print $1}')
  approved_hashes=$(echo "$hashes_json" | jq -r ".[\"$file\"][]")
  if ! echo "$approved_hashes" | grep -q "^${computed_hash}$"; then
    echo "::error::Hash mismatch for $file. Computed: $computed_hash"
    echo "allowed=false" >> "$GITHUB_OUTPUT"
    exit 1
  fi
done

echo "::notice::Script integrity verified"
