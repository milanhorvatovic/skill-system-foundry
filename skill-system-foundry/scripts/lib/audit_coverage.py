"""Audit-level corpus-coverage rules for ``audit_skill_system.py``.

The description-quality runner (``evaluate_descriptions.py``) validates each
corpus *when it is loaded*.  These rules add the orthogonal, audit-time
question: does every discoverable unit *have* a corpus, is each corpus *fresh*
relative to the description it tests, are a skill's capability corpora
*consistent* with one another, and is each corpus *large enough* once committed?

Five rules, mirroring the orphan-references rule's allow-list philosophy:

1. **Missing corpus** (WARN) — a discoverable unit with no corpus file and no
   ``allowed_missing_corpus`` opt-out.
2. **Stale allow-list entry** (INFO) — an ``allowed_missing_corpus`` entry that
   matches no discovered unit, so the list cannot rot silently.
3. **Corpus freshness** (WARN) — a corpus whose ``description_sha256`` no longer
   matches the SHA-256 of the live unit description.
4. **Sibling parity** (WARN) — within one skill, some capabilities have corpora
   and others (not opted out) do not.
5. **Corpus-size escalation** (FAIL) — a committed corpus with fewer than
   ``EVAL_RECOMMENDED_PROMPTS`` prompts on its smaller side, escalating the
   runner's Tier B WARN to a hard FAIL.  (Below ``EVAL_MIN_PROMPTS`` the corpus
   fails to load at all; that load FAIL is surfaced here too.)

Discovery and the corpus root: units come from
:func:`lib.description_eval.discover_units` (which finds a skill at the audit
root or as an immediate subdirectory and resolves capability descriptions from
their body), *not* from the audit's ``find_skill_dirs``.  The corpus root is
resolved relative to the audit root via :func:`resolve_corpus_root`; every rule
self-skips when it is absent, so ``cd skill && audit .`` (no corpus under the
skill) stays quiet while the repo-root audit — where ``tests/skill-corpus``
resolves — runs the rules.

Library contract: no ``print()`` / ``sys.exit()`` here.  Each function returns a
list of ``"SEVERITY: [foundry] message"`` strings the entry point appends to its
finding stream.
"""

import os

from .constants import (
    EVAL_COVERAGE_ALLOWED_MISSING,
    EVAL_COVERAGE_CORPUS_ROOT,
    EVAL_COVERAGE_FRESHNESS_ENABLED,
    EVAL_RECOMMENDED_PROMPTS,
    LEVEL_FAIL,
    LEVEL_INFO,
    LEVEL_WARN,
)
from .description_eval import (
    KIND_CAPABILITY,
    Corpus,
    Unit,
    compute_description_sha256,
    discover_units,
    load_corpus,
)

# Corpus file names by unit kind (skill -> skill.json at the skill's root;
# capability -> capabilities/<cap>.json sibling), matching the layout the
# eval runner ships and the backfill writes.
SKILL_CORPUS_FILENAME = "skill.json"

# A unit's coverage status against the corpus root, as classified by
# :func:`_classify_coverage`.  These are internal structural constants (not
# validation rules), so they live in Python rather than configuration.yaml.
_COVERAGE_PRESENT = "present"  # corpus file present and effective (or unloadable)
_COVERAGE_ABSENT = "absent"  # no corpus file at the expected path
_COVERAGE_MISMATCH = "mismatch"  # file present but its target/kind names another unit
_COVERAGE_UNSAFE = "unsafe"  # unit name/parent would escape the corpus root

# Each present corpus is loaded once into this cache (keyed by unit) and shared
# across every rule, so an audit pass reads each corpus file at most once.
LoadedCorpora = dict[Unit, tuple[Corpus | None, list[str]]]


# ===================================================================
# Identity + path helpers
# ===================================================================


def unit_qualified_name(unit: Unit) -> str:
    """Return the allow-list key for *unit*.

    Skills are keyed by name; capabilities by ``<skill>/capabilities/<cap>`` so
    a capability name that collides with a sibling skill name stays distinct.
    """
    if unit.kind == KIND_CAPABILITY:
        return f"{unit.parent}/capabilities/{unit.name}"
    return unit.name


