#!/usr/bin/env python3
"""Compute the next release version from the ``release:`` labels of merged PRs.

``release-prep.yaml`` calls this when its ``version`` input is left empty.  The
next version is the manifest version (``skill-system-foundry/SKILL.md``, the
canonical source ``bump_version.py`` validates against) bumped by the highest
``release:`` level among the PRs merged since the last ``vX.Y.Z`` tag — ``major``
beats ``minor`` beats ``patch``; ``release: skip`` contributes nothing.

The PR window is computed by **commit membership**, not a timestamp search: the
set of commits in ``git rev-list <tag>..HEAD`` is intersected with each merged
PR's ``mergeCommit`` oid.  This excludes the previous release PR cleanly (its
squash commit *is* the tag commit, so it is never in ``<tag>..HEAD``) and is
order- and boundary-independent.  A coarse ``merged:>=<tag-date>`` search
qualifier bounds the ``gh pr list`` result so the exact membership filter
operates on a small, relevant set rather than the whole history.

Policy: any in-window PR that is unlabeled or carries more than one ``release:``
label aborts the run with a per-PR fix hint (the label gate is report-only until
WI-4, so unlabeled merges happen; this surfaces them rather than silently
under-releasing).  Dispatching ``release-prep`` with an explicit version is the
escape hatch, but it does not clear the label debt — the offending PRs must
still be labeled before the next computed release.

On success the computed ``X.Y.Z`` is printed to **stdout** (and nothing else,
so the workflow can capture it directly); a human-readable summary of which PRs
drove the bump goes to **stderr**.

This is repo-infrastructure, not part of the meta-skill bundle.  It is
intentionally independent from ``skill-system-foundry/scripts/``; logic shared
with the release tooling lives in ``scripts/lib/version.py`` and is loaded by
explicit path.

Exit codes:

    0   success — the computed X.Y.Z is on stdout
    2   usage error (argparse)
    3   precondition failed — not inside a git repository, no vX.Y.Z tag,
        manifest/tag drift, a pre-release manifest base, a git/gh invocation
        failed, or the PR-list cap was hit
    4   label gap — one or more in-window PRs are unlabeled or carry more than
        one release label (printed as a fail-and-list with fix hints)
    5   nothing to release — no PRs merged since the last tag, or every merged
        PR in the window is release: skip
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Load the local ``version`` helper by explicit path so the import does not
# collide with ``skill-system-foundry/scripts/lib`` when both trees end up on
# ``sys.path`` (e.g. during test discovery).  Same idiom as bump_version.py.
_VERSION_PATH = os.path.join(_SCRIPTS_DIR, "lib", "version.py")
_spec = importlib.util.spec_from_file_location("repo_infra_version", _VERSION_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise RuntimeError(f"cannot load {_VERSION_PATH}")
_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_version)


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PRECONDITION = 3
EXIT_LABEL_GAP = 4
EXIT_NOTHING = 5

# The GitHub Search API caps a query at ~1000 results; 200 is well above any
# single release window for this repo and keeps the membership filter cheap.
# Hitting it means the window is implausibly large — fail rather than silently
# truncate (which would compute too low a version).
PR_LIST_LIMIT = 200


class ComputeError(Exception):
    """A precondition failed; carries an operator-facing message.

    ``main`` surfaces the message on stderr and returns
    :data:`EXIT_PRECONDITION`.
    """


def find_repo_root(start: str) -> str | None:
    """Walk upward from *start* until a ``.git`` entry is found.

    Returns ``None`` when no ``.git`` entry exists.  Accepts both a ``.git``
    directory (ordinary checkout) and a ``.git`` file (git worktrees write a
    file pointing at the linked repository).  Kept local to match the existing
    per-script duplication in ``bump_version.py`` / ``generate_changelog.py``.
    """
    current = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def run_git(args: list[str], repo_root: str) -> str:
    """Run ``git *args`` in *repo_root*; raise :class:`ComputeError` on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ComputeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def run_gh(args: list[str], repo_root: str) -> str:
    """Run ``gh *args`` in *repo_root*; raise :class:`ComputeError` on failure."""
    result = subprocess.run(
        ["gh", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ComputeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def latest_release_tag(repo_root: str) -> str:
    """Return the highest core-semver ``vX.Y.Z`` tag's version (no ``v``).

    Tags are selected by semver maximum rather than ``git describe`` so the
    result does not depend on commit topology.  Pre-release tags (``v1.2.0-rc.1``)
    are excluded — only core releases are candidates.  Raises
    :class:`ComputeError` when no core-semver tag exists.
    """
    out = run_git(["tag", "-l", "v[0-9]*.[0-9]*.[0-9]*"], repo_root)
    candidates: list[str] = []
    for line in out.splitlines():
        name = line.strip()
        if not name.startswith("v"):
            continue
        core = name[1:]
        if "-" not in core and _version.SEMVER_RE.match(core):
            candidates.append(core)
    if not candidates:
        raise ComputeError(
            "no vX.Y.Z release tag found; dispatch release-prep with an "
            "explicit version for the first release."
        )
    best = candidates[0]
    for core in candidates[1:]:
        if _version.compare(core, best) > 0:
            best = core
    return best


def tag_commit_date(tag_core: str, repo_root: str) -> str:
    """Return the committer date (``YYYY-MM-DD``) of tag ``v<tag_core>``.

    Used as a coarse, timezone-unambiguous lower bound for the ``gh pr list``
    search; the exact window is then narrowed by commit membership.
    """
    out = run_git(["log", "-1", "--format=%cs", f"v{tag_core}^{{commit}}"], repo_root)
    date = out.strip()
    if not date:
        raise ComputeError(f"could not read commit date for tag v{tag_core}")
    return date


def commits_since_tag(tag_core: str, repo_root: str) -> set[str]:
    """Return the set of commit oids in ``git rev-list v<tag_core>..HEAD``."""
    out = run_git(["rev-list", f"v{tag_core}..HEAD"], repo_root)
    return {line.strip() for line in out.splitlines() if line.strip()}


def fetch_merged_prs(repo_root: str, since_date: str) -> list[dict]:
    """Return merged PRs to ``main`` since *since_date* (coarse bound).

    Raises :class:`ComputeError` on a malformed payload or when the result hits
    :data:`PR_LIST_LIMIT` (an implausibly large window that would otherwise be
    silently truncated).
    """
    out = run_gh(
        [
            "pr",
            "list",
            "--search",
            f"is:merged base:main merged:>={since_date}",
            "--json",
            "number,title,labels,mergeCommit",
            "--limit",
            str(PR_LIST_LIMIT),
        ],
        repo_root,
    )
    try:
        rows = json.loads(out)
    except json.JSONDecodeError as exc:
        raise ComputeError(f"could not parse gh pr list output: {exc}") from exc
    if not isinstance(rows, list):
        raise ComputeError("gh pr list did not return a JSON array")
    if len(rows) >= PR_LIST_LIMIT:
        raise ComputeError(
            f"gh pr list hit the {PR_LIST_LIMIT}-result cap since {since_date}; "
            "cut an interim release manually or add pagination."
        )
    return rows


def select_window_levels(
    commit_set: set[str], pr_rows: list[dict]
) -> tuple[
    list[tuple[int, str, str]],
    list[tuple[int, str]],
    list[tuple[int, str, list[str]]],
]:
    """Partition the *pr_rows* whose merge commit is in *commit_set*.

    Returns ``(counted, unlabeled, ambiguous)``:

    * ``counted`` — ``(number, title, level)`` for each in-window PR carrying
      exactly one ``release:`` label (``skip`` included);
    * ``unlabeled`` — ``(number, title)`` for in-window PRs with no release label;
    * ``ambiguous`` — ``(number, title, labels)`` for in-window PRs with more
      than one release label (``labels`` are the ``release: *`` strings found,
      for the operator-facing remove hint).

    A PR whose ``mergeCommit`` is missing/null, or whose oid is not in
    *commit_set*, is out of window and ignored.
    """
    counted: list[tuple[int, str, str]] = []
    unlabeled: list[tuple[int, str]] = []
    ambiguous: list[tuple[int, str, list[str]]] = []
    for row in pr_rows:
        merge_commit = row.get("mergeCommit")
        oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
        if not oid or oid not in commit_set:
            continue
        number = row.get("number")
        title = row.get("title", "")
        labels = [
            label.get("name", "")
            for label in row.get("labels", [])
            if isinstance(label, dict)
        ]
        levels = _version.release_levels_in(labels)
        if not levels:
            unlabeled.append((number, title))
        elif len(levels) > 1:
            ambiguous.append((number, title, [f"release: {lv}" for lv in levels]))
        else:
            counted.append((number, title, levels[0]))
    return counted, unlabeled, ambiguous


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Compute the next release version from the release: labels of PRs "
            "merged since the last vX.Y.Z tag, anchored to the SKILL.md "
            "manifest version. Prints the computed X.Y.Z to stdout."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None or code == 0:
            return EXIT_OK
        return EXIT_USAGE

    repo_root = find_repo_root(os.getcwd())
    if repo_root is None:
        print(
            "error: not inside a git repository; cannot compute the version.",
            file=sys.stderr,
        )
        return EXIT_PRECONDITION

    try:
        tag_core = latest_release_tag(repo_root)
        manifest = _version.read_skill_md_version(_version.skill_md_path(repo_root))
        if manifest is None:
            raise ComputeError(
                "could not read metadata.version from skill-system-foundry/SKILL.md."
            )
        if manifest != tag_core:
            raise ComputeError(
                f"manifest version {manifest} does not match the latest tag "
                f"v{tag_core}. The manifest leads the latest tag — a release "
                "may be mid-tag (release-on-merge runs in a separate workflow), "
                "so wait and retry; if it persists, run the audit and reconcile."
            )
        since_date = tag_commit_date(tag_core, repo_root)
        commit_set = commits_since_tag(tag_core, repo_root)
        pr_rows = fetch_merged_prs(repo_root, since_date)
    except ComputeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PRECONDITION

    counted, unlabeled, ambiguous = select_window_levels(commit_set, pr_rows)

    if unlabeled or ambiguous:
        print(
            "error: cannot compute the next version — these merged PRs need a "
            "release label (the gate is report-only, so label them and "
            "re-dispatch, or dispatch with an explicit version):",
            file=sys.stderr,
        )
        for number, title in unlabeled:
            print(f"  #{number} unlabeled — {title}", file=sys.stderr)
            print(
                f'    fix: gh pr edit {number} --add-label '
                f'"release: <major|minor|patch|skip>"',
                file=sys.stderr,
            )
        for number, title, found in ambiguous:
            print(
                f"  #{number} multiple labels ({', '.join(found)}) — {title}",
                file=sys.stderr,
            )
            print(
                f"    fix: gh pr edit {number} --remove-label "
                "<all but one of the above>",
                file=sys.stderr,
            )
        return EXIT_LABEL_GAP

    bump = _version.highest_level([level for _, _, level in counted])
    if bump is None:
        if not counted:
            print(
                f"error: no PRs merged since v{tag_core}; nothing to release "
                "(dispatched too soon?).",
                file=sys.stderr,
            )
        else:
            print(
                f"error: all {len(counted)} merged PRs since v{tag_core} are "
                "release: skip; nothing user-facing to release.",
                file=sys.stderr,
            )
        return EXIT_NOTHING

    try:
        nxt = _version.next_version(manifest, bump)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PRECONDITION

    contributing = [(n, level) for n, _, level in counted if level != "skip"]
    skipped = [n for n, _, level in counted if level == "skip"]
    summary = (
        f"Computed {bump} bump v{manifest} -> {nxt} from "
        + ", ".join(f"#{n} ({level})" for n, level in contributing)
    )
    if skipped:
        summary += "; skipped " + ", ".join(f"#{n}" for n in skipped)
    print(summary, file=sys.stderr)

    print(nxt)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
