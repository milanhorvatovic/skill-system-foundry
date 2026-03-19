---
name: python-scripts
description: >
  Enforces code quality, modularity, and test coverage for Python scripts
  in the Skill System Foundry repository. Triggers when creating, editing,
  reviewing, refactoring, or debugging any Python file under scripts/ or
  scripts/lib/, writing or updating tests under tests/, adding new validation
  logic, modifying shared library modules, creating new entry points, or
  working with the configuration.yaml validation rules. Also triggers when
  asked to improve test coverage, enforce type hints, fix error handling,
  extract shared logic, or ensure stdlib-only compliance. Use this skill for
  any Python work in the repository, even if the user does not explicitly
  mention code quality.
---

# Python Scripts Skill

Enforces code quality, modularity, test coverage, and best practices for all Python scripts in the Skill System Foundry repository.

The repository's Python codebase follows strict conventions: stdlib-only imports, thin entry points with shared logic in `scripts/lib/`, type hints on all signatures, and comprehensive test coverage. This skill codifies those conventions.

## Architecture

### Directory Layout

```
skill-system-foundry/
├── scripts/                    ← entry points (thin wrappers)
│   ├── __init__.py
│   ├── validate_skill.py       ← validates a single skill
│   ├── audit_skill_system.py   ← audits entire skill system
│   ├── scaffold.py             ← scaffolds new components
│   ├── bundle.py               ← bundles for distribution
│   └── lib/                    ← shared logic (single responsibility per module)
│       ├── __init__.py
│       ├── constants.py        ← centralized constants loaded from configuration.yaml
│       ├── configuration.yaml  ← validation rules (limits, patterns, reserved words)
│       ├── validation.py       ← shared name/field validation
│       ├── references.py       ← reference scanning and graph traversal
│       ├── frontmatter.py      ← YAML frontmatter parsing
│       ├── reporting.py        ← structured output formatting
│       ├── discovery.py        ← skill directory discovery
│       ├── manifest.py         ← manifest parsing and validation
│       ├── bundling.py         ← bundle packaging logic
│       ├── codex_config.py     ← Codex agents/openai.yaml validation
│       └── yaml_parser.py      ← subset YAML parser (stdlib-only)
tests/
├── helpers.py                  ← shared test utilities
├── test_validation.py          ← tests for lib/validation.py
├── test_validate_skill.py      ← tests for validate_skill.py
├── test_references.py          ← tests for lib/references.py
├── ...                         ← one test file per module
```

### Separation of Concerns

- **Entry points** (`scripts/*.py`) — argument parsing, output formatting, `sys.exit()`. Thin wrappers that delegate to library code
- **Library modules** (`scripts/lib/*.py`) — domain logic, validation, data transformation. No `print()` or `sys.exit()` except in dedicated output helpers (`reporting.py`)
- **Constants** (`scripts/lib/constants.py`) — structural constants in Python, validation rules loaded from `configuration.yaml`
- **Tests** (`tests/`) — one test file per module, comprehensive coverage

## Design Principles

### KISS

Prefer the simplest solution that works. Avoid abstractions, indirection, or patterns that add complexity without clear benefit. If a function can be understood in one reading, it is the right size.

### DRY

Each piece of logic has a single authoritative location. If the same validation, pattern, or transformation appears in more than one place, extract to `scripts/lib/`. But do not over-extract — three similar lines are better than a premature abstraction.

### Modularity

Each module in `scripts/lib/` has a single, clear responsibility. Do not let modules grow into catch-all utilities. When a module handles unrelated concerns, split it.

### Fail-Fast

Validate inputs at entry point boundaries before doing any work. If arguments are missing, names are invalid, or required files do not exist, report the error immediately.

## Hard Constraints

### Standard Library Only

No third-party imports. These scripts ship with the skill and must run without `pip install`. The only external dev dependency is `coverage` (in `requirements-dev.txt`), used exclusively for test coverage measurement.

### Python 3.12+ Compatibility

Do not use features introduced in Python 3.13 or later. Specifically avoid:
- `type` parameter defaults (`type Alias[T = int]`)
- `warnings.deprecated` decorator
- `PythonFinalizationError`

### Validation Rules in YAML

Limits, patterns, and reserved words live in `scripts/lib/configuration.yaml`. Change rules in the YAML, not by hardcoding values in Python. `constants.py` loads and exposes them.

