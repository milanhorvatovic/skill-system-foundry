import os


DEFAULT_DESCRIPTION = (
    "Packages a minimal demo skill. Use when running bundling smoke tests."
)


def write_text(path: str, content: str) -> None:
    """Write *content* to *path* with LF terminators on every host.

    Pinning ``newline="\\n"`` makes test fixtures deterministic
    across platforms.  Without it, Python's text mode translates
    ``\\n`` to ``\\r\\n`` on Windows, so any test that asserts
    LF-byte semantics (line-ending detection, ``load_bytes_lf ==
    load_bytes`` for an LF-only fixture) silently fails on a
    Windows runner.
    """
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def write_skill_md(
    skill_dir: str,
    *,
    name: str = "demo-skill",
    description: str = DEFAULT_DESCRIPTION,
    body: str = "# Demo Skill\n",
    allowed_tools: str | None = None,
    extra_frontmatter: str = "",
) -> None:
    body_text = body if body.endswith("\n") else f"{body}\n"
    extra = ""
    if allowed_tools is not None:
        extra += f"allowed-tools: {allowed_tools}\n"
    if extra_frontmatter:
        extra += extra_frontmatter
        if not extra.endswith("\n"):
            extra += "\n"
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"{extra}"
        "---\n\n"
        f"{body_text}"
    )
    write_text(os.path.join(skill_dir, "SKILL.md"), content)


def write_capability_md(
    skill_dir: str,
    capability_name: str,
    *,
    body: str = "# Capability\n",
    allowed_tools: str | None = None,
    extra_frontmatter: str = "",
) -> None:
    """Write a ``capability.md`` under ``capabilities/<name>/``.

    The capability has no frontmatter by default and is never
    registered in discovery — the parent ``SKILL.md`` is the
    discovery boundary.  Frontmatter on a capability is optional and
    its fields fall into two categories: ``allowed-tools`` is
    *behaviourally meaningful* — it feeds the bottom-up aggregation
    rule and the per-file effective coherence check — while the
    skill-only fields enumerated in ``CAPABILITY_SKILL_ONLY_FIELDS``
    (``license``, ``compatibility``,
    ``metadata.author``/``version``/``spec``) are *informational only
    at the capability layer*; the parent SKILL.md is authoritative,
    and declaring them on a capability triggers an INFO redirect.

    Pass *allowed_tools* (string written verbatim after the
    ``allowed-tools:`` key) or *extra_frontmatter* (raw lines appended
    inside the frontmatter block) to author capabilities that
    exercise the validation rules.
    """
    body_text = body if body.endswith("\n") else f"{body}\n"
    if allowed_tools is None and not extra_frontmatter:
        write_text(
            os.path.join(
                skill_dir, "capabilities", capability_name, "capability.md",
            ),
            body_text,
        )
        return
    fm_lines: list[str] = ["---"]
    if allowed_tools is not None:
        fm_lines.append(f"allowed-tools: {allowed_tools}")
    if extra_frontmatter:
        for line in extra_frontmatter.splitlines():
            fm_lines.append(line)
    fm_lines.append("---")
    content = "\n".join(fm_lines) + "\n\n" + body_text
    write_text(
        os.path.join(
            skill_dir, "capabilities", capability_name, "capability.md",
        ),
        content,
    )
