# Hello Orchestrator

## Purpose

Coordinates a tone-aware welcome workflow that combines the standalone
`hello-greeter` skill (default greeting) with the `hello-router` skill
(tone-specific dispatch). Activates when a multi-step welcome is requested
and the caller wants the role to decide which skill to invoke based on the
tone signal in the request.

This role is a reference example. It shows the orchestration contract a
real role would publish — responsibility, allowed actions, forbidden
actions, handoff rules, and a Skills Used table — without owning any
domain logic of its own.

## Responsibilities

- Detect the tone signal in the request and decide between the standalone
  greeter and the tone-specific router.
- Emit exactly one greeting per request — never two greetings, never zero.
- Preserve recipient names verbatim, including honorifics, when passing
  them to the underlying skills.
- Surface a clear handoff message when the request falls outside the
  greeting domain.

## Allowed

- Loading the `hello-greeter` skill for the default casual greeting.
- Loading the `hello-router` skill and selecting one of its two registered
  capabilities (`greet-formal`, `greet-casual`).
- Reading the recipient name and tone fields from the incoming request.

## Forbidden

- Loading more than one greeting skill in a single turn.
- Inventing tone variants beyond `formal` and `casual`. Unknown tones
  trigger the handoff rule below.
- Holding state between turns. Each request is treated independently.
- Loading other roles. Roles never compose roles in this skill system.

## Handoff

- Tone is missing or unrecognized → fall back to `hello-greeter` with the
  default casual tone, and note the fallback in the response prefix.
- Request asks for multi-recipient or templated bulk greetings → return a
  short refusal pointing the caller at a future bulk-greeting skill.
- Request asks for anything other than a greeting → return control to the
  caller with an explicit "out of scope" message.

## Workflow

Task Progress:
- [ ] Step 1: Parse the recipient name and tone from the request.
- [ ] Step 2: If tone is `formal` or `casual`, load `hello-router` and
      dispatch to the matching capability.
- [ ] Step 3: Otherwise, load `hello-greeter` and emit the default
      casual greeting.
- [ ] Step 4: Return the single greeting line and stop.

## Skills Used

| Skill / Capability | Purpose in Workflow |
|---|---|
| skills/hello-greeter/SKILL.md | Default casual greeting when no tone is specified |
| skills/hello-router/SKILL.md | Tone-aware dispatch entry point |
| skills/hello-router/capabilities/greet-formal/capability.md | Formal tone rendering loaded by the router |

<!-- Paths in this table are relative to the example mini system root
     (the examples/ directory containing skills/ and roles/), not relative
     to this role file's location. -->

## Interaction Pattern

The role decides autonomously between the standalone and router paths
based on the tone signal. It asks no clarifying questions for missing
tone — it falls back to the default greeting and notes the fallback in
the prefix. It escalates to the caller only when the request is outside
the greeting domain.
