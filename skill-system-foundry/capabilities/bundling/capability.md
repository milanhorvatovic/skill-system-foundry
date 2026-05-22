---
allowed-tools: Bash Read
---

# Bundling

Package a skill as a self-contained zip bundle for distribution. The archive packages exactly one skill directory, preserves its internal layout, and excludes large or non-essential assets not required at runtime (patterns defined in [configuration.yaml](../../scripts/lib/configuration.yaml)).

## Prerequisites

- The skill must pass `validate_skill.py` (spec compliance)
- The skill's description must not exceed 200 characters (Claude.ai limit)
- All file references in the skill must resolve to existing files
- No external reference may point to another skill (cross-skill boundary violation) — unless `--inline-orchestrated-skills` is used for Path 1 coordination skills. Cross-skill references would produce incomplete bundles; keep dependencies inside the bundled skill, or use `--inline-orchestrated-skills` for coordination skills that intentionally orchestrate other skills.

## Usage

```bash
python scripts/bundle.py <skill-path> [--system-root <path>] [--output <path>] [--target claude|gemini|generic] [--inline-orchestrated-skills] [--verbose] [--json]
```

- `--system-root`: Path to the skill system root (contains `skills/`, `roles/`). If omitted, inferred by walking up from the skill path.
- `--output`: Output path for the zip. Defaults to `<skill-name>.zip` in the current directory.
- `--target`: Target platform. `claude` (default) enforces 200-char description limit as FAIL; `gemini` and `generic` downgrade to WARNING.
- `--inline-orchestrated-skills`: When bundling a Path 1 coordination skill, inline the orchestrated skills into the bundle. Without this flag, cross-skill references are rejected.

## What the Bundler Does

`bundle.py` implements the **plan-validate-execute** pattern (see [authoring-principles.md](../../references/authoring-principles.md#workflows-and-feedback-loops)): build a structured plan, validate it against the source of truth, then execute — only after validation passes. Concretely:

1. **Pre-validates** — runs spec validation, checks description length, scans references, and rejects broken links, cross-skill references, and cycles. This is the plan-validation step: a broken reference graph fails the bundle before any file is touched.
2. **Assembles the bundle** — copies skill files and resolved external dependencies, then rewrites markdown paths to bundle-relative form.
3. **Post-validates** — verifies all markdown references resolve within the bundle and exactly one SKILL.md exists. This is the execute-verification step: rewriting a path is a destructive transform on the bundle copy, so the post-pass confirms the assembled artifact still resolves cleanly.
4. **Creates the zip** with the skill folder as the archive root.

The archive root contains a `<skill-name>/` wrapper directory matching the skill's `name` field. Files must not be placed directly at the archive root. Any system-level `roles/` referenced by the skill are inlined under the skill directory to make the bundle self-contained.

## What Counts as a Reference

The bundler uses the **same definition of a file reference as `validate_skill`** (the configured `reference_patterns` in `configuration.yaml`): a markdown link or backtick whose target is anchored on a recognized top-level directory (capabilities, references, scripts, assets, shared) or — for markdown links — ends in a known file extension. Prose that merely *looks* path-like is not a reference and never blocks a bundle: CLI slash-commands (`/review`), provider model IDs (`provider/model`), templated placeholders (`/{name}`), and illustrative absolute or home paths (`/tmp`, `~/.config`) are all ignored. Links inside fenced code blocks are skipped by reference *detection*, so a worked example never causes a finding and is never bundled on its own account — but the path *rewriter* runs over the whole file, so a fenced example whose target also matches a separately-bundled file may still have its path rewritten during assembly.

Two deliberate softer severities keep documentation-heavy skills bundleable:

- **References that escape the skill** to a non-existent shared or cross-skill resource (a documented out-of-skill example path that points above the skill root) are surfaced as a **warning**, not a failure — mirroring `validate_skill`, which declines to existence-check out-of-skill paths. They are never bundled; an *in-skill* broken reference is still a hard failure.
- **Path-like tokens in non-markdown files** (Python or YAML docstrings, error-message examples) are a best-effort heuristic with no `validate_skill` counterpart. A token must carry a file-extension shape to be considered, and an unresolved one is a **warning** — the file ships into the bundle verbatim regardless, so it cannot break bundle integrity.

**Migration note:** because the bundler now bundles exactly what `validate_skill` recognizes, a file referenced only via an unrecognized form (for example a backtick path under a non-recognized prefix such as roles) is no longer auto-bundled. If a needed file stops appearing in a bundle after upgrading, reference it with a recognized markdown link form.

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

## Gotchas

- **Description over 200 chars on Claude.ai target.** Spec allows 1024; Claude.ai rejects over 200. The bundler fails-fast at pre-validation when `--target claude` (default). Either shorten the description or switch to `--target gemini|generic` (downgrades to WARNING).
- **Cross-skill references reject the bundle.** A reference from one skill into another skill's directory is a structural violation — the bundle would be incomplete. For Path 1 coordination skills only, use `--inline-orchestrated-skills` to inline the orchestrated skills. For other cases, fix the reference or inline the content.
- **Path rewriting touches `.md` files only.** Script paths (Python imports, shell `python scripts/...` invocations, `--help` output, docstrings) are detected and warned about, never rewritten. Update them manually before bundling, or expect them to break in the bundle.

## Key Resources

**Scripts** — run by trigger:
- [bundle.py](../../scripts/bundle.py) — run when packaging a skill for distribution (Claude.ai upload, release asset, marketplace).

**Configuration** — read by trigger:
- [configuration.yaml](../../scripts/lib/configuration.yaml) — read when a file or directory is unexpectedly excluded from a bundle, or when adding a new exclusion pattern under `bundle_exclusions`.
