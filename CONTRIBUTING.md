# Contributing to Skill System Foundry

Thank you for your interest in contributing. This document explains how to get involved and what to expect.

## Ways to Contribute

**Report issues.** Found a bug in the validation scripts, an inaccuracy in the documentation, or a broken cross-reference? Open an issue in this repository's **Issues** tab with a clear description and steps to reproduce.

**Suggest improvements.** Have an idea for a new anti-pattern, a missing workflow, or better template defaults? Open an issue to discuss it before writing code.

**Submit pull requests.** Bug fixes, documentation improvements, and enhancements are welcome. For anything beyond a small fix, open an issue first to align on the approach.

**Share feedback.** Using Skill System Foundry in your project? Feedback on real-world usage helps prioritize improvements.

## Before You Start

1. Read the [README](README.md) to understand the architecture and design principles.
2. Read the [skill-level documentation](skill-system-foundry/README.md) for the meta-skill's structure and conventions.
3. Check existing issues in this repository to avoid duplicating work.

## Development Setup

**Requirements:** Python 3.12+ (standard library only — no external dependencies).

```bash
git clone https://github.com/milanhorvatovic/skill-system-foundry.git
cd skill-system-foundry
```

Verify the setup by running validation on the meta-skill itself:

```bash
cd skill-system-foundry
python3 scripts/validate_skill.py . --allow-nested-references
python3 scripts/audit_skill_system.py .
```

Both commands should complete successfully. In this distribution repository, `audit_skill_system.py .` currently emits one expected warning about a missing `skills/` directory.

## Project Structure

```
.
├── README.md                        ← Repository overview and architecture
├── CONTRIBUTING.md                  ← This file
├── LICENSE                          ← MIT license
└── skill-system-foundry/            ← The meta-skill
    ├── SKILL.md                     ← Router entry point
    ├── README.md                    ← Skill documentation
    ├── references/                  ← Guidance documents
    ├── assets/                      ← Templates for scaffolding
    └── scripts/                     ← Validation, scaffolding, and bundling tools
```

Changes typically fall into one of these areas:

| Area | Files | Validation |
|------|-------|------------|
| Documentation | `README.md`, `skill-system-foundry/README.md` | Manual review |
| References | `skill-system-foundry/references/*.md` | `validate_skill.py` |
| Templates | `skill-system-foundry/assets/*` | Manual review |
| Scripts | `skill-system-foundry/scripts/**/*.py` | `validate_skill.py`, `audit_skill_system.py`, `bundle.py` |
| Spec compliance | `skill-system-foundry/SKILL.md`, frontmatter | `validate_skill.py` |

## Guidelines

### Documentation

The project follows a **conciseness-first** principle. The model is already smart — only add context it does not already have.

- Challenge every paragraph: "Does the model really need this?"
- Use third person in skill descriptions ("Validates skills" not "I validate skills")
- Keep cross-references one level deep from `SKILL.md` (see [anti-patterns](skill-system-foundry/references/anti-patterns.md))
- Preserve the existing progressive disclosure structure (metadata → instructions → resources)

### Scripts

All scripts use the Python standard library only. Do not introduce external dependencies.

- Follow the existing code style (see existing files in `scripts/lib/` for patterns)
- Handle errors explicitly with helpful messages
- Document magic numbers with inline comments
- Keep shared logic in `scripts/lib/`; keep entry points in `scripts/`

### Templates

Templates in `assets/` contain placeholder values and inline comments. When modifying templates:

- Preserve placeholder markers so users know what to replace
- Keep templates minimal — provide a starting point, not a finished product
- Ensure templates remain valid against `validate_skill.py` after placeholder replacement

### Commit Messages

Use a short summary line describing **what** changed:

```
Update <component> and <component>
Add <new-thing> to <location>
Fix <issue> in <component>
```

## Pull Request Process

1. **Fork and branch.** Create a feature branch from `main`.

2. **Make your changes.** Keep commits focused — one logical change per commit.

3. **Validate.** Run these from the `skill-system-foundry/` directory:
   ```bash
   python3 scripts/validate_skill.py . --allow-nested-references
   python3 scripts/audit_skill_system.py .
   ```
   No failures are acceptable. In this distribution repository, one warning about a missing `skills/` directory is expected for `audit_skill_system.py .`; additional warnings should be documented.

4. **Self-review.** Check that your changes:
   - Follow the documentation and code guidelines above
   - Do not break existing cross-references between files
   - Maintain consistency with existing terminology and formatting

5. **Open the PR.** Include:
   - A clear description of what changed and why
   - Which area of the project is affected (documentation, scripts, templates, etc.)
   - How you validated the changes

