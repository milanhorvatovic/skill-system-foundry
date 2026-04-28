"""Tests for .github/scripts/validate-examples.py.

Covers ``discover_skill_dirs`` (only directories with SKILL.md, hidden
entries skipped, missing root tolerated, sorted output), ``validate_one``
(success, failure with empty stdout, invalid JSON, non-zero exit code
treated as failure), ``format_verdict`` (success and failure rendering,
missing JSON), ``run_validation`` (aggregates, ``all_success`` flag), and
``main`` integration against the real ``validate_skill.py`` (happy path,
missing validator, missing examples, sibling roles directory ignored).
"""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import textwrap
import unittest
from unittest import mock


_CI_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".github", "scripts"),
)
_script_path = os.path.join(_CI_SCRIPTS_DIR, "validate-examples.py")
_spec = importlib.util.spec_from_file_location(
    "validate_examples", _script_path,
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load module from {_script_path}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
discover_skill_dirs = _mod.discover_skill_dirs
discover_capability_dirs = _mod.discover_capability_dirs
find_malformed_skill_dirs = _mod.find_malformed_skill_dirs
find_malformed_capability_dirs = _mod.find_malformed_capability_dirs
validate_one = _mod.validate_one
format_verdict = _mod.format_verdict
run_validation = _mod.run_validation
main = _mod.main


_REAL_VALIDATOR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "skill-system-foundry",
        "scripts",
        "validate_skill.py",
    )
)


# ===================================================================
# Helpers
# ===================================================================


def _write(path: str, content: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _write_minimal_skill(skill_dir: str, *, name: str) -> None:
    """Create a minimal valid skill at *skill_dir* with directory name *name*."""
    description = (
        "Greets a single recipient with a one-line message. "
        "Test fixture used by the validate-examples CI helper. "
        "Activates only when the conversation explicitly asks for a hello."
    )
    content = textwrap.dedent(
        f"""\
        ---
        name: {name}
        description: >
          {description}
        ---

        # Test Skill

        ## Purpose

        Reference fixture only.

        ## Instructions

        1. Emit a greeting.
        """
    )
    _write(os.path.join(skill_dir, "SKILL.md"), content)


# ===================================================================
# discover_skill_dirs
# ===================================================================


class DiscoverSkillDirsTests(unittest.TestCase):

    def test_returns_only_directories_with_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "with-skill"))
            _write(os.path.join(root, "with-skill", "SKILL.md"), "stub")
            os.makedirs(os.path.join(root, "no-skill"))
            _write(os.path.join(root, "loose-file.txt"), "stub")
            found = discover_skill_dirs(root)
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].endswith("with-skill"))

    def test_skips_hidden_directories(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".hidden"))
            _write(os.path.join(root, ".hidden", "SKILL.md"), "stub")
            self.assertEqual(discover_skill_dirs(root), [])

    def test_missing_root_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, "does-not-exist")
            self.assertEqual(discover_skill_dirs(missing), [])

    def test_results_are_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            for name in ("zebra", "alpha", "mike"):
                os.makedirs(os.path.join(root, name))
                _write(os.path.join(root, name, "SKILL.md"), "stub")
            found = discover_skill_dirs(root)
            self.assertEqual(
                [os.path.basename(p) for p in found],
                ["alpha", "mike", "zebra"],
            )


# ===================================================================
# discover_capability_dirs
# ===================================================================


class DiscoverCapabilityDirsTests(unittest.TestCase):

    def test_returns_capability_dirs_with_capability_md(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            cap = os.path.join(root, "capabilities", "alpha")
            os.makedirs(cap)
            _write(os.path.join(cap, "capability.md"), "stub")
            other = os.path.join(root, "capabilities", "no-cap")
            os.makedirs(other)
            found = discover_capability_dirs(root)
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].endswith("alpha"))

    def test_no_capabilities_subtree_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(discover_capability_dirs(root), [])

    def test_skips_hidden_and_loose_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "capabilities", ".hidden"))
            _write(
                os.path.join(root, "capabilities", ".hidden", "capability.md"),
                "stub",
            )
            _write(os.path.join(root, "capabilities", "loose.md"), "stub")
            self.assertEqual(discover_capability_dirs(root), [])

    def test_results_are_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            for name in ("zulu", "alpha", "mike"):
                cap = os.path.join(root, "capabilities", name)
                os.makedirs(cap)
                _write(os.path.join(cap, "capability.md"), "stub")
            found = discover_capability_dirs(root)
            self.assertEqual(
                [os.path.basename(p) for p in found],
                ["alpha", "mike", "zulu"],
            )


