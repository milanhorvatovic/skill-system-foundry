"""Enforce per-file branch coverage minimum.

Reads coverage.json (produced by ``python -m coverage json``) and the
threshold from ``.coveragerc``.  Exits non-zero when any individual source
file's branch coverage falls below the threshold.
"""

import argparse
import configparser
import json
import os
import sys


def load_threshold(coveragerc_path: str) -> float:
    """Read ``fail_under`` from a ``.coveragerc`` file.

    Raises ``SystemExit`` with a clear message when the file is missing,
    the ``[report]`` section is absent, ``fail_under`` is not set, or the
    value is not a valid number.
    """
    if not os.path.isfile(coveragerc_path):
        print(
            "Error: .coveragerc not found at: %s" % coveragerc_path,
            file=sys.stderr,
        )
        raise SystemExit(1)

    parser = configparser.ConfigParser()
    try:
        files_read = parser.read(coveragerc_path, encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        print(
            "Error: failed to read/parse .coveragerc at %s: %s"
            % (coveragerc_path, exc),
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not files_read:
        print(
            "Error: failed to read .coveragerc at: %s" % coveragerc_path,
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not parser.has_section("report"):
        print(
            "Error: .coveragerc missing [report] section",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not parser.has_option("report", "fail_under"):
        print(
            "Error: .coveragerc [report] section missing fail_under key",
            file=sys.stderr,
        )
        raise SystemExit(1)

    raw = parser.get("report", "fail_under")
    try:
        return float(raw)
    except ValueError:
        print(
            "Error: .coveragerc fail_under is not a valid number: %s" % raw,
            file=sys.stderr,
        )
        raise SystemExit(1)


def check_per_file(
    json_path: str, threshold: float
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return ``(failures, passes)`` for per-file branch coverage.

    *json_path* is the path to a ``coverage.json`` file produced by
    ``python -m coverage json``.  Each file's
    ``summary.percent_branches_covered`` is compared against *threshold*.

    Raises ``OSError`` when the file cannot be read, ``json.JSONDecodeError``
    when the content is not valid JSON, and ``ValueError`` when the data
    structure is malformed (missing ``files`` dict, or a file entry lacks
    ``summary.percent_branches_covered`` as a number).
    """
    with open(json_path, encoding="utf-8") as fh:
        data = json.load(fh)

    if "files" not in data or not isinstance(data.get("files"), dict):
        raise ValueError(
            "coverage.json is malformed — missing or non-dict top-level 'files' key"
        )

    failures: list[tuple[str, float]] = []
    passes: list[tuple[str, float]] = []
    for filename in sorted(data["files"]):
        info = data["files"][filename]
        if not isinstance(info, dict) or "summary" not in info:
            raise ValueError(
                "coverage.json malformed entry for '%s': missing 'summary'" % filename
            )
        summary = info["summary"]
        if not isinstance(summary, dict) or "percent_branches_covered" not in summary:
            raise ValueError(
                "coverage.json malformed entry for '%s': missing "
                "'summary.percent_branches_covered'" % filename
            )
        pct = summary["percent_branches_covered"]
        if not isinstance(pct, (int, float)):
            raise ValueError(
                "coverage.json malformed entry for '%s': "
                "'percent_branches_covered' is not a number" % filename
            )
        if pct < threshold:
            failures.append((filename, pct))
        else:
            passes.append((filename, pct))
    return failures, passes


def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns 0 when all files pass, 1 otherwise."""
    parser = argparse.ArgumentParser(
        description="Check per-file branch coverage against a minimum threshold."
    )
    parser.add_argument(
        "--coverage-json",
        default="coverage.json",
        help="Path to coverage.json (default: coverage.json)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override threshold instead of reading from .coveragerc",
    )
    parser.add_argument(
        "--coveragerc",
        default=".coveragerc",
        help="Path to .coveragerc (default: .coveragerc)",
    )
    args = parser.parse_args(argv)

    # Determine threshold
    if args.threshold is not None:
        threshold = args.threshold
    else:
        threshold = load_threshold(args.coveragerc)

    # Load and validate coverage data via check_per_file
    if not os.path.isfile(args.coverage_json):
        print(
            "Error: coverage.json not found at: %s" % args.coverage_json,
            file=sys.stderr,
        )
        return 1

    try:
        failures, passes = check_per_file(args.coverage_json, threshold)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            "Error: failed to read/parse coverage.json at %s: %s"
            % (args.coverage_json, exc),
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1

    # Print results
    print("Per-file branch coverage (threshold: %.1f%%)" % threshold)
    print("-" * 60)

    for filename, pct in passes:
        print("  PASS  %6.1f%%  %s" % (pct, filename))

    for filename, pct in failures:
        print("  FAIL  %6.1f%%  %s" % (pct, filename))

    print("-" * 60)

    if failures:
        print(
            "%d file(s) below %.1f%% branch coverage threshold"
            % (len(failures), threshold)
        )
        return 1

    print("All %d file(s) meet the %.1f%% threshold" % (len(passes), threshold))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