def expected_corpus_relpath(unit: Unit) -> str:
    """Return *unit*'s corpus path relative to the corpus root (POSIX form)."""
    if unit.kind == KIND_CAPABILITY:
        return f"{unit.parent}/capabilities/{unit.name}.json"
    return f"{unit.name}/{SKILL_CORPUS_FILENAME}"


def _corpus_abspath(corpus_root: str, unit: Unit) -> str:
    """Absolute filesystem path to *unit*'s corpus under *corpus_root*."""
    return os.path.join(corpus_root, *expected_corpus_relpath(unit).split("/"))


def resolve_corpus_root(system_root: str) -> str:
    """Return the absolute corpus root for an audit rooted at *system_root*."""
    return os.path.join(
        os.path.abspath(system_root), *EVAL_COVERAGE_CORPUS_ROOT.split("/")
    )


def _has_safe_corpus_identity(unit: Unit) -> bool:
    """True when *unit*'s name (and parent) cannot escape the corpus root.

    A unit's ``name`` — and a capability's ``parent`` — come straight from
    untrusted ``SKILL.md`` frontmatter.  A value containing a path separator or
    a bare ``..`` segment would interpolate into the corpus path and let the
    audit probe (or read) files outside the corpus tree, so it is rejected
    before any path is built.  Mirrors the guard ``constants.py`` applies to
    ``corpus_root_relative``.
    """
    parts: list[str] = [unit.name]
    if unit.kind == KIND_CAPABILITY and unit.parent is not None:
        parts.append(unit.parent)
    for value in parts:
        if not value or "/" in value or "\\" in value or value == "..":
            return False
    return True


def load_present_corpora(units: list[Unit], corpus_root: str) -> LoadedCorpora:
    """Load every present corpus once, keyed by unit.

    A unit earns an entry only when its identity is safe (see
    :func:`_has_safe_corpus_identity`) and a file exists at its expected path;
    the entry is the full ``load_corpus`` result so freshness, size, missing,
    and parity all consume one read per file.  Units that are unsafe or absent
    are simply missing from the map.
    """
    loaded: LoadedCorpora = {}
    for unit in units:
        if not _has_safe_corpus_identity(unit):
            continue
        path = _corpus_abspath(corpus_root, unit)
        if not os.path.isfile(path):
            continue
        loaded[unit] = load_corpus(path)
    return loaded


def _classify_coverage(
    unit: Unit, loaded: LoadedCorpora,
) -> tuple[str, Corpus | None]:
    """Classify *unit*'s coverage from the shared *loaded* cache.

    Returns ``(status, corpus)`` where *status* is one of the ``_COVERAGE_*``
    constants and *corpus* is the loaded corpus when one was parsed (used by the
    missing-corpus rule to name the mis-targeted unit).  A file that exists but
    fails to load counts as ``_COVERAGE_PRESENT`` — the size rule surfaces its
    load FAIL, so the missing rule must not double-report it.
    """
    if not _has_safe_corpus_identity(unit):
        return _COVERAGE_UNSAFE, None
    result = loaded.get(unit)
    if result is None:
        return _COVERAGE_ABSENT, None
    corpus, _findings = result
    if corpus is None:
        return _COVERAGE_PRESENT, None
    if corpus.target == unit.name and corpus.kind == unit.kind:
        return _COVERAGE_PRESENT, corpus
    return _COVERAGE_MISMATCH, corpus


# ===================================================================
# Rule 1 — Missing corpus (WARN)
# ===================================================================


