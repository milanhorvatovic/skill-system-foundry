---
name: git-release
description: >
  Guides the release lifecycle for the Skill System Foundry repository —
  version bumping, changelog preparation, GitHub release creation, and
  post-release verification. Triggers when asked to prepare a release,
  bump a version, create a changelog, tag a release, publish a GitHub
  release, verify a release artifact, or update the version in SKILL.md
  frontmatter. Also triggers on questions about semver conventions,
  release workflows, the release.yml GitHub Action, or distributing
  skill bundles. Use this skill whenever version numbers, releases,
  tags, or distribution are mentioned.
---

# Git Release Skill

Guides the full release lifecycle for the Skill System Foundry — from version bumping through GitHub release creation, automated bundling, and post-release verification.

## Version Convention

The repository uses **semver** (MAJOR.MINOR.PATCH) tracked in the `metadata.version` field of `skill-system-foundry/SKILL.md` frontmatter:

```yaml
metadata:
  author: Milan Horvatovič
  version: 1.0.2
  spec: agentskills.io
```

This is the single source of truth for the current version. Git tags mirror it as `v1.0.2`.

### When to Bump

- **PATCH** (1.0.2 → 1.0.3) — bug fixes in scripts, documentation corrections, reference updates, template fixes
- **MINOR** (1.0.2 → 1.1.0) — new features: new validation checks, new scripts, new reference documents, new template types, new bundling targets
- **MAJOR** (1.0.2 → 2.0.0) — breaking changes: configuration.yaml schema changes that break existing setups, removed validation checks, renamed scripts, changed CLI arguments

## Release Checklist

### Step 1: Verify Pre-Release State

Confirm the release gate is green on `main` for the commit being tagged **before** publishing the release. `release.yml` triggers on `release: published` and does not run tests; `python-tests.yaml` on `main` is the only workflow that gates a release — `shellcheck.yaml` and `codex-code-review.yaml` are advisory and can be red at release time. Check the gate via the GitHub Actions UI or:

```bash
# Latest python-tests.yaml run on main — conclusion must be success
# and headSha must match the commit you are about to tag.
gh run list --workflow python-tests.yaml --branch main --limit 1 \
  --json conclusion,headSha,databaseId,displayTitle
git rev-parse main
```

Do not publish a release unless the latest `main` run of `python-tests.yaml` is green **and** its `headSha` equals the commit being tagged. If `main` has advanced past the commit you intend to release, either wait for the run on the newer tip to finish (and retarget the tag to that tip), or re-run the workflow on the exact commit via `gh run rerun <databaseId>`. This is a procedural gate, not a workflow gate.

Then run validation and tests locally to confirm the codebase is clean:

```bash
# Self-validate the meta-skill
cd skill-system-foundry
python scripts/validate_skill.py . --allow-nested-references

# Audit (expect one warning about missing skills/ directory — this is normal
# for the distribution repository)
python scripts/audit_skill_system.py .

# Run full test suite with coverage
cd ..
python -m coverage run -m unittest discover -s tests -p "test_*.py" -v
python -m coverage report
```

All validation checks must pass (zero failures). Coverage must meet the 70% threshold configured in `.coveragerc`. The suite includes an end-to-end integration smoke test (`tests/test_integration_pipeline.py`) that guards both the `scaffold → validate → bundle → unzip → validate` authoring pipeline and the `zip -r` release artifact shape.

### Step 2: Bump the Version

Update `metadata.version` in `skill-system-foundry/SKILL.md`:

```yaml
metadata:
  author: Milan Horvatovič
  version: 1.1.0       # ← update this
  spec: agentskills.io
```

This is the only file where the version lives. There is no `pyproject.toml`, `setup.py`, or `package.json` to synchronize.

### Step 3: Commit and Push

```bash
git add skill-system-foundry/SKILL.md
git commit -m "Update version to 1.1.0"
git push origin main
```

Use the commit message format: `Update version to X.Y.Z`.

### Step 4: Create the GitHub Release

Create a tag and release via the GitHub CLI or web UI:

```bash
gh release create v1.1.0 \
  --title "v1.1.0" \
  --notes "Release notes here" \
  --target main
```

Or through the GitHub web UI: Releases → Draft a new release → Tag: `v1.1.0` → Target: `main`.

### Step 5: Automated Bundling

The `release.yml` workflow triggers automatically on release publication. It:

1. Checks out the tagged commit
2. Creates a zip archive: `dist/skill-system-foundry-v1.1.0.zip`
3. Uploads it as a release asset using `gh release upload --clobber`

The zip contains the entire `skill-system-foundry/` directory — SKILL.md, references, assets, and scripts. This is the distribution artifact for manual installation.

No manual intervention is needed after creating the release.

### Step 6: Post-Release Verification

After the workflow completes:

1. **Check the release page** — verify the zip asset appears under the release
2. **Download and inspect** — unzip and run validation on the bundled skill:
   ```bash
   unzip skill-system-foundry-v1.1.0.zip
   cd skill-system-foundry
   python scripts/validate_skill.py . --allow-nested-references
   ```
3. **Verify installation paths** — confirm the skill installs correctly:
   ```bash
   npx skills add milanhorvatovic/skill-system-foundry
   ```

## Release Notes Format

Structure release notes by change type:

```markdown
## What's Changed

### Added
- New validation check for X (#15)
- Reference document for Y

### Fixed
- False positive in name validation for single-character names (#12)
- Broken cross-reference in architecture-patterns.md

### Changed
- Increased max_body_lines from 400 to 500 in configuration.yaml
```

Keep entries concise — one line per change, with issue/PR references where applicable.

## CI Pipeline and Releases

The full CI pipeline for a release involves multiple workflows:

| Workflow | Trigger | What It Does |
|---|---|---|
| `python-tests.yaml` | Push to `main`, PRs | Tests + coverage + badge update |
| `shellcheck.yaml` | Changes to `.github/scripts/*.sh` | Lints shell scripts |
| `codex-code-review.yaml` | PRs (non-draft) | AI-assisted code review |
| `release.yml` | Release published | Bundles zip + uploads asset |

The coverage badge updates automatically on pushes to `main` via the `update-badge` job. It writes `coverage.json` to an orphan `badges` branch, which shields.io reads.

## Distribution Channels

After a release, the skill is available through:

1. **npx skills** — `npx skills add milanhorvatovic/skill-system-foundry`
2. **Claude Code Plugin** — `/plugin marketplace add milanhorvatovic/skill-system-foundry`
3. **Gemini CLI** — `gemini skills link milanhorvatovic/skill-system-foundry`
4. **GitHub Release zip** — download from the Releases page
5. **Manual copy** — clone the repo and copy `skill-system-foundry/` directory

Channels 1-3 pull from the repository directly (latest `main`). Channel 4 is versioned and immutable. Channel 5 is unversioned.

## Bundle Script (Optional Pre-Release)

For testing distribution before creating a release, use the bundle script:

```bash
cd skill-system-foundry
python scripts/bundle.py . --output ../dist/skill-system-foundry.zip
```

The bundle script applies stricter validation than the release workflow — it checks description length against platform-specific limits (Claude enforces 200 chars vs the spec's 1024).

## Common Mistakes

- Forgetting to bump `metadata.version` in SKILL.md before tagging
- Version in SKILL.md not matching the git tag (e.g., `1.1.0` vs `v1.1.0`)
- Tagging before pushing the version bump commit to `main`
- Creating a release from a branch other than `main`
- Not running validation before release — a broken SKILL.md ships in the zip
- Writing release notes that reference internal details instead of user-facing changes
- Forgetting to verify the zip asset downloads and validates after the workflow runs
