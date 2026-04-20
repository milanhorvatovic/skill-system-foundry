#!/usr/bin/env python3
"""Emit a JSON / human report of the YAML 1.2.2 conformance corpus.

Wraps the shared ``yaml_conformance_runner`` harness so JSON tooling
consumers can read the same ``corpus`` slot that ``validate_skill`` /
``audit_skill_system`` surface — without spinning up the unittest
suite.

Usage::

    python scripts/yaml_conformance_report.py
    python scripts/yaml_conformance_report.py --json
    python scripts/yaml_conformance_report.py --corpus-root tests/fixtures/yaml-conformance

Exit code: 0 on all-pass, 1 on any failure.  Output mode: human by
default, ``--json`` for machine consumption.
"""

import argparse
import os
import sys

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "skill-system-foundry", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from lib import yaml_conformance_runner as runner  # noqa: E402
from lib.reporting import to_json_output  # noqa: E402

DEFAULT_CORPUS_ROOT = os.path.join(
    _REPO_ROOT, "tests", "fixtures", "yaml-conformance"
)


def format_human(summary: dict) -> str:
    """Format the summary dict as one-line-per-failure human output."""
    head = (
        f"YAML conformance corpus: {summary['passed']}/{summary['total']} "
        f"passed, {summary['failed']} failed."
    )
    if not summary["failures"]:
        return head
    body_lines = [head, ""]
    for failure in summary["failures"]:
        body_lines.append(f"FAIL {failure['file']}")
        for msg in failure["messages"]:
            body_lines.append(f"  - {msg}")
    return "\n".join(body_lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns 0 on clean run, 1 on any failure."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the YAML 1.2.2 conformance corpus and emit the same "
            "yaml_conformance.corpus shape that validate_skill / "
            "audit_skill_system surface."
        )
    )
    parser.add_argument(
        "--corpus-root",
        default=DEFAULT_CORPUS_ROOT,
        help=(
            "Path to the corpus root "
            "(default: tests/fixtures/yaml-conformance)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the default human-readable summary.",
    )
    args = parser.parse_args(argv)

    if not os.path.isdir(args.corpus_root):
        if args.json:
            # Tooling consumers parsing --json output need a structured
            # payload on every exit path, including the missing-corpus-
            # root error — bare stderr text breaks the contract.  The
            # missing-root condition counts as one failed corpus-level
            # assertion so ``passed + failed == total`` holds and
            # consumers that key on ``failed`` rather than exit code
            # see the same answer.
            print(
                to_json_output(
                    {
                        "corpus": {
                            "total": 1,
                            "passed": 0,
                            "failed": 1,
                            "failures": [
                                {
                                    "file": "corpus_root",
                                    "messages": [
                                        f"corpus root not found: {args.corpus_root}",
                                    ],
                                }
                            ],
                        }
                    }
                )
            )
        else:
            print(
                f"Error: corpus root not found: {args.corpus_root}",
                file=sys.stderr,
            )
        return 1

    # ``runner.run_corpus`` raises ValueError on hard manifest
    # corruption (malformed digests.txt line, duplicate path, etc.)
    # and discover_fixtures raises on layout violations.  ``--json``
    # consumers depend on the pinned ``corpus`` shape on every exit,
    # so route any such raise into a single failed corpus-level
    # assertion rather than a Python traceback.
    try:
        summary = runner.run_corpus(args.corpus_root)
    except ValueError as exc:
        if args.json:
            print(
                to_json_output(
                    {
                        "corpus": {
                            "total": 1,
                            "passed": 0,
                            "failed": 1,
                            "failures": [
                                {
                                    "file": "corpus",
                                    "messages": [
                                        f"corpus load failure: {exc}"
                                    ],
                                }
                            ],
                        }
                    }
                )
            )
        else:
            print(f"Error: corpus load failure: {exc}", file=sys.stderr)
        return 1

    payload = {"corpus": summary}

    if args.json:
        print(to_json_output(payload))
    else:
        print(format_human(summary))

    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
