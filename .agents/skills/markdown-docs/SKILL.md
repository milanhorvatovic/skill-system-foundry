---
name: markdown-docs
description: >
  Enforces documentation quality and structural consistency across Markdown
  files in the Skill System Foundry repository. Triggers on creating, editing,
  reviewing, or auditing any .md file — including SKILL.md entry points,
  reference documents, README files, capability.md files, role definitions,
  and CONTRIBUTING.md. Also triggers when asked to check documentation
  consistency, fix cross-references, improve descriptions, enforce progressive
  disclosure, review frontmatter formatting, or align terminology across files.
  Use this skill whenever Markdown content is being created or modified,
  even if the user does not explicitly mention "documentation."
---

# Markdown Documentation Skill

Enforces documentation quality, structural consistency, and progressive disclosure across all Markdown files in the Skill System Foundry repository.

This skill codifies the conventions from the repository's existing documentation standards. It applies to every `.md` file — entry points (`SKILL.md`, `capability.md`), reference documents, templates, READMEs, and contribution guides.

## Content Principles

### Conciseness-First

The model is already smart. Only add context it does not already have.

Challenge every paragraph:
- "Does the model really need this explanation?"
- "Can I assume it knows this?"
- "Does this paragraph justify its token cost?"

Do not explain general programming concepts, standard library APIs, or well-known conventions. If a sentence can be removed without losing meaning, remove it.

### Voice and Terminology

- **Third person in skill descriptions** — "Validates skills and generates reports" not "I validate skills" or "You can use this to validate skills"
- **One term per concept** — pick one term and use it everywhere within a file and across related files. Do not mix synonyms (e.g., "API endpoint" / "URL" / "route")
- **Actionable over explanatory** — prefer decision checklists, quick references, and step-by-step workflows over narrative prose
- **Simplicity** — prefer the simplest phrasing that conveys full meaning. Avoid nested qualifications, double negatives, and multi-clause sentences when a direct statement works

### DRY Documentation

Each piece of knowledge has a single authoritative location. If the same concept appears in multiple files, one file owns the definition and others reference it. Do not copy content between `SKILL.md`, reference files, templates, or `CONTRIBUTING.md`.

### Line Wrapping

Do not hard-wrap prose lines to a fixed width. See `skill-system-foundry/references/authoring-principles.md` (section "Line wrapping") for the full rule and rationale — this file intentionally does not duplicate it.

## Frontmatter Rules

### Required Fields

Every registered skill directory must have a `SKILL.md` with YAML frontmatter containing:
- `name` — lowercase letters, numbers, and hyphens only. Max 64 characters. Must match the parent directory name exactly. No leading, trailing, or consecutive hyphens
- `description` — max 1024 characters. Third person. Must state what the skill does AND when to trigger it. No XML tags (Anthropic platform restriction)

### Formatting

- **Multi-line descriptions** — use folded block scalar (`>`) to avoid YAML quoting issues with colons, commas, and special characters
- **Single-line values with special characters** — must be quoted. A bare `description: Tracks: milestones` breaks YAML parsing
- **No trailing whitespace in block scalars**

### Optional Fields

- `allowed-tools` — space-delimited tool names (e.g., `Bash Read Write Edit Glob Grep`)
- `compatibility` — max 500 characters, environment requirements
- `license` — SPDX identifier or license name
- `metadata` — arbitrary key-value map (author, version, spec)

## Structure Rules

### Progressive Disclosure

Content flows through three levels:
1. **Metadata** (~100 tokens) — name + description, always in context
2. **Instructions** (<5000 tokens / max 500 lines) — `SKILL.md` body, loaded when triggered
3. **Resources** (unlimited) — `references/`, `scripts/`, `assets/`, loaded on demand

`SKILL.md` serves as an overview that points to detailed materials. Do not inline large reference content into `SKILL.md` when a reference file serves the same purpose.

### Line Limits

- `SKILL.md` must stay under 500 lines. When approaching this limit, move detailed material into `references/` files
- Reference files over 100 lines must include a table of contents at the top

### Cross-Reference Depth

References stay one level deep from the entry point:
- **Valid:** `SKILL.md` → `references/foo.md`
- **Invalid:** `SKILL.md` → `references/foo.md` → `references/bar.md`

The model may partially read chained files, breaking progressive disclosure.

### File References

- **Relative paths from skill root** — all references use paths relative to the directory containing `SKILL.md` (e.g., `references/foo.md`, `scripts/validate.py`)
- **Forward slashes only** — regardless of operating system
- **Descriptive filenames** — `form-validation-rules.md` not `doc2.md`
- **Every bundled file must be linked from `SKILL.md`** — agents need to know what each file contains and when to load it
- **System-root-relative paths in roles** — role files live outside skill directories, so they reference skills as `skills/<domain>/SKILL.md`
- **Orchestration skill exception** — when a `SKILL.md` references roles, use system-root-relative paths (`roles/<group>/<n>.md`)

### Entry Point Naming

- `SKILL.md` (uppercase) — registered entry point for a skill directory
- `capability.md` (lowercase) — entry point for capabilities

## Description Quality Checklist

Descriptions are the primary trigger mechanism — agents use them to decide whether to activate a skill. A weak description means the skill under-triggers.

A good description includes:
1. **What** the skill does — concrete verbs and nouns
2. **When** to trigger it — user intent phrases and keywords
3. **What distinguishes it** from related skills

**Good:** "Manages project timelines, tracks milestones, generates status reports. Use when asked to plan sprints, check deadlines, or summarize progress."

**Bad:** "Helps with projects."

Make descriptions "pushy" — keyword-rich and specific, erring toward over-triggering rather than under-triggering.

## Template Files

Templates in `assets/` follow these rules:
- Preserve placeholder markers so users know what to replace
- Keep templates minimal — a starting point, not a finished product
- Templates must remain valid against `validate_skill.py` after placeholder replacement

## Review Checklist

When creating or editing any Markdown file, verify:

1. **Description quality** — keyword-rich with trigger phrases, or vague and generic?
2. **Conciseness** — every paragraph justifies its token cost?
3. **Simplicity** — direct phrasing, no complex multi-clause sentences?
4. **DRY** — same concept defined in only one place?
5. **Structure** — progressive disclosure respected? Entry point under 500 lines? Cross-references one level deep?
6. **File references** — relative to skill root? Forward slashes? Referenced files exist?
7. **Consistency** — terminology consistent within file and across repository?
8. **Accuracy** — spec claims aligned with validation scripts? File paths valid?
9. **Frontmatter** — folded block scalar for multi-line descriptions? Special characters quoted?
10. **No time-sensitive content** — no dates or version-specific language that will age

## Common Issues

- Vague `description` missing trigger phrases — agents will under-trigger
- Content explaining what the model already knows
- First or second person in skill descriptions
- Same definition duplicated across multiple files instead of referencing a single source
- Overly complex phrasing where a direct statement works
- Inconsistent terminology within or between files
- `SKILL.md` exceeding 500 lines
- Cross-reference chains deeper than one level
- Unreferenced files not linked from `SKILL.md`
- Backslashes in file paths
- Non-descriptive filenames
- Multi-line `description` without folded block scalar
- Unquoted value containing special characters (`:`, `#`, `{`, `}`)
- Missing table of contents in files over 100 lines
- Placeholder markers removed from templates
- Hard-wrapped prose lines instead of one-paragraph-per-line