# ===================================================================
# find_malformed_skill_dirs
# ===================================================================


class FindMalformedSkillDirsTests(unittest.TestCase):

    def test_returns_directories_missing_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "with-skill"))
            _write(os.path.join(root, "with-skill", "SKILL.md"), "stub")
            os.makedirs(os.path.join(root, "broken"))
            malformed = find_malformed_skill_dirs(root)
            self.assertEqual(len(malformed), 1)
            self.assertTrue(malformed[0].endswith("broken"))

    def test_skips_hidden_and_loose_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".hidden"))
            _write(os.path.join(root, "loose.txt"), "stub")
            self.assertEqual(find_malformed_skill_dirs(root), [])

    def test_missing_root_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, "does-not-exist")
            self.assertEqual(find_malformed_skill_dirs(missing), [])

    def test_returns_empty_when_every_child_has_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            for name in ("alpha", "bravo"):
                os.makedirs(os.path.join(root, name))
                _write(os.path.join(root, name, "SKILL.md"), "stub")
            self.assertEqual(find_malformed_skill_dirs(root), [])


# ===================================================================
# find_malformed_capability_dirs
# ===================================================================


class FindMalformedCapabilityDirsTests(unittest.TestCase):

    def test_returns_capability_dirs_missing_capability_md(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            valid = os.path.join(root, "capabilities", "ok")
            os.makedirs(valid)
            _write(os.path.join(valid, "capability.md"), "stub")
            broken = os.path.join(root, "capabilities", "broken")
            os.makedirs(broken)
            malformed = find_malformed_capability_dirs(root)
            self.assertEqual(len(malformed), 1)
            self.assertTrue(malformed[0].endswith("broken"))

    def test_returns_empty_without_capabilities_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(find_malformed_capability_dirs(root), [])

    def test_skips_hidden_and_loose_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "capabilities", ".hidden"))
            _write(os.path.join(root, "capabilities", "loose.md"), "stub")
            self.assertEqual(find_malformed_capability_dirs(root), [])


# ===================================================================
# validate_one
# ===================================================================


