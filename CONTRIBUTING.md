# Contributing to Skill System Foundry

Thank you for your interest in contributing. This document explains how to get involved and what to expect.

## Ways to Contribute

**Report issues.** Found a bug in the validation scripts, an inaccuracy in the documentation, or a broken cross-reference? Open an issue in this repository's **Issues** tab with a clear description and steps to reproduce.

**Suggest improvements.** Have an idea for a new anti-pattern, a missing workflow, or better template defaults? Open an issue to discuss it before writing code.

**Submit pull requests.** Bug fixes, documentation improvements, and enhancements are welcome. For anything beyond a small fix, open an issue first to align on the approach.

**Share feedback.** Using Skill System Foundry in your project? Feedback on real-world usage helps prioritize improvements.

## Before You Start

1. Read the [README](README.md) to understand the architecture and design principles.
2. Read the [skill-level documentation](skill-system-foundry/README.md) for the meta-skill's structure and conventions.
3. Check existing issues in this repository to avoid duplicating work.

## Development Setup

**Requirements:** Python 3.12+ (standard library only — no external dependencies).

```bash
git clone https://github.com/milanhorvatovic/skill-system-foundry.git
cd skill-system-foundry
```

Verify the setup by running validation on the meta-skill itself:

```bash
cd skill-system-foundry
python3 scripts/validate_skill.py . --allow-nested-references
python3 scripts/audit_skill_system.py .
```

Both commands should complete successfully. In this distribution repository, `audit_skill_system.py .` currently emits one expected warning about a missing `skills/` directory.

## Project Structure

```
.
├── README.md                        ← Repository overview and architecture
├── CONTRIBUTING.md                  ← This file
├── LICENSE                          ← MIT license
└── skill-system-foundry/            ← The meta-skill
    ├── SKILL.md                     ← Router entry point
    ├── README.md                    ← Skill documentation
    ├── references/                  ← Guidance documents
    ├── assets/                      ← Templates for scaffolding
    └── scripts/                     ← Validation, scaffolding, and bundling tools
```

Changes typically fall into one of these areas:

| Area | Files | Validation |
|------|-------|------------|
| Documentation | `README.md`, `skill-system-foundry/README.md` | Manual review |
| References | `skill-system-foundry/references/*.md` | `validate_skill.py` |
| Templates | `skill-system-foundry/assets/*` | Manual review |
| Scripts | `skill-system-foundry/scripts/**/*.py` | `validate_skill.py`, `audit_skill_system.py`, `bundle.py` |
| Spec compliance | `skill-system-foundry/SKILL.md`, frontmatter | `validate_skill.py` |

## Guidelines

### Documentation

The project follows a **conciseness-first** principle. The model is already smart — only add context it does not already have.

- Challenge every paragraph: "Does the model really need this?"
- Use third person in skill descriptions ("Validates skills" not "I validate skills")
- Keep cross-references one level deep from `SKILL.md` (see [anti-patterns](skill-system-foundry/references/anti-patterns.md))
- Preserve the existing progressive disclosure structure (metadata → instructions → resources)

### Scripts

All scripts use the Python standard library only. Do not introduce external dependencies.

- Follow the existing code style (see existing files in `scripts/lib/` for patterns)
- Handle errors explicitly with helpful messages
- Document magic numbers with inline comments
- Keep shared logic in `scripts/lib/`; keep entry points in `scripts/`

### Templates

Templates in `assets/` contain placeholder values and inline comments. When modifying templates:

- Preserve placeholder markers so users know what to replace
- Keep templates minimal — provide a starting point, not a finished product
- Ensure templates remain valid against `validate_skill.py` after placeholder replacement

### Commit Messages

Use a short summary line describing **what** changed:

```
Update <component> and <component>
Add <new-thing> to <location>
Fix <issue> in <component>
```

## Pull Request Process

1. **Fork and branch.** Create a feature branch from `main`.

2. **Make your changes.** Keep commits focused — one logical change per commit.

3. **Validate.** Run these from the `skill-system-foundry/` directory:
   ```bash
   python3 scripts/validate_skill.py . --allow-nested-references
   python3 scripts/audit_skill_system.py .
   ```
   No failures are acceptable. In this distribution repository, one warning about a missing `skills/` directory is expected for `audit_skill_system.py .`; additional warnings should be documented.

4. **Self-review.** Check that your changes:
   - Follow the documentation and code guidelines above
   - Do not break existing cross-references between files
   - Maintain consistency with existing terminology and formatting

5. **Open the PR.** Include:
   - A clear description of what changed and why
   - Which area of the project is affected (documentation, scripts, templates, etc.)
   - How you validated the changes

6. **Respond to feedback.** PRs may require revisions before merging.

## What Happens Next

Maintainers review PRs on a best-effort basis. Smaller, focused PRs are reviewed faster than large ones. If your PR has not received feedback after a reasonable time, a polite ping in the PR comments is welcome.

## Scope

Skill System Foundry is intentionally focused on the **structural and architectural** concerns of organizing AI-agnostic skill systems. Contributions that stay within this scope are most likely to be accepted.

Out of scope:
- Domain-specific skill content (e.g., a complete project management skill)
- Tool-specific features that do not generalize across the supported tool landscape
- External dependencies for the validation scripts

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
