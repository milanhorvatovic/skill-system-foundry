"""Tests for scripts/compute_release_version.py.

The pure decision core (``select_window_levels``) is tested with plain dicts.
The orchestration is tested by monkeypatching the thin ``run_git`` / ``run_gh``
wrappers and the manifest reader, so no real repository, subprocess, or
``gh`` auth is needed — every test is hermetic.
"""

import contextlib
import importlib.util
import io
import json
import os
import unittest
from collections.abc import Callable, Iterator
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_COMPUTE_PATH = os.path.join(REPO_ROOT, "scripts", "compute_release_version.py")
_spec = importlib.util.spec_from_file_location(
    "repo_infra_compute_release_version", _COMPUTE_PATH
)
assert _spec is not None and _spec.loader is not None
compute = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compute)


def _row(number: int, labels: list[str], oid: str | None, title: str = "t") -> dict:
    merge_commit = {"oid": oid} if oid is not None else None
    return {
        "number": number,
        "title": title,
        "labels": [{"name": name} for name in labels],
        "mergeCommit": merge_commit,
    }


# ===========================================================================
# Pure decision core
# ===========================================================================


class SelectWindowLevelsTests(unittest.TestCase):
    def test_counts_single_labelled_in_window_pr(self) -> None:
        rows = [_row(1, ["release: minor"], "aaa")]
        counted, unlabeled, ambiguous = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual(counted, [(1, "t", "minor")])
        self.assertEqual(unlabeled, [])
        self.assertEqual(ambiguous, [])

    def test_ignores_out_of_window_pr(self) -> None:
        rows = [_row(1, ["release: major"], "zzz")]
        counted, unlabeled, ambiguous = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual((counted, unlabeled, ambiguous), ([], [], []))

    def test_ignores_null_merge_commit(self) -> None:
        rows = [_row(1, ["release: minor"], None)]
        counted, unlabeled, ambiguous = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual((counted, unlabeled, ambiguous), ([], [], []))

    def test_ignores_missing_merge_commit_key(self) -> None:
        rows = [{"number": 1, "title": "t", "labels": [{"name": "release: minor"}]}]
        counted, unlabeled, ambiguous = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual((counted, unlabeled, ambiguous), ([], [], []))

    def test_flags_unlabeled_in_window_pr(self) -> None:
        rows = [_row(7, [], "aaa")]
        counted, unlabeled, ambiguous = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual(counted, [])
        self.assertEqual(unlabeled, [(7, "t")])
        self.assertEqual(ambiguous, [])

    def test_flags_ambiguous_in_window_pr_with_labels(self) -> None:
        rows = [_row(9, ["release: major", "release: skip"], "aaa")]
        counted, unlabeled, ambiguous = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual(counted, [])
        self.assertEqual(unlabeled, [])
        self.assertEqual(
            ambiguous, [(9, "t", ["release: major", "release: skip"])]
        )

    def test_skip_label_is_counted(self) -> None:
        rows = [_row(3, ["release: skip"], "aaa")]
        counted, _, _ = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual(counted, [(3, "t", "skip")])

    def test_valid_plus_malformed_sibling_is_ambiguous(self) -> None:
        rows = [_row(11, ["release: patch", "release: huge"], "aaa")]
        counted, unlabeled, ambiguous = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual(counted, [])
        self.assertEqual(unlabeled, [])
        self.assertEqual(ambiguous, [(11, "t", ["release: patch", "release: huge"])])

    def test_single_malformed_label_is_ambiguous(self) -> None:
        rows = [_row(12, ["release: huge"], "aaa")]
        counted, unlabeled, ambiguous = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual(counted, [])
        self.assertEqual(ambiguous, [(12, "t", ["release: huge"])])

    def test_null_labels_does_not_crash(self) -> None:
        rows = [{"number": 5, "title": "t", "labels": None, "mergeCommit": {"oid": "aaa"}}]
        counted, unlabeled, ambiguous = compute.select_window_levels({"aaa"}, rows)
        self.assertEqual((counted, ambiguous), ([], []))
        self.assertEqual(unlabeled, [(5, "t")])


# ===========================================================================
# Tag selection
# ===========================================================================


