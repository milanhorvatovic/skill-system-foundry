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

This helper replaces the one-liner.  ``bundle.py``'s contract is
exactly one top-level ``<skill-name>/`` entry per archive, and the
helper enforces that contract on three branches:

* zero top-level directories contain a ``SKILL.md`` → FAIL with the
  extracted-root listing (the previous traceback case);
* exactly one match → invoke the validator and propagate its exit
  code (happy path);
* two or more matches → FAIL with every candidate listed, without
  invoking the validator (a previous "first match wins"
  implementation would have silently picked the alphabetically-
  first entry and let a duplicated-namespace regression slip past
  the smoke step).

The helper keeps the cross-shell escape surface flat — bash on
ubuntu and PowerShell on windows-latest both invoke it the same way.

Usage::

    python .github/scripts/smoke-validate-extracted.py \\
        <extracted-root> <validator-path>
"""

import argparse
import os
import subprocess
import sys


# Bring the meta-skill's error-level constants into scope so this CI
# helper can prefix its diagnostics with ``LEVEL_FAIL`` instead of a
# hardcoded ``"FAIL"`` literal.  The repository convention is
# non-negotiable across the entire codebase: error levels come from
# ``skill-system-foundry/scripts/lib/constants.py``, never from raw
# strings.  ``smoke-cross-platform-fixtures.py`` uses the same
# sys.path-insertion pattern for the same reason.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "skill-system-foundry", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from lib.constants import LEVEL_FAIL  # noqa: E402  (path injected above)
from lib.reporting import to_posix  # noqa: E402  (path injected above)


def find_skill_dirs(extracted_root: str) -> list[str]:
    """Return every top-level entry in *extracted_root* that holds a SKILL.md.

    ``bundle.py`` writes the skill under its own basename inside the
    archive, so a clean extraction yields *exactly one* entry under
    *extracted_root* that is a directory containing ``SKILL.md``.
    The smoke job exists to catch regressions in that contract, so
    the helper returns *every* matching entry (sorted, for runner
    determinism) and lets ``main`` distinguish three failure modes:

    * zero matches → bundle did not produce the expected layout;
    * one match → happy path, validate it;
    * two or more matches → bundle wrote the skill more than once
      under different top-level names, which the previous "first
      match wins" implementation would have hidden by silently
      picking the alphabetically-first entry.

    Returns an empty list when *extracted_root* is missing or has no
    matching entries — the caller surfaces both as the same FAIL.
    """
    if not os.path.isdir(extracted_root):
        return []
    matches: list[str] = []
    for name in sorted(os.listdir(extracted_root)):
        candidate = os.path.join(extracted_root, name)
        if os.path.isfile(os.path.join(candidate, "SKILL.md")):
            matches.append(candidate)
    return matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Locate the extracted skill directory and validate it. "
            "Exits non-zero with a clear message when no top-level "
            "directory inside the extracted root contains a "
            "SKILL.md, or when more than one does (the bundler's "
            "contract is exactly one such entry per archive), "
            "instead of crashing with a TypeError or silently "
            "validating an alphabetically-picked candidate."
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

    matches = find_skill_dirs(args.extracted_root)
    if len(matches) == 1:
        return subprocess.call(
            [sys.executable, args.validator_path, matches[0]]
        )
    # Normalise every path that crosses the diagnostic boundary so
    # finding text is byte-identical across runners.  Without this,
    # the multi-match branch (which renders the candidate list via
    # ``repr``) emits double-escaped ``\\`` sequences on Windows
    # that downstream substring assertions and log-grep filters
    # would not match.  ``to_posix`` is the established chokepoint
    # for any path crossing a UI boundary in this repo.
    extracted_root_posix = to_posix(args.extracted_root)
    if len(matches) > 1:
        # A multi-match is itself a regression worth surfacing — the
        # bundler's contract is one top-level <skill-name>/ entry
        # per archive.  The previous implementation picked the
        # alphabetically-first hit and validated it, which would
        # silently mask a duplicated-namespace regression.  Listing
        # every candidate makes the failure self-explanatory.
        matches_posix = [to_posix(m) for m in matches]
        print(
            f"{LEVEL_FAIL}: '{extracted_root_posix}' contains "
            f"{len(matches_posix)} top-level directories with a SKILL.md "
            f"({matches_posix!r}) — bundle extraction must produce "
            "exactly one <skill-name>/SKILL.md layout",
            file=sys.stderr,
        )
        return 1
    # Zero matches: try to surface the actual entries for
    # diagnostics.  ``os.listdir`` may itself raise if
    # ``extracted_root`` is missing entirely; report that branch
    # distinctly so the caller can tell "no skill" from "no
    # extracted root at all".
    try:
        entries = sorted(os.listdir(args.extracted_root))
    except OSError as exc:
        print(
            f"{LEVEL_FAIL}: cannot list extracted root "
            f"'{extracted_root_posix}': {exc}",
            file=sys.stderr,
        )
        return 1
    print(
        f"{LEVEL_FAIL}: no top-level directory under "
        f"'{extracted_root_posix}' contains a SKILL.md "
        f"(entries: {entries!r}) — bundle extraction did not "
        "produce the expected <skill-name>/SKILL.md layout",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
