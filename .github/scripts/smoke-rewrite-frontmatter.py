#!/usr/bin/env python3
"""Rewrite a scaffolded SKILL.md frontmatter to a bundle-able stub.

The bundle-extract-smoke CI job scaffolds a synthetic skill via
``scaffold.py`` and then needs a frontmatter shape that fits the
Claude.ai 200-char description cap so ``bundle.py --target claude``
can package it.  The scaffolded SKILL.md ships with a folded-scalar
description that exceeds the cap, so an in-place line replacement
would leave the YAML malformed.

Replacing the whole frontmatter wholesale is the right approach.
Doing it in a multi-line ``run:`` step is the wrong approach: shell
escaping for ``\\"\\"`` (the YAML empty-string literal) and embedded
``\\n`` differs between bash on ubuntu and PowerShell on
windows-latest, so a quoted one-liner is brittle and hard to verify
without running the workflow on both runners.

This helper does the rewrite in plain Python with no shell-escape
surface, and pins the frontmatter fields the validator surface
actually exercises:

* ``name`` and ``description`` — spec-required.
* ``allowed-tools: ""`` — documented opt-out the tool-coherence rule
  keys off.
* ``compatibility`` — exercises the optional-string check.
* ``license`` — exercises the SPDX recognition.
* ``metadata.version`` — exercises semver validation.

``metadata.author`` is intentionally omitted; the validator surface
it covers is a string-length check the other fields already
exercise.

Usage::

    python .github/scripts/smoke-rewrite-frontmatter.py <path-to-SKILL.md>
"""

import argparse
import os
import sys


_STUB_FRONTMATTER = (
    "---\n"
    "name: demo\n"
    "description: triggers when the demo runs\n"
    "allowed-tools: \"\"\n"
    "compatibility: smoke test\n"
    "license: MIT\n"
    "metadata:\n"
    "  version: 1.0.0\n"
    "---\n"
)


def rewrite(skill_md_path: str) -> int:
    """Replace *skill_md_path*'s frontmatter with the smoke-test stub.

    Returns 0 on success, 1 if the file is missing or unreadable.
    """
    if not os.path.isfile(skill_md_path):
        print(
            f"FAIL: '{skill_md_path}' is not a file",
            file=sys.stderr,
        )
        return 1
    try:
        with open(skill_md_path, "r", encoding="utf-8") as fh:
            src = fh.read()
    except OSError as exc:
        print(
            f"FAIL: cannot read '{skill_md_path}': {exc}",
            file=sys.stderr,
        )
        return 1
    except UnicodeDecodeError as exc:
        # ``open(..., encoding="utf-8")`` raises this when the body
        # contains non-UTF-8 bytes.  Surfacing it as the documented
        # exit-1 ("unreadable file") keeps the smoke job's failure
        # mode predictable instead of crashing with a traceback that
        # the caller's status handling does not expect.
        print(
            f"FAIL: cannot decode '{skill_md_path}' as UTF-8: {exc}",
            file=sys.stderr,
        )
        return 1
    # Strip the existing frontmatter block so the body alone remains.
    # The split must be LINE-AWARE: a substring search like
    # ``src.split("---", 2)`` would treat any ``---`` appearing
    # inside a folded scalar or quoted value as the closing fence,
    # potentially rewriting the wrong slice of the file.  Walk the
    # opening ``---`` line, then look for the next line whose
    # stripped content is exactly ``---`` (the YAML frontmatter
    # closer must appear on its own line per the spec).
    #
    # Refuse to silently rewrite a file that lacks a parseable
    # frontmatter block (no opener, or no closer).  The smoke job's
    # purpose is to verify the scaffold pipeline; if ``scaffold.py``
    # regresses to omit or corrupt the SKILL.md frontmatter, this
    # helper is the right place to FAIL — falling through to a
    # ``body = src`` / ``body = ""`` path would silently mask the
    # regression by writing a valid stub on top of garbage.
    lines = src.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        print(
            f"FAIL: '{skill_md_path}' has no frontmatter opener "
            "('---' on line 1) — refusing to rewrite a file the "
            "scaffold pipeline should have produced with a proper "
            "frontmatter block",
            file=sys.stderr,
        )
        return 1
    closer_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].rstrip("\r\n") == "---":
            closer_idx = idx
            break
    if closer_idx is None:
        print(
            f"FAIL: '{skill_md_path}' has an unclosed frontmatter "
            "block (no second '---' delimiter line found) — "
            "refusing to rewrite a file the scaffold pipeline "
            "should have produced with a complete frontmatter block",
            file=sys.stderr,
        )
        return 1
    body = "".join(lines[closer_idx + 1:])
    # Strip leading newlines/CR only — not arbitrary whitespace.
    # ``body.lstrip()`` would also remove leading spaces/tabs, which
    # is meaningful in markdown (e.g. an indented code block on
    # line 1 right after the frontmatter).  The stub already ends
    # in ``\n`` so a single blank line between stub and body is
    # both intended and idempotent.
    new_content = _STUB_FRONTMATTER + body.lstrip("\r\n")
    try:
        with open(skill_md_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_content)
    except OSError as exc:
        print(
            f"FAIL: cannot write '{skill_md_path}': {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite a scaffolded SKILL.md frontmatter to a stub the "
            "bundle pipeline can package under --target claude."
        ),
    )
    parser.add_argument(
        "skill_md",
        help="Path to the SKILL.md file to rewrite.",
    )
    args = parser.parse_args(argv)
    return rewrite(args.skill_md)


if __name__ == "__main__":
    sys.exit(main())
