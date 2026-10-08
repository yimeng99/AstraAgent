# LiteLLM 模型网关

网关独立于 Agent 运行。当前只接入现有 MiniMax 渠道，**尚未启用备用渠道**。
部署不会修改项目根目录 `.env`，也不会重启聊天服务。

## 启动

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe deploy/litellm/init.py
docker compose -f deploy/litellm/compose.yaml up -d
docker compose -f deploy/litellm/compose.yaml ps
docker compose -f deploy/litellm/compose.yaml logs -f --tail 100 gateway
```

首次初始化从项目 `.env` 复制 OpenAI 兼容模型地址、模型名和密钥；重复执行保留原值。
换渠道时修改 `deploy/litellm/.env`，再执行 `up -d --force-recreate gateway`。
网关镜像固定 digest；升级时显式更新镜像并重新联调。

- 控制台：http://127.0.0.1:4000/ui
- 登录名：`admin`，密码见 `deploy/litellm/.env` 的 `UI_PASSWORD`。
- 模型 API：http://127.0.0.1:4000/v1，模型别名 `agent-main`。
- 存活检查：`/health/liveliness`；就绪检查：`/health/readiness`。
- `/health` 会实际调用上游，可能产生费用；容器探针只使用 readiness。

网关凭证只保存在被 Git 忽略的 `deploy/litellm/.env`。
数据库使用独立 Docker volume，未对宿主机开放端口。`down` 保留数据，
`down -v` 会删除数据，不要用于常规重启。已有数据库的密码和盐不能随意重新生成。

## 应用接入

先在控制台创建仅允许 `agent-main` 的应用虚拟密钥，再修改项目 `.env`：

```dotenv
LLM_PROVIDER=litellm
LLM_BASE_URL=http://127.0.0.1:4000/v1
LLM_MODEL=agent-main
LLM_API_KEY=<应用虚拟密钥，不使用管理密钥>
LLM_TIMEOUT_SECONDS=420
LLM_MAX_RETRIES=0
LLM_VISION=1
```

确认没有执行中的任务后重启后端。应用关闭自动重试，网关统一处理一次重试；
网关每次上游超时 180 秒，应用等待预算需覆盖重试和排队。
添加备用后应重新计算总预算，不能无限重试或排队。
回退直连时恢复原 LLM 配置并重启后端。

项目依赖模型名称判断图片能力，因此当前 MiniMax-M3 渠道显式设置 `LLM_VISION=1`。
更换渠道或加入备用时，必须确认所有渠道支持图片，否则应关闭此配置。
正式切换前应联调普通输出、SSE、思考字段、工具调用、图片附件和中断恢复，
不能仅凭网关健康检查判断业务完全兼容。

本机已创建 `commonagent-backend` 应用密钥，仅允许访问 `agent-main`。
密钥保存在网关 `.env` 的 `APP_API_KEY`，项目 `.env` 的 `LLM_API_KEY` 引用同一值。
直连配置保存在网关 `.env` 的 `DIRECT_LLM_*` 字段，回滚时恢复对应字段后重启后端。

## 备用渠道

模型选择器使用当前应用密钥的 `/v1/models` 和 `/v1/model/info`，按供应商分组。
在每个部署的 `model_info` 中设置 `provider`（例如 `MiniMax`）和
`display_name`（例如 `MiniMax-M3`）。这是项目用于展示的元数据，模型 ID
仍使用网关的 `model_name`。未标注时使用 `litellm_provider`，但 OpenAI 兼容渠道
可能只显示协议适配器 `openai`，因此应显式标注实际供应商。
同一供应商下相同模型别名的多个部署去重；只有当前密钥有权访问的别名才会展示。

1. 在网关 `.env` 填入 `BACKUP_MODEL`、`BACKUP_API_BASE`、`BACKUP_API_KEY`。
   OpenAI 兼容渠道的模型值写成 `openai/实际模型名称`。
2. 取消 `config.yaml` 中 `agent-backup` 和 `fallbacks` 的注释。
3. 重建 gateway 容器，分别验证主备工具调用及流式输出，再模拟主渠道故障验证切换。

备用渠道应有独立配额；未配置前网关不会凭空提供备用容量。
故障切换不等于恢复 Agent 任务，已输出内容或执行过工具的请求不能盲目整轮重放。

## 生产边界

此配置是本机单实例部署，仅绑定 127.0.0.1。生产需通过受控网络和 TLS 访问，
为应用分发虚拟密钥，备份数据库和加密盐，并按渠道真实配额设置 RPM/TPM。
应用侧仍需限制运行任务数与排队长度。多网关实例需要共享限流状态（Redis），
配置负载均衡和数据库高可用后才能提供网关层面的冗余。
默认不启用详细请求调试日志，Docker 日志限制为每服务 3 × 10 MB。

参考：[配置](https://docs.litellm.ai/docs/proxy/configs)、
[故障切换](https://docs.litellm.ai/docs/proxy/reliability)、
[部署](https://docs.litellm.ai/docs/proxy/docker_quick_start)。
