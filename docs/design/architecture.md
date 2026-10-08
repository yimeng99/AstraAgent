# Architecture — 项目架构设计

当前聊天执行链路以 [Agent 执行设计](agent-execution.md) 为准，包含本轮职责划分、错误契约、验证范围及待处理部分。下文为早期整体设计，其中 `astra_agent/` 等示例路径不代表当前目录。

> 适用范围：`src/astra_agent/` 模块划分、依赖方向、配置、可观测性。
> 配套：`coding-style.md`、`project-layout.md`、`docs/feishu/integration.md`、`docs/rules/project-rules.md`。

---

## 1. 设计目标

| 目标 | 含义 |
|------|------|
| **可演进** | 单模块改动不破坏全局；新增能力只需新增模块 |
| **可观测** | 所有外部调用有日志、有重试、有超时 |
| **可测试** | 每个模块可独立 mock，无隐式全局状态 |
| **可替换** | LLM / 工具 / 存储后端可替换实现，不改业务代码 |
| **安全** | 密钥不落代码；危险操作有审计与白名单 |

---

## 2. 分层架构

```
┌──────────────────────────────────────────────┐
│              CLI / 入口层                       │
│        (astra_agent.cli / __main__)           │
├──────────────────────────────────────────────┤
│              Agent 编排层                       │
│   (astra_agent.agent / agent_factory)         │
├──────────────────────────────────────────────┤
│           能力（Tools / Skills）                │
│      (astra_agent.tools / skills)             │
├──────────────────────────────────────────────┤
│           LLM / 模型层                          │
│      (astra_agent.llm.clients)                │
├──────────────────────────────────────────────┤
│           记忆 / 持久化层                        │
│   (astra_agent.memory / storage)              │
├──────────────────────────────────────────────┤
│           基础设施层                            │
│   (astra_agent.config / utils / logging)      │
└──────────────────────────────────────────────┘
```

### 依赖方向（强制）

```
入口层      →  编排层
编排层      →  能力层、LLM 层、记忆层
能力层      →  LLM 层、记忆层、基础设施层
LLM 层      →  基础设施层
记忆层      →  基础设施层
基础设施层  →  （仅依赖 stdlib + 已批准的第三方）
```

- **禁止反向依赖**（基础设施层绝不导入业务层）
- **禁止跨层跳依赖**（入口层不能直接调 LLM，必须经编排层）
- 检测工具：`ruff` 自定义规则 / `import-linter`

---

## 3. 模块职责

| 模块 | 职责 | 不做什么 |
|------|------|---------|
| `agent/` | 创建、运行、监控 agent；接入 deepagents | 不直接调 LLM API |
| `tools/` | 实现一个个独立 tool（飞书、网络、文件、计算） | 不持有 session 级状态 |
| `skills/` | 组合 tool 的高层能力（可复用流程） | 不直接调外部 API |
| `llm/` | LLM 客户端、retry、限流、token 计数 | 不解析业务逻辑 |
| `memory/` | 短期 / 长期记忆读写、向量检索 | 不做权限决策 |
| `models/` | Pydantic 数据模型、配置 schema | 不包含业务逻辑 |
| `prompts/` | 提示词模板与加载器 | 不嵌入业务数据 |
| `config/` | 配置加载（环境变量、YAML） | 不做 I/O |
| `utils/` | 通用工具（日志、时间、hash） | 无业务语义 |

---

## 4. 入口与生命周期

### 4.1 入口

```python
# src/astra_agent/__main__.py
from astra_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

### 4.2 启动顺序

1. 加载 `pyproject.toml` 元数据 → `__version__`
2. `load_dotenv()` 读取 `.env`
3. 初始化日志（structlog）
4. 构建 LLM 客户端（懒加载）
5. 初始化 agent 工作目录（`workspace/`）
6. 注册 tools / skills
7. `agent.invoke(...)` / 进入交互循环

### 4.3 关闭顺序

1. 取消 in-flight 任务
2. 持久化短期记忆 → 长期记忆
3. flush 日志、关闭文件句柄
4. 退出

---

## 5. 配置加载

```python
# src/astra_agent/config.py
from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os

load_dotenv()


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    timeout: float = 60.0


class FeishuConfig(BaseModel):
    app_id: str = Field(default_factory=lambda: os.getenv("FEISHU_APP_ID", ""))
    app_secret: str = Field(repr=False, default_factory=lambda: os.getenv("FEISHU_APP_SECRET", ""))
    cache_ttl: int = 3600


class WorkspaceConfig(BaseModel):
    root: Path = Path("./workspace")
    session_isolation: str = "per_session"   # per_session | shared
    retention_days: int = 30


class AppConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    feishu: FeishuConfig = FeishuConfig()
    workspace: WorkspaceConfig = WorkspaceConfig()
