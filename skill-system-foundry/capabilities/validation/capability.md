---
allowed-tools: Bash Read
---

# Validation

Validate individual skills against the Agent Skills specification and audit entire skill systems for structural consistency.

## Validating a Single Skill

Run the spec validator against a skill directory before any commit that touches a `SKILL.md` or `capability.md` — treating spec compliance as something to fix later means it never gets fixed ([anti-patterns.md#specification-drift](../../references/anti-patterns.md#specification-drift)):

```bash
python scripts/validate_skill.py <skill-path> [--capability] [--verbose] [--allow-nested-references] [--json]
```

- `--capability`: Validate a capability directory instead of a skill
- `--verbose`: Show all checks, not just failures
- `--allow-nested-references`: Suppress nested-reference warnings (needed for skills that intentionally cross-reference their own reference files)
- `--json`: Machine-readable output
- `--check-prose-yaml`: Validate ```` ```yaml ```` fences in `SKILL.md`, `capabilities/**/*.md`, and `references/**/*.md` (the literal globs configured under `prose_yaml.in_scope_globs` in `../../scripts/lib/configuration.yaml`, resolved from the skill root). See [authoring-principles.md](../../references/authoring-principles.md) for the counter-example convention and [yaml-support.md](../../references/yaml-support.md) for the supported grammar surface.
- `--foundry-self`: Run this skill the way the foundry runs itself (currently implies `--check-prose-yaml`).

For registered skills, the validator checks: frontmatter fields (`name`, `description`), naming conventions (lowercase + hyphens, max 64 chars, matches directory), line counts (recommended max 500 lines), and resource directory structure. In `--capability` mode it only validates the body (line counts, nested-reference rules) and, if frontmatter is present, reports name/description as informational notes without enforcing frontmatter or directory checks.

## Validation Pipeline as Plan-Validate-Execute

The validation surface implements the **plan-validate-execute** pattern (see [authoring-principles.md](../../references/authoring-principles.md#workflows-and-feedback-loops)) across three layers. `validate_skill.py` checks a single skill against the spec (per-skill plan validation). `audit_skill_system.py` checks cross-skill consistency — dependency direction, role composition, orphan references — and, when invoked in distribution-repo mode (root contains both `.claude-plugin/plugin.json` and `skill-system-foundry/SKILL.md`), additionally fires the version-consistency rule that catches manifest drift across `SKILL.md`, `plugin.json`, and `marketplace.json`. Together they let an integrator validate at each scope before any execute step (bundle, deploy, release) acts on the artifacts. Run validation top-down: single skill → system audit → distribution-repo audit before release.

## Auditing System Consistency

Run the automated audit against a deployed system root — the directory containing a `skills/` subdirectory (e.g., `.agents/`):

```bash
python scripts/audit_skill_system.py <system-path> [--verbose] [--allow-orchestration] [--json]
```

- `--allow-orchestration`: Downgrade skill→role references from FAIL to WARN (expected for orchestration skills)

> **Note:** This is not the same as the distribution repository root. For single-skill validation, use `validate_skill.py` instead.

The script checks: spec compliance (frontmatter fields, naming, line counts), dependency direction (no upward references), role composition (2+ skills/capabilities, best-effort heuristic), nesting depth, shared resource usage, manifest presence, and orphan references — every file under `references/` (or `capabilities/<name>/references/`) that no `SKILL.md` and no `capability.md` reaches via the configured body reference patterns is flagged as `WARN`. Suppress legitimate cases (e.g. a reference file staged for an upcoming skill) by listing the path under `orphan_references.allowed_orphans` in `../../scripts/lib/configuration.yaml`. The orphan rule fires the same way in both system-root mode and skill-root mode and is independent of `--allow-nested-references`.

### Manual Checklist

**Spec Compliance:**
- [ ] Every registered skill has `name` + `description` in frontmatter
- [ ] All names match directories, lowercase + hyphens, max 64 chars
- [ ] All descriptions: max 1024 chars, with triggers (third-person recommended)
- [ ] No SKILL.md exceeds 500 lines
- [ ] File references: relative paths, one level deep

**Structure:**
- [ ] No capability registered in discovery layer
- [ ] Shared resources used by 2+ capabilities
- [ ] Max 2 levels deep (router → capability)
- [ ] Roles compose 2+ skills or capabilities (automated — audit warns if < 2)
- [ ] No capability references siblings

**Dependencies:**
- [ ] Direction maintained (no upward references). Exception: orchestration skills (both paths) may reference roles intentionally.
- [ ] All role skill paths valid

**Manifest:**
- [ ] Complete and matches filesystem
- [ ] No phantom entries (orphaned reference files are flagged automatically — see the orphan-reference rule above)

## Description-Quality Evaluation

Structural checks confirm a description is *well-formed*; they do not confirm it *activates* on the right prompts. `evaluate_descriptions.py` measures activation precision and recall against a corpus of positive prompts (should activate the unit) and negative prompts (should not):

```bash
python scripts/evaluate_descriptions.py <corpus-path> [--skill-set <dir>] [--min-precision <f>] [--min-recall <f>] [--split-seed <int>] [--soft] [--json] [--verbose]
```

**Corpus format.** A corpus is one JSON file per discoverable unit, or a directory of them. Each file declares `target` (the unit name), `kind` (`"skill"` or `"capability"`), and `positive` / `negative` prompt lists; optional `min_precision` / `min_recall` override the CLI thresholds. The meta-skill's own corpus lives under `tests/skill-corpus/skill-system-foundry/`; integrators place theirs anywhere and pass the path. The starter template is [assets/description-test-cases/skill.json](../../assets/description-test-cases/skill.json). The loader enforces shape rules (minimum 4 prompts per side, no duplicates, no pos/neg contradiction, length and control-character limits); their thresholds live under `skill.description.evaluation` in [configuration.yaml](../../scripts/lib/configuration.yaml).

**Unit card model.** The scorer matches a prompt against each unit's `name + description` card. A skill's card comes from its `SKILL.md` frontmatter; a capability has no frontmatter `name` / `description`, so its card is the directory name plus the first body paragraph after the `# Heading` in `capability.md`. A capability is scored against its sibling capabilities; a skill against the sibling skills in `--skill-set` (default: the current directory).

**Heuristic scoring.** Pure stdlib, deterministic, free. It selects the highest Jaccard token overlap between the prompt and each candidate card, or `none` below `heuristic_min_overlap`. It runs on every PR with `--soft` — a smoke check on description-vocabulary coverage, not ground truth, since the corpus author also writes the description. Higher-fidelity activation testing against a real model is a separate, opt-in workstream and is intentionally not bundled here, so the meta-skill stays stdlib-only and AI-agnostic.

**Thresholds and exit code.** `--min-precision` / `--min-recall` gate the exit code on the point estimate (the validation half when `--split-seed` is given); `--soft` reports findings but always exits 0. Per-target pairwise confusion (which other unit stole a prompt) is advisory JSON output only.

## Gotchas

- **Specification drift.** Treating spec compliance as something to fix later means it never gets fixed. Run `validate_skill.py` before any commit that touches a `SKILL.md` or `capability.md`. See [anti-patterns.md#specification-drift](../../references/anti-patterns.md#specification-drift).
- **`--allow-nested-references` as a fix, not a waiver.** The flag suppresses the depth warning; it does not make deep references a good idea. Use it only for skills (like this meta-skill) where the cross-reference depth is structurally unavoidable. For new skills, restructure first.
- **Skipping the repo-root release audit.** `audit_skill_system.py` has three modes — system-root (`.agents/` with `skills/` subtree), skill-root (a single skill directory), and distribution-repo (the foundry repo root). The version-consistency rule that catches manifest version drift across `SKILL.md`, `plugin.json`, and `marketplace.json` fires only in distribution-repo mode — when the root contains both `.claude-plugin/plugin.json` AND `skill-system-foundry/SKILL.md`. Skill-root and system-root modes both skip it by design. Always run from the repo root before any release.

## Key Resources

**References** — load by trigger:
- [agentskills-spec.md](../../references/agentskills-spec.md) — read when a validator finding cites a spec rule and the rule itself needs verification.
- [yaml-support.md](../../references/yaml-support.md) — read when a frontmatter or doc-snippet YAML fence triggers a parser error or warning, or when the supported grammar surface is unclear.

**Scripts** — run by trigger:
- [validate_skill.py](../../scripts/validate_skill.py) — run before any commit that touches a `SKILL.md`, `capability.md`, or skill-root frontmatter.
- [audit_skill_system.py](../../scripts/audit_skill_system.py) — run before any release, after adding or removing a skill or role, or to confirm dependency direction and orphan references.
- [evaluate_descriptions.py](../../scripts/evaluate_descriptions.py) — run when adding or revising a skill or capability description, to confirm it activates on the right prompts.
