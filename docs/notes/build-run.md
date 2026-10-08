# 编译 / 启动 / 安装依赖命令

> 日期：2026-09-24
> 管理工具：`uv 0.12.8`
> 入口脚本：`main.py`

本项目使用 `uv` 管理依赖与运行环境。Python 是解释型语言，没有传统意义上的「编译」步骤，下文按工作流列出从「拉代码」到「跑起来」所需的全部命令。

---

## 1. 安装依赖

> 适用场景：刚 `git clone` 下来、或者 `pyproject.toml` / `uv.lock` 发生了变化。

```bash
# 同步 lock 文件与虚拟环境（推荐）
uv sync

# 仅当只想用 lock 文件、不愿重新解析时
uv sync --frozen
```

执行后 `uv` 会：

- 比对 `pyproject.toml` 与 `uv.lock`
- 在 `.venv/` 中安装（或更新）所有声明的依赖
- 自动下载缺失的 Python 解释器（如果锁文件指定的版本未安装）

**新增依赖**（会修改 `pyproject.toml` 并自动重新锁定）：

```bash
# 添加运行时依赖
uv add deepagents
uv add "requests>=2.31"

# 添加开发依赖（写入 [dependency-groups] dev）
uv add --dev pytest ruff

# 移除依赖
uv remove requests
```

**手动更新 lock 文件**（一般在 CI 或多人协作时）：

```bash
# 重新解析并更新 uv.lock
uv lock

# 把 lock 文件回写到 pyproject.toml 中的版本约束
uv lock --upgrade
```

---

## 2. 启动 / 运行项目

> 当前入口：`main.py`（PyCharm 自带模板，未替换）。

```bash
# 方式 A：使用 uv run（推荐，会自动激活虚拟环境）
uv run python main.py

# 方式 B：先激活虚拟环境再执行
.venv\Scripts\activate      # Windows PowerShell / CMD
# source .venv/bin/activate # Git Bash / Linux / macOS
python main.py
```

> 注意：uv 已经把所有依赖装到 `.venv/`，**不要**直接用系统 `python` 运行，否则会找不到 `deepagents` 等包。

### 传入参数

```bash
# 向脚本传参
uv run python main.py --name "Astra"

# 或者通过模块方式运行（如果有 src 布局）
uv run -m astraagent.cli
```

---

## 3. 「编译」相关（Python 视角）

Python 没有显式编译步骤，但有以下「产物化」动作：

| 动作 | 命令 | 用途 |
|------|------|------|
| 字节码缓存 | `python -m compileall src` | 生成 `__pycache__/*.pyc`，分发前可加速冷启动 |
| 类型检查 | `uvx mypy src` | 静态类型检查（需先 `uv add --dev mypy`） |
| 代码检查 | `uvx ruff check .` | Lint |
| 代码格式化 | `uvx ruff format .` | 自动格式化 |
| 打包 wheel | `uv build` | 生成 `dist/*.whl` 与 `*.tar.gz`（需 `uv add --dev hatchling` 或 `setuptools`） |
| 安装为可编辑包 | `uv pip install -e .` | 把项目本身装到虚拟环境，便于 `import astraagent` |

> 当前项目尚未进入开发阶段，上述命令先记录备查。

---

## 4. 环境变量加载

`pyproject.toml` 中已经声明了 `dotenv` 和 `load-dotenv`，说明项目会从 `.env` 文件读取配置。

```bash
# 推荐用法（dotenv 库）
uv run python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('OPENAI_API_KEY'))"
```

> `.env` 文件应加入 `.gitignore`，仓库内只保留 `.env.example` 作为模板。

---

## 5. 一键速查表

```bash
# 安装/同步依赖
uv sync

# 跑项目
uv run python main.py

# 加新依赖
uv add <pkg>

# 更新所有依赖到最新兼容版本
uv lock --upgrade && uv sync

# 跑测试（待项目接入 pytest 后）
uv run pytest

# 清理虚拟环境重新装
rm -rf .venv && uv sync
```
# API 服务与 IDE 断点调试

在项目根运行 `.\.venv\Scripts\python.exe run_api.py`，或在 IDE 中选择该虚拟环境，
以 `run_api.py` 为脚本启动 Debug。默认监听 `127.0.0.1:8000`；端口冲突时先停止已有后端，
或传入 `--port 8001`（前端代理默认仍指向 8000）。

