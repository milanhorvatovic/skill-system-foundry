# Setting Up Symlink-Based Pointers

Symlinks are the default deployment-pointer mechanism. Platform compatibility and tool support details are documented in the deployment capability.

## 1. Determine Scope

**Default: same canonical path for all tools.** Skills authored under `.agents/skills/<name>` are reused by every tool that supports `.agents/` natively, and the symlinks from tool-specific paths (`.claude/skills/`, `.cursor/skills/`, `.kiro/skills/`) all point to the same canonical location. When a tool requires content tailored to that tool, do **not** create a tool-specific canonical path — fall back to a wrapper file in that tool's discovery path instead (see [deployment/capability.md](../capability.md) for the wrapper-file fallback rule).

## 2. Capture the Canonical Path

Ask once:

```
Where is the canonical skill located?
> .agents/skills/my-skill
```

If a tool requires tool-specific content in its discovery path, stop the symlink workflow for that tool and create a wrapper file instead (per the wrapper-file fallback rule in [deployment/capability.md](../capability.md)).

## 3. Create Symlinks

Relative-path rule: compute the target from the **directory that contains the link**. For `.claude/skills/my-skill` use `../../.agents/...`; for `.claude/skills/my-skill/SKILL.md` use `../../../.agents/...`. Never use absolute paths — they break on every other clone ([anti-patterns.md#absolute-symlink-paths](../../../references/anti-patterns.md#absolute-symlink-paths)).

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
