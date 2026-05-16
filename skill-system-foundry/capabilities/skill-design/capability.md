---
allowed-tools: Bash Read Write Edit
---

# Skill Design

Create skills, capabilities, roles, and manifests. Decide architecture (standalone vs router), write effective descriptions, and understand directory conventions.

## Creating a New Skill

1. **Determine scope** — Default to standalone. Only use the router pattern when 3+ distinct operations with different trigger contexts justify it. Capabilities are optional and should be added incrementally, not upfront ([anti-patterns.md#premature-capability-creation](../../references/anti-patterns.md#premature-capability-creation)).

2. **Scaffold** (optional):
   ```bash
   python scripts/scaffold.py skill <skill-name> [--router] [--with-references] [--with-scripts] [--with-assets]
   ```
   By default only `SKILL.md` is created (plus `capabilities/` for routers). Use the `--with-*` flags to include optional directories upfront.

3. **Or create manually** using templates from `assets/`:
   - Standalone: copy [skill-standalone.md](../../assets/skill-standalone.md) → `skills/<name>/SKILL.md`
   - Router: copy [skill-router.md](../../assets/skill-router.md) → `skills/<name>/SKILL.md`

4. **Write the SKILL.md** following [authoring-principles.md](../../references/authoring-principles.md):
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

3. **Or copy** [role.md](../../assets/role.md) → `roles/<group>/<name>.md`

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

A skill can serve as the orchestration entry point. Two forms exist — choose based on needs. See [architecture-patterns.md](../../references/architecture-patterns.md#orchestration-skills) for the full decision checklist.

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

Only add a capability when the integrator explicitly requests it or when the domain clearly warrants a new distinct operation. Do not create capabilities speculatively ([anti-patterns.md#premature-capability-creation](../../references/anti-patterns.md#premature-capability-creation)).

1. Create `skills/<domain>/capabilities/<new-cap>/capability.md` (copy from the [capability template](../../assets/capability.md)).
2. Add row to router's Capabilities table. Each capability trigger must be mutually exclusive and action-oriented — if you cannot unambiguously route a request, tighten the wording before merging ([anti-patterns.md#vague-router-descriptions](../../references/anti-patterns.md#vague-router-descriptions)).
3. Update router's `description` if new triggers needed (max 1024 chars).
4. Update manifest.yaml.

## Gotchas

- **Style-only role definitions.** A role without explicit responsibility, authority, and constraints (plus handoff rules) is just a tone preset. See [anti-patterns.md#style-only-role-definitions](../../references/anti-patterns.md#style-only-role-definitions).
- **1:1 role-to-capability mapping.** Roles compose 2+ skills or capabilities. Wrapping a single capability in a role adds overhead without value. See [anti-patterns.md#11-role-to-capability-mapping](../../references/anti-patterns.md#11-role-to-capability-mapping).
- **Vague router descriptions.** Capability triggers in the router table must be mutually exclusive and action-oriented. If you can't unambiguously route a request, tighten the wording. See [anti-patterns.md#vague-router-descriptions](../../references/anti-patterns.md#vague-router-descriptions).

## Key Resources

**Templates** — copy when creating components (the skill, role, and capability templates are linked inline at the body step where they apply; the manifest template is indexed here only since `manifest.yaml` is referenced across multiple body steps without a single canonical insertion point):
- [skill-standalone.md](../../assets/skill-standalone.md), [skill-router.md](../../assets/skill-router.md), [capability.md](../../assets/capability.md), [role.md](../../assets/role.md), [manifest.yaml](../../assets/manifest.yaml).

**References** — load by trigger:
- [authoring-principles.md](../../references/authoring-principles.md) — read when writing or reviewing a description, picking degrees-of-freedom, or structuring progressive disclosure.
- [architecture-patterns.md](../../references/architecture-patterns.md) — read when deciding standalone vs router, or choosing between coordination-only and self-contained orchestration paths.
- [agentskills-spec.md](../../references/agentskills-spec.md) — read when a frontmatter field, naming rule, or file-reference convention is in question.
- [directory-structure.md](../../references/directory-structure.md) — read when deciding where to place a new file or what the on-disk layout should look like.
- [anti-patterns.md](../../references/anti-patterns.md) — read before scaffolding capabilities, defining a role, or extracting shared resources; the foot-guns concentrate there.

**Scripts** — run by trigger:
- [scaffold.py](../../scripts/scaffold.py) — run when starting a new skill, capability, or role from a template.
