---
allowed-tools: Bash Read Write Edit
---

# Skill Design

Create skills, capabilities, roles, and manifests. Decide architecture (standalone vs router), write effective descriptions, and understand directory conventions.

## Creating a New Skill

1. **Determine scope** — Default to standalone. Only use the router pattern when 3+ distinct operations with different trigger contexts justify it. Capabilities are optional and should be added incrementally, not upfront.

2. **Scaffold** (optional):
   ```bash
   python scripts/scaffold.py skill <skill-name> [--router] [--with-references] [--with-scripts] [--with-assets]
   ```
   By default only `SKILL.md` is created (plus `capabilities/` for routers). Use the `--with-*` flags to include optional directories upfront.

3. **Or create manually** using templates from `assets/`:
   - Standalone: copy [skill-standalone.md](assets/skill-standalone.md) → `skills/<name>/SKILL.md`
   - Router: copy [skill-router.md](assets/skill-router.md) → `skills/<name>/SKILL.md`

4. **Write the SKILL.md** following [authoring-principles.md](references/authoring-principles.md):
   - Description max 1024 chars, with triggers (third-person voice recommended)
   - Body recommended max 500 lines, only context the model doesn't already have
   - `name` matches directory, lowercase + hyphens, max 64 chars

5. **Validate:**
   ```bash
   python scripts/validate_skill.py skills/<skill-name>
   ```

6. **Update manifest.yaml.**

## Creating a New Role

1. **Verify it composes 2+ skills or capabilities.**

2. **Scaffold** (optional):
   ```bash
   python scripts/scaffold.py role <role-group> <role-name>
   ```

3. **Or copy** [role.md](assets/role.md) → `roles/<group>/<name>.md`

4. **Define the role contract explicitly.** Include:
   - Responsibility, authority, and constraints (captured explicitly through the `Responsibilities`, `Allowed`, and `Forbidden` sections)
   - Responsibilities (what the role owns)
   - Allowed actions (authority)
   - Forbidden actions (hard boundaries)
   - Handoff rules (when and how work transfers)
   - Workflow sequence (task steps/checklist)

5. **Map skill dependencies.** Verify paths exist. In role files, use system-root-relative paths (for example, `skills/<domain>/SKILL.md`).

6. **Add to router** if accessed through a domain skill.

7. **Update manifest.yaml.**

## Creating an Orchestration Skill

A skill can serve as the orchestration entry point. Two forms exist — choose based on needs. See [architecture-patterns.md](references/architecture-patterns.md#orchestration-skills) for the full decision checklist.

1. **Choose the form:**
   - **Coordination-only (path 1):** A lean standalone skill that sequences roles across domains. No domain logic.
   - **Self-contained (path 2):** A domain skill (standalone or router) that loads one or more roles for interactive workflow logic.

**For coordination-only (path 1):**

2. **Scaffold** a standalone skill:
   ```bash
   python scripts/scaffold.py skill <orchestration-name>
   ```

3. **Write the SKILL.md.** The description should identify it as an orchestration entry point with appropriate trigger phrases. The body defines the workflow sequence and references roles by system-root-relative path (e.g., `roles/<group>/<name>.md`).

4. **Reference roles, not domain skills.** The coordination skill selects and sequences roles. Domain logic belongs in the roles and their skills.

**For self-contained (path 2):**

2. **Start with the domain skill.** Use an existing standalone or router skill, or create one.

3. **Create a role** for the workflow logic. The role provides responsibility, authority, and constraints, plus sequencing and interaction patterns. It references the skill's capabilities by system-root-relative path.

4. **Reference the role from the skill's SKILL.md.** The skill loads the role to gain interactive workflow orchestration.

**For both forms:**

5. **Validate the skill:**
   ```bash
   python scripts/validate_skill.py skills/<skill-name>
   ```

6. **Run the skill system audit** to check dependency direction:
   ```bash
   python scripts/audit_skill_system.py /path/to/system --allow-orchestration
   ```
   Note: `audit_skill_system.py` (not `validate_skill.py`) checks dependency direction. Use `--allow-orchestration` to downgrade skill→role references from FAIL to WARN — this is expected for orchestration skills (both paths).

7. **Update manifest.yaml.** Include role dependencies under the skill entry.

## Adding a Capability to an Existing Router

Only add a capability when the integrator explicitly requests it or when the domain clearly warrants a new distinct operation. Do not create capabilities speculatively.

1. Create `skills/<domain>/capabilities/<new-cap>/capability.md`.
2. Add row to router's Capabilities table.
3. Update router's `description` if new triggers needed (max 1024 chars).
4. Update manifest.yaml.

## Key Resources

**Templates** — copy and fill in when creating components:
- [skill-standalone.md](assets/skill-standalone.md) — Standalone skill template
- [skill-router.md](assets/skill-router.md) — Router skill template
- [capability.md](assets/capability.md) — Capability template
- [role.md](assets/role.md) — Role template
- [manifest.yaml](assets/manifest.yaml) — Manifest schema template

**References** — read when you need guidance:
- [authoring-principles.md](references/authoring-principles.md) — Shared skill authoring principles
- [architecture-patterns.md](references/architecture-patterns.md) — Standalone vs router decisions
- [agentskills-spec.md](references/agentskills-spec.md) — Specification compliance
- [directory-structure.md](references/directory-structure.md) — Full directory layout and conventions
- [anti-patterns.md](references/anti-patterns.md) — Common mistakes and how to avoid them

**Scripts** — run for scaffolding and validation:
- [scaffold.py](scripts/scaffold.py) — Scaffold new skills or roles from templates
- [validation.py](scripts/lib/validation.py) — Shared name validation logic
- [manifest.py](scripts/lib/manifest.py) — Manifest parsing and validation