```

**强制：**

- 配置全部走 `pydantic.BaseModel`，启动期校验失败即崩溃
- 密钥**只**从 `.env` / 环境变量读取，**绝不**放 YAML / JSON 配置文件
- 配置对象**只构造一次**，作为依赖注入传入

---

## 6. 错误处理策略

| 层 | 错误处理 |
|----|---------|
| LLM 层 | 5xx / 限流自动重试（指数退避 + jitter），4xx 直接抛出 |
| 工具层 | 业务异常（`FeishuAPIError` 等）捕获后包装为 tool 错误返回给 agent |
| 编排层 | 单步失败可配置 retry / fallback；不可恢复抛 `AgentError` |
| 入口层 | 顶层 `try/except AstraAgentError`，打印用户友好提示后退出 |

```python
# 推荐：自定义异常 + 异常链
class AstraAgentError(Exception): ...
class LLMError(AstraAgentError): ...
class ToolError(AstraAgentError): ...
class ConfigError(AstraAgentError): ...

try:
    client.chat(...)
except httpx.HTTPStatusError as e:
    raise LLMError(f"upstream {e.response.status_code}") from e
```

---

## 7. 日志与可观测性

### 7.1 结构化日志

```python
# src/astra_agent/utils/logging.py
import structlog

def configure_logging(json_output: bool = True) -> None:
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer() if json_output
        else structlog.dev.ConsoleRenderer(),
    ]
    structlog.configure(processors=processors, wrapper_class=structlog.make_filtering_bound_logger(20))
```

### 7.2 关键字段（每条日志至少包含）

- `timestamp` (ISO 8601, UTC)
- `level`
- `event`（动词短语，如 `tool.invoked`）
- `session_id`
- `agent_id`（如有）
- `request_id` / `trace_id`

### 7.3 工具调用审计

所有 tool 调用记录到 `workspace/sessions/<id>/logs/tool_calls.jsonl`：

```jsonl
{"ts":"2026-09-24T10:00:00Z","tool":"fetch_feishu_doc","args":{"document_id":"doccnABC"},"elapsed_ms":421,"ok":true}
{"ts":"2026-09-24T10:00:01Z","tool":"fetch_feishu_doc","args":{...},"ok":false,"error":"timeout"}
```

---

## 8. 重试、限流、超时

| 场景 | 策略 |
|------|------|
| HTTP 调用 | `tenacity` 装饰器：指数退避（base 2s, max 60s），最多 3 次 |
| 飞书 API | 同上 + 429 尊重 `Retry-After` |
| LLM 调用 | 流式输出：read timeout 30s，整体 timeout 180s |
| 文件 I/O | `tenacity` + 短重试（3 次，base 0.5s） |
| 数据库 / 存储 | 短重试（3 次），不可恢复立即报错 |

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPError, LLMError)),
    reraise=True,
)
async def call_llm(...): ...
```

---

## 9. 数据模型

### 9.1 选型

| 场景 | 选择 |
|------|------|
| 外部输入 / API 边界 / 配置 | **Pydantic v2** `BaseModel` |
| 内部 DTO / 不可变值对象 | `@dataclass(frozen=True, slots=True)` |
| Enum / 常量集合 | `enum.StrEnum`（3.11+，原 `str, Enum`） |
| 复杂行为 / 多态 | 抽象基类 `abc.ABC` + `Protocol` |

### 9.2 Pydantic 模型规约

- `model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)`
- 字段加 `Field(description=...)` —— 自动生成 schema
- 敏感字段加 `repr=False`
- 不要在 model 里写 `__init__` / `validate`，用 `field_validator` / `model_validator`

---

## 10. 依赖注入

```python
# 工厂模式 + 显式依赖
class Agent:
    def __init__(
        self,
        llm: LLMClient,
        tools: list[Tool],
        memory: Memory,
        config: AppConfig,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.config = config


def build_agent(config: AppConfig) -> Agent:
    llm = OpenAIClient(config.llm)
    tools = [fetch_feishu_doc, search_web]
    memory = JSONLMemory(config.workspace)
    return Agent(llm=llm, tools=tools, memory=memory, config=config)
```

- **禁止全局单例**（`global agent` / 模块级 client 实例）
- 测试时容易替换
- 依赖关系显式可见

---

## 11. 安全

| 项 | 措施 |
|----|------|
| 密钥 | 只在 `.env`；不进 git；不入日志 |
| 文件操作 | 工具白名单目录；拒绝路径穿越（`..` / 绝对路径） |
| 命令执行 | 如有 shell tool，必须走白名单命令 + 超时 |
| 网络请求 | 强制 HTTPS；可信域名单 |
| 外部输入 | 所有 user / tool 输入经 Pydantic 校验 |

---

## 12. 测试策略

| 层 | 工具 | 覆盖目标 |
|----|------|---------|
| 单元 | `pytest`，`unittest.mock` | 工具函数、解析、格式化 |
| 集成 | `pytest` + `pytest-asyncio` + mock HTTP | 跨模块协作 |
| 端到端 | `pytest -m e2e`，真飞书 sandbox | 关键路径 |
| 类型 | `mypy --strict` | 0 error |
| 风格 | `ruff check` + `ruff format --check` | 0 violation |

覆盖率门槛：`--cov-fail-under=80`（CI 强制）。

---

## 13. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-09-24 | 初版：分层架构、依赖注入、配置、日志、重试、模型、安全、测试 |
