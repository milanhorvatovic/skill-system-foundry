"""Regenerate the YAML conformance corpus ``digests.txt`` manifest.

Walks ``tests/fixtures/yaml-conformance/`` for ``*.lf.yaml``,
``*.crlf.yaml``, and ``*.mixed.yaml`` files, computes their SHA-256
hex digest, and writes the result to ``digests.txt`` in
``sha256sum``-compatible format (``<digest>  <relative-path>``), sorted
by path ascending so re-runs produce byte-identical output.

Lifecycle: committed permanently as a re-runnable contributor utility
— every PR touching corpus fixtures regenerates the manifest before
committing.

Atomic write: the new manifest is written to a temp file in the same
directory and renamed via ``os.replace`` so a mid-write crash cannot
corrupt the in-tree manifest.

Whitespace rejection: corpus paths may not contain whitespace — the
``sha256sum`` line format splits on the first run of whitespace, so
embedded spaces or tabs in a path would silently mis-parse.  This
script aborts with a clear error if it encounters such a path.
"""

import argparse
import hashlib
import os
import sys

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_DEFAULT_CORPUS_ROOT = os.path.join(
    _REPO_ROOT, "tests", "fixtures", "yaml-conformance"
)
_VARIANT_SUFFIXES = (".lf.yaml", ".crlf.yaml", ".mixed.yaml")
_MANIFEST_FILENAME = "digests.txt"


def _hash_file(path: str) -> str:
    """Return hex SHA-256 of *path*'s bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_manifest(corpus_root: str) -> str:
    """Return the manifest text for the corpus rooted at *corpus_root*.

    Raises ``ValueError`` when any fixture path contains whitespace.
    """
    rows: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(corpus_root):
        dirnames.sort()
        for fname in sorted(filenames):
            if not any(fname.endswith(s) for s in _VARIANT_SUFFIXES):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, corpus_root).replace(os.sep, "/")
            if any(ch.isspace() for ch in rel):
                raise ValueError(
                    f"corpus path contains whitespace: {rel!r}"
                )
            rows.append((rel, _hash_file(full)))
    rows.sort(key=lambda r: r[0])
    return "".join(f"{digest}  {rel}\n" for rel, digest in rows)


def write_manifest_atomic(corpus_root: str, manifest_text: str) -> str:
    """Write *manifest_text* to ``digests.txt`` via tempfile + rename."""
    final_path = os.path.join(corpus_root, _MANIFEST_FILENAME)
    tmp_path = final_path + ".tmp"
    with open(tmp_path, "wb") as fh:
        fh.write(manifest_text.encode("utf-8"))
    os.replace(tmp_path, final_path)
    return final_path


def read_existing_manifest(corpus_root: str) -> str:
    """Return the on-disk manifest text, or empty string if absent."""
    path = os.path.join(corpus_root, _MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns 0 on success, 1 on drift (``--check``) or
    other recoverable errors."""
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate or verify the YAML conformance corpus "
            "digests.txt manifest."
        )
    )
    parser.add_argument(
        "--corpus-root",
        default=_DEFAULT_CORPUS_ROOT,
        help="Path to the corpus root (default: tests/fixtures/yaml-conformance).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Compare the regenerated manifest to the on-disk file "
            "without rewriting; exit 0 on match, 1 on drift."
        ),
    )
    args = parser.parse_args(argv)

    if not os.path.isdir(args.corpus_root):
        print(
            f"Error: corpus root not found: {args.corpus_root}",
            file=sys.stderr,
        )
        return 1

    try:
        manifest = collect_manifest(args.corpus_root)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.check:
        existing = read_existing_manifest(args.corpus_root)
        if existing == manifest:
            print("digests.txt is up to date.")
            return 0
        print(
            "digests.txt drift detected — re-run without --check to regenerate.",
            file=sys.stderr,
        )
        return 1

    write_manifest_atomic(args.corpus_root, manifest)
    print(f"Wrote {args.corpus_root}/{_MANIFEST_FILENAME}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
