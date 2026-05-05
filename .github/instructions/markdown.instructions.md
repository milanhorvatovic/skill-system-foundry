---
applyTo: "**/*.md"
---

# Markdown Documentation Instructions

Review changes as a **documentation quality reviewer**, ensuring all Markdown files maintain structural clarity, conciseness, and consistency with the skill system's progressive disclosure model.

## Content Principles

- **Conciseness-first** — only add context the model does not already have. Do not explain general programming concepts, standard library APIs, or well-known conventions. If a sentence can be removed without losing meaning, remove it
- **Third person in skill descriptions** — "Processes files and generates reports" not "I can help you process files" or "You can use this to process files"
- **One term per concept** — pick one term and use it everywhere. Do not mix synonyms (e.g., "API endpoint" / "URL" / "route") within a file or across related files
- **Actionable over explanatory** — prefer decision checklists, quick references, and step-by-step workflows over narrative prose
- **Don't repeat yourself** — each piece of knowledge should have a single authoritative location. If the same concept appears in multiple files, one file should own the definition and others should reference it. Do not copy content between `SKILL.md`, reference files, templates, or `CONTRIBUTING.md`
- **Simplicity** — prefer the simplest phrasing that conveys the full meaning. Avoid nested qualifications, double negatives, and multi-clause sentences when a direct statement works
- **Do not hard-wrap prose** — one paragraph is one logical line; let the renderer handle wrapping. Hard-wrapping produces noisy diffs when a single word changes mid-paragraph and forces every editor to honour the same column limit. Lists, tables, code fences, and frontmatter values keep their natural line structure (one item per line)

## Description Quality

Skill descriptions are the primary trigger mechanism — agents use them to decide whether to activate a skill. A description must be "pushy": keyword-rich and specific about what the skill does and when to use it.

- **Good:** "Manages project timelines, tracks milestones, generates status reports. Use when asked to plan sprints, check deadlines, or summarize progress."
- **Bad:** "Helps with projects."

Include: what the skill does (verbs and nouns), when to trigger it (user intent phrases), and what distinguishes it from related skills.

## Frontmatter Formatting

- **Use folded block scalar (`>`) for multi-line descriptions** — avoids YAML quoting issues with colons, commas, and special characters
- **Single-line values with special characters must be quoted** — a bare `description: Tracks: milestones` breaks YAML parsing because of the unquoted colon
- **No trailing whitespace in block scalars** — some parsers treat trailing spaces differently

## Naming Convention

- **`SKILL.md` (uppercase)** is the registered entry point for a skill directory — agents discover and load it
- **Capabilities use `capability.md`** as their entry point

## Structure Rules

- **Progressive disclosure** — `SKILL.md` serves as an overview that points to detailed materials. Do not inline large reference content into `SKILL.md` when a reference file serves the same purpose
- **`SKILL.md` under 500 lines** — move detailed reference material to separate files. Agents load these on demand, so smaller files mean less context usage
- **Cross-references stay one level deep from each entry point** — entry points are `SKILL.md` (for standalone skills and routers) and `capability.md` (for capabilities). From an entry point, one hop to a reference file is allowed: `SKILL.md` → `references/foo.md` or `capability.md` → `references/foo.md`. Reference files, including capability-local reference docs, must not link to other reference files — avoid chains where a referenced file itself references other files
- **Reference supporting files from the entry point** — for standalone skills, every file in `references/`, `scripts/`, or `assets/` should be linked directly from `SKILL.md`. For router skills, `SKILL.md` links capabilities, and each `capability.md` lists its own resources in a Key Resources section. Every shared file must be reachable from at least one entry point (`SKILL.md` or `capability.md`)
- **Table of contents for long files** — reference files over 100 lines should include a table of contents at the top
- **No time-sensitive content** — use an "old patterns" section for deprecated approaches instead of embedding dates or version-specific language that will age

## File References

