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
            f"Error: .coveragerc not found at: {coveragerc_path}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    parser = configparser.ConfigParser(interpolation=None)
    try:
        files_read = parser.read(coveragerc_path, encoding="utf-8")
    except (OSError, configparser.Error, UnicodeDecodeError) as exc:
        print(
            f"Error: failed to read/parse .coveragerc at {coveragerc_path}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not files_read:
        print(
            f"Error: failed to read .coveragerc at: {coveragerc_path}",
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
            f"Error: .coveragerc fail_under is not a valid number: {raw}",
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

    When ``percent_branches_covered`` is absent (coverage < 7.7), the
    percentage is computed from ``covered_branches / num_branches``.
    Files with ``num_branches == 0`` (branchless) are treated as 100%
    covered.

    Raises ``OSError`` when the file cannot be read, ``json.JSONDecodeError``
    when the content is not valid JSON, and ``ValueError`` when the data
    structure is malformed (missing ``files`` dict, or a file entry lacks
    branch coverage data that can be used or computed).
    """
    with open(json_path, encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ValueError(
            "coverage.json is malformed — missing or non-dict top-level 'files' key"
        )

    failures: list[tuple[str, float]] = []
    passes: list[tuple[str, float]] = []
    for filename in sorted(data["files"]):
        info = data["files"][filename]
        if not isinstance(info, dict) or "summary" not in info:
            raise ValueError(
                f"coverage.json malformed entry for '{filename}': missing 'summary'"
            )
        summary = info["summary"]
        if not isinstance(summary, dict):
            raise ValueError(
                f"coverage.json malformed entry for '{filename}': "
                f"'summary' is not a dict"
            )

        if "percent_branches_covered" in summary:
            pct = summary["percent_branches_covered"]
            if not isinstance(pct, (int, float)):
                raise ValueError(
                    f"coverage.json malformed entry for '{filename}': "
                    f"'percent_branches_covered' is not a number"
                )
        else:
            # coverage < 7.7 omits percent_branches_covered — compute
            # from raw counts when available.
            num = summary.get("num_branches")
            covered = summary.get("covered_branches")
            if isinstance(num, (int, float)) and num == 0:
                if covered is not None and not (
                    isinstance(covered, (int, float)) and covered == 0
                ):
                    raise ValueError(
                        f"coverage.json malformed entry for '{filename}': "
                        f"'num_branches' is 0 but 'covered_branches' is {covered!r}"
                    )
                pct = 100.0
            elif (
                isinstance(num, (int, float))
                and num > 0
                and isinstance(covered, (int, float))
            ):
                pct = (covered * 100.0) / num
            else:
                raise ValueError(
                    f"coverage.json malformed entry for '{filename}': missing "
                    f"'summary.percent_branches_covered' and cannot compute "
                    f"from raw counts"
                )
        if not (0.0 <= pct <= 100.0):
            raise ValueError(
                f"coverage.json malformed entry for '{filename}': "
                f"branch coverage {pct:.2f}% is outside the 0–100 range"
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
        try:
            threshold = load_threshold(args.coveragerc)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1

    # Validate threshold range
    if not (0.0 <= threshold <= 100.0):
        print(
            f"Error: coverage threshold must be between 0 and 100 (inclusive); got {threshold:.2f}",
            file=sys.stderr,
        )
        return 1

    # Load and validate coverage data via check_per_file
    if not os.path.isfile(args.coverage_json):
        print(
            f"Error: coverage.json not found at: {args.coverage_json}",
            file=sys.stderr,
        )
        return 1

    try:
        failures, passes = check_per_file(args.coverage_json, threshold)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"Error: failed to read/parse coverage.json at {args.coverage_json}: {exc}",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Print results
    print(f"Per-file branch coverage (threshold: {threshold:.1f}%)")
    print("-" * 60)

    for filename, pct in passes:
        print(f"  PASS  {pct:6.1f}%  {filename}")

    for filename, pct in failures:
        print(f"  FAIL  {pct:6.1f}%  {filename}")

    print("-" * 60)

    if failures:
        print(
            f"{len(failures)} file(s) below {threshold:.1f}% branch coverage threshold"
        )
        return 1

    print(f"All {len(passes)} file(s) meet the {threshold:.1f}% threshold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
