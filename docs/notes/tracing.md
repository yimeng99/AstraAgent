# Agent 调用链追踪（Langfuse）

## 本地启动

```powershell
# 随机生成本地部署密码、项目 API key；重复运行保留已有凭证。
.\.venv\Scripts\python.exe deploy/tracing/init.py
docker compose -f deploy/tracing/compose.yaml up -d
# 服务健康后，将本地项目 key 和追踪配置写入根目录 .env。
.\.venv\Scripts\python.exe deploy/tracing/init.py --activate
.\.venv\Scripts\python.exe run_api.py
```

访问 http://localhost:3100，使用 `admin@astra.local` 登录。
密码为 `deploy/tracing/.env` 中的 `ADMIN_PASSWORD`，项目为 `astra-agent`。
该文件已忽略，包含部署和 API 凭证，不要提交或粘贴到日志。
首次启动会创建管理员和项目；修改初始化变量不会重置数据库中已有账号。

后端通过官方 OTLP HTTP 接口上传，沿用现有 OTel/OpenInference 插桩，
无需再安装另一套 LangChain callback。出口使用项目 API key 的 Basic Auth，
并携带 v4 实时摄入头。Docker 内运行后端时需将 endpoint 改为可达的服务地址。

## 如何查找

- Tracing 中将 `Is Root Observation` 设为 `True`，每次对话执行对应一个 `agent.execute` 根节点；点击进入模型、工具和沙箱调用树。
- Sessions 对应应用的 `thread_id`；User ID 对应实际运行上下文用户。
- 模型调用显示为 Generation，模型返回的 Token 用量会被记录。
- `agent.execute` 记录本次 run、状态、恢复标识及首个模型 chunk 耗时。
- 后台 Agent 日志的 `trace_id` 可用于关联排障。
- 审批和提问挂起会结束本次 Trace；恢复生成新 Trace，通过同一 Session 关联。

OpenInference 自动记录 LangGraph 节点、子 Agent、工具、模型。
`sandbox.acquire`、`sandbox.execute`、`skills.sync` 补充沙箱边界；
不再自动采集普通 HTTP 和 SQL，避免会话列表、轮询和检查点写入淹没 Agent 调用。
外部服务未插桩时只看到客户端耗时，不包含容器内每条代码的执行过程。

## 数据边界

`AGENT_TRACING_CAPTURE_CONTENT=false` 默认隐藏输入输出；本地经用户授权可设为 `true`。
开启后记录 Agent 输入/最终输出、模型和工具输入输出，限制大小并过滤凭证字段、已知环境密钥和图片数据。
这些记录仍可能包含业务正文，不能把字段过滤当成完整的数据防泄漏方案。
运行时上下文和任意 metadata 不上传；错误堆栈需结合本地日志查看。
User/Session 标识用于筛选，不等于项目成员之间的数据访问隔离。

`--activate` 会关闭旧的 `LANGSMITH_TRACING`，避免同时发送两份追踪。
采样率 `AGENT_TRACING_SAMPLE_RATE` 为 0～1，默认全量；降低采样率不能保证保留所有错误。
后台批量上报不阻塞业务，队列满、服务故障或进程崩溃可能丢记录，不能替代审批审计。

## 部署与迁移

单机 Compose 包含 Langfuse Web/Worker、Postgres、ClickHouse、Redis、MinIO。
Web 和文件端点仅绑定本机；数据库不映射宿主端口。生产部署还需按实际环境配置
HTTPS、账号权限、备份、保留策略、资源监控与高可用，不能直接当作生产集群。
自部署会消耗本机存储和计算资源。

数据保存在 `astra-langfuse_*` Docker 卷；`down` 保留数据，`down -v` 会删除。

参考：[官方 OTLP 接入](https://langfuse.com/integrations/native/opentelemetry)、
[官方无界面初始化](https://langfuse.com/self-hosting/administration/headless-initialization)。
