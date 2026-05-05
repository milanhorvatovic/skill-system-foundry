"""Tests for ``.github/scripts/smoke-rewrite-frontmatter.py``.

The helper is invoked from the bundle-extract-smoke CI job to
replace a scaffolded SKILL.md frontmatter with a known-good stub
that fits the Claude.ai 200-char description cap.  Failures here
would land the smoke job in a confusing state — the bundler would
see a malformed or oversize frontmatter and FAIL with a generic
error.  Pin the rewrite shape so a future contributor cannot
silently change which validator surface the smoke job exercises.
"""

import importlib.util
import os
import tempfile
import unittest


_CI_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".github", "scripts")
)
_script_path = os.path.join(
    _CI_SCRIPTS_DIR, "smoke-rewrite-frontmatter.py"
)
_spec = importlib.util.spec_from_file_location(
    "smoke_rewrite_frontmatter", _script_path
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load module from {_script_path}")
smoke_rewrite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke_rewrite)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class RewriteTests(unittest.TestCase):
    """``rewrite`` replaces existing frontmatter and preserves body."""

    def test_replaces_existing_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            with open(skill_md, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(
                    "---\n"
                    "name: scaffolded-name\n"
                    "description: >\n"
                    "  A long folded-scalar description that would\n"
                    "  exceed the Claude.ai cap if left untouched.\n"
                    "---\n"
                    "# Demo\n\nbody body body\n"
                )
            self.assertEqual(smoke_rewrite.rewrite(skill_md), 0)
            content = _read(skill_md)
            self.assertTrue(content.startswith("---\n"))
            self.assertIn("name: demo\n", content)
            self.assertIn("description: triggers when the demo runs\n", content)
            self.assertIn('allowed-tools: ""\n', content)
            self.assertIn("compatibility: smoke test\n", content)
            self.assertIn("license: MIT\n", content)
            self.assertIn("metadata:\n  version: 1.0.0\n", content)
            # Body preserved
            self.assertIn("# Demo\n\nbody body body\n", content)
            # Old frontmatter dropped
            self.assertNotIn("scaffolded-name", content)
            self.assertNotIn("folded-scalar", content)

    def test_lf_newlines_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            with open(skill_md, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("---\nname: x\n---\nbody\n")
            self.assertEqual(smoke_rewrite.rewrite(skill_md), 0)
            with open(skill_md, "rb") as fh:
                raw = fh.read()
        self.assertNotIn(b"\r\n", raw)

    def test_no_frontmatter_returns_one(self) -> None:
        """A SKILL.md without a frontmatter opener FAILs the helper.

        Pinned regression: an earlier implementation silently
        prepended the stub when the source had no ``---`` opener,
        masking a scaffold regression that omits frontmatter.  The
        smoke job's job is to surface scaffold-pipeline regressions
        — refusing to rewrite a malformed SKILL.md is the right
        failure mode.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            with open(skill_md, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("# Demo\n\nbody only\n")
            self.assertEqual(smoke_rewrite.rewrite(skill_md), 1)

    def test_unclosed_frontmatter_returns_one(self) -> None:
        """A SKILL.md with an opener but no closer FAILs the helper.

        Same rationale as the no-frontmatter case: half-open
        frontmatter is a corruption signal, not something the
        helper should silently overwrite.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            with open(skill_md, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("---\nname: demo\n# no closer\nbody\n")
            self.assertEqual(smoke_rewrite.rewrite(skill_md), 1)

    def test_missing_file_returns_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(
                smoke_rewrite.rewrite(os.path.join(tmpdir, "missing.md")),
                1,
            )

    def test_non_utf8_content_returns_one(self) -> None:
        """A SKILL.md with non-UTF-8 bytes returns the documented exit 1.

        Pinned regression: ``open(..., encoding="utf-8")`` raises
        ``UnicodeDecodeError`` (not ``OSError``) on undecodable
        bytes, so an earlier helper that caught only ``OSError``
        crashed with a traceback instead of exiting cleanly.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = os.path.join(tmpdir, "SKILL.md")
            # Write bytes that are invalid UTF-8 (lone continuation
            # byte 0x80 is never a valid start byte).
            with open(skill_md, "wb") as fh:
                fh.write(b"\x80\x80\x80")
            self.assertEqual(smoke_rewrite.rewrite(skill_md), 1)


if __name__ == "__main__":
    unittest.main()
