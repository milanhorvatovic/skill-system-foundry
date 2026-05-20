#!/usr/bin/env python3
"""Evaluate skill/capability description activation accuracy against a corpus.

Usage:
    python scripts/evaluate_descriptions.py <corpus-path>
    python scripts/evaluate_descriptions.py <corpus-dir> --skill-set .
    python scripts/evaluate_descriptions.py <corpus-dir> --soft --json
    python scripts/evaluate_descriptions.py <corpus-dir> --llm --model <name>

Heuristic mode (default) is pure stdlib and deterministic.  LLM mode (--llm)
classifies via a configured provider over ``urllib`` and needs the provider's
API-key environment variable.  Exit code is 0 when every target clears its
precision/recall thresholds (or under --soft); 1 otherwise.
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
    EVAL_PROVIDERS,
    EVAL_RUNS_HEURISTIC,
    EVAL_RUNS_LLM,
    EVAL_TRAIN_VALIDATION_RATIO,
    LEVEL_FAIL,
)
from lib.description_eval import (
    MODE_HEURISTIC,
    MODE_LLM,
    EvalReport,
    Metrics,
    TargetResult,
    _anthropic_messages,
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

# Maps a provider's ``client`` key (configuration.yaml) to its client function.
_CLIENT_DISPATCH = {"anthropic_messages": _anthropic_messages}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate description activation accuracy (heuristic or LLM mode)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "corpus_path", help="A corpus JSON file or a directory of corpus files.",
    )
    parser.add_argument(
        "--skill-set", dest="skill_set", default=None,
        help="Directory of candidate skills (default: current directory).",
    )
    parser.add_argument("--llm", action="store_true", help="Opt-in LLM mode.")
    parser.add_argument(
        "--provider", default="anthropic", help="Provider name (default: anthropic).",
    )
    parser.add_argument("--model", default=None, help="Override the provider model.")
    parser.add_argument(
        "--runs", type=int, default=None,
        help="Runs per query (default: 1 heuristic, 3 LLM).",
    )
    parser.add_argument("--min-precision", dest="min_precision", type=float, default=None)
    parser.add_argument("--min-recall", dest="min_recall", type=float, default=None)
    parser.add_argument(
        "--split-seed", dest="split_seed", type=int, default=None,
        help="Enable a stratified train/validation split with this seed.",
    )
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
        "validation_metrics": (
            _metrics_to_dict(result.validation_metrics)
            if result.validation_metrics is not None else None
        ),
        "advisory": result.advisory,
    }


def _report_to_json(report: EvalReport) -> str:
    return to_json_output({
        "tool": "evaluate_descriptions",
        "mode": report.mode,
        "provider": report.provider,
        "model": report.model,
        "success": report.success,
        "thresholds": {
            "min_precision": report.min_precision,
            "min_recall": report.min_recall,
        },
        "split": report.split,
        "targets": [_target_to_dict(t) for t in report.targets],
        "findings": categorize_errors_for_json(report.errors),
    })


def _print_human(report: EvalReport, verbose: bool) -> None:
    for result in report.targets:
        metrics = result.gate_metrics
        status = "PASS" if metrics.passed else "FAIL"
        print(
            f"[{status}] {result.kind} {result.target}: "
            f"precision={metrics.precision:.2f} recall={metrics.recall:.2f} "
            f"(candidates={result.candidate_count})"
        )
        if verbose:
            pairwise = result.advisory.get("pairwise_confusion") or {}
            if pairwise:
                print(f"    confused with: {pairwise}")
            unstable = result.advisory.get("unstable_queries") or []
            if unstable:
                print(f"    unstable prompts: {len(unstable)}")
    for finding in report.errors:
        print_error_line(finding)
    print(f"Overall: {'PASS' if report.success else 'FAIL'}")


def _make_client_fn(provider: str, model_override: str | None, json_mode: bool):
    """Bind the provider's client function; exits on misconfiguration."""
    provider_cfg = EVAL_PROVIDERS.get(provider)
    if provider_cfg is None:
        _exit(f"unknown provider '{provider}'", json_mode)
    client_key = provider_cfg.get("client")
    client = _CLIENT_DISPATCH.get(client_key)
    if client is None:
        _exit(f"provider '{provider}' has no known client '{client_key}'", json_mode)
    env_var = provider_cfg["env_var"]
    api_key = os.environ.get(env_var)
    if not api_key:
        _exit(f"environment variable {env_var} is not set (required for --llm)", json_mode)
    model = model_override or provider_cfg["default_model"]
    endpoint = provider_cfg["endpoint"]

    def client_fn(prompt: str, candidates: list) -> str:
        return client(prompt, candidates, model, api_key, endpoint)

    return client_fn, model


def main() -> None:
    json_mode = "--json" in sys.argv
    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(1)

    args = _build_parser().parse_args()
    mode = MODE_LLM if args.llm else MODE_HEURISTIC

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

    provider = None
    model = None
    client_fn = None
    if args.llm:
        client_fn, model = _make_client_fn(args.provider, args.model, json_mode)
        provider = args.provider

    opts = {
        "runs": args.runs if args.runs is not None else (
            EVAL_RUNS_LLM if args.llm else EVAL_RUNS_HEURISTIC
        ),
        "min_precision": (
            args.min_precision if args.min_precision is not None
            else EVAL_DEFAULT_MIN_PRECISION
        ),
        "min_recall": (
            args.min_recall if args.min_recall is not None
            else EVAL_DEFAULT_MIN_RECALL
        ),
        "split_seed": args.split_seed,
        "ratio": EVAL_TRAIN_VALIDATION_RATIO,
        "client_fn": client_fn,
        "provider": provider,
        "model": model,
    }

    report = evaluate(corpora, units, mode, opts)
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
