# uv 初始化记录

> 日期：2026-09-24
> 工具版本：`uv 0.12.8`
> Python 版本：`CPython 3.13.13`（来自 `D:\anaconda\python.exe`）

本项目使用 [uv](https://docs.astral.sh/uv/) 作为 Python 包管理与虚拟环境工具。`uv` 是 `pip`/`venv`/`pip-tools`/`virtualenv` 的统一替代品，速度快、零配置。

---

## 1. 已完成的初始化步骤

```bash
# 1. 在项目根目录初始化（生成 pyproject.toml）
uv init --no-readme --bare --no-workspace

# 2. 调整 requires-python，匹配当前可用解释器（系统默认 3.14，实际可用 3.13）
#    修改 pyproject.toml: requires-python = ">=3.13"

# 3. 创建虚拟环境（.venv/）
uv venv --python 3.13

# 4. 同步依赖（生成 uv.lock）
uv sync
```

执行完毕后项目根目录新增了：

| 路径 | 作用 |
|------|------|
| `pyproject.toml` | 项目元数据与依赖声明（PEP 621 标准） |
| `uv.lock` | 锁定版本的依赖文件，应纳入版本控制 |
| `.venv/` | 虚拟环境，**加入 `.gitignore`** |

---

## 2. `pyproject.toml` 当前内容

```toml
[project]
name = "astraagent"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = []
```

---

## 3. 常用命令速查

### 依赖管理

```bash
# 添加运行时依赖
uv add requests

# 添加开发依赖（分组）
uv add --dev pytest ruff

# 按 requirements.txt 添加
uv add -r requirements.txt

# 移除依赖
uv remove requests

# 同步环境到 lock 文件
uv sync

# 仅安装项目自身（不解锁）
uv sync --frozen
```

### 运行与脚本

```bash
# 在虚拟环境中执行任意命令
uv run python main.py
uv run pytest

# 进入虚拟环境的 shell
uv shell
```

### 工具管理（替代 pipx / pip-tools）

```bash
# 运行临时工具（不污染环境）
uvx ruff check .
uvx black .

# 安装全局工具
uv tool install ruff
```

### Python 版本管理

```bash
# 列出已安装的 Python
uv python list

# 安装指定版本的 Python（按需）
uv python install 3.12

# 固定项目使用的 Python 版本（写入 .python-version）
uv python pin 3.13
```

---

## 4. `.gitignore` 建议

`.venv/` 与 Python 缓存不应纳入版本控制，建议在 `.gitignore` 中加入：

```gitignore
# uv
.venv/
uv.lock  # 如果是应用而非库，建议提交；库可不提交

# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ruff_cache/
.mypy_cache/
```

> **约定**：`uv.lock` 在应用项目中**应提交**，在库项目中可选择不提交（让下游消费者自行解析）。本项目为应用，建议提交。

---

## 5. 与 PyCharm / IDE 集成

PyCharm 2024.2+ 已原生支持 `uv`：在 **Settings → Project → Python Interpreter** 选择 **Add Interpreter → uv Environment** 即可自动识别 `.venv` 与 `uv.lock`。

VS Code 安装 [Ruff 扩展](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff) 即可在保存时自动使用 `uvx ruff`。

---

## 6. 后续 TODO（待开发阶段启动后处理）

- [ ] 添加项目实际依赖（待需求明确）
- [ ] 配置 `pyproject.toml` 中的 `[tool.ruff]` / `[tool.pytest]` 等开发工具
- [ ] 选择并固定 Python 解释器版本（写入 `.python-version`）
- [ ] 配置 CI（如 GitHub Actions 中使用 `astral-sh/setup-uv@v1`）