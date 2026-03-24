# Review reference

Detailed guidance for the Codex code review prompt. Read this file when reviewing a pull request and apply the relevant sections based on the file types in the diff.

## Confidence scoring

Assign a `confidence_score` (0.0 to 1.0) to each finding reflecting how certain you are that it is a real, actionable issue:

- **0.9–1.0** — certain: the code is demonstrably wrong or violates a documented rule
- **0.7–0.9** — high: very likely an issue based on context, but depends on intent
- **0.5–0.7** — moderate: plausible issue, but could be intentional or context-dependent
- **0.3–0.5** — low: possible concern, may be a false positive
- **Below 0.3** — speculative: flag only if the potential impact is severe

Do not default all scores to the same value. Differentiate based on the evidence available in the diff and referenced files.

## File-type review guidance

Apply the appropriate checklist for each file type changed in the diff.

### Python scripts (`scripts/**/*.py`)

- Verify all function signatures have type hints using builtin generics (`list`, `dict`, `tuple`) and `X | None`
- Check that all `open()` calls include `encoding="utf-8"`
- Confirm no third-party imports — only standard library modules are allowed
- Verify `os.path` is used for path manipulation, not `pathlib`
- Check that validation functions return `(errors, passes)` tuples and never raise exceptions for validation failures
- Verify error levels use `LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO` from `lib/constants.py`, not hardcoded strings
- Check that validation rules come from `configuration.yaml` via `constants.py`, not hardcoded values
- Verify library modules (`scripts/lib/*.py`) do not call `print()` or `sys.exit()` — those belong only in entry points and `reporting.py`

### Shell scripts (`.github/scripts/*.sh`)

- Verify `set -euo pipefail` is at the top of every script
- Check that required environment variables are validated with `${VAR:?}` before use
- Look for unquoted variable expansions that could cause word splitting or globbing
- Verify error paths exit cleanly and write structured output to `$GITHUB_OUTPUT` when applicable
- Check for command injection risks in any variable interpolation

### JavaScript files (`.github/scripts/*.js`)

- Trace all `Number()`, `parseInt()`, `parseFloat()` calls — check what happens when the input is `undefined`, `null`, or a non-numeric string (`NaN` propagation)
- Verify that environment variables read via `process.env` are validated before use
- Check that array operations handle empty arrays gracefully
- Look for implicit type coercions that could cause silent failures

### Markdown files (`**/*.md`)

- Check that file cross-references point to files that exist in the repository
- Verify frontmatter fields match the expected format (folded block scalar `>` for multi-line descriptions)
- Check for consistent terminology — one term per concept, no synonym mixing
- Verify progressive disclosure: entry-point files should be concise with detail in `references/`
- Check that descriptions use third person ("Validates skills" not "I validate skills")

### Workflow YAML (`.github/workflows/*.yaml`)

- Verify all actions are pinned to commit SHAs, not tags
- Check that job permissions follow least-privilege (separate read/write jobs)
- Verify environment variables are passed correctly between steps and jobs
- Check step ordering and conditional expressions (`if:`) for logical correctness
- Look for secrets or tokens that could be exposed in logs

## Review-specific focus areas

Beyond code correctness, also evaluate:

- **Description quality** — do commit messages and PR description explain *why*, not just *what*?
- **Progressive disclosure** — are large additions broken into digestible sections?
- **Architecture justification** — do structural changes follow the patterns in `AGENTS.md`?
- **Convention compliance** — does the change follow the constraints and rules documented in `AGENTS.md`?

`AGENTS.md` is the authority for repository conventions. Do not duplicate its content — reference it.