class _FakeCompleted:

    def __init__(
        self, stdout: str, returncode: int = 0, stderr: str = "",
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class ValidateOneTests(unittest.TestCase):

    def test_success_path(self) -> None:
        payload = {
            "tool": "validate_skill",
            "success": True,
            "summary": {"failures": 0, "warnings": 0, "info": 0, "passes": 5},
        }
        fake = _FakeCompleted(json.dumps(payload), returncode=0)
        with mock.patch.object(_mod.subprocess, "run", return_value=fake):
            success, parsed, raw, stderr = validate_one(
                "/tmp/skill", "/tmp/v.py",
            )
        self.assertTrue(success)
        self.assertEqual(parsed["summary"]["failures"], 0)
        self.assertIn("validate_skill", raw)
        self.assertEqual(stderr, "")

    def test_failure_payload_marks_unsuccessful(self) -> None:
        payload = {
            "tool": "validate_skill",
            "success": False,
            "summary": {"failures": 2, "warnings": 0, "info": 0, "passes": 3},
            "errors": {"failures": ["bad thing"], "warnings": [], "info": []},
        }
        fake = _FakeCompleted(json.dumps(payload), returncode=1)
        with mock.patch.object(_mod.subprocess, "run", return_value=fake):
            success, parsed, _, _ = validate_one("/tmp/skill", "/tmp/v.py")
        self.assertFalse(success)
        self.assertEqual(parsed["summary"]["failures"], 2)

    def test_warnings_count_as_failure(self) -> None:
        # ``errors.warnings`` entries are stored prefix-free in the real
        # validator's --json output; the helper's main() loop is what
        # prepends the ``WARN: `` label.
        payload = {
            "tool": "validate_skill",
            "success": True,
            "summary": {"failures": 0, "warnings": 1, "info": 0, "passes": 4},
            "errors": {"failures": [], "warnings": ["drift"], "info": []},
        }
        fake = _FakeCompleted(json.dumps(payload), returncode=0)
        with mock.patch.object(_mod.subprocess, "run", return_value=fake):
            success, _, _, _ = validate_one("/tmp/skill", "/tmp/v.py")
        self.assertFalse(success)

    def test_info_findings_count_as_failure(self) -> None:
        payload = {
            "tool": "validate_skill",
            "success": True,
            "summary": {"failures": 0, "warnings": 0, "info": 1, "passes": 4},
            "errors": {"failures": [], "warnings": [], "info": ["nit"]},
        }
        fake = _FakeCompleted(json.dumps(payload), returncode=0)
        with mock.patch.object(_mod.subprocess, "run", return_value=fake):
            success, _, _, _ = validate_one("/tmp/skill", "/tmp/v.py")
        self.assertFalse(success)

    def test_invalid_json_returns_none_and_captures_stderr(self) -> None:
        fake = _FakeCompleted(
            "not-json-at-all", returncode=0, stderr="boom",
        )
        with mock.patch.object(_mod.subprocess, "run", return_value=fake):
            success, parsed, raw, stderr = validate_one(
                "/tmp/skill", "/tmp/v.py",
            )
        self.assertFalse(success)
        self.assertIsNone(parsed)
        self.assertEqual(raw, "not-json-at-all")
        self.assertEqual(stderr, "boom")

    def test_empty_stdout_returns_none(self) -> None:
        fake = _FakeCompleted("", returncode=1, stderr="trace")
        with mock.patch.object(_mod.subprocess, "run", return_value=fake):
            success, parsed, _, stderr = validate_one(
                "/tmp/skill", "/tmp/v.py",
            )
        self.assertFalse(success)
        self.assertIsNone(parsed)
        self.assertEqual(stderr, "trace")

    def test_returncode_nonzero_overrides_success_flag(self) -> None:
        payload = {
            "tool": "validate_skill",
            "success": True,
            "summary": {"failures": 0, "warnings": 0, "info": 0, "passes": 1},
        }
        fake = _FakeCompleted(json.dumps(payload), returncode=2)
        with mock.patch.object(_mod.subprocess, "run", return_value=fake):
            success, _, _, _ = validate_one("/tmp/skill", "/tmp/v.py")
        self.assertFalse(success)

    def test_capability_flag_is_passed_to_subprocess(self) -> None:
        # When capability=True the helper must add ``--capability`` so the
        # validator looks for capability.md instead of SKILL.md.
        captured: dict[str, list[str]] = {}

        def _fake_run(cmd: list[str], **kwargs: object) -> _FakeCompleted:
            captured["cmd"] = list(cmd)
            payload = {
                "tool": "validate_skill",
                "success": True,
                "summary": {"failures": 0, "warnings": 0, "info": 0, "passes": 1},
            }
            return _FakeCompleted(json.dumps(payload), returncode=0)

        with mock.patch.object(_mod.subprocess, "run", side_effect=_fake_run):
            success, _, _, _ = validate_one(
                "/tmp/cap", "/tmp/v.py", capability=True,
            )
        self.assertTrue(success)
        self.assertIn("--capability", captured["cmd"])
        # Skill mode (default) must not include the flag.
        with mock.patch.object(_mod.subprocess, "run", side_effect=_fake_run):
            validate_one("/tmp/skill", "/tmp/v.py")
        self.assertNotIn("--capability", captured["cmd"])


# ===================================================================
# format_verdict
# ===================================================================


class FormatVerdictTests(unittest.TestCase):

    def test_success_renders_check_mark(self) -> None:
        payload = {
            "success": True,
            "summary": {"failures": 0, "warnings": 0, "info": 0},
        }
        line = format_verdict("/tmp/skills/alpha", payload, success=True)
        self.assertIn("alpha", line)
        self.assertIn("0 fail / 0 warn / 0 info", line)
        self.assertIn("✓", line)

    def test_failure_renders_cross_mark(self) -> None:
        payload = {
            "success": False,
            "summary": {"failures": 1, "warnings": 0, "info": 0},
        }
        line = format_verdict("/tmp/skills/alpha", payload, success=False)
        self.assertIn("✗", line)
        self.assertIn("1 fail", line)

    def test_warning_only_renders_cross_mark_when_success_false(self) -> None:
        payload = {
            "success": True,
            "summary": {"failures": 0, "warnings": 1, "info": 0},
        }
        line = format_verdict("/tmp/skills/alpha", payload, success=False)
        self.assertIn("✗", line)
        self.assertIn("1 warn", line)

    def test_missing_payload_renders_explanation(self) -> None:
        line = format_verdict("/tmp/skills/alpha", None, success=False)
        self.assertIn("alpha", line)
        self.assertIn("no valid JSON output", line)

    def test_capability_kind_renders_with_indent_and_prefix(self) -> None:
        payload = {
            "success": True,
            "summary": {"failures": 0, "warnings": 0, "info": 0},
        }
        line = format_verdict(
            "/tmp/skills/router/capabilities/do-thing",
            payload,
            success=True,
            kind="capability",
        )
        self.assertIn("└─", line)
        self.assertIn("capabilities/do-thing", line)
        self.assertTrue(line.startswith("    "))

    def test_top_level_error_field_surfaces_in_verdict(self) -> None:
        # Early-exit JSON payloads from validate_skill.py omit the
        # ``summary`` object and emit a top-level ``error`` instead. The
        # verdict must surface that message rather than print misleading
        # zero counts.
        payload = {
            "tool": "validate_skill",
            "success": False,
            "error": "'/no/such' is not a directory",
        }
        line = format_verdict("/tmp/skills/alpha", payload, success=False)
        self.assertIn("✗", line)
        self.assertIn("validator error:", line)
        self.assertIn("not a directory", line)
        self.assertNotIn("0 fail", line)


# ===================================================================
# run_validation
# ===================================================================


class RunValidationTests(unittest.TestCase):

    def test_all_success_when_every_skill_passes(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _write_minimal_skill(os.path.join(root, "alpha"), name="alpha")
            _write_minimal_skill(os.path.join(root, "bravo"), name="bravo")
            results, all_ok = run_validation(root, _REAL_VALIDATOR)
        self.assertTrue(all_ok)
        self.assertEqual(len(results), 2)
        for _, kind, success, _, _, _ in results:
            self.assertEqual(kind, "skill")
            self.assertTrue(success)

    def test_all_success_false_when_one_skill_fails(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _write_minimal_skill(os.path.join(root, "alpha"), name="alpha")
            broken_dir = os.path.join(root, "broken")
            os.makedirs(broken_dir)
            # SKILL.md exists but frontmatter is missing — guaranteed FAIL.
            _write(os.path.join(broken_dir, "SKILL.md"), "# Broken\n")
            results, all_ok = run_validation(root, _REAL_VALIDATOR)
        self.assertFalse(all_ok)
        self.assertEqual(len(results), 2)
        labels = {os.path.basename(r[0]): r[2] for r in results}
        self.assertTrue(labels["alpha"])
        self.assertFalse(labels["broken"])

    def test_router_capabilities_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            router_dir = os.path.join(root, "router")
            _write_minimal_skill(router_dir, name="router")
            cap_dir = os.path.join(router_dir, "capabilities", "do-thing")
            os.makedirs(cap_dir)
            _write(
                os.path.join(cap_dir, "capability.md"),
                textwrap.dedent(
                    """\
                    ---
                    description: >
                      Renders one greeting line. Use when a friendly
                      greeting is requested with a recipient name.
                    ---
                    # Do Thing

                    ## Purpose

                    Test capability fixture.

                    ## Instructions

                    1. Emit a greeting.
                    """,
                ),
            )
            results, all_ok = run_validation(root, _REAL_VALIDATOR)
        self.assertTrue(all_ok)
        self.assertEqual(len(results), 2)
        kinds = [r[1] for r in results]
        self.assertEqual(kinds, ["skill", "capability"])
        # Capability row immediately follows its parent skill.
        self.assertTrue(results[0][0].endswith("router"))
        self.assertTrue(results[1][0].endswith("do-thing"))

    def test_broken_capability_fails_aggregate(self) -> None:
        # Use a mocked validator: capability validation is lenient about
        # missing frontmatter (it's optional), so the deterministic way
        # to exercise the aggregate-fail-on-capability path is to inject
        # a failing JSON payload for the capability call only.
        skill_payload = {
            "tool": "validate_skill",
            "success": True,
            "summary": {"failures": 0, "warnings": 0, "info": 0, "passes": 5},
        }
        cap_payload = {
            "tool": "validate_skill",
            "success": False,
            "summary": {"failures": 1, "warnings": 0, "info": 0, "passes": 0},
            "errors": {
                "failures": ["body exceeds line cap"],
                "warnings": [],
                "info": [],
            },
        }
        side_effect = [
            _FakeCompleted(json.dumps(skill_payload), returncode=0),
            _FakeCompleted(json.dumps(cap_payload), returncode=1),
        ]
        with tempfile.TemporaryDirectory() as root:
            router_dir = os.path.join(root, "router")
            os.makedirs(router_dir)
            _write(os.path.join(router_dir, "SKILL.md"), "stub")
            cap_dir = os.path.join(router_dir, "capabilities", "broken")
            os.makedirs(cap_dir)
            _write(os.path.join(cap_dir, "capability.md"), "stub")
            with mock.patch.object(
                _mod.subprocess, "run", side_effect=side_effect,
            ):
                results, all_ok = run_validation(root, _REAL_VALIDATOR)
        self.assertFalse(all_ok)
        self.assertEqual(len(results), 2)
        skill_row = next(r for r in results if r[1] == "skill")
        cap_row = next(r for r in results if r[1] == "capability")
        self.assertTrue(skill_row[2])
        self.assertFalse(cap_row[2])


# ===================================================================
# main
# ===================================================================


class MainTests(unittest.TestCase):

    def test_happy_path_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            skills_root = os.path.join(root, "skills")
            os.makedirs(skills_root)
            _write_minimal_skill(
                os.path.join(skills_root, "alpha"), name="alpha",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main([
                    "--skills-root", skills_root,
                    "--validator", _REAL_VALIDATOR,
                ])
        self.assertEqual(rc, 0)

    def test_missing_validator_returns_one(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            skills_root = os.path.join(root, "skills")
            os.makedirs(skills_root)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = main([
                    "--skills-root", skills_root,
                    "--validator", os.path.join(root, "no-such-validator.py"),
                ])
        self.assertEqual(rc, 1)
        self.assertIn("validator not found", stderr.getvalue())

    def test_no_skills_returns_one(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            empty_root = os.path.join(root, "skills")
            os.makedirs(empty_root)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = main([
                    "--skills-root", empty_root,
                    "--validator", _REAL_VALIDATOR,
                ])
        self.assertEqual(rc, 1)
        self.assertIn("no example skills found", stderr.getvalue())

    def test_sibling_roles_directory_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            skills_root = os.path.join(root, "skills")
            roles_root = os.path.join(root, "roles")
            os.makedirs(skills_root)
            os.makedirs(roles_root)
            _write_minimal_skill(
                os.path.join(skills_root, "alpha"), name="alpha",
            )
            # A loose markdown file that would FAIL if validated as a skill.
            _write(os.path.join(roles_root, "some-role.md"), "# Role\n")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main([
                    "--skills-root", skills_root,
                    "--validator", _REAL_VALIDATOR,
                ])
        # roles/ is outside skills_root, so the helper never sees it and
        # the run succeeds.
        self.assertEqual(rc, 0)

    def test_main_reports_failure_when_skill_breaks(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            skills_root = os.path.join(root, "skills")
            broken_dir = os.path.join(skills_root, "broken")
            os.makedirs(broken_dir)
            _write(os.path.join(broken_dir, "SKILL.md"), "# Broken\n")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main([
                    "--skills-root", skills_root,
                    "--validator", _REAL_VALIDATOR,
                ])
        self.assertEqual(rc, 1)

    def test_main_fails_fast_on_malformed_capability_dir(self) -> None:
        # A non-hidden capabilities/<name>/ directory missing
        # capability.md must fail the run before validation begins,
        # mirroring the SKILL.md-level guard.
        with tempfile.TemporaryDirectory() as root:
            skills_root = os.path.join(root, "skills")
            os.makedirs(skills_root)
            router_dir = os.path.join(skills_root, "router")
            _write_minimal_skill(router_dir, name="router")
            os.makedirs(os.path.join(router_dir, "capabilities", "broken-cap"))
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), \
                 contextlib.redirect_stderr(stderr):
                rc = main([
                    "--skills-root", skills_root,
                    "--validator", _REAL_VALIDATOR,
                ])
        self.assertEqual(rc, 1)
        err = stderr.getvalue()
        self.assertIn("malformed example capability directories", err)
        self.assertIn("broken-cap", err)
        self.assertIn("missing capability.md", err)

    def test_main_fails_fast_on_malformed_skill_dir(self) -> None:
        # A non-hidden child directory missing SKILL.md must fail the run
        # rather than silently disappear from CI's view. A real example
        # alongside it must not rescue the build.
        with tempfile.TemporaryDirectory() as root:
            skills_root = os.path.join(root, "skills")
            os.makedirs(skills_root)
            _write_minimal_skill(
                os.path.join(skills_root, "alpha"), name="alpha",
            )
            os.makedirs(os.path.join(skills_root, "broken-no-skill-md"))
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), \
                 contextlib.redirect_stderr(stderr):
                rc = main([
                    "--skills-root", skills_root,
                    "--validator", _REAL_VALIDATOR,
                ])
        self.assertEqual(rc, 1)
        err = stderr.getvalue()
        self.assertIn("malformed example skill directories", err)
        self.assertIn("broken-no-skill-md", err)
        self.assertIn("missing SKILL.md", err)

    def test_main_prints_warn_info_and_stderr_lines(self) -> None:
        # Three skills under skills_root, exercising every diagnostic
        # branch in main():
        #   * alpha — clean payload but non-zero return code, plus
        #     non-empty stderr; helper must print the stderr even though
        #     stdout was valid JSON.
        #   * bravo — top-level ``error`` field on an early-exit payload.
        #   * charlie — invalid JSON on stdout and a traceback on stderr.
        # Fixture strings for ``errors.*`` are prefix-free, matching the
        # real validator's --json schema.
        warn_payload = {
            "tool": "validate_skill",
            "success": True,
            "summary": {"failures": 0, "warnings": 1, "info": 1, "passes": 1},
            "errors": {
                "failures": [],
                "warnings": ["drift"],
                "info": ["nit"],
            },
        }
        early_exit_payload = {
            "tool": "validate_skill",
            "success": False,
            "error": "'/no/such' is not a directory",
        }
        side_effect = [
            _FakeCompleted(
                json.dumps(warn_payload), returncode=2, stderr="env-warn",
            ),
            _FakeCompleted(json.dumps(early_exit_payload), returncode=1),
            _FakeCompleted("not-json", returncode=2, stderr="trace"),
        ]
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            skills_root = os.path.join(root, "skills")
            for label in ("alpha", "bravo", "charlie"):
                os.makedirs(os.path.join(skills_root, label))
                _write(os.path.join(skills_root, label, "SKILL.md"), "stub")
            with mock.patch.object(
                _mod.subprocess, "run", side_effect=side_effect,
            ), contextlib.redirect_stdout(stdout):
                rc = main([
                    "--skills-root", skills_root,
                    "--validator", _REAL_VALIDATOR,
                ])

        out = stdout.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("WARN: drift", out)
        self.assertIn("INFO: nit", out)
        self.assertIn("raw stderr: env-warn", out)
        self.assertIn("validator error:", out)
        self.assertIn("not a directory", out)
        self.assertIn("raw stdout: not-json", out)
        self.assertIn("raw stderr: trace", out)


if __name__ == "__main__":
    unittest.main()
