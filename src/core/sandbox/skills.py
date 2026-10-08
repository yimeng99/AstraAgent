"""把服务端内置 skills 初始化到每个用户的持久沙箱。"""

from __future__ import annotations

import hashlib
import io
import shlex
import uuid
import zipfile
from pathlib import Path

from core.skills import list_skill_paths
from core.tracing import operation

SKILLS_ROOT = "/workspace/skills"


def skills_version() -> str:
    """按实际技能文件生成版本；用于避免每个沙箱操作都重新上传技能包。"""
    digest = hashlib.sha256()
    for source in sorted(list_skill_paths()):
        directory = Path(source)
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory.parent)
            if any(part.startswith((".", "__")) for part in relative.parts):
                continue
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                raise ValueError(f"skill 不允许包含符号链接：{relative}")
            if path.is_file():
                digest.update(relative.as_posix().encode())
                digest.update(b"\0")
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:48]


@operation("skills.sync")
def sync_skills(sandbox) -> None:
    # 只打包实际 skill 及其资源，不把 Python 包、缓存或宿主机链接带入沙箱。
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for source in list_skill_paths():
            directory = Path(source)
            for path in sorted(directory.rglob("*")):
                relative = path.relative_to(directory.parent)
                if any(part.startswith((".", "__")) for part in relative.parts):
                    continue
                if any(parent.is_symlink() for parent in (path, *path.parents)):
                    raise ValueError(f"skill 不允许包含符号链接：{relative}")
                if path.is_file():
                    bundle.writestr(relative.as_posix(), path.read_bytes())
    temporary = f"/tmp/astra-skills-{uuid.uuid4().hex}.zip"
    sandbox.files.write_file(temporary, archive.getvalue())
    # 在容器私有临时目录解包，完整 skill 原子迁入；恢复时不覆盖用户已有版本。
    code = f"""import os, pathlib, tempfile, zipfile
archive = pathlib.Path({temporary!r})
root = pathlib.Path({SKILLS_ROOT!r})
try:
    assert os.path.realpath('/workspace') == '/workspace'
    assert not root.is_symlink(), 'skills root must not be a symlink'
    # 新容器可能连 /workspace 都没有，不能依赖此前执行工具创建过工作区。
    root.mkdir(mode=0o755, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.skills-', dir='/workspace') as staging:
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                path = pathlib.PurePosixPath(name)
                assert not path.is_absolute() and '..' not in path.parts
            bundle.extractall(staging)
        for skill in pathlib.Path(staging).iterdir():
            target = root / skill.name
            if not os.path.lexists(target):
                skill.rename(target)
finally:
    archive.unlink(missing_ok=True)
"""
    result = sandbox.commands.run("python3 -c " + shlex.quote(code))
    if result.exit_code != 0:
        raise RuntimeError("用户沙箱 skills 初始化失败，保留原环境供重试")
