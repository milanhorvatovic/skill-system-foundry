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
import random
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field

from .constants import (
    DIR_CAPABILITIES,
    EVAL_DIVERSITY_RATIO,
    EVAL_HEURISTIC_MIN_OVERLAP,
    EVAL_MAX_PROMPT_CHARS,
    EVAL_STOPWORDS,
    FILE_CAPABILITY_MD,
    FILE_SKILL_MD,
    LEVEL_FAIL,
    LEVEL_WARN,
)
from .frontmatter import load_frontmatter

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# --- structural constants ---------------------------------------------------

KIND_SKILL = "skill"
KIND_CAPABILITY = "capability"
LABEL_POSITIVE = "positive"
LABEL_NEGATIVE = "negative"
PREDICTION_NONE = "none"  # the LLM's literal "no unit fits" answer

MODE_HEURISTIC = "heuristic"
MODE_LLM = "llm"

# Anthropic Messages API version header value (stable).
ANTHROPIC_API_VERSION = "2023-06-01"
_CLASSIFIER_SYSTEM_PROMPT = (
    "You are a skill router.  Given a user request and a list of skills, reply "
    "with exactly one skill name from the list, or 'none' if no skill fits.  "
    "Output only the name, with no punctuation or explanation."
)

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


def extract_capability_card(capability_md_path: str, dir_name: str) -> tuple[str, str]:
    """Return ``(name, description)`` for a capability.

    Name is *dir_name* (capabilities carry no frontmatter ``name``); description
    is the first non-empty body paragraph after the ``# Heading`` line in
    *capability_md_path* (empty when none exists).
    """
    _frontmatter, body, _findings = load_frontmatter(capability_md_path)
    return dir_name, _first_paragraph_after_heading(body)


def _units_for_skill(skill_dir: str) -> list[Unit]:
    """Build the skill Unit plus a Unit for each of its capabilities."""
    units: list[Unit] = []
    skill_md = os.path.join(skill_dir, FILE_SKILL_MD)
    frontmatter, _body, _findings = load_frontmatter(skill_md)
    frontmatter = frontmatter or {}
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


# --- heuristic scoring (step 6) ---------------------------------------------


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


def score_heuristic(prompt: str, candidates: list[Unit]) -> str | None:
    """Predict the unit name with the highest Jaccard overlap, or ``None``.

    Candidates are scanned in name order so ties resolve deterministically to
    the alphabetically-first name.  Returns ``None`` when the best overlap is
    below ``EVAL_HEURISTIC_MIN_OVERLAP`` (no candidate fits).
    """
    if not candidates:
        return None
    prompt_tokens = tokenize(prompt)
    best_name: str | None = None
    best_score = -1.0
    for candidate in sorted(candidates, key=lambda unit: unit.name):
        score = _jaccard(prompt_tokens, tokenize(candidate.card_text))
        if score > best_score:
            best_score = score
            best_name = candidate.name
    if best_score < EVAL_HEURISTIC_MIN_OVERLAP:
        return None
    return best_name


# --- deterministic split (step 7) -------------------------------------------


