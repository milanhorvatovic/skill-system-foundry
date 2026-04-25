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
    except (SystemExit, KeyboardInterrupt):
        # Do not swallow interpreter-teardown signals — they must
        # propagate so the script exits the way the operator intended.
        raise
    except Exception as exc:
        # ImportError, SyntaxError, or anything else raised while
        # executing yaml_parser.py must route through main()'s
        # ``error: …`` / exit 2 contract instead of escaping as a
        # traceback.
        raise RuntimeError(
            f"failed to load yaml_parser from {_YAML_PARSER_PATH}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    parse_yaml_subset = getattr(module, "parse_yaml_subset", None)
    if parse_yaml_subset is None:
        raise RuntimeError(
            f"yaml_parser at {_YAML_PARSER_PATH} does not define "
            "parse_yaml_subset; update this script if the parser API "
            "was renamed."
        )
    if not callable(parse_yaml_subset):
        raise RuntimeError(
            f"yaml_parser at {_YAML_PARSER_PATH} exports parse_yaml_subset, "
            "but it is not callable."
        )
    return parse_yaml_subset

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "lib", "changelog.yaml"
)

SECTION_ORDER = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

# Accepts X.Y.Z and vX.Y.Z with optional pre-release and/or build
# metadata per semver 2.0.0 (e.g. 1.2.0-rc.1, 1.2.0+build.42).  Numeric
# identifiers (major/minor/patch and numeric prerelease identifiers)
# must not carry leading zeros — semver 2.0.0 §2 and §9 forbid
# ``01.2.3`` and ``1.2.3-01``.  Alphanumeric prerelease identifiers
# (``rc1``, ``alpha-2``) are unrestricted.  Each dot-separated
# identifier must have at least one character, which excludes
# malformed inputs like ``1.2.0-.``.
_SEMVER_RE = re.compile(
    r"^v?(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

# Subjects produced by the ``release-prep.yml`` workflow's bump commit.
# These are meta-commits that should not appear in the changelog of the
# version they introduce — the section they prepend already records the
# real changes.  They are also not candidates for "unmapped — review
# manually" stderr noise: the verb ``Release`` is intentionally absent
# from ``changelog.yaml`` (see issue #106), so without this filter every
# subsequent release would surface a stale warning.  The pattern matches
# the full subject so a hand-edited subject like ``Release v1.2.0 (RC)``
# still routes through the verb map (and thus to unmapped) and forces
# the operator to either fix the subject or reclassify deliberately.
_RELEASE_COMMIT_RE = re.compile(
    r"^Release v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?$"
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
    """Return ``{verb: section}`` flattened from ``scripts/lib/changelog.yaml``.

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
    # ``parse_yaml_subset`` accepts any valid YAML document at the top
    # level, so a typo like starting the file with ``- Add`` would
    # return a list (or a scalar for ``42``).  Guard before ``.get``
    # so AttributeError does not escape past main()'s
    # RuntimeError/OSError/ValueError handler.
    if not isinstance(config, dict):
        raise RuntimeError(
            f"{config_path} must contain a top-level mapping, got "
            f"{type(config).__name__}."
        )
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
            # Guard before dict key use: a nested mapping/list item in
            # the YAML would otherwise raise TypeError at ``verb in
            # flat``, and main() only catches RuntimeError/OSError/
            # ValueError — the traceback would escape instead of the
            # documented ``error: …`` / exit 2 contract.
            if not isinstance(verb, str):
                raise RuntimeError(
                    f"verb_mapping[{section!r}] must contain only strings, "
                    f"got {type(verb).__name__}; check {config_path}."
                )
            if verb in flat:
                raise RuntimeError(
                    f"verb {verb!r} appears under both {flat[verb]!r} and "
                    f"{section!r} in {config_path}; a verb must map to a "
                    f"single section."
                )
            flat[verb] = section
    return flat


def run_git(args: list[str], cwd: str) -> str:
    """Run a git command and return stdout.  Raises on non-zero exit.

    Output is decoded as UTF-8 with ``errors="replace"`` rather than
    the process locale so UTF-8 commit subjects do not crash the
    generator on Windows code pages.  A handful of mojibake characters
    in an unmappable commit is strictly better than a traceback that
    aborts the entire release.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def tag_exists(ref: str, repo_root: str) -> bool:
    """Return ``True`` when ``refs/tags/{ref}`` resolves in *repo_root*.

    Decodes stdout/stderr as UTF-8 for the same locale-independence
    rationale as ``run_git``; we only inspect the return code here,
    but tag names and git's stderr messages should still decode
    without raising on Windows code pages.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{ref}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.returncode == 0


def tag_commit_date(tag: str, repo_root: str) -> str:
    """Return the release date (ISO short) for *tag*.

    Prefers the annotated tag's own tagger date, which is the
    authoritative signal for "when this release was cut".  For
    lightweight tags (no tag object, just a ref pointing at a commit)
    ``%(taggerdate:short)`` comes back empty, so we fall back to the
    tagged commit's committer date (``%cs``).  Author date (``%as``)
    is intentionally not used: after a rebase or cherry-pick it can
    predate the actual release by days.
    """
    qualified = f"refs/tags/{tag}"
    tagger_date = run_git(
        ["for-each-ref", "--format=%(taggerdate:short)", qualified],
        repo_root,
    ).strip()
    if tagger_date:
        return tagger_date
    # Qualify the ref explicitly: ``git log v1.1.0`` can resolve to a
    # branch or other ref if a name collision exists, which would pick
    # the wrong commit even though ``tag_exists`` already verified
    # ``refs/tags/<name>``.  ``refs/tags/<tag>`` disambiguates.
    return run_git(["log", "-1", "--format=%cs", qualified], repo_root).strip()


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
        if not sha:
            continue
        # Keep empty-subject commits (body-only / purely machine
        # commits) so classify_commits routes them to the unmapped
        # path — their first word is the empty string, which is not
        # in the verb map.  Dropping them here would bypass the
        # unmapped-review safeguard and let the release run succeed
        # while silently omitting a real commit from the changelog.
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
        if _RELEASE_COMMIT_RE.match(subject):
            # Release-prep bump commits are meta — skip silently so they
            # neither pollute the changelog nor surface as unmapped noise.
            continue
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
# CommonMark §4.5: a fenced code block opens on a line indented by 0-3
# spaces and begins with at least three backticks or tildes.  The
# captured group is the full marker run so callers can enforce the
# CommonMark rule that closing fences must match the opener's
# character family and be at least as long.  An info string
# (e.g. ``` ```python ```) is allowed after the fence characters on
# the opening line, so no trailing lookahead is imposed.
_FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")


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

    ``## [X.Y.Z]`` lines inside ```` ``` ```` / ``~~~`` fences are
    content examples, not real release headings, and must not trip
    the splice's duplicate-version guard or anchor scan.

    Fence tracking follows CommonMark §4.5: a closing fence must use
    the same marker character as the opener and be at least as long,
    and may be followed only by whitespace.  A shorter or different
    fence sequence inside the block (``~~~`` inside a ``` ``` block,
    or three backticks inside a four-backtick block) is therefore
    treated as content, not as a premature close.  The previous
    implementation flipped a single boolean on any fence-looking
    line, which could close the block too early and let the
    anchor/duplicate scans see release headings that live inside
    examples.
    """
    opener: str | None = None
    for idx, line in enumerate(text.splitlines()):
        match = _FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if opener is None:
                # Opening fence — remember the full marker so the
                # closing fence can be verified against it.
                opener = marker
                continue
            # Inside a fence; only close on a matching marker character
            # family, at least as long as the opener, with no trailing
            # content other than whitespace.
            closes = (
                marker[0] == opener[0]
                and len(marker) >= len(opener)
                and line[match.end():].strip() == ""
            )
            if closes:
                opener = None
            # Whether or not it closed, the fence line itself is not
            # yielded — it belongs to the fenced block.
            continue
        if opener is not None:
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

    # Any non-empty existing file must begin with a '# ' H1 on its
    # first non-empty, non-fenced line.  Run this check *before* the
    # semver-anchor scan so a file that starts with ``## [1.0.0]`` (no
    # parent H1) is rejected rather than anchored — anchoring would
    # silently splice into a Keep-a-Changelog-shaped-but-H1-less file.
    first_real_line: str | None = None
    for _, line in _iter_heading_lines(existing):
        if line.strip():
            first_real_line = line
            break

    if first_real_line is not None and not first_real_line.startswith("# "):
        raise RuntimeError(
            "CHANGELOG.md is non-empty but does not begin with a '# ' H1 "
            "heading; refusing to splice into unrecognized content.  Add "
            "a '# Changelog' heading at the top (or delete the file) and "
            "re-run."
        )

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

    if first_real_line is None:
        # ``first_real_line`` is populated from ``_iter_heading_lines``,
        # which skips everything inside fenced code blocks.  So a file
        # whose only content lives inside fences (a draft or a notes
        # file) would reach this branch even though *existing* is not
        # empty — synthesizing a preamble here would silently drop
        # that content.  Inspect the raw text before deciding.
        if existing.strip():
            raise RuntimeError(
                "CHANGELOG.md contains only fenced or whitespace content "
                "with no '# ' H1 heading; refusing to synthesize a "
                "preamble on top of it (that would discard the existing "
                "content).  Add a '# Changelog' heading at the top (or "
                "delete the file) and re-run."
            )
        # Truly empty (or whitespace-only) file — synthesize a full
        # Keep-a-Changelog preamble for a brand-new changelog.
        preamble = (
            "# Changelog\n"
            "\n"
            "All notable changes to this project are documented in this file.\n"
            "\n"
            "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n"
            "\n"
        )
        return preamble + new_section

    # H1 invariant is already enforced above; existing has a '# ' H1
    # and no release anchor — append the new section at the end so any
    # preamble (and optional ``## [Unreleased]``) is preserved.
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
    """Pick the commit range endpoint: the fully-qualified version tag if it exists, else HEAD.

    When the tag exists we return ``refs/tags/<tag>`` rather than the
    bare ``<tag>``.  Bare refnames are ambiguous in Git — if a branch
    happens to share the tag's name, ``git log v1.1.0..HEAD`` would
    resolve to the branch instead — and the fully-qualified form
    forces the commit range against the verified tag.  The ``HEAD``
    fallback is intentional for the pre-tag workflow (generate the
    upcoming section before tagging); callers that need to detect the
    fallback explicitly can still call ``tag_exists`` first.
    """
    tag = _version_tag(version)
    return f"refs/tags/{tag}" if tag_exists(tag, repo_root) else "HEAD"


def _qualified_ref(ref: str, repo_root: str) -> str:
    """Return ``refs/tags/{ref}`` when *ref* names a tag, else *ref* unchanged.

    Prevents a branch that happens to share a tag's name from
    shadowing the tag in ``git log <since>..<until>``.  Refs already
    prefixed with ``refs/`` and non-tag inputs (commit SHAs, branches,
    ``HEAD``) pass through untouched.
    """
    if ref.startswith("refs/"):
        return ref
    if tag_exists(ref, repo_root):
        return f"refs/tags/{ref}"
    return ref


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
        help=(
            "Override the release date (YYYY-MM-DD).  Defaults to the "
            "annotated tag's tagger date (falling back to the tagged "
            "commit's committer date for lightweight tags) when the "
            "version tag exists.  When the tag does not exist, stdout "
            "and --in-place --dry-run previews fall back to today's "
            "UTC date, but --in-place writes require --date explicitly "
            "so a pre-tag release cannot be stamped with a guessed "
            "date."
        ),
    )
    parser.add_argument(
        "--until",
        default=None,
        help=(
            "Pin the upper bound of the commit range to a specific "
            "ref (tag, branch, or SHA).  When provided, this overrides "
            "the default upper bound even if the version tag exists; "
            "when omitted, the range ends at the version tag when it "
            "exists and at HEAD when it does not.  Use this to "
            "preview and write the same commit range even if new "
            "commits land on HEAD between the dry-run and the final "
            "write."
        ),
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
    until_override: str | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    """Pure function — returns ``(rendered_section, unmapped_commits)``.

    ``until_override`` pins the upper bound explicitly (typically to
    a stable SHA / branch / tag chosen by the operator so the same
    commit set is used by both the dry-run preview and the in-place
    write).  When omitted, the upper bound resolves to the verified
    version tag if it exists, or ``HEAD`` otherwise.  Both ``since``
    and ``until_override`` are qualified to ``refs/tags/<name>`` when
    they name an existing tag so a branch sharing the name cannot
    shadow the tag in the ``git log`` range.
    """
    since_ref = _qualified_ref(since, repo_root)
    if until_override is not None:
        until = _qualified_ref(until_override, repo_root)
    else:
        until = resolve_until(version, repo_root)
    commits = collect_commits(since_ref, until, repo_root)
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
    stdout/stderr), bypass translation by writing bytes directly.
    Encode with the stream's own ``encoding`` (with ``errors="replace"``
    for robustness) so a Windows console still on a non-UTF-8 code
    page does not turn the em dash in ``unmapped — review manually``
    or a non-ASCII commit subject into mojibake.  Fall back to a
    plain ``write`` for test-time surrogates like ``io.StringIO`` that
    have no ``buffer``.
    """
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        buffer.write(text.encode(encoding, errors="replace"))
    else:
        stream.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not _SEMVER_RE.match(args.version):
        parser.error(
            f"--version must be X.Y.Z or vX.Y.Z (optional -prerelease "
            f"suffix); got {args.version!r}"
        )
    if "+" in args.version:
        # SemVer build metadata (``+build.42``) is valid under the grammar
        # but is not a publishable release version for this repository —
        # release tags are ``vX.Y.Z`` only.  Worse, the duplicate-version
        # guard intentionally collapses build metadata via
        # ``_precedence_token``, so a ``## [1.2.0+1]`` heading spliced
        # here would later block the real ``1.2.0`` release.  Reject at
        # the CLI boundary.
        parser.error(
            f"--version must not include SemVer build metadata "
            f"('+...' suffix); the release workflow publishes vX.Y.Z "
            f"tags only, and a ``## [{args.version}]`` heading would "
            f"block the plain version under the duplicate-check guard. "
            f"got {args.version!r}"
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

        tag = _version_tag(args.version)
        tag_present = tag_exists(tag, repo_root)

        # The pre-tag / retrospective-regen split is load-bearing: the
        # same command line behaves differently depending on whether
        # ``refs/tags/<version>`` is present locally.  Surface the
        # HEAD fallback on stderr so an operator who *meant* to
        # regenerate a published section (but is working in a clone
        # that has not fetched the tag yet) notices before accepting
        # output that silently widened the range to HEAD.
        if not tag_present and args.until is None:
            _write_preserving_lf(
                f"note: tag {tag!r} not found locally; collecting commits "
                f"through HEAD and treating this as pre-tag generation.  "
                f"Pass --until <ref> to pin the upper bound to a stable "
                f"commit so the range does not drift between dry-run and "
                f"write.  If you meant to regenerate an already-published "
                f"section, run ``git fetch --tags`` and re-invoke.\n",
                sys.stderr,
            )

        # The documented release flow generates CHANGELOG.md *before*
        # creating the tag.  In that case ``resolve_date`` would fall
        # back to today's date, which is wrong if the tag ends up on a
        # different day.  Refuse an ``--in-place`` write that would
        # commit a guessed date to disk.  Previews — stdout and
        # ``--in-place --dry-run`` — are explicitly exempt so the
        # preview/classify loop still works before the tag exists;
        # the guard fires only on the real write path.
        if (
            args.in_place
            and not args.dry_run
            and args.date is None
            and not tag_present
        ):
            raise RuntimeError(
                f"--in-place requires --date when the version tag "
                f"{tag!r} does not exist yet; the generator would "
                f"otherwise stamp today's date on a release that may be "
                f"tagged on a different day.  Pass "
                f"--date YYYY-MM-DD explicitly (matching the date you "
                f"plan to tag) or create the tag first."
            )

        section, unmapped = generate(
            since=args.since,
            version=args.version,
            date_override=args.date,
            repo_root=repo_root,
            today=today_iso(),
            verb_map=verb_map,
            until_override=args.until,
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
                # Default text mode (``newline=None``) normalizes CRLF/CR
                # to LF on read so the splice logic — which uses
                # ``rstrip("\n")`` and manual ``"\n\n"`` joins — sees
                # LF-only content even on a Windows checkout with
                # ``core.autocrlf=true``.  Writing with ``newline="\n"``
                # pins LF on disk so CHANGELOG.md stays stable across
                # OSes.
                with open(changelog_path, "r", encoding="utf-8") as fh:
                    existing = fh.read()
            merged = splice_into_changelog(existing, section)
            if args.dry_run:
                _write_preserving_lf(merged, sys.stdout)
            else:
                with open(changelog_path, "w", encoding="utf-8", newline="\n") as fh:
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
