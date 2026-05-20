"""Description-quality evaluation: heuristic activation accuracy.

This module measures whether a skill's (or capability's) ``name + description``
card causes the right activations on a corpus of positive prompts (should
activate the unit) and negative prompts (should not).  It powers the
``evaluate_descriptions.py`` entry point.

Heuristic mode (pure stdlib, deterministic, free): for each prompt it computes
Jaccard token overlap against every candidate card and selects the highest, or
``none`` when the best overlap is below ``EVAL_HEURISTIC_MIN_OVERLAP``.  It is a
smoke check on description-vocabulary coverage — fast and reproducible, suitable
for running in CI on every PR.

Unit card model
---------------
Every discoverable unit is reduced to a ``name + description`` card.  Skills
expose both in ``SKILL.md`` frontmatter.  Capabilities carry only
``allowed-tools`` in frontmatter, so a capability's name is its directory name
and its description is the first body paragraph after the ``# Heading`` line in
``capability.md``.

Scoring semantics
-----------------
For a target unit ``T`` each prompt's prediction is the single selected unit or
``None``:

* positive prompt -> ``TP`` if prediction == ``T`` else ``FN``.
* negative prompt -> ``FP`` if prediction == ``T`` else ``TN`` (selecting
  ``None`` or a different unit both reject ``T``).

``precision = TP / (TP + FP)`` and ``recall = TP / (TP + FN)``; each defaults to
``1.0`` when its denominator is ``0``.  The threshold gate compares these point
estimates.  Pairwise confusion is reported in the JSON payload but never gates
exit status.

Library contract
----------------
No ``print()`` or ``sys.exit()`` here — the entry point owns all output via
``lib/reporting.py``.  Validation surfaces (corpus loading) return
``(value, findings)`` where each finding is a ``"SEVERITY: [tag] body"`` string.
"""

import json
import os
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from .constants import (
    DIR_CAPABILITIES,
    EVAL_DIVERSITY_RATIO,
    EVAL_HEURISTIC_MIN_OVERLAP,
    EVAL_MAX_PROMPT_CHARS,
    EVAL_MIN_PROMPTS,
    EVAL_RECOMMENDED_PROMPTS,
    EVAL_STOPWORDS,
    FILE_CAPABILITY_MD,
    FILE_SKILL_MD,
    LEVEL_FAIL,
    LEVEL_WARN,
)
from .frontmatter import load_frontmatter
from .reporting import format_exception, to_posix

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# --- structural constants ---------------------------------------------------

KIND_SKILL = "skill"
KIND_CAPABILITY = "capability"
LABEL_POSITIVE = "positive"
LABEL_NEGATIVE = "negative"

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
    parent: str | None = None  # owning skill name for a capability, else None

    @property
    def card_text(self) -> str:
        """The ``name + description`` text the scorer matches against."""
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
    prediction: str | None  # selected unit name, or None for no activation


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
    """Per-target evaluation result, including advisory pairwise confusion."""

    target: str
    kind: str
    candidate_count: int
    metrics: Metrics
    min_precision: float
    min_recall: float
    scored: tuple[ScoredQuery, ...]
    advisory: dict = field(default_factory=dict)


