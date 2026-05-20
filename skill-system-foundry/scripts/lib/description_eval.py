"""Description-quality evaluation: heuristic and opt-in LLM activation accuracy.

This module measures whether a skill's (or capability's) ``name + description``
card causes the right activations on a corpus of positive prompts (should
activate the unit) and negative prompts (should not).  It powers the
``evaluate_descriptions.py`` entry point.

Two modes
---------
* **heuristic** (default, pure stdlib, deterministic): Jaccard token overlap
  between each prompt and every candidate card; the highest-overlap candidate
  is selected, or ``none`` when the best overlap is below
  ``EVAL_HEURISTIC_MIN_OVERLAP``.  Free, fast, runnable in CI on every PR.
* **llm** (opt-in, ``urllib`` only): a classifier prompt asks a configured
  provider to pick the single most relevant unit (or ``none``) from the same
  candidate cards.  Each query runs ``runs`` times to produce a trigger rate.

Unit card model
---------------
Every discoverable unit is reduced to a ``name + description`` card.  Skills
expose both in ``SKILL.md`` frontmatter.  Capabilities carry only
``allowed-tools`` in frontmatter, so a capability's name is its directory name
and its description is the first body paragraph after the ``# Heading`` line in
``capability.md``.  Both modes consume this identical card — neither reads the
full body, so there is no information asymmetry between them.

Scoring semantics
-----------------
For a target unit ``T`` each prompt's prediction is the single selected unit or
``None`` (``"none"``):

* positive prompt -> ``TP`` if prediction == ``T`` else ``FN``.
* negative prompt -> ``FP`` if prediction == ``T`` else ``TN`` (selecting
  ``None`` *or* a different unit both count as correctly rejecting ``T``).

``precision = TP / (TP + FP)`` and ``recall = TP / (TP + FN)``; each defaults to
``1.0`` when its denominator is ``0``.  The threshold gate compares these point
estimates.

Advisory statistics
-------------------
Bootstrap confidence intervals, per-query variance flags, and pairwise
confusion are computed for reporting only — they are emitted in the JSON
payload but never affect exit status, because corpora of 8-10 prompts make them
unreliable as pass/fail signals.

Library contract
----------------
No ``print()`` or ``sys.exit()`` here — the entry point owns all output via
``lib/reporting.py``.  Validation surfaces (corpus loading) return
``(value, findings)`` where each finding is a ``"SEVERITY: [tag] body"`` string.
"""

import json
import os
from dataclasses import dataclass, field

from .constants import (
    EVAL_DIVERSITY_RATIO,
    EVAL_MAX_PROMPT_CHARS,
    LEVEL_FAIL,
    LEVEL_WARN,
)

# --- structural constants ---------------------------------------------------

KIND_SKILL = "skill"
KIND_CAPABILITY = "capability"
LABEL_POSITIVE = "positive"
LABEL_NEGATIVE = "negative"
PREDICTION_NONE = "none"  # the LLM's literal "no unit fits" answer

MODE_HEURISTIC = "heuristic"
MODE_LLM = "llm"

# Top-level corpus keys.  Required keys plus the optional metadata keys the
# schema validator tolerates; any other top-level key (except ``_*``) is a FAIL.
CORPUS_REQUIRED_KEYS = ("target", "kind", "positive", "negative")
CORPUS_OPTIONAL_KEYS = ("description_sha256", "min_precision", "min_recall")


# --- data model -------------------------------------------------------------


@dataclass(frozen=True)
class Unit:
    """A discoverable skill or capability reduced to its discovery card."""

    name: str
    kind: str  # KIND_SKILL | KIND_CAPABILITY
    description: str
    path: str  # absolute path to SKILL.md or capability.md

    @property
    def card_text(self) -> str:
        """The ``name + description`` text both modes score against."""
        return f"{self.name} {self.description}".strip()


@dataclass(frozen=True)
class Corpus:
    """A parsed, schema-valid corpus for one target unit."""

    target: str
    kind: str
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    min_precision: float | None
    min_recall: float | None
    source_path: str