class RunHelperErrorTests(unittest.TestCase):
    def test_run_git_missing_binary_raises_compute_error(self) -> None:
        def boom(*args: object, **kwargs: object) -> object:
            raise FileNotFoundError("git")

        with mock.patch.object(compute.subprocess, "run", boom):
            with self.assertRaises(compute.ComputeError):
                compute.run_git(["status"], "/repo")

    def test_run_gh_missing_binary_raises_compute_error(self) -> None:
        def boom(*args: object, **kwargs: object) -> object:
            raise FileNotFoundError("gh")

        with mock.patch.object(compute.subprocess, "run", boom):
            with self.assertRaises(compute.ComputeError):
                compute.run_gh(["pr", "list"], "/repo")


class LatestReleaseTagTests(unittest.TestCase):
    def test_picks_semver_max_and_excludes_prereleases(self) -> None:
        tags = "v1.0.0\nv1.2.1\nv1.10.0\nv2.0.0-rc.1\n"
        with mock.patch.object(compute, "run_git", lambda args, root: tags):
            self.assertEqual(compute.latest_release_tag("/repo"), "1.10.0")

    def test_raises_when_no_core_semver_tag(self) -> None:
        with mock.patch.object(compute, "run_git", lambda args, root: "\n"):
            with self.assertRaises(compute.ComputeError):
                compute.latest_release_tag("/repo")


# ===========================================================================
# Cap guard
# ===========================================================================


class FetchMergedPrsTests(unittest.TestCase):
    def test_raises_when_pr_list_cap_hit(self) -> None:
        rows = [_row(n, ["release: patch"], f"oid{n}") for n in range(compute.PR_LIST_LIMIT)]
        payload = json.dumps(rows)
        with mock.patch.object(compute, "run_gh", lambda args, root: payload):
            with self.assertRaises(compute.ComputeError):
                compute.fetch_merged_prs("/repo", "2026-05-22")

    def test_raises_on_non_object_row(self) -> None:
        payload = json.dumps(["not-an-object"])
        with mock.patch.object(compute, "run_gh", lambda args, root: payload):
            with self.assertRaises(compute.ComputeError):
                compute.fetch_merged_prs("/repo", "2026-05-22")

    def test_raises_on_null_labels(self) -> None:
        payload = json.dumps(
            [{"number": 1, "title": "t", "labels": None, "mergeCommit": {"oid": "a"}}]
        )
        with mock.patch.object(compute, "run_gh", lambda args, root: payload):
            with self.assertRaises(compute.ComputeError):
                compute.fetch_merged_prs("/repo", "2026-05-22")

    def test_raises_on_missing_number(self) -> None:
        payload = json.dumps([{"title": "t", "labels": [], "mergeCommit": {"oid": "a"}}])
        with mock.patch.object(compute, "run_gh", lambda args, root: payload):
            with self.assertRaises(compute.ComputeError):
                compute.fetch_merged_prs("/repo", "2026-05-22")


# ===========================================================================
# Orchestration (main)
# ===========================================================================


def _fake_git(
    tag_list: str, revlist: str, date: str = "2026-05-22\n"
) -> Callable[[list[str], str], str]:
    def fake(args: list[str], repo_root: str) -> str:
        if args[:2] == ["tag", "-l"]:
            return tag_list
        if args[:1] == ["log"]:
            return date
        if args[:1] == ["rev-list"]:
            return revlist
        raise AssertionError(f"unexpected git args: {args}")
    return fake


@contextlib.contextmanager
def _run_env(
    *, manifest: str, tag_list: str, revlist: str, gh_rows: list[dict]
) -> Iterator[None]:
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(compute, "find_repo_root", lambda start: "/repo")
        )
        stack.enter_context(
            mock.patch.object(compute, "run_git", _fake_git(tag_list, revlist))
        )
        stack.enter_context(
            mock.patch.object(
                compute, "run_gh", lambda args, root: json.dumps(gh_rows)
            )
        )
        stack.enter_context(
            mock.patch.object(
                compute._version, "read_skill_md_version", lambda path: manifest
            )
        )
        yield


def _invoke() -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = compute.main([])
    return code, out.getvalue(), err.getvalue()


