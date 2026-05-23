#!/bin/bash
set -euo pipefail

# Build and verify the distributable skill bundle.
#
# Single source of truth for the release zip so the pre-merge dry-build in
# release-prep.yaml and the real build in release.yaml cannot drift: whatever
# release-prep proves buildable is the exact procedure release.yaml runs to
# publish. Without this, a bundle that builds in the dry-run could still fail at
# release time and burn the (immutable) tag.
#
# Environment variables:
#   BUNDLE_PATH    — output path for the zip (required)
#   CHECKSUM_PATH  — when set, also write and self-verify a SHA256 checksum file
#
# Behaviour: zips skill-system-foundry/, fails if the bundle contains any
# yaml-conformance corpus entry, and (when CHECKSUM_PATH is set) writes the
# checksum file and re-hashes the bundle to confirm it matches.

: "${BUNDLE_PATH:?Environment variable BUNDLE_PATH is required}"

mkdir -p "$(dirname "$BUNDLE_PATH")"
zip -r "$BUNDLE_PATH" skill-system-foundry/

python - "$BUNDLE_PATH" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    hits = [n for n in z.namelist() if 'yaml-conformance' in n]
if hits:
    print('Found forbidden yaml-conformance entries in bundle:', file=sys.stderr)
    for n in hits:
        print(f'  {n}', file=sys.stderr)
    sys.exit(1)
PY

if [ -z "${CHECKSUM_PATH:-}" ]; then
  echo "Bundle OK (no checksum requested): $BUNDLE_PATH"
  exit 0
fi

python - "$BUNDLE_PATH" "$CHECKSUM_PATH" <<'PY'
import hashlib, os, sys

def hash_bundle(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

bundle_path, checksum_path = sys.argv[1], sys.argv[2]
actual_name = os.path.basename(bundle_path)
write_line = f"{hash_bundle(bundle_path)}  {actual_name}\n"
with open(checksum_path, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(write_line)
# Re-read the checksum file and re-hash the bundle so this confirms the checksum
# file matches the bundle as it exists at the end of generation.
with open(checksum_path, "r", encoding="utf-8") as fh:
    checksum_line = fh.readline().rstrip("\r\n")
if "  " not in checksum_line:
    print('Malformed checksum file: expected "<sha256>  <filename>"', file=sys.stderr)
    sys.exit(1)
expected_digest, expected_name = checksum_line.split("  ", 1)
if expected_name != actual_name:
    print(f"Checksum filename mismatch: {expected_name!r} vs {actual_name!r}", file=sys.stderr)
    sys.exit(1)
actual_digest = hash_bundle(bundle_path)
if actual_digest != expected_digest:
    print(f"Checksum mismatch: file has {expected_digest}, bundle hashes to {actual_digest}", file=sys.stderr)
    sys.exit(1)
print(f"{actual_name}: OK")
PY

echo "Bundle + checksum OK: $BUNDLE_PATH"