@dataclass
class EvalReport:
    """The full evaluation outcome consumed by the entry point's formatter."""

    min_precision: float
    min_recall: float
    targets: list[TargetResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True when every target cleared its threshold and no FAIL fired."""
        return all(t.metrics.passed for t in self.targets) and not any(
            e.startswith(LEVEL_FAIL) for e in self.errors
        )


# --- corpus loading + schema validation -------------------------------------


def _has_control_chars(text: str) -> bool:
    """True when *text* holds a C0/C1 control character (space excluded)."""
    return any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 for c in text)


def _check_prompt_rules(
    positive: list[str], negative: list[str],
    fail: Callable[[str], None], warn: Callable[[str], None],
) -> None:
    """Apply the prompt-level corpus-shape rules.

    *fail* / *warn* are the finding-appending closures from
    :func:`load_corpus`.  Cross-target overlap lives in
    :func:`check_cross_target_overlap`.
    """
    sides = ((LABEL_POSITIVE, positive), (LABEL_NEGATIVE, negative))

    # Per-prompt hygiene: empty, over-length, control characters.
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

    # Per-side counts (thresholds from configuration.yaml).
    for label, prompts in sides:
        count = len(prompts)
        if count < EVAL_MIN_PROMPTS:
            fail(
                f"'{label}' has {count} prompts; at least {EVAL_MIN_PROMPTS} "
                "are required"
            )
        elif count < EVAL_RECOMMENDED_PROMPTS:
            warn(
                f"'{label}' has {count} prompts; at least "
                f"{EVAL_RECOMMENDED_PROMPTS} are recommended"
            )

    # Duplicate prompts within a side.
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

    # Same prompt on both sides (self-contradiction).
    both = {p.strip() for p in positive} & {p.strip() for p in negative}
    for prompt in sorted(both):
        fail(f"prompt appears in both 'positive' and 'negative': {prompt!r}")

    # Phrasing diversity by leading bigram.
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
    rule fired; ``findings`` carries every ``"SEVERITY: [tag] body"`` string
    from the per-file corpus-shape rules.  Cross-target overlap is checked
    separately — see :func:`check_cross_target_overlap`.
    """
    findings: list[str] = []
    label = to_posix(path)

    def fail(message: str) -> None:
        findings.append(f"{LEVEL_FAIL}: [foundry] {label}: {message}")

    def warn(message: str) -> None:
        findings.append(f"{LEVEL_WARN}: [foundry] {label}: {message}")

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except (OSError, UnicodeError) as exc:
        fail(f"cannot read corpus file ({format_exception(exc)})")
        return None, findings
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        fail(f"invalid JSON ({exc.__class__.__name__}: {exc})")
        return None, findings
    if not isinstance(data, dict):
        fail("top-level JSON value must be an object")
        return None, findings

    # Unknown top-level keys (``_*`` and the optional metadata keys tolerated).
    allowed_keys = set(CORPUS_REQUIRED_KEYS) | set(CORPUS_OPTIONAL_KEYS)
    for key in data:
        if not key.startswith("_") and key not in allowed_keys:
            fail(f"unknown top-level key '{key}'")

    # Required keys present.
    for key in CORPUS_REQUIRED_KEYS:
        if key not in data:
            fail(f"missing required key '{key}'")

    # Types.
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
        non_strings = [item for item in value if not isinstance(item, str)]
        for item in non_strings:
            fail(f"'{key}' must contain only strings; got {item!r}")
        if non_strings:
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
        source_path=path,
    )
    return corpus, findings


def check_cross_target_overlap(corpora: list[Corpus]) -> list[str]:
    """Flag a positive prompt shared across competing targets.

    Targets only compete within the same kind (skills with skills, capabilities
    with capabilities), so the check is scoped by kind — a prompt that is
    legitimately positive for a skill and one of its capabilities is not an
    ambiguity.  (Per-parent scoping for capabilities would need discovery; kind
    scoping removes the common skill-vs-capability false positive.)
    """
    findings: list[str] = []
    by_kind: dict[str, list[Corpus]] = {}
    for corpus in corpora:
        by_kind.setdefault(corpus.kind, []).append(corpus)
    for kind, group in sorted(by_kind.items()):
        targets_by_prompt: dict[str, list[str]] = {}
        for corpus in group:
            for prompt in corpus.positive:
                key = prompt.strip()
                bucket = targets_by_prompt.setdefault(key, [])
                if corpus.target not in bucket:
                    bucket.append(corpus.target)
        for prompt, targets in sorted(targets_by_prompt.items()):
            if len(targets) > 1:
                findings.append(
                    f"{LEVEL_WARN}: [foundry] positive prompt shared across "
                    f"{kind} targets {sorted(targets)}: {prompt!r}"
                )
    return findings


# --- unit discovery + card extraction ---------------------------------------


def _first_paragraph_after_heading(body: str) -> str:
    """Return the first non-empty paragraph following the body's H1 heading.

    Falls back to the first non-empty paragraph of *body* when no ``# `` H1 is
    present, and to an empty string when the body has no prose at all.  A
    paragraph is the run of consecutive non-blank lines, joined with single
    spaces.
    """
    lines = body.splitlines()
    start = 0
    for index, line in enumerate(lines):
        if line.lstrip().startswith("# "):
            start = index + 1
            break
    index = start
    while index < len(lines) and not lines[index].strip():
        index += 1
    paragraph: list[str] = []
    while index < len(lines) and lines[index].strip():
        paragraph.append(lines[index].strip())
        index += 1
    return " ".join(paragraph).strip()


def _safe_load_frontmatter(path: str) -> tuple[dict, str]:
    """Load frontmatter defensively for discovery.

    Unreadable, undecodable, or YAML-parse-error files yield an empty card
    ``({}, "")`` rather than crashing the evaluator; a file without frontmatter
    yields ``({}, <full body>)``.
    """
    try:
        frontmatter, body, _findings = load_frontmatter(path)
    except (OSError, UnicodeError):
        return {}, ""
    if isinstance(frontmatter, dict) and "_parse_error" in frontmatter:
        return {}, ""
    return (frontmatter if isinstance(frontmatter, dict) else {}), (body or "")


