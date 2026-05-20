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
    KIND_SKILL,
    Unit,
    compute_description_sha256,
    discover_units,
    load_corpus,
)
from .reporting import to_posix

# Corpus file names by unit kind (skill -> skill.json at the skill's root;
# capability -> capabilities/<cap>.json sibling), matching the layout the
# eval runner ships and the backfill writes.
SKILL_CORPUS_FILENAME = "skill.json"


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


# ===================================================================
# Rule 1 — Missing corpus (WARN)
# ===================================================================


def find_missing_corpora(
    units: list[Unit], corpus_root: str, allowed_missing: tuple[str, ...] | list[str],
) -> list[str]:
    """WARN for every unit with no corpus file that is not opted out."""
    allowed = set(allowed_missing)
    findings: list[str] = []
    for unit in units:
        qual = unit_qualified_name(unit)
        if qual in allowed:
            continue
        if os.path.isfile(_corpus_abspath(corpus_root, unit)):
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


def find_stale_corpora(units: list[Unit], corpus_root: str) -> list[str]:
    """WARN for every corpus whose recorded hash no longer matches the live
    description.  Corpora that are absent, fail to load, or carry no hash are
    silently skipped — the freshness rule only speaks to corpora that opted in
    by recording a hash via ``--backfill-hash``.
    """
    findings: list[str] = []
    for unit in units:
        path = _corpus_abspath(corpus_root, unit)
        if not os.path.isfile(path):
            continue
        corpus, _load_findings = load_corpus(path)
        if corpus is None or corpus.description_sha256 is None:
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
    units: list[Unit], corpus_root: str, allowed_missing: tuple[str, ...] | list[str],
) -> list[str]:
    """WARN per skill that covers some — but not all — of its capabilities.

    A capability is *covered* when its corpus file exists and *exempt* when it
    is allow-listed; an exempt capability is neutral.  The rule fires only on
    the genuinely mixed case: at least one covered capability and at least one
    uncovered, non-exempt capability under the same skill.
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
            if os.path.isfile(_corpus_abspath(corpus_root, cap)):
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
    units: list[Unit], corpus_root: str, size_floor: int,
) -> list[str]:
    """FAIL for every committed corpus below *size_floor* on its smaller side.

    This rule owns reading each corpus's content, so it also surfaces the
    load-time FAILs (malformed JSON, fewer than ``EVAL_MIN_PROMPTS`` prompts)
    that prevent a corpus from loading at all — keeping a structurally broken
    committed corpus from passing the audit silently.
    """
    findings: list[str] = []
    for unit in units:
        path = _corpus_abspath(corpus_root, unit)
        if not os.path.isfile(path):
            continue
        corpus, load_findings = load_corpus(path)
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

    findings: list[str] = []
    findings.extend(find_missing_corpora(units, corpus_root, allowed_missing))
    findings.extend(find_stale_allowed_missing(units, allowed_missing))
    findings.extend(
        find_sibling_parity_violations(units, corpus_root, allowed_missing)
    )
    findings.extend(find_undersized_corpora(units, corpus_root, size_floor))
    if freshness_enabled:
        findings.extend(find_stale_corpora(units, corpus_root))
    return findings
