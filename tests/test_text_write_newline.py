"""Lint test: every production text-mode write declares newline="\\n".

Without ``newline="\\n"``, Python's text mode translates ``\\n`` to
``\\r\\n`` on Windows, so files authored on a Windows runner pick up
CRLF terminators that diverge from LF on POSIX.  The rule is to
declare ``newline="\\n"`` on every text-mode write so output is
deterministic regardless of host.

The lint walks the production source trees (the meta-skill scripts,
the repo-infrastructure scripts under top-level ``scripts/``, and the
CI helpers under ``.github/scripts/``) using Python's ``ast`` module
and asserts that every ``open(...)`` call with a text-mode write
flag and ``encoding="utf-8"`` also carries ``newline="\\n"``.  Tests
under ``tests/`` are exempt because they typically write fixtures in
``"wb"`` mode or rely on default newline handling that does not
affect production output.

An earlier implementation used a regex matcher.  Two false-negative
holes prompted the move to AST: the regex stopped the first
positional argument at any comma, so common production shapes like
``open(os.path.join(root, "out"), "w", encoding="utf-8")`` evaded
the matcher silently; and the ``newline=`` substring check accepted
any ``newline=...`` keyword (including ``newline=""`` and
``newline=None``), so the lint did not actually enforce the
``newline="\\n"`` value the rule requires.  The AST walker handles
nested calls in any positional argument and inspects the
``newline`` keyword's value, eliminating both gaps.
"""

import ast
import os
import unittest


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)


