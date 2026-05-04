"""Tests for skill documentation integrity.

Validates cross-reference anchors and Table of Contents consistency
for the skill-system-foundry skill's markdown files.
"""

import os
import re
import unittest


SKILL_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skill-system-foundry")
)

# Markdown files that are part of the skill documentation.
DOCS = {
    "SKILL.md": os.path.join(SKILL_ROOT, "SKILL.md"),
    "references/tool-integration.md": os.path.join(
        SKILL_ROOT, "references", "tool-integration.md"
    ),
    "references/directory-structure.md": os.path.join(
        SKILL_ROOT, "references", "directory-structure.md"
    ),
    "references/architecture-patterns.md": os.path.join(
        SKILL_ROOT, "references", "architecture-patterns.md"
    ),
    "references/anti-patterns.md": os.path.join(
        SKILL_ROOT, "references", "anti-patterns.md"
    ),
    "references/authoring-principles.md": os.path.join(
        SKILL_ROOT, "references", "authoring-principles.md"
    ),
    "references/agentskills-spec.md": os.path.join(
        SKILL_ROOT, "references", "agentskills-spec.md"
    ),
    "references/claude-code-extensions.md": os.path.join(
        SKILL_ROOT, "references", "claude-code-extensions.md"
    ),
    "references/codex-extensions.md": os.path.join(
        SKILL_ROOT, "references", "codex-extensions.md"
    ),
    "references/cursor-extensions.md": os.path.join(
        SKILL_ROOT, "references", "cursor-extensions.md"
    ),
    "capabilities/skill-design/capability.md": os.path.join(
        SKILL_ROOT, "capabilities", "skill-design", "capability.md"
    ),
    "capabilities/validation/capability.md": os.path.join(
        SKILL_ROOT, "capabilities", "validation", "capability.md"
    ),
    "capabilities/migration/capability.md": os.path.join(
        SKILL_ROOT, "capabilities", "migration", "capability.md"
    ),
    "capabilities/bundling/capability.md": os.path.join(
        SKILL_ROOT, "capabilities", "bundling", "capability.md"
    ),
    "capabilities/deployment/capability.md": os.path.join(
        SKILL_ROOT, "capabilities", "deployment", "capability.md"
    ),
    "capabilities/deployment/references/symlink-setup.md": os.path.join(
        SKILL_ROOT, "capabilities", "deployment", "references", "symlink-setup.md"
    ),
}

# ---------- helpers ----------

