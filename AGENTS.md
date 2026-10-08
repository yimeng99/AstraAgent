# AGENTS.md —— 给 AI 协作者的项目说明

> 本文件是**所有 AI 工具（DeepSeek Harness / Claude Code / Cursor …）的入口**，请先读完再动手。
> 项目规范细节在 [`docs/`](docs/README.md)；本文件只写"必须知道"的部分。

## 1. 这是什么

AstraAgent：企业知识库 + 多 LLM provider + 子智能体派发的智能体框架（Python 3.13 / FastAPI / LangGraph + deepagents），
带一个 Vue 3 + Vite + Element Plus 的聊天前端。

| 层 | 位置 |
|---|---|
| 智能体编排 | `src/core/`（agent / llm / prompts / subagent / skills） |
| Web API | `src/api/`（chat SSE / threads / upload / history） |
| 业务接入 | `src/business/`（每个子包 = 一个业务系统，见 [business-plugins](docs/design/business-plugins.md)） |
| 基础设施 | `src/core/storage.py`（本地/OSS）、`checkpointer.py`（对话历史）、`backend.py`（长期记忆 store）、`mcp/`、`sandbox/` |
| 文档能力 | `src/core/documents.py`（Word/Excel/PDF 抽文本）、`reports.py` + `report_tools.py`（生成报表） |
| 前端 | `frontend/`（Vue 3 + Vite + Element Plus + TS，`/api` 代理到 :8000） |

## 2. 常用命令

```powershell
# 后端（长任务使用此入口：显式 Selector，不随源码改动重启）
.\.venv\Scripts\python.exe run_api.py --host 0.0.0.0 --port 8000

# 前端（另开一个终端）
cd frontend; pnpm dev            # http://localhost:5173

# 仅调试短请求时启用热重载；改源码会取消正在执行的任务
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir src

# 测试 / 静态检查
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format src tests

# 配置自检 / MCP 连通性自检
.\.venv\Scripts\python.exe -m core check
.\.venv\Scripts\python.exe -m core.mcp
```

前端构建时把临时目录指到工作区（esbuild 在系统 TEMP 里删临时文件会失败）：

```powershell
$env:TEMP="$PWD\.cache\tmp"; $env:TMP=$env:TEMP; cd frontend; pnpm build
```

## 3. 硬规矩（AI 协作者必读）

1. **临时文件一律放 `.cache/`**，不要写进 `src/`、仓库根或 `docs/`。
   ```text
   .cache/tmp/     一次性脚本、探针
   .cache/verify/  截图、对比图、验证输出
   .cache/logs/    运行日志
   ```
   `.cache/` 已 gitignore（只放行它的 README），**交付前清理**不再需要的产物。
2. **改文本文件用编辑工具，别用 PowerShell 的 `Get-Content`/`Set-Content` 往返** ——
   UTF-8 会被按 GBK 误读，中文变乱码甚至整行粘连（本项目已因此损坏过
   `frontend/src/useThreads.ts` 与 `.env`，后者直接导致服务起不来）。
3. **运行数据不入库**：`workspace/uploads/`（用户上传）、`.env`、`.cache/`、
   `frontend/dist/`、`__pycache__/`。新增忽略规则请同步更新 `.gitignore`。
4. **注释写"为什么"，不复述代码**：踩坑记录、反直觉之处、与外部系统的契约必须留；
   `Args:`/`Returns:` 这类只重复类型签名的样板可以不留（详细口径见 §5）。
5. **改完必须验证**（不能只跑单测）：
   ```powershell
   pytest -q                       # 全量测试
   ruff check src tests            # lint
   cd frontend; pnpm build         # 前端 tsc + 构建（改了前端才需要）
   ```
   涉及接口、启动顺序、第三方集成（Postgres / MCP / 沙箱）的改动，**必须起真实服务跑一遍** ——
   单测覆盖不到 pydantic 运行时注解、lifespan 顺序、事件循环类型这类问题（都踩过）。
6. **提交信息**遵循 [`docs/rules/commit-conventions.md`](docs/rules/commit-conventions.md)：
   `<type>(<scope>): 中文标题`，正文写"为什么"。

## 4. 环境陷阱（Windows / 运行期）

| 陷阱 | 说明 |
|---|---|
| **Windows 事件循环** | 长任务使用 `run_api.py`，它显式选择 psycopg 所需的 `SelectorEventLoop`。不要把 `--reload` 当作 PG 兼容开关：源码改动会重启进程并取消所有活动任务。同步主目录代码或重启前，先确认没有活动任务 |
| **相对路径按项目根解析** | `STORAGE_LOCAL_ROOT` / `AGENT_WORKSPACE` 的相对路径锚定在 `PROJECT_ROOT`（见 `core/config.py`），不是当前工作目录 |
| **PG 配置** | Web API 的 `POSTGRES_URL` 同时用于执行租约和运行记录，初始化失败会中止启动；CLI 历史和长期记忆 `POSTGRES_STORE_URL` 仍可使用内存模式 |
| **Excel 预览** | 必须自己 `import "@js-preview/excel/lib/index.css"`，否则画布只算两行高（`FilePreview.tsx` 有注释） |
| **Postgres 资源生命周期** | checkpointer / store 都是"context manager 必须保活"的形态，别把 CM 丢掉（`connection is closed` 的根源） |

## 5. 项目约定速览

- **注释**：写动机与坑，不写"这行在做什么"。踩坑注释（IME 回车、Excel 预览 CSS、
  anyio 异常剥壳、Postgres CM 生命周期…）**不许删**。
- **配置**：新增环境变量要同时更新 `.env.example`，并在 `core/config.py` 里做校验；
  写错的变量名会静默失效（踩过：`SANDBOX_MAX_SANDBOXES` 拼错）。
- **失败隔离**：MCP 服务、沙箱、业务子包都是**可选能力** —— 连不上只丢它自己，日志说清原因，不拖垮启动。
- **内部契约**：入口校验外部数据后，内部直接使用明确类型；不要逐层 `getattr`、空值兜底或吞掉程序错误。执行职责与锁交接见 [agent-execution](docs/design/agent-execution.md)。
- **安全**：MCP/外部工具返回的是**不可信输入**（防提示注入）；写操作需用户确认；
  `X-User-Id` 头目前可伪造，接真实鉴权前不能当作授权依据。

## 6. 文档导航

| 想看什么 | 文件 |
|---|---|
| 文档总索引 | [`docs/README.md`](docs/README.md) |
| 命名 / 注释 / 日志规范 | [`docs/design/coding-style.md`](docs/design/coding-style.md) |
| 目录布局 | [`docs/design/project-layout.md`](docs/design/project-layout.md) |
| 架构设计 | [`docs/design/architecture.md`](docs/design/architecture.md) |
| 数据模型 / 字段命名 | [`docs/design/data-modeling.md`](docs/design/data-modeling.md) |
| 业务系统接入 | [`docs/design/business-plugins.md`](docs/design/business-plugins.md) |
| 提交规范 | [`docs/rules/commit-conventions.md`](docs/rules/commit-conventions.md) |
| 启动 / 构建 / 依赖 | [`docs/notes/build-run.md`](docs/notes/build-run.md) |
| LLM provider | [`docs/notes/llm-providers.md`](docs/notes/llm-providers.md) |
