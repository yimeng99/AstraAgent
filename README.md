# AstraAgent

> 集成企业知识库（RagWiki）与工具调用的智能体框架，基于 [deepagents](https://github.com/langchain-ai/deepagents)。

[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-managed-blueviolet)](https://docs.astral.sh/uv/)
[![Conventional Commits](https://img.shields.io/badge/commits-conventional-fe5197)](https://www.conventionalcommits.org/)

---

## 是什么

AstraAgent 是一个**企业知识库 + 多 LLM provider + 子智能体派发**的智能体框架：

- LLM 客户端支持多 provider：**OpenAI / MiniMax Token Plan / DeepSeek / Zhipu / Moonshot / Anthropic**
- 知识库：内置 RagWiki 集成（HTTP API）；子智能体 `ragwiki-agent` 负责检索增强问答
- 文件型技能（skills）：Markdown 描述，注入到 system prompt
- 主智能体自动按 description 派发子智能体（`task()` 工具）
- 中文优先的代码、注释与提交信息

---

## 特性

| 模块 | 能力 |
|------|------|
| **多 LLM provider** | OpenAI 兼容 + 自定义 base_url，预设 7 个国内/国外常用厂商 |
| **RagWiki 集成** | 通过 HTTP API 检索你的企业知识库文档 |
| **Sub-agents** | `ragwiki-agent` + `code-reviewer`，主 agent 按 description 自动派发 |
| **Skills** | 文件型技能，注入到 system prompt |
| **文档理解** | 上传 Word / Excel / PDF / 文本，服务端抽成文本喂给模型 |
| **报表生成** | 模型产出结构化 spec，服务端渲染 xlsx / docx / pdf 并回读自检 |
| **MCP 接入** | 对接外部 MCP 服务（http / sse / stdio），带角色校验与身份透传 |
| **代码沙箱** | OpenSandbox 隔离执行（可选，未配置自动降级） |
| **Web 前端** | SSE 流式聊天、附件上传、Excel/PDF 在线预览、思维链折叠 |
| **持久化** | 对话历史（Postgres checkpointer）、长期记忆（store，按组织/用户隔离） |
| **结构化日志** | structlog + JSON 输出，工具调用审计与错误脱敏 |
| **代码规范** | ruff + pre-commit + commitlint |

---

## 快速开始

### 1. 安装依赖

```bash
uv sync --extra dev
```

### 2. 配置 LLM

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
LLM_PROVIDER=MiniMax            # 默认 MiniMax Token Plan
LLM_API_KEY=eyJxxxxxxxxxxxxxxx
# LLM_BASE_URL / LLM_MODEL 留空自动用预设值
```

### 3. 校验

```bash
uv run python -m core check
```

输出示例：

```
2026-... [info] config.check.ok llm_model=MiniMax-M3
AstraAgent 配置 OK。
  LLM: MiniMax/MiniMax-M3
  Workspace: workspace
```

### 4. 跑 agent

```bash
# 单轮执行
uv run python -m core run "RagWiki 里有没有提到 X 接口？"

# 交互式 REPL
uv run python -m core chat
> 你好

# 或用 console_script 入口
astra-agent check
astra-agent chat
astra-agent run "..."
```

---

## 架构

```
┌──────────────────────────────────────────────┐
│              CLI / 入口层                       │
│        core/cli.py（check / chat / run）       │
├──────────────────────────────────────────────┤
│              Agent 编排层                       │
│   core/agent.py（build_core_agent）            │
│   core/subagent/（ragwiki-agent / code-reviewer）│
├──────────────────────────────────────────────┤
│           LLM 客户端（多 provider）             │
│   core/llm.py（OpenAI / MiniMax / ...）      │
├──────────────────────────────────────────────┤
│           RagWiki 集成层                       │
│   ragwiki/client.py（HTTP API）              │
│   ragwiki/tools.py（@tool 封装）              │
├──────────────────────────────────────────────┤
│           基础设施层                            │
│   core/checkpointer.py / core/backend.py      │
│   core/utils/logging.py                       │
│   core/security/redact.py                     │
└──────────────────────────────────────────────┘
```

详细见 [`docs/design/architecture.md`](docs/design/architecture.md)。

---

## 目录结构

```
AstraAgent/
├── AGENTS.md                 # ★ AI 协作者入口（硬规矩 / 环境陷阱 / 命令）
├── pyproject.toml            # 项目元数据 + 依赖 + 工具配置
├── uv.lock                   # 依赖锁
├── README.md                 # 本文件
├── .env.example              # 环境变量模板（LLM / PG / MCP / 沙箱 / 存储）
├── .cache/                   # ★ 临时脚本 / 截图 / 日志（已 gitignore，见 AGENTS.md）
├── docs/                     # 设计、规则、笔记
│   ├── design/               # 硬性规约（coding-style / project-layout / architecture / data-modeling / business-plugins）
│   ├── rules/                # 项目规则（project-rules / commit-conventions）
│   └── notes/                # 开发笔记（uv-init / build-run / llm-providers）
├── scripts/                  # 运维/演示脚本（如 demo_mcp_server.py）
├── src/
│   ├── core/                 # 主智能体编排
│   │   ├── agent.py          # build_core_agent + lifespan（异步资源在此初始化）
│   │   ├── config.py / llm.py / prompts.py
│   │   ├── checkpointer.py   # 对话历史（Postgres / 内存）
│   │   ├── backend.py        # 长期记忆 store + CompositeBackend
│   │   ├── storage.py        # 上传文件存储（本地 / OSS）
│   │   ├── documents.py      # Word/Excel/PDF → 文本
│   │   ├── reports.py        # 报表渲染（xlsx / docx / pdf）
│   │   ├── report_tools.py   # 报表相关 @tool
│   │   ├── artifacts.py      # 产物落库与回传
│   │   ├── think.py          # <think> 流式分流
│   │   ├── mcp/              # MCP 接入（config / registry / interceptors / 自检）
│   │   ├── sandbox/          # OpenSandbox 隔离执行
│   │   ├── subagent/         # 内置 sub-agent
│   │   ├── skills/           # 文件型技能
│   │   └── security/ utils/
│   ├── api/                  # FastAPI（/api/v1：chat SSE / threads / upload / files / history）
│   ├── business/             # 业务接入（每个子包 = 一个业务系统）
│   └── ragwiki/              # RagWiki HTTP 客户端 + @tool
├── tests/                    # pytest
└── frontend/                 # Vue 3 + Vite + Element Plus + TS（/api 代理到 :8000）
    └── src/
        ├── App.vue
        ├── components/       # Composer / ChatMessage / FilePreview / Markdown / Reasoning
        └── use*.ts           # SSE 流、附件上传、会话、打字机、用户
```

---

## AI 协作

本仓库有 [`AGENTS.md`](AGENTS.md)：AI 工具（DeepSeek Harness / Claude Code / Cursor …）的入口，
写明了命令、硬规矩（临时文件放 `.cache/`、别用 shell 改文本文件）、环境陷阱与文档导航。

**约定**：所有临时脚本、截图、日志一律放 `.cache/`（已 gitignore），不要污染源码树。

---

## 开发

### 环境

```bash
uv sync --extra dev         # 装 ruff / mypy / pytest
uv tool install pre-commit   # 装 pre-commit（与项目依赖隔离）
pre-commit install --hook-type commit-msg   # 启用 commit 校验
git config commit.template .gitmessage      # 启用 commit 模板
```

### 提交流程

```bash
# Conventional Commits + 中文标题
git add .
git commit -m "feat(ragwiki): 新增多文档对比 sub-agent"
```

格式详见 [`docs/rules/commit-conventions.md`](docs/rules/commit-conventions.md)。

### 静态检查

```bash
uv run ruff check src scripts        # lint
uv run ruff format src scripts       # 格式化
uv run mypy src                      # 类型检查（strict）
uv run pytest                        # 测试
```

### 添加 sub-agent

1. 在 `src/core/subagent/<name>.py` 写一个 `SubAgentSpec` 实例
2. 在 `src/core/subagent/registry.py: BUILTIN_SUBAGENTS` 注册
3. `build_core_agent` 启动时自动注入到主 agent

### 添加 LLM provider

1. 在 `src/core/llm.py: PROVIDER_PRESETS` 加一项 `ProviderPreset(...)`
2. 如使用非 OpenAI 协议，在 `build_llm_client` 加分支 + 装对应 SDK

---

## 文档导航

| 想看什么 | 文件 |
|---------|------|
| **AI 协作者入口 / 硬规矩** | [`AGENTS.md`](AGENTS.md) |
| 文档总索引 | [`docs/README.md`](docs/README.md) |
| 命名 / 编码规范 | [`docs/design/coding-style.md`](docs/design/coding-style.md) |
| 数据模型 / 字段命名 | [`docs/design/data-modeling.md`](docs/design/data-modeling.md) |
| 目录布局 | [`docs/design/project-layout.md`](docs/design/project-layout.md) |
| 架构设计 | [`docs/design/architecture.md`](docs/design/architecture.md) |
| 业务系统接入 | [`docs/design/business-plugins.md`](docs/design/business-plugins.md) |
| 项目基本规则 | [`docs/rules/project-rules.md`](docs/rules/project-rules.md) |
| 提交规范 | [`docs/rules/commit-conventions.md`](docs/rules/commit-conventions.md) |
| 启动 / 构建 / 依赖 | [`docs/notes/build-run.md`](docs/notes/build-run.md) |
| LLM provider 说明 | [`docs/notes/llm-providers.md`](docs/notes/llm-providers.md) |

---

## 故障排查

| 症状 | 解法 |
|------|------|
| `ConfigError: 缺少 LLM_API_KEY` | 检查 `.env` 是否在项目根目录 |
| 配置校验失败、值里带着 `# …` | `.env` 里注释没和值分开：`KEY=值# 注释` 会被当成值，**`#` 前必须有空格** |
| 对话历史重启就没了 | 检查 `POSTGRES_URL` 是否可达；Windows 使用 `python run_api.py` 显式选择 Selector 事件循环（见 [AGENTS.md](AGENTS.md) §4） |
| 长任务执行中被取消 | 检查是否使用 `--reload`：保存源码会重启服务并取消任务。长任务使用 `python run_api.py`，更新代码前先等待活动任务结束 |
| `RagWiki 未配置` | 在 `.env` 设置 `RAGWIKI_API_KEY` + `RAGWIKI_KNOWLEDGE_BASE_ID` |
| 网络异常 | 检查 `RAGWIKI_ENDPOINT` 是否可达 |
| `ruff check` 报错 | `uv run ruff check --fix` 自动改 |
| `commitlint` 拒绝 | 参考 [`commit-conventions.md`](docs/rules/commit-conventions.md) 调整标题 |

---

## 许可证

MIT
