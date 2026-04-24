#!/usr/bin/env python3
"""Generate a Keep-a-Changelog section from git commit history.

Reads commits between two refs, buckets them into Keep-a-Changelog
sections (Added / Changed / Deprecated / Removed / Fixed / Security)
via a first-word verb map loaded from ``scripts/lib/changelog.yaml``,
and emits a Keep-a-Changelog 1.1.0 section.  Commits whose first word
is not in the map are surfaced on stderr and are NOT written to the
output — the human author then reclassifies them manually.

Usage::

    python scripts/generate_changelog.py --since v1.0.2 --version 1.1.0
    python scripts/generate_changelog.py --since v1.0.2 --version 1.1.0 --in-place
    python scripts/generate_changelog.py --since v1.0.2 --version 1.1.0 --in-place --dry-run
    python scripts/generate_changelog.py --since v1.0.2 --version 1.1.0 --date 2026-03-22

Exit codes:

    0   all commits were classified and output was produced
    2   argparse usage error (argparse default), or a runtime failure
        surfaced as an ``error: ...`` line on stderr (missing --since
        ref, duplicate version in CHANGELOG.md, unreadable or invalid
        configuration).  Reserved for genuine script failures so CI
        can distinguish "broken invocation" from "needs classification"
    3   one or more commits were unmapped (human review required).
        Covers three surfaces: the stdout path (section printed,
        unmapped listed on stderr), ``--in-place --dry-run`` (partial
        merge printed, file unchanged), and ``--in-place`` without
        --dry-run (the write is refused with an ``error: ...`` line on
        stderr to avoid leaving a partial section on disk)

The script is repository infrastructure, not part of the meta-skill.
It borrows the meta-skill's YAML parser by loading
``skill-system-foundry/scripts/lib/yaml_parser.py`` directly via
``importlib.util`` — this avoids vendoring a second copy without
reserving the ``lib`` package name on ``sys.path``.  The script also
does not implement ``--json`` (a meta-skill convention) because its
output is a single Markdown section consumed by humans during a
release, and unmapped commits are surfaced on stderr in a
line-oriented form already suitable for scripting.

The generator always synthesizes a fresh ``## [version] - date``
section from git history; it does not promote an existing
``## [Unreleased]`` heading.  New releases are inserted below
``## [Unreleased]`` when present, which matches this repository's
ledger-style workflow (no Unreleased accumulator is maintained).
"""

import argparse
import datetime
import importlib.util
import os
import re
import subprocess
import sys
import typing

# Load-bearing: this script reuses the meta-skill's stdlib-only YAML
# parser rather than vendoring a second copy.  The file is loaded
# directly via ``importlib.util`` so the ``lib`` package name on
# ``sys.path`` is not claimed globally — a second ``scripts/lib/`` tree
# in this repo (or a test that inserts one) would otherwise collide.
# If ``skill-system-foundry/scripts/lib/yaml_parser.py`` is renamed or
# relocated, update ``_YAML_PARSER_PATH`` below in the same change.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_YAML_PARSER_PATH = os.path.join(
    _REPO_ROOT, "skill-system-foundry", "scripts", "lib", "yaml_parser.py"
)


def _require_yaml_parser() -> typing.Callable[[str], typing.Any]:
    """Load the meta-skill's YAML parser or raise with an actionable message.

    Deferred so the import failure routes through main()'s error
    contract (``error: ...`` on stderr, exit 2) instead of escaping as
    a traceback at module-load time.
    """
    if not os.path.exists(_YAML_PARSER_PATH):
        raise RuntimeError(
            f"cannot locate yaml_parser.py at {_YAML_PARSER_PATH}; "
            "update _YAML_PARSER_PATH at the top of this file if "
            "skill-system-foundry was moved or renamed."
        )
    spec = importlib.util.spec_from_file_location(
        "_changelog_yaml_parser", _YAML_PARSER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"importlib could not build a spec for {_YAML_PARSER_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        raise RuntimeError(
            f"failed to load yaml_parser from {_YAML_PARSER_PATH}: {exc}"
        ) from exc
    return module.parse_yaml_subset

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "lib", "changelog.yaml"
)

