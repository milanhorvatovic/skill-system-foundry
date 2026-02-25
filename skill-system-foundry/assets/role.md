# <Role Name>

## Purpose

<What this role is accountable for and when to activate it.>
<!-- This role contract should explicitly define responsibility, authority,
     and constraints through the sections below. -->

## Responsibilities

- <What this role must accomplish>
- <What quality bar it enforces>
- <What outcomes it owns>

## Allowed

- <Actions this role is explicitly allowed to take>
- <Tools or files this role can use>

## Forbidden

- <Actions this role must never take>
- <Decisions this role cannot make alone>

## Handoff

- <Condition> → <Target role/owner> with <required context>
- <Escalation condition> → <Target role/owner>

## Workflow

<Step-by-step orchestration sequence. For complex workflows, include a checklist the model can track progress against.>

Task Progress:
- [ ] Step 1: <step description>
- [ ] Step 2: <step description>
- [ ] Step 3: <step description>
- [ ] Step 4: <step description>

## Skills Used

| Skill / Capability | Purpose in Workflow |
|---|---|
| skills/<domain>/SKILL.md | <How this skill is used> |
| skills/<domain>/capabilities/<cap>/SKILL.md | <How this capability is used> |

<!-- Paths in this table are relative to the system root (the directory
     containing skills/ and roles/), not relative to this role
     file's location. -->
<!-- A role may be loaded by a skill (see references/architecture-patterns.md
     § Orchestration Skills, both paths). The role still documents which
     skills/capabilities it uses regardless of the loading direction. -->

## Interaction Pattern

<How the role interacts with the user — questions it asks, decisions it makes autonomously, when it escalates to the user.>

<!--
Role checklist:
- Must compose 2+ skills or capabilities, or add meaningful interaction logic
- Must not be a thin passthrough to a single capability
- Must express responsibility, authority, and constraints explicitly
- Must define responsibilities, allowed actions, forbidden actions, and handoff rules
- References skills and capabilities by system-root-relative path
- May be loaded by a skill for workflow orchestration (both paths)
- Is a behavioral contract, not a subagent definition
-->
