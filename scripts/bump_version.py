#!/usr/bin/env python3
"""Bump the version across SKILL.md, plugin.json, and marketplace.json in lockstep.

Each file is replaced via ``os.replace`` so the swap is atomic *per file*,
but the set of three is **not** transactional: a failure between the
first and last swap leaves the manifests inconsistent on disk and the
script reports that drift via ``EXIT_PARTIAL_WRITE``.  Treat this as a
best-effort lockstep bump, not a cross-file atomic transaction.

The three files are the single source of truth for the release version.
``audit_skill_system.py`` enforces that they agree; this script is the
primitive for changing all three in lockstep.

Usage::

    python scripts/bump_version.py 1.2.0
    python scripts/bump_version.py 1.2.0 --dry-run
    python scripts/bump_version.py 0.9.0 --allow-downgrade

Behavior:

* Reads the current version from every file and refuses to run if they
  disagree — version drift must be fixed first (run the audit).
* Validates the new version against a local semver regex (reject ``v``
  prefix and ``+build`` metadata).
* Rejects equal versions unconditionally.  Rejects downgrades unless
  ``--allow-downgrade`` is passed.
* Plans the three file edits in memory, probes the changelog generator
  in ``--dry-run`` mode when ``CHANGELOG.md`` exists, and only then
  commits the edits via ``os.replace`` (per-file atomicity).  A failing
  probe aborts before any manifest file is touched.
* After writing the manifest files, invokes ``scripts/generate_changelog.py``
  with ``--in-place`` to prepend the new section.  If that step fails the
  manifest files are already bumped — the script surfaces the failure with
  a non-zero exit code so the operator can re-run the changelog step.

The script is repo-infrastructure, not part of the meta-skill bundle.
It is intentionally independent from ``skill-system-foundry/scripts/``;
logic shared with that tree is duplicated by design (see
``scripts/lib/version.py``).

Exit codes:

    0   success, or dry-run preview printed
    2   invalid input (bad semver, equal version, downgrade without flag,
        not inside a git repository, argparse error)
    3   precondition failed (the three manifest files already disagree)
    4   changelog generator probe or write failed
    5   plan failed (regex matched zero or multiple times) OR the first
        write raised before any file was swapped (no drift introduced)
    6   partial write — at least one file was swapped before the failure,
        so version drift is now present on disk and must be reconciled
"""

import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Load the local ``version`` helper by explicit path so the import does not
# collide with ``skill-system-foundry/scripts/lib`` when both trees end up
# on ``sys.path`` (e.g. during test discovery).  The two trees are
# intentionally independent — duplication over bridging.
_VERSION_PATH = os.path.join(_SCRIPTS_DIR, "lib", "version.py")
_spec = importlib.util.spec_from_file_location(
    "repo_infra_version", _VERSION_PATH
)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise RuntimeError(f"cannot load {_VERSION_PATH}")
_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_version)


EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_DRIFT = 3
EXIT_CHANGELOG_FAILED = 4
EXIT_PLAN_FAILED = 5
EXIT_PARTIAL_WRITE = 6

GENERATOR_SCRIPT = os.path.join(_SCRIPTS_DIR, "generate_changelog.py")


def _display_path(path: str, repo_root: str) -> str:
    """Return *path* relative to *repo_root* with forward-slash separators.

    Operator-facing output should not depend on the OS the bump ran on —
    tests assert against the forward-slash form and maintainers copy-paste
    these paths between Windows and POSIX shells.
    """
    return os.path.relpath(path, repo_root).replace(os.sep, "/")