class MainTests(unittest.TestCase):
    def test_happy_path_highest_bump_wins_and_window_filters(self) -> None:
        rows = [
            _row(163, ["release: minor"], "aaa"),
            _row(164, ["release: minor"], "bbb"),
            _row(165, ["release: patch"], "ccc"),
            _row(166, ["release: skip"], "ddd"),
            _row(999, ["release: major"], "zzz"),  # before the tag → ignored
        ]
        with _run_env(
            manifest="1.2.1",
            tag_list="v1.2.0\nv1.2.1\n",
            revlist="aaa\nbbb\nccc\nddd\n",
            gh_rows=rows,
        ):
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_OK)
        self.assertEqual(out.strip(), "1.3.0")
        self.assertIn("#163", err)
        self.assertIn("skipped #166", err)
        self.assertNotIn("999", out)

    def test_drift_manifest_ahead_of_tag_aborts(self) -> None:
        with _run_env(
            manifest="1.3.0",
            tag_list="v1.2.1\n",
            revlist="aaa\n",
            gh_rows=[_row(1, ["release: patch"], "aaa")],
        ):
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_PRECONDITION)
        self.assertEqual(out, "")
        self.assertIn("does not match the latest tag", err)
        self.assertIn("leads the latest tag", err)

    def test_unreadable_manifest_aborts_cleanly(self) -> None:
        def boom(path: str) -> str | None:
            raise OSError("unreadable")

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(compute, "find_repo_root", lambda start: "/repo")
            )
            stack.enter_context(
                mock.patch.object(compute, "run_git", _fake_git("v1.2.1\n", "aaa\n"))
            )
            stack.enter_context(
                mock.patch.object(compute._version, "read_skill_md_version", boom)
            )
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_PRECONDITION)
        self.assertEqual(out, "")
        self.assertIn("SKILL.md", err)

    def test_drift_manifest_behind_tag_aborts(self) -> None:
        with _run_env(
            manifest="1.2.0",
            tag_list="v1.2.1\n",
            revlist="aaa\n",
            gh_rows=[_row(1, ["release: patch"], "aaa")],
        ):
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_PRECONDITION)
        self.assertEqual(out, "")
        self.assertIn("behind the latest tag", err)

    def test_unlabeled_pr_fails_with_add_label_hint(self) -> None:
        with _run_env(
            manifest="1.2.1",
            tag_list="v1.2.1\n",
            revlist="aaa\n",
            gh_rows=[_row(42, [], "aaa")],
        ):
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_LABEL_GAP)
        self.assertEqual(out, "")
        self.assertIn("#42", err)
        self.assertIn("--add-label", err)

    def test_ambiguous_pr_fails_with_remove_label_hint(self) -> None:
        with _run_env(
            manifest="1.2.1",
            tag_list="v1.2.1\n",
            revlist="aaa\n",
            gh_rows=[_row(43, ["release: major", "release: skip"], "aaa")],
        ):
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_LABEL_GAP)
        self.assertEqual(out, "")
        # Concrete, shell-safe: keeps the highest (major), removes the rest quoted.
        self.assertIn('--remove-label "release: skip"', err)
        self.assertNotIn("<all but one", err)

    def test_valid_plus_malformed_label_fails_with_remove_hint(self) -> None:
        with _run_env(
            manifest="1.2.1",
            tag_list="v1.2.1\n",
            revlist="aaa\n",
            gh_rows=[_row(50, ["release: patch", "release: huge"], "aaa")],
        ):
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_LABEL_GAP)
        self.assertEqual(out, "")
        self.assertIn('--remove-label "release: huge"', err)

    def test_only_malformed_label_fails_with_add_hint(self) -> None:
        with _run_env(
            manifest="1.2.1",
            tag_list="v1.2.1\n",
            revlist="aaa\n",
            gh_rows=[_row(51, ["release: huge"], "aaa")],
        ):
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_LABEL_GAP)
        self.assertEqual(out, "")
        self.assertIn('--remove-label "release: huge"', err)
        self.assertIn("--add-label", err)

    def test_empty_window_reports_nothing_to_release(self) -> None:
        with _run_env(
            manifest="1.2.1",
            tag_list="v1.2.1\n",
            revlist="",
            gh_rows=[],
        ):
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_NOTHING)
        self.assertEqual(out, "")
        self.assertIn("no PRs merged", err)

    def test_all_skip_reports_nothing_user_facing(self) -> None:
        with _run_env(
            manifest="1.2.1",
            tag_list="v1.2.1\n",
            revlist="aaa\nbbb\n",
            gh_rows=[
                _row(1, ["release: skip"], "aaa"),
                _row(2, ["release: skip"], "bbb"),
            ],
        ):
            code, out, err = _invoke()
        self.assertEqual(code, compute.EXIT_NOTHING)
        self.assertEqual(out, "")
        self.assertIn("release: skip", err)


if __name__ == "__main__":
    unittest.main()