def extract_capability_card(capability_md_path: str, dir_name: str) -> tuple[str, str]:
    """Return ``(name, description)`` for a capability.

    Name is *dir_name* (capabilities carry no frontmatter ``name``); description
    is the first non-empty body paragraph after the ``# Heading`` line in
    *capability_md_path* (empty when none exists or the file is unreadable).
    """
    _frontmatter, body = _safe_load_frontmatter(capability_md_path)
    return dir_name, _first_paragraph_after_heading(body)


def _units_for_skill(skill_dir: str) -> list[Unit]:
    """Build the skill Unit plus a Unit for each of its capabilities."""
    units: list[Unit] = []
    skill_md = os.path.join(skill_dir, FILE_SKILL_MD)
    frontmatter, _body = _safe_load_frontmatter(skill_md)
    name = str(frontmatter.get("name") or os.path.basename(skill_dir))
    description = str(frontmatter.get("description") or "")
    units.append(
        Unit(name=name, kind=KIND_SKILL, description=description, path=skill_md)
    )

    caps_dir = os.path.join(skill_dir, DIR_CAPABILITIES)
    if os.path.isdir(caps_dir):
        for entry in sorted(os.listdir(caps_dir)):
            cap_md = os.path.join(caps_dir, entry, FILE_CAPABILITY_MD)
            if os.path.isfile(cap_md):
                cap_name, cap_desc = extract_capability_card(cap_md, entry)
                units.append(
                    Unit(
                        name=cap_name, kind=KIND_CAPABILITY,
                        description=cap_desc, path=cap_md, parent=name,
                    )
                )
    return units


def discover_units(skill_set_dir: str) -> list[Unit]:
    """Discover candidate units under *skill_set_dir*.

    Accepts both the skill-root layout (``<dir>/SKILL.md`` plus
    ``<dir>/capabilities/*/capability.md``) and the deployed layout
    (``<dir>/<name>/SKILL.md`` plus ``<dir>/<name>/capabilities/*/...``).  A
    ``SKILL.md`` directly under *skill_set_dir* selects skill-root mode;
    otherwise each immediate subdirectory holding a ``SKILL.md`` is a skill.
    """
    root = os.path.abspath(skill_set_dir)
    if os.path.isfile(os.path.join(root, FILE_SKILL_MD)):
        return _units_for_skill(root)

    units: list[Unit] = []
    if not os.path.isdir(root):
        return units
    for entry in sorted(os.listdir(root)):
        sub = os.path.join(root, entry)
        if os.path.isfile(os.path.join(sub, FILE_SKILL_MD)):
            units.extend(_units_for_skill(sub))
    return units


# --- heuristic scoring ------------------------------------------------------