- **File-relative resolution** — every cross-file reference resolves from the directory containing the file the link lives in (standard markdown semantics). Two scopes own their own subgraph: the skill root (containing `SKILL.md`, `references/`, `assets/`, `scripts/`) and each capability root (`capabilities/<name>/`). A capability reaches the shared skill root via the explicit `../../<dir>/<file>` form. The full rule, the liftability invariant, the migration cheat sheet, and the validator finding shape live in [`skill-system-foundry/references/path-resolution.md`](../../skill-system-foundry/references/path-resolution.md)
- **Forward slashes only** — regardless of operating system
- **Descriptive filenames** — `form-validation-rules.md` not `doc2.md`
- **System-root-relative paths in roles** — role files live outside skill directories, so they reference skills as `skills/<domain>/SKILL.md` (relative to the directory containing `skills/` and `roles/`)
- **Orchestration skill exception** — when a `SKILL.md` references roles, use system-root-relative paths (`roles/<group>/<name>.md`) for consistency with how roles reference skills

## Template Files (`assets/`)

- Preserve placeholder markers so users know what to replace
- Keep templates minimal — provide a starting point, not a finished product
- Templates must remain valid against `validate_skill.py` after placeholder replacement

## Review Focus Areas

1. **Description quality** — Is the `description` keyword-rich with trigger phrases, or is it vague and generic? Would an agent reliably activate this skill based on the description alone?
2. **Conciseness** — Does every paragraph justify its token cost? Could it be shorter without losing meaning?
3. **Simplicity** — Is the phrasing direct and clear? Could complex sentences be broken into simpler ones?
4. **DRY** — Is the same concept defined in only one place? Do other files reference it rather than duplicate it?
5. **Structure** — Does the file follow progressive disclosure? Is `SKILL.md` under 500 lines? Are cross-references one level deep?
6. **File references** — Do all markdown links resolve under standard file-relative semantics? Capability files reach the shared skill root via `../../<dir>/<file>`? Forward slashes only? Do referenced files actually exist? Are role paths system-root-relative?
7. **Consistency** — Is terminology consistent within the file and across the repository?
8. **Accuracy** — Are spec claims aligned with the validation scripts? Are referenced file paths valid?

## Common Issues to Flag

- Vague or generic `description` that lacks trigger phrases and keyword coverage — agents will under-trigger
- Content that explains what the model already knows (general Python, well-known conventions, standard algorithms)
- First or second person in skill descriptions
- Same definition or rule duplicated across multiple files instead of referencing a single source
- Overly complex phrasing — nested qualifications, double negatives, or multi-clause sentences where a direct statement works
- Inconsistent terminology within a file or between related files
- `SKILL.md` exceeding 500 lines without delegating to reference files
- Cross-reference chains deeper than one level from the entry point (`SKILL.md` for standalone skills, `capability.md` for capabilities within router skills)
- Unreferenced files in `references/`, `scripts/`, or `assets/` not reachable from `SKILL.md` (directly for standalone skills, or transitively through capabilities for router skills)
- Backslashes in file paths
- Non-descriptive filenames (`doc2.md`, `notes.md`, `misc.md`)
- Capability file using legacy skill-root form (`references/foo.md`) instead of file-relative form (`../../references/foo.md` for shared resources, or local `references/foo.md` for capability-internal references)
- Reference file using redundant `references/` prefix when linking siblings under the shared `references/` directory
- Role file using skill-root-relative paths instead of system-root-relative paths
- Missing table of contents in files over 100 lines
- Placeholder markers removed or overwritten in template files
- Multi-line `description` without folded block scalar (`>`) or unquoted value containing special characters (`:`, `#`, `{`, `}`)
- Hard-wrapped prose lines instead of one-paragraph-per-line — defer wrapping to the renderer

---

## Prose YAML fences

When reviewing Markdown that contains ```` ```yaml ```` fenced code blocks inside the in-scope globs (`SKILL.md`, `capabilities/**/*.md`, `references/**/*.md`):

- Apply the **counter-example convention** in `references/authoring-principles.md` — counter-examples must be opted out via the `<!-- yaml-ignore -->` HTML comment on the line immediately above the fence-open line, with no blank line between.
- Confirm the fence shape matches: three backticks, lowercase `yaml` token, no whitespace between backticks and `yaml`, opener at byte offset 0.
- Avoid embedding column-0 ```` ``` ```` lines inside YAML block scalars — the extractor terminates the fence at the first column-0 ```` ``` ```` per CommonMark.

For the parser's supported surface and the three pinned grammar-gap rejections, see `skill-system-foundry/references/yaml-support.md`.

---

**Remember:** Review as a documentation quality reviewer. Prioritize conciseness, structural clarity, and consistency.