## Code Quality Standards

### Type Hints

Type hints on all function signatures. Use builtin generic types:

```python
# Correct
def validate_name(name: str, dir_name: str) -> tuple[list[str], list[str]]:

# Wrong — do not use typing.Optional or typing.List
def validate_name(name: Optional[str], dir_name: str) -> Tuple[List[str], List[str]]:
```

Use `X | None` instead of `Optional[X]`. Fall back to `typing` only for advanced types (`TypedDict`, `Literal`, `TypeAlias`).

### Docstrings

PEP 257 docstrings on all public functions and modules.

Entry point module docstrings double as the usage message printed when the script runs without arguments (via `print(__doc__)`).

```python
"""
Validate a single skill directory against the Agent Skills specification.

Usage:
    python scripts/validate_skill.py <skill-path>
    python scripts/validate_skill.py skills/project-mgmt --verbose
"""
```

### File Encoding

Always specify `encoding="utf-8"` on `open()` calls:

```python
# Correct
with open(path, "r", encoding="utf-8") as f:

# Wrong — platform-dependent behavior
with open(path, "r") as f:
```

### Entry Point Guard

Required for all entry points:

```python
if __name__ == "__main__":
    main()
```

## Validation Function Pattern

Validation functions return `(errors, passes)` tuples — never raise exceptions for validation failures. Collect all issues and return them so callers can report everything at once.

```python
def validate_description(description: str) -> tuple[list[str], list[str]]:
    """Validate the description field."""
    errors: list[str] = []
    passes: list[str] = []

    if not description:
        errors.append(f"{LEVEL_FAIL}: [spec] 'description' field is empty")
        return errors, passes

    if len(description) > MAX_DESCRIPTION_CHARS:
        errors.append(
            f"{LEVEL_FAIL}: [spec] 'description' exceeds "
            f"{MAX_DESCRIPTION_CHARS} characters ({len(description)} chars)"
        )
    else:
        passes.append(f"description: {len(description)} chars (max {MAX_DESCRIPTION_CHARS})")

    return errors, passes
```

Key patterns:
- Use error level constants (`LEVEL_FAIL`, `LEVEL_WARN`, `LEVEL_INFO`) from `lib/constants.py` — never hardcode strings
- Tag errors with source: `[spec]` for specification rules, `[platform: X]` for platform restrictions, `[foundry]` for conventions
- Short-circuit on critical failures (return early when subsequent checks are meaningless)
- Passes record what was checked so verbose mode can report them

## Error Handling

- Handle errors explicitly with actionable messages that tell the caller what to do next
- Do not silently swallow exceptions or re-raise bare `Exception` — use specific exception types
- Script output is consumed by AI agents — prefer structured, labeled output over decorated prose. No progress bars, spinners, or decorative formatting

## Exit Codes

- Exit 0 on success (including warnings)
- Exit 1 only on failures (`LEVEL_FAIL`)
- Scripts must be composable in CI pipelines

## JSON Output Convention

All entry points support `--json` for machine-readable output. Use `to_json_output()` from `lib/reporting.py`, which auto-injects a `version` key for forward-compatible schema evolution.

Two error shapes exist:
- `"error"` (string) — early-exit path, single fatal condition (missing arguments, invalid path)
- `"errors"` (object) — full validation results with `"failures"`, `"warnings"`, `"info"` lists

Override `parser.error()` to emit JSON on argparse failures when `--json` is present:

```python
def _json_aware_error(message: str) -> None:
    if _json_mode:
        print(to_json_output({"tool": "my_tool", "success": False, "error": message}))
        sys.exit(1)
    parser.print_usage(sys.stderr)
    print(f"{parser.prog}: error: {message}", file=sys.stderr)
    sys.exit(1)

parser.error = _json_aware_error
```

## Path Handling

Use `os.path` throughout. Do not mix `os.path` and `pathlib` within the same codebase.

```python
# Correct — consistent os.path usage
skill_dir = os.path.dirname(skill_md_path)
ref_path = os.path.normpath(os.path.join(skill_dir, normalized_ref))

# Wrong — mixing paradigms
skill_dir = Path(skill_md_path).parent
ref_path = os.path.normpath(os.path.join(str(skill_dir), normalized_ref))
```