@dataclass(frozen=True)
class ScoredQuery:
    """The outcome of scoring one prompt against the candidate set."""

    prompt: str
    label: str  # LABEL_POSITIVE | LABEL_NEGATIVE
    prediction: str | None  # selected unit name, or None for "none"
    trigger_rate: float | None  # LLM mode only; None in heuristic mode
    runs: int


@dataclass(frozen=True)
class Metrics:
    """Point-estimate confusion matrix and derived precision/recall."""

    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    passed: bool


@dataclass
class TargetResult:
    """Per-target evaluation result, including advisory statistics."""

    target: str
    kind: str
    candidate_count: int
    metrics: Metrics
    scored: tuple[ScoredQuery, ...]
    validation_metrics: Metrics | None = None
    advisory: dict = field(default_factory=dict)


@dataclass
class EvalReport:
    """The full evaluation outcome consumed by the entry point's formatter."""

    mode: str
    provider: str | None
    model: str | None
    min_precision: float
    min_recall: float
    split: dict | None
    targets: list[TargetResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True when every target cleared its gate (ignores ``--soft``)."""
        return all(t.metrics.passed for t in self.targets) and not any(
            e.startswith(LEVEL_FAIL) for e in self.errors
        )


# --- corpus loading + schema validation (step 4) ----------------------------


def _has_control_chars(text: str) -> bool:
    """True when *text* holds a C0/C1 control character (space excluded)."""
    return any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 for c in text)


def _check_prompt_rules(
    positive: list[str], negative: list[str],
    fail, warn,
) -> None:
    """Apply the prompt-level corpus-shape rules (4-8, 10-12).

    *fail* / *warn* are the finding-appending closures from
    :func:`load_corpus`.  Rule 9 is cross-target and lives in
    :func:`check_cross_target_overlap`.
    """
    sides = ((LABEL_POSITIVE, positive), (LABEL_NEGATIVE, negative))

    # Rules 7, 11, 12 — per-prompt hygiene.
    for label, prompts in sides:
        for prompt in prompts:
            if not prompt.strip():
                fail(f"empty or whitespace-only prompt in '{label}'")
                continue
            if len(prompt) > EVAL_MAX_PROMPT_CHARS:
                fail(
                    f"prompt in '{label}' exceeds {EVAL_MAX_PROMPT_CHARS} "
                    f"characters ({len(prompt)})"
                )
            if _has_control_chars(prompt):
                fail(
                    f"prompt in '{label}' contains control / non-printable "
                    f"characters: {prompt!r}"
                )

    # Rules 4, 5 — per-side counts.
    for label, prompts in sides:
        count = len(prompts)
        if count < 4:
            fail(f"'{label}' has {count} prompts; at least 4 are required")
        elif count <= 7:
            warn(f"'{label}' has {count} prompts; 8-10 are recommended")

    # Rule 6 — duplicate prompts within a side.
    for label, prompts in sides:
        seen: set[str] = set()
        dupes: set[str] = set()
        for prompt in prompts:
            key = prompt.strip()
            if key in seen:
                dupes.add(key)
            seen.add(key)
        for dupe in sorted(dupes):
            fail(f"duplicate prompt in '{label}': {dupe!r}")

    # Rule 8 — same prompt on both sides (self-contradiction).
    both = {p.strip() for p in positive} & {p.strip() for p in negative}
    for prompt in sorted(both):
        fail(f"prompt appears in both 'positive' and 'negative': {prompt!r}")

    # Rule 10 — phrasing diversity by leading bigram.
    non_empty = [p for p in (*positive, *negative) if p.strip()]
    if non_empty:
        leading_bigrams = {" ".join(p.lower().split()[:2]) for p in non_empty}
        ratio = len(leading_bigrams) / len(non_empty)
        if ratio < EVAL_DIVERSITY_RATIO:
            warn(
                f"phrasing diversity {ratio:.2f} is below "
                f"{EVAL_DIVERSITY_RATIO:.2f} — many prompts share a leading "
                "bigram"
            )


def load_corpus(path: str) -> tuple[Corpus | None, list[str]]:
    """Load and schema-validate one corpus JSON file.

    Returns ``(corpus, findings)``.  ``corpus`` is ``None`` when any FAIL-level
    rule fired (the corpus cannot be scored safely); ``findings`` carries every
    ``"SEVERITY: [tag] body"`` string from the per-file corpus-shape rules
    (1-8, 10-12).  Rule 9 is cross-target — see
    :func:`check_cross_target_overlap`.
    """
    findings: list[str] = []
    label = os.path.basename(path)

    def fail(message: str) -> None:
        findings.append(f"{LEVEL_FAIL}: [foundry] {label}: {message}")

    def warn(message: str) -> None:
        findings.append(f"{LEVEL_WARN}: [foundry] {label}: {message}")

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        fail(f"cannot read corpus file ({exc.__class__.__name__})")
        return None, findings
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        fail(f"invalid JSON ({exc.__class__.__name__}: {exc})")
        return None, findings
    if not isinstance(data, dict):
        fail("top-level JSON value must be an object")
        return None, findings

    # Rule 3 — unknown top-level keys (``_*`` and the optional metadata keys
    # are tolerated).
    allowed_keys = set(CORPUS_REQUIRED_KEYS) | set(CORPUS_OPTIONAL_KEYS)
    for key in data:
        if not key.startswith("_") and key not in allowed_keys:
            fail(f"unknown top-level key '{key}'")

    # Rule 1 — required keys present.
    for key in CORPUS_REQUIRED_KEYS:
        if key not in data:
            fail(f"missing required key '{key}'")

    # Rule 2 — types.
    target = data.get("target")
    kind = data.get("kind")
    if "target" in data and not (isinstance(target, str) and target.strip()):
        fail("'target' must be a non-empty string")
    if "kind" in data and kind not in (KIND_SKILL, KIND_CAPABILITY):
        fail(f"'kind' must be '{KIND_SKILL}' or '{KIND_CAPABILITY}'")

    def string_list(key: str) -> list[str] | None:
        value = data.get(key)
        if not isinstance(value, list):
            fail(f"'{key}' must be a list of strings")
            return None
        for item in value:
            if not isinstance(item, str):
                fail(f"'{key}' must contain only strings")
                return None
        return value

    positive = string_list("positive") if "positive" in data else None
    negative = string_list("negative") if "negative" in data else None

    def optional_threshold(key: str) -> float | None:
        if key not in data or data[key] is None:
            return None
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail(f"'{key}' must be a number between 0 and 1")
            return None
        as_float = float(value)
        if not 0.0 <= as_float <= 1.0:
            fail(f"'{key}' must be between 0 and 1")
            return None
        return as_float

    min_precision = optional_threshold("min_precision")
    min_recall = optional_threshold("min_recall")

    # Prompt-level rules need both sides as well-formed string lists.
    if positive is not None and negative is not None:
        _check_prompt_rules(positive, negative, fail, warn)

    if any(f.startswith(LEVEL_FAIL) for f in findings):
        return None, findings

    corpus = Corpus(
        target=target,
        kind=kind,
        positive=tuple(positive or ()),
        negative=tuple(negative or ()),
        min_precision=min_precision,
        min_recall=min_recall,
        source_path=os.path.abspath(path),
    )
    return corpus, findings


def check_cross_target_overlap(corpora: list[Corpus]) -> list[str]:
    """Rule 9 — flag a positive prompt shared across sibling targets.

    A prompt used as a positive for more than one target is a boundary
    ambiguity (WARN): both descriptions claim it.  Cross-target by nature, so
    it runs over the full corpus set rather than inside :func:`load_corpus`.
    """
    findings: list[str] = []
    targets_by_prompt: dict[str, list[str]] = {}
    for corpus in corpora:
        for prompt in corpus.positive:
            key = prompt.strip()
            bucket = targets_by_prompt.setdefault(key, [])
            if corpus.target not in bucket:
                bucket.append(corpus.target)
    for prompt, targets in sorted(targets_by_prompt.items()):
        if len(targets) > 1:
            findings.append(
                f"{LEVEL_WARN}: [foundry] positive prompt shared across "
                f"targets {sorted(targets)}: {prompt!r}"
            )
    return findings


# --- unit discovery + card extraction (step 5) ------------------------------


def discover_units(skill_set_dir: str) -> list[Unit]:
    """Discover candidate units under *skill_set_dir*.

    Accepts both the skill-root layout (``<dir>/SKILL.md`` plus
    ``<dir>/capabilities/*/capability.md``) and the deployed layout
    (``<dir>/<name>/SKILL.md`` plus ``<dir>/<name>/capabilities/*/...``).
    """
    raise NotImplementedError


def extract_capability_card(capability_md_path: str, dir_name: str) -> tuple[str, str]:
    """Return ``(name, description)`` for a capability.

    Name is *dir_name*; description is the first non-empty body paragraph after
    the ``# Heading`` line in *capability_md_path* (empty when none exists).
    """
    raise NotImplementedError


# --- heuristic scoring (step 6) ---------------------------------------------


def tokenize(text: str) -> set[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords -> token set."""
    raise NotImplementedError


def score_heuristic(prompt: str, candidates: list[Unit]) -> str | None:
    """Predict the unit name with the highest Jaccard overlap, or ``None``.

    Ties break deterministically by candidate name.  Returns ``None`` when the
    best overlap is below ``EVAL_HEURISTIC_MIN_OVERLAP``.
    """
    raise NotImplementedError


# --- deterministic split (step 7) -------------------------------------------


def split_train_validation(
    corpus: Corpus, ratio: float, seed: int,
) -> tuple[Corpus, Corpus]:
    """Stratified, deterministic train/validation split keyed by *seed*."""
    raise NotImplementedError


# --- metrics aggregation (step 8) -------------------------------------------


def aggregate(
    scored: list[ScoredQuery], target: str,
    min_precision: float, min_recall: float,
) -> Metrics:
    """Build the confusion matrix and derive precision/recall + pass verdict."""
    raise NotImplementedError


# --- LLM client + scorer (steps 9-10) ---------------------------------------


def build_classifier_prompt(prompt: str, candidates: list[Unit]) -> str:
    """Render the classifier instruction listing every candidate card."""
    raise NotImplementedError


def _anthropic_messages(
    prompt: str, candidates: list[Unit], model: str,
    api_key: str, endpoint: str,
) -> str:
    """POST one classification request to the Anthropic Messages API.

    Returns the model's raw first non-blank answer line (caller maps it to a
    unit name or ``None``).  Raises a ``RuntimeError`` with an actionable
    message on HTTP / transport / decode failure.
    """
    raise NotImplementedError


def score_llm(
    prompt: str, candidates: list[Unit], runs: int,
    client_fn,
) -> tuple[str | None, float]:
    """Run *client_fn* *runs* times; return ``(prediction, trigger_rate)``.

    The prediction is the target only when its trigger rate is >= 0.5.
    *client_fn* has the signature of :func:`_anthropic_messages` bound to its
    provider settings, so this scorer stays provider-agnostic and mockable.
    """
    raise NotImplementedError


# --- advisory statistics (steps 11-13) --------------------------------------


def bootstrap_confidence_interval(
    scored: list[ScoredQuery], target: str,
    iterations: int, confidence: float,
) -> dict:
    """Resample *scored* with replacement -> CI bounds for precision/recall.

    Advisory only — never gates.  Deterministic under a fixed internal seed.
    """
    raise NotImplementedError


def flag_unstable_queries(
    scored: list[ScoredQuery], low: float, high: float,
) -> list[str]:
    """Return prompts whose LLM trigger rate falls within ``[low, high]``."""
    raise NotImplementedError


def pairwise_confusion(
    scored: list[ScoredQuery], target: str,
) -> dict[str, int]:
    """Count, per wrongly-selected unit, how often it stole *target*'s prompts."""
    raise NotImplementedError


# --- orchestrator (step 14) -------------------------------------------------


def evaluate(
    corpora: list[Corpus], candidates: list[Unit], mode: str, opts: dict,
) -> EvalReport:
    """Score every corpus against *candidates* and assemble the report.

    *opts* carries the resolved CLI options (runs, thresholds, split seed,
    provider/model, client function).  The exit-affecting gate compares point
    estimates (the validation half when a split is active); all statistical
    output is advisory.
    """
    raise NotImplementedError
