---
name: review
description: >
  Guides human PR review and contributor self-review for the Skill System
  Foundry repository. Triggers when preparing a pull request for others to
  review, doing a self-review before requesting review, reviewing someone
  else's PR on GitHub, deciding whether to approve or request changes,
  evaluating whether automated review findings are worth addressing, or
  understanding what to check before merging. Also triggers when asked
  about the review process, review checklists, or how to structure review
  feedback for contributors. This skill provides process guidance — for
  running automated checks locally, use the local-code-review skill instead.
---

# PR Review Skill

Guides human PR review and self-review for the Skill System Foundry — what to check, what to skip (because automation handles it), and how to structure feedback.

## Before Opening a PR

### Self-Review Checklist

Run the local-code-review skill to execute all automated checks (tests, coverage, skill validation, shellcheck). If any fail, fix before requesting review.

Once automated checks pass, self-review focuses on what automation cannot catch.

### Self-Review Questions

Ask these about your own PR before requesting review:

**For Python changes:**
- Does the new code follow the `(errors, passes)` return pattern for validation functions?
- Are new validation rules in `configuration.yaml`, not hardcoded?
- Do new functions have type hints and docstrings?
- Are new entry point flags (`--json`, `--verbose`) consistent with existing scripts?
- Did you add tests for new branches and error conditions?

**For Markdown changes:**
- Would an agent trigger reliably based on the description? (If you changed a SKILL.md or capability.md)
- Is new content in the right progressive disclosure level? (Overview in SKILL.md, detail in references)
- Are all new files linked from the parent entry point?

**For shell script changes:**
- Does the script start with `set -euo pipefail`?
- Are all environment variables validated with `${VAR:?}` at the top?
- Is the script called from the correct permission-boundary job?

**For all changes:**
- Does the commit message follow the format? (`Update X`, `Add X to Y`, `Fix X in Y`)
- Are there any uncommitted changes you forgot to stage?

## Reviewing a PR

### What Automation Already Checked

Do not spend time verifying these — CI handles them:

- Test suite passes (ubuntu + windows)
- Coverage threshold met (70% branch)
- SKILL.md frontmatter validity (name, description, format)
- Cross-reference integrity (broken links, nesting depth)
- Shell script lint (shellcheck)
- Codex automated review (behavioral bugs, security issues)

If CI is green, all of the above passed. Focus your time on what CI cannot judge.

### Where to Focus

These are the four areas that require human judgment (ordered by impact):

**1. Behavioral correctness** — Does the change do what the PR description claims? Read the diff with the PR title in mind. If the PR says "fix false positive in name validation," verify the fix actually addresses the described scenario and doesn't introduce new false positives or negatives.

**2. Description quality** (for SKILL.md / capability.md changes) — Would an agent reliably activate based on this description? This is the single highest-leverage review question for a skill system. A vague description means the skill under-triggers in production. Check: does it include trigger phrases, concrete operations, and context about when to activate?

**3. Progressive disclosure** — Is content in the right layer? This matters because context window space is a shared resource. If detailed reference material is inlined in SKILL.md instead of living in `references/`, every activation of the skill pays the token cost. Check: could any section of SKILL.md be moved to a reference file without losing the overview?

**4. Architecture justification** — Is a capability warranted? A new capability needs 3+ distinct operations with mutually exclusive triggers. If a PR adds a capability for a single operation, push back. Standalone is the default; complexity must be justified.

### What NOT to Comment On

- Style preferences not backed by a documented convention
- Alternative implementations that aren't clearly better ("you could also...")
- Issues already flagged by the automated Codex review (don't pile on)
- Anything `validate_skill.py` or `shellcheck` would catch (if CI is green, it passed)

### How to Give Feedback

Use this format (matches `.github/copilot-instructions.md`):

1. **Problem** — what is wrong (one sentence)
2. **Why it matters** — impact on agents, users, or maintainability (one sentence, omit if obvious)
3. **Suggested fix** — concrete action or code snippet

Keep the total number of comments small. A PR with 15 review comments is demoralizing and likely mixes high-value feedback with noise. Aim for 0-5 comments focused on the four areas above.

## Approve vs Request Changes

**Approve** when:
- CI is green
- The change does what it claims
- No high-severity issues in the four focus areas
- Remaining concerns are minor and can be addressed in follow-up

**Request changes** when:
- The change introduces a behavioral bug or regression
- A SKILL.md description is too vague to trigger reliably
- The PR violates a hard constraint (third-party import, hardcoded validation rule, mixed `os.path`/`pathlib`)
- A security boundary is crossed (write operations in read-only job, secrets in logs)

**Comment** (without approve/request changes) when:
- You have questions but no blocking concerns
- The automated review flagged something you want the contributor to explicitly acknowledge

## Handling Automated Review Findings

When Codex generates findings on a PR you're reviewing:

1. **Scan severity** — only High findings require contributor action
2. **Check for false positives** — if a finding duplicates what `validate_skill.py` catches, it's noise
3. **Don't pile on** — if the automated review already flagged an issue, don't add your own comment saying the same thing. Instead, confirm or dismiss the automated finding
4. **Use them as a starting point** — automated findings can point you to areas of the diff worth closer human review, even if the specific finding is wrong
