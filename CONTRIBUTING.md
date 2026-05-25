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

   These labels are the input to label-driven release automation: when a release is prepared without an explicit version, `release-prep.yaml` computes the next version from the `release:` labels of PRs merged since the last tag (highest bump wins; `skip` contributes nothing). `verify-pr-release-label` is a required, blocking check: a PR missing exactly one valid `release:` label cannot merge until the label is added or corrected (adding it re-runs the check green). It stays fail-soft on a transient API read error so a hiccup cannot strand a PR, and `compute_release_version.py` re-validates every in-window label at release time as the backstop. Dependabot PRs are labeled automatically by `dependabot-release-label.yaml` (see [Dependency Updates](#dependency-updates)); label human-authored PRs by hand — on a fork PR a maintainer applies the label.

7. **Respond to feedback.** PRs may require revisions before merging.

## What Happens Next

Maintainers review PRs on a best-effort basis. Smaller, focused PRs are reviewed faster than large ones. If your PR has not received feedback after a reasonable time, a polite ping in the PR comments is welcome.

## Dependency Updates

Dependabot opens grouped pull requests weekly for the GitHub Actions and Python dev dependencies. Each ecosystem groups minor and patch bumps into one rolling PR; semver-major bumps split into standalone PRs. Every Dependabot PR is labeled automatically — `dependencies`, its ecosystem, and a `release:` level reconciled by `dependabot-release-label.yaml`.

### Auto-merge

`dependabot-auto-merge.yaml` drives a Dependabot PR on a three-tier policy:

- **Eligible** — patch/minor, not a trust-boundary action, no veto label: the bot approves *and* arms auto-merge, so the PR merges hands-off once required checks pass.
- **Held** — the effective update-type is **semver-major**, *or* the bump touches a **trust-boundary action** that runs with secrets in scope (currently `actions/create-github-app-token`, which mints the App private key, and `milanhorvatovic/codex-ai-code-review-action`, which runs with `OPENAI_API_KEY`): the bot **arms auto-merge but does not approve**. The PR shows "auto-merge enabled, waiting for review" and merges the moment a **code-owner approves** — you approve, you do not also have to merge. When a new action-level trust-boundary dependency is added, extend the exclude list in `.github/dependabot.yaml`, the **approve**-step guard in `.github/workflows/dependabot-auto-merge.yaml`, the `check_dependency_gates` guard in `.github/workflows/dependabot-reconciler.yaml`, and this list.
- **Veto** — the PR carries **`trust-boundary`** or **`security-review-required`**: the bot neither approves nor arms; it stays fully manual. Apply either to any dependency PR you want held; applying one to an already-armed PR disarms the pending auto-merge.

**Approving a held trust-boundary action authorizes secret-scoped CI on that version.** Bringing a held PR up to date — the reconciler does this once you have approved, under the automation App identity — re-runs the repository's workflows **with secrets in scope** on the new action version, so review the action *version's source*, not just the SHA bump. Under the `main` ruleset's strict-up-to-date + dismiss-stale-reviews rules a busy batch can dismiss your approval and re-run that CI on each base advance, so you may re-approve (and re-authorize the run) more than once before it merges.

> **Ruleset precondition.** Held safety for files outside `CODEOWNERS` (the pip ecosystem — `requirements-dev.txt` is unowned) relies on the `main` ruleset requiring **at least one approving review on every PR**. If that requirement is ever removed, an armed semver-major pip bump would merge with no human review.

The repository variable **`DEPENDABOT_AUTOMERGE_ENABLED`** is the kill-switch: the bot approves/arms only when it is exactly `true`. Unset or any other value disables auto-merge, and the PR waits for a manual merge.

A held PR merges automatically once a code-owner approves it; a veto-labeled PR is merged the normal way after review. Note that an unresolved **Copilot review comment** parks a PR — the `main` ruleset requires review-thread resolution — so resolve the threads (or comment `@dependabot recreate`) to let auto-merge proceed.

When the grouping or label configuration changes, existing open Dependabot PRs keep their old shape until recreated — comment `@dependabot recreate` (or close them) so they adopt the new configuration.

### Reconciler

`dependabot-auto-merge.yaml` only sees `pull_request` events, so a PR can stall in a state no `pull_request` event re-fires on. `dependabot-reconciler.yaml` is the backstop that re-drives every open Dependabot PR each tick. It runs reactively (when the auto-merge workflow completes, and on pushes to `main`), hourly on a schedule, and on manual `workflow_dispatch`. It covers three cases the auto-merge workflow cannot: a PR that goes **`BEHIND`** when another PR in the batch merges (the `main` ruleset requires branches to be up to date, and GitHub does not auto-rebase in that mode); an approval **dismissed** by the reconciler's own branch-update push (the ruleset dismisses stale reviews on push); and an auto-merge enable that **dropped or silently failed**.

It never invokes a separate synchronous-merge call, though enabling auto-merge on an already-ready PR can complete the merge immediately — the same behavior as the auto-merge workflow's arm step, since `gh pr merge --auto --squash` merges on the spot when every required protection is already satisfied. It updates `BEHIND` branches, posts a `@dependabot recreate` on a real conflict, restores a dismissed approval on an already-armed PR, and **arms-or-advances** an approved + mergeable PR — arming it if unarmed, or re-issuing the idempotent merge to back up the async auto-merge worker if already armed (the held tier has no synchronous merge, so this advance is its safety net). It honors the **`DEPENDABOT_AUTOMERGE_ENABLED`** kill-switch for those merge-advancing actions — while the switch is off it still updates `BEHIND` branches and posts recreate nudges, but it does not re-approve or arm. A genuinely stuck reconciliation (a silent auto-merge enable, or a failed defensive disable on a security-review PR) fails the run red rather than passing silently.

The reconciler acts on a PR the auto-merge workflow has already **approved or armed**, via two paths: it **re-approves** an armed PR whose approval was dismissed (or that the workflow could not approve from the Dependabot-secret context — its approve step reads the Dependabot-store token; the reconciler reads the Actions-store copy), and it **arms-or-advances** an approved, mergeable PR. The re-approve path re-runs the full dependency holds first (semver-major, the trust-boundary actions, and the `trust-boundary` / `security-review-required` labels), so the bot never approves a held PR; because it approves, on an armed-but-unapproved PR it may post the first approval — the approved/armed precondition plus the re-run gates are the boundary, not a prior-approval check. The arm-or-advance path does **not** re-run the dependency holds — arming and merging are ruleset-gated, so a held PR cannot merge until a code-owner approves — keeping only the label-veto and kill-switch guards. It does **not** approve or arm a PR that is neither approved nor armed — for example one whose initial `Dependabot Auto-Merge` run dropped entirely and no later push re-fired it — leaving it for manual triage; recover such a PR by re-running the `Dependabot Auto-Merge` workflow against it, or by pushing to (or `@dependabot rebase`-ing) the branch so a fresh `synchronize` re-fires the auto-merge path. The **`BEHIND`-branch update** applies the dependency holds **unless a code-owner has approved** — an approved held version is authorized for the privileged App-identity CI an update-branch triggers, an unapproved one is left `BEHIND` for manual handling — while the **recreate nudge** keeps the holds unconditionally (a held PR, even approved, is left for manual conflict resolution). If you manually arm or approve a PR you want to hold, request changes or apply a `trust-boundary` / `security-review-required` label — the gates above honor both.

Because the reconciler runs outside the Dependabot event context, its re-approval reads **`CODEOWNER_APPROVER_TOKEN` from the Actions secret store** — the auto-merge workflow reads the same PAT from the Dependabot secret store. The single code-owner PAT must therefore be stored under that name in **both** stores (workflows triggered by Dependabot cannot read Actions secrets, and vice versa). Rotate both copies together.

## Scope

Skill System Foundry is intentionally focused on the **structural and architectural** concerns of organizing AI-agnostic skill systems. Contributions that stay within this scope are most likely to be accepted.

Out of scope:
- Domain-specific skill content (e.g., a complete project management skill)
- Tool-specific features that do not generalize across the supported tool landscape
- External dependencies for the validation scripts

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
