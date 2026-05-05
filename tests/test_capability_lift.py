"""End-to-end check of the liftability invariant.

The path-resolution rule (``skill-system-foundry/references/path-resolution.md``)
states that a capability sub-graph must be **mechanically liftable** to a
standalone skill: only the capability's external (``../../...``) references
need rewriting, every internal edge stays as-is, and the result validates
clean.

This module exercises the invariant with a synthetic fixture that mirrors
the meta-skill's structure — capability.md, capability-local references,
and external references into the shared skill root.  The test:

1. Builds a parent skill with one capability.
2. Lifts the capability by copying its directory to a fresh skill root,
   inlining each external target into a local ``references/`` or
   ``assets/`` directory, and rewriting every ``../../...`` link to its
   inline destination.  No semantic edits.
3. Promotes ``capability.md`` to ``SKILL.md`` (frontmatter rename only).
4. Runs ``validate_skill`` on the lifted skill and asserts no FAIL or WARN.

If a future change introduces a reference that the rewriter cannot
mechanically translate, this test breaks before the invariant rots.
"""

import os
import re
import shutil
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_REPO_ROOT, "skill-system-foundry", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from validate_skill import validate_skill  # noqa: E402

from helpers import write_text  # noqa: E402


_EXTERNAL_LINK_RE = re.compile(r"\(((?:\.\./)+(?:references|assets|scripts)/[^)]+)\)")
_EXTERNAL_BACKTICK_RE = re.compile(r"`((?:\.\./)+(?:references|assets|scripts)/[^`]+)`")


def _mechanical_lift(parent_skill: str, capability_name: str, dest: str) -> None:
    """Lift *capability_name* from *parent_skill* into a standalone skill at *dest*.

    Pure mechanical transformation: copies the capability directory,
    inlines every external target, rewrites ``../../...`` links to the
    inlined location, renames ``capability.md`` to ``SKILL.md``, and
    swaps the frontmatter to satisfy the standalone-skill spec.  No
    semantic edits; no human judgment required.  This is the exact
    operation a future ``lift`` tool would perform.
    """
    cap_src = os.path.join(parent_skill, "capabilities", capability_name)
    shutil.copytree(cap_src, dest)

    for dirpath, _dirs, names in os.walk(dest):
        for name in names:
            if not name.endswith(".md"):
                continue
            md_path = os.path.join(dirpath, name)
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Find every external reference, inline its target, and
            # rewrite the link to point at the inlined location.
            def _inline_link(m: re.Match, *, _is_md: bool) -> str:
                ext_path = m.group(1)
                # Strip leading ../ segments to recover skill-root form.
                segs = ext_path.split("/")
                clean = "/".join(s for s in segs if s != "..")
                src = os.path.normpath(
                    os.path.join(parent_skill, *clean.split("/"))
                )
                if not os.path.isfile(src):
                    return m.group(0)  # leave broken refs alone
                # Inline at <dest>/<clean>.  Local form is the same path
                # relative to the lifted skill root.
                inline_dst = os.path.join(dest, *clean.split("/"))
                os.makedirs(os.path.dirname(inline_dst), exist_ok=True)
                if not os.path.exists(inline_dst):
                    shutil.copy2(src, inline_dst)
                # Rewrite link target to skill-root form, then to file-relative
                # form for this source file.
                rel_to_inline = os.path.relpath(
                    inline_dst, os.path.dirname(md_path)
                ).replace(os.sep, "/")
                if _is_md:
                    return f"({rel_to_inline})"
                return f"`{rel_to_inline}`"

            content = _EXTERNAL_LINK_RE.sub(
                lambda m: _inline_link(m, _is_md=True), content,
            )
            content = _EXTERNAL_BACKTICK_RE.sub(
                lambda m: _inline_link(m, _is_md=False), content,
            )

            with open(md_path, "w", encoding="utf-8") as f:
                f.write(content)

    # Promote capability.md → SKILL.md with standalone frontmatter.
    cap_md = os.path.join(dest, "capability.md")
    skill_md = os.path.join(dest, "SKILL.md")
    if os.path.isfile(cap_md):
        with open(cap_md, "r", encoding="utf-8") as f:
            body = f.read()
        # Drop existing frontmatter (capability frontmatter is optional
        # and may use fields the standalone spec doesn't require), then
        # write fresh standalone frontmatter that satisfies validate_skill.
        body_no_fm = re.sub(r"^---\n.*?\n---\n", "", body, count=1, flags=re.DOTALL)
        new_frontmatter = (
            "---\n"
            f"name: {capability_name}\n"
            "description: >\n"
            f"  Lifted from a capability for testing — triggers when "
            f"exercising the {capability_name} workflow end to end.\n"
            "---\n"
        )
        with open(skill_md, "w", encoding="utf-8") as f:
            f.write(new_frontmatter + body_no_fm)
        os.remove(cap_md)


class CapabilityLiftInvariantTests(unittest.TestCase):
    """A synthetic capability with internal + external references must
    survive a mechanical lift and validate clean as a standalone skill."""

    def test_lift_preserves_validation_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = os.path.join(tmp, "parent")
            os.makedirs(parent)

            # Parent skill structure
            write_text(
                os.path.join(parent, "SKILL.md"),
                "---\nname: parent\n"
                "description: Parent skill triggered when validating "
                "capability lift end to end.\n---\n# Parent\n"
                "See [demo](capabilities/demo/capability.md).\n",
            )
            write_text(
                os.path.join(parent, "references", "shared.md"),
                "# Shared\nUsed by capabilities.\n",
            )
            write_text(
                os.path.join(parent, "assets", "template.md"),
                "# Template\n",
            )

            # Capability with both internal and external refs
            cap_dir = os.path.join(parent, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n"
                "Local: [local](references/local.md)\n"
                "Shared: [shared](../../references/shared.md)\n"
                "Asset: [asset](../../assets/template.md)\n",
            )
            write_text(
                os.path.join(cap_dir, "references", "local.md"),
                "# Local\nIntra-capability sibling.\n",
            )

            # Lift — destination directory name must match the capability
            # name so the standalone skill's ``name`` frontmatter matches
            # the dir basename (a structural rule the validator enforces).
            lifted = os.path.join(tmp, "demo")
            _mechanical_lift(parent, "demo", lifted)

            # Validate the lifted skill
            errors, _passes = validate_skill(lifted)
            fails = [e for e in errors if e.startswith("FAIL")]
            warns = [e for e in errors if e.startswith("WARN")]
            self.assertEqual(
                fails, [],
                f"lifted skill must produce no FAIL findings; got: {fails!r}",
            )
            self.assertEqual(
                warns, [],
                f"lifted skill must produce no WARN findings; got: {warns!r}",
            )


if __name__ == "__main__":
    unittest.main()