def tokenize(text: str) -> set[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords -> token set."""
    return {
        token for token in _TOKEN_RE.findall(text.lower())
        if token not in EVAL_STOPWORDS
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    """Jaccard overlap of two token sets; ``0.0`` when both are empty."""
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _candidate_tokens(candidates: list[Unit]) -> list[tuple[str, set[str]]]:
    """Tokenize each candidate card once, ordered by name for deterministic ties."""
    return [
        (unit.name, tokenize(unit.card_text))
        for unit in sorted(candidates, key=lambda unit: unit.name)
    ]


def _score_prompt(
    prompt_tokens: set[str], candidate_tokens: list[tuple[str, set[str]]],
) -> str | None:
    """Pick the highest-overlap candidate from precomputed token sets, or ``None``.

    *candidate_tokens* must be ordered by name so ties resolve deterministically
    to the alphabetically-first name.  Returns ``None`` when the best overlap is
    below ``EVAL_HEURISTIC_MIN_OVERLAP``.
    """
    best_name: str | None = None
    best_score = -1.0
    for name, tokens in candidate_tokens:
        score = _jaccard(prompt_tokens, tokens)
        if score > best_score:
            best_score = score
            best_name = name
    if best_score < EVAL_HEURISTIC_MIN_OVERLAP:
        return None
    return best_name


def score_heuristic(prompt: str, candidates: list[Unit]) -> str | None:
    """Predict the unit name with the highest Jaccard overlap, or ``None``.

    Candidates are scanned in name order so ties resolve deterministically to
    the alphabetically-first name.  Returns ``None`` when the best overlap is
    below ``EVAL_HEURISTIC_MIN_OVERLAP`` (no candidate fits).
    """
    if not candidates:
        return None
    return _score_prompt(tokenize(prompt), _candidate_tokens(candidates))


# --- metrics aggregation ----------------------------------------------------


def aggregate(
    scored: list[ScoredQuery], target: str,
    min_precision: float, min_recall: float,
) -> Metrics:
    """Build the confusion matrix and derive precision/recall + pass verdict.

    A positive prompt predicting *target* is a TP (else FN); a negative prompt
    predicting *target* is an FP (else TN — selecting ``None`` or another unit
    both reject *target*).  Precision and recall default to ``1.0`` when their
    denominator is ``0``.
    """
    tp = fp = tn = fn = 0
    for query in scored:
        hit = query.prediction == target
        if query.label == LABEL_POSITIVE:
            tp, fn = (tp + 1, fn) if hit else (tp, fn + 1)
        else:
            fp, tn = (fp + 1, tn) if hit else (fp, tn + 1)

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    passed = precision >= min_precision and recall >= min_recall
    return Metrics(
        tp=tp, fp=fp, tn=tn, fn=fn,
        precision=precision, recall=recall, passed=passed,
    )


def pairwise_confusion(
    scored: list[ScoredQuery], target: str,
) -> dict[str, int]:
    """Count, per sibling unit, how often a *positive* prompt for *target* was
    misrouted to that unit (a real boundary confusion).

    Only positive prompts count: a negative prompt that correctly selects a
    different unit is the expected outcome, not confusion against *target*.
    """
    votes = Counter(
        query.prediction for query in scored
        if query.label == LABEL_POSITIVE
        and query.prediction is not None
        and query.prediction != target
    )
    return dict(sorted(votes.items()))


# --- orchestrator -----------------------------------------------------------


def _matching_units(corpus: Corpus, candidates: list[Unit]) -> list[Unit]:
    """All discovered units whose name and kind match the corpus target."""
    return [
        unit for unit in candidates
        if unit.name == corpus.target and unit.kind == corpus.kind
    ]


def _candidate_set(target_unit: Unit, candidates: list[Unit]) -> list[Unit]:
    """Resolve the candidate units *target_unit* discriminates against.

    Skills compete with sibling skills; capabilities with sibling capabilities
    under the same parent skill.
    """
    if target_unit.kind == KIND_SKILL:
        return [unit for unit in candidates if unit.kind == KIND_SKILL]
    return [
        unit for unit in candidates
        if unit.kind == KIND_CAPABILITY and unit.parent == target_unit.parent
    ]


def _score_corpus(corpus: Corpus, candidate_set: list[Unit]) -> list[ScoredQuery]:
    """Score every prompt of *corpus* heuristically against *candidate_set*.

    Candidate cards are tokenized once per corpus (not per prompt) so cost stays
    linear in prompts rather than prompts x candidates.
    """
    candidate_tokens = _candidate_tokens(candidate_set)
    scored: list[ScoredQuery] = []
    sides = (
        (LABEL_POSITIVE, corpus.positive), (LABEL_NEGATIVE, corpus.negative),
    )
    for label, prompts in sides:
        for prompt in prompts:
            prediction = _score_prompt(tokenize(prompt), candidate_tokens)
            scored.append(ScoredQuery(prompt, label, prediction))
    return scored


def evaluate(
    corpora: list[Corpus], candidates: list[Unit], opts: dict,
) -> EvalReport:
    """Score every corpus against *candidates* and assemble the report.

    *opts* carries the resolved options: ``min_precision`` and ``min_recall``.
    The exit-affecting gate compares the point estimate; pairwise confusion is
    advisory.
    """
    report = EvalReport(
        min_precision=opts["min_precision"], min_recall=opts["min_recall"],
    )

    for corpus in corpora:
        base = to_posix(corpus.source_path)
        matches = _matching_units(corpus, candidates)
        if not matches:
            report.errors.append(
                f"{LEVEL_FAIL}: [foundry] {base}: target '{corpus.target}' "
                f"({corpus.kind}) was not found among the discovered units"
            )
            continue
        if len(matches) > 1:
            parents = sorted((unit.parent or "<skill-root>") for unit in matches)
            report.errors.append(
                f"{LEVEL_FAIL}: [foundry] {base}: target '{corpus.target}' "
                f"({corpus.kind}) is ambiguous — it matches units under "
                f"{parents}; point --skill-set at a single skill root"
            )
            continue
        candidate_set = _candidate_set(matches[0], candidates)

        min_precision = (
            corpus.min_precision if corpus.min_precision is not None
            else opts["min_precision"]
        )
        min_recall = (
            corpus.min_recall if corpus.min_recall is not None
            else opts["min_recall"]
        )

        scored = _score_corpus(corpus, candidate_set)
        metrics = aggregate(scored, corpus.target, min_precision, min_recall)
        advisory = {"pairwise_confusion": pairwise_confusion(scored, corpus.target)}

        report.targets.append(
            TargetResult(
                target=corpus.target, kind=corpus.kind,
                candidate_count=len(candidate_set), metrics=metrics,
                min_precision=min_precision, min_recall=min_recall,
                scored=tuple(scored), advisory=advisory,
            )
        )

    return report
