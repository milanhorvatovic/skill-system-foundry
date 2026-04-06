# Review reference

Repository-specific review guidance that supplements the built-in review reference. Apply these rules in addition to the standard checklists.

## Repository conventions

These constraints are non-negotiable across the entire codebase. Flag violations as P1 findings:

- **Standard library only** — no third-party imports in production code (`skill-system-foundry/scripts/`). Scripts must run anywhere Python 3.12+ is available.
- **Python 3.12 compatibility** — do not use features from 3.13+.
- **`os.path` only** — do not use `pathlib`. Do not mix the two.
- **`encoding="utf-8"` on all `open()` calls.**
- **Type hints on all function signatures** — use builtin generics (`list`, `dict`, `tuple`) and `X | None`.
- **Validation rules in YAML** — limits, patterns, and reserved words live in `scripts/lib/configuration.yaml`. Never hardcode validation rules in Python.
- **Error levels from constants** — use `LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO` from `lib/constants.py`, never hardcode strings.
- **Validation functions return `(errors, passes)` tuples** — never raise exceptions for validation failures.
- **Actions pinned to commit SHAs** — not tags.

## Python scripts (`skill-system-foundry/scripts/**/*.py`)

Apply these in addition to the standard Python checklist:

- Verify library modules (`skill-system-foundry/scripts/lib/*.py`) do not call `print()` or `sys.exit()` — those belong only in entry points and `reporting.py`.
- Check that validation rules come from `configuration.yaml` via `constants.py`, not hardcoded values.
- Verify error levels use `LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO` from `lib/constants.py`, not hardcoded strings.

## Workflow YAML (`.github/workflows/*.yaml`)

Apply these in addition to the standard workflow checklist:

- Verify all actions are pinned to commit SHAs, not tags (e.g. `uses: actions/checkout@<sha> # @v6 as 6.0.2`).
- Check that job permissions follow least-privilege (separate read/write jobs).

## Review-specific focus areas

Beyond code correctness, also evaluate:

- **Architecture justification** — do structural changes follow the two-layer architecture (skills and roles) documented in `AGENTS.md`?
- **Convention compliance** — does the change follow the constraints listed above?

`AGENTS.md` is the authority for repository conventions. Do not duplicate its content — reference it.
