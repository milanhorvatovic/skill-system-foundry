# Workflows

Step-by-step procedures for common skill system operations.

## Table of Contents

- [Creating a New Skill](#creating-a-new-skill)
- [Creating a New Role](#creating-a-new-role)
- [Creating an Orchestration Skill](#creating-an-orchestration-skill)
- [Migrating Flat Skills to Router Pattern](#migrating-flat-skills-to-router-pattern)
- [Adding a Capability to an Existing Router](#adding-a-capability-to-an-existing-router-optional)
- [Deploying Skills to Tools](#deploying-skills-to-tools)
- [Packaging a Skill as a Zip Bundle](#packaging-a-skill-as-a-zip-bundle)
- [Auditing System Consistency](#auditing-system-consistency)

---

## Creating a New Skill

1. **Determine scope** — Default to standalone. Only use the router pattern when 3+ distinct operations with different trigger contexts justify it. Capabilities are optional and should be added incrementally, not upfront.

2. **Scaffold** (optional):
   ```bash
   python scripts/scaffold.py skill <skill-name> [--router]
   ```

3. **Or create manually** using templates from `assets/`:
   - Standalone: copy `assets/skill-standalone.md` → `skills/<name>/SKILL.md`
   - Router: copy `assets/skill-router.md` → `skills/<name>/SKILL.md`

4. **Write the SKILL.md** following [authoring-principles.md](authoring-principles.md):
   - Third-person description, max 1024 chars, with triggers
   - Body recommended max 500 lines, only context the model doesn't already have
   - `name` matches directory, lowercase + hyphens, max 64 chars

5. **Validate:**
   ```bash
   python scripts/validate_skill.py skills/<skill-name>
   ```

6. **Update manifest.yaml.**

---

## Creating a New Role

1. **Verify it composes 2+ skills or capabilities.**

2. **Scaffold** (optional):
   ```bash
   python scripts/scaffold.py role <role-group> <role-name>
   ```

3. **Or copy** `assets/role.md` → `roles/<group>/<name>.md`

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

---

## Creating an Orchestration Skill

A skill can serve as the orchestration entry point. Two forms exist — choose based on needs. See [architecture-patterns.md](architecture-patterns.md#orchestration-skills) for the full decision checklist.

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

---

## Migrating Flat Skills to Router Pattern

1. **Audit existing skills** — list triggers and references.

2. **Scaffold router:**
   ```bash
   python scripts/scaffold.py skill <domain> --router
   ```

3. **Write the router** with mutually exclusive trigger descriptions.

4. **Move skills to capabilities** under `capabilities/<name>/`. Rename the entry point from `SKILL.md` to `capability.md`. Frontmatter is optional for capabilities — remove it or keep it for documentation, but it will not be used for discovery.

5. **Extract shared resources** to `shared/`. Each must be used by 2+.

6. **Audit:**
   ```bash
   python scripts/audit_skill_system.py /path/to/system
   ```

7. **Update manifest.yaml.**

---

## Adding a Capability to an Existing Router (Optional)

Only add a capability when the integrator explicitly requests it or when the domain clearly warrants a new distinct operation. Do not create capabilities speculatively.

1. Create `skills/<domain>/capabilities/<new-cap>/capability.md`.
2. Add row to router's Capabilities table.
3. Update router's `description` if new triggers needed (max 1024 chars).
4. Update manifest.yaml.

---

## Deploying Skills to Tools

Skills placed in `.agents/skills/` are natively discovered by most tools (Codex, Gemini CLI, Warp, OpenCode, Windsurf). For tools that do not scan this path, create a thin deployment pointer in the tool's discovery path. See [tool-integration.md](tool-integration.md) for per-tool details.

**Claude Code:** Create a pointer at `.claude/skills/<domain>/SKILL.md` that references the canonical source (registered skills only — not capability files). Or use the plugin marketplace.

**Claude.ai:** Bundle the skill as a zip using `bundle.py` (see [Packaging a Skill as a Zip Bundle](#packaging-a-skill-as-a-zip-bundle)), then upload via Settings > Features. Per-user. Description must be max 200 characters.

**Claude API:** Upload via `/v1/skills` endpoints. Workspace-wide.

**Codex:** `skill-installer install <skill-name>` or place in `~/.agents/skills/`. Natively scans `.agents/skills/`.

**Cursor:** If canonical content is in `.agents/skills/`, create a pointer at `.cursor/skills/<domain>/SKILL.md`. If canonical content is in `.claude/skills/`, Cursor discovers it natively.

**Windsurf:** Usually no deployment pointer needed when canonical skills live in `.agents/skills/`. Optionally add `.windsurf/rules/<domain>.md` for rules-based activation.

**Kiro:** Create a pointer at `.kiro/skills/<domain>/SKILL.md` that references the canonical source.

---

## Packaging a Skill as a Zip Bundle

Create a self-contained zip archive from a project-layout skill. The bundle resolves external references (roles, shared docs), copies them in, rewrites markdown paths, and validates the result.

Note: `bundle.py` enforces Claude.ai packaging constraints (including the 200-character description limit). This is target-specific and stricter than the Agent Skills specification limit of 1024 characters.

See [tool-integration.md](tool-integration.md#zip-bundle-packaging) for platform-specific constraints and [directory-structure.md](directory-structure.md#packaging-for-distribution) for the bundle structure.

### Prerequisites

- The skill must pass `validate_skill.py` (spec compliance)
- The skill's description must not exceed 200 characters (Claude.ai limit)
- All file references in the skill must resolve to existing files
- No external reference may point to another skill (cross-skill boundary violation)

### Usage

```bash
python scripts/bundle.py <skill-path> [--system-root <path>] [--output <path>]
```

- `--system-root`: Path to the skill system root (contains `skills/`, `roles/`). If omitted, inferred by walking up from the skill path.
- `--output`: Output path for the zip. Defaults to `<skill-name>.zip` in the current directory.

### Three-Phase Process

**Phase 1: Pre-validation**

1. Validates the skill against the Agent Skills specification
2. Checks description length against the 200-character Claude.ai limit
3. Scans skill files for external references (full rewrite support for `.md` files; best-effort detection in other text files)
4. Verifies all references resolve to existing files
5. Checks external files for cross-skill references (fails if found)
6. Traverses references transitively, including from non-markdown detected references (depth limit: 25, configurable in `configuration.yaml`)
7. Detects cycles between external documents
8. Emits warnings for non-markdown file references (detected but not rewritten automatically)

**Phase 2: Bundle creation**

1. Copies the skill directory as-is (excluding patterns defined in `scripts/lib/configuration.yaml` under `bundle.exclude_patterns`)
2. Copies all resolved external files into the bundle (deduplicated):
   - Role files → `roles/` (preserving group structure)
   - Other files → `references/`, `assets/`, or `scripts/` per conventions
3. Rewrites all markdown link and backtick references to use bundle-relative paths

**Phase 3: Post-validation**

1. Verifies all markdown references resolve within the bundle
2. Verifies exactly one SKILL.md exists (case-insensitive — Claude.ai constraint)
3. Creates the zip archive with the skill folder as the archive root

### Example

```bash
# Bundle a skill with an inferred system root
python scripts/bundle.py .agents/skills/project-mgmt --output dist/

# Bundle with an explicit system root
python scripts/bundle.py .agents/skills/project-mgmt --system-root .agents --output project-mgmt.zip
```

### Common Errors

| Error | Cause | Fix |
|---|---|---|
| Description exceeds 200 characters | Claude.ai limit is stricter than the 1024-char spec limit | Shorten the description |
| Broken reference | A markdown link points to a non-existent file | Fix the file path or remove the reference |
| Cross-skill reference | An external file references another skill | Remove the cross-skill reference or inline the content |
| Circular reference between external files | External docs reference each other in a cycle | Break the cycle — this is likely a structural bug |
| Multiple SKILL.md files | Case-insensitive scan found duplicates | Rename capability files to `capability.md` |

### Limitations

- Path rewriting is performed only in `.md` files. References in scripts (Python, shell, etc.) are detected and reported as warnings but not rewritten — update them manually.
- The bundler does not modify the original skill files. All changes are made in the bundle copy.

---

## Auditing System Consistency

Run the automated audit:
```bash
python scripts/audit_skill_system.py /path/to/system
```

> **Note:** Point this at the deployed system root — the directory containing a `skills/` subdirectory (e.g., `.agents/`). This is not the same as the distribution repository root. For single-skill validation, use `validate_skill.py` instead.

The script checks: spec compliance (frontmatter fields, naming, line counts), dependency direction (no upward references), nesting depth, shared resource usage, and manifest presence. Path validity and orphan detection require manual review (see checklist below).

> **Manual-only checks:** `audit_skill_system.py` does not currently enforce role composition (2+ skills/capabilities). Verify using the checklist below.

### Manual Checklist

**Spec Compliance:**
- [ ] Every registered skill has `name` + `description` in frontmatter
- [ ] All names match directories, lowercase + hyphens, max 64 chars
- [ ] All descriptions: third-person, max 1024 chars, with triggers
- [ ] No SKILL.md exceeds 500 lines
- [ ] File references: relative paths, one level deep

**Structure:**
- [ ] No capability registered in discovery layer
- [ ] Shared resources used by 2+ capabilities
- [ ] Max 2 levels deep (router → capability)
- [ ] Roles compose 2+ skills or capabilities
- [ ] No capability references siblings

**Dependencies:**
- [ ] Direction maintained (no upward references). Exception: orchestration skills (both paths) may reference roles intentionally.
- [ ] All role skill paths valid

**Manifest:**
- [ ] Complete and matches filesystem
- [ ] No orphaned files or phantom entries
