# Bundling

Package a skill as a self-contained zip bundle for distribution. The archive packages exactly one skill directory, preserves its internal layout, and excludes large or non-essential assets not required at runtime (patterns defined in [configuration.yaml](scripts/lib/configuration.yaml)).

## Prerequisites

- The skill must pass `validate_skill.py` (spec compliance)
- The skill's description must not exceed 200 characters (Claude.ai limit)
- All file references in the skill must resolve to existing files
- No external reference may point to another skill (cross-skill boundary violation) — unless `--inline-orchestrated-skills` is used for Path 1 coordination skills

## Usage

```bash
python scripts/bundle.py <skill-path> [--system-root <path>] [--output <path>] [--target claude|gemini|generic] [--inline-orchestrated-skills] [--verbose] [--json]
```

- `--system-root`: Path to the skill system root (contains `skills/`, `roles/`). If omitted, inferred by walking up from the skill path.
- `--output`: Output path for the zip. Defaults to `<skill-name>.zip` in the current directory.
- `--target`: Target platform. `claude` (default) enforces 200-char description limit as FAIL; `gemini` and `generic` downgrade to WARNING.
- `--inline-orchestrated-skills`: When bundling a Path 1 coordination skill, inline the orchestrated skills into the bundle. Without this flag, cross-skill references are rejected.

## What the Bundler Does

1. **Pre-validates** — runs spec validation, checks description length, scans references, and rejects broken links, cross-skill references, and cycles.
2. **Assembles the bundle** — copies skill files and resolved external dependencies, then rewrites markdown paths to bundle-relative form.
3. **Post-validates** — verifies all markdown references resolve within the bundle and exactly one SKILL.md exists.
4. **Creates the zip** with the skill folder as the archive root.

The archive root contains a `<skill-name>/` wrapper directory matching the skill's `name` field. Files must not be placed directly at the archive root. Any system-level `roles/` referenced by the skill are inlined under the skill directory to make the bundle self-contained.

## Example

```bash
# Bundle a skill with an inferred system root
python scripts/bundle.py /path/to/project/.agents/skills/project-mgmt --output /path/to/project/dist/

# Bundle with an explicit system root
python scripts/bundle.py /path/to/project/.agents/skills/project-mgmt --system-root /path/to/project/.agents --output /path/to/project/project-mgmt.zip
```

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| Description exceeds 200 characters | Claude.ai limit is stricter than the 1024-char spec limit | Shorten the description |
| Broken reference | A markdown link points to a non-existent file | Fix the file path or remove the reference |
| Cross-skill reference | An external file references another skill | Remove the reference, inline the content, or use `--inline-orchestrated-skills` for Path 1 coordination skills |
| Circular reference between external files | External docs reference each other in a cycle | Break the cycle — this is likely a structural bug |
| Multiple SKILL.md files | Case-insensitive scan found duplicates | Rename capability files to `capability.md` |

## Limitations

- Path rewriting is performed only in `.md` files. References in scripts (Python, shell, etc.) are detected and reported as warnings but not rewritten — update them manually.
- The bundler does not modify the original skill files. All changes are made in the bundle copy.

## Key Resources

**Scripts:**
- [bundle.py](scripts/bundle.py) — Bundle entry point
- [bundling.py](scripts/lib/bundling.py) — Core bundling logic
- [references.py](scripts/lib/references.py) — Reference scanning, resolution, and graph traversal
- [configuration.yaml](scripts/lib/configuration.yaml) — Bundle exclusion patterns and limits
