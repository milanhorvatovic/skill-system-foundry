# Setting Up Symlink-Based Pointers

Use this workflow when the user chose symlinks as the deployment pointer mechanism. See [tool-integration.md](references/tool-integration.md#symlink-based-deployment-pointers) for platform compatibility and tool support details.

## 1. Determine Scope

```
Is the canonical skill path the same for all AI tool integrations,
or should each tool point to a different location?
> [ ] Same path for all tools
> [ ] Different path per tool
```

## 2. Prompt for Canonical Paths

- **Same path for all tools** — ask once:
  ```
  Where is the canonical skill located?
  > .agents/skills/my-skill
  ```

- **Different path per tool** — ask per tool being configured:
  ```
  Canonical path for Claude Code?
  > .agents/skills/my-skill

  Canonical path for Cursor?
  > .agents/skills/my-skill
  ```

## 3. Create Symlinks

Relative-path rule: compute the target from the **directory that contains the link**. For `.claude/skills/my-skill` use `../../.agents/...`; for `.claude/skills/my-skill/SKILL.md` use `../../../.agents/...`.

**Linux / macOS:**

```bash
# Example: Claude Code pointer to .agents/skills/my-skill
ln -s ../../.agents/skills/my-skill .claude/skills/my-skill

# Example: Kiro pointer to .agents/skills/my-skill
ln -s ../../.agents/skills/my-skill .kiro/skills/my-skill
```

**Windows (cmd) — requires Developer Mode or admin:**

```cmd
:: Example: Claude Code pointer to .agents\skills\my-skill
mklink /D .claude\skills\my-skill ..\..\.agents\skills\my-skill
```

**Windows (PowerShell) — requires Developer Mode or admin:**

```powershell
# Example: Claude Code pointer to .agents\skills\my-skill
New-Item -ItemType SymbolicLink -Path .claude\skills\my-skill -Target ..\..\.agents\skills\my-skill
```

## 4. Verify Symlink Resolution

```bash
# Linux / macOS — verify the symlink resolves
ls -la .claude/skills/my-skill
cat .claude/skills/my-skill/SKILL.md
```

```cmd
:: Windows (cmd) — verify the symlink resolves
dir .claude\skills /AL
type .claude\skills\my-skill\SKILL.md
```

```powershell
# Windows (PowerShell) — verify the symlink resolves
Get-Item .claude\skills\my-skill | Select-Object LinkType, Target
Get-Content .claude\skills\my-skill\SKILL.md
```

If the SKILL.md content matches the canonical source, the symlink is working correctly.