此入口显式使用 Windows Selector 事件循环，兼容 psycopg；不开 reload 和子进程，
适合长任务，也支持 IDE 断点。需要局域网访问时加 `--host 0.0.0.0`。

`--reload` 只用于短请求开发调试。它会在源码变更时关闭当前服务进程，取消正在执行的
主任务和子任务；后台任务脱离 SSE 连接也无法跨进程重启继续运行。不要为了兼容 PG
而给长任务开启热重载。更新主目录或手动重启前先确认没有活动任务；重启后可检查
已有会话的检查点和产物，再按界面提示恢复，避免重复执行有副作用的工具。

建议断点：`api.main.lifespan` → `core.agent.build_core_agent`（启动）；
`api.routes.chat.chat_stream` → `core.agent.stream_once` →
`core.approvals.WriteApprovalMiddleware.awrap_tool_call` → `core.sandbox.tools.run_python`（请求执行）。

## 用户沙箱生命周期

用户环境按组织与用户绑定，首次使用创建 OpenSandbox，使用结束后进入空闲状态。
`SANDBOX_IDLE_TTL_SECONDS` 后失活（远端 pause），下次 acquire 恢复同一容器；
后端正常关闭时也只失活，不销毁。创建使用 `timeout=None`，不设置远端自动过期时间。
`SANDBOX_MAX_SANDBOXES` 限制活跃环境数，失活环境不计入，但仍占用服务端存储。

`workspace/sandbox-state.sqlite3` 保存服务地址、用户范围、容器 ID 和状态，重启后复用；
这是单进程方案，多 worker / 多主机需共享存储与跨进程互斥。请备份此运行数据库。
`deactivate(scope)` 只挂起，`destroy(scope)` 和原 `terminate(lease)` 保留显式销毁能力。
普通空闲回收不会调用销毁；若显式销毁失败，后台会重试该销毁意图。

旧版未记录归属的容器不会被自动认领；远端丢失的容器会报错并保留记录，
需管理员检查后显式销毁记录才能重建，避免静默替换为一个空环境。

## 会话内文件隔离

同一用户容器内，附件和报表放在 `/workspace/sessions/{thread_id 的 SHA256}/`。
代码通过 OpenSandbox isolation 的 strict profile 执行，只挂载当前工作区且不共享网络；
隔离不可用时直接拒绝，不能退回 `commands.run` 在容器根环境执行模型代码。
固定的服务端目录校验不执行模型代码，检查符号链接不能逃出会话目录。

跨会话访问使用 `import_session_file`，仅允许当前用户的来源会话，经审批将指定文件
复制到当前会话；不会开放来源目录，编辑副本不改变来源文件。来源会话 ID 必须明确。
既有未分会话保存的文件不会自动迁移。

Docker 创建沙箱时传入官方扩展 `bootstrap.execd.isolation=enable`，由 OpenSandbox
配置 bwrap 所需的 SYS_ADMIN、AppArmor/seccomp 与 tmpfs；不需要全局开启 privileged。
仅挂起/恢复旧容器不会改变它创建时的权限，已有用户环境须保留文件后安排迁移。
strict 默认只读挂载容器根目录，因此额外遮蔽整个 `/workspace` 后仅挂回当前会话。

2026-10-03 本机 Docker 实测修复：execd v1.1.0 的 native workload gate EOF
源于 bwrap 配置私有 loopback 的 RTM_NEWADDR 返回 EPERM，而非 gate 本身损坏。
官方扩展只加 SYS_ADMIN，缺少 NET_ADMIN。本机已在用户授权后修复
`E:/docker_data/OpenSandbox/.venv/Lib/site-packages/opensandbox_server/services/docker/docker_service.py`
的隔离扩展分支：cap_add 添加 SYS_ADMIN / NET_ADMIN，并从 cap_drop 移除这两项。
原文件备份为同目录 `docker_service.py.astra-isolation-backup`，控制服务已重启。
升级 OpenSandbox 会覆盖 site-packages 热修复，升级后须检查该问题是否已由官方修复。

模型代码通过 setpriv 以 UID/GID 1000 执行，SDK 写入文件在执行前只对当前会话目录
移交所有权，不跟随符号链接；命令显式切换到当前会话工作目录。遮蔽挂载源位于
execd 白名单内 `/workspace/.session-masks/`，挂载后自身不可见。
真实验证通过：代码执行、连续执行保留文件、其他会话不可见、符号链接不能跨会话读取、
外部网络不可达。不可用时仍保持失败关闭。

