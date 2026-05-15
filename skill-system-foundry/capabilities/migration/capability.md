---
allowed-tools: Bash Read Write Edit
---

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

5. **Extract shared resources** to `shared/`. Each must be used by 2+ capabilities — premature `shared/` extraction is a common migration foot-gun ([anti-patterns.md#orphaned-shared-resources](../../references/anti-patterns.md)). This is the standard layout for router skills (see the [router template](../../assets/skill-router.md)). Note: the foundry itself places shared resources directly at the skill root (`references/`, `assets/`, `scripts/`) rather than under `shared/` — this is an intentional exception because the foundry's scripts depend on fixed relative paths from the skill root.

6. **Audit:**
   ```bash
   python scripts/audit_skill_system.py /path/to/system
   ```

7. **Update manifest.yaml.**

## Gotchas

- **Premature `shared/` extraction.** A `shared/` resource must be used by 2+ capabilities. Extracting on first use bloats the structure and creates orphans. See [anti-patterns.md#orphaned-shared-resources](../../references/anti-patterns.md). Inline callout is at step 5 above.
- **Inlining rare, extracting common.** The router stays lean if rare operations live in capabilities and frequently used operations stay in the router body. Reverse the rule and the router bloats with seldom-used logic. See [anti-patterns.md#inlining-rare-extracting-common](../../references/anti-patterns.md).
- **1:1 role-to-capability mapping during migration.** When promoting a flat skill to a router, do not auto-create one role per capability. Roles compose 2+ — if there is no role to add, do not add one. See [anti-patterns.md#11-role-to-capability-mapping](../../references/anti-patterns.md).

## Key Resources

**References** — load by trigger:
- [architecture-patterns.md](../../references/architecture-patterns.md) — read at step 1 (audit existing skills) to confirm the domain actually warrants router migration, not just reorganization.
- [anti-patterns.md](../../references/anti-patterns.md) — read at step 5 (extracting shared resources) before creating any `shared/` entry; the foot-guns "Premature Capability Creation", "Inlining Rare, Extracting Common", and "Orphaned Shared Resources" all apply here.

**Scripts** — run by trigger:
- [scaffold.py](../../scripts/scaffold.py) — run at step 2 to scaffold the router skeleton.
- [audit_skill_system.py](../../scripts/audit_skill_system.py) — run at step 6 to verify dependency direction and capability isolation after migration.
