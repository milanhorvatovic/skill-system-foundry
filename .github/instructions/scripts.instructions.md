---
applyTo: "skill-system-foundry/scripts/**/*.py"
---

# Python Scripts Instructions

Review changes as a **Python tooling maintainer**, ensuring validation and scaffolding scripts remain reliable, minimal, and consistent.

## Design Principles

- **KISS** — prefer the simplest solution that works. Avoid abstractions, indirection, or patterns that add complexity without clear benefit. If a function can be understood in one reading, it's the right size
- **DRY** — each piece of logic should have a single authoritative location. If the same validation, pattern, or transformation appears in more than one place, extract it to `scripts/lib/`. But do not over-extract — three similar lines are better than a premature abstraction
- **Modularity** — each module in `scripts/lib/` should have a single, clear responsibility. Do not let modules grow into catch-all utilities. When a module handles unrelated concerns, split it
- **Fail-fast** — validate inputs at entry point boundaries before doing any work. If arguments are missing, names are invalid, or required files do not exist, report the error immediately rather than proceeding and failing in a confusing way later

## Constraints

- **Standard library only** — no third-party imports. These scripts ship with the skill and must run without `pip install`
- **Shared logic in `scripts/lib/`** — entry points in `scripts/` must stay thin; reusable logic belongs in `scripts/lib/`
- **Python 3.8+ compatibility** — do not use features introduced after Python 3.8 (walrus operator is fine; `match`/`case` is not)
- **Validation rules live in `scripts/lib/configuration.yaml`** — limits, patterns, and reserved words are loaded from YAML at startup. Change rules in the YAML, not by hardcoding values in Python

## Code Quality

- **Type hints on all function signatures** — use `typing` module for complex types (`List`, `Tuple`, `Dict`, `Optional`). Type hints make code self-documenting and catch errors early
- **Docstrings on all public functions and modules** — follow PEP 257. Entry point module docstrings must double as the usage message printed when the script is run without arguments (via `print(__doc__)`)
- **`encoding="utf-8"` on all `open()` calls** — omitting encoding causes platform-dependent behavior
- **`if __name__ == "__main__"` guard** — required for all entry points so modules remain importable

## Error Handling

- Handle errors explicitly with actionable messages that tell the caller what to do next
- Do not silently swallow exceptions or re-raise bare `Exception` — use specific exception types
- Use error level constants (`LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO`) from `lib/constants.py` — never hardcode level prefixes as strings
- Script output is consumed by AI agents — prefer structured, labeled output over decorated prose. No progress bars, spinners, or decorative formatting

## Conventions

- **Validation functions return `(errors, passes)` tuples** — do not raise exceptions for validation failures. Collect all issues and return them so callers can report everything at once
- **Exit codes** — exit 0 on success (including warnings), exit 1 only on failures (`LEVEL_FAIL`). Scripts must be composable in CI pipelines
- **Library functions return data, don't print** — except for dedicated output/formatting helpers whose purpose is producing structured output. Keep `print()` and `sys.exit()` out of validation and domain logic
- **Consistent path handling** — use `os.path` throughout. Do not mix `os.path` and `pathlib` within the same codebase
- **Keep scripts focused** — one task per entry point. Do not combine unrelated operations in a single script
- Document magic numbers with inline comments explaining why the value was chosen

## Review Scope

These scripts (`validate_skill.py`, `audit_skill_system.py`) validate repository content — SKILL.md files, manifests, and directory structure — not their own correctness. Regressions in the tooling itself are not caught automatically. Review Python changes for code quality, maintainability, and adherence to the principles above. Only flag issues with high confidence.

## Common Issues to Flag

- Third-party import (`pip install` dependency)
- Reusable logic placed directly in a `scripts/*.py` entry point instead of `scripts/lib/`
- Missing type hints on function signatures
- Missing or empty docstring on a public function or module
- `open()` call without `encoding="utf-8"`
- Bare `except` or swallowed exception without actionable output
- Hardcoded error level string (`"FAIL"`) instead of `LEVEL_FAIL` constant
- Validation rule hardcoded in Python instead of `scripts/lib/configuration.yaml`
- Use of Python 3.9+ features (`match`/`case`, `dict | dict` merge, `str.removeprefix`)
- `print()` or `sys.exit()` in library code outside dedicated output helpers
- Missing `if __name__ == "__main__"` guard in entry point
- Unexplained magic numbers or hardcoded values
- Mixing `os.path` and `pathlib` in the same file
- Script that mixes multiple unrelated operations
- Duplicated logic across files that should be extracted to `scripts/lib/`
- Over-engineered abstraction for a one-time operation
- Library module that handles unrelated concerns (should be split)

---

**Remember:** Review as a Python tooling maintainer. Prioritize stdlib-only imports, type safety, proper error handling, and separation between entry points and shared logic.