本机已登记用户环境完成保留数据迁移：先停止 API 避免并发写入，备份绑定 SQLite，
挂起旧容器并 docker commit 成保留镜像，再由 OpenSandbox 使用隔离扩展创建替代环境。
核对 `/workspace` 文件哈希、验证隔离执行后才切换绑定并重启 API。
旧容器仍挂起保留，迁移记录写入 `sandbox_migrations`，绑定备份为
`workspace/sandbox-state.before-isolation-migration.sqlite3`；两者不进入 Git。
实际用户现有会话的 `get_sandbox_environment` 工具已通过真实验证，未向会话追加测试消息。

## 会话文件面板

对话中优先提供可点击文件链接：`get_sandbox_file_link` 校验当前会话文件存在后，
返回 Markdown 文件名预览链接和下载链接；报表回执也提供沙箱链接。
前端拦截此类链接，携带当前用户身份读取文件并打开预览，不直接跳转到容器路径。
旧消息中的完整会话文件路径显示为可点击文件卡片，且校验目录哈希与当前会话一致。
文件面板默认收起，作为可选管理入口；预览窗口下载同样回读沙箱最新文件。

聊天页面右上角“文件”可开关右侧面板，浏览当前会话目录和子目录。
支持上传、新建文件夹、重命名、确认删除、预览及下载；生成/编辑结束后自动刷新。
Excel、PDF、图片、常见文本可预览；Word 展示正文文本，完整排版下载原文查看。
单文件上传/下载上限为 20 MiB，不覆盖同名上传，下载直接读取沙箱当前内容且不缓存。

接口位于 `/api/v1/threads/{thread_id}/sandbox`：`GET /files` 列目录，
`GET /content` 预览/下载，`GET /preview` 抽取 Word 正文，`POST /files` 上传，
`POST /directories` 新建目录，`PATCH /files` 重命名，`DELETE /files` 删除。
路径为当前会话内相对路径；根目录不可删除/重命名，符号链接不能引向其他会话。
文件面板与模型代码通过用户沙箱租约串行执行，短暂占用时排队，超时返回 409。
身份沿用当前开发期请求头，接入正式鉴权前不能作为生产安全边界。
# 会话内补充问题

缺少关键需求时，Agent 使用 `ask_user` 展示问题卡片，支持自由输入和最多四个建议选项。
选项不默认选中，提交回答后恢复当前工具调用，回答随工具结果进入当前会话上下文。
问题按用户、组织和会话校验归属；普通回答不会批准写操作，审批参数默认折叠。
审批与提问使用 LangGraph `interrupt` 保存检查点并结束本轮请求，不用协程等待用户。
前端进入会话时读取 `/threads/{id}/interactions`；处理后经 `/threads/{id}/resume`
传入断点响应，继续原任务，不追加或重复发送用户消息。挂起事项不再按 5/10 分钟过期。
同批多项确认分步保存在 `workspace/human-decisions.sqlite3`，全部处理后恢复；
若已保存回答但网络中断，卡片会提供“继续任务”，恢复时仍验证原断点与参数摘要。
启用 Postgres checkpointer 时重启后可恢复；内存 checkpointer 仅支持当前进程内恢复。
当前按单 API 进程部署，线程互斥不跨 worker；多 worker 需共享回答存储和分布式执行锁。
# LangSmith 调用追踪

项目已使用 LangChain 原生追踪，无需改写 Agent 或模型调用。
在项目根 `.env` 中自行配置：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=你的密钥
LANGSMITH_PROJECT=astra-agent
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

密钥从 LangSmith 的 Settings 获取，不要提交 `.env`。
EU 等区域需使用账户对应的 API endpoint，多工作区密钥可额外设置
`LANGSMITH_WORKSPACE_ID`。开启追踪会上传模型和工具调用输入输出。

配置后重启后端并发送一条消息，在 LangSmith 的 `astra-agent` 项目中查看
模型调用、工具执行、子智能体、耗时和错误。挂起恢复后的执行可能显示为新的
trace，可按 `thread_id` 关联会话。未配置密钥时保持 `LANGSMITH_TRACING=false`；
显式开启但缺少密钥时启动配置校验会报错。

官方说明：https://docs.langchain.com/langsmith/trace-with-langchain
