# Reference Examples

This directory is a self-contained mini skill-system that demonstrates the three patterns the foundry supports: a standalone skill, a router skill with capabilities, and a role that composes both. The layout mirrors a deployed skill-system root (a top-level `skills/` and `roles/` directory), so the examples teach the same paths bundling and orchestration use in real projects.

The examples ship in the repository for onboarding only. The release zip published by `release.yml` packages just `skill-system-foundry/`, so nothing in `examples/` adds weight to the distributed bundle.

## Layout

```
examples/
├── skills/
│   ├── hello-greeter/                                    ← standalone
│   │   └── SKILL.md
│   └── hello-router/                                     ← router
│       ├── SKILL.md
│       └── capabilities/
│           ├── greet-formal/capability.md
│           └── greet-casual/capability.md
└── roles/
    └── hello-orchestrator.md                             ← role composing the two skills
```

## Examples

### Standalone skill — [`skills/hello-greeter/`](skills/hello-greeter/SKILL.md)

The smallest valid skill: a single `SKILL.md` with the required `name` and `description` frontmatter plus an optional `metadata` block, no `allowed-tools`, no shell fences, and no subdirectories. Read this first to see the floor of what counts as a skill in the Skill System Foundry.

### Router skill — [`skills/hello-router/`](skills/hello-router/SKILL.md)

A thin router entry point dispatching to two capabilities. Declares `allowed-tools: Bash` so a fenced `bash` example inside `capabilities/greet-formal/capability.md` stays coherent with the foundry's tool-coherence rule. Read this to see how a router table, capability layout, and `allowed-tools` declaration fit together.

### Role — [`roles/hello-orchestrator.md`](roles/hello-orchestrator.md)

A role contract composing the standalone and router skills above. Demonstrates the responsibility, allowed, forbidden, handoff, workflow, and "Skills Used" sections. Paths in the role's "Skills Used" table use the canonical `skills/<domain>/SKILL.md` form — the same form the audit and bundle tools recognise.

## Validation

Each skill example validates clean under the foundry's own validator:

```bash
python skill-system-foundry/scripts/validate_skill.py examples/skills/hello-greeter
python skill-system-foundry/scripts/validate_skill.py examples/skills/hello-router
```

CI runs these automatically. The role file is intentionally outside `validate_skill.py`'s scope today — a dedicated role validator is tracked as a separate follow-up.
