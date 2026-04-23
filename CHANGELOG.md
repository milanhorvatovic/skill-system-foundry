# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes are tracked in `git log` on `main`; this file is a ledger of shipped versions only.

## [1.1.0] - 2026-03-22

### Added

- Missing type hints across `discovery.py`, `frontmatter.py`, `yaml_parser.py`, and `audit_skill_system.py` (#74)
- Internal development skills, `AGENTS.md`, and Claude Code symlinks for contributor workflows (#64)

### Changed

- Restructured the foundry into a router skill with five capabilities (skill-design, validation, migration, bundling, deployment) (#65)
- Raised branch-coverage floor: per-file minimum now enforced in CI (#71, #75)
- Improved test coverage for `audit_skill_system.py` (73% → 99%), `references.py` (76% → 93%), `scaffold.py` (46% → 96%), and `bundle.py` (41% → 98%) (#78, #79, #73, #72)
- Bumped version to 1.1.0 (#80)

### Fixed

- `validate_skill.py` now resolves references from the skill root rather than the containing file (#67)

## [1.0.2] - 2026-03-17

### Changed

- Replaced the bundle implementation with a simple zip-based packager (#61)

## [1.0.1] - 2026-03-17

### Changed

- Bumped version across all version references (#59)

### Fixed

- Shortened `SKILL.md` description to fit the Claude.ai bundle limit (200 chars) (#56, #58)

## [1.0.0] - 2026-03-16

Initial release. Meta-skill for building AI-agnostic skill systems with a two-layer architecture (skills and roles), templates, validation tools, and cross-platform authoring guidance based on the [Agent Skills specification](https://agentskills.io).