SECTION_ORDER = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

# Accepts X.Y.Z and vX.Y.Z with optional pre-release and/or build
# metadata per semver 2.0.0 (e.g. 1.2.0-rc.1, 1.2.0+build.42).  Each
# dot-separated identifier must have at least one character — this
# excludes malformed inputs like ``1.2.0-.`` that a looser character
# class would otherwise accept.
_SEMVER_RE = re.compile(
    r"^v?\d+\.\d+\.\d+"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _is_iso_date(value: str) -> bool:
    """Return ``True`` when *value* is a real ``YYYY-MM-DD`` calendar date.

    ``datetime.date.fromisoformat`` also accepts richer ISO forms
    (e.g. ``20260322``), which would splice a heading the rest of the
    toolchain does not recognize; enforce the hyphenated 10-char shape
    first, then let ``fromisoformat`` reject impossible dates like
    ``2026-13-45``.
    """
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def load_verb_mapping(config_path: str = CONFIG_PATH) -> dict[str, str]:
    """Return ``{verb: section}`` flattened from configuration.yaml.

    The YAML stores sections as keys with verb lists as values (the
    natural way to read it); this inverts to a flat lookup for O(1)
    bucketing during commit processing.

    Raises ``RuntimeError`` if the YAML declares a section name that is
    not in ``SECTION_ORDER`` — the renderer iterates ``SECTION_ORDER``
    only, so an unknown section would silently drop its commits.
    """
    parse_yaml_subset = _require_yaml_parser()
    with open(config_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    config = parse_yaml_subset(text)
    changelog = config.get("changelog")
    if not isinstance(changelog, dict) or "verb_mapping" not in changelog:
        raise RuntimeError(
            f"{config_path} is missing the required 'changelog.verb_mapping' "
            f"block; cannot classify commits."
        )
    sections = changelog["verb_mapping"]
    if not isinstance(sections, dict):
        raise RuntimeError(
            f"'changelog.verb_mapping' in {config_path} must be a mapping, "
            f"got {type(sections).__name__}."
        )
    flat: dict[str, str] = {}
    for section, verbs in sections.items():
        if section not in SECTION_ORDER:
            raise RuntimeError(
                f"verb_mapping section {section!r} is not in SECTION_ORDER "
                f"{SECTION_ORDER}; either add it to SECTION_ORDER or remove "
                f"it from {config_path}."
            )
        if not isinstance(verbs, list):
            raise RuntimeError(
                f"verb_mapping[{section!r}] must be a list, got "
                f"{type(verbs).__name__}; check {config_path}."
            )
        for verb in verbs:
            if verb in flat:
                raise RuntimeError(
                    f"verb {verb!r} appears under both {flat[verb]!r} and "
                    f"{section!r} in {config_path}; a verb must map to a "
                    f"single section."
                )
            flat[verb] = section
    return flat


def run_git(args: list[str], cwd: str) -> str:
    """Run a git command and return stdout.  Raises on non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def tag_exists(ref: str, repo_root: str) -> bool:
    """Return ``True`` when ``refs/tags/{ref}`` resolves in *repo_root*."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{ref}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def tag_commit_date(tag: str, repo_root: str) -> str:
    """Return ``%as`` (author date, ISO short) for *tag*."""
    return run_git(["log", "-1", "--format=%as", tag], repo_root).strip()


def collect_commits(since: str, until: str, repo_root: str) -> list[tuple[str, str]]:
    """Return ``[(sha, subject)]`` for commits in ``since..until``.

    Merge commits are excluded: in a squash-merge workflow they should
    not appear, and in a traditional-merge workflow their ``Merge pull
    request #N`` subjects would route to unmapped anyway.  Excluding
    them up-front keeps stderr output focused on real content commits.

    Commits are returned newest-first (git's default for ``log``), and
    ``render_section`` preserves that order in the rendered bullets.
    Keep-a-Changelog does not mandate an ordering; reviewers are free
    to reorder manually before tagging.
    """
    out = run_git(
        [
            "log",
            "--no-merges",
            "--pretty=%H%x00%s",
            f"{since}..{until}",
        ],
        repo_root,
    )
    commits: list[tuple[str, str]] = []
    for line in out.splitlines():
        if "\x00" not in line:
            continue
        sha, subject = line.split("\x00", 1)
        sha = sha.strip()
        subject = subject.strip()
        if sha and subject:
            commits.append((sha, subject))
    return commits


def first_word(subject: str) -> str:
    """Return the first whitespace-delimited token of *subject*."""
    tokens = subject.split(None, 1)
    return tokens[0] if tokens else ""


def classify_commits(
    commits: list[tuple[str, str]],
    verb_map: dict[str, str],
) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """Split commits into ``{section: [subject]}`` and ``[(sha, subject)]`` unmapped.

    Multi-verb subjects (``Update X and add Y``) use the first word
    only; every commit subject in this repo already starts with a
    verb, so the first word is the intended classifier.
    """
    buckets: dict[str, list[str]] = {s: [] for s in SECTION_ORDER}
    unmapped: list[tuple[str, str]] = []
    for sha, subject in commits:
        verb = first_word(subject)
        section = verb_map.get(verb)
        if section is None:
            unmapped.append((sha, subject))
            continue
        buckets[section].append(subject)
    return buckets, unmapped


def render_section(
    version: str,
    date: str,
    buckets: dict[str, list[str]],
) -> str:
    """Render a Keep-a-Changelog section for *version*.

    Empty subsections are omitted — Keep-a-Changelog allows this and
    it keeps the output tight.
    """
    lines = [f"## [{version}] - {date}"]
    for section in SECTION_ORDER:
        entries = buckets.get(section) or []
        if not entries:
            continue
        lines.append("")
        lines.append(f"### {section}")
        lines.append("")
        for subject in entries:
            lines.append(f"- {subject}")
    lines.append("")
    return "\n".join(lines)


_VERSION_LINE_RE = re.compile(r"^## \[([^\]]+)\]")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _precedence_token(bracket_contents: str) -> str:
    """Drop build metadata and a leading ``v`` so semver-equivalent versions collapse.

    Per semver 2.0.0 §10, build metadata (``+...``) does not affect
    precedence: ``1.0.0`` and ``1.0.0+build.42`` are equivalent for
    ordering and uniqueness.  The splice guard must treat them as the
    same version so a rebuilt release cannot smuggle a duplicate
    section in under a build-metadata alias.  A leading ``v`` is also
    stripped because ``normalize_version`` drops it from the emitted
    heading: a hand-edited ``## [v1.1.0]`` in CHANGELOG.md must still
    block a newly-emitted ``## [1.1.0]`` rather than silently coexist.
    """
    token = bracket_contents.split("+", 1)[0]
    return token[1:] if token.startswith("v") else token


def _extract_version(section: str) -> str | None:
    """Return the semver-precedence token from a section's heading.

    Strips build metadata (see ``_precedence_token``); the prerelease
    suffix (``-rc.1``) is preserved because it does affect precedence.
    """
    for line in section.splitlines():
        match = _VERSION_LINE_RE.match(line)
        if match:
            return _precedence_token(match.group(1))
    return None


def _iter_heading_lines(text: str) -> typing.Iterator[tuple[int, str]]:
    """Yield ``(index, line)`` for each top-level line outside fenced code blocks.

    ``## [X.Y.Z]`` lines inside ```` ``` ```` / ``~~~`` fences are content
    examples, not real release headings, and must not trip the splice's
    duplicate-version guard or anchor scan.
    """
    in_fence = False
    for idx, line in enumerate(text.splitlines()):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield idx, line


def splice_into_changelog(existing: str, new_section: str) -> str:
    """Insert *new_section* above the most recent release section.

    The anchor is the first ``## [X.Y.Z]`` heading in *existing*; the
    new section is inserted directly before it so any preamble between
    the H1 and that heading stays intact.  When *existing* has no
    release sections yet, the new section is appended after whatever
    preamble is present (or synthesized if the H1 is also missing).

    Refuses to splice when the version already appears in *existing* —
    the release path should not silently produce a duplicate section.
    Fenced code blocks are skipped during both scans so embedded
    examples do not cause false positives.
    """
    version = _extract_version(new_section)
    if version and existing:
        for _, line in _iter_heading_lines(existing):
            match = _VERSION_LINE_RE.match(line)
            if match and _precedence_token(match.group(1)) == version:
                raise RuntimeError(
                    f"CHANGELOG.md already contains a section for {version}; "
                    "remove it first or run without --in-place to emit to stdout."
                )

    new_section = new_section.rstrip() + "\n"
    lines = existing.splitlines(keepends=True)

    # Preferred anchor: the first existing release section outside any
    # fenced code block.  Only semver-shaped headings count — a
    # standard Keep-a-Changelog ``## [Unreleased]`` must not anchor the
    # splice (new releases belong below Unreleased, not above it).
    for idx, line in _iter_heading_lines(existing):
        match = _VERSION_LINE_RE.match(line)
        if match and _SEMVER_RE.match(match.group(1)):
            head = "".join(lines[:idx]).rstrip("\n") + "\n\n"
            tail = "".join(lines[idx:])
            return head + new_section + "\n" + tail

    # No release sections yet.  Synthesize a Keep-a-Changelog preamble
    # only when the file is empty; refuse when the file has content
    # without an H1 (silently demoting user text below a synthesized
    # preamble + release would be more surprising than raising).
    has_h1 = any(line.startswith("# ") for line in lines)
    if not has_h1:
        if existing:
            raise RuntimeError(
                "CHANGELOG.md is non-empty but has no '# ' H1 heading; "
                "refusing to synthesize a preamble on top of unrecognized "
                "content.  Add a '# Changelog' heading (or delete the file) "
                "and re-run."
            )
        preamble = (
            "# Changelog\n"
            "\n"
            "All notable changes to this project are documented in this file.\n"
            "\n"
            "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),\n"
            "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n"
            "\n"
        )
        return preamble + new_section

    head = existing.rstrip("\n") + "\n\n"
    return head + new_section


def _version_tag(version: str) -> str:
    """Return the ``vX.Y.Z`` tag name for *version*, adding ``v`` if missing."""
    return version if version.startswith("v") else f"v{version}"


def resolve_date(
    version: str,
    repo_root: str,
    override: str | None,
    today: str,
) -> str:
    """Return the release date for *version*.

    Precedence: ``--date`` override > tag commit date (if the version
    tag exists) > today's UTC date (see ``today_iso`` for rationale).
    """
    if override:
        return override
    tag = _version_tag(version)
    if tag_exists(tag, repo_root):
        return tag_commit_date(tag, repo_root)
    return today


def resolve_until(version: str, repo_root: str) -> str:
    """Pick the commit range endpoint: the version tag if it exists, else HEAD."""
    tag = _version_tag(version)
    return tag if tag_exists(tag, repo_root) else "HEAD"


def find_repo_root(start: str) -> str:
    """Walk upward from *start* until a ``.git`` entry is found."""
    current = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError(f"no .git found walking up from {start}")
        current = parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a Keep-a-Changelog section from git history.",
    )
    parser.add_argument(
        "--since",
        required=True,
        help="Previous version tag (e.g., v1.0.2) — start of the commit range.",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="New version (e.g., 1.1.0 or v1.1.0) — the section heading version.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Override the release date (YYYY-MM-DD). Defaults to tag commit date when the version tag exists, else today's UTC date.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Splice the generated section into CHANGELOG.md at the repo root, above the most recent release section (below any preamble).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what --in-place would do without writing.",
    )
    return parser


def normalize_version(version: str) -> str:
    """Strip a leading ``v`` from *version* for the section heading."""
    return version[1:] if version.startswith("v") else version


def generate(
    since: str,
    version: str,
    date_override: str | None,
    repo_root: str,
    today: str,
    verb_map: dict[str, str],
) -> tuple[str, list[tuple[str, str]]]:
    """Pure function — returns ``(rendered_section, unmapped_commits)``."""
    until = resolve_until(version, repo_root)
    commits = collect_commits(since, until, repo_root)
    buckets, unmapped = classify_commits(commits, verb_map)
    date = resolve_date(version, repo_root, date_override, today)
    section = render_section(normalize_version(version), date, buckets)
    return section, unmapped


def report_unmapped(
    unmapped: list[tuple[str, str]],
    stream: typing.TextIO,
) -> None:
    """Write ``unmapped — review manually: <sha> <subject>`` for each entry.

    *stream* must have a ``write(str)`` method; the caller picks stderr
    or stdout.  Entries are emitted in the order they were classified
    so the output matches ``git log`` ordering.  Lines are routed
    through ``_write_preserving_lf`` so stderr keeps the same LF
    discipline as stdout on Windows.
    """
    for sha, subject in unmapped:
        _write_preserving_lf(
            f"unmapped — review manually: {sha[:12]} {subject}\n",
            stream,
        )


def today_iso() -> str:
    """Return today's UTC date as YYYY-MM-DD.

    UTC avoids wallclock drift between a contributor running this
    locally and the same command running in GitHub Actions (which is
    always UTC).  Explicit ``--date`` overrides this when needed.
    """
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _write_preserving_lf(text: str, stream: typing.TextIO) -> None:
    """Write *text* to *stream* without newline translation.

    On Windows, text-mode ``stream.write`` rewrites ``\\n`` to
    ``\\r\\n``.  When *stream* exposes a ``buffer`` attribute (real
    stdout/stderr), bypass translation by writing UTF-8 bytes
    directly; fall back to a plain ``write`` for test-time surrogates
    like ``io.StringIO`` that have no ``buffer``.
    """
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
    else:
        stream.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not _SEMVER_RE.match(args.version):
        parser.error(
            f"--version must be X.Y.Z or vX.Y.Z (optional -prerelease / "
            f"+build suffix); got {args.version!r}"
        )
    if args.date is not None and not _is_iso_date(args.date):
        parser.error(
            f"--date must be a valid YYYY-MM-DD calendar date; got {args.date!r}"
        )
    if args.dry_run and not args.in_place:
        parser.error("--dry-run has no effect without --in-place")

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = find_repo_root(script_dir)
        verb_map = load_verb_mapping()

        section, unmapped = generate(
            since=args.since,
            version=args.version,
            date_override=args.date,
            repo_root=repo_root,
            today=today_iso(),
            verb_map=verb_map,
        )

        report_unmapped(unmapped, sys.stderr)

        changelog_path = os.path.join(repo_root, "CHANGELOG.md")

        if args.in_place and unmapped and not args.dry_run:
            # Writing a partial section into CHANGELOG.md is a trap: the
            # user would then have to delete it manually before re-running,
            # because the duplicate-version guard blocks a second splice.
            # Refuse and point at the preview workflow instead.  Exit 3
            # (not 2) because the underlying condition — unmapped commits
            # — is the same "needs human classification" signal the stdout
            # and --dry-run paths already surface with 3.
            _write_preserving_lf(
                f"error: refusing to write CHANGELOG.md with {len(unmapped)} "
                "unmapped commit(s); classify them in scripts/lib/changelog.yaml "
                "(or rewrite the commit subjects) and re-run.  Use "
                "--in-place --dry-run to preview the partial output.\n",
                sys.stderr,
            )
            return 3

        if args.in_place:
            existing = ""
            if os.path.exists(changelog_path):
                # newline="" preserves LF on read; we write LF explicitly below
                # to keep CHANGELOG.md stable across OSes (Windows CI would
                # otherwise churn the whole file to CRLF).
                with open(changelog_path, "r", encoding="utf-8", newline="") as fh:
                    existing = fh.read()
            merged = splice_into_changelog(existing, section)
            if args.dry_run:
                _write_preserving_lf(merged, sys.stdout)
            else:
                with open(changelog_path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(merged)
        else:
            _write_preserving_lf(section, sys.stdout)
    except (RuntimeError, OSError, ValueError) as exc:
        # OSError covers FileNotFoundError and PermissionError from
        # reading/writing CHANGELOG.md; ValueError: parse_yaml_subset
        # raises on unsupported YAML grammar.
        _write_preserving_lf(f"error: {exc}\n", sys.stderr)
        return 2

    return 3 if unmapped else 0


if __name__ == "__main__":
    sys.exit(main())
