#!/usr/bin/env python3
"""Evaluate skill/capability description activation accuracy against a corpus.

Usage:
    python scripts/evaluate_descriptions.py <corpus-path>
    python scripts/evaluate_descriptions.py <corpus-dir> --skill-set .
    python scripts/evaluate_descriptions.py <corpus-dir> --soft --json

Heuristic mode is pure stdlib and deterministic: each prompt is scored by
Jaccard token overlap against the candidate ``name + description`` cards.  Exit
code is 0 when every target clears its precision/recall thresholds (or under
--soft); 1 otherwise.
"""

import argparse
import os
import sys

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from lib.constants import (
    EVAL_DEFAULT_MIN_PRECISION,
    EVAL_DEFAULT_MIN_RECALL,
    LEVEL_FAIL,
)
from lib.description_eval import (
    EvalReport,
    Metrics,
    TargetResult,
    check_cross_target_overlap,
    discover_units,
    evaluate,
    load_corpus,
)
from lib.reporting import (
    categorize_errors_for_json,
    print_error_line,
    to_json_output,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate description activation accuracy (heuristic).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "corpus_path", help="A corpus JSON file or a directory of corpus files.",
    )
    parser.add_argument(
        "--skill-set", dest="skill_set", default=None,
        help="Directory of candidate skills (default: current directory).",
    )
    parser.add_argument("--min-precision", dest="min_precision", type=float, default=None)
    parser.add_argument("--min-recall", dest="min_recall", type=float, default=None)
    parser.add_argument(
        "--soft", action="store_true",
        help="Exit 0 even on threshold breach (findings still emitted).",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show per-target advisory detail.",
    )
    return parser


def _resolve_corpus_paths(corpus_path: str) -> list[str]:
    """Return the corpus files: the path itself, or every ``*.json`` beneath it."""
    if os.path.isfile(corpus_path):
        return [corpus_path]
    if not os.path.isdir(corpus_path):
        return []
    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(corpus_path):
        for name in sorted(filenames):
            if name.endswith(".json"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def _exit(message: str, json_mode: bool) -> None:
    """Emit a fatal early-exit error (JSON or human) and exit 1."""
    if json_mode:
        print(to_json_output({
            "tool": "evaluate_descriptions", "success": False, "error": message,
        }))
    else:
        print_error_line(f"{LEVEL_FAIL}: {message}")
    sys.exit(1)


def _metrics_to_dict(metrics: Metrics) -> dict:
    return {
        "precision": metrics.precision,
        "recall": metrics.recall,
        "passed": metrics.passed,
        "confusion": {
            "tp": metrics.tp, "fp": metrics.fp, "tn": metrics.tn, "fn": metrics.fn,
        },
    }


def _target_to_dict(result: TargetResult) -> dict:
    return {
        "target": result.target,
        "kind": result.kind,
        "candidate_count": result.candidate_count,
        "metrics": _metrics_to_dict(result.metrics),
        "thresholds": {
            "min_precision": result.min_precision,
            "min_recall": result.min_recall,
        },
        "advisory": result.advisory,
    }


def _report_to_json(report: EvalReport) -> str:
    return to_json_output({
        "tool": "evaluate_descriptions",
        "success": report.success,
        "thresholds": {
            "min_precision": report.min_precision,
            "min_recall": report.min_recall,
        },
        "targets": [_target_to_dict(t) for t in report.targets],
        "errors": categorize_errors_for_json(report.errors),
    })


def _print_human(report: EvalReport, verbose: bool) -> None:
    for result in report.targets:
        metrics = result.metrics
        status = "PASS" if metrics.passed else "FAIL"
        print(
            f"[{status}] {result.kind} {result.target}: "
            f"precision={metrics.precision:.2f} recall={metrics.recall:.2f} "
            f"(candidates={result.candidate_count})"
        )
        if verbose:
            print(
                f"    thresholds: min_precision={result.min_precision:.2f} "
                f"min_recall={result.min_recall:.2f}"
            )
            pairwise = result.advisory.get("pairwise_confusion") or {}
            if pairwise:
                print(f"    confused with: {pairwise}")
    for finding in report.errors:
        print_error_line(finding)
    print(f"Overall: {'PASS' if report.success else 'FAIL'}")


def main() -> None:
    # Pre-parse scan: _json_aware_error fires during parse_args(), before `args`
    # exists, so it can only consult argv. Recomputed from args.json_output below.
    json_mode = "--json" in sys.argv
    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(1)

    parser = _build_parser()

    def _json_aware_error(message: str) -> None:
        # Emit the tool's JSON error shape on argparse failures under --json,
        # matching validate_skill.py / bundle.py / stats.py.
        if json_mode:
            print(to_json_output({
                "tool": "evaluate_descriptions", "success": False,
                "error": message,
            }))
            sys.exit(1)
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)

    parser.error = _json_aware_error  # type: ignore[assignment]
    args = parser.parse_args()
    # Post-parse, honor argparse's parsed value: it handles flag abbreviation
    # (e.g. --js -> --json) that the pre-parse argv scan above would miss.
    json_mode = args.json_output

    for flag, value in (
        ("--min-precision", args.min_precision),
        ("--min-recall", args.min_recall),
    ):
        if value is not None and not 0.0 <= value <= 1.0:
            _exit(f"{flag} must be a number between 0 and 1", json_mode)

    corpus_paths = _resolve_corpus_paths(args.corpus_path)
    if not corpus_paths:
        _exit(f"no corpus JSON found at '{args.corpus_path}'", json_mode)

    corpora = []
    findings: list[str] = []
    for path in corpus_paths:
        corpus, corpus_findings = load_corpus(path)
        findings.extend(corpus_findings)
        if corpus is not None:
            corpora.append(corpus)
    findings.extend(check_cross_target_overlap(corpora))

    skill_set = args.skill_set or os.getcwd()
    units = discover_units(skill_set)

    opts = {
        "min_precision": (
            args.min_precision if args.min_precision is not None
            else EVAL_DEFAULT_MIN_PRECISION
        ),
        "min_recall": (
            args.min_recall if args.min_recall is not None
            else EVAL_DEFAULT_MIN_RECALL
        ),
    }

    report = evaluate(corpora, units, opts)
    # Prepend corpus-load + cross-target findings so they share the report's
    # error stream (and feed report.success / the exit code).
    report.errors = findings + report.errors

    if args.json_output:
        print(_report_to_json(report))
    else:
        _print_human(report, args.verbose)

    sys.exit(0 if (report.success or args.soft) else 1)


if __name__ == "__main__":
    main()