def find_missing_corpora(
    units: list[Unit],
    allowed_missing: tuple[str, ...] | list[str],
    loaded: LoadedCorpora,
) -> list[str]:
    """WARN for every unit with no *effective* corpus that is not opted out.

    A corpus only counts as coverage when it exists at the expected path *and*
    its ``target``/``kind`` name this unit: a file copied from — or misnamed
    after — another unit (``_COVERAGE_MISMATCH``) leaves this unit effectively
    uncovered while the evaluator just re-scores the duplicate target.  An
    unsafe unit name is surfaced regardless of the allow-list because it can
    never map to a valid corpus path.
    """
    allowed = set(allowed_missing)
    findings: list[str] = []
    for unit in units:
        qual = unit_qualified_name(unit)
        status, corpus = _classify_coverage(unit, loaded)
        if status == _COVERAGE_UNSAFE:
            findings.append(
                f"{LEVEL_WARN}: [foundry] {qual} has a name with a path "
                f"separator or '..' segment — refusing to map it to a corpus "
                f"path (it could escape {EVAL_COVERAGE_CORPUS_ROOT}); rename "
                f"the unit"
            )
            continue
        if qual in allowed:
            continue
        if status == _COVERAGE_PRESENT:
            continue
        if status == _COVERAGE_MISMATCH and corpus is not None:
            findings.append(
                f"{LEVEL_WARN}: [foundry] {qual} has no corpus — the file at "
                f"{EVAL_COVERAGE_CORPUS_ROOT}/{expected_corpus_relpath(unit)} "
                f"targets a different unit ('{corpus.target}' / {corpus.kind}); "
                f"replace it with a corpus for '{qual}'"
            )
            continue
        findings.append(
            f"{LEVEL_WARN}: [foundry] {qual} has no corpus at "
            f"{EVAL_COVERAGE_CORPUS_ROOT}/{expected_corpus_relpath(unit)} — "
            f"add one, or list '{qual}' under "
            f"skill.description.evaluation.coverage.allowed_missing_corpus"
        )
    return findings


# ===================================================================
# Rule 2 — Stale allow-list entry (INFO)
# ===================================================================


def find_stale_allowed_missing(
    units: list[Unit], allowed_missing: tuple[str, ...] | list[str],
) -> list[str]:
    """INFO for every allow-list entry matching no discovered unit."""
    known = {unit_qualified_name(unit) for unit in units}
    findings: list[str] = []
    for entry in allowed_missing:
        if entry not in known:
            findings.append(
                f"{LEVEL_INFO}: [foundry] coverage.allowed_missing_corpus entry "
                f"'{entry}' matches no discovered unit — remove it from "
                f"configuration.yaml or update the name"
            )
    return findings


# ===================================================================
# Rule 3 — Corpus freshness (WARN)
# ===================================================================


def find_stale_corpora(units: list[Unit], loaded: LoadedCorpora) -> list[str]:
    """WARN for every corpus whose recorded hash no longer matches the live
    description.  Corpora that are absent, fail to load, carry no hash, or
    target a different unit are silently skipped — the freshness rule only
    speaks to corpora that effectively cover the unit and opted in by recording
    a hash via ``--backfill-hash`` (a mis-targeted file is flagged by the
    missing-corpus rule instead, so comparing its hash here would be noise).
    """
    findings: list[str] = []
    for unit in units:
        status, corpus = _classify_coverage(unit, loaded)
        if status != _COVERAGE_PRESENT or corpus is None:
            continue
        if corpus.description_sha256 is None:
            continue
        live = compute_description_sha256(unit.description)
        if live != corpus.description_sha256:
            findings.append(
                f"{LEVEL_WARN}: [foundry] {unit_qualified_name(unit)} corpus "
                f"description_sha256 is stale — the live description changed; "
                f"refresh with 'evaluate_descriptions.py "
                f"{EVAL_COVERAGE_CORPUS_ROOT}/... --backfill-hash' "
                f"({expected_corpus_relpath(unit)})"
            )
    return findings


# ===================================================================
# Rule 4 — Sibling parity (WARN)
# ===================================================================


