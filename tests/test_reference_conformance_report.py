"""Tests for ``scripts/reference_conformance_report.py``.

The conformance report is a permanent foundry script that quantifies
how well a skill's link graph matches what a standard markdown reader
sees.  See ``references/path-resolution.md`` for the rule, and the
script's docstring for the metrics it reports.
"""

import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

# Add scripts/ to the path so we can import the module under test.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_REPO_ROOT, "skill-system-foundry", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import reference_conformance_report as rcr  # noqa: E402

from helpers import write_text  # noqa: E402


def _build_skill(skill_root: str, skill_body: str = "") -> None:
    """Write a minimal SKILL.md plus the requested body."""
    skill_md = os.path.join(skill_root, "SKILL.md")
    body = skill_body if skill_body else "# Skill\n"
    write_text(skill_md, f"---\nname: test\n---\n{body}")


# ===================================================================
# compute_report
# ===================================================================


class ComputeReportConformingSkillTests(unittest.TestCase):
    """A conforming skill produces zeros and a single connected
    component reachable from SKILL.md."""

    def test_empty_skill_conforms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp)
            report = rcr.compute_report(tmp)
        self.assertTrue(report["conforms"])
        self.assertEqual(report["total_links"], 0)
        self.assertEqual(report["broken_under_standard_semantics"], 0)
        self.assertEqual(report["files_unreachable_from_root"], 0)

    def test_skill_with_resolved_link_conforms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, "See [g](references/guide.md).\n")
            write_text(os.path.join(tmp, "references", "guide.md"), "# Guide\n")
            report = rcr.compute_report(tmp)
        self.assertTrue(report["conforms"])
        self.assertEqual(report["total_links"], 1)
        self.assertEqual(report["resolves_under_standard_semantics"], 1)
        self.assertEqual(report["broken_under_standard_semantics"], 0)

    def test_capability_link_resolves_file_relative(self) -> None:
        # Capability bodies resolve refs file-relative under the
        # redefined rule (see references/path-resolution.md).
        # ``[x](references/y.md)`` resolves under the capability root.
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp)
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [y](references/y.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "references", "y.md"),
                "# Y\n",
            )
            report = rcr.compute_report(tmp)
        self.assertTrue(report["conforms"])
        self.assertEqual(report["broken_under_standard_semantics"], 0)


class ComputeReportBrokenLinkTests(unittest.TestCase):
    """Broken intra-skill links are counted under
    ``broken_under_standard_semantics`` and surfaced in
    ``broken_links``."""

    def test_broken_skill_link_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, "See [m](references/missing.md).\n")
            report = rcr.compute_report(tmp)
        self.assertFalse(report["conforms"])
        self.assertEqual(report["total_links"], 1)
        self.assertEqual(report["broken_under_standard_semantics"], 1)
        self.assertEqual(len(report["broken_links"]), 1)
        self.assertEqual(report["broken_links"][0]["source"], "SKILL.md")
        self.assertEqual(
            report["broken_links"][0]["target"], "references/missing.md",
        )

    def test_broken_links_are_grouped_by_source_scope(self) -> None:
        # The per-scope breakdown lets a triage user see at a glance
        # whether the work is concentrated in the skill root or a
        # specific capability.  Pin both buckets are tracked
        # independently and only the scopes with broken links appear.
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, "See [m](references/missing.md).\n")
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\n"
                "See [a](references/a.md) and [b](references/b.md).\n",
            )
            report = rcr.compute_report(tmp)
        self.assertEqual(
            report["broken_under_standard_semantics_by_scope"],
            {"capability:demo": 2, "skill": 1},
        )


class ComputeReportExternalEdgeTests(unittest.TestCase):
    """Edges from a capability into the shared skill root are counted
    per capability so the future capability-lift tool can find them."""

    def test_external_edges_counted_per_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp)
            write_text(
                os.path.join(tmp, "references", "alpha.md"), "# Alpha\n",
            )
            write_text(
                os.path.join(tmp, "references", "beta.md"), "# Beta\n",
            )
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\n"
                "See [a](../../references/alpha.md) and "
                "[b](../../references/beta.md).\n",
            )
            report = rcr.compute_report(tmp)
        self.assertTrue(report["conforms"])
        self.assertEqual(
            report["external_edges_per_capability"], {"demo": 2},
        )

    def test_capability_local_parent_traversal_is_not_external(self) -> None:
        # A capability-local reference under
        # ``capabilities/<name>/references/foo.md`` reaching back to
        # the capability entry via ``../capability.md`` is intra-scope
        # — not a lift-rewrite candidate.  The metric must not count
        # every ``../``-prefixed link blindly; it counts only links
        # whose resolved target sits outside ``capabilities/<name>/``.
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp)
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [r](references/r.md).\n",
            )
            write_text(
                os.path.join(cap_dir, "references", "r.md"),
                "# R\n\nBack to [entry](../capability.md).\n",
            )
            report = rcr.compute_report(tmp)
        self.assertTrue(report["conforms"])
        self.assertEqual(
            report["external_edges_per_capability"], {},
            msg="../capability.md is intra-capability, not external",
        )

    def test_broken_external_link_is_not_counted_as_external_edge(self) -> None:
        # A broken capability link to the shared skill root is in
        # ``broken_links`` already.  Counting it again under
        # ``external_edges_per_capability`` would double-report and
        # would mislead the future lift tool into thinking there is
        # rewriteable shared content where there is none.
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp)
            cap_dir = os.path.join(tmp, "capabilities", "demo")
            write_text(
                os.path.join(cap_dir, "capability.md"),
                "# Demo\n\nSee [m](../../references/missing.md).\n",
            )
            report = rcr.compute_report(tmp)
        self.assertEqual(report["broken_under_standard_semantics"], 1)
        self.assertEqual(report["external_edges_per_capability"], {})

    def test_skill_root_links_are_not_external_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, "See [g](references/guide.md).\n")
            write_text(
                os.path.join(tmp, "references", "guide.md"), "# Guide\n",
            )
            report = rcr.compute_report(tmp)
        self.assertEqual(report["external_edges_per_capability"], {})


