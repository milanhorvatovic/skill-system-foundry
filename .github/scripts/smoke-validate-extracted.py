#!/usr/bin/env python3
"""Validate the extracted bundle-extract-smoke archive.

The bundle-extract-smoke CI job extracts the smoke bundle into
``smoke-extracted/`` and then needs to invoke ``validate_skill.py``
against the top-level skill directory the archive shipped.  The
previous implementation did this in an inline ``python -c`` one-liner
that resolved the skill directory via ``next((d for ...), None)`` and
passed the result straight into ``subprocess.call``.  When the
extraction produced no top-level directory containing a ``SKILL.md``
(a real failure mode the smoke job is supposed to catch), the
``None`` propagated into ``subprocess.call`` and crashed with a
``TypeError`` that obscured the actual problem.

This helper replaces the one-liner.  It surfaces a clear failure
message when the expected ``<skill-name>/SKILL.md`` layout is
missing, propagates the validator's exit code on success, and keeps
the cross-shell escape surface flat — bash on ubuntu and PowerShell
on windows-latest both invoke it the same way.

Usage::

    python .github/scripts/smoke-validate-extracted.py \\
        <extracted-root> <validator-path>
"""

import argparse
import os
import subprocess
import sys


def find_skill_dir(extracted_root: str) -> str | None:
    """Return the first top-level entry in *extracted_root* that holds a SKILL.md.

    ``bundle.py`` writes the skill under its own basename inside the
    archive, so a clean extraction yields exactly one entry under
    *extracted_root* that is a directory containing ``SKILL.md``.
    Returns ``None`` if no such entry exists — the caller turns that
    into a clear error rather than letting the missing path
    propagate into ``subprocess.call``.
    """
    if not os.path.isdir(extracted_root):
        return None
    for name in sorted(os.listdir(extracted_root)):
        candidate = os.path.join(extracted_root, name)
        if os.path.isfile(os.path.join(candidate, "SKILL.md")):
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Locate the extracted skill directory and validate it. "
            "Exits non-zero with a clear message when no top-level "
            "directory inside the extracted root contains a "
            "SKILL.md, instead of crashing with a TypeError."
        )
    )
    parser.add_argument(
        "extracted_root",
        help="Directory the smoke bundle was extracted into.",
    )
    parser.add_argument(
        "validator_path",
        help="Path to skill-system-foundry/scripts/validate_skill.py.",
    )
    args = parser.parse_args(argv)

    skill_dir = find_skill_dir(args.extracted_root)
    if skill_dir is None:
        # ``os.listdir`` may itself raise if ``extracted_root`` is
        # missing entirely; surface that as the same diagnostic so
        # the caller does not have to distinguish "no entries" from
        # "no extracted root at all".
        try:
            entries = sorted(os.listdir(args.extracted_root))
        except OSError as exc:
            print(
                f"FAIL: cannot list extracted root "
                f"'{args.extracted_root}': {exc}",
                file=sys.stderr,
            )
            return 1
        print(
            f"FAIL: no top-level directory under "
            f"'{args.extracted_root}' contains a SKILL.md "
            f"(entries: {entries!r}) — bundle extraction did not "
            "produce the expected <skill-name>/SKILL.md layout",
            file=sys.stderr,
        )
        return 1

    return subprocess.call(
        [sys.executable, args.validator_path, skill_dir]
    )


if __name__ == "__main__":
    sys.exit(main())
