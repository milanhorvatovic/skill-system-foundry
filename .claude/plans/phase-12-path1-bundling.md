# Phase 12: Enhancement #14 — Add Bundling Support for Path 1 Orchestration Skills

## Context

Path 1 coordination skills (standalone skills that sequence roles across domains) work at the project level but cannot currently be packaged as self-contained zip bundles. The bundler rejects cross-skill references, which a coordination skill's roles necessarily contain.

**GitHub Issue:** #14
**Dependencies:** None — standalone. Builds on the bundler infrastructure from Phase 4 (PR #11).
**Status:** Done

**Current state:**
- `scripts/bundle.py` — entry point; pre-validation rejects cross-skill references
- `scripts/lib/references.py` — reference graph traversal; detects cross-skill references
- `scripts/lib/bundling.py` — external file copying and path rewriting infrastructure
- Cross-skill references currently trigger a validation error: bundling a Path 1 skill fails

## Proposed Solution

When bundling a Path 1 coordination skill, inline the referenced domain skills as capabilities:

1. Scan roles referenced by the coordination skill
2. Identify all domain skills those roles reference
3. Copy each referenced skill into `capabilities/<skill-name>/` within the bundle
4. Rename `SKILL.md` → `capability.md` in each inlined skill
5. Rewrite role references to point to the new `capabilities/<skill-name>/capability.md` locations

This transforms a Path 1 coordination skill into a self-contained Path 2 router at bundle time.

### Before bundling (project layout)

```
.agents/
├── skills/
│   ├── release-coordinator/       ← coordination skill (Path 1)
│   │   └── SKILL.md
│   ├── testing/
│   │   ├── SKILL.md
│   │   └── references/
│   └── deployment/
│       ├── SKILL.md
│       └── scripts/
└── roles/
    ├── qa-role.md                 ← references skills/testing/SKILL.md
    └── release-role.md            ← references skills/deployment/SKILL.md
```

### After bundling (archive)

```
release-coordinator/
├── SKILL.md
├── capabilities/
│   ├── testing/
│   │   ├── capability.md          ← was skills/testing/SKILL.md (renamed)
│   │   └── references/
│   └── deployment/
│       ├── capability.md          ← was skills/deployment/SKILL.md (renamed)
│       └── scripts/
└── roles/
    ├── qa-role.md                 ← rewritten: capabilities/testing/capability.md
    └── release-role.md            ← rewritten: capabilities/deployment/capability.md
```

## Sub-tasks

### 12a. Opt-in flag

Add `--inline-orchestrated-skills` flag to `bundle.py`. Without it, cross-skill reference rejection behaviour is unchanged.

### 12b. Skill collection

In `lib/references.py` or a new `lib/inlining.py`: when the flag is set, change cross-skill reference handling from "reject" to "collect for inlining". Walk roles, identify referenced skill roots, return the list.

### 12c. Copy and rename

In `lib/bundling.py`: copy each collected skill directory into `capabilities/<skill-name>/`; rename `SKILL.md` → `capability.md` in the copy.

### 12d. Reference rewriting

Extend the existing rewrite map to cover inlined skills. Rewrite role references from system-root-relative paths to bundle-relative `capabilities/<skill-name>/capability.md` paths.

### 12e. Edge case handling

- Inlined skills that also reference roles (recursive inlining — document as unsupported for now, or implement if straightforward)
- Inlined skills that reference each other (intra-bundle cross-references — detect and rewrite)
- Router skills inlined as capabilities (nested capabilities in the bundle)
- Cycle detection (already handled by the reference scanner — verify it still applies)

### 12f. Tests

Add tests covering:
- Successful Path 1 bundle with `--inline-orchestrated-skills`
- Inlined skill directory structure (capability.md rename, files copied)
- Rewritten role references resolve correctly in the bundle
- Cross-skill references still rejected without the flag

## Verification

1. Bundle a Path 1 coordination skill: `python skill-system-foundry/scripts/bundle.py release-coordinator --system-root .agents --inline-orchestrated-skills`
2. Resulting zip contains `capabilities/<skill-name>/capability.md` for each referenced skill
3. Role references within the bundle point to the correct capability paths
4. Without `--inline-orchestrated-skills`, cross-skill references still fail validation
5. Run: `python -m pytest tests/` — all existing tests pass
