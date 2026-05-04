---
name: validate-skill-spec
description: >
  Validates a skill directory against the Agent Skills specification
  (agentskills.io/specification). Checks file reference consistency,
  frontmatter compliance, progressive disclosure, and structural
  correctness. Triggers when asked to validate a skill against the spec,
  check skill references, verify spec compliance, audit a skill's
  structure, or confirm a skill is ready for distribution. Also triggers
  on phrases like "is this skill valid," "check spec compliance,"
  "validate file references," "verify the skill structure," or "does
  this skill follow the spec." Use this skill to catch structural issues,
  broken references, and spec violations in any skill directory.
---

# Validate Skill Spec

Validates a skill directory against the Agent Skills specification (agentskills.io/specification). Checks file reference consistency, frontmatter compliance, progressive disclosure, and structural correctness.

This skill provides a manual validation workflow that complements automated validation scripts. It covers checks that scripts may not fully enforce — particularly file reference consistency per the spec's file-references rules.

## When to Use

- After adding, renaming, or removing files in a skill directory
- After editing file references in `SKILL.md` or any referenced file
- After modifying frontmatter fields
- Before a release or distribution
- When unsure if a structural change broke something

## Step 1: Identify the Skill Directory

Determine the skill directory to validate. The skill root is the directory containing `SKILL.md`. Cross-file references resolve file-relative (standard markdown semantics) under the redefined path-resolution rule — every link resolves from the directory containing the file the link lives in. The skill root and each capability root own their own subgraph; capability bodies reach the shared skill root via the explicit `../../<dir>/<file>` form. The full rule lives in the foundry skill's reference document at `skill-system-foundry/references/path-resolution.md`.

If validation scripts are available (e.g., `validate_skill.py` from this repository), run them from within the `skill-system-foundry/` directory:

```bash
cd skill-system-foundry
python scripts/validate_skill.py <skill-path> --verbose
```

If the skill uses nested references intentionally, add `--allow-nested-references`. If the scripts report failures, fix them before proceeding to the manual checks below.

## Step 2: Verify Frontmatter Compliance

Read the `SKILL.md` and check its YAML frontmatter against the spec:

| Field | Required | Rule |
|---|---|---|
| `name` | Yes | Max 64 chars. Lowercase letters, numbers, and hyphens only. Must not start or end with a hyphen. Must not contain consecutive hyphens. Must match the parent directory name |
| `description` | Yes | Max 1024 chars. Non-empty. Must describe what the skill does AND when to use it |
| `license` | No | License name or reference to a bundled license file |
| `compatibility` | No | Max 500 chars. Environment requirements |
| `metadata` | No | Arbitrary key-value map (string keys to string values) |
| `allowed-tools` | No | Space-delimited list of pre-approved tools |

Check each required field against its constraints. For optional fields, verify they meet their limits if present.

## Step 3: Verify File Reference Consistency

The spec defines file reference rules at agentskills.io/specification#file-references. Every file reference in the skill must comply.

### 3a: Extract all file references

Read `SKILL.md` and extract every reference to a file:

- **Markdown links** — `[text](path)` where path is not a URL or anchor
- **Backtick-quoted paths** — paths in backticks that contain `/` and point to skill-internal files

Filter out:
- URLs (starting with `http://`, `https://`, or protocol-relative `//`)
- Anchor-only links (`#section`)
- Template placeholders (containing `<` or `>`)

### 3b: Check that every referenced file exists

For each extracted reference, resolve it file-relative (from the directory containing the file the link lives in) per the redefined path-resolution rule. Strip any fragment (`#section`), query string, or title annotation before resolving.

Verify that each resolved path:
- Points to an existing file (not a directory)
- Is readable (no encoding or permission errors)

Report any reference that does not resolve to an existing file.

### 3c: Check that every bundled file is referenced

List all files in the skill's subdirectories (`references/`, `scripts/`, `assets/`, and any other directories). Compare against the references extracted from `SKILL.md`.

An unreferenced file means agents do not know it exists and cannot load it on demand. Every bundled file should be linked from `SKILL.md` with a description of what it contains and when to use it.

Report any file that exists in the skill directory but is not referenced from `SKILL.md`.

### 3d: Verify path format

All file references must comply with these rules:

- **File-relative resolution** — paths must be relative, resolved from the directory containing the file the link lives in (standard markdown semantics)
- **No absolute paths** — any path starting with `/` or a drive letter (e.g., `C:\`) is a violation
- **`..` segments are legal** — they are how a capability reaches the shared skill root (`../../<dir>/<file>`). Paths whose `..` chain escapes the skill root entirely are out of scope and surfaced as INFO, not failures
- **Forward slashes only** — all paths must use `/`, not `\`. This is a cross-platform portability requirement

### 3e: Verify reference depth

The spec says: "Keep file references one level deep from SKILL.md. Avoid deeply nested reference chains."

- **Level 1** — `SKILL.md` references files in `references/`, `scripts/`, `assets/` (valid)
- **Level 2** — a referenced file itself contains references to other files (nested — should be flagged unless intentionally allowed)

For each file referenced from `SKILL.md`, read it and check whether it contains its own file references. If it does, report the nesting. Deep reference chains risk partial reads by agents, breaking progressive disclosure.

## Step 4: Verify Content Structure

Check that the skill follows progressive disclosure:

### Line count

`SKILL.md` should stay under 500 lines. Count the lines and report if the limit is approached or exceeded. When approaching the limit, detailed material should be moved to `references/` files.

### Reference files over 100 lines

Any referenced file over 100 lines should include a table of contents at the top to help agents navigate.

### Description quality

The `description` field is the primary trigger mechanism. Check:
- Does it describe what the skill does? (concrete verbs and nouns)
- Does it describe when to trigger? (user intent phrases and keywords)
- Is it specific enough to distinguish from related skills?
- Is it keyword-rich, erring toward over-triggering rather than under-triggering?

### Directory structure

The skill may contain these optional directories:
- `scripts/` — executable code
- `references/` — additional documentation
- `assets/` — templates and static resources

Verify that files are organized in the appropriate directories. Scripts should not live in `references/`, documentation should not live in `scripts/`.

## Step 5: Report Results

Structure the output:

```
## Skill Validation Report

**Skill:** <skill-name>
**Path:** <skill-directory-path>

### Frontmatter
- name: (valid/invalid — details)
- description: (valid/invalid — length, quality assessment)
- optional fields: (list any issues)

### File Reference Consistency
- Missing targets: (list or "None")
- Unreferenced files: (list or "None")
- Invalid paths: (list or "None")
- Forward-slash violations: (list or "None")
- Nested references: (list or "None — intentional/unintentional")

### Content Structure
- Line count: X/500
- Files over 100 lines without ToC: (list or "None")
- Description quality: (assessment)

### Overall
(Clean / Issues found — with summary of what to fix)
```
