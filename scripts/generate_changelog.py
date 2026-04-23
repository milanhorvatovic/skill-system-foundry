#!/usr/bin/env python3
"""Generate a Keep-a-Changelog section from git commit history.

Reads commits between two refs, buckets them into Added / Changed /
Fixed / Removed via a first-word verb map loaded from
``scripts/lib/configuration.yaml``, and emits a Keep-a-Changelog 1.1.0
section.  Commits whose first word is not in the map are surfaced on
stderr and are NOT written to the output — the human author then
reclassifies them manually.

Usage::

    python scripts/generate_changelog.py --since v1.0.2 --version 1.1.0
    python scripts/generate_changelog.py --since v1.0.2 --version 1.1.0 --in-place
    python scripts/generate_changelog.py --since v1.0.2 --version 1.1.0 --in-place --dry-run
    python scripts/generate_changelog.py --since v1.0.2 --version 1.1.0 --date 2026-03-22

Exit codes:

    0   all commits were classified and output was produced
    1   one or more commits were unmapped (human review required)
    2   argparse usage error, or a runtime failure surfaced as a
        message on stderr (e.g., missing --since ref, duplicate
        version in CHANGELOG.md, unreadable configuration)

The script is repository infrastructure, not part of the meta-skill.
It borrows the meta-skill's YAML parser via a ``sys.path`` shim to
avoid vendoring a second copy.  The script also does not implement
``--json`` (a meta-skill convention) because its output is a single
Markdown section consumed by humans during a release, and unmapped
commits are surfaced on stderr in a line-oriented form already
suitable for scripting.
"""

import argparse
import datetime
import os
import re
import subprocess
import sys
import typing

# Borrow the meta-skill's stdlib-only YAML parser.  The skill directory
# name contains a hyphen, which blocks plain imports, so insert the
# path explicitly.  This is the only cross-boundary dependency; the
# verb_mapping data itself lives in this repo's scripts/lib/ tree.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FOUNDRY_SCRIPTS = os.path.join(_REPO_ROOT, "skill-system-foundry", "scripts")
if _FOUNDRY_SCRIPTS not in sys.path:
    sys.path.insert(0, _FOUNDRY_SCRIPTS)

from lib.yaml_parser import parse_yaml_subset  # noqa: E402

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "lib", "configuration.yaml"
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


def load_verb_mapping(config_path: str = CONFIG_PATH) -> dict[str, str]:
    """Return ``{verb: section}`` flattened from configuration.yaml.

    The YAML stores sections as keys with verb lists as values (the
    natural way to read it); this inverts to a flat lookup for O(1)
    bucketing during commit processing.

    Raises ``RuntimeError`` if the YAML declares a section name that is
    not in ``SECTION_ORDER`` — the renderer iterates ``SECTION_ORDER``
    only, so an unknown section would silently drop its commits.
    """
    with open(config_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    config = parse_yaml_subset(text)
    sections = config.get("changelog", {}).get("verb_mapping", {})
    flat: dict[str, str] = {}
    for section, verbs in sections.items():
        if section not in SECTION_ORDER:
            raise RuntimeError(
                f"verb_mapping section {section!r} is not in SECTION_ORDER "
                f"{SECTION_ORDER}; either add it to SECTION_ORDER or remove "
                f"it from {config_path}."
            )
        if not isinstance(verbs, list):
            continue
        for verb in verbs:
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
    return subject.split(None, 1)[0] if subject else ""


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
        buckets.setdefault(section, []).append(subject)
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


def _extract_version(section: str) -> str | None:
    """Return the ``X.Y.Z`` token from a section's ``## [X.Y.Z] - date`` heading."""
    for line in section.splitlines():
        match = _VERSION_LINE_RE.match(line)
        if match:
            return match.group(1)
    return None


def splice_into_changelog(existing: str, new_section: str) -> str:
    """Insert *new_section* above the most recent release section.

    The anchor is the first ``## [X.Y.Z]`` heading in *existing*; the
    new section is inserted directly before it so any preamble between
    the H1 and that heading stays intact.  When *existing* has no
    release sections yet, the new section is appended after whatever
    preamble is present (or synthesized if the H1 is also missing).

    Refuses to splice when the version already appears in *existing* —
    the release path should not silently produce a duplicate section.
    """
    version = _extract_version(new_section)
    if version and existing:
        for line in existing.splitlines():
            match = _VERSION_LINE_RE.match(line)
            if match and match.group(1) == version:
                raise RuntimeError(
                    f"CHANGELOG.md already contains a section for {version}; "
                    "remove it first or run without --in-place to emit to stdout."
                )

    new_section = new_section.rstrip() + "\n"
    lines = existing.splitlines(keepends=True)

    # Preferred anchor: the first existing release section.  Preserves
    # any H1 + preamble block above it.
    for idx, line in enumerate(lines):
        if _VERSION_LINE_RE.match(line):
            head = "".join(lines[:idx]).rstrip("\n") + "\n\n"
            tail = "".join(lines[idx:])
            return head + new_section + "\n" + tail

    # No release sections yet.  Synthesize a Keep-a-Changelog preamble
    # when the file is empty or has no H1; otherwise append below the
    # existing preamble so the first release lands at the bottom.
    has_h1 = any(line.startswith("# ") for line in lines)
    if not has_h1:
        preamble = (
            "# Changelog\n"
            "\n"
            "All notable changes to this project are documented in this file.\n"
            "\n"
            "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),\n"
            "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n"
            "\n"
        )
        return preamble + new_section + (existing if existing else "")

    head = existing.rstrip("\n") + "\n\n"
    return head + new_section


def resolve_date(
    version: str,
    repo_root: str,
    override: str | None,
    today: str,
) -> str:
    """Return the release date for *version*.

    Precedence: ``--date`` override > tag commit date (if the version
    tag exists) > today's local date.
    """
    if override:
        return override
    tag = version if version.startswith("v") else f"v{version}"
    if tag_exists(tag, repo_root):
        return tag_commit_date(tag, repo_root)
    return today


def resolve_until(version: str, repo_root: str) -> str:
    """Pick the commit range endpoint: the version tag if it exists, else HEAD."""
    tag = version if version.startswith("v") else f"v{version}"
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
        help="Override the release date (YYYY-MM-DD). Defaults to tag commit date when the version tag exists, else today's local date.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Splice the generated section into CHANGELOG.md at the repo root, directly after the H1 heading.",
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
    so the output matches ``git log`` ordering.
    """
    for sha, subject in unmapped:
        stream.write(
            f"unmapped — review manually: {sha[:12]} {subject}\n"
        )


def today_iso() -> str:
    """Return today's local date as YYYY-MM-DD."""
    return datetime.date.today().isoformat()


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
    except (RuntimeError, FileNotFoundError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    return 1 if unmapped else 0


if __name__ == "__main__":
    sys.exit(main())
