---
description: >
  Produces a casual, friendly greeting line for a named recipient.
  Activates when the request asks for a casual, friendly, or first-name
  greeting.
metadata:
  version: "1.0.0"
---
# Greet Casual

## Purpose

Renders one casual greeting line for a single recipient. Use when the request asks for a casual, friendly, or first-name greeting.

## Instructions

1. Read the recipient name from the request. Strip honorifics if present — casual greetings drop titles by convention.
2. Render the greeting using the format `Hello, <name>!` followed by no trailing characters.
3. Stop after a single line. The capability never loops or chains.

## Output Format

One plain-text line. No markdown, no fences, no trailing whitespace.
