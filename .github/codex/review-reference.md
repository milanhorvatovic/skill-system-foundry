# Review reference

Repository-specific review guidance that supplements the built-in review reference. Apply these rules in addition to the standard checklists.

## Repository conventions

These constraints are non-negotiable across the entire codebase. Flag violations as P1 findings:

- **Standard library only** — no third-party imports in production code (`skill-system-foundry/scripts/`). Scripts must run anywhere Python 3.12+ is available.
- **Python 3.12 compatibility** — do not use features from 3.13+.
- **`os.path` only** — do not use `pathlib`. Do not mix the two.
- **`encoding="utf-8"` on all `open()` calls.**
- **Type hints on all function signatures** — use builtin generics (`list`, `dict`, `tuple`) and `X | None`.
- **Validation rules in YAML** — limits, patterns, and reserved words live in `skill-system-foundry/scripts/lib/configuration.yaml`. Never hardcode validation rules in Python.
- **Error levels from constants** — use `LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO` from `skill-system-foundry/scripts/lib/constants.py`, never hardcode strings.
- **Validation functions return `(errors, passes)` tuples** — never raise exceptions for validation failures.
- **Actions pinned to commit SHAs** — not tags.

## Python scripts (`skill-system-foundry/scripts/**/*.py`)

Apply these in addition to the standard Python checklist:

- Verify library modules (`skill-system-foundry/scripts/lib/*.py`) do not call `print()` or `sys.exit()` — those belong only in entry points and `reporting.py`.
- Check that validation rules come from `configuration.yaml` via `constants.py` (both in `skill-system-foundry/scripts/lib/`), not hardcoded values.
- Verify error levels use `LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO` from `skill-system-foundry/scripts/lib/constants.py`, not hardcoded strings.

## Workflow YAML (`.github/workflows/*.yaml`)

Apply these in addition to the standard workflow checklist:

- Verify all actions are pinned to commit SHAs, not tags (e.g. `uses: actions/checkout@<sha> # @v6 as 6.0.2`).
- Check that job permissions follow least-privilege (separate read/write jobs).

## Markdown inside skills (`skill-system-foundry/**/*.md`)

Apply these rules to file-reference links inside skill content (`SKILL.md`, `capabilities/**/*.md`, `references/**/*.md`). They override plain CommonMark expectations:

- **Skill-root-relative paths, never parent traversals** — every markdown link target is written as if the file were standing at the skill root, regardless of the referencing file's physical location (e.g., from `capabilities/validation/capability.md` the correct link is `[...](references/authoring-principles.md)`, not `../../references/authoring-principles.md`). Do **not** flag these as broken links — the in-repo reference resolver (`lib/references.py::resolve_reference`) tries source-dir-relative first, then falls back to skill-root-relative, so skill-root paths always resolve.
- **Forward slashes only** — no Windows-style backslashes in link targets.
- **Role files are the exception** — files outside any `skills/` tree (the `roles/` tree) use system-root-relative paths (e.g., `skills/<domain>/SKILL.md`). Skill-internal links still use the skill-root-relative form.
- Do flag a link as broken only after confirming the target does not exist **at the skill root** either; do not rely on `<source-dir>/<link>` existence alone.

## Review-specific focus areas

Beyond code correctness, also evaluate:

- **Architecture justification** — do structural changes follow the two-layer architecture (skills and roles) documented in `AGENTS.md`?
- **Convention compliance** — does the change follow the constraints listed above?

`AGENTS.md` is the authority for repository conventions. The constraints above are derived from `AGENTS.md` and included here because this file is injected into the review prompt.