def split_train_validation(
    corpus: Corpus, ratio: float, seed: int,
) -> tuple[Corpus, Corpus]:
    """Stratified, deterministic train/validation split keyed by *seed*.

    *ratio* is the train fraction; positives and negatives are split
    independently (stratified) so both halves keep the corpus's pos/neg
    structure.  Identical *seed* yields identical splits.
    """
    rng = random.Random(seed)

    def split_side(items: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        ordered = list(items)
        rng.shuffle(ordered)
        cut = int(round(len(ordered) * ratio))
        return tuple(ordered[:cut]), tuple(ordered[cut:])

    pos_train, pos_val = split_side(corpus.positive)
    neg_train, neg_val = split_side(corpus.negative)

    def rebuild(positive: tuple[str, ...], negative: tuple[str, ...]) -> Corpus:
        return Corpus(
            target=corpus.target, kind=corpus.kind,
            positive=positive, negative=negative,
            min_precision=corpus.min_precision, min_recall=corpus.min_recall,
            source_path=corpus.source_path,
        )

    return rebuild(pos_train, neg_train), rebuild(pos_val, neg_val)


# --- metrics aggregation (step 8) -------------------------------------------


def aggregate(
    scored: list[ScoredQuery], target: str,
    min_precision: float, min_recall: float,
) -> Metrics:
    """Build the confusion matrix and derive precision/recall + pass verdict.

    A positive prompt predicting *target* is a TP (else FN); a negative prompt
    predicting *target* is an FP (else TN — selecting ``None`` or another unit
    both reject *target*).  Precision and recall default to ``1.0`` when their
    denominator is ``0`` (section 4.6).
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


# --- LLM client + scorer (steps 9-10) ---------------------------------------


def build_classifier_prompt(prompt: str, candidates: list[Unit]) -> str:
    """Render the classifier instruction listing every candidate card."""
    lines = ["Available skills:"]
    for candidate in sorted(candidates, key=lambda unit: unit.name):
        description = candidate.description.strip() or "(no description)"
        lines.append(f"- {candidate.name}: {description}")
    lines.append("- none: the request matches no skill above")
    lines.append("")
    lines.append(f"User request: {prompt}")
    lines.append("")
    lines.append(
        "Reply with only the single most relevant skill name from the list "
        "above (or 'none')."
    )
    return "\n".join(lines)


def _anthropic_messages(
    prompt: str, candidates: list[Unit], model: str,
    api_key: str, endpoint: str,
) -> str:
    """POST one classification request to the Anthropic Messages API.

    Returns the model's first non-blank answer line (caller maps it to a unit
    name or ``None``).  Raises a ``RuntimeError`` with an actionable message on
    HTTP / transport / decode failure — no retry logic.
    """
    body = json.dumps(
        {
            "model": model,
            "max_tokens": 30,
            "temperature": 0,
            "system": _CLASSIFIER_SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": build_classifier_prompt(prompt, candidates),
                }
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        excerpt = ""
        try:
            excerpt = exc.read().decode("utf-8", "replace")[:200]
        except OSError:
            pass
        raise RuntimeError(
            f"Anthropic API returned HTTP {exc.code}: {excerpt}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Anthropic API request failed: {exc.reason}"
        ) from exc

    try:
        payload = json.loads(raw)
        text = payload["content"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"Anthropic API returned an unexpected payload ({exc})"
        ) from exc

    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _normalize_choice(answer: str, name_by_lower: dict[str, str]) -> str | None:
    """Map a raw model answer to a candidate name or ``None``."""
    cleaned = answer.strip().strip(".").strip().lower()
    if cleaned == PREDICTION_NONE:
        return None
    return name_by_lower.get(cleaned)


def score_llm(
    prompt: str, target: str, candidates: list[Unit], runs: int,
    client_fn,
) -> tuple[str | None, float]:
    """Run *client_fn* *runs* times; return ``(prediction, trigger_rate)``.

    *trigger_rate* is the fraction of runs that selected *target* (drives the
    advisory variance flag).  *prediction* is the majority-voted unit across
    runs — ``None`` when no unit reaches a 50% share — and is what the
    confusion matrix and pairwise confusion consume, so a consistently
    mis-selected sibling is still captured.  Ties among units break to the
    alphabetically-first name.  *client_fn* takes ``(prompt, candidates)`` and
    returns the raw answer line, so the Anthropic client is mockable.
    """
    name_by_lower = {unit.name.lower(): unit.name for unit in candidates}
    choices = [
        _normalize_choice(client_fn(prompt, candidates), name_by_lower)
        for _ in range(runs)
    ]

    trigger_rate = (
        sum(1 for choice in choices if choice == target) / runs if runs else 0.0
    )

    unit_votes = Counter(choice for choice in choices if choice is not None)
    prediction: str | None = None
    if unit_votes and runs:
        top_unit, top_count = sorted(
            unit_votes.items(), key=lambda item: (-item[1], item[0]),
        )[0]
        if top_count / runs >= 0.5:
            prediction = top_unit
    return prediction, trigger_rate


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
