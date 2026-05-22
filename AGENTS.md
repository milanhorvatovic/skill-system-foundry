# Skill System Foundry

Meta-skill for building AI-agnostic skill systems with a two-layer architecture (skills and roles), templates, validation tools, and cross-platform authoring guidance based on the [Agent Skills specification](https://agentskills.io).

## Project Context

This repository contains **one skill** (`skill-system-foundry/`) and its **test suite** (`tests/`). The skill is a meta-skill — its domain is building other skills. It is not an application. There is no server, no database, no frontend.

**Language:** Python 3.12+ (standard library only — no third-party imports in production code).

**Dev dependency:** `coverage` (test coverage measurement only; see `requirements-dev.txt` for the exact version).

**Repository structure:**

```
.
├── AGENTS.md                        ← this file
├── CLAUDE.md                        ← symlink to AGENTS.md
├── CONTRIBUTING.md                  ← contributor guidelines
├── README.md                        ← repository overview
├── .coveragerc                      ← coverage configuration (70% threshold, branch)
├── .python-version                  ← Python version (see file for current value)
├── requirements-dev.txt             ← coverage only
├── skill-system-foundry/            ← the meta-skill itself
│   ├── SKILL.md                     ← entry point (router)
│   ├── README.md                    ← skill documentation
│   ├── capabilities/                ← self-contained capability modules
│   │   ├── skill-design/
│   │   │   └── capability.md        ← create skills, capabilities, roles, manifests
│   │   ├── validation/
│   │   │   └── capability.md        ← validate skills, audit systems
│   │   ├── migration/
│   │   │   └── capability.md        ← migrate flat skills to router pattern
│   │   ├── bundling/
│   │   │   └── capability.md        ← package skills as zip bundles
│   │   └── deployment/
│   │       ├── capability.md        ← deploy to tools, wrappers, symlinks
│   │       └── references/
│   │           └── symlink-setup.md ← platform-specific symlink commands
│   ├── references/                  ← guidance loaded into context on demand
│   │   ├── authoring-principles.md  ← cross-platform skill writing consensus
│   │   ├── architecture-patterns.md ← standalone vs router decisions
│   │   ├── agentskills-spec.md      ← specification compliance guide
│   │   ├── tool-integration.md      ← tool-specific paths and deployment
│   │   ├── directory-structure.md   ← full layout and conventions
│   │   ├── anti-patterns.md         ← common mistakes
│   │   ├── claude-code-extensions.md
│   │   ├── codex-extensions.md
│   │   └── cursor-extensions.md
│   ├── assets/                      ← templates for scaffolding
│   │   ├── skill-standalone.md
│   │   ├── skill-router.md
│   │   ├── capability.md
│   │   ├── role.md
│   │   └── manifest.yaml
│   └── scripts/                     ← validation, scaffolding, bundling tools
│       ├── lib/                     ← shared logic (single responsibility per module)
│       │   ├── configuration.yaml   ← single source of truth for all validation rules
│       │   ├── constants.py         ← loads YAML, exposes as Python constants
│       │   ├── validation.py        ← shared name/field validation
│       │   ├── references.py        ← reference scanning and graph traversal
│       │   ├── bundling.py          ← core bundling logic
│       │   ├── manifest.py          ← manifest parsing and validation
│       │   ├── codex_config.py      ← Codex agents/openai.yaml validation
│       │   ├── yaml_parser.py       ← stdlib-only YAML subset parser
│       │   ├── frontmatter.py       ← YAML frontmatter extraction
│       │   ├── reporting.py         ← structured output formatting
│       │   └── discovery.py         ← skill directory discovery
│       ├── validate_skill.py        ← validate a single skill
│       ├── audit_skill_system.py    ← audit entire skill system
│       ├── scaffold.py              ← scaffold new components from templates
│       ├── bundle.py                ← bundle for distribution (zip)
│       ├── stats.py                 ← report skill token-budget proxies
│       ├── yaml_conformance_report.py  ← run the YAML 1.2.2 corpus
│       └── evaluate_descriptions.py    ← heuristic description activation evaluation
├── scripts/                         ← repository infrastructure (not part of the meta-skill)
│   ├── generate_changelog.py        ← changelog generator (git history → CHANGELOG.md)
│   └── lib/
│       └── changelog.yaml           ← verb→section map for the changelog generator
├── tests/                           ← comprehensive test suite (see tests/ for current files)
│   ├── helpers.py                   ← shared test utilities
│   └── test_*.py                    ← one test file per source module
├── .agents/                         ← internal development skills (not distributed)
│   └── skills/
│       ├── commit-conventions/       ← commit message format and conventions
│       ├── critique/                ← constructive criticism of plans and solutions
│       ├── git-release/             ← release lifecycle guidance
│       ├── github-actions/          ← CI/CD workflow authoring and review
│       ├── local-code-review/       ← local automated checks and diff analysis
│       ├── markdown-docs/           ← documentation quality enforcement
│       ├── python-scripts/          ← Python code quality conventions
│       ├── review/                  ← human PR review process guidance
│       ├── shell-scripts/           ← shell script safety and consistency
│       ├── skill-authoring/         ← meta-skill structure consistency
│       ├── solution-design/         ← solution planning before implementation
│       ├── validate-skill-spec/     ← skill structure and spec compliance validation
│       └── yaml-config/             ← configuration.yaml governance
├── .claude/                         ← Claude Code configuration and skill symlinks
│   └── skills/                      ← symlinks to .agents/skills/ for Claude Code
├── .claude-plugin/                  ← Claude Code plugin marketplace config
│   ├── plugin.json
│   └── marketplace.json
└── .github/
    ├── codex/                       ← Codex review configuration
    │   └── review-reference.md      ← repository-specific review guidance
    ├── scripts/                     ← CI helper scripts (bash + Python)
    ├── workflows/                   ← GitHub Actions CI/CD
    │   ├── python-tests.yaml        ← tests + coverage + badge update (ubuntu + windows)
    │   ├── shellcheck.yaml          ← lints .github/scripts/*.sh
    │   ├── codex-code-review.yaml   ← Codex PR review via codex-ai-code-review-action
    │   └── release.yaml              ← bundles zip + uploads release asset
    ├── instructions/                ← review rules for Copilot/Codex
    │   ├── markdown.instructions.md ← applies to **/*.md
    │   └── scripts.instructions.md  ← applies to scripts/**/*.py
    ├── copilot-instructions.md      ← top-level review guidance
    └── CODEOWNERS                   ← requires code-owner approval for .github/
```

## Constraints

These constraints are non-negotiable across the entire codebase:

- **Standard library only** — no `pip install` dependencies in production code. Scripts must run anywhere Python 3.12+ is available.
- **Python 3.12 compatibility** — do not use features from 3.13+.
- **Validation rules in YAML** — limits, patterns, and reserved words live in `skill-system-foundry/scripts/lib/configuration.yaml`. Never hardcode validation rules in Python. (Repo-infrastructure tools keep their own YAML under `scripts/lib/` — e.g., `scripts/lib/changelog.yaml` for the changelog generator's verb mapping — and are not loaded by the meta-skill.)
- **`os.path` only** — do not use `pathlib`. Do not mix the two.
- **Type hints on all function signatures** — use builtin generics (`list`, `dict`, `tuple`) and `X | None`.
- **`encoding="utf-8"` on all `open()` calls.**
- **`newline="\n"` on every production text-mode write** — without it Python translates `\n` to `\r\n` on Windows, so files authored on a Windows runner pick up CRLF terminators that diverge from LF on POSIX. The `tests/test_text_write_newline.py` lint enforces the rule across the meta-skill and repo-infrastructure scripts.
- **Error levels from constants** — use `LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO` from `lib/constants.py`, never hardcode strings.
- **Validation functions return `(errors, passes)` tuples** — never raise exceptions for validation failures.
- **Shell scripts use `set -euo pipefail`** and validate environment variables at the top with `${VAR:?}`.
- **Actions pinned to commit SHAs** — not tags.
- **Meta-skill script entry points support `--json`** — entry points under `skill-system-foundry/scripts/` must provide machine-readable output via `to_json_output()` from `lib/reporting.py`. Repo-infrastructure scripts under the top-level `scripts/` tree (e.g., `scripts/generate_changelog.py`) are exempt: their output is consumed directly by humans during maintenance tasks, and line-oriented stderr diagnostics already cover the tooling surface.

## Development Workflow

### Contributor Setup on Windows

The repository uses symlinks for the dev-cycle layout — `CLAUDE.md` points at `AGENTS.md` and every entry under `.claude/skills/` points into `.agents/skills/`. Cloning on Windows without Developer Mode (or without `core.symlinks=true` in the local git config) materialises those links as plain text files containing the target path, which breaks the contributor experience. Either enable Developer Mode before cloning (`Settings → Privacy & Security → For developers`) or set `git config --global core.symlinks true` and re-clone. The same Windows precondition is documented in `README.md`'s "Windows Setup" section for the user-facing skill-deployment workflow.

### Running Tests

```bash
python -m coverage run -m unittest discover -s tests -p "test_*.py" -v
python -m coverage report
```

Coverage threshold: 70% branch coverage (configured in `.coveragerc`). CI runs tests on both ubuntu-latest and windows-latest with Python 3.12.

### Validating the Meta-Skill

```bash
cd skill-system-foundry
python scripts/validate_skill.py . --allow-nested-references --foundry-self --verbose
python scripts/audit_skill_system.py .
```

The `--allow-nested-references` flag is needed because this meta-skill intentionally uses nested references.

The audit runs in two modes. *System-root mode* applies when the target directory contains a `skills/` tree (deployed-system layout) and walks every `skills/<name>/SKILL.md`. *Skill-root mode* applies when the target directory contains a `SKILL.md` directly (single-skill layout) and audits that skill on its own. The router-table consistency rule and the orphan-reference rule both fire per-skill in both modes, so this same invocation also catches drift in the meta-skill's own `capabilities/` directory and in any integrator-built meta-skill. Most other per-skill rules iterate only the deployed-system layout.

The orphan-reference rule flags any file under `references/` (or `capabilities/<name>/references/`) that no `SKILL.md` and no `capability.md` reaches via the configured body reference patterns. Suppress individual paths by listing them under `orphan_references.allowed_orphans` in `scripts/lib/configuration.yaml`; entries that begin with `skills/` are audit-root-relative (target one specific skill in a deployed-system audit), all other entries are skill-root-relative (apply to every skill the audit walks). The rule is independent of `--allow-nested-references` — that flag only suppresses depth warnings, not reachability findings. Allow-list entries that no longer resolve to an existing file are surfaced as `INFO` (one finding per stale entry) so the list cannot silently rot — `skills/...`-prefixed entries are silently skipped in skill-root mode because that layout has no enclosing `skills/` directory to disambiguate against.

The version-consistency rule in `audit_skill_system.py` (which compares `SKILL.md`, `.claude-plugin/plugin.json`, and `.claude-plugin/marketplace.json`) only fires when the audit root contains both `.claude-plugin/plugin.json` and `skill-system-foundry/SKILL.md` — the gate keeps the rule scoped to the foundry distribution repository so integrator skill systems that ship their own Claude plugin manifest are unaffected. The `cd skill-system-foundry` invocation above therefore skips that rule by design — it is a repo-level check, not a skill-level check. To include it, run the audit from the repo root:

```bash
python skill-system-foundry/scripts/audit_skill_system.py .
```

The repo root has no `skills/` tree and no top-level `SKILL.md`, so this invocation runs in distribution-repo mode and emits one expected `WARN: No skills/ directory under system root — ran partial audit`. Per-skill rules (including the router-table rule) are skipped under that invocation — it adds the repo-level version-consistency check and the corpus-coverage rules (below) on top of what the `cd skill-system-foundry` invocation already covers. To audit the meta-skill's own router table, the `cd skill-system-foundry && python scripts/audit_skill_system.py .` invocation above (skill-root mode) is the canonical self-check.

#### Flag behavior

| Flag | Effect | When to use |
|---|---|---|
| `--check-prose-yaml` | Validates ```` ```yaml ```` fences in `SKILL.md`, `capabilities/**/*.md`, and `references/**/*.md`. Findings route to the existing FAIL/WARN/INFO stream and the `yaml_conformance.doc_snippets` JSON slot. | When fixing or adding documentation that contains YAML examples. |
| `--foundry-self` | Implies `--check-prose-yaml`. Runs the target skill the way the foundry runs itself. On `audit_skill_system` it is a mode switch — the prose check runs across every scanned skill. | Self-validation of the meta-skill, or to run an integrator skill with foundry-equivalent strictness. |
| `--allow-nested-references` | Suppresses the nested-reference depth warning. Required for skills that intentionally cross-reference their own reference files. | Any meta-skill or template-rich skill where reference graphs span more than one level. |
| `--verbose` | Prints per-file progress messages for the prose check (`Checking prose YAML: <path> (<N> fences)`) and shows passing checks otherwise. Silent under `--json`. | Local debugging / triage. |

In addition, `python scripts/yaml_conformance_report.py` runs the YAML 1.2.2 conformance corpus and emits the same `yaml_conformance.corpus` JSON slot for tooling consumers; exit 0 on all-pass, non-zero on any failure.

#### Corpus-coverage rules

`audit_skill_system.py` enforces five audit-level corpus-coverage rules (`scripts/lib/audit_coverage.py`) on top of the per-corpus shape rules the description-quality runner applies at load time. They answer the questions a runner alone cannot: does every discoverable unit *have* a corpus, is each corpus *fresh* against the description it tests, are a skill's capability corpora *consistent*, and is a committed corpus *large enough*. The rules are: (1) missing corpus — a unit with no corpus file and no opt-out, `WARN`; (2) stale allow-list entry — an `allowed_missing_corpus` entry matching no discovered unit, `INFO`; (3) freshness — a corpus whose `description_sha256` no longer matches the SHA-256 of the live unit description, `WARN`; (4) sibling parity — a skill that covers some but not all of its (non-exempt) capabilities, `WARN`; (5) size escalation — a committed corpus below `recommended_prompts_per_side` on its smaller side, `FAIL` (escalating the runner's Tier B WARN; below `min_prompts_per_side` the corpus fails to load and that load `FAIL` surfaces here too).

Units are discovered the way the description-quality runner discovers them — a skill at the audit root or as an immediate subdirectory, with capability descriptions read from each `capability.md` body — not via the deployed-system `find_skill_dirs` walk. The corpus root resolves relative to the audit root from `skill.description.evaluation.coverage.corpus_root_relative` (default `tests/skill-corpus`), and every rule self-skips when that directory is absent. The practical consequence: the canonical coverage self-check for the meta-skill is the **repo-root** audit (`python skill-system-foundry/scripts/audit_skill_system.py .`), where `tests/skill-corpus` resolves and `skill-system-foundry` is found as a subdirectory; the `cd skill-system-foundry && python scripts/audit_skill_system.py .` skill-root self-check self-skips coverage because no corpus tree lives under the skill itself. The `validate-examples` job in `python-tests.yaml` runs that repo-root audit on every PR, so missing or undersized corpora surface at PR time (size escalation `FAIL`s the job; missing / stale / parity are `WARN` and visible in the log without blocking).

Each corpus carries a `description_sha256` in its header that the freshness rule compares against. Refresh it with one idempotent command after any description change:

```bash
cd skill-system-foundry
python scripts/evaluate_descriptions.py ../tests/skill-corpus/skill-system-foundry --backfill-hash
```

`--backfill-hash` recomputes each corpus's hash from the live unit description (`--skill-set`, defaulting to the current directory, supplies the units) and writes it into the corpus header in place. It is byte-stable: a corpus already carrying the correct hash is left untouched, so re-running produces no diff. The hash is over the unit's *resolved* description — the folded frontmatter `description` for a skill, the first body paragraph after the `# Heading` for a capability — so a capability's freshness tracks edits to that intro paragraph, not its frontmatter.

Suppress an intentional coverage gap by listing the unit's qualified name under `allowed_missing_corpus` in `configuration.yaml` — a skill name, or `<skill>/capabilities/<cap>` for a capability. The mechanism mirrors `orphan_references.allowed_orphans`: an allow-listed unit is exempt from the missing-corpus rule *and* neutral for sibling parity, and an entry that matches no discovered unit is surfaced as `INFO` so the list cannot rot silently. Integrators that ship no corpora can disable the freshness rule with `coverage.freshness_check_enabled: false`; the size rule reuses the existing `min_prompts_per_side` / `recommended_prompts_per_side` thresholds rather than a parallel floor.

### Evaluating Description Quality

Structural validation does not test whether a description actually *activates* on the prompts it should. `evaluate_descriptions.py` measures activation precision and recall against a JSON corpus of positive (should activate) and negative (should not) prompts:

```bash
cd skill-system-foundry
python scripts/evaluate_descriptions.py ../tests/skill-corpus/skill-system-foundry --skill-set . --soft --json
```

The meta-skill ships its own corpus under `tests/skill-corpus/skill-system-foundry/` (`skill.json` plus one file per capability), exercised on every PR by the `validate-examples` job in `python-tests.yaml` (heuristic, `--soft`). Scoring is heuristic, stdlib-only, and key-free. A higher-fidelity, semantic check ships alongside it as the agent-delegated mode below — still stdlib-only and key-free, because the host agent (not an API client) does the classifying. The corpus format, the unit card model, and the exact `--soft` exit-code semantics are documented in the validation capability's "Description-Quality Evaluation" section; evaluation settings (thresholds, stopwords) live under `skill.description.evaluation` in `scripts/lib/configuration.yaml`.

The agent-delegated mode is an authoring-time deep check that catches semantic-but-non-lexical routing the Jaccard heuristic misses. It runs in three steps:

```bash
cd skill-system-foundry
# 1. Emit one classification task per prompt.
python scripts/evaluate_descriptions.py ../tests/skill-corpus/skill-system-foundry --skill-set . --emit-tasks /tmp/skf.tasks.json --json
# 2. The host agent reads /tmp/skf.tasks.json and writes /tmp/skf.predictions.json as {id: name|null}.
# 3. Score the agent's predictions through the same gate as the heuristic.
python scripts/evaluate_descriptions.py ../tests/skill-corpus/skill-system-foundry --skill-set . --predictions /tmp/skf.predictions.json --soft --json
```

To see exactly where the agent and the heuristic route differently, write the heuristic's answers for the same task ids and diff the two files:

```bash
cd skill-system-foundry
python scripts/evaluate_descriptions.py ../tests/skill-corpus/skill-system-foundry --skill-set . --emit-heuristic-predictions /tmp/skf.heuristic.predictions.json --json
diff /tmp/skf.heuristic.predictions.json /tmp/skf.predictions.json || true
```

Agent reasoning is non-deterministic, so this mode is never a CI gate — the heuristic `validate-examples` step stays the gate, and the agent mode adds no audit, freshness, or corpus surface. An integrator who wants a stability signal runs step 2 several times and diffs the predictions files; the runner scores one file per invocation by design (a single point estimate). Task and prediction files are ephemeral run artifacts — `.gitignore` covers `*.tasks.json` and `*.predictions.json`, and they must never be placed under `tests/skill-corpus/`.

### Measuring the Meta-Skill's Token Budget

```bash
cd skill-system-foundry
python scripts/stats.py . --json
```

`stats.py` reports two byte-based proxies for a skill's context cost: `discovery_bytes` (the sum of every YAML frontmatter block the harness reads at discovery time — `SKILL.md` plus each `capabilities/<name>/capability.md` that declares one) and `load_bytes` (SKILL.md plus every capability and reference file reachable through markdown links, backticks, and bare router-table path cells). Every discovery-relevant `files[]` row — `SKILL.md` and each `capabilities/<name>/capability.md` — carries a `discovery_bytes` key with its own contribution (`0` when the file is silent on frontmatter); non-discovery rows (capability-local references and shared references) omit the key entirely. Consumers can reconstruct the breakdown without re-reading any files, and the human-readable report shows the breakdown directly when at least one capability declares frontmatter. Files under `scripts/` and `assets/` are excluded — they are not loaded into the model's context during skill use. Bytes are not tokens and are not comparable across models or tokenizers; treat the number as a deterministic on-disk signal for tracking the relative cost of authoring decisions over time. Counts are taken from raw on-disk UTF-8 bytes, so CRLF terminators on Windows checkouts produce higher numbers than the same content on POSIX checkouts.

For cross-platform comparability, `stats.py --json` reports `discovery_bytes_lf` and `load_bytes_lf` inside the nested `stats` object alongside the raw counts, plus a per-row `line_endings` field (`lf` / `crlf` / `mixed`) on every *text-shaped* load-budget contributor — markdown, YAML, JSON, txt, sh, py, toml. Binary load contributors (e.g. an image or PDF referenced from `references/`) deliberately omit the `line_endings` key because arbitrary `\r\n` byte pairs in binary content are not line terminators; counting them as CRLFs would reduce `load_bytes_lf` and emit a meaningless mode label for files byte-identical across platforms. JSON consumers should branch on key presence rather than treat the missing key as a regression. The `*_lf` numbers subtract one byte per `\r\n` pair detected *within the relevant window* — `load_bytes_lf` subtracts every CRLF in every text-shaped load-budget file, `discovery_bytes_lf` subtracts only the CRLFs inside each frontmatter block — so a CRLF checkout and an LF checkout of the same content produce equal normalized totals. The raw counts continue to be the deterministic on-disk signal. The human-readable report only shows the normalized line when it diverges from the raw count, so existing LF-only checkouts see no extra noise. Detection is gated by `stats.line_endings.enabled` in `configuration.yaml` for integrators who want a pure raw-byte view; when the toggle is off, the `*_lf` keys and `line_endings` rows are omitted from the JSON payload entirely so consumers branch on key presence rather than read an equal-to-raw fallback that would silently misrepresent CRLF checkouts.

A missing or unreadable `SKILL.md` is a FAIL — that includes the file not existing, an I/O error during read, or invalid UTF-8 in either the frontmatter scan or the body. Everything else recovers: broken references, parent-traversal attempts, external references, undecodable referenced files, and frontmatter parse errors (in `SKILL.md` or in any capability entry) are surfaced as WARN/INFO findings while the run still emits a usable metric. A capability that is silent on frontmatter is legal and produces no finding — its per-row `discovery_bytes` is simply `0`.

### Detecting Tool Catalog Drift

The hand-maintained Claude Code tool catalog at `skill.allowed_tools.catalogs.claude_code` in `skill-system-foundry/scripts/lib/configuration.yaml` drifts as Claude Code adds, renames, or retires tools. A weekly scheduled workflow (`.github/workflows/tool-catalog-drift.yaml`, helper at `.github/scripts/tool-catalog-drift.py`) compares the catalog against the canonical upstream tools reference at the URL recorded in `skill.allowed_tools.catalog_provenance.claude_code.source_url` and force-pushes a single rolling PR (`chore/tool-catalog-drift`) when drift is detected. Additions are auto-applied; removals are surfaced in the PR body as advisory candidates only — verify each name before deleting.

When drift is additions-only and the count is at or below `MAX_AUTO_MERGE_ADDITIONS` (see the helper for the policy rationale and current value), the helper marks the run `auto_mergeable: true` in its JSON payload and the workflow auto-merges the rolling PR — it waits for the ruleset's `required_status_checks` via `gh pr checks --required --watch --fail-fast`, squash-merges synchronously under the bot's token if CI is green, and falls back to enabling GitHub auto-merge if a check fails or mergeability changes between the watch and the merge call (so a later rerun-to-green can fire the merge without a manual workflow re-trigger). Drift outside the gate — any removals, or additions above the threshold — routes through the manual-review path: the PR opens but no merge is attempted.

To run the sweep locally:

```bash
python .github/scripts/tool-catalog-drift.py --dry-run
python .github/scripts/tool-catalog-drift.py --dry-run --json
```

`--dry-run` exits 0 on no drift, 1 on drift detected; default mode mutates `configuration.yaml` and bumps `skill.allowed_tools.catalog_provenance.claude_code.last_checked` only when there are additions to apply. Removals-only drift leaves the YAML untouched (removals are advisory and never auto-applied); the workflow surfaces them through the PR body via an empty commit.

The helper tracks the `claude_code` catalog only. The `catalogs.<harness>` YAML structure preserves room for a future second harness, but adding one is not a YAML-only edit — `run` and `parse_catalog` in `.github/scripts/tool-catalog-drift.py` currently process the single default harness, so a future extension requires helper changes (and may need workflow updates for per-harness PR titles or reporting).

#### Operator preconditions for the auto-merge path

Four repo-level preconditions must be in place for the workflow to function end-to-end. They split into two tiers. **Tier 1 — workflow-runtime prerequisite:** the App + secrets are the only HARD prerequisite for the workflow to run at all; an unavailable App or missing secret hard-fails at the "Mint App token" step before any drift logic. **Tier 2 — auto-merge-safety prerequisites:** the ruleset's `required_status_checks` rule, the "Allow auto-merge" repo setting, and the absence of CODEOWNERS coverage on the catalog file each gate a different aspect of the auto-merge path's safety, but drift detection and PR open/update succeed without any of them. A missing or empty `required_status_checks` rule causes the wait-and-merge step to hard-fail immediately at the expected-count query (`gh api repos/.../rules/branches/main` returns 0 contexts) with `::error::Could not determine the expected required-check count...`; if the rule is present but the listed checks don't register on the PR (paths-filter mismatch on the consumer, App events not firing), the pre-watch polling guard times out after 90s with a different `::error::Only N of M required check runs appeared...` diagnostic. Without "Allow auto-merge", the fallback `gh pr merge --auto` errors out with `::error::`. With the catalog file in CODEOWNERS, `require_code_owner_review: true` blocks every auto-merge attempt because the bot cannot approve its own PR. Recording all four here because they are not derivable from the code and silently regress when a fork, repo-recreate, or org-policy reset clears them.

1. **GitHub App installed on the repo** with five permissions: `contents: write` (push the rolling branch), `pull-requests: write` (open / edit / merge the rolling PR), `issues: write` (`gh pr close --comment` posts via the issues API — PR comments are issue comments in GitHub's permission model), and `checks: read` + `statuses: read` (`gh pr checks --required --watch` reads check-run and commit-status state). These are App-level permissions — the workflow's job-level `permissions:` block scopes `GITHUB_TOKEN` only and CANNOT compensate for missing App permissions; an under-scoped App will mint a token that mints fine but then 403s on the corresponding gh call. The App's client ID is stored as repository variable `AUTOMATION_CLIENT_ID` (client IDs are not sensitive — variable, not secret, so the value is visible in repo settings for debugging) and its PEM private key as repository secret `AUTOMATION_PRIVATE_KEY`. The App identity (not the default `GITHUB_TOKEN`) is required so the rolling PR's `push`/`pull_request` events trigger downstream workflows — GitHub deliberately excludes `GITHUB_TOKEN`-authored events from triggering further runs, which would otherwise leave the auto-merge wait with no checks to wait on.
2. **Repo setting "Allow auto-merge"** enabled at *Settings → General → Pull Requests*. `gh pr merge --auto` errors out when this is disabled and the workflow surfaces the failure with `::error::` — no silent stranding, but also no merge.
3. **Branch ruleset on `main`** includes a `required_status_checks` rule listing the checks that always fire on drift PRs. The wait-and-merge step has two distinct failure modes for this precondition: (a) if the rule is absent or empty, the workflow hard-fails immediately at the expected-count query with `::error::Could not determine the expected required-check count...` (the query reads the rule via `gh api repos/.../rules/branches/main`); (b) if the rule is present but the listed checks don't register on the PR (paths-filter mismatch on the consumer, App events not firing), the pre-watch polling guard times out after 90s with `::error::Only N of M required check runs appeared...`. Concretely the four distinct contexts that need to be listed are the two matrix entries from `.github/workflows/python-tests.yaml` — `test (ubuntu-latest, 3.12)` and `test (windows-latest, 3.12)` — plus the two matrix entries from `.github/workflows/ci-helper-tests.yaml` — `helper-tests (ubuntu-latest, 3.12)` and `helper-tests (windows-latest, 3.12)` — which is paths-filtered to include `configuration.yaml` so it does fire on drift PRs. The two workflows use distinct job names (`test` and `helper-tests`) so their check contexts never collide; GitHub registers each context as the bare job-name + matrix suffix — *without* a workflow-name prefix in this repo's setup — so the contexts in the ruleset are exactly those four bare strings, not `python-tests / test (...)` or `Python tests / test (...)`. The distinct names matter for branch-protection clarity: a duplicate context name across workflows would leave `gh pr checks --required` and the auto-merge wait-and-merge step unable to attribute a pass/fail back to the originating workflow. `shellcheck` is paths-filtered to `.github/scripts/*.sh` and does NOT fire on drift PRs, so it should NOT be listed.
4. **CODEOWNERS does not cover `skill-system-foundry/scripts/lib/configuration.yaml`**. The current `.github/CODEOWNERS` only owns `.github/codex/`, `.github/instructions/`, `.github/scripts/`, and `.github/workflows/` — keeping the catalog out of CODEOWNERS keeps `require_code_owner_review: true` from blocking the auto-merge path (the bot cannot approve its own PR; adding the catalog to CODEOWNERS would require the second-identity workaround used in `milanhorvatovic/codex-ai-code-review-action`'s dependabot-auto-merge workflow).

The auto-merge path is intentionally tolerant of `required_review_thread_resolution` + Copilot review: if Copilot leaves an unresolved comment on the rolling PR, the synchronous squash-merge fails and the workflow falls back to enabling GitHub auto-merge. The PR then waits for the maintainer to resolve the threads (or for a fresh push to dismiss the stale Copilot review). Auto-merge fires once thread resolution lands. This keeps Copilot's review as a real checkpoint without giving the bot bypass rights against the ruleset.

A defensive disarm step protects against the rolling-branch reuse race that the fallback opens up: if a later run produces drift that is NOT auto-mergeable (removals present, or additions over the threshold), the workflow force-pushes the new content to the same PR — but the previously armed auto-merge would still be active and could land out-of-policy drift once blocking conditions resolve. The disarm runs *before* the force-push (looking up the rolling PR via `gh pr list` since the open-or-update step has not yet run), queries `autoMergeRequest`, calls `gh pr merge --disable-auto` when armed, and verifies the disarm took. Running the disarm before the push closes the window in which the GitHub auto-merge worker could fire against the freshly-pushed non-eligible commit. A failed disarm is a hard error that aborts before the push — the security failure being prevented (auto-merge of out-of-policy drift) is worse than a noisy workflow failure.

### Linting Shell Scripts

```bash
shellcheck .github/scripts/*.sh
```

### Commit Message Format

```
Update <component> and <component>
Add <new-thing> to <location>
Fix <issue> in <component>
```

## Architecture Rules

The skill system has exactly two layers:

- **Skills** — canonical, AI-agnostic knowledge. Standalone for focused tasks, router for complex domains.
- **Roles** — orchestration contracts composing 2+ skills with responsibility, authority, constraints, and handoff rules.

Dependencies flow strictly downward: `roles → skills → capabilities`. Never the reverse. Capabilities are optional and only warranted when 3+ distinct operations have mutually exclusive triggers.

## Code Organization

The rules below apply to the meta-skill tree under `skill-system-foundry/scripts/`. Repo-infrastructure scripts under the top-level `scripts/` tree (e.g., `scripts/generate_changelog.py`) are self-contained maintenance tools — they are allowed to carry domain logic in the entry point rather than delegating to a `lib/` module, because they are invoked only by maintainers during releases and do not need to share logic with the meta-skill.

- **Entry points** (`skill-system-foundry/scripts/*.py`) — thin wrappers: argument parsing, output formatting, `sys.exit()`. Delegate everything to `skill-system-foundry/scripts/lib/`.
- **Library modules** (`skill-system-foundry/scripts/lib/*.py`) — domain logic. No `print()` or `sys.exit()` except in dedicated output helpers (`reporting.py`).
- **Constants** (`skill-system-foundry/scripts/lib/constants.py`) — structural constants in Python, validation rules loaded from `configuration.yaml`. All YAML values are returned as strings by the custom parser — convert with `int()` in `constants.py`.
- **Tests** (`tests/`) — one test file per source module. `unittest.TestCase` with descriptive class names grouped by feature. Section separators (`# ===...`) for visual clarity.

## Documentation Standards

- **Conciseness-first** — only add context the model does not already have.
- **Third person in skill descriptions** — "Validates skills" not "I validate skills".
- **One term per concept** — no synonym mixing within or across files.
- **Progressive disclosure** — `SKILL.md` under 500 lines, detail in `references/`, cross-references one level deep.
- **Frontmatter** — folded block scalar (`>`) for multi-line descriptions, quote special characters.
- **Error level tagging** — `[spec]` for specification rules, `[platform: X]` for platform restrictions, `[foundry]` for conventions.

## Review Guidance

Detailed review rules are in `.github/instructions/`:

| File | Applies To | Focus |
|---|---|---|
| `.github/copilot-instructions.md` | All files | Agent Skills spec compliance, architecture |
| `.github/instructions/markdown.instructions.md` | `**/*.md` | Documentation quality, description triggers |
| `.github/instructions/scripts.instructions.md` | `scripts/**/*.py` | Code quality, stdlib-only, type hints |

Automated validation (`validate_skill.py`, `audit_skill_system.py`) handles many frontmatter, naming, line-count, and structural checks. Manual review still verifies markdown file-reference conventions (file-relative resolution per `skill-system-foundry/references/path-resolution.md`, including the `../../<dir>/<file>` external-reference syntax used from capabilities), path validity, progressive disclosure, description quality, architecture justification, and semantic consistency.

## Release Process

Version lives in three files that must agree: `skill-system-foundry/SKILL.md` frontmatter (`metadata.version`, canonical), `.claude-plugin/plugin.json`, and `.claude-plugin/marketplace.json`. The version-consistency rule in `audit_skill_system.py` fails the repo-root audit if they drift. Tags mirror as `vX.Y.Z`.

Releases are automated: dispatch the `release-prep.yaml` workflow with the target version and it bumps the three manifests, prepends the changelog, dry-builds the bundle, opens the release PR as oss-release-bot, has oss-automation-bot approve it, and auto-merges on green; `release-on-merge.yaml` then tags the merge commit and `release.yaml` builds the bundle and creates the GitHub Release with the zip + SHA256 attached at creation. The manual tooling below is what that workflow runs internally, and the path to use when dispatching is unavailable (offline, or regenerating a past release). Run full validation and tests before tagging by hand.

Bump all three manifest files in lockstep with `scripts/bump_version.py`:

```sh
python scripts/bump_version.py NEXT_VERSION --dry-run   # preview the plan and changelog probe
python scripts/bump_version.py NEXT_VERSION             # write the three files and prepend the changelog
```

The script rejects invalid semver, equal versions, and downgrades (unless `--allow-downgrade` is passed), refuses to run when the three files already disagree, and probes the changelog generator in `--dry-run` mode before touching disk. The changelog step below is only needed when calling the generator directly (for example, to regenerate a past release).

When publishing a release **by hand** — the dispatch path generates release notes from the matching `CHANGELOG.md` section automatically — paste the body from [`.github/RELEASE_NOTES_TEMPLATE.md`](.github/RELEASE_NOTES_TEMPLATE.md) and replace every `{VERSION}` placeholder with the release number. Generate the changelog section using the checklist below.

1. **Preview** the section for the exact commit you intend to tag. Substitute the previous tag and the new release number (e.g., `--since v1.1.0 --version 1.2.0`) — not SemVer build metadata like `+1`. Pin `--until` so the range cannot drift between the preview and the write.

   Unix-like shells:

   ```sh
   python scripts/generate_changelog.py --since vPREVIOUS_VERSION --version NEXT_VERSION --until "$(git rev-parse HEAD)" --in-place --dry-run
   ```

   PowerShell:

   ```powershell
   python scripts/generate_changelog.py --since vPREVIOUS_VERSION --version NEXT_VERSION --until "$(git rev-parse HEAD)" --in-place --dry-run
   ```

2. **Reclassify** any commits reported on stderr as `unmapped — review manually`:
   - add their first-word verb to `scripts/lib/changelog.yaml`, or
   - reword the commit subject.

3. **Write** `CHANGELOG.md` only after the preview is clean. For a version whose tag does not yet exist, pass `--date YYYY-MM-DD` so the file gets a deterministic stamp, then commit the updated `CHANGELOG.md` before tagging.

   Unix-like shells:

   ```sh
   python scripts/generate_changelog.py --since vPREVIOUS_VERSION --version NEXT_VERSION --until "$(git rev-parse HEAD)" --date YYYY-MM-DD --in-place
   ```

   PowerShell:

   ```powershell
   python scripts/generate_changelog.py --since vPREVIOUS_VERSION --version NEXT_VERSION --until "$(git rev-parse HEAD)" --date YYYY-MM-DD --in-place
   ```

4. **Expected failure modes:**
   - `--in-place` refuses with exit 3 while any commit remains unmapped.
   - `--in-place` refuses with `error:` and exit 2 if `--date` is omitted for a version whose tag does not yet exist.
   - Previews (stdout and `--in-place --dry-run`) keep the today-fallback for date.

5. **Retrospective regeneration** (the version tag already exists) does not need `--date` or `--until`. The generator uses the annotated tag's tagger date, falling back to the tagged commit's committer date for lightweight tags, so rebased or cherry-picked commits do not produce a stale author date.
