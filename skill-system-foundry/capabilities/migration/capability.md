# Migration

Convert existing flat skill structures into the router+capabilities pattern. Consolidates duplicate logic, reduces discovery tokens, and establishes proper layering.

## Migrating Flat Skills to Router Pattern

1. **Audit existing skills** — list triggers and references.

2. **Scaffold router:**
   ```bash
   python scripts/scaffold.py skill <domain> --router
   ```

3. **Write the router** with mutually exclusive trigger descriptions.

4. **Move skills to capabilities** under `capabilities/<name>/`. Rename the entry point from `SKILL.md` to `capability.md`. Frontmatter is optional for capabilities — remove it or keep it for documentation, but it will not be used for discovery.

5. **Extract shared resources** to `shared/`. Each must be used by 2+. This is the standard layout for router skills (see the [router template](../../assets/skill-router.md)). Note: the foundry itself places shared resources directly at the skill root (`references/`, `assets/`, `scripts/`) rather than under `shared/` — this is an intentional exception because the foundry's scripts depend on fixed relative paths from the skill root.

6. **Audit:**
   ```bash
   python scripts/audit_skill_system.py /path/to/system
   ```

7. **Update manifest.yaml.**

## Key Resources

**References:**
- [architecture-patterns.md](../../references/architecture-patterns.md) — Standalone vs router decision checklist
- [anti-patterns.md](../../references/anti-patterns.md) — Common migration mistakes

**Scripts:**
- [scaffold.py](../../scripts/scaffold.py) — Scaffold router from template
- [audit_skill_system.py](../../scripts/audit_skill_system.py) — Verify structure after migration
