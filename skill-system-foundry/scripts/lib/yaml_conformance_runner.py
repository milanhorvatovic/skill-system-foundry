"""Shared helpers for the YAML 1.2.2 conformance corpus harness.

Two consumers:

- ``tests/test_yaml_conformance.py`` — runs the full corpus as part of
  the unittest suite and surfaces failures via ``self.fail(...)``.
- ``skill-system-foundry/scripts/yaml_conformance_report.py`` — emits
  the same shape as JSON for tooling consumers that don't run tests.

This module is pure data — no test framework dependencies — so callers
control how failures surface.  It lives under ``lib/`` so the shipped
report script can import it from the bundled distribution rather than
crossing into ``tests/`` (which the release bundle excludes).

Sorted iteration: ``os.walk`` is wrapped to sort directory and
filename order, ensuring byte-identical output across platforms with
different filesystem ordering.

Digest manifest format: ``digests.txt`` follows the standard
``sha256sum`` shape (``<hex-digest>  <relative-path>``).  Lines split
on the first run of whitespace; the right half is the path verbatim
so paths with embedded ``=`` etc. survive.  Whitespace-in-paths is
forbidden by curation convention so the simple split is unambiguous.
"""

import hashlib
import json
import os
from collections.abc import Iterator

from .yaml_parser import parse_yaml_subset

VARIANT_SUFFIXES = (".lf.yaml", ".crlf.yaml", ".mixed.yaml")
BUCKETS = ("supported", "divergent", "rejected")
_EXPECTED_SUFFIX = ".expected.json"
_META_SUFFIX = ".meta.json"


def parse_digests_file(text: str) -> dict[str, str]:
    """Parse ``digests.txt`` text into a ``{path: hex-digest}`` dict.

    Splits each non-empty line on the first run of whitespace.  Raises
    ``ValueError`` when a line lacks two whitespace-separated fields,
    or when the same fixture path appears more than once: duplicate
    entries are manifest corruption (typically a bad merge), and
    silently letting the last value win would mask drift depending on
    line order.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\n").strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"malformed digests.txt line: {raw!r}")
        digest, path = parts[0], parts[1]
        if path in out:
            raise ValueError(
                f"duplicate digest entry for path: {path}"
            )
        out[path] = digest
    return out


def hash_file(path: str) -> str:
    """Return hex SHA-256 of the bytes at *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _strip_variant_suffix(rel: str) -> str:
    """Return *rel* with any ``.{lf,crlf,mixed}.yaml`` suffix removed."""
    for suffix in VARIANT_SUFFIXES:
        if rel.endswith(suffix):
            return rel[: -len(suffix)]
    return rel


