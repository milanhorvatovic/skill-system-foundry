#!/bin/bash
set -euo pipefail

# Validate required environment variables
: "${DIFF_FILE:?Environment variable DIFF_FILE is required}"
: "${GITHUB_OUTPUT:?Environment variable GITHUB_OUTPUT is required}"

# Split a unified diff into per-chunk diffs by file boundaries.
#
# Environment variables:
#   DIFF_FILE          — path to the full PR diff
#   FILES_PER_CHUNK    — max files per chunk (default: 5)
#   OUTPUT_DIR         — output directory for chunks (default: .codex/chunks)
#
# Outputs (via $GITHUB_OUTPUT):
#   chunk-matrix — JSON matrix for GitHub Actions (e.g. {"include":[{"chunk":0},{"chunk":1}]})
#   chunk-count  — total number of chunks

FILES_PER_CHUNK="${FILES_PER_CHUNK:-5}"
if ! [[ "$FILES_PER_CHUNK" =~ ^[1-9][0-9]*$ ]]; then
  echo "::error::FILES_PER_CHUNK must be a positive integer."
  exit 1
fi
OUTPUT_DIR="${OUTPUT_DIR:-.codex/chunks}"
if [ -z "$OUTPUT_DIR" ] || [ "$OUTPUT_DIR" = "/" ] || [ "$OUTPUT_DIR" = "." ] || [ "$OUTPUT_DIR" = ".." ]; then
  echo "::error::Refusing unsafe OUTPUT_DIR value: '$OUTPUT_DIR'"
  exit 1
fi
if [[ "$OUTPUT_DIR" = /* ]]; then
  echo "::error::Refusing absolute OUTPUT_DIR path: '$OUTPUT_DIR'"
  exit 1
fi
if [[ "$OUTPUT_DIR" == *".."* ]]; then
  echo "::error::Refusing OUTPUT_DIR with path traversal: '$OUTPUT_DIR'"
  exit 1
fi
if [[ "$OUTPUT_DIR" != .codex/* ]]; then
  echo "::error::Refusing OUTPUT_DIR outside .codex/: '$OUTPUT_DIR'"
  exit 1
fi

rm -rf -- "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

if [ ! -s "$DIFF_FILE" ]; then
  echo "Diff is empty — creating single empty chunk."
  touch "$OUTPUT_DIR/chunk-0.diff"
  echo 'chunk-matrix={"include":[{"chunk":0}]}' >> "$GITHUB_OUTPUT"
  echo "chunk-count=1" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Split the diff by "diff --git" boundaries into per-file temp files,
# then group files into chunks.
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT
FILE_INDEX=0
CURRENT_FILE=""

while IFS= read -r line; do
  if [[ "$line" == "diff --git "* ]]; then
    CURRENT_FILE="${TEMP_DIR}/file-${FILE_INDEX}.diff"
    FILE_INDEX=$((FILE_INDEX + 1))
  fi
  if [ -n "$CURRENT_FILE" ]; then
    printf '%s\n' "$line" >> "$CURRENT_FILE"
  fi
done < "$DIFF_FILE"

TOTAL_FILES=$FILE_INDEX
echo "Split diff into ${TOTAL_FILES} file(s)."

if [ "$TOTAL_FILES" -eq 0 ]; then
  touch "$OUTPUT_DIR/chunk-0.diff"
  echo 'chunk-matrix={"include":[{"chunk":0}]}' >> "$GITHUB_OUTPUT"
  echo "chunk-count=1" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Group files into chunks
CHUNK_INDEX=0
FILE_IN_CHUNK=0

for i in $(seq 0 $((TOTAL_FILES - 1))); do
  FILE_PATH="${TEMP_DIR}/file-${i}.diff"
  if [ ! -f "$FILE_PATH" ]; then
    continue
  fi

  cat "$FILE_PATH" >> "${OUTPUT_DIR}/chunk-${CHUNK_INDEX}.diff"
  FILE_IN_CHUNK=$((FILE_IN_CHUNK + 1))

  if [ "$FILE_IN_CHUNK" -ge "$FILES_PER_CHUNK" ] && [ "$i" -lt $((TOTAL_FILES - 1)) ]; then
    CHUNK_INDEX=$((CHUNK_INDEX + 1))
    FILE_IN_CHUNK=0
  fi
done

CHUNK_COUNT=$((CHUNK_INDEX + 1))
echo "Created ${CHUNK_COUNT} chunk(s) from ${TOTAL_FILES} file(s) (${FILES_PER_CHUNK} files/chunk)."

# Build JSON matrix for GitHub Actions
MATRIX='{"include":['
for i in $(seq 0 $((CHUNK_COUNT - 1))); do
  if [ "$i" -gt 0 ]; then
    MATRIX="${MATRIX},"
  fi
  MATRIX="${MATRIX}{\"chunk\":${i}}"
done
MATRIX="${MATRIX}]}"

echo "chunk-matrix=${MATRIX}" >> "$GITHUB_OUTPUT"
echo "chunk-count=${CHUNK_COUNT}" >> "$GITHUB_OUTPUT"

# Report chunk sizes
for i in $(seq 0 $((CHUNK_COUNT - 1))); do
  CHUNK_FILE="${OUTPUT_DIR}/chunk-${i}.diff"
  if [ -f "$CHUNK_FILE" ]; then
    BYTE_COUNT=$(wc -c < "$CHUNK_FILE" | tr -d ' ')
    FILE_COUNT=$(grep -c "^diff --git " "$CHUNK_FILE" || true)
    echo "  chunk-${i}: ${FILE_COUNT} file(s), ${BYTE_COUNT} bytes"
  fi
done