6. **Label the release impact.** Apply exactly one `release:` label. The line between `patch` and `skip` is "does anything user-facing ship?":
   - `release: major` — a breaking change to the published meta-skill (a removed or renamed capability or script, or a backwards-incompatible change to a validation rule or script interface)
   - `release: minor` — a new, backwards-compatible feature
   - `release: patch` — a user-facing fix or change worth a release note (bug fix, corrected/clarified skill docs)
   - `release: skip` — nothing user-facing ships, so it does not influence the next version (CI, tests, internal tooling, repo meta, contributor docs)

   These labels are the input to label-driven release automation: when a release is prepared without an explicit version, `release-prep.yaml` computes the next version from the `release:` labels of PRs merged since the last tag (highest bump wins; `skip` contributes nothing). Labeling does not block your PR from merging today — `verify-pr-release-label` is report-only — but an unlabeled or ambiguously labeled merged PR blocks the next computed release until it is fixed (the check becomes required once the labeling habit is established). Dependabot PRs are labeled automatically by `dependabot-release-label.yaml` (see [Dependency Updates](#dependency-updates)); label human-authored PRs by hand.

7. **Respond to feedback.** PRs may require revisions before merging.

## What Happens Next

Maintainers review PRs on a best-effort basis. Smaller, focused PRs are reviewed faster than large ones. If your PR has not received feedback after a reasonable time, a polite ping in the PR comments is welcome.

## Dependency Updates

Dependabot opens grouped pull requests weekly for the GitHub Actions and Python dev dependencies. Each ecosystem groups minor and patch bumps into one rolling PR; semver-major bumps split into standalone PRs. Every Dependabot PR is labeled automatically — `dependencies`, its ecosystem, and a `release:` level reconciled by `dependabot-release-label.yaml`.

### Auto-merge

`dependabot-auto-merge.yaml` merges a Dependabot PR hands-off once its required checks pass and a code-owner approval is in place. It deliberately **holds** a PR for manual review when any of the following is true:

- the effective update-type is **semver-major** (these arrive as standalone PRs);
- the bump touches a **trust-boundary action** that runs with secrets in scope — currently `actions/create-github-app-token` (mints the App private key) and `milanhorvatovic/codex-ai-code-review-action` (runs with `OPENAI_API_KEY`). When a new action-level trust-boundary dependency is added, extend the exclude list in `.github/dependabot.yaml`, the auto-merge guard in `.github/workflows/dependabot-auto-merge.yaml`, and the `check_dependency_gates` guard in `.github/workflows/dependabot-reconciler.yaml`;
- the PR carries **`trust-boundary`** or **`security-review-required`**. Apply either to any dependency PR you want a human to review before it merges; applying one to an already-armed PR disarms the pending auto-merge.

The repository variable **`DEPENDABOT_AUTOMERGE_ENABLED`** is the kill-switch: auto-merge acts only when it is exactly `true`. Unset or any other value disables it, and the PR waits for a manual merge.

A held PR is merged the normal way after review. Note that an unresolved **Copilot review comment** parks a PR — the `main` ruleset requires review-thread resolution — so resolve the threads (or comment `@dependabot recreate`) to let auto-merge proceed.

When the grouping or label configuration changes, existing open Dependabot PRs keep their old shape until recreated — comment `@dependabot recreate` (or close them) so they adopt the new configuration.

### Reconciler

`dependabot-auto-merge.yaml` only sees `pull_request` events, so a PR can stall in a state no `pull_request` event re-fires on. `dependabot-reconciler.yaml` is the backstop that re-drives every open Dependabot PR each tick. It runs reactively (when the auto-merge workflow completes, and on pushes to `main`), hourly on a schedule, and on manual `workflow_dispatch`. It covers three cases the auto-merge workflow cannot: a PR that goes **`BEHIND`** when another PR in the batch merges (the `main` ruleset requires branches to be up to date, and GitHub does not auto-rebase in that mode); an approval **dismissed** by the reconciler's own branch-update push (the ruleset dismisses stale reviews on push); and an auto-merge enable that **dropped or silently failed**.

It never merges synchronously itself — it updates `BEHIND` branches, posts a `@dependabot recreate` on a real conflict, restores a dismissed approval on an already-armed PR, and enables auto-merge on an approved + mergeable PR. It applies the **same holds** as the auto-merge workflow (semver-major, the trust-boundary actions, and the `trust-boundary` / `security-review-required` labels), and it honors the **`DEPENDABOT_AUTOMERGE_ENABLED`** kill-switch for those merge-advancing actions — while the switch is off it still updates `BEHIND` branches and posts recreate nudges, but it does not re-approve or arm. A genuinely stuck reconciliation (a silent auto-merge enable, or a failed defensive disable on a security-review PR) fails the run red rather than passing silently.

The reconciler **restores** a PR the auto-merge workflow already approved or armed; it does not **initiate** the first approval. If a Dependabot PR is open, unapproved, and unarmed — for example because its initial `Dependabot Auto-Merge` run dropped entirely and no later push re-fired it — the reconciler intentionally leaves it for manual triage. Recover it by re-running the `Dependabot Auto-Merge` workflow against that PR, or by pushing to (or `@dependabot rebase`-ing) the branch so a fresh `synchronize` re-fires the auto-merge path.

Because the reconciler runs outside the Dependabot event context, its re-approval reads **`CODEOWNER_APPROVER_TOKEN` from the Actions secret store** — the auto-merge workflow reads the same PAT from the Dependabot secret store. The single code-owner PAT must therefore be stored under that name in **both** stores (workflows triggered by Dependabot cannot read Actions secrets, and vice versa). Rotate both copies together.

## Scope

Skill System Foundry is intentionally focused on the **structural and architectural** concerns of organizing AI-agnostic skill systems. Contributions that stay within this scope are most likely to be accepted.

Out of scope:
- Domain-specific skill content (e.g., a complete project management skill)
- Tool-specific features that do not generalize across the supported tool landscape
- External dependencies for the validation scripts

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