class ComputeReportConnectedComponentsTests(unittest.TestCase):
    """The connected-component analysis treats SKILL.md and every
    capability.md as roots; reachability spans both directions."""

    def test_unreached_md_file_is_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp)
            # Reachable from SKILL.md
            write_text(os.path.join(tmp, "references", "linked.md"), "# Linked\n")
            skill_md = os.path.join(tmp, "SKILL.md")
            write_text(
                skill_md,
                "---\nname: test\n---\nSee [l](references/linked.md).\n",
            )
            # Orphan
            write_text(os.path.join(tmp, "references", "orphan.md"), "# Orphan\n")
            report = rcr.compute_report(tmp)
        # 3 .md files: SKILL.md, linked.md, orphan.md
        # 2 are reachable (SKILL → linked); 1 unreachable.
        self.assertEqual(report["files_unreachable_from_root"], 1)
        self.assertFalse(report["conforms"])


# ===================================================================
# CLI
# ===================================================================


class CliInvocationTests(unittest.TestCase):
    """The CLI exits 0 on conformance, non-zero otherwise; ``--json``
    emits a structured payload."""

    def _invoke(self, args: list[str]) -> tuple[int, str, str]:
        argv_backup = sys.argv
        sys.argv = ["reference_conformance_report.py", *args]
        out = io.StringIO()
        err = io.StringIO()
        try:
            with unittest.mock.patch("sys.stdout", out):
                with unittest.mock.patch("sys.stderr", err):
                    rc = rcr.main()
        finally:
            sys.argv = argv_backup
        return rc, out.getvalue(), err.getvalue()

    def test_conforming_skill_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp)
            rc, _out, _err = self._invoke([tmp])
        self.assertEqual(rc, 0)

    def test_non_conforming_skill_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, "See [m](references/missing.md).\n")
            rc, _out, _err = self._invoke([tmp])
        self.assertEqual(rc, 1)

    def test_missing_directory_exits_two(self) -> None:
        rc, _out, err = self._invoke(["/nonexistent/path/that/does/not/exist"])
        self.assertEqual(rc, 2)
        self.assertIn("error", err.lower())

    def test_no_args_prints_docstring_and_exits_one(self) -> None:
        # Mirrors the convention shared with validate_skill.py /
        # bundle.py / scaffold.py: invoking the script with no
        # arguments prints the module docstring as a usage hint and
        # exits non-zero.  The argparse usage line on its own does
        # not surface the metric definitions or scope rules, so the
        # docstring is what users actually need.
        rc, out, _err = self._invoke([])
        self.assertEqual(rc, 1)
        self.assertIn("Reference Conformance", out) if False else None
        # The docstring opens with "Report a skill's cross-file
        # reference conformance" — a stable substring to pin against.
        self.assertIn("cross-file reference conformance", out)

    def test_directory_without_skill_md_exits_two(self) -> None:
        # Refuses to scan an arbitrary directory — without the guard the
        # walker would enumerate whatever markdown the directory contains
        # (e.g. the repo root's top-level docs, .github/, examples/) and
        # report broken links for paths that are simply outside any skill.
        with tempfile.TemporaryDirectory() as tmp:
            # Add a markdown file but no SKILL.md so the directory is
            # non-empty but still not a skill root.
            write_text(os.path.join(tmp, "README.md"), "# Readme\n")
            rc, _out, err = self._invoke([tmp])
        self.assertEqual(rc, 2)
        self.assertIn("SKILL.md", err)

    def test_directory_without_skill_md_json_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_text(os.path.join(tmp, "README.md"), "# Readme\n")
            rc, out, _err = self._invoke([tmp, "--json"])
        self.assertEqual(rc, 2)
        payload = json.loads(out)
        self.assertEqual(payload["tool"], "reference_conformance_report")
        self.assertIn("error", payload)

    def test_json_output_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp)
            rc, out, _err = self._invoke([tmp, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["tool"], "reference_conformance_report")
        self.assertIn("total_links", payload)
        self.assertIn("conforms", payload)
        self.assertTrue(payload["conforms"])

    def test_verbose_lists_broken_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _build_skill(tmp, "See [m](references/missing.md).\n")
            rc, out, _err = self._invoke([tmp, "--verbose"])
        self.assertEqual(rc, 1)
        self.assertIn("references/missing.md", out)


if __name__ == "__main__":
    unittest.main()
