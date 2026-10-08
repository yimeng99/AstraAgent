"""上传落盘位置：必须锚定在**项目根**的 workspace/uploads，而不是当前工作目录。

回归背景：`./workspace/uploads` 原先按 CWD 解析，于是 `python src/api/main.py`
启动时上传落到 `src/api/workspace/uploads`，和根目录下那份并存 —— 同一份存储
出现两个目录，还各自被 gitignore 掉，很难发现。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.config import (
    PROJECT_ROOT,
    StorageConfig,
    WorkspaceConfig,
    load_app_config,
    resolve_project_path,
)
from core.storage import LocalBackend, get_backend

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _env(monkeypatch: MonkeyPatch) -> None:
    """load_app_config 需要 LLM_API_KEY 才能跑起来。"""
    monkeypatch.setenv("LLM_API_KEY", "test-key")


def test_project_root_points_at_repo_root():
    assert (PROJECT_ROOT / "pyproject.toml").is_file()


def test_relative_path_is_anchored_to_project_root():
    assert resolve_project_path("./workspace/uploads") == PROJECT_ROOT / "workspace" / "uploads"


def test_absolute_path_is_untouched(tmp_path: Path):
    assert resolve_project_path(tmp_path) == tmp_path


def test_default_workspace_is_absolute():
    root = WorkspaceConfig().root
    assert root.is_absolute()
    assert root == PROJECT_ROOT / "workspace"


def test_local_backend_anchors_relative_root(tmp_path: Path, monkeypatch: MonkeyPatch):
    """即使有人手搓一个相对 root，也落到项目根下（换 CWD 不影响结果）。"""
    monkeypatch.chdir(tmp_path)
    backend = LocalBackend("workspace/uploads")
    assert backend.root.is_absolute()
    assert backend.root == resolve_project_path("./workspace/uploads")


def test_storage_local_root_from_env(tmp_path: Path, monkeypatch: MonkeyPatch):
    _env(monkeypatch)
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", "./workspace/uploads")
    cfg = load_app_config(dotenv_path=tmp_path / "missing.env")  # 别读仓库里的 .env
    assert cfg.storage.local_root == PROJECT_ROOT / "workspace" / "uploads"


def test_default_root_is_project_workspace(tmp_path: Path, monkeypatch: MonkeyPatch):
    """未配 STORAGE_LOCAL_ROOT 时，落点 = 项目根/workspace/uploads。"""
    monkeypatch.chdir(tmp_path)
    backend = get_backend(StorageConfig(driver="local", local_root=None))
    assert isinstance(backend, LocalBackend)
    assert backend.root == PROJECT_ROOT / "workspace" / "uploads"


def test_agent_workspace_env_is_honored(tmp_path: Path, monkeypatch: MonkeyPatch):
    _env(monkeypatch)
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path / "ws"))
    cfg = load_app_config(dotenv_path=tmp_path / "missing.env")
    assert cfg.workspace.root == tmp_path / "ws"


def test_relative_agent_workspace_is_anchored(tmp_path: Path, monkeypatch: MonkeyPatch):
    _env(monkeypatch)
    monkeypatch.setenv("AGENT_WORKSPACE", "./workspace")
    cfg = load_app_config(dotenv_path=tmp_path / "missing.env")
    assert cfg.workspace.root == PROJECT_ROOT / "workspace"
