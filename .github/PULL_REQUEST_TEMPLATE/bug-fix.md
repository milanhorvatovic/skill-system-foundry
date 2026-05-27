<!--
House rules mirror CONTRIBUTING.md "Pull Request Process". When editing,
update all 4 PR templates + CONTRIBUTING.md together.

When writing this body:
- Cite files by symbol name or heading, not file:line — line numbers rot.
- Don't reference PR sequence ("PR-1", "post-PR-3") or commit counts ("28 commits ahead").
- Don't name a specific future release version — describe the bump instead.
- One paragraph = one logical line; do not hard-wrap for visual width.
-->

Closes #

## Summary

The root cause and the fix. State the bug in one sentence, then the underlying reason it happened, then the change that resolves it.

## Test plan

- [ ] Regression-test pin added (cite the test file + test name)
- [ ] Reproduced the bug before the fix; verified the fix resolves it
- [ ] `(cd skill-system-foundry && python scripts/validate_skill.py . --allow-nested-references --foundry-self)` — green
- [ ] `(cd skill-system-foundry && python scripts/audit_skill_system.py .)` — no new findings beyond the expected baseline
- [ ] CI green on ubuntu + windows

---

Apply exactly one `release: major | minor | patch | skip` label via the sidebar (required check; PR cannot merge without it). See CONTRIBUTING.md for the bump policy.
