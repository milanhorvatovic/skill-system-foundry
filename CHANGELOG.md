# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes are tracked in `git log` on `main`; this file is a ledger of shipped versions only.

## [1.2.1] - 2026-05-22

### Added

- Add agent-delegated description activation evaluation (#150)
- Add corpus-coverage audit rules to audit_skill_system (#148)
- Add structural description validation rules to validate_skill (#147)
- Add description-quality evaluation runner (heuristic) (#146)
- Add auto-merge to tool catalog drift workflow (#142)
- Add retain-findings inputs to Codex review workflow (#138)
- Add per-capability discovery_bytes accounting to stats (#130)
- Add scheduled workflow detecting drift between tool catalog and upstream (#128)
- Add bottom-up `allowed-tools` aggregation and capability-frontmatter scoping rules (#127)
- Add orphan-reference audit rule (#126)
- Add stats entry point that reports skill token budgets (#125)
- Add description trigger-phrase heuristic to validate_skill and audit_skill_system (#123)
- Add examples/ directory with three reference skills (#122)
- Add allowed-tools coherence rule and per-harness tool catalogs (#100) (#121)
- Add router-table consistency audit to audit_skill_system (#117)
- Add release-prep dispatch workflow (#116)
- Add version-drift audit and bump_version.py release primitive (#115)
- Add CHANGELOG.md and stdlib changelog generator (#114)
- Emit SHA256 checksum as a release asset alongside the bundle zip (#113)
- Suggest close matches on unknown frontmatter keys (#112)
- Fail CI when workflow uses: lines are not pinned to a commit SHA (#111)
- Add end-to-end integration smoke test for authoring and release pipelines (#110)
- Add YAML 1.2.2 conformance corpus and parser hardening (#95)
- Add prose-YAML fence validation to validate_skill and audit_skill_system (#94)
- Add plain scalar divergence detection to YAML parser (#86)

### Changed

- Recognize angle-bracket link destinations across reference surfaces (#155)
- Sync claude_code tool catalog with upstream tools-reference (#145)
- Apply Agent Skills best-practices guidance to meta-skill content (#144)
- Sync claude_code tool catalog with upstream (#141)
- Make the meta-skill survive cross-platform deployment (#139)
- Switch cross-file reference resolution to standard markdown semantics (#137)
- Move catalog provenance to top-level catalog_provenance key (#135)
- Apply YAML 1.2.2 divergence checks at every parse and emit site (#91)
- Raise coverage above 95% for validate_skill, codex_config, bundling (#88)
- Migrate Codex code review to codex-ai-code-review-action v2 (#84)
- Overhaul Codex code review pipeline (#82)

### Fixed

- Fix release-prep dispatch startup failure and unmapped changelog verbs (#156)
- Fix bundle reference scanner false positives on prose paths (#153)
- Resolve Snyk security findings (SSRF, zip-slip, path-traversal policy) (#152)
- Address remaining review findings from PR #128 and fix three drift-helper defects (#143)

## [1.1.0] - 2026-03-22

### Added

- Missing type hints across `discovery.py`, `frontmatter.py`, `yaml_parser.py`, and `audit_skill_system.py` (#74)
- Internal development skills, `AGENTS.md`, and Claude Code symlinks for contributor workflows (#64)

### Changed

- Restructured the foundry into a router skill with five capabilities (skill-design, validation, migration, bundling, deployment) (#65)
- Raised branch-coverage floor: per-file minimum now enforced in CI (#71, #75)
- Improved test coverage for `audit_skill_system.py` (73% → 99%), `references.py` (76% → 93%), `scaffold.py` (46% → 96%), and `bundle.py` (41% → 98%) (#78, #79, #73, #72)

### Fixed

- `validate_skill.py` now resolves references from the skill root rather than the containing file (#67)

## [1.0.2] - 2026-03-17

### Changed

- Replaced the bundle implementation with a simple zip-based packager (#61)

## [1.0.1] - 2026-03-17

### Fixed

- Shortened `SKILL.md` description to fit the Claude.ai bundle limit (200 chars) (#56, #58)

## [1.0.0] - 2026-03-16

Initial release. Meta-skill for building AI-agnostic skill systems with a two-layer architecture (skills and roles), templates, validation tools, and cross-platform authoring guidance based on the [Agent Skills specification](https://agentskills.io).
