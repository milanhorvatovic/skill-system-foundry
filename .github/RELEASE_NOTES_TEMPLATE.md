<!--
Release notes template — paste into the body of the GitHub Release
when publishing a new version.  Replace every {VERSION} placeholder
with the release number (e.g., 1.2.0).  Links use ``blob/v{VERSION}``
so historical release pages keep pointing at the changelog and
README as they shipped, not at whatever is on ``main`` later.
-->

## What's changed

See the [changelog](https://github.com/milanhorvatovic/skill-system-foundry/blob/v{VERSION}/CHANGELOG.md) for the full list of changes in this release.

## Install

### npx skills

```bash
npx skills add milanhorvatovic/skill-system-foundry
```

Covers Claude Code, Codex, Cursor, Gemini CLI, Windsurf, Kiro, GitHub Copilot, Cline, OpenCode, and many more agents — see [skills.sh](https://skills.sh) for the full list.

### Claude Code plugin

```
/plugin marketplace add milanhorvatovic/skill-system-foundry
/plugin install skill-system-foundry@skill-system-foundry
```

### Gemini CLI

```bash
gemini skills link milanhorvatovic/skill-system-foundry
```

### Manual (any tool)

Download `skill-system-foundry-v{VERSION}.zip` from the assets below, extract into your project's skills directory (e.g., `.agents/skills/` or tool-specific equivalent), and see the main [README](https://github.com/milanhorvatovic/skill-system-foundry/blob/v{VERSION}/README.md#installation) for per-tool installation paths.

## Verify the bundle

Each release publishes a `skill-system-foundry-v{VERSION}.zip.sha256` file alongside the bundle. Download both into the same directory and verify:

```bash
# Linux
cd /path/to/downloads && sha256sum --check skill-system-foundry-v{VERSION}.zip.sha256

# macOS
cd /path/to/downloads && shasum -a 256 -c skill-system-foundry-v{VERSION}.zip.sha256
```

```powershell
# Windows (PowerShell)
$expected = ((Get-Content skill-system-foundry-v{VERSION}.zip.sha256 -Raw).Trim() -split '\s+' | Select-Object -First 1).ToLower()
$actual   = (Get-FileHash skill-system-foundry-v{VERSION}.zip -Algorithm SHA256).Hash.ToLower()
if ($expected -eq $actual) { "OK" } else { "MISMATCH"; exit 1 }
```
