# Authoring Principles

Shared skill authoring principles consolidated from the official skill creation guides published by Anthropic, OpenAI (Codex), and Google (Gemini CLI). These principles represent the current cross-platform consensus for writing effective skills.

Skill System Foundry maintains these principles as a unified reference because the vendor skill creators cannot be loaded together — each is written for a single tool. This file provides the combined picture.

## Provenance

| Principle | Anthropic | OpenAI | Google |
|---|:-:|:-:|:-:|
| Conciseness | ✓ | ✓ | ✓ |
| Writing Descriptions | ✓ | ✓ | ✓ |
| Degrees of Freedom | ✓ | ✓ | ✓ |
| Progressive Disclosure | ✓ | ✓ | ✓ |
| Content Guidelines | ✓ | ✓ | ✓ |
| Common Patterns | ✓ | | ✓ |
| Scripts and Executable Code | ✓ | ✓ | ✓ |
| — Agentic Script Output * | | | ✓ |
| Workflows and Feedback Loops | ✓ | | ✓ |
| Evaluation and Iteration | ✓ | ✓ | ✓ |

> \* Agentic Script Output is covered within the [Scripts and Executable Code](#scripts-and-executable-code) section (see "Design Output for Model Consumption" subsection).

## Table of Contents

- [Conciseness](#conciseness)
- [Writing Descriptions](#writing-descriptions)
- [Degrees of Freedom](#degrees-of-freedom)
- [Progressive Disclosure in Practice](#progressive-disclosure-in-practice)
- [Content Guidelines](#content-guidelines)
- [Common Patterns](#common-patterns)
- [Scripts and Executable Code](#scripts-and-executable-code)
- [Workflows and Feedback Loops](#workflows-and-feedback-loops)
- [Evaluation and Iteration](#evaluation-and-iteration)

---

## Conciseness

The context window is a shared resource. Your skill competes with the system prompt, conversation history, other skills' metadata, and the user's request.

**Default assumption: the model is already smart.** Only add context it doesn't already have. For every piece of content, ask:
- "Does the model really need this explanation?"
- "Can I assume it knows this?"
- "Does this paragraph justify its token cost?"

**Good** (~50 tokens):
```
## Parse configuration
Use tomllib for TOML parsing:
import tomllib
with open("config.toml", "rb") as f:
    config = tomllib.load(f)
```

**Bad** (~150 tokens):
```
## Parse configuration
TOML (Tom's Obvious Minimal Language) is a configuration file format that
is easy to read. To parse a TOML file, you'll need to use a library.
There are many libraries available...
```

---

## Writing Descriptions

The `description` field is the primary discovery mechanism. The model uses it to select the right skill from potentially 100+ available skills.

### Rules

- **Write in third person (foundry convention).** Descriptions are injected into the system prompt. Consistent POV improves discovery. Note: the spec does not mandate a specific voice, but third person is strongly recommended.
  - Good: "Processes data files and generates reports"
  - Bad: "I can help you process data files"
  - Bad: "You can use this to process data files"

- **Be specific and include trigger terms.** Include both what the skill does and specific contexts/keywords for when to use it.

- **Be slightly pushy.** Skills tend to under-trigger. Include more trigger contexts than you think necessary.

- **Include negative triggers when helpful.** "Use when... Don't use when..." improves routing accuracy.

- **Max 1024 characters.** Hard limit from the spec.

### Examples

**Good:**
```yaml
description: >
  Manage deployment pipelines, run rollbacks, and monitor release health.
  Use when working with deployments or when the user mentions releases,
  rollbacks, or CI/CD pipelines.
```

**Good (with negative trigger):**
```yaml
description: >
  Comprehensive data transformation, validation, and export for structured
  datasets. Use when working with data pipelines. Do not use for raw log
  analysis or monitoring tasks.
```

**Bad:**
```yaml
description: Helps with deployments.
```

---

## Degrees of Freedom

Match the level of specificity to the task's fragility and variability.

### High Freedom (text instructions)

Use when multiple approaches are valid and decisions depend on context.

```
## Code review process
1. Analyze the code structure and organization
2. Check for potential bugs or edge cases
3. Suggest improvements for readability
4. Verify adherence to project conventions
```

### Medium Freedom (pseudocode / parameterized scripts)

Use when a preferred pattern exists but some variation is acceptable.

```
## Generate report
Use this template and customize as needed:
def generate_report(data, format="markdown", include_charts=True):
    # Process data, generate output, optionally include visualizations
```

### Low Freedom (exact scripts, no parameters)

Use when operations are fragile, consistency is critical, or a specific sequence must be followed.

```
## Database migration
Run exactly this script:
python scripts/migrate.py --verify --backup
Do not modify the command or add additional flags.
```

**Analogy:** Narrow bridge with cliffs = exact guardrails (low freedom). Open field with no hazards = general direction (high freedom).

---

## Progressive Disclosure in Practice

SKILL.md serves as an overview that points to detailed materials as needed.

### Pattern 1: High-level guide with references

```markdown
# <Domain Name>
## Quick start
[core instructions here]
## Advanced features
**<Feature A>**: See FEATURE-A.md
**API reference**: See REFERENCE.md
```

### Pattern 2: Domain-specific organization

```
<domain-skill>/
├── SKILL.md (overview and navigation)
└── references/
    ├── <area-a>.md
    ├── <area-b>.md
    └── <area-c>.md
```

### Pattern 3: Conditional details

```markdown
## Creating documents → Follow "Creation workflow" below
## Editing documents → Follow "Editing workflow" below
**For tracked changes**: See REDLINING.md
```

### Critical Rule: One Level Deep

Keep file references one level deep from SKILL.md. The model may partially read files referenced from other referenced files.

**Bad:** SKILL.md → advanced.md → details.md → actual info **Good:** SKILL.md → advanced.md, SKILL.md → reference.md

### Long Reference Files

For files over 100 lines, include a table of contents at the top.

---

## Content Guidelines

### Avoid Time-Sensitive Information

Use an "old patterns" section for deprecated approaches.

### Use Consistent Terminology

Choose one term per concept. Don't mix "API endpoint" / "URL" / "route".

### Avoid Offering Too Many Options

Provide a default with an escape hatch, not multiple equivalent approaches.

---

## Common Patterns

### Template Pattern

Provide output format templates. Match strictness to requirements.

### Examples Pattern

Provide input/output pairs (like regular prompting):

```
**Example 1:**
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication
```

### Conditional Workflow Pattern

```
1. Determine the modification type:
   Creating new content? → Follow "Creation workflow"
   Editing existing content? → Follow "Editing workflow"
```

---

## Scripts and Executable Code

### Solve, Don't Punt

Scripts should handle errors explicitly with helpful messages.

### Justify Constants

Document why parameters have specific values:
```python
REQUEST_TIMEOUT = 30  # HTTP requests typically complete within 30 seconds
MAX_RETRIES = 3       # Most intermittent failures resolve by second retry
```

### Utility Scripts Are Valuable

Pre-made scripts offer reliability, token savings, and consistency. Make clear whether the model should **execute** ("Run analyze_form.py") or **read** it ("See analyze_form.py for the algorithm").

### Design Output for Model Consumption

Script output is read by a model, not a human. Design accordingly:

- **Structured over decorated.** Prefer labeled sections or key-value pairs over human-friendly prose. No progress bars, spinners, or decorative formatting.
- **Concise over complete.** Truncate or paginate large outputs. A 10,000-line dump overwhelms the context window.
- **Actionable errors.** When a script fails, tell the model what to do next — not just what went wrong.

Bad:
```
ERROR: Connection refused on port 5432
```

Good:
```
ERROR: Connection refused on port 5432
FIX: Start PostgreSQL with `pg_ctl start -D /usr/local/var/postgres`
or verify the port with `lsof -i :5432`
```

---

## Workflows and Feedback Loops

### Workflows for Complex Tasks

Break complex operations into sequential steps with a trackable checklist:

```
Task Progress:
- [ ] Step 1: Analyze the form
- [ ] Step 2: Create field mapping
- [ ] Step 3: Validate mapping
- [ ] Step 4: Fill the form
- [ ] Step 5: Verify output
```

### Feedback Loops

The pattern "run validator → fix errors → repeat" greatly improves quality:

```
1. Make edits to document.xml
2. Validate: python scripts/validate.py unpacked_dir/
3. If validation fails → fix issues → validate again
4. Only proceed when validation passes
```

### Verifiable Intermediate Outputs

For complex open-ended tasks, use plan-validate-execute: analyze → create plan file → validate plan → execute → verify.

---

## Evaluation and Iteration

### Build Evaluations First

Create evaluations BEFORE extensive documentation:

1. Run the model on representative tasks without a skill
2. Document specific failures or missing context
3. Build 3+ test scenarios
4. Write minimal instructions to address gaps
5. Iterate: evaluate, compare, refine

### Iterative Development with Two Instances

Work with "Claude A" to create a skill, test with "Claude B":
1. Complete a task without a skill, noting what context you provide
2. Ask Claude A to capture the pattern
3. Review for conciseness
4. Test with Claude B on similar tasks
5. Observe, bring insights back to Claude A, repeat

### Observe Navigation Patterns

Watch for unexpected exploration paths, missed connections, overreliance on certain sections, and ignored content.

### Test Across Models

Skills act as additions to models. What works for Opus/o3 might need more detail for Haiku/mini. Test with all models you plan to use.

## Counter-example convention for prose YAML fences

Skills sometimes ship intentional examples of YAML that the in-repo parser would reject — counter-examples illustrating divergences. The doc-snippet validator (`validate_skill --check-prose-yaml`) treats every ```yaml` fence in scope as live input by default; counter-examples need an opt-out.

**Opt-out marker.** The HTML comment `<!-- yaml-ignore -->` on the line immediately above the fence-open line — with no blank line between — opts the fence out of validation. The marker is reviewer-visible by design: a waiver, not silent acceptance.

**Fence shape rules.** The validator only sees fences that match all of:

- Three backticks (no more, no fewer); tilde fences are invisible.
- Lowercase literal `yaml` immediately after the backticks (no whitespace between).
- The opening backticks at byte offset 0 (column 0); indented fences are invisible.
- A column-0 ` ``` ` close marker before end of file.

**Avoid column-0 ` ``` ` inside a YAML block scalar.** The markdown extractor terminates the fence at the first column-0 ` ``` ` line per CommonMark, even when that line is inside a literal-block content region. If a YAML example needs a literal triple-backtick, indent the line so it is no longer at column 0.

**Commented-out fences.** HTML comments are not parsed by the extractor — a column-0 ```yaml` line inside an `<!-- ... -->` block is still recognised. Wrap it in `<!-- yaml-ignore -->` (one fence per marker) or indent the fence to hide it.

