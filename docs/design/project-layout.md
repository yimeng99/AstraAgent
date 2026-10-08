# Project Layout — 目录结构与文件路径

> 适用范围：本仓库全部目录与文件组织。
> 主要参考：[Python Packaging User Guide – src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)、[PEP 621](https://peps.python.org/pep-0621/)。

---

## 1. 顶层结构

```
AstraAgent/
├── .venv/                    # 虚拟环境（uv 管理；gitignore）
├── .idea/                    # PyCharm 配置（gitignore）
├── .env.example                # 环境变量模板（git 跟踪）
├── .gitignore
├── .python-version           # 解释器版本（uv python pin 生成）
├── pyproject.toml            # 项目元数据 + 依赖 + 工具配置（单一来源）
├── uv.lock                   # 依赖锁文件（必须入库）
├── README.md                 # 项目入口文档
├── LICENSE
├── src/                      # 源代码（src-layout，PEP 推荐）
│   └── astra_agent/
│       ├── __init__.py
│       ├── py.typed          # PEP 561 类型提示标记
│       └── ...
├── tests/                    # 测试，结构镜像 src/
│   ├── conftest.py
│   └── ...
├── workspace/                # 智能体运行时工作目录（详见 workspace 设计）
├── docs/                     # 设计、规则、笔记、对接文档
│   ├── README.md
│   ├── design/
│   ├── rules/
│   ├── notes/
│   └── feishu/
└── scripts/                  # 一次性脚本（迁移、批处理、运维）
```

---

## 2. src/ 布局（强制）

> **强制使用 src/ 布局**。禁止把包目录放在仓库根。

```
src/
└── astra_agent/             # 与 pyproject.toml [project].name 一致
    ├── __init__.py           # 必须存在；可包含 __version__
    ├── py.typed              # 标记本包对外提供类型提示（PEP 561）
    ├── agent.py              # Agent 主入口
    ├── config.py             # 配置加载
    ├── cli.py                # CLI 入口（可选）
    ├── tools/                # Agent 工具
    │   ├── __init__.py
    │   ├── feishu_doc.py
    │   └── ...
    ├── llm/                  # LLM 客户端
    │   ├── __init__.py
    │   └── clients.py
    ├── memory/               # 记忆管理
    │   ├── __init__.py
    │   ├── short_term.py
    │   └── long_term.py
    ├── models/               # Pydantic / dataclass 模型
    │   ├── __init__.py
    │   └── ...
    ├── prompts/              # 提示词（Markdown + 加载器）
    │   ├── __init__.py
    │   └── system.md
    └── utils/
        ├── __init__.py
        └── ...
```

### 为什么必须 src/ 布局

| 好处 | 说明 |
|------|------|
| 防误导入 | 测试只能 import 安装后的包，不能 import 工作树副本 |
| 抓包问题 | `MANIFEST.in` / `pyproject.toml` 的 `package-data` 缺失会立刻暴露 |
| 利于 tox / hatch | 隔离虚拟环境跑测试，更接近生产 |
| 类型检查 | `mypy` / `pyright` 默认按 src/ 工作，配置最少 |

---

## 3. 测试目录

```
tests/
├── conftest.py                # 全局 fixture
├── unit/                      # 单元测试（按模块镜像 src/）
│   ├── test_agent.py
│   ├── test_config.py
│   └── tools/
│       └── test_feishu_doc.py
├── integration/               # 集成测试（跨模块、I/O）
│   └── test_agent_runtime.py
├── e2e/                       # 端到端测试（可选）
└── fixtures/                  # 测试数据、夹具文件
    ├── feishu_response.json
    └── ...
```

- 测试文件命名 `test_*.py`
- 测试目录结构**镜像** `src/`（`tests/unit/tools/` 对应 `src/astra_agent/tools/`）
- 共享 fixture 放 `conftest.py`，子目录的 `conftest.py` 可做局部 fixture
- 集成测试打 `@pytest.mark.integration`，默认 `pytest -m "not integration"` 跳过

---

## 4. docs/ 目录（已规范）

```
docs/
├── README.md                  # 顶层索引
├── design/                    # 设计规约（硬性）
│   ├── README.md
│   ├── coding-style.md
│   ├── project-layout.md      # 本文件
│   └── architecture.md
├── rules/                     # 项目规则（环境、Git、Claude 协作）
│   ├── README.md
│   └── project-rules.md
├── notes/                     # 探索性笔记、初始化记录
│   ├── README.md
│   ├── uv-init.md
│   └── build-run.md
└── feishu/                    # 外部对接设计稿
    ├── README.md
    └── integration.md
```

详细子目录职责见 `docs/README.md` 与各子目录的 `README.md`。

---

## 5. workspace/ 智能体运行时

```
workspace/
├── config.yaml                # 工作目录配置
├── shared/                    # 跨 session 共享
│   ├── knowledge/
│   ├── prompts/
│   └── tools/
└── sessions/
    └── <session_id>/
        ├── input/
        ├── output/
        ├── scratch/
        ├── plans/todo.md
        ├── memory/
        ├── tool_cache/
        ├── artifacts/
        └── logs/
```

详见 `docs/rules/project-rules.md` 与待写的 `agent-workspace.md`。

---

## 6. 文件命名规则

| 类型 | 规则 | 示例 |
|------|------|------|
| Python 模块 | `snake_case.py` | `agent_runner.py`、`feishu_doc.py` |
| Python 包（目录） | `snake_case/`，**无下划线**时优先无下划线 | `agent/`、`tools/`、`memory/` |
| 测试文件 | `test_<module>.py` | `test_agent.py` |
| Markdown 文档 | `kebab-case.md` | `coding-style.md`、`project-layout.md` |
| YAML 配置 | `snake_case.yaml` 或 `<context>.yaml` | `config.yaml`、`feishu.yaml` |
| 环境变量 | `UPPER_SNAKE_CASE` | `FEISHU_APP_ID` |
| 类名 | `PascalCase`（与文件名无关） | `class AgentRunner` 写在 `agent_runner.py` |

### 禁止

- 文件名带空格、中文
- 文件名带 `-`（连字符，Python 不可导入）
- 同一目录下两个同名模块仅大小写不同（Windows 不区分，但 Linux 区分，会引发 CI 问题）
- 在 `src/` 顶层放 `.py` 文件 —— 必须在 `astra_agent/` 子包内

---

## 7. `pyproject.toml` 布局

```toml
[project]
name = "astra-agent"           # 注意：下划线变连字符（PEP 503 规范化）
version = "0.1.0"
description = "..."
requires-python = ">=3.13"
dependencies = [
    "deepagents>=0.7.18",
    "dotenv>=0.9.9",
    "load-dotenv>=0.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-cov",
    "ruff>=0.6",
    "mypy>=1.10",
]

[project.scripts]
astra-agent = "astra_agent.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/astra_agent"]

# —— 工具配置 ——
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]

[tool.ruff.lint.isort]
known-first-party = ["astra_agent"]

[tool.mypy]
python_version = "3.13"
strict = true
mypy_path = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
addopts = "-ra -q --strict-markers --cov=astra_agent --cov-report=term-missing"
testpaths = ["tests"]
markers = [
    "integration: 集成测试，需要外部依赖",
    "unit: 单元测试",
]
```

---

## 8. `.gitignore` 模板

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
*.egg
.eggs/
build/
dist/

# 测试 / 覆盖率
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/

# 环境
.venv/
.env
.env.local

# IDE
.idea/
.vscode/
*.swp
.DS_Store

# Agent workspace（运行时数据）
workspace/sessions/*/scratch/
workspace/sessions/*/tool_cache/
workspace/sessions/*/logs/
!workspace/.gitkeep
!workspace/sessions/.gitkeep
!workspace/shared/.gitkeep
```

---

## 9. 模块导入示例

```python
# ✅ 绝对导入
from astra_agent.config import WORKSPACE_ROOT
from astra_agent.tools.feishu_doc import get_feishu_doc_text
from astra_agent.models.feishu import FeishuConfig

# ❌ 相对导入（禁止出现在 src/ 内）
from .config import WORKSPACE_ROOT
from ..tools.feishu_doc import get_feishu_doc_text
```

唯一允许相对导入的场景：**包内部循环引用**（极少数，且必须配 Lint 豁免）。

---

## 10. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-09-24 | 初版：基于 Python Packaging User Guide 与 2025 现代实践整合 |