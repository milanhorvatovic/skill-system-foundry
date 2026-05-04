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
│       └── yaml_conformance_report.py  ← run the YAML 1.2.2 corpus
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
    │   └── release.yml              ← bundles zip + uploads release asset
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
- **Error levels from constants** — use `LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO` from `lib/constants.py`, never hardcode strings.
- **Validation functions return `(errors, passes)` tuples** — never raise exceptions for validation failures.
- **Shell scripts use `set -euo pipefail`** and validate environment variables at the top with `${VAR:?}`.
- **Actions pinned to commit SHAs** — not tags.
- **Meta-skill script entry points support `--json`** — entry points under `skill-system-foundry/scripts/` must provide machine-readable output via `to_json_output()` from `lib/reporting.py`. Repo-infrastructure scripts under the top-level `scripts/` tree (e.g., `scripts/generate_changelog.py`) are exempt: their output is consumed directly by humans during maintenance tasks, and line-oriented stderr diagnostics already cover the tooling surface.

## Development Workflow

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

The repo root has no `skills/` tree and no top-level `SKILL.md`, so this invocation runs in distribution-repo mode and emits one expected `WARN: No skills/ directory under system root — ran partial audit`. Per-skill rules (including the router-table rule) are skipped under that invocation — it only adds the repo-level version-consistency check on top of what the `cd skill-system-foundry` invocation already covers. To audit the meta-skill's own router table, the `cd skill-system-foundry && python scripts/audit_skill_system.py .` invocation above (skill-root mode) is the canonical self-check.

#### Flag behavior

| Flag | Effect | When to use |
|---|---|---|
| `--check-prose-yaml` | Validates ```` ```yaml ```` fences in `SKILL.md`, `capabilities/**/*.md`, and `references/**/*.md`. Findings route to the existing FAIL/WARN/INFO stream and the `yaml_conformance.doc_snippets` JSON slot. | When fixing or adding documentation that contains YAML examples. |
| `--foundry-self` | Implies `--check-prose-yaml`. Runs the target skill the way the foundry runs itself. On `audit_skill_system` it is a mode switch — the prose check runs across every scanned skill. | Self-validation of the meta-skill, or to run an integrator skill with foundry-equivalent strictness. |
| `--allow-nested-references` | Suppresses the nested-reference depth warning. Required for skills that intentionally cross-reference their own reference files. | Any meta-skill or template-rich skill where reference graphs span more than one level. |
| `--verbose` | Prints per-file progress messages for the prose check (`Checking prose YAML: <path> (<N> fences)`) and shows passing checks otherwise. Silent under `--json`. | Local debugging / triage. |

In addition, `python scripts/yaml_conformance_report.py` runs the YAML 1.2.2 conformance corpus and emits the same `yaml_conformance.corpus` JSON slot for tooling consumers; exit 0 on all-pass, non-zero on any failure.

### Measuring the Meta-Skill's Token Budget

```bash
cd skill-system-foundry
python scripts/stats.py . --json
```

`stats.py` reports two byte-based proxies for a skill's context cost: `discovery_bytes` (the sum of every YAML frontmatter block the harness reads at discovery time — `SKILL.md` plus each `capabilities/<name>/capability.md` that declares one) and `load_bytes` (SKILL.md plus every capability and reference file reachable through markdown links, backticks, and bare router-table path cells). Every discovery-relevant `files[]` row — `SKILL.md` and each `capabilities/<name>/capability.md` — carries a `discovery_bytes` key with its own contribution (`0` when the file is silent on frontmatter); non-discovery rows (capability-local references and shared references) omit the key entirely. Consumers can reconstruct the breakdown without re-reading any files, and the human-readable report shows the breakdown directly when at least one capability declares frontmatter. Files under `scripts/` and `assets/` are excluded — they are not loaded into the model's context during skill use. Bytes are not tokens and are not comparable across models or tokenizers; treat the number as a deterministic on-disk signal for tracking the relative cost of authoring decisions over time. Counts are taken from raw on-disk UTF-8 bytes, so CRLF terminators on Windows checkouts produce higher numbers than the same content on POSIX checkouts.

A missing or unreadable `SKILL.md` is a FAIL — that includes the file not existing, an I/O error during read, or invalid UTF-8 in either the frontmatter scan or the body. Everything else recovers: broken references, parent-traversal attempts, external references, undecodable referenced files, and frontmatter parse errors (in `SKILL.md` or in any capability entry) are surfaced as WARN/INFO findings while the run still emits a usable metric. A capability that is silent on frontmatter is legal and produces no finding — its per-row `discovery_bytes` is simply `0`.

### Detecting Tool Catalog Drift

The hand-maintained Claude Code tool catalog at `skill.allowed_tools.catalogs.claude_code` in `skill-system-foundry/scripts/lib/configuration.yaml` drifts as Claude Code adds, renames, or retires tools. A weekly scheduled workflow (`.github/workflows/tool-catalog-drift.yaml`, helper at `.github/scripts/tool-catalog-drift.py`) compares the catalog against the canonical upstream tools reference at the URL recorded in `skill.allowed_tools.catalog_provenance.claude_code.source_url` and force-pushes a single rolling PR (`chore/tool-catalog-drift`) when drift is detected. Additions are auto-applied; removals are surfaced in the PR body as advisory candidates only — verify each name before deleting.

To run the sweep locally:

```bash
python .github/scripts/tool-catalog-drift.py --dry-run
python .github/scripts/tool-catalog-drift.py --dry-run --json
```

`--dry-run` exits 0 on no drift, 1 on drift detected; default mode mutates `configuration.yaml` and bumps `skill.allowed_tools.catalog_provenance.claude_code.last_checked` only when there are additions to apply. Removals-only drift leaves the YAML untouched (removals are advisory and never auto-applied); the workflow surfaces them through the PR body via an empty commit.

The helper tracks the `claude_code` catalog only. The `catalogs.<harness>` YAML structure preserves room for a future second harness, but adding one is not a YAML-only edit — `run` and `parse_catalog` in `.github/scripts/tool-catalog-drift.py` currently process the single default harness, so a future extension requires helper changes (and may need workflow updates for per-harness PR titles or reporting).

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

Version lives in three files that must agree: `skill-system-foundry/SKILL.md` frontmatter (`metadata.version`, canonical), `.claude-plugin/plugin.json`, and `.claude-plugin/marketplace.json`. The version-consistency rule in `audit_skill_system.py` fails the repo-root audit if they drift. Tags mirror as `vX.Y.Z`. The `release.yml` workflow auto-bundles a zip and uploads it as a release asset. Run full validation and tests before tagging.

Bump all three manifest files in lockstep with `scripts/bump_version.py`:

```sh
python scripts/bump_version.py NEXT_VERSION --dry-run   # preview the plan and changelog probe
python scripts/bump_version.py NEXT_VERSION             # write the three files and prepend the changelog
```

The script rejects invalid semver, equal versions, and downgrades (unless `--allow-downgrade` is passed), refuses to run when the three files already disagree, and probes the changelog generator in `--dry-run` mode before touching disk. The changelog step below is only needed when calling the generator directly (for example, to regenerate a past release).

When publishing the GitHub Release, paste the body from [`.github/RELEASE_NOTES_TEMPLATE.md`](.github/RELEASE_NOTES_TEMPLATE.md) and replace every `{VERSION}` placeholder with the release number. Generate the changelog section using the checklist below.

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
