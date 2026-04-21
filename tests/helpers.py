import os
import subprocess


DEFAULT_DESCRIPTION = "Packages a minimal demo skill for bundling smoke tests."


def run_script(argv: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run *argv* as a subprocess in *cwd* and capture stdout/stderr as text.

    Shared helper for subprocess-style CLI tests so scaffold / bundle /
    validate invocations don't re-duplicate ``subprocess.run`` boilerplate.
    Callers are responsible for choosing ``argv[0]`` (typically
    ``sys.executable`` for the in-repo Python scripts).
    """
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


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
) -> None:
    body_text = body if body.endswith("\n") else f"{body}\n"
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body_text}"
    )
    write_text(os.path.join(skill_dir, "SKILL.md"), content)
