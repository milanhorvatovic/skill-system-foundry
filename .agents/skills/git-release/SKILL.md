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

## Dispatch-Driven Prep (Preferred)

The `Release prep` workflow (`.github/workflows/release-prep.yml`) is the primary release-prep path. Trigger it from the GitHub Actions UI (or `gh workflow run release-prep.yml -f version=X.Y.Z`):

1. Dispatch the workflow with the target version (`X.Y.Z`, no leading `v`, no prerelease).
2. The workflow creates `release/v<X.Y.Z>`, runs the `bump_version.py` helper (manifest lockstep), prepends a generated section to `CHANGELOG.md`, runs `validate_skill.py` and `audit_skill_system.py` (the latter from repo root, which fires the version-drift rule), runs the full test matrix via the reusable `python-tests.yaml`, and opens a PR titled `Release v<X.Y.Z>`.
3. Review the PR. The PR body lists any manual follow-ups (notably: edit `.agents/skills/git-release/SKILL.md` prose if any examples reference an outdated release).
4. Re-trigger CI on the PR by closing and reopening it (GitHub does not fire PR workflows for PRs opened by `GITHUB_TOKEN`).
5. Merge the PR to `main`.
6. Tag and publish:
   ```bash
   gh release create v<X.Y.Z> --generate-notes
   ```
   The post-merge `release.yml` workflow bundles the zip, computes the SHA256 checksum, and uploads both as release assets.

The workflow exposes a `dry_run` input that runs validation, bump, changelog generation, validate, and audit but skips the push and the PR — useful to verify a target version's gates before committing to a real prep.

## Manual Release Checklist (Fallback)

Use this path when the dispatch workflow is unavailable (for example, when running offline against a pre-tag commit, or when retrospectively regenerating a past release).

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

Use the `bump_version.py` helper (under the repo's top-level `./scripts/`) to update all three manifest files (SKILL.md, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`) in lockstep:

```bash
python scripts/bump_version.py 1.1.0 --dry-run   # preview
python scripts/bump_version.py 1.1.0             # write
```

The `audit_skill_system.py` version-drift rule will fail if these three files disagree, so editing only `SKILL.md` is no longer sufficient.

### Step 2.5: Prepend the Changelog Section

Use the `generate_changelog.py` helper (also under the repo's top-level `./scripts/`) to add a new release section to `CHANGELOG.md`. See the "Release Process" section of `CLAUDE.md` for the full preview-then-write checklist; the short form is:

```bash
PREV=$(git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*')
python scripts/generate_changelog.py --since "$PREV" --version 1.1.0 \
  --until "$(git rev-parse HEAD)" --date "$(date -u +%Y-%m-%d)" --in-place
```

The `--match` glob filters `git describe` to release-shaped tags so a stray non-release tag (debug, hotfix experiment) cannot widen or narrow the changelog range — the dispatch workflow uses the same glob for the same reason.

Reclassify any commits the generator reports on stderr as `unmapped — review manually` (either by adding their first-word verb to the generator's `changelog.yaml` config or by rewording the commit subject) before re-running.

### Step 3: Commit and Push

```bash
git add skill-system-foundry/SKILL.md .claude-plugin/plugin.json .claude-plugin/marketplace.json CHANGELOG.md
git commit -m "Release v1.1.0"
git push origin main
```

Use the commit message format `Release vX.Y.Z` so the changelog generator filters the bump commit out of future regenerations. The full subject is matched against `_RELEASE_COMMIT_RE` in `scripts/generate_changelog.py`, which mirrors the strict SemVer grammar the generator already enforces on `--version` (no leading zeros, optional dot-separated prerelease suffix; build metadata is intentionally unsupported). Off-grammar subjects like `Release v1.2.0 (RC)` or `Release v1.2.3-..1` are deliberately not skipped — they route to `unmapped — review manually` so the operator either fixes the subject or reclassifies it deliberately.

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
| `python-tests.yaml` | Push to `main`, PRs, `workflow_call` | Tests + coverage + badge update; reusable from `release-prep.yml` |
| `shellcheck.yaml` | Changes to `.github/scripts/*.sh` | Lints shell scripts |
| `codex-code-review.yaml` | PRs (non-draft) | AI-assisted code review |
| `release-prep.yml` | `workflow_dispatch` | Bumps version, prepends changelog, opens release PR |
| `release.yml` | Release published | Bundles zip + uploads asset (zip + SHA256) |

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

- Editing only `SKILL.md` and missing `.claude-plugin/plugin.json` or `.claude-plugin/marketplace.json` — the version-drift audit rule will fail. Use `bump_version.py` (or the dispatch workflow) to keep the three files in lockstep.
- Version in the manifests not matching the git tag (e.g., `1.1.0` vs `v1.1.0`).
- Tagging before pushing the bump commit to `main`.
- Creating a release from a branch other than `main`.
- Skipping validation — a broken SKILL.md ships in the zip.
- Forgetting to verify the zip asset downloads and validates after `release.yml` runs.
- Using a commit subject other than `Release vX.Y.Z` for the bump — the changelog generator skip filter only matches that exact shape.