_PRODUCTION_DIRS: tuple[str, ...] = (
    os.path.join(_REPO_ROOT, "skill-system-foundry", "scripts"),
    os.path.join(_REPO_ROOT, "scripts"),
    os.path.join(_REPO_ROOT, ".github", "scripts"),
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


def _is_open_call(node: ast.Call) -> bool:
    """Return True when *node* is a call to ``open`` (or ``X.open``).

    The walker accepts both the bare-name form and the
    attribute form because production code may shadow ``open`` via
    ``import builtins; builtins.open(...)`` or use a module's
    ``open`` member (e.g., ``io.open``).  Either way the
    text-mode-newline rule applies because the underlying call
    accepts the same ``newline=`` keyword.
    """
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "open":
        return True
    return False


def _string_constant(node: ast.expr | None) -> str | None:
    """Return the string value of *node* iff it is a string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_open_kwargs(call: ast.Call) -> dict[str, ast.expr]:
    """Map ``mode`` / ``encoding`` / ``newline`` to their AST nodes.

    Handles both positional and keyword forms.  ``open``'s signature
    is ``open(file, mode='r', buffering=-1, encoding=None,
    errors=None, newline=None, ...)``; we only care about the three
    keywords that gate the lint, and we pull them from positional
    args when present.
    """
    out: dict[str, ast.expr] = {}
    # Positional: file, mode, buffering, encoding, errors, newline
    positional_names = (
        "file", "mode", "buffering", "encoding", "errors", "newline",
    )
    for idx, arg in enumerate(call.args):
        if idx < len(positional_names):
            out[positional_names[idx]] = arg
    for kw in call.keywords:
        if kw.arg is None:  # **kwargs splat
            continue
        out[kw.arg] = kw.value
    return out


def _is_text_mode_write(mode: str) -> bool:
    """Return True for text-mode writes.

    Covers every Python file-mode shape that produces a writable
    text stream:

    * ``w`` — open for writing, truncating first.
    * ``a`` — open for writing, appending.
    * ``x`` — open for exclusive creation, failing if the path exists.
    * ``r+`` (and the optional ``t``) — open for reading AND
      writing.  Even though the prefix is ``r``, the ``+`` opens a
      writable stream that performs the same newline translation
      as the other text modes.

    All four shapes require ``newline="\\n"`` to keep output
    deterministic on Windows.  Binary modes (those containing
    ``b``) are exempt because they bypass newline translation
    entirely.
    """
    if not mode:
        return False
    if "b" in mode:  # binary writes are exempt
        return False
    # Mode is writable when its prefix is ``w``/``a``/``x`` OR when
    # it carries ``+`` (which makes ``r+``/``rt+`` writable text
    # streams).  Read-only modes (``r``, ``rt``) never carry ``+``
    # and never start with one of the write prefixes, so they fall
    # through to False.
    return mode[0] in ("w", "a", "x") or "+" in mode


def _find_offenders(source_path: str) -> list[tuple[int, str]]:
    """Yield ``(line_no, reason)`` for every offending ``open`` call.

    A call is an offender when:

    1. It targets ``open``.
    2. It declares a text-mode write flag (``"w"``, ``"a"``,
       ``"w+"``, ``"wt"``, …; binary modes are skipped).
    3. It declares ``encoding="utf-8"`` (the project convention —
       binary writes and bare reads are out of scope).
    4. It does NOT declare ``newline="\\n"`` (either omits the
       keyword entirely or uses a different value such as ``""`` or
       ``None``).
    """
    offenders: list[tuple[int, str]] = []
    with open(source_path, "r", encoding="utf-8") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=source_path)
    except SyntaxError as exc:  # pragma: no cover — defensive only
        offenders.append((exc.lineno or 0, f"could not parse: {exc}"))
        return offenders
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_open_call(node):
            continue
        kwargs = _extract_open_kwargs(node)
        mode = _string_constant(kwargs.get("mode"))
        if mode is None or not _is_text_mode_write(mode):
            continue
        encoding = _string_constant(kwargs.get("encoding"))
        if encoding != "utf-8":
            continue
        newline_node = kwargs.get("newline")
        newline = _string_constant(newline_node)
        if newline == "\n":
            continue
        # Anything else is an offender — keyword missing, set to a
        # different literal, or set to a non-literal expression.
        if newline_node is None:
            reason = "newline=\"\\n\" missing"
        else:
            shown = ast.unparse(newline_node)
            reason = f'newline expected to be "\\n" but is {shown}'
        offenders.append((node.lineno, reason))
    return offenders


class TextWriteNewlineLintTests(unittest.TestCase):
    """Production text writes must declare ``newline="\\n"``."""

    def test_every_text_write_declares_newline(self) -> None:
        offenders: list[str] = []
        for source in _iter_python_sources():
            rel = os.path.relpath(source, _REPO_ROOT).replace(os.sep, "/")
            for line_no, reason in _find_offenders(source):
                offenders.append(f"{rel}:{line_no} -> {reason}")
        self.assertEqual(
            offenders,
            [],
            msg=(
                "Text-mode writes missing newline=\"\\n\" — Python "
                "translates \\n to \\r\\n on Windows without it.  "
                "Sites:\n  " + "\n  ".join(offenders)
            ),
        )


class LintCoverageTests(unittest.TestCase):
    """The AST-based lint catches text-mode writes the regex missed.

    Pinned regressions for the gaps that prompted the move to AST:

    1. Nested calls in the first positional argument (the previous
       regex's ``[^,)]+`` couldn't consume them, so common shapes
       evaded the matcher).
    2. Multi-character text modes (``"w+"``, ``"wt"``, ``"at+"``).
    3. ``newline="" `` and ``newline=None`` masquerading as
       compliant via a substring check on ``newline=``.
    """

    def _scan(self, source: str) -> list[tuple[int, str]]:
        # Helper: write *source* to a temp file and run the walker.
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".py", delete=False,
        ) as fh:
            fh.write(source)
            path = fh.name
        try:
            return _find_offenders(path)
        finally:
            os.unlink(path)

    def test_nested_call_in_first_arg_is_matched(self) -> None:
        # ``open(os.path.join(root, "out"), "w", encoding="utf-8")``
        # without ``newline="\n"`` is an offender.  The regex
        # missed it because of the comma inside ``os.path.join``.
        source = (
            "import os\n"
            "with open(os.path.join('a', 'b'), 'w', encoding='utf-8') as fh:\n"
            "    fh.write('x')\n"
        )
        self.assertEqual(len(self._scan(source)), 1)

    def test_multi_char_text_mode_is_matched(self) -> None:
        # ``"w+"`` and friends are text-mode writes; the lint must
        # flag them when ``newline="\n"`` is absent.  ``x`` /
        # ``x+`` / ``xt`` (exclusive-create text writes) are also
        # text-mode and must be covered.  ``r+`` / ``rt+`` open
        # an existing file for read AND write — the ``+`` makes
        # the stream writable and newline translation still
        # applies, so the lint must flag them too.
        for mode in (
            "w+", "wt", "wt+",
            "a+", "at", "at+",
            "x", "x+", "xt", "xt+",
            "r+", "rt+",
        ):
            with self.subTest(mode=mode):
                source = (
                    f"with open('p', '{mode}', encoding='utf-8') as fh:\n"
                    "    fh.write('x')\n"
                )
                self.assertEqual(len(self._scan(source)), 1)

    def test_binary_mode_is_skipped(self) -> None:
        # Binary writes never need ``newline="\n"`` and must not be
        # flagged.  Includes ``xb`` (exclusive-create binary) for
        # completeness alongside ``x`` text-mode coverage.
        for mode in ("wb", "ab", "wb+", "rb", "xb", "xb+"):
            with self.subTest(mode=mode):
                source = (
                    f"with open('p', '{mode}', encoding='utf-8') as fh:\n"
                    "    fh.write(b'x')\n"
                )
                self.assertEqual(self._scan(source), [])

    def test_newline_empty_string_is_offender(self) -> None:
        # The regex's substring check accepted ``newline=""``; the
        # AST walker requires the value to be exactly ``"\n"``.
        source = (
            "with open('p', 'w', encoding='utf-8', newline='') as fh:\n"
            "    fh.write('x')\n"
        )
        offenders = self._scan(source)
        self.assertEqual(len(offenders), 1)
        self.assertIn("newline expected", offenders[0][1])

    def test_newline_none_is_offender(self) -> None:
        # Same shape: ``newline=None`` is not compliant.
        source = (
            "with open('p', 'w', encoding='utf-8', newline=None) as fh:\n"
            "    fh.write('x')\n"
        )
        self.assertEqual(len(self._scan(source)), 1)

    def test_newline_lf_passes(self) -> None:
        source = (
            "with open('p', 'w', encoding='utf-8', newline='\\n') as fh:\n"
            "    fh.write('x')\n"
        )
        self.assertEqual(self._scan(source), [])

    def test_keyword_mode_is_matched(self) -> None:
        # The walker handles keyword mode too (``open(file,
        # mode="w", encoding="utf-8")``), even though production
        # code currently uses positional mode exclusively.
        source = (
            "with open('p', mode='w', encoding='utf-8') as fh:\n"
            "    fh.write('x')\n"
        )
        self.assertEqual(len(self._scan(source)), 1)


if __name__ == "__main__":
    unittest.main()
