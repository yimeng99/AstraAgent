"""文件型 skills（deepagents SkillsMiddleware 加载）。

每个 skill 是 ``src/core/skills/<name>/`` 目录，里面含 ``SKILL.md``（YAML frontmatter + body）。

Skills 与 :mod:`core.subagent` 的区别：

* **Sub-agent**：框架原生配置，通过 ``task()`` 工具委派
* **Skill**：markdown 文件，SkillsMiddleware 注入到 system prompt，按 description 匹配

详见 :file:`docs/notes/skills.md`（待写）。
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["SKILLS_DIR", "list_skill_paths"]


# skills 目录在包内，使用相对路径解析
SKILLS_DIR: Path = Path(__file__).resolve().parent


def list_skill_paths() -> list[str]:
    """返回所有 skill 目录路径（字符串列表，喂给 ``create_deep_agent(skills=...)``）。

    自动排除 ``__pycache__`` / 隐藏目录。

    Returns:
        每个 skill 目录的绝对路径字符串。
    """
    return [
        str(p)
        for p in SKILLS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "SKILL.md").is_file()
    ]
