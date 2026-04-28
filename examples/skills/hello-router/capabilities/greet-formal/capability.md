---
description: >
  Produces a formal, business-appropriate greeting line for a named
  recipient. Activates when the request asks for a formal,
  business-appropriate, or honorific greeting.
metadata:
  version: "1.0.0"
---
# Greet Formal

## Purpose

Renders one formal greeting line for a single recipient. Use when the request asks for a formal, business-appropriate, or honorific greeting.

## Instructions

1. Read the recipient name from the request. Preserve any honorific provided ("Dr.", "Prof.", "Ms.") verbatim.
2. Render the greeting using the format `Good day, <name>.`. Nothing follows the period on the same line.
3. Optionally print the rendered line through the harness Bash tool when the request asks for an interactive demonstration — see [Optional Shell Demonstration](#optional-shell-demonstration) below for the canonical invocation.
4. Stop after a single line. The capability never loops or chains.

## Optional Shell Demonstration

The fence below shows the canonical Bash invocation. `printf` terminates the line with a single newline, which is the line terminator the shell needs and is not part of the greeting itself. This fence is at column 0 so the foundry's tool-coherence rule recognises it and matches it against the parent skill's `allowed-tools: Bash` declaration:

```bash
printf 'Good day, %s.\n' "$RECIPIENT"
```

## Output Format

One plain-text line. No markdown, no fences in the final answer, no trailing whitespace beyond the single line terminator.
