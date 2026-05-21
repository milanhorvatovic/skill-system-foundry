#!/usr/bin/env python3
"""Evaluate skill/capability description activation accuracy against a corpus.

Usage:
    python scripts/evaluate_descriptions.py <corpus-path>
    python scripts/evaluate_descriptions.py <corpus-dir> --skill-set .
    python scripts/evaluate_descriptions.py <corpus-dir> --soft --json
    python scripts/evaluate_descriptions.py <corpus-dir> --backfill-hash
    python scripts/evaluate_descriptions.py <corpus-dir> --emit-tasks tasks.json
    python scripts/evaluate_descriptions.py <corpus-dir> --emit-heuristic-predictions h.json
    python scripts/evaluate_descriptions.py <corpus-dir> --predictions agent.json --soft

Heuristic mode is pure stdlib and deterministic: each prompt is scored by
Jaccard token overlap against the candidate ``name + description`` cards.  Exit
code is 0 when every target clears its precision/recall thresholds.  ``--soft``
suppresses threshold breaches only (still exit 0); FAIL-level findings (malformed
corpus, missing or ambiguous target) always exit 1.

``--backfill-hash`` switches to a write mode: it recomputes each corpus's
``description_sha256`` from the live unit description and writes it into the
corpus header in place.  It is idempotent — a corpus already carrying the
correct hash is left byte-for-byte unchanged — so the audit's freshness rule
gets a one-command refresh.  The candidate units come from ``--skill-set``
(default: current directory).

Agent-delegated mode is a key-free, two-phase deep check: ``--emit-tasks``
writes one classification task per prompt (the prompt plus the candidate cards)
for the host agent to fill; the agent writes a ``{id: name | null}`` predictions
file; ``--predictions`` scores it through the same gate, ``--json`` shape, and
exit codes as the heuristic.  ``--emit-heuristic-predictions`` writes the
heuristic's answers for the same task ids, so the two files diff id-for-id.  The
write / score modes (``--backfill-hash``, ``--emit-tasks``,
``--emit-heuristic-predictions``, ``--predictions``) are mutually exclusive.
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
    BackfillOutcome,
    EmitOutcome,
    EvalReport,
    Metrics,
    TargetResult,
    backfill_corpus_hashes,
    check_cross_target_overlap,
    discover_units,
    emit_heuristic_predictions,
    emit_tasks,
    evaluate,
    evaluate_with_predictions,
    load_corpus,
    load_predictions,
)
from lib.reporting import (
    categorize_errors_for_json,
    print_error_line,
    to_json_output,
    to_posix,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate description activation accuracy (heuristic + agent-delegated).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        # Disable prefix abbreviation so the pre-parse `--json` scan and the
        # parsed `args.json_output` agree (no `--js` -> `--json` divergence).
        allow_abbrev=False,
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
        help="Suppress threshold breaches (exit 0); FAIL findings still exit 1.",
    )
    parser.add_argument(
        "--backfill-hash", dest="backfill_hash", action="store_true",
        help=(
            "Write description_sha256 into each corpus header (idempotent), "
            "computed from the --skill-set unit descriptions. Skips scoring."
        ),
    )
    parser.add_argument(
        "--emit-tasks", dest="emit_tasks", default=None, metavar="PATH",
        help=(
            "Write one classification task per prompt to PATH for a host agent "
            "to fill; skips scoring."
        ),
    )
    parser.add_argument(
        "--emit-heuristic-predictions", dest="emit_heuristic_predictions",
        default=None, metavar="PATH",
        help=(
            "Write the heuristic's {id: name|null} answers to PATH for id-keyed "
            "diffing against an agent predictions file; skips scoring."
        ),
    )
    parser.add_argument(
        "--predictions", dest="predictions", default=None, metavar="PATH",
        help=(
            "Score an agent's predictions JSON ({id: name|null}) through the "
            "shared gate; same report shape and exit codes as heuristic mode."
        ),
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
            # Skip run artifacts so an emitted task / predictions file left in
            # the corpus tree is never mistaken for a corpus.  An explicit file
            # path (the branch above) is always honored regardless of suffix.
            if name.endswith((".tasks.json", ".predictions.json")):
                continue
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


def _emit_backfill(outcome: BackfillOutcome, json_mode: bool) -> None:
    """Print the backfill summary (JSON or human) and exit.

    Exit 1 only when a FAIL-level finding fired (a corpus that could not be
    read / parsed); skipped-target WARNs and a clean no-op both exit 0.
    """
    has_fail = any(f.startswith(LEVEL_FAIL) for f in outcome.findings)
    if json_mode:
        print(to_json_output({
            "tool": "evaluate_descriptions",
            "mode": "backfill",
            "success": not has_fail,
            "updated": [to_posix(p) for p in outcome.updated],
            "unchanged": [to_posix(p) for p in outcome.unchanged],
            "errors": categorize_errors_for_json(outcome.findings),
        }))
    else:
        for path in outcome.updated:
            print(f"updated  {to_posix(path)}")
        for path in outcome.unchanged:
            print(f"unchanged {to_posix(path)}")
        for finding in outcome.findings:
            print_error_line(finding)
        print(
            f"Backfill: {len(outcome.updated)} updated, "
            f"{len(outcome.unchanged)} unchanged"
        )
    sys.exit(1 if has_fail else 0)


def _emit_write_outcome(
    outcome: EmitOutcome, json_mode: bool, mode: str, noun: str,
) -> None:
    """Print an emit-mode write summary (JSON or human) and exit.

    Exit 1 when a FAIL-level finding fired (malformed corpus, unwritable path,
    missing or ambiguous target); a clean write exits 0.
    """
    has_fail = any(f.startswith(LEVEL_FAIL) for f in outcome.findings)
    if json_mode:
        print(to_json_output({
            "tool": "evaluate_descriptions",
            "mode": mode,
            "success": not has_fail,
            "path": outcome.path,
            "task_count": outcome.task_count,
            "corpora_count": outcome.corpora_count,
            "errors": categorize_errors_for_json(outcome.findings),
        }))
    else:
        for finding in outcome.findings:
            print_error_line(finding)
        if not has_fail:
            print(
                f"wrote {outcome.task_count} {noun} from "
                f"{outcome.corpora_count} corpora to {outcome.path}"
            )
    sys.exit(1 if has_fail else 0)


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
    # Post-parse, honor argparse's parsed value for the early-exit paths below.
    # Abbreviation is disabled (allow_abbrev=False), so this only guards against
    # argument-ordering differences, not `--js` -> `--json` expansion.
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

    skill_set = args.skill_set or os.getcwd()

    # The write / agent modes are mutually exclusive: each owns the run.
    active_modes = [
        name for name, value in (
            ("--backfill-hash", args.backfill_hash),
            ("--emit-tasks", args.emit_tasks),
            ("--emit-heuristic-predictions", args.emit_heuristic_predictions),
            ("--predictions", args.predictions),
        ) if value
    ]
    if len(active_modes) > 1:
        _exit(f"{' and '.join(active_modes)} are mutually exclusive", json_mode)

    # Backfill is a write mode that short-circuits scoring entirely: it only
    # needs the unit descriptions to recompute and persist each corpus's hash.
    if args.backfill_hash:
        outcome = backfill_corpus_hashes(corpus_paths, discover_units(skill_set))
        _emit_backfill(outcome, json_mode)
        return  # _emit_backfill calls sys.exit; return keeps flow obvious.

    # Agent-delegated phase one: emit one classification task per prompt for the
    # host agent to fill. A write mode — no scoring.
    if args.emit_tasks:
        outcome = emit_tasks(corpus_paths, discover_units(skill_set), args.emit_tasks)
        _emit_write_outcome(outcome, json_mode, "emit-tasks", "tasks")
        return

    # The heuristic's answers for the same task ids — a baseline to diff against
    # an agent predictions file. Also a write mode.
    if args.emit_heuristic_predictions:
        outcome = emit_heuristic_predictions(
            corpus_paths, discover_units(skill_set), args.emit_heuristic_predictions,
        )
        _emit_write_outcome(
            outcome, json_mode, "emit-heuristic-predictions", "predictions",
        )
        return

    corpora = []
    findings: list[str] = []
    for path in corpus_paths:
        corpus, corpus_findings = load_corpus(path)
        findings.extend(corpus_findings)
        if corpus is not None:
            corpora.append(corpus)
    findings.extend(check_cross_target_overlap(corpora))

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

    # Agent-delegated phase two: score an agent's predictions through the same
    # gate as the heuristic. A load FAIL leaves predictions None — surfaced via
    # findings on an empty report so --soft cannot mask it.
    if args.predictions:
        predictions, pred_findings = load_predictions(args.predictions)
        findings.extend(pred_findings)
        if predictions is None:
            report = EvalReport(
                min_precision=opts["min_precision"],
                min_recall=opts["min_recall"],
            )
        else:
            report = evaluate_with_predictions(corpora, units, predictions, opts)
    else:
        report = evaluate(corpora, units, opts)
    # Prepend corpus-load + cross-target findings so they share the report's
    # error stream (and feed report.success / the exit code).
    report.errors = findings + report.errors

    if args.json_output:
        print(_report_to_json(report))
    else:
        _print_human(report, args.verbose)

    # --soft is advisory for threshold breaches only: it must never mask a
    # FAIL-level finding (malformed JSON, missing keys, target not found,
    # ambiguous target), or a structurally broken corpus would pass CI green.
    has_fail_finding = any(e.startswith(LEVEL_FAIL) for e in report.errors)
    exit_ok = report.success or (args.soft and not has_fail_finding)
    sys.exit(0 if exit_ok else 1)


if __name__ == "__main__":
    main()
