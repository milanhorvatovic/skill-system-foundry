import os


DEFAULT_DESCRIPTION = "Packages a minimal demo skill for bundling smoke tests."


def write_text(path: str, content: str) -> None:
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
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
) -> None:
    """Write a minimal ``capability.md`` under ``capabilities/<name>/``.

    The capability has no frontmatter by default — the foundry's
    convention treats capability frontmatter as informational only.
    """
    body_text = body if body.endswith("\n") else f"{body}\n"
    write_text(
        os.path.join(
            skill_dir, "capabilities", capability_name, "capability.md",
        ),
        body_text,
    )