## Testing Standards

### Structure

One test file per source module. Test files mirror the source structure:

| Source | Test |
|---|---|
| `scripts/validate_skill.py` | `tests/test_validate_skill.py` |
| `scripts/lib/validation.py` | `tests/test_validation.py` |
| `scripts/lib/references.py` | `tests/test_references.py` |
| `scripts/lib/bundling.py` | `tests/test_bundle.py` |

### Test Organization

Use `unittest.TestCase` with descriptive class and method names. Group related tests into classes by feature or rule being tested. Use section separators for visual clarity:

```python
# ===================================================================
# Empty Name
# ===================================================================


class ValidateNameEmptyTests(unittest.TestCase):
    """Tests for validate_name when the name is empty."""

    def test_empty_string_returns_fail(self) -> None:
        """An empty name produces a single FAIL error and no passes."""
        errors, passes = validate_name("", "some-dir")
        self.assertEqual(len(errors), 1)
        self.assertIn(LEVEL_FAIL, errors[0])
        self.assertIn("empty", errors[0])
        self.assertEqual(passes, [])
```

### Test Helpers

Shared test utilities live in `tests/helpers.py`:

```python
def write_skill_md(
    skill_dir: str,
    *,
    name: str = "demo-skill",
    description: str = DEFAULT_DESCRIPTION,
    body: str = "# Demo Skill\n",
) -> None:
```

Use keyword-only arguments for optional parameters. Create temporary directories with `tempfile.mkdtemp()` and clean up in `tearDown` or `addCleanup`.

### Coverage

The repository targets 70% branch coverage (configured in `.coveragerc`). Coverage source is `skill-system-foundry/scripts` with branch measurement enabled.

Run tests with coverage:

```bash
python -m coverage run -m unittest discover -s tests -t .
python -m coverage report
```

Excluded from coverage:
- `if __name__ == "__main__"` blocks
- `pragma: no cover` markers
- `raise NotImplementedError`

### What to Test

- **Happy path** — valid inputs produce expected outputs
- **Boundary conditions** — max length, min length, exactly at limits
- **Error cases** — invalid inputs produce correct error levels and messages
- **Short-circuit behavior** — critical failures prevent subsequent checks
- **Edge cases** — empty strings, None values, special characters, Unicode

### Test Naming

Method names describe the scenario and expected outcome:

```python
def test_name_at_max_length_passes(self) -> None:
def test_name_one_over_max_length_returns_fail(self) -> None:
def test_empty_string_short_circuits(self) -> None:
def test_short_name_returns_info(self) -> None:
```

## Adding a New Module

1. Create `scripts/lib/<module>.py` with a module docstring and type-hinted functions
2. Import constants from `lib/constants.py` — add new constants to `configuration.yaml` if they are validation rules
3. Create `tests/test_<module>.py` with comprehensive test coverage
4. Import and use the module from the relevant entry point in `scripts/`
5. Keep the entry point thin — argument parsing and output only

## Adding a New Entry Point

1. Create `scripts/<name>.py` with a module docstring that doubles as usage text
2. Add argument parsing with `argparse`
3. Delegate domain logic to `scripts/lib/` modules
4. Add `--json` flag for machine-readable output (use `to_json_output` from `lib/reporting.py`)
5. Add `--verbose` flag for detailed output
6. Override `parser.error()` for JSON-compatible error reporting
7. Add `if __name__ == "__main__"` guard
8. Create `tests/test_<name>.py`

## Common Issues to Avoid

- Third-party import (anything requiring `pip install`)
- Reusable logic in an entry point instead of `scripts/lib/`
- Missing type hints on function signatures
- Missing docstring on a public function or module
- `open()` without `encoding="utf-8"`
- Bare `except` or swallowed exception without actionable output
- Hardcoded error level string (`"FAIL"`) instead of `LEVEL_FAIL`
- Validation rule hardcoded in Python instead of `configuration.yaml`
- `print()` or `sys.exit()` in library code outside output helpers
- Missing `if __name__ == "__main__"` guard
- Unexplained magic numbers
- Mixing `os.path` and `pathlib`
- Module handling unrelated concerns (should be split)
- Duplicated logic across files (should be extracted)
- Over-engineered abstraction for a one-time operation
