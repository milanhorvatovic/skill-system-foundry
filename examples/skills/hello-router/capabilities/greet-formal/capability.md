---
description: >
  Produces a formal, business-appropriate greeting line for a named
  recipient. Activates when the parent router selects the formal tone.
metadata:
  version: "1.0.0"
---
# Greet Formal

## Purpose

Renders one formal greeting line for a single recipient. Loaded on demand
from `hello-router` when the request asks for a formal, business, or
honorific tone.

## Instructions

1. Read the recipient name from the request. Preserve any honorific
   provided ("Dr.", "Prof.", "Ms.") verbatim.
2. Render the greeting using the format `Good day, <name>.` followed by no
   trailing characters.
3. Optionally print the rendered line through the harness Bash tool when
   the request asks for an interactive demonstration. The fence below
   illustrates the canonical invocation:

   ```bash
   printf 'Good day, %s.\n' "$RECIPIENT"
   ```

4. Stop after a single line. The capability never loops or chains.

## Output Format

One plain-text line. No markdown, no fences in the final answer, no
trailing whitespace.
