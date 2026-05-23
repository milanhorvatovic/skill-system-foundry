---
name: git-release
description: >
  Guides the release lifecycle for the Skill System Foundry repository —
  version bumping, changelog preparation, GitHub release creation, and
  post-release verification. Triggers when asked to prepare a release,
  bump a version, create a changelog, tag a release, publish a GitHub
  release, verify a release artifact, or update the version in SKILL.md
  frontmatter. Also triggers on questions about semver conventions,
  release workflows, the release.yaml GitHub Action, or distributing
  skill bundles. Use this skill whenever version numbers, releases,
  tags, or distribution are mentioned.
---

# Git Release Skill

Guides the full release lifecycle for the Skill System Foundry — from version bumping through GitHub release creation, automated bundling, and post-release verification.

## Version Convention

The repository uses **semver** (MAJOR.MINOR.PATCH) tracked across three manifest files that must agree:

- `skill-system-foundry/SKILL.md` — `metadata.version` in the frontmatter (the canonical declaration; the other two manifests are bumped to match)
- `.claude-plugin/plugin.json` — `version` field
- `.claude-plugin/marketplace.json` — `version` field for this skill's entry

The canonical `SKILL.md` declaration looks like:

```yaml
metadata:
  author: Milan Horvatovič
  version: 1.0.2
  spec: agentskills.io
```

The `audit_skill_system.py` version-drift rule (run from the repo root) fails the audit when these three files disagree, so editing only `SKILL.md` is no longer sufficient. Always bump them in lockstep via `scripts/bump_version.py` (or the dispatch workflow, which calls it). Git tags mirror the version as `v1.0.2`.

### When to Bump

- **PATCH** (1.0.2 → 1.0.3) — bug fixes in scripts, documentation corrections, reference updates, template fixes
- **MINOR** (1.0.2 → 1.1.0) — new features: new validation checks, new scripts, new reference documents, new template types, new bundling targets
- **MAJOR** (1.0.2 → 2.0.0) — breaking changes: configuration.yaml schema changes that break existing setups, removed validation checks, renamed scripts, changed CLI arguments

## Dispatch-Driven Release (Preferred)

The `Release prep` workflow (`.github/workflows/release-prep.yaml`) is the entry point for a fully automated release. Dispatch it once with the target version; every step after that is hands-off.

1. Dispatch from the GitHub Actions UI, or `gh workflow run release-prep.yaml -f version=X.Y.Z` (`X.Y.Z`, no leading `v`, no prerelease).
2. The workflow creates `release/v<X.Y.Z>`, runs `bump_version.py` (manifest lockstep), prepends a generated `CHANGELOG.md` section, runs `validate_skill.py` and `audit_skill_system.py` (repo root, firing the version-drift rule), dry-builds the distribution bundle via `build-skill-bundle.sh`, runs the full test matrix via the reusable `python-tests.yaml`, and opens a PR titled `Release v<X.Y.Z>` **as oss-release-bot** (so CI fires automatically — no close/reopen needed).
3. oss-automation-bot approves the PR — a bot cannot approve its own PR, so the second identity satisfies the one-review rule — and GitHub auto-merges it once the required checks pass. There is no human step on the green path. To halt a release, close the PR before the checks pass; if Copilot leaves an unresolved review thread, auto-merge waits until it is resolved.
4. On merge, `release-on-merge.yaml` tags the merge commit `v<X.Y.Z>` (as oss-release-bot), and the tag push triggers `release.yaml`, which builds the bundle and creates the GitHub Release with the zip + SHA256 checksum attached at creation.

The workflow exposes a `dry_run` input that runs the input validation, bump, changelog generation, validate, audit, and bundle dry-build but skips the push, the test matrix, and the PR — useful to verify a version's gates before a real prep.

### Identity prerequisites