# Matches markdown links: [text](target) or [text](target "title")
RE_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Matches markdown headings: # Heading, ## Heading, etc.
RE_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Matches ToC entries: - [Display text](#anchor)
RE_TOC_ENTRY = re.compile(r"^-\s+\[([^\]]+)\]\(#([^)]+)\)", re.MULTILINE)

# Matches fenced code blocks (```...``` or ~~~...~~~)
RE_FENCED_CODE_BLOCK = re.compile(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)")


def _heading_to_anchor(heading_text: str) -> str:
    """Convert a markdown heading to its GitHub-style anchor.

    Rules: lowercase, strip non-alphanumeric except hyphens and spaces,
    replace spaces with hyphens, collapse consecutive hyphens.
    """
    text = heading_text.strip()
    # Remove markdown formatting (bold, italic, code, links)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.lower()
    # Keep alphanumeric, spaces, and hyphens only
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text


def _extract_headings(content: str) -> dict[str, str]:
    """Return {anchor: heading_text} for all headings in content."""
    content = RE_FENCED_CODE_BLOCK.sub("", content)
    result = {}
    for match in RE_HEADING.finditer(content):
        heading_text = match.group(2).strip()
        anchor = _heading_to_anchor(heading_text)
        result[anchor] = heading_text
    return result


def _extract_toc_entries(content: str) -> list[tuple[str, str]]:
    """Return [(display_text, anchor), ...] from Table of Contents section."""
    entries = []
    in_toc = False
    for line in content.splitlines():
        # ToC starts after a "## Table of Contents" heading
        if re.match(r"^##\s+Table of Contents", line):
            in_toc = True
            continue
        # ToC ends at the next heading or horizontal rule
        if in_toc and (re.match(r"^#{1,6}\s+", line) or re.match(r"^---", line)):
            break
        if in_toc:
            m = RE_TOC_ENTRY.match(line.strip())
            if m:
                entries.append((m.group(1), m.group(2)))
    return entries


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------- test classes ----------


class AnchorValidationTests(unittest.TestCase):
    """Every markdown link with a #anchor must resolve to an actual heading."""

    def test_all_anchors_resolve(self) -> None:
        failures = []

        for doc_label, doc_path in DOCS.items():
            if not os.path.isfile(doc_path):
                continue
            content = _read(doc_path)
            doc_dir = os.path.dirname(doc_path)

            for match in RE_MD_LINK.finditer(content):
                raw_target = match.group(1).strip()

                # Strip optional title: (path "title")
                raw_target = re.sub(r'\s+"[^"]*"$', "", raw_target)

                # Skip external URLs and pure anchors
                if re.match(r"https?://|mailto:|file:///|<", raw_target):
                    continue

                if "#" not in raw_target:
                    continue

                parts = raw_target.split("#", 1)
                file_part = parts[0]
                anchor = parts[1]

                if not anchor:
                    continue

                # Determine which file the anchor should be in.
                # All paths resolve from SKILL_ROOT per agentskills.io
                # spec (skill-root-relative, no parent traversals).
                if file_part:
                    target_path = os.path.normpath(
                        os.path.join(SKILL_ROOT, file_part)
                    )
                else:
                    # Self-reference: #anchor within the same file
                    target_path = doc_path

                if not os.path.isfile(target_path):
                    # Missing file — not this test's concern (validate_skill
                    # handles that). Skip.
                    continue

                target_content = _read(target_path)
                headings = _extract_headings(target_content)

                if anchor not in headings:
                    target_label = os.path.relpath(target_path, SKILL_ROOT)
                    failures.append(
                        f"  {doc_label}: anchor '#{anchor}' not found in "
                        f"{target_label} (available: "
                        f"{', '.join(sorted(headings.keys())[:5])}...)"
                    )

        if failures:
            self.fail(
                f"Broken anchors found ({len(failures)}):\n"
                + "\n".join(failures)
            )


class TocConsistencyTests(unittest.TestCase):
    """ToC entries must match actual headings (bidirectional)."""

    # Files that have an explicit Table of Contents section.
    TOC_FILES = [
        ("references/tool-integration.md", DOCS["references/tool-integration.md"]),
        (
            "references/directory-structure.md",
            DOCS["references/directory-structure.md"],
        ),
        (
            "references/architecture-patterns.md",
            DOCS["references/architecture-patterns.md"],
        ),
    ]

    def test_toc_entries_have_matching_headings(self) -> None:
        """Every ToC entry must correspond to an actual heading."""
        failures = []

        for doc_label, doc_path in self.TOC_FILES:
            if not os.path.isfile(doc_path):
                continue
            content = _read(doc_path)
            toc_entries = _extract_toc_entries(content)
            headings = _extract_headings(content)

            for display_text, anchor in toc_entries:
                if anchor not in headings:
                    failures.append(
                        f"  {doc_label}: ToC entry '{display_text}' "
                        f"(#{anchor}) has no matching heading"
                    )

        if failures:
            self.fail(
                f"ToC entries without matching headings ({len(failures)}):\n"
                + "\n".join(failures)
            )

    def test_headings_have_toc_entries(self) -> None:
        """Every ## heading should have a ToC entry (except Table of Contents
        itself)."""
        failures = []

        for doc_label, doc_path in self.TOC_FILES:
            if not os.path.isfile(doc_path):
                continue
            content = _read(doc_path)
            toc_entries = _extract_toc_entries(content)
            toc_anchors = {anchor for _, anchor in toc_entries}
            headings = _extract_headings(content)

            # Only check ## headings (top-level sections), not ### or deeper
            for match in RE_HEADING.finditer(content):
                level = len(match.group(1))
                heading_text = match.group(2).strip()
                anchor = _heading_to_anchor(heading_text)

                if level != 2:
                    continue
                if anchor == "table-of-contents":
                    continue

                if anchor not in toc_anchors:
                    failures.append(
                        f"  {doc_label}: heading '{heading_text}' "
                        f"(#{anchor}) missing from ToC"
                    )

        if failures:
            self.fail(
                f"Headings missing from ToC ({len(failures)}):\n"
                + "\n".join(failures)
            )


class DocsSafetyTests(unittest.TestCase):
    """Safety checks for documented command snippets."""

    def test_documented_symlink_targets_use_expected_relative_depths(self) -> None:
        """Documented symlink targets should use correct relative-depth patterns.

        Validates structural depth (e.g. ``../../.agents/skills/``) rather
        than exact example names so that harmless doc edits (renaming the
        example skill) don't break the test.
        """
        # Each tuple: (file path, list of regex patterns to match)
        # Patterns validate relative-depth structure, not exact example names.
        checks = [
            (
                DOCS["references/tool-integration.md"],
                [
                    # Unix: two-level relative symlink to .agents/skills/<name>
                    r"\.\./\.\./\.agents/skills/\S+",
                    # Unix: three-level relative symlink to .agents/skills/<name>/SKILL.md
                    r"\.\./\.\./\.\./\.agents/skills/\S+/SKILL\.md",
                    # Windows: two-level relative path
                    r"\.\.\\\.\.\\\.agents\\skills\\\S+",
                    # Windows: three-level relative path with SKILL.md
                    r"\.\.\\\.\.\\\.\.\\\.agents\\skills\\\S+\\SKILL\.md",
                ],
            ),
            (
                DOCS["capabilities/deployment/references/symlink-setup.md"],
                [
                    # Unix: two-level relative symlink
                    r"\.\./\.\./\.agents/skills/\S+",
                    # Windows: two-level relative path
                    r"\.\.\\\.\.\\\.agents\\skills\\\S+",
                ],
            ),
        ]

        for path, patterns in checks:
            if not os.path.isfile(path):
                continue
            content = _read(path)
            for pattern in patterns:
                with self.subTest(path=path, pattern=pattern):
                    self.assertRegex(
                        content,
                        pattern,
                        f"Expected relative-depth pattern not found: {pattern}",
                    )

    def test_windows_cmd_verification_snippets_present(self) -> None:
        """Symlink docs should include a cmd verification example."""
        docs_to_check = [
            DOCS["references/tool-integration.md"],
            DOCS["capabilities/deployment/references/symlink-setup.md"],
        ]

        for path in docs_to_check:
            if not os.path.isfile(path):
                continue
            content = _read(path)
            with self.subTest(path=path):
                self.assertIn(r"dir .claude\skills /AL", content)

    def test_extension_deployment_sections_reference_symlinks(self) -> None:
        """Every *-extensions.md with a Deployment Pointer section must
        cross-reference the symlink decision guide."""
        extension_files = [
            DOCS["references/claude-code-extensions.md"],
            DOCS["references/codex-extensions.md"],
            DOCS["references/cursor-extensions.md"],
        ]
        anchor = "tool-integration.md#symlink-based-deployment-pointers"
        failures = []

        for path in extension_files:
            if not os.path.isfile(path):
                continue
            content = _read(path)
            # Only check files that have a Deployment Pointer section
            if "## Deployment Pointer" not in content:
                continue
            if anchor not in content:
                failures.append(os.path.relpath(path, SKILL_ROOT))

        if failures:
            self.fail(
                "Extension files with '## Deployment Pointer' section missing "
                f"symlink cross-reference ({anchor}):\n  "
                + "\n  ".join(failures)
            )

    def test_parent_traversal_links_resolve_within_skill(self) -> None:
        """Under the redefined path-resolution rule
        (``references/path-resolution.md``), ``../`` segments are legal
        — they are how a capability reaches the shared skill root.
        Every ``../``-using link must still resolve to an existing
        file inside the skill directory; links that escape the skill
        root entirely are flagged elsewhere as INFO (out of scope).
        """
        # ``DOCS["SKILL.md"]`` already points at the skill entry, so the
        # enclosing skill directory is one ``dirname`` up — not two.
        # A double-dirname would land on the repo root, which would
        # quietly accept escapes from a capability into top-level repo
        # files (e.g. ``../../../README.md``) as "in-scope" and miss
        # the very class of bad links this test is meant to flag.
        skill_root = os.path.dirname(DOCS["SKILL.md"])
        failures = []

        for doc_label, doc_path in DOCS.items():
            if not os.path.isfile(doc_path):
                continue
            content = _read(doc_path)
            content_no_code = RE_FENCED_CODE_BLOCK.sub("", content)
            for match in RE_MD_LINK.finditer(content_no_code):
                target = match.group(1).strip()
                if re.match(r"https?://|mailto:|file:///|<|#", target):
                    continue
                if "../" not in target:
                    continue
                # Strip optional title and fragment.
                clean = target.split(" ", 1)[0].split("#", 1)[0]
                if not clean:
                    continue
                resolved = os.path.normpath(
                    os.path.join(os.path.dirname(doc_path), clean)
                )
                # Out-of-skill links are recorded as INFO elsewhere; this
                # test only complains about ../ links that don't resolve.
                # Use ``commonpath`` for containment instead of
                # ``startswith`` — a sibling directory whose name shares
                # a textual prefix (e.g. ``/tmp/skill-other`` vs
                # ``/tmp/skill``) would slip through the prefix check
                # and silently pass a broken cross-tree link.
                try:
                    common = os.path.commonpath([skill_root, resolved])
                except ValueError:
                    # Different drives on Windows — definitionally
                    # outside the skill root.
                    common = ""
                if common != skill_root:
                    continue
                # ``isfile`` rather than ``exists``: the docstring
                # promises every ``../`` link must resolve to an
                # existing *file* under the skill root.  A link that
                # resolves to a directory is also a documentation
                # error — the validator's path-resolution rule
                # surfaces non-file targets as WARN — and the test
                # message names "files", so the check must agree.
                if not os.path.isfile(resolved):
                    failures.append(
                        f"  {doc_label}: link target '{target}' "
                        f"resolved to {resolved} which is not an "
                        f"existing file"
                    )

        if failures:
            self.fail(
                "Markdown links using ../ traversal must resolve to "
                "existing files inside the skill:\n" + "\n".join(failures)
            )

    def test_no_dot_slash_prefix_in_file_references(self) -> None:
        """File references must use 'path/to/file' not './path/to/file' per
        agentskills.io spec."""
        failures = []

        for doc_label, doc_path in DOCS.items():
            if not os.path.isfile(doc_path):
                continue
            content = _read(doc_path)
            # Check for `./something` in backtick-quoted paths
            matches = re.findall(r"`\./[^`]+`", content)
            if matches:
                failures.append(
                    f"  {doc_label}: {', '.join(matches)}"
                )

        if failures:
            self.fail(
                "File references with './' prefix violate agentskills.io "
                "spec (use relative paths from skill root without './'):\n"
                + "\n".join(failures)
            )

    def test_no_malformed_windows_dot_agents_paths(self) -> None:
        """Windows path snippets should not contain '..agents' typos."""
        docs_to_check = [
            DOCS["references/tool-integration.md"],
            DOCS["capabilities/deployment/references/symlink-setup.md"],
        ]
        failures = []

        for path in docs_to_check:
            if not os.path.isfile(path):
                continue
            content = _read(path)
            if "..agents" in content:
                failures.append(os.path.relpath(path, SKILL_ROOT))

        if failures:
            self.fail(
                "Malformed '..agents' Windows symlink path found in: "
                + ", ".join(failures)
            )

    def test_no_destructive_git_checkout_recovery_snippet(self) -> None:
        """Docs should avoid suggesting destructive checkout refresh commands."""
        path = DOCS["references/tool-integration.md"]
        if not os.path.isfile(path):
            return

        content = _read(path)
        self.assertNotIn(
            "git checkout -- .",
            content,
            "Use safer guidance than 'git checkout -- .' for symlink recovery.",
        )


if __name__ == "__main__":
    unittest.main()