def find_repo_root(start: str) -> str | None:
    """Walk upward from *start* until a ``.git`` entry is found.

    Returns ``None`` when no ``.git`` entry exists.  Accepts both a
    ``.git`` directory (ordinary checkout) and a ``.git`` file (git
    worktrees write a file pointing at the linked repository).
    """
    current = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def head_sha(repo_root: str) -> str | None:
    """Return ``git rev-parse HEAD`` for *repo_root*, or ``None`` on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


class ManifestReadError(Exception):
    """A manifest file could not be read or parsed.

    Carries a human-readable per-file message that ``main()`` surfaces
    under ``EXIT_DRIFT`` so a malformed manifest is treated as a
    precondition failure rather than an uncaught traceback.
    """


def _safe_read(label: str, fn: Callable[[], str | None]) -> str | None:
    """Run *fn* and translate ``OSError``/``json.JSONDecodeError`` to
    :class:`ManifestReadError` with a *label* prefix.
    """
    try:
        return fn()
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestReadError(f"{label}: {exc}") from exc


def read_all_versions(repo_root: str) -> dict[str, str | None]:
    """Return current version from each of the three manifest files.

    Raises :class:`ManifestReadError` when any manifest is missing,
    unreadable, or contains invalid JSON / frontmatter — operator-facing
    precondition failures that ``main()`` maps to ``EXIT_DRIFT``.  An
    empty or missing top-level ``"name"`` in ``plugin.json`` is also a
    precondition failure: without a name the script cannot match the
    plugin entry inside ``marketplace.json``, and silently skipping that
    read would surface downstream as a misleading "marketplace.json"
    error.
    """
    skill_path = _version.skill_md_path(repo_root)
    plugin_path = _version.plugin_json_path(repo_root)
    market_path = _version.marketplace_json_path(repo_root)
    plugin_name = _safe_read(
        "plugin.json", lambda: _version.read_plugin_name(plugin_path)
    )
    if not plugin_name:
        raise ManifestReadError(
            "plugin.json: missing or empty 'name' — cannot match the "
            "plugin entry in marketplace.json"
        )
    return {
        "SKILL.md": _safe_read(
            "SKILL.md", lambda: _version.read_skill_md_version(skill_path)
        ),
        "plugin.json": _safe_read(
            "plugin.json", lambda: _version.read_plugin_json_version(plugin_path)
        ),
        "marketplace.json": _safe_read(
            "marketplace.json",
            lambda: _version.read_marketplace_json_version(
                market_path, plugin_name
            ),
        ),
    }


def plan_writes(
    repo_root: str, current: str, new: str
) -> list[tuple[str, str]]:
    """Return ``[(path, new_content)]`` for every manifest file.

    Raises ``ValueError`` when any anchored regex does not match exactly
    once — the caller maps that to exit 5.  Raises
    :class:`ManifestReadError` when a manifest cannot be read so the
    caller can surface that as a precondition failure (``EXIT_DRIFT``)
    rather than a stack trace.
    """
    skill_path = _version.skill_md_path(repo_root)
    plugin_path = _version.plugin_json_path(repo_root)
    market_path = _version.marketplace_json_path(repo_root)

    def _read(label: str, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            raise ManifestReadError(f"{label}: {exc}") from exc

    skill_content = _read("SKILL.md", skill_path)
    plugin_content = _read("plugin.json", plugin_path)
    market_content = _read("marketplace.json", market_path)

    return [
        (skill_path, _version.plan_skill_md_edit(skill_content, current, new)),
        (plugin_path, _version.plan_plugin_json_edit(plugin_content, current, new)),
        (market_path, _version.plan_marketplace_json_edit(market_content, current, new)),
    ]


class PartialWriteError(OSError):
    """Phase 2 of commit_writes failed partway through.

    ``swapped`` lists the paths that were successfully replaced with
    the new version; those files now disagree with the untouched ones.
    The caller must surface this drift so the operator can reconcile
    manually — ``os.replace`` is atomic per file, not across the set.
    """

    def __init__(self, swapped: list[str], remaining: list[str], cause: OSError) -> None:
        super().__init__(str(cause))
        self.swapped = swapped
        self.remaining = remaining
        self.cause = cause


def commit_writes(writes: list[tuple[str, str]]) -> None:
    """Replace each target via an adjacent ``.tmp`` using ``os.replace``.

    Each ``os.replace`` is atomic per file, but the set as a whole is
    not transactional.  Phase 1 stages every ``.tmp`` on disk; phase 2
    swaps them into place one at a time.  If phase 1 fails, no target
    has been touched — the stale ``.tmp`` files are cleaned up.  If
    phase 2 fails partway through, earlier files already carry the new
    version while later ones still carry the old; that is drift, and
    we raise :class:`PartialWriteError` so the caller can tell the
    operator exactly which files need manual reconciliation.
    """
    tmp_paths: list[str] = []
    swapped: list[str] = []
    try:
        for path, content in writes:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            tmp_paths.append(tmp)
        staged: list[tuple[str, str]] = list(zip([p for p, _ in writes], tmp_paths))
        for index, (path, tmp) in enumerate(staged):
            try:
                os.replace(tmp, path)
            except OSError as exc:
                remaining = [p for p, _ in staged[index:]]
                raise PartialWriteError(swapped, remaining, exc) from exc
            swapped.append(path)
            tmp_paths.remove(tmp)
    finally:
        for leftover in tmp_paths:
            try:
                os.remove(leftover)
            except OSError:
                pass


def run_generator(
    repo_root: str,
    *,
    since: str,
    new_version: str,
    date: str,
    until: str,
    dry_run: bool,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``scripts/generate_changelog.py`` with appropriate flags."""
    argv = [
        sys.executable,
        GENERATOR_SCRIPT,
        "--since",
        since,
        "--version",
        new_version,
        "--date",
        date,
        "--until",
        until,
        "--in-place",
    ]
    if dry_run:
        argv.append("--dry-run")
    return subprocess.run(
        argv,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bump the version across SKILL.md, plugin.json, and "
            "marketplace.json atomically."
        ),
    )
    parser.add_argument(
        "new_version",
        help="The new version (X.Y.Z, optional -prerelease suffix).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned edits without writing.",
    )
    parser.add_argument(
        "--allow-downgrade",
        action="store_true",
        help=(
            "Allow setting the new version lower than the current one. "
            "Equal versions are still rejected."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # ``parse_args`` raises ``SystemExit`` on bad input or ``--help``.  The
    # script's contract is that ``main()`` returns an int, so translate the
    # exit code: argparse error (2) → ``EXIT_INVALID_INPUT``; ``--help`` /
    # explicit ``SystemExit(0)`` → ``EXIT_OK``; anything else passes through.
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None or code == 0:
            return EXIT_OK
        if isinstance(code, int) and code == 2:
            return EXIT_INVALID_INPUT
        return code if isinstance(code, int) else EXIT_INVALID_INPUT

    new_version = args.new_version
    # Reject shapes not covered by SEMVER_RE.
    if not _version.SEMVER_RE.match(new_version):
        print(
            f"error: new_version must be X.Y.Z (with optional -prerelease "
            f"suffix); got {new_version!r}",
            file=sys.stderr,
        )
        return EXIT_INVALID_INPUT
    # Build metadata is syntactically rejected by SEMVER_RE but be explicit
    # for operators who might paste a ``1.2.3+build`` string from semver.org.
    if "+" in new_version or new_version.startswith("v"):
        print(
            f"error: new_version must not carry a 'v' prefix or '+build' "
            f"metadata; got {new_version!r}",
            file=sys.stderr,
        )
        return EXIT_INVALID_INPUT

    repo_root = find_repo_root(os.getcwd())
    if repo_root is None:
        print(
            "error: not inside a git repository; cannot locate the "
            "manifest files.",
            file=sys.stderr,
        )
        return EXIT_INVALID_INPUT

    # Precondition: all three files already agree.
    try:
        versions = read_all_versions(repo_root)
    except ManifestReadError as exc:
        print(
            f"error: cannot read manifest files — {exc}; fix the manifest "
            "and re-run.",
            file=sys.stderr,
        )
        return EXIT_DRIFT
    missing = [name for name, value in versions.items() if value is None]
    if missing:
        print(
            f"error: could not read current version from: {', '.join(missing)}",
            file=sys.stderr,
        )
        return EXIT_DRIFT
    unique_values = set(versions.values())
    if len(unique_values) != 1:
        print(
            "error: version drift detected before bump — "
            + ", ".join(f"{k}={v}" for k, v in versions.items())
            + "; run `python skill-system-foundry/scripts/audit_skill_system.py "
            + repo_root
            + "` and reconcile before bumping.",
            file=sys.stderr,
        )
        return EXIT_DRIFT
    current = versions["SKILL.md"]
    assert current is not None  # Guarded above; aid the type checker.

    # Equal / downgrade guard.
    try:
        order = _version.compare(new_version, current)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    if order == 0:
        print(
            f"error: new_version {new_version!r} equals the current "
            f"version; nothing to do.",
            file=sys.stderr,
        )
        return EXIT_INVALID_INPUT
    if order < 0 and not args.allow_downgrade:
        print(
            f"error: new_version {new_version!r} is lower than the current "
            f"version {current!r}; pass --allow-downgrade to force.",
            file=sys.stderr,
        )
        return EXIT_INVALID_INPUT

    # Plan the file edits.
    try:
        writes = plan_writes(repo_root, current, new_version)
    except ManifestReadError as exc:
        print(
            f"error: cannot read manifest files — {exc}; fix the manifest "
            "and re-run.",
            file=sys.stderr,
        )
        return EXIT_DRIFT
    except ValueError as exc:
        print(f"error: plan failed: {exc}", file=sys.stderr)
        return EXIT_PLAN_FAILED

    # Probe the changelog generator when CHANGELOG.md is present.  The
    # probe runs the generator with --dry-run --in-place so an unmapped
    # commit or a duplicate section is caught before any file is written.
    changelog_path = os.path.join(repo_root, "CHANGELOG.md")
    changelog_exists = os.path.exists(changelog_path)
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    since_tag = f"v{current}"
    until_ref = head_sha(repo_root) or "HEAD"

    probe_stdout = ""
    if changelog_exists:
        probe = run_generator(
            repo_root,
            since=since_tag,
            new_version=new_version,
            date=today,
            until=until_ref,
            dry_run=True,
        )
        if probe.returncode != 0:
            print(
                f"error: changelog probe failed with exit {probe.returncode}; "
                "no files were modified.",
                file=sys.stderr,
            )
            if probe.stderr:
                sys.stderr.write(probe.stderr)
            return EXIT_CHANGELOG_FAILED
        probe_stdout = probe.stdout

    # Dry-run: print the plan and exit without touching disk.
    if args.dry_run:
        print(f"Planned bump: {current} → {new_version}")
        for path, _ in writes:
            rel = _display_path(path, repo_root)
            print(f"  would update {rel}: {current} → {new_version}")
        if changelog_exists:
            print()
            print("Changelog preview (--dry-run):")
            print(probe_stdout.rstrip())
        else:
            print("(CHANGELOG.md absent — generator step would be skipped.)")
        return EXIT_OK

    # Execute the staged writes.
    try:
        commit_writes(writes)
    except PartialWriteError as exc:
        if not exc.swapped:
            # The first write failed before any file was swapped; no drift.
            print(f"error: write failed: {exc.cause}", file=sys.stderr)
            return EXIT_PLAN_FAILED
        print(
            f"error: partial write — {exc.cause}.  Version drift is now "
            "present on disk and must be reconciled manually:",
            file=sys.stderr,
        )
        for path in exc.swapped:
            rel = _display_path(path, repo_root)
            print(f"  swapped to {new_version}: {rel}", file=sys.stderr)
        for path in exc.remaining:
            rel = _display_path(path, repo_root)
            print(f"  still at  {current}: {rel}", file=sys.stderr)
        return EXIT_PARTIAL_WRITE
    except OSError as exc:
        print(f"error: write failed: {exc}", file=sys.stderr)
        return EXIT_PLAN_FAILED

    # Generate the changelog for real.
    if changelog_exists:
        result = run_generator(
            repo_root,
            since=since_tag,
            new_version=new_version,
            date=today,
            until=until_ref,
            dry_run=False,
        )
        if result.returncode != 0:
            print(
                f"error: changelog generator exited {result.returncode} "
                "after the manifest files were bumped.  The version bump is "
                "committed to disk; re-run the generator manually to finish.",
                file=sys.stderr,
            )
            if result.stderr:
                sys.stderr.write(result.stderr)
            return EXIT_CHANGELOG_FAILED

    print(f"Bumped version: {current} → {new_version}")
    for path, _ in writes:
        rel = _display_path(path, repo_root)
        print(f"  updated {rel}")
    if changelog_exists:
        print("  updated CHANGELOG.md")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