def find_sibling_parity_violations(
    units: list[Unit],
    allowed_missing: tuple[str, ...] | list[str],
    loaded: LoadedCorpora,
) -> list[str]:
    """WARN per skill that covers some — but not all — of its capabilities.

    A capability is *covered* when it has an effective corpus (present and
    targeting the capability), *exempt* when it is allow-listed, and neutral
    when its name is unsafe (the missing-corpus rule surfaces that separately).
    A present-but-mis-targeted file is not effective coverage, so it counts
    toward the missing side.  The rule fires only on the genuinely mixed case:
    at least one covered capability and at least one uncovered, non-exempt
    capability under the same skill.
    """
    allowed = set(allowed_missing)
    findings: list[str] = []
    caps_by_parent: dict[str, list[Unit]] = {}
    for unit in units:
        if unit.kind == KIND_CAPABILITY and unit.parent is not None:
            caps_by_parent.setdefault(unit.parent, []).append(unit)

    for parent in sorted(caps_by_parent):
        caps = caps_by_parent[parent]
        covered = 0
        missing = 0
        for cap in caps:
            status, _corpus = _classify_coverage(cap, loaded)
            if status == _COVERAGE_UNSAFE:
                continue
            if status == _COVERAGE_PRESENT:
                covered += 1
            elif unit_qualified_name(cap) not in allowed:
                missing += 1
        if covered and missing:
            findings.append(
                f"{LEVEL_WARN}: [foundry] {parent} has {covered} of "
                f"{covered + missing} capability corpora — cover all of them or "
                f"none (sibling parity); allow-list the intentional gaps"
            )
    return findings


# ===================================================================
# Rule 5 — Corpus-size escalation (FAIL)
# ===================================================================


def find_undersized_corpora(
    units: list[Unit], loaded: LoadedCorpora, size_floor: int,
) -> list[str]:
    """FAIL for every committed corpus below *size_floor* on its smaller side.

    This rule surfaces the load-time FAILs (malformed JSON, fewer than
    ``EVAL_MIN_PROMPTS`` prompts) cached for each present corpus, keeping a
    structurally broken committed corpus from passing the audit silently.
    """
    findings: list[str] = []
    for unit in units:
        result = loaded.get(unit)
        if result is None:
            continue
        corpus, load_findings = result
        # Surface load-time FAILs before the None check.  load_corpus returns
        # None whenever it emits a FAIL today, but forwarding regardless keeps
        # a structurally broken committed corpus from passing the audit if that
        # contract ever changes.
        findings.extend(f for f in load_findings if f.startswith(LEVEL_FAIL))
        if corpus is None:
            continue
        smaller = min(len(corpus.positive), len(corpus.negative))
        if smaller < size_floor:
            findings.append(
                f"{LEVEL_FAIL}: [foundry] {unit_qualified_name(unit)} corpus has "
                f"{smaller} prompts on its smaller side (min {size_floor} once "
                f"committed) — expand it ({expected_corpus_relpath(unit)})"
            )
    return findings


# ===================================================================
# Orchestrator
# ===================================================================


def audit_corpus_coverage(
    system_root: str,
    *,
    allowed_missing: tuple[str, ...] | list[str] = EVAL_COVERAGE_ALLOWED_MISSING,
    freshness_enabled: bool = EVAL_COVERAGE_FRESHNESS_ENABLED,
    size_floor: int = EVAL_RECOMMENDED_PROMPTS,
) -> list[str]:
    """Run all corpus-coverage rules for an audit rooted at *system_root*.

    Returns an empty list — silently — when the corpus root is absent (so the
    skill-root self-check stays quiet) or no units are discoverable.  Otherwise
    aggregates rules 1, 2, 4, 5 and (when *freshness_enabled*) rule 3.  Corpora
    below ``EVAL_MIN_PROMPTS`` fail to load; that load FAIL is surfaced by the
    size rule rather than gated by a separate parameter here.
    """
    corpus_root = resolve_corpus_root(system_root)
    if not os.path.isdir(corpus_root):
        return []
    units = discover_units(system_root)
    if not units:
        return []

    # Read each present corpus exactly once; every rule consumes this cache.
    loaded = load_present_corpora(units, corpus_root)

    findings: list[str] = []
    findings.extend(find_missing_corpora(units, allowed_missing, loaded))
    findings.extend(find_stale_allowed_missing(units, allowed_missing))
    findings.extend(
        find_sibling_parity_violations(units, allowed_missing, loaded)
    )
    findings.extend(find_undersized_corpora(units, loaded, size_floor))
    if freshness_enabled:
        findings.extend(find_stale_corpora(units, loaded))
    return findings
