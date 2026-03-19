---
name: yaml-config
description: >
  Governs the configuration.yaml file that serves as the single source of
  truth for all validation rules in the Skill System Foundry. Triggers when
  adding, modifying, or reviewing validation rules, limits, patterns, or
  reserved words. Also triggers when working with constants.py, yaml_parser.py,
  or any code that reads from configuration.yaml. Use this skill when asked
  to add a new validation check, change a limit or threshold, update reserved
  word lists, add SPDX license identifiers, modify regex patterns, or
  troubleshoot why a validation rule is not working as expected. Activates
  on mentions of configuration, validation rules, constants, thresholds,
  or pattern definitions.
---

# YAML Configuration Skill

Governs the `configuration.yaml` file — the single source of truth for all validation rules, limits, patterns, and policy constants in the Skill System Foundry.

Every validation check in the codebase reads its parameters from this file. Rules are never hardcoded in Python. `constants.py` loads the YAML at startup and exposes values as module-level constants that the rest of the codebase imports.

## Architecture

```
configuration.yaml          ← rules defined here (single source of truth)
       ↓
constants.py                ← loads YAML, exposes as Python constants
       ↓
validation.py, references.py, bundling.py, ...  ← import from constants
       ↓
validate_skill.py, audit_skill_system.py, ...   ← entry points use lib
```

Changing a rule means editing one line in `configuration.yaml`. The change cascades automatically through `constants.py` into every script that references it.

## File Structure

The YAML is organized into top-level sections separated by comment headers:

```yaml
# ============================================================
# Section Name
# ============================================================
section_key:
  sub_key:
    field: value
```

Current sections and their purposes:

| Section | Purpose |
|---|---|
| `skill` | All skill validation: name, description, body, compatibility, frontmatter keys, allowed-tools, metadata, license, directories |
| `codex_config` | Codex `agents/openai.yaml` schema validation |
| `dependency_direction` | Patterns detecting upward dependency violations |
| `role_composition` | Role minimum skill count and reference patterns |
| `bundle` | Bundle packaging: depth limits, description limits, targets, exclude patterns |

## Adding a New Validation Rule

### Step 1: Add to configuration.yaml

Place the rule in the correct section. Follow existing conventions:

- **Numeric limits** — use descriptive key names with clear units: `max_length: 64`, `min_skills: 2`
- **Regex patterns** — use the key suffix `_pattern`: `format_pattern: ^[a-z0-9]...$`
- **Lists** — use plural key names: `reserved_words`, `known_tools`, `exclude_patterns`
- **Nested groups** — group related rules under a common parent key

Add an inline comment explaining non-obvious values:

```yaml
# Upper bound on tool count — skills requesting too many tools
# likely need to be split.  Increase if justified.
max_tools: 20
```

### Step 2: Expose in constants.py

Import and assign in the appropriate section of `constants.py`:

```python
# --- New Section (if needed) ---
_new = _config["new_section"]
NEW_CONSTANT = int(_new["some_value"])
```

Follow existing patterns:
- Prefix private variables with underscore: `_skill`, `_dep`, `_bundle`
- Convert numeric values explicitly: `int(...)` for integers
- Compile regex patterns: `re.compile(...)` for patterns
- Use `frozenset(...)` for immutable sets
- Clean up private names with `del` at the end of the module

### Step 3: Use in validation code

Import from `lib.constants`:

```python
from lib.constants import NEW_CONSTANT, LEVEL_FAIL
```

Never import from `configuration.yaml` directly — always go through `constants.py`.

### Step 4: Add tests

Write tests in the corresponding `tests/test_*.py` file that verify the rule works at boundaries: at the limit, one over, and well over.

## YAML Parser Constraints

The repository uses a custom stdlib-only YAML parser (`yaml_parser.py`), not PyYAML. It supports a subset of YAML:

**Supported:**
- Key-value pairs with string values
- Nested mappings (indentation-based)
- Scalar lists (`- item`)
- Lists of mappings (`- key: value`)
- Folded (`>`, `>-`) and literal (`|`, `|-`) block scalars
- Inline comments (`# comment` after a space)
- Quoted strings (single and double)

**Not supported:**
- Flow syntax (`{key: value}`, `[item1, item2]`)
- Anchors and aliases (`&anchor`, `*alias`)
- Multi-document (`---` separators)
- Type coercion (all scalars returned as strings)
- Complex keys

**Important:** All scalar values are returned as strings. Numeric values must be explicitly converted in `constants.py` with `int()` or `float()`. Boolean values are strings `"true"` / `"false"`.

Regex patterns with `(?i)` flags and backslash sequences (`\b`, `\d`) are preserved as-is — the parser performs no escape processing.

## Conventions

### Comments

Use section headers with `=` separators to group related rules:

```yaml
# ============================================================
# Section Name
# ============================================================
```

Use inline comments sparingly — only to explain why a value was chosen, not what it is:

```yaml
# Good — explains the "why"
max_reference_depth: 25  # Prevents runaway traversal

# Bad — restates the key name
max_reference_depth: 25  # Maximum reference depth
```

### Naming

- Keys use `snake_case` (not `kebab-case` or `camelCase`)
- Pattern keys end with `_pattern`
- Maximum/minimum keys start with `max_` or `min_`
- List keys use plural nouns
- Boolean-like keys use positive framing: `allow_implicit_invocation` not `disable_explicit_only`

### Values

- **Strings** — bare when simple, quoted when containing special YAML characters (`:`, `#`, `{`, `}`)
- **Patterns with special chars** — quote if the pattern contains characters that could confuse the parser (e.g., `"*.pyc"`)
- **Integers** — bare numbers, no quotes
- **Lists** — one item per line with `- ` prefix, indented under the parent key

### Error Level Tagging

When adding validation rules, use the three-tier error level system:
- `[spec]` — Agent Skills specification requirement (typically `LEVEL_FAIL`)
- `[platform: X]` — platform-specific restriction (typically `LEVEL_WARN`)
- `[foundry]` — foundry convention/recommendation (typically `LEVEL_INFO` or `LEVEL_WARN`)

## Common Mistakes

- Hardcoding a validation limit in Python instead of adding it to `configuration.yaml`
- Forgetting to convert string values to `int()` in `constants.py` — the parser returns all scalars as strings
- Using flow syntax (`[a, b, c]`) that the custom parser does not support
- Adding a new section without cleaning up private variables with `del` at the end of `constants.py`
- Regex patterns using features beyond Python's `re` module
- Forgetting the inline comment explaining a non-obvious threshold
- Adding a key to `configuration.yaml` but not exposing it in `constants.py`
