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


# Match ``open(...)`` calls that include ``"w"`` or ``"a"`` (text-mode
# writes) and ``encoding="utf-8"``.  Captures the full call so the
# matcher can re-check for the ``newline=`` keyword.
_RE_TEXT_WRITE_OPEN = re.compile(
    r"open\(\s*[^)]*?\b[\"']([wa])[\"'][^)]*?\bencoding\s*=\s*[\"']utf-8[\"'][^)]*?\)",
    re.DOTALL,
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


if __name__ == "__main__":
    unittest.main()
