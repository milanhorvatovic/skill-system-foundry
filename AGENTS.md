# Skill System Foundry

Meta-skill for building AI-agnostic skill systems with a two-layer architecture (skills and roles), templates, validation tools, and cross-platform authoring guidance based on the [Agent Skills specification](https://agentskills.io).

## Project Context

This repository contains **one skill** (`skill-system-foundry/`) and its **test suite** (`tests/`). The skill is a meta-skill — its domain is building other skills. It is not an application. There is no server, no database, no frontend.

**Language:** Python 3.12+ (standard library only — no third-party imports in production code).

**Dev dependency:** `coverage==7.6.1` (test coverage measurement only).

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
│   ├── SKILL.md                     ← entry point (standalone)
│   ├── README.md                    ← skill documentation
│   ├── references/                  ← guidance loaded into context on demand
│   │   ├── authoring-principles.md  ← cross-platform skill writing consensus
│   │   ├── architecture-patterns.md ← standalone vs router decisions
│   │   ├── agentskills-spec.md      ← specification compliance guide
│   │   ├── tool-integration.md      ← tool-specific paths and deployment
│   │   ├── directory-structure.md   ← full layout and conventions
│   │   ├── workflows.md             ← step-by-step creation, migration, deployment, auditing
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
│       └── bundle.py                ← bundle for distribution (zip)
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
├── .claude-plugin/                  ← Claude Code plugin marketplace config
│   ├── plugin.json
│   └── marketplace.json
└── .github/
    ├── scripts/                     ← CI helper scripts (bash + one Node.js)
    ├── workflows/                   ← GitHub Actions CI/CD
    │   ├── python-tests.yaml        ← tests + coverage + badge update (ubuntu + windows)
    │   ├── shellcheck.yaml          ← lints .github/scripts/*.sh
    │   ├── codex-code-review.yaml   ← two-job Codex PR review pipeline
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
- **Validation rules in YAML** — limits, patterns, and reserved words live in `scripts/lib/configuration.yaml`. Never hardcode validation rules in Python.
- **`os.path` only** — do not use `pathlib`. Do not mix the two.
- **Type hints on all function signatures** — use builtin generics (`list`, `dict`, `tuple`) and `X | None`.
- **`encoding="utf-8"` on all `open()` calls.**
- **Error levels from constants** — use `LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO` from `lib/constants.py`, never hardcode strings.
- **Validation functions return `(errors, passes)` tuples** — never raise exceptions for validation failures.
- **Shell scripts use `set -euo pipefail`** and validate environment variables at the top with `${VAR:?}`.
- **Actions pinned to commit SHAs** — not tags.
- **All script entry points support `--json`** — machine-readable output via `to_json_output()` from `lib/reporting.py`.

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
python scripts/validate_skill.py . --allow-nested-references --verbose
python scripts/audit_skill_system.py .
```

The `--allow-nested-references` flag is needed because this meta-skill intentionally uses nested references. One warning about a missing `skills/` directory from the audit is expected in this distribution repository.

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

- **Entry points** (`scripts/*.py`) — thin wrappers: argument parsing, output formatting, `sys.exit()`. Delegate everything to `scripts/lib/`.
- **Library modules** (`scripts/lib/*.py`) — domain logic. No `print()` or `sys.exit()` except in dedicated output helpers (`reporting.py`).
- **Constants** (`scripts/lib/constants.py`) — structural constants in Python, validation rules loaded from `configuration.yaml`. All YAML values are returned as strings by the custom parser — convert with `int()` in `constants.py`.
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

Automated validation (`validate_skill.py`, `audit_skill_system.py`) handles mechanical checks. Manual review focuses on description quality, progressive disclosure, architecture justification, and semantic consistency.

## Release Process

Version lives in `skill-system-foundry/SKILL.md` frontmatter (`metadata.version`). Tags mirror as `vX.Y.Z`. The `release.yml` workflow auto-bundles a zip and uploads it as a release asset. Run full validation and tests before tagging.
