"""Lint test: every production text-mode write declares newline="\\n".

Without ``newline="\\n"``, Python's text mode translates ``\\n`` to
``\\r\\n`` on Windows, so files authored on a Windows runner pick up
CRLF terminators that diverge from LF on POSIX.  The rule is to
declare ``newline="\\n"`` on every text-mode write so output is
deterministic regardless of host.

The lint walks the production source trees (the meta-skill scripts,
the repo-infrastructure scripts under top-level ``scripts/``, and the
CI helpers under ``.github/scripts/``) using Python's ``ast`` module
and asserts that every built-in ``open(...)`` call with a text-mode
write flag also carries ``newline="\\n"``.  Tests
under ``tests/`` are exempt because they typically write fixtures in
``"wb"`` mode or rely on default newline handling that does not
affect production output.

The newline rule is **independent of the encoding rule**: any
text-mode write performs Windows newline translation regardless of
which encoding the call uses, so the lint applies to every
text-mode ``open(...)`` write call — calls without ``encoding=`` at
all, calls whose ``encoding`` is a non-literal expression (e.g. a
``UTF8`` constant), and calls that pin ``encoding="utf-8"`` are all
treated identically.  Example call shapes appearing below that
include ``encoding="utf-8"`` are illustrative, not preconditions
for the lint to fire.  The repo's separate ``encoding="utf-8"``
convention is documented in AGENTS.md but is not gating this lint
— coupling the two would let a future ``open(p, "w")`` (no
encoding kwarg at all) silently bypass the newline guard.

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
    """Return True when *node* is a supported built-in ``open`` call.

    The walker accepts the bare-name form plus explicit
    ``builtins.open`` / ``io.open`` aliases because those expose the
    built-in text-file API and support ``newline=``.  It deliberately
    rejects arbitrary ``obj.open(...)`` methods (for example
    ``zipfile.ZipFile.open``), whose signatures and newline semantics
    differ; treating every method named ``open`` as a built-in file
    write would produce false-positive lint failures with invalid
    remediation advice.
    """
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        return True
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "open"
        and isinstance(func.value, ast.Name)
        and func.value.id in ("builtins", "io")
    ):
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
    2. Its ``mode`` argument is either a literal text-mode write
       (``"w"``, ``"a"``, ``"w+"``, ``"wt"``, ``"x"``, ``"r+"``, …;
       binary modes are skipped) OR a non-literal expression that
       the lint cannot prove is safe.
    3. It does NOT declare ``newline="\\n"`` (either omits the
       keyword entirely or uses a different value such as ``""`` or
       ``None``).

    Non-literal modes (``open(path, MODE)`` where ``MODE`` is a
    ``ast.Name`` / attribute / call expression) are flagged because
    a constant resolution like ``WRITE_MODE = "w"`` would otherwise
    let production code introduce CRLF output on Windows while
    bypassing the lint entirely.  An author who genuinely needs a
    dynamic mode has three remediations: inline the literal at the
    call site, pin ``newline="\\n"`` defensively (only safe when
    the dynamic mode is guaranteed text — Python raises
    ``ValueError: binary mode doesn't take a newline argument``
    when ``newline=`` is paired with a binary mode), or split the
    call into separate ``open()`` invocations per mode shape.
    Calls with no ``mode`` argument at all default to ``"r"``
    (read-only text), which cannot write — those are skipped.

    The newline rule is independent of the encoding rule: any
    text-mode write performs newline translation on Windows
    regardless of which encoding it uses, so the lint applies
    even when ``encoding`` is missing or set to a non-literal
    expression (e.g. a ``UTF8`` constant).  The repo's separate
    ``encoding="utf-8"`` convention is documented in AGENTS.md but
    is not gating this lint — coupling the two would let a future
    ``open(p, "w")`` (no encoding kwarg at all) silently bypass
    the newline guard.
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
        mode_node = kwargs.get("mode")
        if mode_node is None:
            # No ``mode`` argument at all — defaults to ``"r"``
            # (read-only text), which never writes.
            continue
        mode = _string_constant(mode_node)
        non_literal_mode = False
        if mode is None:
            non_literal_mode = True
        elif not _is_text_mode_write(mode):
            continue
        newline_node = kwargs.get("newline")
        newline = _string_constant(newline_node)
        if newline == "\n":
            continue
        # Anything else is an offender — keyword missing, set to a
        # different literal, or set to a non-literal expression.
        if non_literal_mode:
            shown = ast.unparse(mode_node)
            if newline_node is None:
                reason = (
                    f"mode is a non-literal expression ({shown}) and "
                    "newline=\"\\n\" missing — pin newline=\"\\n\" "
                    "defensively or inline the mode literal"
                )
            else:
                newline_shown = ast.unparse(newline_node)
                reason = (
                    f"mode is a non-literal expression ({shown}) and "
                    f"newline is {newline_shown}; expected \"\\n\" — "
                    "pin newline=\"\\n\" defensively or inline the "
                    "mode literal"
                )
        elif newline_node is None:
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
        # ``newline="\n"`` keeps the fixture deterministic across hosts.
        # Without it, Windows would translate the source's ``\n`` to
        # ``\r\n`` on disk; the lint walks the file via ``ast.parse``
        # which copes with either, but the regression harness for the
        # explicit-LF rule should not introduce host variability into
        # its own fixture writer.
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", suffix=".py",
            delete=False,
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

    def test_no_encoding_keyword_is_still_matched(self) -> None:
        """A text-mode write without ``encoding=`` still triggers the rule.

        Pinned regression: an earlier ``_find_offenders`` skipped
        any call whose ``encoding`` was not the literal string
        ``"utf-8"``, which let ``open(p, "w")`` (no encoding
        keyword at all) and ``open(p, "w", encoding=UTF8)`` (a
        constant expression) bypass the newline check.  Newline
        translation is independent of encoding, so the lint must
        apply regardless of which encoding the call uses.
        """
        source = (
            "with open('p', 'w') as fh:\n"
            "    fh.write('x')\n"
        )
        self.assertEqual(len(self._scan(source)), 1)

    def test_non_literal_encoding_is_still_matched(self) -> None:
        # ``encoding=UTF8`` is a name expression, not a literal.
        # The newline check must still fire.
        source = (
            "UTF8 = 'utf-8'\n"
            "with open('p', 'w', encoding=UTF8) as fh:\n"
            "    fh.write('x')\n"
        )
        self.assertEqual(len(self._scan(source)), 1)

    def test_arbitrary_open_methods_are_skipped(self) -> None:
        """Only built-in-compatible ``open`` calls are linted.

        Pinned regression: the AST lint previously accepted any
        attribute named ``open``.  Production APIs such as
        ``zipfile.ZipFile.open`` do not accept ``newline=`` and
        should not receive the text-file remediation this lint
        reports.
        """
        source = (
            "import zipfile\n"
            "with zipfile.ZipFile('out.zip', 'w') as zf:\n"
            "    with zf.open('member.txt', mode='w') as fh:\n"
            "        fh.write(b'x')\n"
        )
        self.assertEqual(self._scan(source), [])

    def test_supported_open_attributes_are_matched(self) -> None:
        """``builtins.open`` and ``io.open`` still use file semantics."""
        for opener in ("builtins.open", "io.open"):
            with self.subTest(opener=opener):
                source = (
                    "import builtins\n"
                    "import io\n"
                    f"with {opener}('p', 'w') as fh:\n"
                    "    fh.write('x')\n"
                )
                self.assertEqual(len(self._scan(source)), 1)

    def test_non_literal_mode_is_offender(self) -> None:
        """Non-literal mode expressions are flagged.

        Pinned regression: an earlier ``_find_offenders`` skipped any
        call whose ``mode`` was not a string literal, so a constant
        resolution like ``WRITE_MODE = "w"; open(path, WRITE_MODE,
        encoding="utf-8")`` bypassed the newline check entirely.  The
        lint cannot prove a non-literal mode is binary or read-only,
        so it surfaces such calls as offenders so a reviewer either
        inlines the literal or pins ``newline="\\n"`` defensively.
        """
        source = (
            "WRITE_MODE = 'w'\n"
            "with open('p', WRITE_MODE, encoding='utf-8') as fh:\n"
            "    fh.write('x')\n"
        )
        offenders = self._scan(source)
        self.assertEqual(len(offenders), 1)
        self.assertIn("non-literal", offenders[0][1])

    def test_non_literal_mode_with_lf_newline_passes(self) -> None:
        """Non-literal mode + ``newline="\\n"`` is fine.

        The defensive remediation path: pinning ``newline="\\n"`` at
        the call site removes the variability the lint is worried
        about, so the lint accepts the call even though it cannot
        prove the mode is a write.
        """
        source = (
            "WRITE_MODE = 'w'\n"
            "with open('p', WRITE_MODE, encoding='utf-8', "
            "newline='\\n') as fh:\n"
            "    fh.write('x')\n"
        )
        self.assertEqual(self._scan(source), [])

    def test_non_literal_mode_with_non_lf_newline_is_offender(self) -> None:
        """Non-literal mode + non-LF newline triggers the combined message.

        Pinned regression: ``_find_offenders`` has a four-quadrant
        decision (``non_literal_mode × newline_node is None``); this
        test exercises the fourth quadrant whose dedicated message
        formats both the mode and the newline expressions.  Without
        coverage, a typo swapping ``newline_shown`` for the mode's
        ``shown`` would land silently.
        """
        source = (
            "WRITE_MODE = 'w'\n"
            "with open('p', WRITE_MODE, encoding='utf-8', "
            "newline='') as fh:\n"
            "    fh.write('x')\n"
        )
        offenders = self._scan(source)
        self.assertEqual(len(offenders), 1)
        reason = offenders[0][1]
        self.assertIn("non-literal", reason)
        self.assertIn("WRITE_MODE", reason)
        self.assertIn("newline is ''", reason)

    def test_no_mode_kwarg_is_skipped(self) -> None:
        """``open(path)`` with no mode defaults to ``"r"``; not flagged.

        Distinguishes the absent-argument case from the non-literal
        case so the lint does not produce noise on bare reads.
        """
        source = (
            "with open('p') as fh:\n"
            "    fh.read()\n"
        )
        self.assertEqual(self._scan(source), [])


if __name__ == "__main__":
    unittest.main()
