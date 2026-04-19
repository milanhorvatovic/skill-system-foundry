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
_TESTS_LIB = os.path.join(_REPO_ROOT, "tests", "lib")
for _path in (_SCRIPTS_DIR, _TESTS_LIB):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import yaml_conformance_runner as runner  # noqa: E402
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
        print(
            f"Error: corpus root not found: {args.corpus_root}",
            file=sys.stderr,
        )
        return 1

    summary = runner.run_corpus(args.corpus_root)
    payload = {"corpus": summary}

    if args.json:
        print(to_json_output(payload))
    else:
        print(format_human(summary))

    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
