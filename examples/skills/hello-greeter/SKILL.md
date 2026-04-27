---
name: hello-greeter
description: >
  Greets a single recipient with a friendly welcome message rendered in a
  formal or casual tone. Activates whenever the conversation asks to say
  hello, welcome someone, or produce an opening greeting. Single-purpose,
  no branching, no shell access. Demonstrates the smallest valid standalone
  skill in the Skill System Foundry — minimal frontmatter, third-person
  description, body well under the recommended line cap.
metadata:
  version: "1.0.0"
---

# Hello Greeter

## Purpose

Produces a one-line welcome message addressed to a named recipient. The skill
exists as a reference example only — it shows the smallest valid shape a
standalone skill can take while still satisfying the Agent Skills
specification and foundry conventions.

## Instructions

1. Identify the recipient name from the request. Fall back to the literal
   word "friend" when no name is supplied.
2. Choose a tone token from the request: "formal" or "casual". Default to
   "casual" when nothing is specified.
3. Emit exactly one greeting line. For "casual" tone, the format is
   `Hello, <name>!`. For "formal" tone, the format is
   `Good day, <name>.`.
4. Stop after the single line. The skill performs no follow-up question and
   no continuation prompt.

## Examples

Input: `say hello to Sam`. Output: `Hello, Sam!`

Input: `formal greeting for Dr. Lee`. Output: `Good day, Dr. Lee.`

## Output Format

A single plain-text line containing the greeting. No markdown, no fences,
no trailing whitespace.
