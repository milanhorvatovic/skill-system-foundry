# Path Resolution for Cross-File References

The single source of truth for how cross-file paths inside a skill resolve. Every validator, every scaffolding template, every `--help` example, every reviewer comment, and every external integrator follows the rule defined here.

## Contents

- [Why This Rule Exists](#why-this-rule-exists)
- [The Rule](#the-rule)
- [Two Scopes](#two-scopes)
- [External-Reference Syntax](#external-reference-syntax)
- [Liftability Invariant](#liftability-invariant)
- [Concrete Examples](#concrete-examples)
- [What the Validator Enforces](#what-the-validator-enforces)
- [What the Conformance Report Measures](#what-the-conformance-report-measures)
- [Spec Divergence](#spec-divergence)
- [Migration Cheat Sheet](#migration-cheat-sheet)

## Why This Rule Exists

A markdown file is a graph node. Its links are edges that point to other files. An AI agent (or any reading tool) follows those edges by resolving each link relative to the file that contains it — exactly the way a browser, GitHub's renderer, every Markdown LSP, and every off-the-shelf link checker resolve them. That is the resolution standard; the foundry follows it.

A foundry-only convention that requires every reader to know "links resolve from the skill root regardless of which file contains them" is invisible knowledge. Cold-loading agents, generic crawlers, and rendered previews all miss it. Once the convention diverges from standard markdown, every link from a capability file becomes ambiguous: it might point at the file an agent expects, or at the file the foundry rule expects, and only the foundry's validator knows the difference. The rule below removes that ambiguity by making the foundry's resolution agree with what every standard tool already does.

## The Rule

Every cross-file reference inside a skill resolves **relative to the file that contains the reference**, using standard markdown semantics. There is no privileged base directory. The skill root is no longer a special resolution context — it is just the directory that happens to contain `SKILL.md`.

This is one rule, applied uniformly. There is no per-file-type variation, no announcement required, no out-of-band knowledge.

## Two Scopes

A skill's filesystem is divided into two scopes that own their own subgraph of references:

| Scope | Root | Owns |
|---|---|---|
| **Skill root** | the directory containing `SKILL.md` | `SKILL.md`, `references/`, `assets/`, `scripts/` (the shared root tree) |
| **Capability root** | each `capabilities/<name>/` directory | `capability.md`, `capabilities/<name>/references/`, `capabilities/<name>/assets/`, `capabilities/<name>/scripts/` |

Each scope is a self-contained connected component of the link graph. Within a scope, every reference resolves file-relative and lands inside that same scope. References that cross scope boundaries are *external references* (next section).

A capability is structurally a sub-skill: it has its own optional `references/`, `assets/`, `scripts/`, and a `capability.md` that mirrors `SKILL.md`'s role. Treat each capability as if it were a standalone skill living at `capabilities/<name>/` — every link inside it resolves from `capabilities/<name>/`, never from the enclosing skill root.

## External-Reference Syntax

A reference that crosses out of a capability scope into the shared skill root uses an explicit parent-traversal path. From `capabilities/<name>/capability.md` itself — the canonical case — the form is:

```markdown
[foo](../../references/foo.md)
[bar](../../assets/bar.md)
[baz](../../scripts/baz.py)
```

`../../` is the exact depth from `capability.md`: `..` to leave `capabilities/<name>/`, `..` again to leave `capabilities/`, landing at the skill root. The number of `..` segments depends on the source file's depth — a deeper capability-local file under `capabilities/<name>/references/<f>.md` needs `../../../<dir>/<file>` to reach the skill root, and the validator computes that walk file-relative under standard markdown semantics. Whatever the depth, the link must resolve to a real file inside the skill root.

The validator classifies a reference based on where its **resolved target** lands, not on the literal `..` count. A capability link whose resolved target lives under another scope (the shared skill root, or a sibling capability) is the cross-scope case the validator surfaces; a capability-local link such as `../capability.md` from `capabilities/<n>/references/foo.md` resolves back into the *same* capability and stays intra-scope. Existence is still checked. The scope tag distinguishes external from intra-capability for downstream consumers (the future capability-lift tool, the conformance report, integrators triaging findings).

References from `SKILL.md` or from any file under the shared skill-root tree (`references/`, `assets/`, `scripts/`) never need `..` to reach skill-root resources. They are at or under the skill root already, so file-relative resolution stays within scope. A `..` chain that escapes the skill root entirely is surfaced by the validator as INFO (out of scope) rather than treated as an intra-skill external reference.

There is no foundry-specific sigil (no `@skill/...`, no `<skill-root>/...`). The foundry follows standard markdown.

## Liftability Invariant

A capability is liftable to a standalone skill through purely mechanical rewriting of its external references. No semantic rework is needed.

To promote `capabilities/<name>/` to a standalone skill, a future foundry tool walks the capability's filesystem, finds every reference whose path starts with `..`, and either:

- inlines the referenced shared content into the new standalone skill's own `references/`/`assets/`/`scripts/`, or
- copies the referenced file and rewrites the link to the new local path.

That is the only class of edge that needs touching. Internal capability references stay as-is, because they already resolve file-relative from the capability root and that root becomes the new skill root after the lift.

The rule above guarantees this property:

1. Every intra-capability reference is file-relative within the capability scope. The capability sub-graph is self-contained.
2. Every external reference is uniquely identifiable by its leading `..` segment. The lift tool finds them with a trivial regex.
3. The lift tool needs no per-skill configuration, no special-case logic, no semantic understanding of the link target.

A capability whose link graph satisfies the rule is *mechanically liftable*. A capability that violates the rule (e.g. uses skill-root-relative form for shared resources, or omits `..` on a cross-scope link) is not liftable without manual review. The validator's per-scope finding output makes that distinction visible.

## Concrete Examples

### From `SKILL.md` (skill root)

```markdown
[Authoring Principles](references/authoring-principles.md)
[Validation Capability](capabilities/validation/capability.md)
[Bundle Script](scripts/bundle.py)
[Manifest Template](assets/manifest.yaml)
```

Every link is file-relative from `SKILL.md`'s directory, which is the skill root. Identical to how the link would resolve under any standard markdown reader.

### From `capabilities/<n>/capability.md` (capability root)

```markdown
[Local Reference](references/yaml-support.md)
[Local Asset](assets/sample.yaml)
[Shared Authoring Principles](../../references/authoring-principles.md)
[Shared Validate Script](../../scripts/validate_skill.py)
```

The first two stay within the capability scope (resolve under `capabilities/<n>/`). The last two are external references using `../../` to reach the shared skill root.

### From `references/<file>.md` (shared skill-root reference)

```markdown
[Authoring Principles](authoring-principles.md)
[Anti-Patterns](anti-patterns.md)
```

Bare sibling filenames. No `references/` prefix, because the file is *already* in `references/` — file-relative resolution starts from there.

### From `capabilities/<n>/references/<file>.md` (capability-local reference)

```markdown
[Capability Entry](../capability.md)
[Sibling Capability Reference](other-symlink-doc.md)
[Shared Tool Integration](../../../references/tool-integration.md)
```

`..` to leave `capabilities/<n>/references/` back to the capability, sibling resolution within the capability-local references, and `../../../` (three levels) to reach the shared skill root.

## What the Validator Enforces

`validate_skill.py` and `audit_skill_system.py` apply the rule per-scope. Every finding includes:

- The **rule name** (`path-resolution`).
- The **scope** (`skill` for the skill root, `capability:<name>` for a capability).
- The **offending file** (skill-root-relative path).
- The **offending path** (the link as written).
- A **recommended replacement** when the conversion is mechanical.

Finding levels:

- **WARN** — the link is broken under file-relative resolution: the resolved target does not exist, is not a regular file, or cannot be read. Some WARN findings are mechanically fixable — a legacy capability link to a shared resource resolves under the *previous* (skill-root) rule but not under the current one, and `--fix` rewrites it to the canonical `../../<dir>/<file>` form. Others are genuinely broken and need author attention; the rewriter never invents a target.
- **INFO** — the link resolves but is informational: an *external reference* (a capability link into the shared skill root, recorded for the future capability-lift tool) or an *out-of-skill reference* (a path whose `..` chain escapes the skill root entirely; existence is not checked because the validator declines to act as a filesystem oracle for paths it does not own).

The validator does not emit FAIL for path-resolution findings — a missing skill-internal target is a WARN. FAIL is reserved for spec-level violations elsewhere in the validator (missing `SKILL.md`, malformed frontmatter, etc.).

Under `--json`, every finding text carries the rule tag, scope tag, source file, and offending path inline, and the level is the bucket the finding lands in (`errors.failures`, `errors.warnings`, `errors.info`). Both `validate_skill.py` and `audit_skill_system.py` also emit a top-level `path_resolution` block (`rule_name`, `documentation_path`) so consumers can navigate to this document from any output stream. The mechanical-recommendation surface is the structured `fixes[]` array under `--fix --json` — each row has `file`, `line`, `original`, and `replacement` keys, and unfixable path-resolution findings travel alongside it under `unfixable_findings`. Agent-driven tooling that needs the recommendation programmatically consumes the `--fix --json` shape; tooling that only needs the diagnostic stream parses the finding text.

The `--fix` mode previews mechanical conversions for the source files. By default `--fix` is dry-run and prints each rewrite; `--fix --apply` writes the changes. Path-resolution findings that the rewriter cannot resolve mechanically (a broken intra-skill link with no clear legacy target to rewrite to) are surfaced alongside the rewrites under `unfixable_findings` (JSON) or printed below the rewrite list (text); the run exits non-zero whenever any unfixable finding remains so CI / scripts can gate on a clean run. `--fix` never invents a target.

## What the Conformance Report Measures

`../scripts/reference_conformance_report.py` computes per-skill metrics that quantify how well the skill's link graph matches what a standard markdown reader sees. The report is run during PR review (CI gate), at bundle time, during integrator onboarding, and in the weekly drift workflow. See `directory-structure.md` for the full list of use cases.

Metrics:

- `total_links` — total internal cross-file links across all `.md` files in the skill.
- `resolves_under_standard_semantics` — count of links that resolve to an existing file when interpreted file-relative.
- `broken_under_standard_semantics` — count of links that fail to resolve under standard semantics.
- `connected_components` — number of weakly-connected components in the link graph reachable from `SKILL.md` and every `capability.md`. A router skill in which `SKILL.md` links every capability typically reports `1` because the router edges merge each per-scope sub-graph into a single component; a larger value signals capability scopes that no router edge reaches (a useful drift signal for accidentally unrouted capabilities).
- `files_unreachable_from_root` — count of `.md` files under the skill that no root reaches.
- `external_edges_per_capability` — for each capability, the number of `../../` edges into the shared skill root. The lift tool's per-capability rewrite cost.

A skill conforms when `broken_under_standard_semantics == 0` and `files_unreachable_from_root == 0`. Other fields are diagnostic.

## Spec Divergence

The Agent Skills specification's *File references* section says paths "should be relative to the skill root". The spec's example shows a link from `SKILL.md`, which sits at the skill root — under that example, file-relative resolution and skill-root-relative resolution produce identical results. The spec is silent on capabilities (capabilities are a foundry concept, not a spec concept), so the resolution rule for capability files is the foundry's to define.

The foundry diverges from a strict reading of the spec text in one way: capability files resolve their links file-relative, not skill-root-relative. This is consistent with the spec's *intent* (paths must be unambiguously resolvable) and with the spec's only worked example (which is a `SKILL.md` link, where the two interpretations coincide). It diverges from the *literal text* in the way the foundry intends: every link in every file resolves the way standard markdown resolves it, with no privileged base.

This divergence is recorded once here, cross-referenced from `agentskills-spec.md`. Integrators who care about strict spec literalism can keep their skills in single-scope form (no capabilities) — those skills satisfy both readings simultaneously.

## Migration Cheat Sheet

For an existing skill that uses the old skill-root-relative convention everywhere:

| Old form (anywhere in the skill) | New form (location-dependent) |
|---|---|
| `[x](references/<f>.md)` from `SKILL.md` | unchanged — `[x](references/<f>.md)` |
| `[x](references/<f>.md)` from `capabilities/<n>/capability.md` | `[x](../../references/<f>.md)` |
| `[x](references/<f>.md)` from `references/<b>.md` | `[x](<f>.md)` |
| `[x](capabilities/<n>/references/<f>.md)` from `capability.md` | `[x](references/<f>.md)` |
| `[x](capabilities/<n>/references/<f>.md)` from `capabilities/<n>/references/<b>.md` | `[x](<f>.md)` |
| `[x](scripts/<f>.py)` from `capability.md` | `[x](../../scripts/<f>.py)` |
| `[x](assets/<f>.md)` from `capability.md` | `[x](../../assets/<f>.md)` |

Run `python scripts/validate_skill.py <skill> --fix` to preview the mechanical conversions, and `--fix --apply` to write them. Inspect the diff before committing — the rewriter handles the mechanical class but a human still reviews the result.
