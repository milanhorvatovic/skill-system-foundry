"""Lint test: every production text-mode write declares newline="\\n".

Without ``newline="\\n"``, Python's text mode translates ``\\n`` to
``\\r\\n`` on Windows, so files authored on a Windows runner pick up
CRLF terminators that diverge from LF on POSIX.  The rule is to
declare ``newline="\\n"`` on every text-mode write so output is
deterministic regardless of host.

The lint walks the production source trees (the meta-skill scripts,
the repo-infrastructure scripts under top-level ``scripts/``, and the
CI helpers under ``.github/scripts/``) and asserts that every
``open(..., "w"`` or ``open(..., "a"`` call with ``encoding="utf-8"``
also carries ``newline="\\n"``.  Tests under ``tests/`` are exempt
because they typically write fixtures in ``"wb"`` mode or rely on
default newline handling that does not affect production output.
"""

import os
import re
import unittest


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)


_PRODUCTION_DIRS: tuple[str, ...] = (
    os.path.join(_REPO_ROOT, "skill-system-foundry", "scripts"),
    os.path.join(_REPO_ROOT, "scripts"),
    os.path.join(_REPO_ROOT, ".github", "scripts"),
)


# Match ``open(<path>, "<mode>", ..., encoding="utf-8", ...)`` where
# ``<mode>`` is a text-mode write flag.  The pattern requires the
# mode literal to follow the first positional argument (the path)
# and a comma — production code uses positional mode exclusively, so
# this shape avoids false positives from quoted strings appearing
# elsewhere inside the open call (e.g. ``encoding="utf-8"``).
#
# The mode capture accepts ``w`` or ``a`` followed by zero or more
# of ``t`` / ``+`` so the lint covers ``"w"``, ``"wt"``, ``"w+"``,
# ``"wt+"``, ``"a"``, ``"at"``, ``"a+"``, and ``"at+"`` — every
# text-mode write Python accepts.  Binary modes (``"wb"``, ``"ab"``,
# ``"wb+"``, etc.) are excluded by the absence of ``b`` from the
# trailing class so the lint does not falsely flag binary writes,
# which never need the ``newline="\n"`` keyword.  Read modes
# (``"r"``, ``"rb"``, ``"r+"``) are excluded because their first
# character is ``r``, not in ``[wa]``.
#
# A previous pattern used ``\b["']([wa])["']`` which silently
# matched nothing — between a space and a quote there is no word
# boundary, so production calls like ``open(p, "w", encoding=…)``
# never tripped the regex.  The lint passed trivially with zero
# matches.  This shape captures the real pattern explicitly.
# No ``re.DOTALL`` flag — the pattern uses no ``.`` token, so
# DOTALL would be a no-op.  The newline-traversal across multi-line
# ``open()`` calls comes from ``[^,)]+``, ``[^)]*?``, and ``\s``,
# none of which depend on ``.``'s line-anchored default.
_RE_TEXT_WRITE_OPEN = re.compile(
    r'open\([^,)]+,\s*["\']([wa][t+]*)["\']'
    r'[^)]*?encoding\s*=\s*["\']utf-8["\'][^)]*?\)',
)


def _iter_python_sources() -> list[str]:
    sources: list[str] = []
    for root in _PRODUCTION_DIRS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fname in filenames:
                if fname.endswith(".py"):
                    sources.append(os.path.join(dirpath, fname))
    return sources


class TextWriteNewlineLintTests(unittest.TestCase):
    """Production text writes must declare ``newline="\\n"``."""

    def test_every_text_write_declares_newline(self) -> None:
        offenders: list[str] = []
        for source in _iter_python_sources():
            with open(source, "r", encoding="utf-8") as fh:
                content = fh.read()
            for match in _RE_TEXT_WRITE_OPEN.finditer(content):
                call = match.group(0)
                if "newline=" in call:
                    continue
                # Compute line number for diagnostics.
                line_no = content.count("\n", 0, match.start()) + 1
                rel = os.path.relpath(source, _REPO_ROOT).replace(os.sep, "/")
                offenders.append(f"{rel}:{line_no} -> {call.strip()}")
        self.assertEqual(
            offenders,
            [],
            msg=(
                "Text-mode writes missing newline=\"\\n\" — Python "
                "translates \\n to \\r\\n on Windows without it.  "
                "Sites:\n  " + "\n  ".join(offenders)
            ),
        )


class LintRegexCoverageTests(unittest.TestCase):
    """The lint regex catches every text-mode flavour Python accepts.

    Pinned regression: the previous regex used ``[\"']([wa])[\"']``
    and silently exempted multi-character text modes (``"w+"``,
    ``"a+"``, ``"wt"``, ``"at+"``).  Production code does not use
    those forms today, but the lint's docstring claimed coverage of
    "every text-mode write" so the gap mattered for future-proofing.
    Binary modes (``"wb"`` etc.) must still be excluded because they
    never need the ``newline="\\n"`` keyword.
    """

    def test_text_modes_match(self) -> None:
        for mode in ("w", "wt", "w+", "wt+", "a", "at", "a+", "at+"):
            sample = f"open(p, \"{mode}\", encoding=\"utf-8\")"
            self.assertRegex(
                sample,
                _RE_TEXT_WRITE_OPEN,
                msg=f"text mode '{mode}' not matched",
            )

    def test_binary_modes_do_not_match(self) -> None:
        for mode in ("wb", "ab", "wb+", "ab+", "rb"):
            sample = f"open(p, \"{mode}\", encoding=\"utf-8\")"
            self.assertNotRegex(
                sample,
                _RE_TEXT_WRITE_OPEN,
                msg=f"binary mode '{mode}' incorrectly matched",
            )

    def test_lint_actually_flags_a_violation(self) -> None:
        """The lint regex matches a real violator without ``newline=``.

        Pinned regression for the silent-no-op bug — the previous
        regex's ``\\b["']`` requirement landed between two non-word
        characters (space and quote) and so never matched any
        production open call.  This test proves the new regex finds
        a violator that the lint loop would then report.
        """
        sample = (
            "with open(filepath, \"w\", encoding=\"utf-8\") as fh:\n"
            "    fh.write('x')\n"
        )
        match = _RE_TEXT_WRITE_OPEN.search(sample)
        self.assertIsNotNone(match)
        self.assertNotIn("newline=", match.group(0))


if __name__ == "__main__":
    unittest.main()
