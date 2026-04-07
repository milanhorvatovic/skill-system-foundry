---
name: local-code-review
description: >
  Runs a local code review workflow for the Skill System Foundry repository —
  executes tests, coverage checks, skill validation, and shellcheck, then
  analyzes the diff for pattern violations and produces a structured verdict.
  Triggers when asked to check code locally, run a local review, verify
  changes pass all checks, or catch issues before CI. Also triggers on
  phrases like "check this before I push," "does this look right," "run
  the checks," or "review the current branch locally." Use this skill to
  catch issues locally and avoid spending CI tokens and time on problems
  that can be detected on the development machine. For a deep review
  replicating the CI code review pipeline with confidence scoring and
  structured findings, use the local-ci-code-review skill instead. For
  design-level criticism and constructive feedback, use the critique skill
  instead. For human PR review process guidance, use the review skill
  instead.
---

# Local Code Review Skill

Runs a structured, opinionated local code review of changes in the Skill System Foundry repository. When activated, follow this workflow end to end.

## Step 1: Identify the Changes

Determine the scope of what to review:

```bash
# Uncommitted changes (working tree + staged)
git diff HEAD

# Changes on current branch vs main
git diff main...HEAD

# Specific PR (if a PR number or branch is provided)
git diff main...<branch>
```

List the changed files and categorize them:

| Category | File Pattern | Review Focus |
|---|---|---|
| Python entry points | `scripts/*.py` | Thin wrapper, delegates to lib, argparse, --json |
| Python library | `scripts/lib/*.py` | Domain logic, (errors, passes) pattern, no print/exit |
| Tests | `tests/test_*.py` | Coverage of new branches, descriptive names, boundary cases |
| SKILL.md / capability.md | `**/SKILL.md`, `**/capability.md` | Description quality, progressive disclosure |
| Reference docs | `references/*.md` | Conciseness, one-level-deep cross-refs, ToC if 100+ lines |
| Templates | `assets/*.md` | Placeholder markers preserved |
| Configuration | `scripts/lib/configuration.yaml` | Key naming, inline comments, structure |
| Shell scripts | `.github/scripts/*.sh` | strict mode, env validation |
| Workflows | `.github/workflows/*.yaml` | SHA-pinned actions, permission isolation |
| Other Markdown | `README.md`, `CONTRIBUTING.md` | Accuracy, consistency with SKILL.md |

## Step 2: Run Automated Checks

Run these and capture the output. Any failures here must be reported as High severity — do not proceed to the AI-judgment phase until these are understood:

```bash
# Tests + coverage
python -m coverage run -m unittest discover -s tests -p "test_*.py" -v
python -m coverage report

# Skill validation
cd skill-system-foundry
python scripts/validate_skill.py . --allow-nested-references --json
python scripts/audit_skill_system.py . --json
cd ..

# Shell lint (only if .sh files changed)
shellcheck .github/scripts/*.sh
```

Report automated results as a summary. Do not re-flag individual issues that these tools already caught — the tools are authoritative. Example:

> **Automated checks:** Tests pass (14 files, 342 tests). Coverage 78% (threshold 70%). Skill validation clean. ShellCheck clean.

Or if something fails:

> **Automated checks:** Tests pass. Coverage 78%. Skill validation: 1 FAIL — `description` exceeds 1024 characters. Fix this before merge.

## Step 3: Review for AI-Judgment Issues

Now review the diff for issues that no script can catch. This is the core of the review. Check **only** the categories relevant to the changed files.

### Python Changes

**Check for logic errors:**
- Wrong comparison operators, off-by-one, inverted conditions
- Unreachable code after early returns
- Exception handling that swallows errors or re-raises bare `Exception`
- Race conditions in file operations

**Check for pattern violations:**
- Validation logic that raises exceptions instead of returning `(errors, passes)`
- `print()` or `sys.exit()` in library code outside `reporting.py`
- Validation rules hardcoded in Python instead of `configuration.yaml`
- `pathlib` usage (this repo uses `os.path` exclusively)
- Third-party imports
- Missing `encoding="utf-8"` on `open()` calls
- Hardcoded error level strings instead of `LEVEL_FAIL`/`LEVEL_WARN`/`LEVEL_INFO`

**Check for missing test coverage:**
- New branches that aren't exercised by tests
- New error conditions without corresponding test cases
- Changed exit codes or error messages without test updates

### Markdown Changes

**Check description quality** (SKILL.md and capability.md only):
- Does the description include trigger phrases and concrete operations?
- Would an agent reliably activate based on this description alone?
- Is it "pushy" enough — keyword-rich, erring toward over-triggering?

**Check progressive disclosure:**
- Is detailed content inlined in SKILL.md that belongs in `references/`?
- Is SKILL.md approaching 500 lines? Should content be extracted?
- Are cross-references one level deep from the entry point?

**Check for consistency:**
- Is terminology consistent with the rest of the repository?
- Are new files linked from the parent entry point?
- Do file references use forward slashes and relative paths from skill root?

### Shell Script Changes

**Check for missing safeguards:**
- New environment variables used without `${VAR:?}` validation at script top
- Missing `trap` cleanup for temporary files
- `>` instead of `>>` for `$GITHUB_OUTPUT`

**Check permission boundaries:**
- Does the script run in a job with appropriately scoped permissions?
- Are secrets handled without echoing to logs?

### Configuration Changes

**Check `configuration.yaml`:**
- Are new keys following `snake_case` convention?
- Do pattern keys end with `_pattern`?
- Is there an inline comment explaining non-obvious values?
- Is the corresponding `constants.py` update present? (New YAML keys need `int()` conversion and cleanup with `del`)

### Workflow Changes

**Check actions:**
- Are actions pinned to commit SHAs (not tags)?
- Are permissions minimally scoped?
- Does the permission model maintain the read/write job separation?

## Step 4: Report Findings

Structure the output as follows. Be direct and concise — every finding must be actionable.

**Severity levels:**

- **High** — blocks merge: behavioral bugs, security issues, missing tests for risky changes, broken imports, automated check failures
- **Medium** — worth fixing: pattern violations, consistency issues, documentation gaps
- **Low** — informational: minor style points, suggestions for improvement

**Output format:**

Start with the automated check summary, then list findings:

```
## Automated Checks
Tests: ✓ (14 files, 342 tests)
Coverage: ✓ 78% (threshold 70%)
Skill validation: ✓
ShellCheck: ✓ (or N/A if no .sh changes)

## Findings

### High
(list or "None")

### Medium
(list or "None")

### Low
(list or "None")

## Verdict
(Approve / Request changes — with one-sentence rationale)
```

For each finding, use this format:

> **[file:line]** Brief title
> Description of the problem and concrete fix guidance.

**Rules:**

- **Empty findings is the ideal outcome.** A clean diff with no issues is not a failure to review — it means the code is good. Do not manufacture findings to justify the review.
- Report at most 5-7 findings total. If you find more, prioritize by severity and impact. A wall of 15 findings is noise.
- Do not repeat issues the automated tools already caught.
- Do not suggest alternative implementations unless the current one is clearly wrong.
- Do not comment on style preferences not backed by a documented convention.

## Step 5: Verdict

Based on the findings, give a clear verdict:

- **Approve** — no High findings, no more than 2-3 Medium findings, automated checks pass
- **Request changes** — any High finding, or Medium findings that indicate a pattern violation that will propagate if not fixed now
- **Comment** — questions to discuss, no blocking concerns

State the verdict with a one-sentence rationale. Do not hedge.
