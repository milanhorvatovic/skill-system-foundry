---
name: commit-conventions
description: >
  Enforces commit message format and conventions for the Skill System
  Foundry repository. Triggers when composing a commit message, reviewing
  commit history, squashing commits, or deciding how to describe a change.
  Also triggers on phrases like "write a commit message," "what should
  the commit say," "commit message format," or "how to reference an
  issue in a commit." Use this skill whenever a commit message needs to
  be written or reviewed.
---

# Commit Conventions Skill

Enforces commit message format and conventions for the Skill System Foundry repository.

## Format

Every commit message starts with a short summary line describing **what** changed. Use one of these verb prefixes:

| Verb | When to Use | Example |
|---|---|---|
| `Update` | Enhancement to an existing feature or file | `Update validation to check forward slashes` |
| `Add` | Wholly new feature, file, or component | `Add critique skill to .agents/` |
| `Fix` | Bug fix or correction | `Fix false positive in name validation` |

### Rules

- **One logical change per commit.** Do not mix unrelated changes in a single commit
- **Summary line only.** Keep it to one line. No body paragraph unless the change is unusually complex and the "why" is not obvious from the diff
- **Component names over file names.** Write `Update validation logic` not `Update validation.py`. Use file names only when the component name is the file name (e.g., `Update configuration.yaml`)
- **Multi-component changes.** Use `and` to join: `Update validation and constants`
- **No trailing period.** The summary is a title, not a sentence
- **No co-authors.** Do not add `Co-Authored-By` or any other trailers to commit messages
- **No issue closers.** Do not add `closes #N`, `fixes #N`, or similar references to commit messages — issue references belong in pull requests, not commits

### Issue References

Reference issue numbers when the commit resolves or relates to a specific issue:

```
Fix #12: validation false positive for optional frontmatter
Update version to 1.1.0 (closes #15)
Add forward-slash check to validate_skill.py (fixes #23)
```

Use `Fix #N` or `fixes #N` for bug fixes, `closes #N` for feature completions. Place the reference after a colon or in parentheses.

### Version Bumps

Version bump commits use a specific format:

```
Update version to X.Y.Z
```

Reference issues when the release resolves them: `Update version to 1.1.0 (closes #12)`.

## Examples

**Good:**
- `Add forward-slash validation to reference checks`
- `Fix off-by-one in description length validation`
- `Update shell-scripts skill description for clarity`
- `Add solution-design skill to .agents/`
- `Update configuration.yaml and constants for new limit`
- `Fix #12: false positive in name validation`

**Bad:**
- `updated stuff` — vague, no verb prefix, lowercase
- `Fix bug` — no description of what was fixed
- `Update validation.py, constants.py, test_validation.py, configuration.yaml` — lists files instead of describing the change
- `Add new validation check for forward slashes in file references and also update the constants module to expose the new pattern and add tests` — too long, multiple concerns
- `Fix: validation` — colon after verb is not the convention

## Edge Cases

- **Reformatting or refactoring with no behavior change:** `Refactor` is acceptable as an additional verb: `Refactor validation into separate helper functions`
- **Test-only changes:** `Add tests for forward-slash validation` or `Update tests for new edge cases`
- **Documentation-only changes:** `Update README for new distribution channels`
- **Dependency updates:** `Update coverage to 7.6.1 in requirements-dev.txt`