def _walk_sorted(
    root: str,
) -> Iterator[tuple[str, list[str], list[str]]]:
    """``os.walk`` with sorted dirnames + filenames at every level."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        yield dirpath, dirnames, filenames


def discover_fixtures(corpus_root: str) -> dict[str, list[dict]]:
    """Group corpus variants and sidecars by bucket and base.

    Returns a dict keyed by bucket name (``supported`` / ``divergent`` /
    ``rejected``) whose values are lists of case dicts:

        {
            "base": "<bucket>/<...>/<base>",
            "variants": ["<bucket>/.../base.lf.yaml", ...],
            "expected": "<bucket>/.../base.expected.json" | None,
            "meta": "<bucket>/.../base.meta.json" | None,
        }

    Raises ``ValueError`` for unknown top-level directories and for
    orphan sidecars with no matching fixture.
    """
    result: dict[str, list[dict]] = {b: [] for b in BUCKETS}
    if not os.path.isdir(corpus_root):
        return result
    for entry in sorted(os.listdir(corpus_root)):
        full = os.path.join(corpus_root, entry)
        if not os.path.isdir(full):
            continue
        if entry not in BUCKETS:
            raise ValueError(
                f"unknown corpus bucket: {entry} "
                "(expected supported/divergent/rejected)"
            )
        result[entry] = _collect_bucket(full, corpus_root)
    return result


def _collect_bucket(bucket_dir: str, corpus_root: str) -> list[dict]:
    """Walk *bucket_dir* and return cases sorted by base."""
    bases: dict[str, dict] = {}
    sidecars: dict[str, dict] = {}
    for dirpath, _dirnames, filenames in _walk_sorted(bucket_dir):
        for fname in filenames:
            if fname == ".gitkeep":
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, corpus_root).replace(os.sep, "/")
            if any(rel.endswith(s) for s in VARIANT_SUFFIXES):
                base = _strip_variant_suffix(rel)
                bases.setdefault(base, {"base": base, "variants": []})[
                    "variants"
                ].append(rel)
            elif rel.endswith(_EXPECTED_SUFFIX):
                key = rel[: -len(_EXPECTED_SUFFIX)]
                sidecars.setdefault(key, {})["expected"] = rel
            elif rel.endswith(_META_SUFFIX):
                key = rel[: -len(_META_SUFFIX)]
                sidecars.setdefault(key, {})["meta"] = rel
    cases: list[dict] = []
    for base in sorted(bases):
        case = bases[base]
        case["variants"].sort()
        case["expected"] = sidecars.get(base, {}).get("expected")
        case["meta"] = sidecars.get(base, {}).get("meta")
        cases.append(case)
    seen = set(bases)
    for key, sc in sorted(sidecars.items()):
        if key not in seen:
            sidecar_path = sc.get("expected") or sc.get("meta")
            raise ValueError(
                f"orphan sidecar: {sidecar_path} "
                f"(no matching fixture at {key})"
            )
    return cases


def check_variant_parse(
    bucket: str, raw_text: str, expected: dict
) -> list[str]:
    """Run the bucket-appropriate parse assertion for one variant.

    Returns a list of error messages (empty list on pass).
    """
    errors: list[str] = []
    if bucket == "rejected":
        substr = expected.get("error_substring", "")
        try:
            parse_yaml_subset(raw_text, [])
        except ValueError as exc:
            if substr and substr not in str(exc):
                errors.append(
                    f"ValueError missing substring {substr!r}: {exc}"
                )
            return errors
        errors.append(
            f"expected ValueError containing {substr!r}, parse succeeded"
        )
        return errors

    findings: list[str] = []
    try:
        parsed = parse_yaml_subset(raw_text, findings)
    except ValueError as exc:
        errors.append(f"unexpected ValueError: {exc}")
        return errors
    if "parsed" in expected and parsed != expected["parsed"]:
        errors.append(
            f"parsed dict mismatch: got {parsed!r}, "
            f"expected {expected['parsed']!r}"
        )
    if bucket == "supported" and findings:
        errors.append(
            f"supported case emitted findings: {findings!r}"
        )
    if bucket == "divergent":
        for fdng in expected.get("findings", []):
            sev = fdng.get("severity", "").upper()
            substr = fdng.get("substring", "")
            if not any(f.startswith(sev) and substr in f for f in findings):
                errors.append(
                    f"divergent case missing finding "
                    f"sev={sev!r} substr={substr!r}; got: {findings!r}"
                )
    return errors


def check_parity(variant_texts: list[str]) -> list[str]:
    """Confirm every variant of a base parses to the same dict.

    A variant that raises ``ValueError`` during reparse is reported
    once as ``"parity skipped due to variant parse failure"`` rather
    than propagating — ``check_variant_parse`` already captured the
    underlying parse error per variant, so re-surfacing it here would
    crash the corpus harness on a single malformed fixture instead of
    aggregating failures cleanly.
    """
    if len(variant_texts) <= 1:
        return []
    parsed_dicts = []
    for text in variant_texts:
        try:
            parsed_dicts.append(parse_yaml_subset(text, []))
        except ValueError:
            return ["parity skipped due to variant parse failure"]
    first = parsed_dicts[0]
    return [
        f"parity mismatch on variant index {i}"
        for i, p in enumerate(parsed_dicts[1:], start=1)
        if p != first
    ]


def run_case(
    corpus_root: str,
    bucket: str,
    case: dict,
    digests: dict[str, str],
    *,
    enforce_digests: bool = True,
) -> list[str]:
    """Run digest, parse, and parity checks for one case.

    Returns aggregated error messages (empty on success).
    """
    msgs: list[str] = []

    if not case.get("expected"):
        msgs.append(
            f"fixture base missing sidecar: {case['base']} "
            f"(expected {case['base']}{_EXPECTED_SUFFIX})"
        )
        return msgs
    if not case.get("meta"):
        msgs.append(
            f"fixture base missing sidecar: {case['base']} "
            f"(expected {case['base']}{_META_SUFFIX})"
        )
        return msgs

    try:
        with open(
            os.path.join(corpus_root, case["expected"]),
            "r",
            encoding="utf-8",
        ) as fh:
            expected = json.load(fh)
    except json.JSONDecodeError as exc:
        msgs.append(
            f"sidecar parse error: {case['expected']} — {exc}"
        )
        return msgs
    try:
        with open(
            os.path.join(corpus_root, case["meta"]),
            "r",
            encoding="utf-8",
        ) as fh:
            json.load(fh)
    except json.JSONDecodeError as exc:
        msgs.append(
            f"sidecar parse error: {case['meta']} — {exc}"
        )
        return msgs

    variant_names = set(case["variants"])
    if bucket in ("supported", "divergent"):
        for suffix in VARIANT_SUFFIXES:
            expected_variant = case["base"] + suffix
            if expected_variant not in variant_names:
                msgs.append(
                    f"incomplete line-ending set for {case['base']}: "
                    f"missing {expected_variant}"
                )

    # Digest enforcement is fail-loud per variant when a manifest is in
    # play: a missing entry is just as much a drift signal as a hash
    # mismatch, so both routes mark the variant as drifted and parity
    # is skipped (it is meaningless once we cannot trust the bytes).
    # ``enforce_digests`` is driven by the caller (``run_corpus``) from
    # whether ``digests.txt`` actually exists on disk — an empty-but-
    # present manifest still enforces (every variant fails as missing
    # entry), since an accidentally truncated manifest would otherwise
    # silently disable both per-variant checks and the orphan-digest
    # sweep.  Only an absent file (typical scaffolding state) skips
    # enforcement.
    digest_failures: set[str] = set()
    for variant_rel in case["variants"]:
        variant_path = os.path.join(corpus_root, variant_rel)
        if variant_rel not in digests:
            if enforce_digests:
                msgs.append(f"missing digest entry: {variant_rel}")
                digest_failures.add(variant_rel)
            continue
        actual = hash_file(variant_path)
        if actual != digests[variant_rel]:
            msgs.append(
                f"digest mismatch: {variant_rel} "
                f"expected={digests[variant_rel]} actual={actual}"
            )
            digest_failures.add(variant_rel)

    variant_texts: list[str] = []
    for variant_rel in case["variants"]:
        if variant_rel in digest_failures:
            continue
        variant_path = os.path.join(corpus_root, variant_rel)
        with open(variant_path, "rb") as fh:
            text = fh.read().decode("utf-8")
        variant_texts.append(text)
        msgs.extend(check_variant_parse(bucket, text, expected))

    if bucket in ("supported", "divergent"):
        if digest_failures:
            msgs.append(
                "parity skipped due to byte drift on "
                f"{sorted(digest_failures)}"
            )
        else:
            msgs.extend(check_parity(variant_texts))

    return msgs


def run_corpus(corpus_root: str) -> dict:
    """Run the full corpus and return the summary dict.

    Orphan digest entries (manifest lines whose path does not match any
    discovered fixture variant) are surfaced as a corpus-level failure
    under the synthetic ``digests.txt`` file slot.  This catches the
    inverse of the per-case ``missing digest entry`` check: a fixture
    deletion that left its digest line behind.
    """
    digests: dict[str, str] = {}
    digests_path = os.path.join(corpus_root, "digests.txt")
    manifest_present = os.path.isfile(digests_path)
    if manifest_present:
        with open(digests_path, "r", encoding="utf-8") as fh:
            digests = parse_digests_file(fh.read())

    cases_by_bucket = discover_fixtures(corpus_root)

    total = 0
    failures: list[dict] = []
    discovered_variants: set[str] = set()
    for bucket in BUCKETS:
        for case in cases_by_bucket.get(bucket, []):
            discovered_variants.update(case["variants"])
            total += 1
            messages = run_case(
                corpus_root,
                bucket,
                case,
                digests,
                enforce_digests=manifest_present,
            )
            if messages:
                failures.append(
                    {"file": case["base"], "messages": messages}
                )

    # The orphan-digest sweep is a single corpus-level assertion that
    # only runs when a manifest is present.  Count it in ``total`` so
    # the ``passed + failed == total`` invariant holds (without this
    # bump, an orphan failure could push ``passed`` negative when the
    # rest of the corpus is clean).
    if manifest_present:
        total += 1
        orphan_digests = sorted(set(digests) - discovered_variants)
        if orphan_digests:
            failures.append(
                {
                    "file": "digests.txt",
                    "messages": [
                        f"orphan digest entry: {path}"
                        for path in orphan_digests
                    ],
                }
            )

    failures.sort(key=lambda f: f["file"])
    return {
        "total": total,
        "passed": total - len(failures),
        "failed": len(failures),
        "failures": failures,
    }
