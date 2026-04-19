"""Shared helpers for the YAML 1.2.2 conformance corpus harness.

Two consumers (extracted upfront per G66/G76):

- ``tests/test_yaml_conformance.py`` — runs the full corpus as part of
  the unittest suite and surfaces failures via ``self.fail(...)``.
- ``skill-system-foundry/scripts/yaml_conformance_report.py`` — emits
  the same shape as JSON for tooling consumers that don't run tests.

This module is pure data — no test framework dependencies — so callers
control how failures surface.

Package layout note (deviation from G76)
----------------------------------------
``tests/lib/`` is intentionally **not** a Python package — there is no
``__init__.py``.  Adding one would shadow ``skill-system-foundry/
scripts/lib`` (the canonical ``lib`` package every test imports from
via sys.path injection), breaking the entire suite.  Consumers import
this module by adding ``tests/lib`` to ``sys.path`` instead of using
``from tests.lib.yaml_conformance_runner import ...``.

Sorted iteration (G72): ``os.walk`` is wrapped to sort directory and
filename order, ensuring byte-identical output across platforms with
different filesystem ordering.

Digest manifest format (G40): ``digests.txt`` follows the standard
``sha256sum`` shape (``<hex-digest>  <relative-path>``).  Lines split
on the first run of whitespace; the right half is the path verbatim
so paths with embedded ``=`` etc. survive.  Whitespace-in-paths is
forbidden by curation convention (G132) so the simple split is
unambiguous.
"""

import hashlib
import json
import os
import sys

VARIANT_SUFFIXES = (".lf.yaml", ".crlf.yaml", ".mixed.yaml")
BUCKETS = ("supported", "divergent", "rejected")
_EXPECTED_SUFFIX = ".expected.json"
_META_SUFFIX = ".meta.json"

# Surface ``parse_yaml_subset`` to module callers without forcing them to
# manage sys.path.  The runner lives in tests/lib/, the parser lives in
# skill-system-foundry/scripts/lib/.
_SCRIPTS_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..",
        "skill-system-foundry", "scripts",
    )
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from lib.yaml_parser import parse_yaml_subset  # noqa: E402


def parse_digests_file(text: str) -> dict[str, str]:
    """Parse ``digests.txt`` text into a ``{path: hex-digest}`` dict.

    Splits each non-empty line on the first run of whitespace.  Raises
    ``ValueError`` when a line lacks two whitespace-separated fields.
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


def _walk_sorted(root: str):
    """``os.walk`` with sorted dirnames + filenames at every level (G72)."""
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

    Raises ``ValueError`` for unknown top-level directories (G100) and
    for orphan sidecars with no matching fixture (G55).
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
    """Confirm every variant of a base parses to the same dict (G122)."""
    if len(variant_texts) <= 1:
        return []
    parsed_dicts = [parse_yaml_subset(t, []) for t in variant_texts]
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
        with open(
            os.path.join(corpus_root, case["meta"]),
            "r",
            encoding="utf-8",
        ) as fh:
            json.load(fh)
    except json.JSONDecodeError as exc:
        msgs.append(
            f"sidecar parse error: {case['expected']} — {exc}"
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

    digest_failures: set[str] = set()
    for variant_rel in case["variants"]:
        variant_path = os.path.join(corpus_root, variant_rel)
        if variant_rel in digests:
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
    """Run the full corpus and return summary dict (G127 shape)."""
    digests: dict[str, str] = {}
    digests_path = os.path.join(corpus_root, "digests.txt")
    if os.path.isfile(digests_path):
        with open(digests_path, "r", encoding="utf-8") as fh:
            digests = parse_digests_file(fh.read())

    cases_by_bucket = discover_fixtures(corpus_root)

    total = 0
    failures: list[dict] = []
    for bucket in BUCKETS:
        for case in cases_by_bucket.get(bucket, []):
            total += 1
            messages = run_case(corpus_root, bucket, case, digests)
            if messages:
                failures.append(
                    {"file": case["base"], "messages": messages}
                )
    failures.sort(key=lambda f: f["file"])
    return {
        "total": total,
        "passed": total - len(failures),
        "failed": len(failures),
        "failures": failures,
    }