The auto-merge and publish steps need two GitHub App identities wired as repo variables/secrets. **oss-release-bot** (`RELEASE_CLIENT_ID`, `RELEASE_APP_PRIVATE_KEY`, `RELEASE_APP_BOT_USER_ID`) opens the release PR, tags, and publishes; **oss-automation-bot** (`AUTOMATION_CLIENT_ID`, `AUTOMATION_PRIVATE_KEY`) approves. Every workflow mints via the `client-id` input of `actions/create-github-app-token` (the numeric App ID is the deprecated alternative), so each App's required variable holds its **client ID**, not its App ID. The repo setting "Allow auto-merge" must be on. Because the approval comes from an App, the release PR must touch no CODEOWNER-owned path — otherwise the App approval cannot satisfy the code-owner rule and the merge waits for a human.

## Manual Release Checklist (Fallback)

Use this path when the dispatch workflow is unavailable (for example, when running offline against a pre-tag commit, or when retrospectively regenerating a past release).

### Step 1: Verify Pre-Release State

Confirm the release gate is green on `main` for the commit being tagged **before** publishing the release. `release.yaml` triggers on a `v*.*.*` tag push and does not run tests; `python-tests.yaml` on `main` is the only workflow that gates a release — `shellcheck.yaml` and `codex-code-review.yaml` are advisory and can be red at release time. Check the gate via the GitHub Actions UI or:

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

### Step 4: Tag to Trigger the Release

In the automated model the GitHub Release is created by `release.yaml` on a `v*.*.*` tag push — not by hand. For a manual release, push the tag from `main` under a release identity (so the push triggers workflows; a `GITHUB_TOKEN`-authored tag push would not):

```bash
git tag -a v1.1.0 -m "Release v1.1.0" main
git push origin v1.1.0
```

Do **not** run `gh release create` yourself — `release.yaml` owns release creation, and a tag name is permanent under GitHub immutable releases, so only tag a commit whose release gate is already green (Step 1).

### Step 5: Automated Bundling and Publication

The `release.yaml` workflow triggers on the `v*.*.*` tag push. It:

1. Builds the bundle via `.github/scripts/build-skill-bundle.sh` — the same script `release-prep.yaml` dry-runs pre-merge — producing `dist/skill-system-foundry-v1.1.0.zip` plus its `.sha256` checksum, and asserting the bundle excludes the yaml-conformance corpus.
2. Creates the GitHub Release with the zip and checksum attached **at creation**. Attaching at creation is required under GitHub immutable releases, which forbid adding assets after a release exists (the reason the old create-then-`upload --clobber` model was retired).
3. Uses the matching `CHANGELOG.md` section as the release notes.

The zip contains the entire `skill-system-foundry/` directory — SKILL.md, references, assets, and scripts. No manual intervention is needed after the tag is pushed.

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
| `python-tests.yaml` | Push to `main`, PRs, `workflow_call` | Tests + coverage (reusable from `release-prep.yaml`); read-only |
| `coverage-badge.yaml` | After a successful `Python tests` run on `main` | Publishes the coverage badge |
| `shellcheck.yaml` | Changes to `.github/scripts/*.sh` | Lints shell scripts |
| `codex-code-review.yaml` | PRs (non-draft) | AI-assisted code review |
| `release-prep.yaml` | `workflow_dispatch` | Bumps version, prepends changelog, dry-builds the bundle, opens + auto-merges the release PR |
| `release-on-merge.yaml` | Release PR merged to `main` | Tags the merge commit `v<X.Y.Z>` (oss-release-bot) |
| `release.yaml` | `v*.*.*` tag push | Builds the bundle and creates the Release (zip + SHA256 attached at creation) |

The coverage badge updates automatically via the `coverage-badge.yaml` workflow, which runs after a successful `Python tests` run on `main`, downloads that run's coverage total, and writes `coverage.json` to an orphan `badges` branch that shields.io reads. (Badge publishing was split out of `python-tests.yaml` so the test workflow stays read-only and reusable.)

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
- Forgetting to verify the zip asset downloads and validates after `release.yaml` runs.
- Using a commit subject other than `Release vX.Y.Z` for the bump — the changelog generator skip filter only matches that exact shape.
