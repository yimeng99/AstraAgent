# 项目基本规则

> 适用范围：本仓库（`AstraAgent`）所有 Python 代码与文档。

---

## 1. 环境与运行时

- **Python 版本**：≥ 3.13（由 `pyproject.toml` 中的 `requires-python` 锁定）。
- **包管理**：统一使用 [`uv`](https://docs.astral.sh/uv/)。**禁止**使用 `pip` / `conda` / `poetry` 直接管理本项目依赖。
- **虚拟环境**：根目录 `.venv/`，由 `uv` 自动管理。`.venv/` 必须加入 `.gitignore`。
- **Python 解释器固定**：开发完成后用 `uv python pin 3.13` 把版本写入 `.python-version`，随仓库提交。

---

## 2. 依赖管理

- 所有运行时依赖通过 `uv add <pkg>` 添加，**不要**手动改 `pyproject.toml` 的 `dependencies` 列表。
- 开发依赖（pytest、ruff、mypy 等）通过 `uv add --dev <pkg>` 写入 `[dependency-groups]`。
- `uv.lock` 必须提交到仓库（应用项目约定）。
- 升级依赖：`uv lock --upgrade && uv sync`。

---

## 3. 环境变量与密钥

- 所有密钥、Token、连接串一律走 `.env`，**禁止硬编码**到代码中。
- 仓库内**只保留** `.env.example` 作为模板，`.env` 加入 `.gitignore`。
- 代码中使用 `from dotenv import load_dotenv; load_dotenv()` 加载（`dotenv` / `load-dotenv` 已在 `pyproject.toml`）。

---

## 4. 目录结构

```
AstraAgent/
├── docs/               # 文档（不进 wheel）
│   ├── rules/          # 项目规则（本目录）
│   ├── notes/          # 学习与开发笔记
│   └── feishu/         # 飞书对接相关文档
├── src/                # 源代码（待启用）
├── tests/              # 测试（待启用）
├── pyproject.toml      # 项目元数据
├── uv.lock             # 依赖锁定
├── .python-version     # 解释器版本（待生成）
├── .env.example        # 环境变量模板
└── .venv/              # 虚拟环境（不入库）
```

> 项目源码与测试目录待开发阶段启动后再创建，遵循 `src/` layout。

---

## 5. 代码风格

- 格式化与 Lint：[`ruff`](https://docs.astral.sh/ruff/)（开发期安装：`uv add --dev ruff`）。
- 类型检查：`mypy`（开发期安装：`uv add --dev mypy`）。
- 命名：
  - 类：`PascalCase`
  - 函数 / 变量：`snake_case`
  - 常量：`UPPER_SNAKE_CASE`
- 每个 `.py` 文件不超过 500 行；超过需拆分并写明。

---

## 6. Git 与提交

- 分支策略与提交规范详见 [`commit-conventions.md`](./commit-conventions.md)。
- 简版：分支 `main`（稳定）+ `feat/*` / `fix/*` / `chore/*`（开发）；提交信息遵循 Conventional Commits + 中文标题。
- **禁止**把 `.env`、`.venv/`、`.idea/`、`__pycache__/`、`*.pyc` 提交进仓库。

---

## 7. 与 Claude 协作

- 任何文件改动前，先 **Read** 一遍。
- 复杂任务（>3 步）先进入 plan 模式对齐方案。
- 完成后报告真实结果：测试是否通过、产物是否落地、有无遗留 TODO。
- 若被纠正，记录到 `corrections.jsonl`（参考 `CLAUDE.md`）。

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-09-24 | 初版：环境、依赖、环境变量、目录、代码风格、Git、Claude 协作约定 |