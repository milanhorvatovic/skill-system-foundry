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

What documentation changed and why. State the user-visible improvement: a clarified rule, a corrected reference, a missing example, an out-of-date instruction.

## Test plan

- [ ] Rendered the changed file(s) and confirmed formatting
- [ ] Internal cross-references resolve (run `(cd skill-system-foundry && python scripts/validate_skill.py . --allow-nested-references --foundry-self)` if the change touches the meta-skill)
- [ ] Terminology consistent with the rest of the doc set — no new synonyms for existing concepts
- [ ] CI green

---

Apply exactly one `release: major | minor | patch | skip` label via the sidebar (required check; PR cannot merge without it). See CONTRIBUTING.md for the bump policy.
